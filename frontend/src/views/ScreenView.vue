<template>

  <div class="screen">

    <div class="screen-head">

      <span v-if="urgentCount" class="urgent-chip">加急 {{ urgentCount }} 单待响应</span>

      <span class="screen-time">{{ nowText }}</span>

      <!-- v2.11 自定义刷新间隔 -->

      <span class="refresh-box">

        <span class="refresh-label">刷新间隔</span>

        <el-select v-model="refreshSeconds" size="small" style="width: 90px" @change="onIntervalChange">

          <el-option v-for="s in [10, 15, 30, 60, 120, 180]" :key="s" :label="s >= 60 ? `${s / 60} 分钟` : `${s} 秒`" :value="s" />

          <el-option label="手动" :value="0" />

        </el-select>

        <el-button size="small" text style="color: #9fb3d1" @click="load">立即刷新</el-button>

      </span>

      <el-button size="small" text style="color: #9fb3d1" @click="$router.push('/tickets')">返回管理</el-button>

    </div>

    <!-- v2.12 布局：左侧工单列表全高；右侧上方指标卡两行、下方柱状图 -->

    <div class="panels">

      <div class="panel panel-list">

        <div class="panel-title">工单列表</div>

        <div class="open-list">

          <div v-for="t in recentTickets" :key="t.id" class="open-row">

            <span class="no" :class="`p-${t.priority || 'medium'}`">{{ t.no }}</span>

            <span class="ti">{{ t.title }}</span>

            <span class="as">{{ t.assignee?.name || '未指派' }}</span>

            <span class="st">{{ t.status_label }}</span>

          </div>

          <div v-if="!recentTickets.length" class="empty">暂无工单</div>

        </div>

      </div>

      <div class="right-col">

        <!-- 指标卡两行：本周/未结/今日新建/今日解决 + 时效/达标/满意度 -->

        <div class="cards">

          <div v-for="c in cards" :key="c.label" class="card">

            <div class="num" :style="{ color: c.color }">{{ c.value ?? '-' }}</div>

            <div class="label">{{ c.label }}</div>

          </div>

        </div>

        <div class="panel panel-chart">

          <div class="panel-title">近 30 天 新建 / 解决 / 差评</div>

          <div ref="trendRef" class="chart"></div>

        </div>

      </div>

    </div>

  </div>

</template>

<script setup lang="ts">

import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import * as echarts from 'echarts'

import { get } from '@/api/http'

const nowText = ref('')

const trendRef = ref<HTMLDivElement | null>(null) // script setup 模板 ref：必须声明同名变量，否则 echarts 初始化静默失败

const ov = ref<any>({})

const trend = ref<any[]>([])

const recentTickets = ref<any[]>([])

const urgentCount = ref(0)

// v2.12 默认 3 分钟刷新；仅接受合法选项值，历史旧值一律回默认

const _VALID_REFRESH = [10, 15, 30, 60, 120, 180]

const _stored = Number(localStorage.getItem('itops_screen_refresh') || 0)

const refreshSeconds = ref<number>(_VALID_REFRESH.includes(_stored) ? _stored : 180)

let chart: echarts.ECharts | null = null

let timer: number | null = null

const cards = computed(() => [

  // v2.11 第一行：本周工单（周一起）/ 当前未结 / 今日新建 / 今日解决

  { label: '本周工单', value: ov.value.week_created, color: '#e8eefc' },

  { label: '当前未结', value: ov.value.open, color: '#ffd666' },

  { label: '今日新建', value: ov.value.today_created ?? '-', color: '#69c0ff' },

  { label: '今日解决', value: ov.value.today_resolved ?? '-', color: '#95de64' },

  // 第二行：时效与质量

  { label: '平均响应(分)', value: ov.value.avg_first_response_minutes, color: '#b7eb8f' },

  { label: '平均解决(分)', value: ov.value.avg_resolution_minutes, color: '#ffe58f' },

  { label: '解决达标率', value: ov.value.resolution_sla_rate != null ? ov.value.resolution_sla_rate + '%' : '-', color: '#69c0ff' },

  { label: '满意度', value: ov.value.rating_avg != null ? ov.value.rating_avg + ' ★' : '-', color: '#ff9c6e' },

])

function renderTrend() {

  if (!trendRef.value) return

  chart = chart || echarts.init(trendRef.value)

  chart.resize() // 容器是 flex 弹性高度，渲染前同步一次实际尺寸

  const t = trend.value

  chart.setOption({

    backgroundColor: 'transparent',

    tooltip: { trigger: 'axis' },

    legend: { data: ['新建', '解决', '差评'], textStyle: { color: '#9fb3d1' }, top: 0 },

    grid: { left: 44, right: 20, top: 30, bottom: 26 },

    xAxis: { type: 'category', data: t.map((x: any) => x.date), axisLine: { lineStyle: { color: '#3a4a67' } }, axisLabel: { color: '#9fb3d1', hideOverlap: true } },

    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#2a3a55' } }, axisLabel: { color: '#9fb3d1' } },

    series: [

      { name: '新建', type: 'bar', data: t.map((x: any) => x.created), itemStyle: { color: '#409eff' }, barMaxWidth: 26 },

      { name: '解决', type: 'bar', data: t.map((x: any) => x.resolved), itemStyle: { color: '#67c23a' }, barMaxWidth: 26 },

      // v2.12 差评（≤2 星按解决日归桶）

      { name: '差评', type: 'bar', data: t.map((x: any) => x.bad_rated || 0), itemStyle: { color: '#f56c6c' }, barMaxWidth: 26 },

    ],

  })

}

async function load() {

  nowText.value = new Date().toLocaleString('zh-CN', { hour12: false })

  try {

    ov.value = await get('/api/stats/overview')

    const t = await get('/api/stats/trend?days=30')

    trend.value = t

    // v2.11 左侧工单列表：混合展示；改排序——未完结按时间倒序在上方，已完成沉底按完结时间倒序

    const list = await get('/api/tickets?page_size=60')

    const all = list.items.map((x: any) => ({ ...x, done: x.status === 'resolved' || x.status === 'closed' }))

    const openOnes = all.filter((x: any) => !x.done).sort((a: any, b: any) => (b.created_at || '').localeCompare(a.created_at || ''))

    const doneOnes = all.filter((x: any) => x.done).sort((a: any, b: any) => (b.resolved_at || b.created_at || '').localeCompare(a.resolved_at || a.created_at || ''))

    recentTickets.value = [...openOnes, ...doneOnes]

    urgentCount.value = (await get('/api/tickets?urgent=true&page_size=1')).total

    await nextTick()

    renderTrend()

  } catch { /* 静默重试 */ }

}

function onIntervalChange() {

  localStorage.setItem('itops_screen_refresh', String(refreshSeconds.value))

  restartTimer()

}

function restartTimer() {

  if (timer) window.clearInterval(timer)

  timer = null

  if (refreshSeconds.value > 0) timer = window.setInterval(load, refreshSeconds.value * 1000)

}

onMounted(() => {

  load()

  restartTimer()

  window.addEventListener('resize', resize)

})

function resize() {

  chart?.resize()

}

onBeforeUnmount(() => {

  if (timer) window.clearInterval(timer)

  window.removeEventListener('resize', resize)

  chart?.dispose()

})

</script>

<style scoped>

/* v2.11 全屏单页：铺满视口、无留白、无页面滚动（小屏媒体查询除外） */

.screen {

  width: 100vw; height: 100vh; overflow: hidden;

  background: #0f1726; display: flex; flex-direction: column;

  padding: 14px 20px 16px;

}

.screen-head { display: flex; align-items: center; gap: 14px; flex-shrink: 0; padding-bottom: 14px; }

.urgent-chip {

  background: #3a1d1d; border: 1px solid #a8070a; color: #ff9c6e;

  font-size: 12px; border-radius: 10px; padding: 1px 10px; white-space: nowrap;

}

.screen-time { color: #9fb3d1; font-size: 13px; flex: 1; min-width: 0; }

.refresh-box { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

.refresh-label { color: #9fb3d1; font-size: 12px; }

.panels { flex: 1; min-height: 0; display: flex; gap: 12px; }

.panel {

  background: #16223a; border: 1px solid #24344f; border-radius: 8px;

  padding: 12px 14px; display: flex; flex-direction: column; min-height: 0; min-width: 0;

}

.panel-list { flex: 1; }

.right-col { flex: 1.15; min-width: 0; display: flex; flex-direction: column; gap: 12px; min-height: 0; }

.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; flex-shrink: 0; }

.card {

  background: #16223a; border: 1px solid #24344f; border-radius: 8px;

  padding: 10px 6px; text-align: center; min-width: 0;

}

.num { font-size: 22px; font-weight: 700; line-height: 1.2; }

.label { color: #9fb3d1; font-size: 12px; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.panel-chart { flex: 1; min-height: 0; }

.panel-title { color: #c9d6ee; font-size: 14px; margin-bottom: 8px; flex-shrink: 0; }

.legend { font-size: 12px; }

.legend.red { color: #ff9c6e; }

.legend.green { color: #95de64; }

.chart { flex: 1; min-height: 0; }

.open-list { flex: 1; min-height: 0; overflow: auto; }

.open-row {

  display: flex; gap: 10px; padding: 8px 4px; border-bottom: 1px dashed #24344f;

  color: #c9d6ee; font-size: 13px; align-items: center; flex-shrink: 0; cursor: pointer;

}

.open-row:hover { background: #1c2a44; }

.open-row .no { width: 140px; flex-shrink: 0; font-weight: 600; }

.open-row .no.p-urgent { color: #ff6b5e; }

.open-row .no.p-high { color: #ffc069; }

.open-row .no.p-medium { color: #6fdd8b; }

.open-row .no.p-low { color: #9fb3d1; }

.open-row .ti { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.open-row .as { color: #9fb3d1; width: 80px; flex-shrink: 0; }

.open-row .st { color: #9fb3d1; width: 70px; flex-shrink: 0; text-align: right; }

.empty { color: #9fb3d1; text-align: center; margin: auto 0; }

/* 小屏兜底：允许纵向滚动，面板纵向堆叠 */

@media (max-width: 900px) {

  .screen { height: auto; min-height: 100vh; overflow: auto; }

  .cards { grid-template-columns: repeat(2, 1fr); }

  .panels { flex-direction: column; }

  .panel { min-height: 280px; }

}

</style>
