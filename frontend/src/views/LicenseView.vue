<template>
  <div>
    <!-- v2.11 软件列表：软件许可台账 + 允许安装的软件目录 -->
    <el-tabs v-model="activeTab" class="sw-tabs">
      <!-- ===== 软件列表（v2.12 默认页签：允许安装的软件目录） ===== -->
      <el-tab-pane label="软件列表" name="software">
        <div class="stat-cards">
          <el-card shadow="never" class="stat-card">
            <div class="stat-value" style="color: #1d2535">{{ swSummary.total ?? 0 }}</div>
            <div class="stat-label">软件总数</div>
          </el-card>
          <el-card v-for="(t, i) in LICENSE_TYPES" :key="t" shadow="never" class="stat-card">
            <div class="stat-value" :style="{ color: statColors[i] }">{{ swSummary.by_license_type?.[t] ?? 0 }}</div>
            <div class="stat-label">{{ t }}（软件数量）</div>
          </el-card>
        </div>

        <el-card shadow="never" class="filter-card">
          <div class="filters">
            <el-input v-model="swQuery.q" placeholder="搜索软件名 / 描述 / 类型" clearable style="width: 240px" @keyup.enter="loadSoftwares" @clear="loadSoftwares" />
            <el-select v-model="swQuery.category" placeholder="软件类型" clearable style="width: 140px" @change="loadSoftwares">
              <el-option v-for="c in swCategories" :key="c" :label="c" :value="c" />
            </el-select>
            <el-select v-model="swQuery.license_type" placeholder="授权类型" clearable style="width: 140px" @change="loadSoftwares">
              <el-option v-for="t in LICENSE_TYPES" :key="t" :label="t" :value="t" />
            </el-select>
            <!-- v2.12 适用部门/岗位筛选（未限定部门/岗位的软件同样命中） -->
            <el-select v-model="swQuery.dept" placeholder="适用部门" clearable filterable style="width: 140px" @change="loadSoftwares">
              <el-option v-for="d in swDeptOptions" :key="d" :label="d" :value="d" />
            </el-select>
            <el-button type="primary" @click="loadSoftwares">查询</el-button>
            <div style="flex: 1"></div>
            <el-button v-if="auth.isAdmin" type="primary" plain @click="openSwEditor(null)">
              <el-icon style="margin-right: 4px"><Plus /></el-icon>登记软件
            </el-button>
          </div>
        </el-card>

        <el-card shadow="never">
          <el-table :data="pagedSw" v-loading="swLoading" stripe>
            <!-- v2.12 列序：状态 → 软件名称 → 类型 → 授权类型 → 来源 → 描述（最大宽度） → 操作 -->
            <el-table-column label="状态" width="70">
              <template #default="{ row }">
                <el-tag v-if="row.enabled" type="success" size="small">允许</el-tag>
                <el-tag v-else type="info" size="small">停用</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="软件名称" min-width="180" show-overflow-tooltip />
            <el-table-column prop="category" label="软件类型" min-width="90" />
            <el-table-column label="授权类型" min-width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="licenseTag[row.license_type] || 'info'">{{ row.license_type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="软件来源" min-width="110" class-name="col-sm-hide">
              <template #default="{ row }">
                <el-tag
                  size="small" effect="plain" :type="sourceTag[row.source_type] || 'info'"
                  :style="row.source_url ? 'cursor: pointer' : ''"
                  :title="row.source_url || undefined"
                  @click="row.source_url && window.open(row.source_url, '_blank')"
                >{{ row.source_type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="软件描述" min-width="320" show-overflow-tooltip />
            <el-table-column v-if="auth.isAdmin" label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openSwEditor(row)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="removeSw(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

        <el-pagination
          v-model:current-page="swPage"
          :page-size="20"
          :total="swItems.length"
          layout="total, prev, pager, next"
          style="margin-top: 10px; justify-content: center"
        />
      </el-card>

        <el-dialog v-model="swVisible" :title="swForm.id ? '编辑软件' : '登记软件'" width="620px">
          <el-form label-width="90px">
            <el-form-item label="软件名称" required><el-input v-model="swForm.name" /></el-form-item>
            <el-form-item label="软件类型">
              <el-select v-model="swForm.category" filterable allow-create default-first-option style="width: 100%">
                <el-option v-for="c in SW_CATEGORIES" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>
            <el-form-item label="授权类型">
              <el-select v-model="swForm.license_type" style="width: 100%">
                <el-option v-for="t in LICENSE_TYPES" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item label="软件描述">
              <el-input v-model="swForm.description" type="textarea" :rows="3" placeholder="软件用途、版本要求、注意事项等" />
            </el-form-item>
            <el-form-item label="适用部门">
              <el-select v-model="swForm.departments" multiple filterable allow-create default-first-option placeholder="从部门字典选择或输入新增，留空=全部部门" style="width: 100%">
                <el-option v-for="d in swDeptOptions" :key="d" :label="d" :value="d" />
              </el-select>
            </el-form-item>
            <el-form-item label="软件来源">
              <!-- 第四十三批：来源下拉收窄（内容仅 4 字），加宽右侧网址输入框 -->
              <div style="display: flex; gap: 8px; width: 100%">
                <el-select v-model="swForm.source_type" style="width: 100px; flex-shrink: 0">
                  <el-option v-for="t in SOURCE_TYPES" :key="t" :label="t" :value="t" />
                </el-select>
                <el-input v-model="swForm.source_url" placeholder="来源地址，如 https://www.example.com（可点击跳转）" />
              </div>
            </el-form-item>
            <el-form-item label="状态">
              <el-switch v-model="swForm.enabled" active-text="允许安装" inactive-text="停用" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="swVisible = false">取消</el-button>
            <el-button type="primary" @click="saveSw">保存</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <!-- ===== 软件许可（原台账） ===== -->
      <el-tab-pane label="软件许可" name="license" lazy>
        <div class="stat-cards">
          <el-card v-for="c in cards" :key="c.label" shadow="never" class="stat-card">
            <div class="stat-value" :style="{ color: c.color }">{{ c.value }}</div>
            <div class="stat-label">{{ c.label }}</div>
          </el-card>
        </div>

        <el-card shadow="never" class="filter-card">
          <div class="filters">
            <el-input v-model="q" placeholder="搜索名称 / 厂商" clearable style="width: 240px" @keyup.enter="load" @clear="load" />
            <el-select v-model="licenseType" placeholder="许可类型" clearable style="width: 140px" @change="load">
              <el-option v-for="t in licenseTypes" :key="t" :label="t" :value="t" />
            </el-select>
            <el-button type="primary" @click="load">查询</el-button>
            <div style="flex: 1"></div>
            <el-button v-if="auth.isAdmin" type="primary" plain @click="openEditor(null)">
              <el-icon style="margin-right: 4px"><Plus /></el-icon>登记许可
            </el-button>
          </div>
        </el-card>

        <el-card shadow="never">
          <!-- 第四十二批：到期状态提取为第一列（与软件列表状态列样式一致）；列名调整；移除密钥列 -->
          <el-table :data="pagedLic" v-loading="loading" stripe>
            <el-table-column label="状态" width="85">
              <template #default="{ row }">
                <el-tag v-if="row.expired" type="danger" size="small">已过期</el-tag>
                <el-tag v-else-if="row.expiring" type="warning" size="small">即将到期</el-tag>
                <el-tag v-else type="success" size="small">正常</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="软件名称" min-width="150" show-overflow-tooltip />
            <el-table-column prop="vendor" label="厂商名称" min-width="110" />
            <el-table-column prop="license_type" label="许可类型" min-width="95" />
            <el-table-column label="席位" min-width="90">
              <template #default="{ row }">
                <span :class="{ danger: row.seats_low }">{{ row.seats_used }}/{{ row.seats_total }}</span>
              </template>
            </el-table-column>
            <el-table-column label="到期日" min-width="110">
              <template #default="{ row }">
                <span v-if="row.expiry_date" style="white-space: nowrap">{{ row.expiry_date }}</span>
                <span v-else class="muted">永久</span>
              </template>
            </el-table-column>
            <el-table-column prop="cost" label="成本(元)" min-width="95" />
            <el-table-column v-if="auth.isAdmin" label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openEditor(row)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

        <el-pagination
          v-model:current-page="licPage"
          :page-size="20"
          :total="items.length"
          layout="total, prev, pager, next"
          style="margin-top: 10px; justify-content: center"
        />
      </el-card>

        <el-dialog v-model="visible" :title="form.id ? '编辑许可' : '登记许可'" width="600px">
          <el-form label-width="90px">
            <!-- 第四十二批：命名统一（软件名称/厂商名称/许可类型），移除许可密钥字段 -->
            <el-form-item label="软件名称" required><el-input v-model="form.name" /></el-form-item>
            <el-form-item label="厂商名称"><el-input v-model="form.vendor" /></el-form-item>
            <el-form-item label="许可类型">
              <el-select v-model="form.license_type" style="width: 100%">
                <el-option v-for="t in licenseTypes" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item label="席位数">
              <el-input-number v-model="form.seats_total" :min="1" style="width: 140px" />
              <span class="muted" style="margin-left: 10px">已用 {{ form.seats_used }}</span>
            </el-form-item>
            <el-form-item label="已用席位">
              <el-input-number v-model="form.seats_used" :min="0" style="width: 140px" />
            </el-form-item>
            <el-form-item label="购买日期"><el-date-picker v-model="form.purchase_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
            <el-form-item label="到期日期"><el-date-picker v-model="form.expiry_date" type="date" value-format="YYYY-MM-DD" placeholder="永久授权可留空" /></el-form-item>
            <el-form-item label="成本(元)"><el-input-number v-model="form.cost" :min="0" style="width: 160px" /></el-form-item>
            <el-form-item label="厂商联系"><el-input v-model="form.vendor_contact" /></el-form-item>
            <el-form-item label="备注"><el-input v-model="form.notes" type="textarea" :rows="2" /></el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="visible = false">取消</el-button>
            <el-button type="primary" @click="save">保存</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { del, get, patch, post } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const LICENSE_TYPES = ['完全免费', '部分免费', '开源软件', '免费商用']
const SOURCE_TYPES = ['软件官网', '项目地址', '三方网站']
const SW_CATEGORIES = ['办公软件', '研发工具', '设计软件', '安全软件', '通讯协作', '浏览器', '其他']
const licenseTag: Record<string, string> = { 完全免费: 'success', 部分免费: 'primary', 开源软件: 'warning', 免费商用: 'danger' }
const sourceTag: Record<string, string> = { 软件官网: 'success', 项目地址: 'primary', 三方网站: 'warning' }

const activeTab = ref<'license' | 'software'>('software') // v2.12 默认显示软件列表
const statColors = ['#2f6fed', '#e6a23c', '#67c23a', '#f56c6c']

// ---- 软件许可（原台账） ----
const loading = ref(false)
const items = ref<any[]>([])

const licPage = ref(1)
// 第四十三批：已过期/即将到期置顶显示（权重：已过期 0 → 即将到期 1 → 正常 2），同权重按名称排序
const pagedLic = computed(() => {
  const weight = (row: any) => (row.expired ? 0 : row.expiring ? 1 : 2)
  const sorted = [...items.value].sort((a, b) => {
    const wa = weight(a) - weight(b)
    if (wa !== 0) return wa
    return String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN')
  })
  return sorted.slice((licPage.value - 1) * 20, licPage.value * 20)
})
const summary = ref<any>({})
const licenseTypes = ref<string[]>([])
const q = ref('')
const licenseType = ref('')
const visible = ref(false)
const form = reactive<any>({})

const cards = computed(() => [
  { label: '许可总数', value: summary.value.total ?? '—', color: '#1d2535' },
  { label: '30 天内到期', value: summary.value.expiring_30 ?? '—', color: '#e6a23c' },
  { label: '已过期', value: summary.value.expired ?? '—', color: '#f56c6c' },
  { label: '席位用满', value: summary.value.seats_full ?? '—', color: '#e6a23c' },
  { label: '总成本(元)', value: summary.value.total_cost ?? '—', color: '#2f6fed' },
])

onMounted(() => {
  // 软件许可仅管理员维护（员工无 /api/licenses 权限，避免 403 弹错）
  if (auth.isAdmin) load()
  loadSoftwares()
})

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (q.value) params.set('q', q.value)
    if (licenseType.value) params.set('license_type', licenseType.value)
    const res = await get(`/api/licenses?${params}`)
    items.value = res.items
    summary.value = res.summary
    licenseTypes.value = res.license_types
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function openEditor(row: any) {
  Object.assign(form, row
    ? { ...row, license_key: '' }
    : { id: null, name: '', vendor: '', license_type: '永久授权', license_key: '', seats_total: 1, seats_used: 0, purchase_date: null, expiry_date: null, cost: 0, vendor_contact: '', notes: '', enabled: true })
  visible.value = true
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写软件名')
  try {
    if (form.id) await patch(`/api/licenses/${form.id}`, form)
    else await post('/api/licenses', form)
    ElMessage.success('已保存')
    visible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`确认删除许可「${row.name}」？`, '删除确认', { type: 'warning' })
  try { await del(`/api/licenses/${row.id}`); await load() } catch (e: any) { ElMessage.error(e.message) }
}

// ---- 软件列表（v2.12 默认页签，带统计卡；部门/岗位筛选） ----
const swLoading = ref(false)
const swItems = ref<any[]>([])

const swPage = ref(1)
const pagedSw = computed(() => swItems.value.slice((swPage.value - 1) * 20, swPage.value * 20))
const swCategories = ref<string[]>([])
const swDeptOptions = ref<string[]>([])
const swQuery = reactive<any>({ q: '', category: '', license_type: '', dept: '', position: '' })
const swVisible = ref(false)
const swForm = reactive<any>({})
const swSummary = ref<any>({ total: 0, by_license_type: {}, last_updated: null })

async function loadSoftwares() {
  swLoading.value = true
  try {
    const params = new URLSearchParams()
    if (swQuery.q) params.set('q', swQuery.q)
    if (swQuery.category) params.set('category', swQuery.category)
    if (swQuery.license_type) params.set('license_type', swQuery.license_type)
    if (swQuery.dept) params.set('dept', swQuery.dept)
    const res = await get(`/api/softwares?${params}`)
    swItems.value = res.items
    swCategories.value = res.categories
    swDeptOptions.value = res.dept_options || []
    swSummary.value = res.summary || swSummary.value
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    swLoading.value = false
  }
}

function openSwEditor(row: any) {
  Object.assign(swForm, row
    ? { ...row }
    : { id: null, name: '', category: '办公软件', license_type: '完全免费', description: '', departments: [], source_type: '软件官网', source_url: '', enabled: true })
  swVisible.value = true
}

async function saveSw() {
  if (!swForm.name.trim()) return ElMessage.warning('请填写软件名称')
  try {
    if (swForm.id) await patch(`/api/softwares/${swForm.id}`, { ...swForm, positions: undefined })
    else await post('/api/softwares', { ...swForm, positions: undefined })
    // v2.12 新增的部门/岗位标签自动沉淀进组织字典（系统设置可管理）
    const knownD = new Set(swDeptOptions.value)
    for (const d of swForm.departments || []) {
      if (!knownD.has(d)) await post('/api/org-tags', { type: 'dept', name: d }).catch(() => {})
    }
    ElMessage.success('已保存')
    swVisible.value = false
    await loadSoftwares()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function removeSw(row: any) {
  await ElMessageBox.confirm(`确认从软件目录移除「${row.name}」？`, '删除确认', { type: 'warning' })
  try { await del(`/api/softwares/${row.id}`); await loadSoftwares() } catch (e: any) { ElMessage.error(e.message) }
}
</script>

<style scoped>
.stat-cards { display: flex; gap: 14px; margin-bottom: 14px; }
.stat-card { flex: 1; margin-bottom: 0; text-align: center; }
.stat-value { font-size: 24px; font-weight: 700; }
.stat-value.stat-time { font-size: 18px; line-height: 24px; }
.stat-label { font-size: 12px; color: #909399; margin-top: 4px; }
.filter-card { margin-bottom: 14px; }
.filters { display: flex; gap: 10px; align-items: center; }
.mono { font-family: Menlo, Consolas, monospace; font-size: 12px; color: #606266; }
.muted { color: #909399; font-size: 12px; }
.danger { color: #f56c6c; font-weight: 600; }
</style>
