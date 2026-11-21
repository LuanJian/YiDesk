<template>
  <div>
    <!-- 筛选栏（v2.12：粒度含周，日期框缩窄；原快捷范围页签移除） -->
    <el-card shadow="never" class="filter-card">
      <div class="filters">
        <el-radio-group v-model="granularity" @change="load">
          <el-radio-button value="day">日</el-radio-button>
          <el-radio-button value="week">周</el-radio-button>
          <el-radio-button value="month">月</el-radio-button>
          <el-radio-button value="year">年</el-radio-button>
          <el-radio-button value="custom">自定义</el-radio-button>
        </el-radio-group>
        <el-date-picker
          v-model="range"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始"
          end-placeholder="结束"
          style="width: 260px"
          @change="load"
        />
        <el-select v-model="category" placeholder="全部分类" clearable style="width: 140px" @change="load">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <!-- v2.12 处理人下拉移除：下方处理人构成/明细已有完整维度 -->
        <el-select v-model="department" placeholder="全部部门" clearable filterable allow-create style="width: 140px" @change="load">
          <el-option v-for="d in departments" :key="d" :label="d" :value="d" />
        </el-select>
        <div style="flex: 1"></div>
        <el-button v-if="auth.isAdmin" plain :loading="exporting" @click="exportCsv">
          <el-icon style="margin-right: 4px"><Download /></el-icon>导出 CSV
        </el-button>
        <!-- 第二十八批+：运维月报 PDF 导出 -->
        <el-button plain :loading="reportExporting" @click="exportMonthlyReport">
          <el-icon style="margin-right: 4px"><Document /></el-icon>导出月报
        </el-button>
      </div>
    </el-card>

    <!-- 指标卡（v2.12 快照信息合并进卡片副行） -->

    <el-row :gutter="10" class="cards">
      <el-col :span="6" v-for="c in cards" :key="c.key">
        <el-card shadow="never" class="metric">
          <div class="metric-label">{{ c.label }}</div>
          <div class="metric-value">
            {{ fmt(c.data?.value) }}<span v-if="c.unit" class="metric-unit">{{ c.unit }}</span>
          </div>
          <div class="metric-prev">
            <template v-if="cardSub[c.key]">
              <span class="metric-sub">{{ cardSub[c.key] }}</span>
            </template>
            <template v-else-if="c.data?.prev !== null && c.data?.prev !== undefined">
              上期 {{ fmt(c.data.prev) }}
              <span :class="changeClass(c.data.change)">{{ changeText(c.data.change) }}</span>
              <!-- 第三十七批：同比（上周/上月同周期） -->
              <span v-if="c.data?.yoy !== null && c.data?.yoy !== undefined" style="margin-left: 8px">
                同期 {{ fmt(c.data.yoy) }}
                <span :class="changeClass(c.data.yoy_change)">{{ changeText(c.data.yoy_change) }}</span>
              </span>
            </template>
            <span v-else class="muted">上期无数据</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 第二十七批+：高频问题 Top 放左（宽=分类占比 span8）、趋势放右（宽=优先级+满意度 span16） -->
    <el-row :gutter="10">
      <el-col :span="8">
        <el-card shadow="never" class="block">
          <template #header><b>高频问题 Top（占总量百分比）</b></template>
          <div ref="hotRef" class="chart-lg"></div>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card shadow="never" class="block">
          <template #header><b>趋势（新建 / 解决 / 平均解决时长）</b></template>
          <div ref="trendRef" class="chart-lg"></div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="10">
      <el-col :span="8">
        <el-card shadow="never" class="block">
          <template #header><b>分类占比</b></template>
          <div ref="catRef" class="chart"></div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="block">
          <template #header><b>优先级分布</b></template>
          <div ref="priRef" class="chart"></div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never" class="block">
          <template #header><b>满意度分布</b></template>
          <div ref="satRef" class="chart"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 处理人明细表（第二十七批+ 与问题构成互换位置） -->
    <el-card shadow="never" class="block">
      <template #header><b>处理人员明细</b></template>
      <el-table :data="d.engineers || []" size="small" stripe>
        <el-table-column prop="name" label="处理人" width="110" fixed />
        <el-table-column prop="assigned" label="受理" min-width="70" sortable />
        <el-table-column prop="resolved" label="解决" min-width="70" sortable />
        <el-table-column prop="open" label="未结" min-width="70" sortable />
        <el-table-column label="平均响应" min-width="100" sortable prop="avg_response_minutes">
          <template #default="{ row }">{{ row.avg_response_minutes != null ? row.avg_response_minutes + ' 分' : '-' }}</template>
        </el-table-column>
        <el-table-column label="平均解决" min-width="100" sortable prop="avg_resolution_minutes">
          <template #default="{ row }">{{ row.avg_resolution_minutes != null ? row.avg_resolution_minutes + ' 分' : '-' }}</template>
        </el-table-column>
        <el-table-column label="响应达标" min-width="90">
          <template #default="{ row }">{{ pct(row.response_sla_rate) }}</template>
        </el-table-column>
        <el-table-column label="解决达标" min-width="90">
          <template #default="{ row }">{{ pct(row.resolution_sla_rate) }}</template>
        </el-table-column>
        <el-table-column label="满意度" min-width="110">
          <template #default="{ row }">
            <span v-if="row.avg_stars != null">{{ row.avg_stars }} ★（{{ row.rating_count }}）</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="重开率" min-width="90">
          <template #default="{ row }">{{ pct(row.reopen_rate) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header><b>处理人问题构成（按解决量）</b></template>
      <div ref="mixRef" class="chart-wide"></div>
    </el-card>

    <!-- v2.12 提单员工 Top10 / 部门汇总 左右拆分（表格预留 Top10 行高）；低分单移至下方占整行 -->
    <el-row :gutter="10">
      <el-col :span="12">
        <el-card shadow="never" class="block">
          <template #header><b>提单员工 Top10</b></template>
          <el-table :data="(d.submitters?.employees || []).slice(0, 10)" size="small" stripe>
            <el-table-column type="index" label="#" width="46" />
            <el-table-column prop="name" label="提单员工" min-width="120" />
            <el-table-column prop="department" label="部门" min-width="120">
              <template #default="{ row }">{{ row.department || '-' }}</template>
            </el-table-column>
            <el-table-column prop="count" label="工单量" sortable />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never" class="block">
          <template #header><b>部门汇总</b></template>
          <el-table :data="(d.submitters?.departments || []).slice(0, 10)" size="small" stripe>
            <el-table-column prop="department" label="部门" min-width="140" />
            <el-table-column prop="count" label="工单量" min-width="90" sortable />
            <el-table-column label="占比" min-width="90">
              <template #default="{ row }">{{ row.pct }}%</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { download, get } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
// granularity: day/week/month/year/custom（custom=按日分桶+自由区间）
const range = ref<[string, string] | null>(null)
const granularity = ref('day')
const category = ref('')
const department = ref('')
const categories = ref<string[]>([])
const engineers = ref<any[]>([])
const departments = ref<string[]>([])
const d = ref<any>({})
const exporting = ref(false)

const trendRef = ref<HTMLElement>()
const hotRef = ref<HTMLElement>()
const catRef = ref<HTMLElement>()
const priRef = ref<HTMLElement>()
const satRef = ref<HTMLElement>()
const mixRef = ref<HTMLElement>()
const ov = ref<any>({})
let trendChart: echarts.ECharts | null = null
let hotChart: echarts.ECharts | null = null
let catChart: echarts.ECharts | null = null
let priChart: echarts.ECharts | null = null
let satChart: echarts.ECharts | null = null
let mixChart: echarts.ECharts | null = null

const CARDS = [
  { key: 'created', label: '新建工单' },
  { key: 'resolved', label: '解决工单' },
  { key: 'open', label: '当前未结' },
  { key: 'overdue', label: '超期未结' },
  { key: 'avg_response_minutes', label: '平均响应', unit: ' 分' },
  { key: 'avg_resolution_minutes', label: '平均解决', unit: ' 分' },
  { key: 'resolution_sla_rate', label: '解决达标率', unit: '%' },
  { key: 'rating_avg', label: '平均满意度', unit: ' ★' },
]
// v2.12 快照条合并：部分卡片副行展示全量口径信息（累计/状态分布/历史满意度）
const cardSub = computed(() => {
  const bs: Record<string, number> = ov.value.by_status || {}
  const sub: Record<string, string> = {
    created: `累计 ${ov.value.total ?? 0} 单`,
    resolved: `已解决 ${bs['已解决'] ?? 0} · 已关闭 ${bs['已关闭'] ?? 0}`,
    open: `待受理 ${bs['待受理'] ?? 0} · 处理中 ${bs['处理中'] ?? 0} · 待确认 ${bs['待确认'] ?? 0} · 待审批 ${bs['待审批'] ?? 0}`,
    rating_avg: ov.value.rating_avg != null ? `历史 ${ov.value.rating_avg}★（${ov.value.rating_count ?? 0} 评）` : '',
  }
  return sub
})
const cards = computed(() => CARDS.map((c) => ({ ...c, data: d.value.summary?.[c.key] })))

function fmt(v: any) {
  return v === null || v === undefined ? '-' : v
}
function pct(v: any) {
  return v === null || v === undefined ? '-' : `${v}%`
}
function changeText(c: any) {
  if (c === null || c === undefined) return ''
  return c > 0 ? `↑ ${c}%` : c < 0 ? `↓ ${Math.abs(c)}%` : '持平'
}
function changeClass(c: any) {
  if (c === null || c === undefined || c === 0) return 'muted'
  return c > 0 ? 'up' : 'down'
}

/** 默认区间：近 30 天（本地日期） */
function initRange() {
  const today = new Date()
  const iso = (dt: Date) => dt.toISOString().slice(0, 10)
  const s = new Date(today)
  s.setDate(s.getDate() - 29)
  range.value = [iso(s), iso(today)]
}

async function load() {
  if (!range.value) initRange()
  const params = new URLSearchParams()
  if (range.value) {
    params.set('start', range.value[0])
    params.set('end', range.value[1])
  }
  // 自定义 = 按日分桶 + 自由区间
  params.set('granularity', granularity.value === 'custom' ? 'day' : granularity.value)
  if (category.value) params.set('category', category.value)
  if (department.value) params.set('department', department.value)
  try {
    d.value = await get(`/api/analytics/dashboard?${params}`)
    await nextTick()
    renderCharts()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

function renderCharts() {
  // 趋势
  if (trendRef.value) {
    trendChart = trendChart || echarts.init(trendRef.value)
    const t = d.value.trend || []
    trendChart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['新建', '解决', '平均解决时长(分)'] },
      grid: { left: 40, right: 46, top: 34, bottom: 26 },
      xAxis: { type: 'category', data: t.map((x: any) => x.bucket) },
      yAxis: [
        { type: 'value', name: '单量' },
        { type: 'value', name: '分钟', splitLine: { show: false } },
      ],
      series: [
        { name: '新建', type: 'bar', data: t.map((x: any) => x.created), itemStyle: { color: '#409eff' } },
        { name: '解决', type: 'bar', data: t.map((x: any) => x.resolved), itemStyle: { color: '#67c23a' } },
        { name: '平均解决时长(分)', type: 'line', yAxisIndex: 1, smooth: true, data: t.map((x: any) => x.avg_resolution_minutes), itemStyle: { color: '#e6a23c' } },
      ],
    })
  }
  // 高频问题（横向条形，百分比标签）
  if (hotRef.value) {
    hotChart = hotChart || echarts.init(hotRef.value)
    const kws = (d.value.hot_issues?.keywords || []).slice().reverse()
    hotChart.setOption({
      tooltip: { trigger: 'axis', formatter: (ps: any) => `${ps[0].name}：${ps[0].value} 单（${kws.find((k: any) => k.keyword === ps[0].name)?.pct}%）` },
      grid: { left: 8, right: 56, top: 8, bottom: 24, containLabel: true },
      xAxis: { type: 'value' },
      yAxis: { type: 'category', data: kws.map((k: any) => k.keyword) },
      series: [{
        type: 'bar', barMaxWidth: 16,
        data: kws.map((k: any) => k.count),
        label: { show: true, position: 'right', formatter: (p: any) => `${p.value}（${kws.find((k: any) => k.keyword === p.name)?.pct}%）` },
        itemStyle: { color: '#f56c6c' },
      }],
    })
  }
  // 分类占比
  if (catRef.value) {
    catChart = catChart || echarts.init(catRef.value)
    catChart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}：{c}（{d}%）' },
      legend: { bottom: 0, type: 'scroll' },
      series: [{ type: 'pie', radius: ['38%', '66%'], center: ['50%', '44%'], data: d.value.hot_issues?.categories || [] }],
    })
  }
  // 优先级分布（原统计看板并入）
  if (priRef.value) {
    priChart = priChart || echarts.init(priRef.value)
    priChart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}：{c}（{d}%）' },
      legend: { bottom: 0 },
      series: [{
        type: 'pie', radius: ['38%', '66%'], center: ['50%', '44%'],
        data: (d.value.priority_mix || []).map((x: any) => ({
          name: x.name, value: x.value,
          itemStyle: { color: ({ low: '#909399', medium: '#409eff', high: '#e6a23c', urgent: '#f56c6c' } as any)[x.name] },
        })),
      }],
    })
  }
  // 满意度分布
  if (satRef.value) {
    satChart = satChart || echarts.init(satRef.value)
    const dist = d.value.satisfaction?.distribution || {}
    satChart.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 36, right: 16, top: 20, bottom: 26 },
      xAxis: { type: 'category', data: ['1星', '2星', '3星', '4星', '5星'] },
      yAxis: { type: 'value' },
      series: [{
        type: 'bar', barMaxWidth: 30,
        data: [1, 2, 3, 4, 5].map((i) => ({
          value: dist[String(i)] || 0,
          itemStyle: { color: i <= 2 ? '#f56c6c' : i === 3 ? '#e6a23c' : '#67c23a' },
        })),
        label: { show: true, position: 'top' },
      }],
    })
  }
  // 处理人 × 分类堆叠
  if (mixRef.value) {
    mixChart = mixChart || echarts.init(mixRef.value)
    const mix = d.value.engineer_mix || []
    const catsSet = new Set<string>()
    mix.forEach((m: any) => m.parts.forEach((p: any) => catsSet.add(p.category)))
    const catList = [...catsSet]
    mixChart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0, type: 'scroll' },
      grid: { left: 80, right: 20, top: 12, bottom: 40 },
      xAxis: { type: 'value' },
      yAxis: { type: 'category', data: mix.map((m: any) => m.name) },
      series: catList.map((c) => ({
        name: c, type: 'bar', stack: 'total', barMaxWidth: 18,
        data: mix.map((m: any) => m.parts.find((p: any) => p.category === c)?.count || 0),
      })),
    })
  }
}

function onResize() {
  trendChart?.resize(); hotChart?.resize(); catChart?.resize(); priChart?.resize(); satChart?.resize(); mixChart?.resize()
}

// 第二十八批+：运维月报 PDF 导出（默认当前系统日期所在月）
const reportExporting = ref(false)

async function exportMonthlyReport() {
  if (!auth.isAdmin) return ElMessage.warning('月报导出仅管理员可用')
  reportExporting.value = true
  try {
    const now = new Date()
    const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
    await download(`/api/export/monthly-report?month=${month}`, `运维月报-${month}.pdf`)
    ElMessage.success('月报已导出')
  } catch (e: any) {
    ElMessage.error(e.message || '导出失败')
  } finally {
    reportExporting.value = false
  }
}

/** v2.11 导出 CSV 仅管理员；download() 带 Authorization（window.open 无法带 token 会 401） */
async function exportCsv() {
  if (!auth.isAdmin) return ElMessage.warning('导出仅管理员可用')
  exporting.value = true
  try {
    const params = new URLSearchParams()
    if (range.value) { params.set('start', range.value[0]); params.set('end', range.value[1]) }
    params.set('granularity', granularity.value)
    if (category.value) params.set('category', category.value)
    await download(`/api/analytics/export?sheet=engineers&${params}`, '处理人明细.csv')
  } catch (e: any) {
    ElMessage.error(e.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  window.addEventListener('resize', onResize)
  // 全量快照（原统计看板并入）：累计/状态分布/历史满意度
  get('/api/stats/overview').then((res) => (ov.value = res)).catch(() => {})
  try {
    const info = await get('/api/admin/info')
    categories.value = info.categories || []
  } catch { /* ignore */ }
  try {
    engineers.value = (await get('/api/users?role=engineer')).items
    const depts = new Set<string>()
    engineers.value.forEach((e: any) => e.department && depts.add(e.department))
    departments.value = [...depts]
  } catch { /* ignore */ }
  await load()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  trendChart?.dispose(); hotChart?.dispose(); catChart?.dispose(); priChart?.dispose(); satChart?.dispose(); mixChart?.dispose()
})
</script>

<style scoped>
.filter-card { margin-bottom: 12px; }
.filters { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.cards { margin-bottom: 12px; }
.metric { text-align: center; }
.metric-label { color: #909399; font-size: 12px; }
.metric-value { font-size: 24px; font-weight: 600; margin: 4px 0 2px; }
.metric-unit { font-size: 12px; color: #909399; font-weight: 400; }
.metric-sub { color: #909399; font-size: 12px; }
.metric-prev { font-size: 12px; color: #909399; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
.block { margin-bottom: 12px; }
.chart { height: 260px; }
.chart-lg { height: 320px; }
.chart-wide { height: 300px; }
.snapshot-card { margin-bottom: 12px; }
.snapshot { display: flex; gap: 28px; align-items: center; flex-wrap: wrap; }
.snap-item { text-align: center; min-width: 90px; }
.snap-num { font-size: 22px; font-weight: 600; }
.snap-num.warn { color: #e6a23c; }
.snap-unit { font-size: 12px; color: #909399; font-weight: 400; }
.snap-label { color: #909399; font-size: 12px; margin-top: 2px; }
.status-tags { max-width: 420px; text-align: left; }
/* v2.12 低分单占整行：两列栅格铺开 */
.low-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px 24px; }
.low-row { padding: 8px 0; border-bottom: 1px dashed #ebeef5; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.low-title { font-size: 13px; }
.low-comment { width: 100%; padding-left: 2px; }
/* 第四十四批：后端已硬限 Top10，提单员工/部门表格高度自适应内容（原 min-height 440px 预留已删） */
.muted { color: #909399; font-size: 12px; }
@media (max-width: 768px) {
  .el-col { max-width: 100%; flex: 0 0 100%; }
  .filters { flex-wrap: wrap; }
  .cards .el-col { max-width: 50%; flex: 0 0 50%; }
}
</style>
