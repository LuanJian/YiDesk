<template>
  <div>
    <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px"
      title="备份文件包含全部业务数据与账号信息，请妥善保管。恢复为覆盖式操作：JSON 数据包在线重建（不含附件文件）；SQLite 整库包含附件但恢复后需重启服务。" />

    <!-- 立即备份 -->
    <el-card shadow="never" class="block">
      <div class="row">
        <span class="label">立即备份：</span>
        <el-radio-group v-model="runFormat">
          <el-radio-button value="sqlite">整库 zip（含附件）</el-radio-button>
          <el-radio-button value="json">JSON 数据包</el-radio-button>
          <el-radio-button value="csv">工单 CSV</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :loading="running" @click="run">立即备份</el-button>
        <el-upload :show-file-list="false" :http-request="doImport" accept=".json,.zip" style="display: inline-block">
          <el-button type="warning" plain :loading="importing">
            <el-icon style="margin-right: 4px"><Upload /></el-icon>上传备份恢复
          </el-button>
        </el-upload>
      </div>
      <div class="hint">上传恢复：.json 在线重建数据（无需重启）；.zip 覆盖整库与附件（需重启服务）。恢复/导入为覆盖式操作，请先立即备份当前数据。</div>
    </el-card>

    <!-- 定时计划 -->
    <el-card shadow="never" class="block">
      <template #header>
        <div class="row" style="justify-content: space-between">
          <b>定时备份计划</b>
          <el-button type="primary" plain size="small" @click="openPlan(null)"><el-icon><Plus /></el-icon>&nbsp;新增计划</el-button>
        </div>
      </template>
      <el-table :data="plans" size="small" stripe>
        <!-- 第四十二批：状态列前置 -->
        <el-table-column label="状态" min-width="85">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '停用' }}</el-tag>
            <div v-if="row.last_error" class="hint" style="color: #f56c6c">{{ row.last_error }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="130" />
        <el-table-column label="格式" min-width="90">
          <template #default="{ row }">{{ ({ sqlite: '整库 zip', json: 'JSON', csv: 'CSV' } as any)[row.format] }}</template>
        </el-table-column>
        <el-table-column label="频率" min-width="110">
          <template #default="{ row }">
            {{ ({ daily: '每天', weekly: '每周', monthly: '每月' } as any)[row.frequency] }}
            <span v-if="row.frequency === 'weekly'">周{{ '一二三四五六日'[row.weekday] }}</span>
            <span v-if="row.frequency === 'monthly'">每月{{ row.month_day }}日</span>
          </template>
        </el-table-column>
        <el-table-column prop="time" label="时间" min-width="70" />
        <el-table-column prop="keep_last" label="保留份数" min-width="80" />
        <el-table-column prop="next_run" label="下次执行" min-width="150" />
        <el-table-column label="操作" width="290" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="runPlan(row)">立即执行</el-button>
            <el-button size="small" @click="openPlan(row)">编辑</el-button>
            <el-button size="small" @click="togglePlan(row)">{{ row.enabled ? '停用' : '启用' }}</el-button>
            <el-button size="small" type="danger" plain @click="removePlan(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 备份文件 -->
    <el-card shadow="never" class="block">
      <template #header>
        <div class="row" style="justify-content: space-between">
          <b>备份文件（data/backups/）</b>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </template>
      <el-table :data="files" size="small" stripe>
        <el-table-column prop="filename" label="文件名" min-width="280" show-overflow-tooltip />
        <el-table-column label="大小" min-width="100">
          <template #default="{ row }">{{ (row.size / 1024).toFixed(0) }} KB</template>
        </el-table-column>
        <el-table-column label="格式" min-width="90">
          <template #default="{ row }">{{ ({ sqlite: '整库 zip', json: 'JSON', csv: 'CSV' } as any)[row.format] }}</template>
        </el-table-column>
        <el-table-column label="生成时间" min-width="170">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN', { hour12: false }) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="download(row)">下载</el-button>
            <el-button
              v-if="row.format !== 'csv'"
              size="small"
              type="warning"
              plain
              @click="restore(row)"
            >恢复</el-button>
            <el-button size="small" type="danger" plain @click="removeFile(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 计划编辑 -->
    <el-dialog v-model="planVisible" :title="planForm.id ? '编辑计划' : '新增计划'" width="480px">
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="planForm.name" placeholder="如：每日整库备份" />
        </el-form-item>
        <el-form-item label="格式">
          <el-radio-group v-model="planForm.format">
            <el-radio-button value="sqlite">整库 zip</el-radio-button>
            <el-radio-button value="json">JSON</el-radio-button>
            <el-radio-button value="csv">CSV</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="频率">
          <el-select v-model="planForm.frequency" style="width: 110px">
            <el-option label="每天" value="daily" />
            <el-option label="每周" value="weekly" />
            <el-option label="每月" value="monthly" />
          </el-select>
          <el-select v-if="planForm.frequency === 'weekly'" v-model="planForm.weekday" style="width: 110px; margin-left: 8px">
            <el-option v-for="(n, i) in ['周一', '周二', '周三', '周四', '周五', '周六', '周日']" :key="i" :label="n" :value="i" />
          </el-select>
          <el-select v-if="planForm.frequency === 'monthly'" v-model="planForm.month_day" style="width: 110px; margin-left: 8px">
            <el-option v-for="i in 28" :key="i" :label="`${i} 日`" :value="i" />
          </el-select>
          <el-time-select v-model="planForm.time" start="00:00" step="00:30" end="23:30" style="width: 120px; margin-left: 8px" />
        </el-form-item>
        <el-form-item label="保留份数">
          <el-input-number v-model="planForm.keep_last" :min="1" :max="100" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="planForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="planVisible = false">取消</el-button>
        <el-button type="primary" @click="savePlan">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { del, get, patch, post } from '@/api/http'

const files = ref<any[]>([])
const plans = ref<any[]>([])
const runFormat = ref('sqlite')
const running = ref(false)
const importing = ref(false)
const planVisible = ref(false)
const planForm = ref<any>({})

onMounted(load)

async function load() {
  try {
    const res = await get('/api/admin/backups')
    files.value = res.files
    plans.value = res.plans
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function run() {
  running.value = true
  try {
    const res = await post('/api/admin/backups/run', { format: runFormat.value })
    ElMessage.success(`备份完成：${res.filename}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    running.value = false
  }
}

async function doImport(opt: any) {
  try {
    await ElMessageBox.prompt(
      '恢复为覆盖式操作，将清空现有数据并以备份重建。输入 RECOVER 确认：',
      '上传备份恢复', {
        inputPlaceholder: 'RECOVER',
        inputValidator: (v: string) => v.trim() === 'RECOVER' || '请输入 RECOVER',
        confirmButtonText: '恢复', cancelButtonText: '取消', type: 'warning',
      },
    )
  } catch {
    return
  }
  importing.value = true
  try {
    const fd = new FormData()
    fd.append('file', opt.file)
    fd.append('confirm', 'RECOVER')
    const token = localStorage.getItem('itops_token') || ''
    const resp = await fetch('/api/admin/backups/import', {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd,
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) throw new Error(data.detail || '导入失败')
    if (data.restart_required) {
      await ElMessageBox.alert('整库恢复完成，请重启服务后生效。', '恢复完成', { type: 'success' })
    } else {
      ElMessage.success(`数据恢复完成（工单 ${data.ticket_count} 条）`)
    }
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '导入失败')
  } finally {
    importing.value = false
  }
}

async function restore(row: any) {
  try {
    await ElMessageBox.prompt(
      `从「${row.filename}」恢复为覆盖式操作，将清空现有数据。输入 RECOVER 确认：`,
      '恢复备份', {
        inputPlaceholder: 'RECOVER',
        inputValidator: (v: string) => v.trim() === 'RECOVER' || '请输入 RECOVER',
        confirmButtonText: '恢复', cancelButtonText: '取消', type: 'warning',
      },
    )
  } catch {
    return
  }
  try {
    const res = await post(`/api/admin/backups/restore/${row.filename}`, { confirm: 'RECOVER' })
    if (res.restart_required) {
      await ElMessageBox.alert('整库恢复完成，请重启服务后生效。', '恢复完成', { type: 'success' })
    } else {
      ElMessage.success(`数据恢复完成（工单 ${res.ticket_count} 条）`)
      await load()
    }
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function download(row: any) {
  try {
    const token = localStorage.getItem('itops_token') || ''
    const resp = await fetch(`/api/admin/backups/${row.filename}/download`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!resp.ok) throw new Error('下载失败')
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = row.filename
    a.click()
    URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error(e.message || '下载失败')
  }
}

async function removeFile(row: any) {
  await ElMessageBox.confirm(`确认删除备份「${row.filename}」？`, '删除确认', { type: 'warning' })
  try {
    await del(`/api/admin/backups/${row.filename}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

function openPlan(row: any) {
  planForm.value = row
    ? { ...row }
    : { id: null, name: '', format: 'sqlite', frequency: 'daily', time: '02:00', weekday: null, month_day: null, keep_last: 10, enabled: true }
  planVisible.value = true
}

async function savePlan() {
  const f = planForm.value
  if (!f.name.trim()) return ElMessage.warning('请填写名称')
  try {
    if (f.id) await patch(`/api/admin/backups/plans/${f.id}`, f)
    else await post('/api/admin/backups/plans', f)
    ElMessage.success('已保存')
    planVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function togglePlan(row: any) {
  try {
    await patch(`/api/admin/backups/plans/${row.id}`, { enabled: !row.enabled })
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function removePlan(row: any) {
  await ElMessageBox.confirm(`确认删除计划「${row.name}」？`, '删除确认', { type: 'warning' })
  try {
    await del(`/api/admin/backups/plans/${row.id}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function runPlan(row: any) {
  try {
    const res = await post(`/api/admin/backups/plans/${row.id}/run`)
    ElMessage.success(`备份完成：${res.filename}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.block { margin-bottom: 14px; }
.row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.label { font-size: 13px; color: #606266; }
.hint { color: #909399; font-size: 12px; margin-top: 6px; }
</style>
