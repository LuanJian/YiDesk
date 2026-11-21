<template>
  <div>
    <!-- 顶部统计卡：与网络设备页签一致（基于当前页签范围统计，随筛选联动） -->
    <el-row :gutter="14">
      <el-col :span="6" v-for="c in statCards" :key="c.label">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value" :style="{ color: c.color }">{{ c.value }}</div>
          <div class="stat-label">{{ c.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="filter-card">
      <div class="filters">
        <!-- 第四十一批：搜索范围扩展至 编号/名称/位置/品牌/型号（占位符同步） -->
        <el-input v-model="q" placeholder="搜索编号/名称/品牌/型号/位置" clearable style="width: 240px" @keyup.enter="load" @clear="load" />
        <el-select v-model="typeFilter" placeholder="类型" clearable filterable style="width: 140px" @change="load">
          <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
        </el-select>
        <el-select v-model="status" placeholder="状态" clearable style="width: 140px" @change="load">
          <el-option v-for="s in statuses" :key="s" :label="s" :value="s" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
        <div style="flex: 1"></div>
        <el-button v-if="auth.can('assets.write')" type="primary" plain @click="openEditor(null)">
          <el-icon style="margin-right: 4px"><Plus /></el-icon>登记资产
        </el-button>
      </div>
    </el-card>

    <el-card shadow="never">
      <!-- 第四十二批：状态列第一列；共同列前置（编号/名称/类型/品牌/型号/最近检测/位置/IP/保修到期日/备注），特有列（在线/使用人）置后 -->
      <el-table :data="pagedItems" v-loading="loading" stripe>
        <el-table-column label="状态" min-width="85">
          <template #default="{ row }">
            <el-tag :type="({ 在用: 'success', 维修中: 'warning', 闲置: 'info', 报废: 'danger' } as any)[row.status]" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="asset_tag" label="资产编号" min-width="150" show-overflow-tooltip />
        <el-table-column prop="name" label="名称" min-width="190" show-overflow-tooltip />
        <el-table-column prop="category" label="类型" min-width="90" show-overflow-tooltip />
        <el-table-column label="品牌" min-width="100">
          <template #default="{ row }">{{ row.vendor || '-' }}</template>
        </el-table-column>
        <el-table-column prop="model" label="型号" min-width="130" show-overflow-tooltip class-name="col-sm-hide" />
        <el-table-column label="最近检测" min-width="170">
          <template #default="{ row }">
            <span v-if="row.last_checked_at" class="nowrap">{{ fmtTime(row.last_checked_at) }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="location" label="位置" min-width="120" show-overflow-tooltip />
        <el-table-column prop="ip_address" label="IP 地址" min-width="130" show-overflow-tooltip class-name="col-sm-hide" />
        <!-- 第三十八批：保修到期日（30 天内临期/已过期红标）；第四十二批：标签改「保修到期日」并前置备注列 -->
        <el-table-column label="保修到期日" width="115">
          <template #default="{ row }">
            <span v-if="row.expire_date" :style="{ whiteSpace: 'nowrap', ...expireStyle(row.expire_date) }">{{ row.expire_date }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="140" show-overflow-tooltip />
        <!-- 特有列置后：在线检测 / 使用人 -->
        <el-table-column label="在线" width="100">
          <template #default="{ row }">
            <template v-if="row._online === undefined">
              <el-button v-if="row.ip_address" size="small" text type="primary" :loading="detectingId === row.id" @click="detect(row)">检测</el-button>
              <span v-else class="muted">-</span>
            </template>
            <template v-else>
              <el-tag :type="row._online ? 'success' : 'danger'" size="small">{{ row._online ? '在线' : '离线' }}</el-tag>
              <el-button size="small" text type="primary" style="margin-left: 4px" :loading="detectingId === row.id" @click="detect(row)">重测</el-button>
            </template>
          </template>
        </el-table-column>
        <el-table-column label="使用人" min-width="100">
          <template #default="{ row }"><span style="white-space: nowrap">{{ row.owner?.name || '-' }}</span></template>
        </el-table-column>
        <el-table-column v-if="auth.can('assets.write')" label="操作" width="290" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEditor(row)">编辑</el-button>
            <el-button size="small" type="info" plain @click="showHistory(row)">历史</el-button>
            <el-button size="small" type="warning" plain @click="recover(row)">回收</el-button>
            <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
        <el-pagination
          v-model:current-page="assetPage"
          :page-size="20"
          :total="items.length"
          layout="total, prev, pager, next"
          style="margin-top: 10px; justify-content: center"
        />
    </el-card>

    <el-dialog v-model="editorVisible" :title="editorForm.id ? '编辑资产' : '登记资产'" width="560px">
      <el-form label-width="80px">
        <el-form-item label="资产编号" required>
          <el-input v-model="editorForm.asset_tag" placeholder="如 PC-0001" />
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="editorForm.name" />
        </el-form-item>
        <el-form-item label="类型">
          <!-- 固定选项不开放自定义：自定义类型会导致设备从页签过滤中消失 -->
          <el-select v-model="editorForm.category" style="width: 100%">
            <el-option v-for="c in (props.onlyCategories?.length ? props.onlyCategories : TYPE_OPTIONS)" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editorForm.status" style="width: 100%">
            <el-option v-for="s in statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="位置">
          <el-input v-model="editorForm.location" placeholder="如 3F-301" />
        </el-form-item>
        <el-form-item label="IP 地址">
          <el-input v-model="editorForm.ip_address" placeholder="如 192.168.1.66（打印/网络设备填）" />
        </el-form-item>
        <el-form-item label="品牌">
          <el-input v-model="editorForm.vendor" placeholder="如 惠普 / 联想 / 华为（品牌与型号分列填写）" />
        </el-form-item>
        <el-form-item label="型号">
          <el-input v-model="editorForm.model" placeholder="如 LaserJet P1108（不含品牌名）" />
        </el-form-item>
        <el-form-item label="使用人">
          <el-select v-model="editorForm.owner_id" clearable filterable style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="u.name || u.username" :value="u.id" />
          </el-select>
        </el-form-item>
        <!-- 第三十八批：到期日期（维保/租期），临期 30 天内自动提醒管理员 -->
        <el-form-item label="到期日期">
          <el-date-picker
            v-model="editorForm.expire_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="维保/租期到期日（选填）"
            style="width: 100%"
          />
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

    <!-- 生命周期历史（v2.7） -->
    <el-drawer v-model="histVisible" :title="`生命周期 · ${histAsset?.asset_tag || ''} ${histAsset?.name || ''}`" size="420px">
      <div class="hist-actions">
        <el-dropdown trigger="click" @command="doAction">
          <el-button type="primary" plain size="small">执行操作</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="assign">领用</el-dropdown-item>
              <el-dropdown-item command="return">归还</el-dropdown-item>
              <el-dropdown-item command="repair">送修</el-dropdown-item>
              <el-dropdown-item command="repair_done">修复完成</el-dropdown-item>
              <el-dropdown-item command="scrap">报废</el-dropdown-item>
              <el-dropdown-item command="note">备注</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <el-timeline>
        <el-timeline-item v-for="e in histEvents" :key="e.id" :timestamp="new Date(e.created_at).toLocaleString('zh-CN', { hour12: false })">
          <b>{{ e.action_label }}</b>
          <span v-if="e.note" class="muted">（{{ e.note }}）</span>
          <!-- v2.12 维修拆装部件明细（溯源：加装的硬盘/内存等） -->
          <div v-if="e.parts?.length" class="part-list">
            <el-tag
              v-for="(p, pi) in e.parts" :key="pi"
              :type="p.direction === 'add' ? 'success' : 'danger'" size="small" effect="plain"
              style="margin-right: 6px; margin-top: 4px"
            >{{ p.direction === 'add' ? '＋加装' : '－拆卸' }} {{ p.name }}{{ p.sn ? '（SN ' + p.sn + '）' : '' }}</el-tag>
          </div>
          <div class="muted">{{ e.operator }}</div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!histEvents.length" description="暂无操作记录" :image-size="60" />
    </el-drawer>

    <!-- v2.12 维修拆装部件登记弹窗（送修/修复完成时） -->
    <el-dialog v-model="partDialogVisible" :title="pendingAction === 'repair' ? '送修登记（含拆装部件溯源）' : '修复完成登记（含更换部件）'" width="680px" append-to-body>
      <el-form label-width="70px">
        <el-form-item :label="pendingAction === 'repair' ? '送修说明' : '结果说明'">
          <el-input v-model="repairNote" type="textarea" :rows="2" placeholder="如：硬盘异响更换固态 / 内存加装至 16G" />
        </el-form-item>
      </el-form>
      <div class="parts-editor">
        <div v-for="(p, i) in partsForm" :key="i" class="part-row">
          <el-select v-model="p.direction" style="width: 104px; flex-shrink: 0">
            <el-option label="＋加装" value="add" />
            <el-option label="－拆卸" value="remove" />
          </el-select>
          <el-input v-model="p.name" placeholder="部件名称（如 内存条 / 固态硬盘 / 风扇）" style="flex: 1" />
          <el-input v-model="p.sn" placeholder="序列号 SN（选填）" style="width: 190px; flex-shrink: 0" />
          <el-button text type="danger" @click="removePartRow(i)">删</el-button>
        </div>
        <el-button size="small" text type="primary" @click="addPartRow">＋ 添加部件</el-button>
        <div class="muted" style="font-size: 12px; margin-top: 6px">部件记录将永久留在该设备的生命周期时间线中，可随时溯源查询。</div>
      </div>
      <template #footer>
        <el-button @click="partDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmParts">确认登记</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { del, get, patch, post } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

// v2.12 设备管理页签过滤：onlyCategories 限定展示类别（办公电脑/打印机），defaultCategory 为登记默认类型
const props = defineProps<{ onlyCategories?: string[]; defaultCategory?: string }>()

const auth = useAuthStore()
const statuses = ['在用', '维修中', '闲置', '报废']
const TYPE_OPTIONS = ['电脑', '打印机', '显示器', '网络设备', '外设', '其他']
const loading = ref(false)
const items = ref<any[]>([])

const assetPage = ref(1)
const pagedItems = computed(() => items.value.slice((assetPage.value - 1) * 20, assetPage.value * 20))

// v2.12 设备管理：顶部统计卡（与网络设备页签样式一致），基于当前页签筛选结果统计
const statCards = computed(() => [
  { label: '资产总数', value: items.value.length, color: '#1d2535' },
  { label: '在用', value: items.value.filter(i => i.status === '在用').length, color: '#67c23a' },
  { label: '维修中', value: items.value.filter(i => i.status === '维修中').length, color: '#e6a23c' },
  { label: '闲置', value: items.value.filter(i => i.status === '闲置').length, color: '#909399' },
])
const users = ref<any[]>([])
const q = ref('')
const status = ref('')
// 第四十一批：类型筛选（全库资产类型聚合，办公电脑多分类页签使用）
const typeFilter = ref('')
const categoryOptions = ref<string[]>([])

const editorVisible = ref(false)
const editorForm = reactive<any>({})

const histVisible = ref(false)
const histAsset = ref<any>(null)
const histEvents = ref<any[]>([])
const detectingId = ref<number | null>(null)

/** v2.11 在线检测：TCP 探活资产 IP（打印机/网络设备常用端口） */
async function detect(row: any) {
  detectingId.value = row.id
  try {
    const d = await post(`/api/assets/${row.id}/detect`)
    row._online = d.online
    if (!d.online) ElMessage.info(`${row.asset_tag}（${row.ip_address}）常见端口均未连通，判定离线`)
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    detectingId.value = null
  }
}

onMounted(() => {
  load()
  if (auth.isStaff) {
    get('/api/users').then((res) => (users.value = res.items)).catch(() => {})
  }
})

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (q.value) params.set('q', q.value)
    if (status.value) params.set('status', status.value)
    // 第四十一批：类型筛选（办公电脑页签；打印机等单分类页签也保留，全库可筛）
    if (typeFilter.value) params.set('category', typeFilter.value)
    // v2.12 页签分类过滤（多值逗号分隔）
    if (props.onlyCategories?.length) params.set('categories', props.onlyCategories.join(','))
    const res = await get(`/api/assets?${params}`)
    items.value = res.items
    // 类型筛选选项：固定类型集合（与登记表单一致，避免自定义类型从页签过滤消失）
    if (!categoryOptions.value.length) categoryOptions.value = TYPE_OPTIONS
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

/** 第四十一批：时间格式化（与网络设备一致） */
function fmtTime(s: string | null) {
  if (!s) return '-'
  return new Date(s).toLocaleString('zh-CN', { hour12: false })
}

function openEditor(row: any) {
  Object.assign(editorForm, row
    ? { ...row, owner_id: row.owner?.id ?? null, ip_address: row.ip_address || '', model: row.model || '', vendor: row.vendor || '', driver_url: row.driver_url || '', expire_date: row.expire_date || null }
    : { id: null, asset_tag: '', name: '', category: props.defaultCategory || '电脑', location: '', status: '在用', owner_id: null, note: '', ip_address: '', model: '', vendor: '', driver_url: '', expire_date: null })
  editorVisible.value = true
}

// 第三十八批：到期日红标样式（30 天内临期橙、已过期红）
function expireStyle(d: string) {
  const days = Math.round((new Date(d + 'T00:00:00').getTime() - new Date(new Date().toLocaleDateString('sv-SE') + 'T00:00:00').getTime()) / 86400000)
  if (days < 0) return { color: '#f56c6c', fontWeight: 600 }
  if (days <= 30) return { color: '#e6a23c', fontWeight: 600 }
  return { color: '#606266' }
}

async function save() {
  if (!editorForm.asset_tag.trim() || !editorForm.name.trim()) return ElMessage.warning('请填写资产编号和名称')
  try {
    if (editorForm.id) await patch(`/api/assets/${editorForm.id}`, editorForm)
    else await post('/api/assets', editorForm)
    ElMessage.success('已保存')
    editorVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`确认删除资产「${row.asset_tag}」？`, '删除确认', { type: 'warning' })
  try {
    await del(`/api/assets/${row.id}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function recover(row: any) {
  try {
    const r = await ElMessageBox.prompt(
      `回收资产「${row.asset_tag} ${row.name}」：将清空使用人、状态改为闲置，并留痕。`,
      '资产回收', {
        inputPlaceholder: '回收说明（如：员工离职收回 / 设备调拨）', inputValue: '',
        confirmButtonText: '确认回收', cancelButtonText: '取消',
      },
    )
    await post(`/api/assets/${row.id}/recover`, { note: r.value || '' })
    ElMessage.success('已回收（使用人清空，状态改为闲置）')
    await load()
  } catch (e: any) {
    if (e !== 'cancel' && e?.message) ElMessage.error(e.message)
  }
}

async function showHistory(row: any) {
  histAsset.value = row
  histVisible.value = true
  await loadHistory(row.id)
}

async function loadHistory(id: number) {
  try {
    histEvents.value = (await get(`/api/assets/${id}/events`)).items
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

/** v2.12 维修拆装部件登记：送修/修复完成时可记录加装的硬盘/内存等与拆卸的部件（SN 级溯源） */
const partsForm = ref<any[]>([])
const partDialogVisible = ref(false)
const pendingAction = ref('')
const repairNote = ref('')

function addPartRow() {
  partsForm.value.push({ name: '', sn: '', direction: 'add', note: '' })
}
function removePartRow(i: number) {
  partsForm.value.splice(i, 1)
}

async function doAction(action: string) {
  pendingAction.value = action
  const needParts = action === 'repair' || action === 'repair_done'
  if (needParts) {
    // 维修类操作：弹部件登记表单（说明 + 部件行），留痕溯源
    partsForm.value = [{ name: '', sn: '', direction: 'add', note: '' }]
    repairNote.value = ''
    partDialogVisible.value = true
    return
  }
  let note = ''
  try {
    const r = await ElMessageBox.prompt('操作说明（可选）', '资产生命周期操作', {
      inputPlaceholder: '说明（可留空）', inputValue: '',
      confirmButtonText: '执行', cancelButtonText: '取消',
    })
    note = r.value || ''
  } catch { return }
  await submitAction(action, note, [])
}

async function confirmParts() {
  const parts = partsForm.value.filter((p) => p.name.trim())
  const note = repairNote.value || ''
  const action = pendingAction.value
  partDialogVisible.value = false
  await submitAction(action, note, parts)
}

async function submitAction(action: string, note: string, parts: any[]) {
  try {
    await post(`/api/assets/${histAsset.value.id}/action`, { action, note, parts })
    ElMessage.success('操作完成，已留痕' + (parts.length ? `（${parts.length} 条部件记录）` : ''))
    await loadHistory(histAsset.value.id)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.stat-card { margin-bottom: 14px; text-align: center; }
.stat-value { font-size: 24px; font-weight: 700; }
.stat-label { font-size: 12px; color: #909399; margin-top: 4px; }
.filter-card { margin-bottom: 14px; }
.filters { display: flex; gap: 10px; align-items: center; }
.hist-actions { margin-bottom: 12px; }
.muted { color: #909399; font-size: 12px; }
.nowrap { white-space: nowrap; }
.part-list { margin-top: 4px; }
.parts-editor { display: flex; flex-direction: column; gap: 8px; }
.part-row { display: flex; gap: 8px; align-items: center; }
</style>
