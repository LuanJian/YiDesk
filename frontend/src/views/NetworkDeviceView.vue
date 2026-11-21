<template>
  <div>
    <el-row :gutter="14">
      <el-col :span="6" v-for="c in cards" :key="c.label">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value" :style="{ color: c.color }">{{ c.value }}</div>
          <div class="stat-label">{{ c.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="filter-card">
      <div class="filters">
        <!-- 第四十一批：搜索范围扩展至 编号/名称/IP/位置/品牌/型号 -->
        <el-input v-model="q" placeholder="搜索编号/名称/品牌/型号/IP/位置" clearable style="width: 240px" @keyup.enter="load" @clear="load" />
        <el-select v-model="deviceType" placeholder="类型" clearable style="width: 140px" @change="load">
          <el-option v-for="t in deviceTypes" :key="t" :label="t" :value="t" />
        </el-select>
        <el-select v-model="status" placeholder="状态" clearable style="width: 140px" @change="load">
          <el-option v-for="s in statuses" :key="s" :label="s" :value="s" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
        <div style="flex: 1"></div>
        <el-button v-if="auth.can('devices.write')" plain :loading="probingAll" @click="probeAll">
          <el-icon style="margin-right: 4px"><Connection /></el-icon>全部探活
        </el-button>
        <el-button v-if="auth.can('devices.write')" type="primary" plain @click="openEditor(null)">
          <el-icon style="margin-right: 4px"><Plus /></el-icon>登记设备
        </el-button>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table :data="pagedItems" v-loading="loading" stripe>
        <!-- 第四十二批：状态列第一列，列序与资产台账一致 -->
        <el-table-column label="状态" min-width="85">
          <template #default="{ row }">
            <el-tag :type="({ 在线: 'success', 失联: 'danger', 停用: 'info', 备用: '' } as any)[row.status]" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="asset_tag" label="资产编号" min-width="130" show-overflow-tooltip />
        <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column prop="device_type" label="类型" min-width="100" />
        <el-table-column label="品牌" min-width="90">
          <template #default="{ row }">{{ row.vendor || '-' }}</template>
        </el-table-column>
        <el-table-column prop="model" label="型号" min-width="110" show-overflow-tooltip />
        <el-table-column label="最近检测" min-width="170">
          <template #default="{ row }"><span class="nowrap">{{ fmtTime(row.last_checked_at) }}</span></template>
        </el-table-column>
        <el-table-column prop="location" label="位置" min-width="110" show-overflow-tooltip />
        <el-table-column prop="ip" label="IP 地址" min-width="130">
          <template #default="{ row }"><span class="mono">{{ row.ip }}</span></template>
        </el-table-column>
        <el-table-column label="保修到期日" width="115">
          <template #default="{ row }">
            <!-- 第四十一批：日期单元格 nowrap 避免折行 -->
            <span v-if="row.expire_date" :style="{ whiteSpace: 'nowrap', ...expireStyle(row.expire_date) }">{{ row.expire_date }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="notes" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <template v-if="auth.can('devices.write')">
              <el-button size="small" type="success" plain :loading="probingId === row.id" @click="probe(row)">检测</el-button>
              <el-button size="small" @click="openEditor(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
        <el-pagination
          v-model:current-page="netPage"
          :page-size="20"
          :total="items.length"
          layout="total, prev, pager, next"
          style="margin-top: 10px; justify-content: center"
        />
    </el-card>

    <el-dialog v-model="visible" :title="form.id ? '编辑设备' : '登记设备'" width="600px">
      <el-form label-width="90px">
        <!-- 第四十一批：资产编号与品牌/型号分列（与资产台账口径一致） -->
        <el-form-item label="资产编号">
          <el-input v-model="form.asset_tag" placeholder="留空自动生成（如 NET-0001）" />
        </el-form-item>
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.device_type" style="width: 100%">
            <el-option v-for="t in deviceTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="品牌"><el-input v-model="form.vendor" /></el-form-item>
        <el-form-item label="型号"><el-input v-model="form.model" /></el-form-item>
        <el-form-item label="管理 IP" required><el-input v-model="form.ip" placeholder="如 192.168.10.2" /></el-form-item>
        <el-form-item label="探测端口">
          <el-input-number v-model="form.mgmt_port" :min="1" :max="65535" style="width: 160px" placeholder="留空自动尝试常见端口" />
        </el-form-item>
        <el-form-item label="位置"><el-input v-model="form.location" placeholder="如 5F 弱电间" /></el-form-item>
        <el-form-item label="序列号"><el-input v-model="form.serial_no" /></el-form-item>
        <el-form-item label="固件版本"><el-input v-model="form.firmware" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 160px">
            <el-option v-for="s in statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="保修到期">
          <el-date-picker
            v-model="form.expire_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="维保/保修到期日（选填）"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="自动探活"><el-switch v-model="form.probe_enabled" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.notes" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { del, get, patch, post } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const loading = ref(false)
const probingAll = ref(false)
const probingId = ref<number | null>(null)
const items = ref<any[]>([])

const netPage = ref(1)
const pagedItems = computed(() => items.value.slice((netPage.value - 1) * 20, netPage.value * 20))
const summary = ref<any>({})
const deviceTypes = ref<string[]>([])
const statuses = ref<string[]>([])
const q = ref('')
const deviceType = ref('')
const status = ref('')
const visible = ref(false)
const form = reactive<any>({})

const cards = computed(() => [
  { label: '设备总数', value: summary.value.total ?? '—', color: '#1d2535' },
  { label: '在线', value: summary.value.by_status?.在线 ?? 0, color: '#67c23a' },
  { label: '失联', value: summary.value.by_status?.失联 ?? 0, color: '#f56c6c' },
  { label: '类型分布', value: Object.keys(summary.value.by_type || {}).length, color: '#2f6fed' },
])

onMounted(load)

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (q.value) params.set('q', q.value)
    if (deviceType.value) params.set('device_type', deviceType.value)
    if (status.value) params.set('status', status.value)
    const res = await get(`/api/network-devices?${params}`)
    items.value = res.items
    summary.value = res.summary
    deviceTypes.value = res.device_types
    statuses.value = res.statuses
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function probe(row: any) {
  probingId.value = row.id
  try {
    const r = await post(`/api/network-devices/${row.id}/probe`)
    if (r.ok) ElMessage.success(`${row.name}（${row.ip}）在线`)
    else ElMessage.error(`${row.name}（${row.ip}）失联`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    probingId.value = null
  }
}

async function probeAll() {
  probingAll.value = true
  try {
    const r = await post('/api/network-devices/probe-all')
    ElMessage.success(`探活完成：在线 ${r.online}，失联 ${r.offline}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    probingAll.value = false
  }
}

function openEditor(row: any) {
  Object.assign(form, row
    ? { ...row, asset_tag: row.asset_tag || '', expire_date: row.expire_date || null }
    : { id: null, name: '', device_type: '交换机', vendor: '', model: '', ip: '', mgmt_port: null, location: '', serial_no: '', firmware: '', status: '备用', probe_enabled: true, asset_tag: '', expire_date: null, notes: '' })
  visible.value = true
}

// 第四十一批：到期日红标样式（30 天内临期橙、已过期红），与资产台账一致
function expireStyle(d: string) {
  const days = Math.round((new Date(d + 'T00:00:00').getTime() - new Date(new Date().toLocaleDateString('sv-SE') + 'T00:00:00').getTime()) / 86400000)
  if (days < 0) return { color: '#f56c6c', fontWeight: 600 }
  if (days <= 30) return { color: '#e6a23c', fontWeight: 600 }
  return { color: '#606266' }
}

async function save() {
  if (!form.name.trim() || !form.ip.trim()) return ElMessage.warning('请填写设备名和管理 IP')
  // 资产编号留空自动生成
  if (!form.asset_tag?.trim()) {
    const count = summary.value.total || 0
    form.asset_tag = 'NET-' + String(count + 1).padStart(4, '0')
  }
  try {
    if (form.id) await patch(`/api/network-devices/${form.id}`, form)
    else await post('/api/network-devices', form)
    ElMessage.success('已保存')
    visible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`确认删除设备「${row.name}」？`, '删除确认', { type: 'warning' })
  try { await del(`/api/network-devices/${row.id}`); await load() } catch (e: any) { ElMessage.error(e.message) }
}

function fmtTime(s: string | null) {
  if (!s) return '未检测'
  return new Date(s).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.stat-card { margin-bottom: 14px; text-align: center; }
.stat-value { font-size: 24px; font-weight: 700; }
.stat-label { font-size: 12px; color: #909399; margin-top: 4px; }
.filter-card { margin-bottom: 14px; }
.filters { display: flex; gap: 10px; align-items: center; }
.mono { font-family: Menlo, Consolas, monospace; font-size: 12px; }
.nowrap { white-space: nowrap; }
.muted { color: #909399; font-size: 12px; }
</style>
