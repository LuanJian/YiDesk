<template>
  <div>
    <el-card shadow="never" class="filter-card">
      <div class="filters">
        <el-select v-model="kind" placeholder="全部类型" clearable style="width: 140px" @change="onKindChange">
          <el-option v-for="(label, k) in KINDS" :key="k" :label="label" :value="k" />
        </el-select>
        <!-- 第三十九批：按默认分类筛选（选项=现有标签分类去重聚合） -->
        <el-select v-model="category" placeholder="全部默认分类" clearable filterable style="width: 140px" @change="load">
          <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
        <div style="flex: 1"></div>
        <el-button type="primary" plain @click="openEditor(null)">
          <el-icon style="margin-right: 4px"><Plus /></el-icon>生成二维码
        </el-button>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table :data="pagedTags" v-loading="loading" stripe>
        <!-- 第四十二批：状态/类型前置，按 状态/类型/短码/名称/绑定信息/操作 排列 -->
        <el-table-column label="状态" min-width="85">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="类型" min-width="110">
          <template #default="{ row }">
            <el-tag :type="kindTag[row.kind]" size="small">{{ row.kind_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="短码" min-width="95" show-overflow-tooltip class-name="col-sm-hide" />
        <el-table-column prop="name" label="名称" min-width="240" show-overflow-tooltip />
        <el-table-column label="绑定信息" min-width="260" show-overflow-tooltip class-name="col-sm-hide">
          <template #default="{ row }">
            <span class="bnd" v-if="row.kind === 'location'"><el-icon style="vertical-align: -2px"><Location /></el-icon> {{ row.location || '-' }}</span>
            <span class="bnd" v-else-if="row.kind === 'device'">
              <el-icon style="vertical-align: -2px"><Monitor /></el-icon>
              {{ row.asset ? `${row.asset.asset_tag} ${row.asset.name}` : '资产已删除' }}
              <template v-if="row.asset?.ip_address">（IP {{ row.asset.ip_address }}）</template>
            </span>
            <span class="bnd" v-else-if="row.kind === 'room'">
              <el-icon style="vertical-align: -2px"><Calendar /></el-icon>
              {{ row.room ? row.room.name : '会议室已删除' }}
              <template v-if="row.room?.location">（{{ row.room.location }}）</template>
            </span>
            <span class="bnd" v-else><el-icon style="vertical-align: -2px"><User /></el-icon> {{ row.engineer ? row.engineer.name : '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="showQr(row)">二维码</el-button>
            <el-button size="small" @click="openEditor(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
        <el-pagination
          v-model:current-page="tagPage"
          :page-size="20"
          :total="items.length"
          layout="total, prev, pager, next"
          style="margin-top: 10px; justify-content: center"
        />
    </el-card>

    <!-- 新建/编辑 -->
    <el-dialog v-model="editorVisible" :title="editorForm.id ? '编辑二维码标签' : '生成二维码标签'" width="520px">
      <el-form label-width="110px">
        <el-form-item label="类型">
          <el-radio-group v-model="editorForm.kind" :disabled="!!editorForm.id">
            <el-radio-button v-for="(label, k) in KINDS" :key="k" :value="k">{{ label }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="editorForm.name" placeholder="如 3 层打印机 / 5 层 B 区工位" />
        </el-form-item>
        <el-form-item v-if="editorForm.kind === 'location' || editorForm.kind === 'assignee'" label="位置">
          <el-input v-model="editorForm.location" placeholder="如 5 层 B 区 12 工位（贴在工位上则填工位号）" />
        </el-form-item>
        <el-form-item v-if="editorForm.kind === 'device'" label="关联资产" required>
          <el-select v-model="editorForm.asset_id" filterable style="width: 100%" placeholder="选择资产（含型号 / IP）">
            <el-option v-for="a in assets" :key="a.id" :label="`${a.asset_tag} ${a.name}${a.model ? ' · ' + a.model : ''}`" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editorForm.kind === 'assignee'" label="指定工程师" required>
          <el-select v-model="editorForm.engineer_id" filterable style="width: 100%" placeholder="扫码提交的工单直接指派给该工程师">
            <el-option v-for="u in engineers" :key="u.id" :label="u.name || u.username" :value="u.id" />
          </el-select>
        </el-form-item>
        <!-- v2.12 会议室码：扫码进入会议室预约页 -->
        <el-form-item v-if="editorForm.kind === 'room'" label="关联会议室" required>
          <el-select v-model="editorForm.room_id" filterable style="width: 100%" placeholder="选择会议室（在「会议管理」中维护）">
            <el-option v-for="r in rooms" :key="r.id" :label="`${r.name}${r.location ? ' · ' + r.location : ''}`" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editorForm.enabled" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editorForm.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 二维码展示 / 打印 -->
    <el-dialog v-model="qrVisible" :title="qrTag ? `二维码 · ${qrTag.name}` : '二维码'" width="380px">
      <div v-if="qrTag" class="qr-box">
        <img v-if="qrDataUrl" :src="qrDataUrl" alt="QR" class="qr-img" />
        <div class="qr-name">{{ qrTag.name }}</div>
        <div class="qr-code">{{ qrTag.code }}</div>
        <div class="qr-url">{{ qrTag.qr_url }}</div>
        <!-- 第四十三批：打印样式可选（默认样式 1） -->
        <el-divider style="margin: 12px 0" />
        <div style="text-align: left">
          <div class="muted" style="margin-bottom: 6px">打印样式</div>
          <el-radio-group v-model="printStyle">
            <el-radio value="1">样式 1：仅二维码</el-radio>
            <el-radio value="2">样式 2：信息卡片</el-radio>
          </el-radio-group>
        </div>
      </div>
      <template #footer>
        <el-button plain @click="exportQrImage"><el-icon style="margin-right: 4px"><Download /></el-icon>导出图片</el-button>
        <el-button @click="qrVisible = false">关闭</el-button>
        <el-button type="primary" @click="printQr">打印贴纸</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { del, get, patch, post } from '@/api/http'
import { getToken } from '@/api/http'

// 第四十二批：下拉按字数少到多排列（位置码/设备码/会议室码/指定派单码）
const KINDS: Record<string, string> = { location: '位置码', device: '设备码', room: '会议室码', assignee: '指定派单码' }
const kindTag: Record<string, string> = { location: 'primary', device: 'warning', assignee: 'danger', room: 'danger' }

const loading = ref(false)
const items = ref<any[]>([])

const tagPage = ref(1)
const pagedTags = computed(() => items.value.slice((tagPage.value - 1) * 20, tagPage.value * 20))
const kind = ref('')
const category = ref('')
const categoryOptions = ref<string[]>([])

// 第四十批：类型变更时清空已选分类，避免「类型+旧分类」组合查空
function onKindChange() {
  category.value = ''
  load()
}
const assets = ref<any[]>([])
const engineers = ref<any[]>([])
const rooms = ref<any[]>([])

const editorVisible = ref(false)
const editorForm = ref<any>({})

const qrVisible = ref(false)
const qrTag = ref<any>(null)
const qrDataUrl = ref('')
// 第四十三批：打印样式（1=仅二维码，默认；2=信息卡片）
const printStyle = ref('1')

onMounted(async () => {
  try {
    const res = await get('/api/assets')
    assets.value = res.items
  } catch { /* ignore */ }
  try {
    const res = await get('/api/users')
    engineers.value = res.items.filter((u: any) => u.role === 'admin' || u.role === 'engineer')
  } catch { /* ignore */ }
  try {
    rooms.value = (await get('/api/meetings/rooms')).items
  } catch { /* 会议管理仅管理员；工程师生成会议室码时若无房间可先让管理员维护 */ }
  await load()
})

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (kind.value) params.set('kind', kind.value)
    if (category.value) params.set('category', category.value)
    const res = await get(`/api/qr-tags?${params}`)
    items.value = res.items
    if (res.categories?.length) categoryOptions.value = res.categories
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function openEditor(row: any) {
  editorForm.value = row
    ? { ...row }
    : { id: null, name: '', kind: 'location', location: '', asset_id: null, engineer_id: null, room_id: null, enabled: true, note: '' }
  editorVisible.value = true
}

async function save() {
  const f = editorForm.value
  if (!f.name.trim()) return ElMessage.warning('请填写名称')
  if (f.kind === 'device' && !f.asset_id) return ElMessage.warning('设备码必须关联资产')
  if (f.kind === 'assignee' && !f.engineer_id) return ElMessage.warning('指定派单码必须选择工程师')
  if (f.kind === 'room' && !f.room_id) return ElMessage.warning('会议室码必须选择会议室')
  try {
    if (f.id) await patch(`/api/qr-tags/${f.id}`, f)
    else await post('/api/qr-tags', f)
    ElMessage.success('已保存')
    editorVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(
    `确认删除标签「${row.name}」？删除后已贴出的二维码扫码将失效（无法建单）。`,
    '删除确认', { type: 'warning' },
  )
  try {
    await del(`/api/qr-tags/${row.id}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function showQr(row: any) {
  qrTag.value = row
  qrDataUrl.value = ''
  printStyle.value = '1'
  qrVisible.value = true
  try {
    // PNG 接口走 Authorization 头，手动 fetch 转 objectURL
    const resp = await fetch(`/api/qr-tags/${row.id}/qr.png`, { headers: { Authorization: `Bearer ${getToken()}` } })
    if (!resp.ok) throw new Error('二维码生成失败')
    const blob = await resp.blob()
    qrDataUrl.value = URL.createObjectURL(blob)
  } catch (e: any) {
    ElMessage.error(e.message || '二维码生成失败')
  }
}

// 第四十五批：打印窗口 HTML 插值转义（名称/绑定信息含 <script> 等字符时防注入打印页）
function escapeHtml(v: unknown): string {
  return String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))
}

// 第四十三批：绑定信息文本（与表格列渲染一致，供打印卡片使用）
function bindText(row: any): string {
  if (row.kind === 'location') return row.location || '-'
  if (row.kind === 'device') return row.asset ? `${row.asset.asset_tag} ${row.asset.name}` : '资产已删除'
  if (row.kind === 'room') return row.room ? row.room.name : '会议室已删除'
  return row.engineer ? row.engineer.name : '-'
}

// 第四十三批续：导出二维码图片（PNG 下载，方便自行调整）
function exportQrImage() {
  if (!qrDataUrl.value || !qrTag.value) return
  const a = document.createElement('a')
  a.href = qrDataUrl.value
  a.download = `二维码_${qrTag.value.code}.png`
  a.click()
}

function printQr() {
  if (!qrTag.value || !qrDataUrl.value) return
  const w = window.open('', '_blank', 'width=420,height=560')
  if (!w) return ElMessage.warning('浏览器拦截了打印窗口，请允许弹窗')
  if (printStyle.value === '2') {
    // 样式 2：长方形信息卡片——左侧二维码，右侧 类型/短码/名称（第四十三批续排序调整）；预览含标题名称，文案居中
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(qrTag.value.name)}</title>
    <style>body{font-family:sans-serif;margin:0;padding:24px;text-align:center}
    .card{display:flex;align-items:center;gap:16px;border:2px solid #1d2535;border-radius:10px;padding:16px;width:380px;margin:0 auto;text-align:left}
    img{width:130px;height:130px;flex-shrink:0}
    .info{text-align:left}
    .kind{display:inline-block;border:1px solid #999;border-radius:4px;padding:2px 8px;font-size:12px;color:#555;margin-bottom:6px}
    .code{font-family:Menlo,Consolas,monospace;font-size:15px;font-weight:700;margin-bottom:6px}
    .name{font-size:14px;color:#333;line-height:1.5;word-break:break-all}
    .tip{font-size:11px;color:#999;margin-top:10px}</style>
    </head><body>
    <div class="card">
    <img src="${qrDataUrl.value}"/>
    <div class="info">
      <div class="kind">${escapeHtml(qrTag.value.kind_label)}</div>
      <div class="code">${escapeHtml(qrTag.value.code)}</div>
      <div class="name">${escapeHtml(qrTag.value.name)}</div>
    </div>
    </div>
    <div class="tip">扫码提交工单 · 绑定：${escapeHtml(bindText(qrTag.value))}</div>
    <script>window.onload=function(){window.print()}<\/script></body></html>`)
    w.document.close()
    return
  }
  // 样式 1（默认）：二维码 + 标题名称，文案居中
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(qrTag.value.name)}</title>
    <style>body{font-family:sans-serif;text-align:center;padding:24px}
    img{width:280px;height:280px}
    .n{font-size:18px;font-weight:600;margin:14px 0 6px}
    .k{display:inline-block;border:1px solid #999;border-radius:4px;padding:2px 10px;font-size:12px;color:#555}
    .c{color:#666;font-size:13px;margin-top:8px;font-family:Menlo,Consolas,monospace}
    .u{color:#999;font-size:11px;margin-top:6px;word-break:break-all}</style>
    </head><body>
    <img src="${qrDataUrl.value}"/>
    <div class="n">${escapeHtml(qrTag.value.name)}</div>
    <div class="k">${escapeHtml(qrTag.value.kind_label)}</div>
    <div class="c">${escapeHtml(qrTag.value.code)}</div>
    <div class="u">${escapeHtml(qrTag.value.qr_url)}</div>
    <script>window.onload=function(){window.print()}<\/script></body></html>`)
  w.document.close()
}
</script>

<style scoped>
.filter-card { margin-bottom: 14px; }
.filters { display: flex; gap: 10px; align-items: center; }
.qr-box { text-align: center; padding: 6px 0; }
.qr-img { width: 260px; height: 260px; }
.qr-name { font-weight: 600; font-size: 15px; margin-top: 10px; }
.qr-code { color: #5a6478; font-size: 13px; margin-top: 2px; }
.qr-url { color: #8a93a6; font-size: 12px; margin-top: 4px; white-space: nowrap; overflow-x: auto; }
/* 第四十一批：绑定信息列不换行（内容超宽时截断+tooltip） */
.bnd { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: inline-block; max-width: 100%; }
</style>
