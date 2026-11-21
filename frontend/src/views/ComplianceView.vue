<template>
  <div>
    <!-- 总览 -->
    <el-row :gutter="14">
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value" :style="{ color: rateColor }">{{ summary.overall_rate != null ? summary.overall_rate + '%' : '—' }}</div>
          <div class="stat-label">整体合规率（按各终端最新检查结果）</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value" style="color: #f56c6c">{{ summary.noncompliant?.length ?? 0 }}</div>
          <div class="stat-label">不合规项（按严重度排序）</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value">{{ summary.terminals_total ?? '—' }}</div>
          <div class="stat-label">已登记终端（来自资产管理）</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never" class="stat-card">
          <el-button type="primary" plain style="width: 100%" @click="scanVisible = true">
            <el-icon><Plus /></el-icon>&nbsp;发起巡检批次
          </el-button>
          <div class="stat-label" style="margin-top: 8px">批次用于组织一轮巡检的记录归档</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 第四十一批：不合规清单移至上方整行（详情单行完整显示），巡检项合规率移下方并统一 peak-line 图表风格 -->
    <el-row :gutter="14">
      <el-col :span="24">
        <el-card shadow="never" class="block">
          <template #header><b>不合规清单</b></template>
          <el-table :data="pagedNC" size="small" stripe max-height="420">
            <el-table-column prop="asset_tag" label="终端" min-width="110" />
            <el-table-column prop="asset_name" label="名称" min-width="120" show-overflow-tooltip class-name="col-sm-hide" />
            <el-table-column prop="item_name" label="巡检项" min-width="170" show-overflow-tooltip />
            <el-table-column label="严重度" min-width="75">
              <template #default="{ row }">
                <el-tag size="small" :type="({ 高: 'danger', 中: 'warning', 低: 'info' } as any)[row.severity]">{{ row.severity }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="detail" label="详情" min-width="360" show-overflow-tooltip class-name="col-sm-hide" />
            <el-table-column label="操作" width="95" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="danger" plain @click="remediate(row)">整改建单</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="ncPage"
            :page-size="20"
            :total="(summary.noncompliant || []).length"
            layout="total, prev, pager, next"
            style="margin-top: 10px; justify-content: center"
          />
          <el-empty v-if="!(summary.noncompliant || []).length" description="全部合规 🎉" :image-size="70" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 各巡检项合规率（peak-line 风格与会议管理图表统一） -->
    <el-card shadow="never" class="block">
      <template #header><b>巡检项合规率</b></template>
      <div class="compliance-panel">
        <div v-for="p in summary.per_item || []" :key="p.item_id" class="c-line">
          <span class="c-name">
            <!-- 第四十二批：状态（严重度+方式）前置 -->
            <el-tag size="small" :type="({ 高: 'danger', 中: 'warning', 低: 'info' } as any)[p.severity]" effect="plain">{{ p.severity }}</el-tag>
            <span class="muted">{{ p.method === 'agent' ? '代理' : '人工' }}</span>
            <b :title="p.name">{{ p.name }}</b>
          </span>
          <el-progress
            v-if="p.total"
            :percentage="p.rate ?? 0"
            :stroke-width="8"
            :show-text="false"
            :color="p.rate != null && p.rate >= 90 ? '#67c23a' : p.rate != null && p.rate >= 70 ? '#e6a23c' : '#f56c6c'"
            style="flex: 1"
          />
          <span class="c-num">{{ p.compliant }}/{{ p.total }}</span>
        </div>
        <div v-for="p in (summary.per_item || []).filter(x => !x.total)" :key="'e' + p.item_id" class="muted" style="font-size: 12px">
          「{{ p.name }}」暂无检查记录（等待代理上报或人工登记）
        </div>
        <el-empty v-if="!(summary.per_item || []).length" description="暂无巡检数据，配置 API Key 后用代理脚本上报，或手工登记" :image-size="70" />
      </div>
    </el-card>

    <!-- 代理脚本说明（第三十九批：详细部署步骤移 README，界面留一句指引；第四十二批：字体与全站说明文字统一 12px） -->
    <el-card shadow="never" class="block">
      <template #header><b>终端代理脚本（Windows PowerShell）</b></template>
      <el-alert type="warning" :closable="false" show-icon class="agent-tip"
        title="部署步骤见 README「终端合规巡检」章节；脚本自动检查病毒库/补丁/磁盘加密，人工项在上方「手工登记」。" />
    </el-card>

    <!-- 巡检批次弹窗 -->
    <el-dialog v-model="scanVisible" title="发起巡检批次" width="480px">
      <el-form label-width="80px">
        <el-form-item label="批次名" required>
          <el-input v-model="scanForm.name" placeholder="如：2026Q4 安全巡检" />
        </el-form-item>
        <el-form-item label="范围说明">
          <el-input v-model="scanForm.scope_note" placeholder="如：全部 Windows 终端" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="scanVisible = false">取消</el-button>
        <el-button type="primary" @click="createScan">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { get, post } from '@/api/http'

const ncPage = ref(1)
const pagedNC = computed(() => (summary.value.noncompliant || []).slice((ncPage.value - 1) * 20, ncPage.value * 20))
const summary = ref<any>({})
const scanVisible = ref(false)
const scanForm = reactive({ name: '', scope_note: '' })

const rateColor = computed(() => {
  const r = summary.value.overall_rate
  if (r == null) return '#1d2535'
  return r >= 90 ? '#67c23a' : r >= 70 ? '#e6a23c' : '#f56c6c'
})

onMounted(load)

async function load() {
  try {
    summary.value = await get('/api/compliance/summary')
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function createScan() {
  if (!scanForm.name.trim()) return ElMessage.warning('请填写批次名')
  try {
    await post('/api/compliance/scans', scanForm)
    ElMessage.success('批次已创建；代理脚本上报时可携带 scan_id 归档')
    scanVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function remediate(row: any) {
  try {
    await post('/api/compliance/remediation-ticket', {
      asset_id: row.asset_id,
      record_ids: [row.record_id],
    })
    ElMessage.success(`已创建整改工单（${row.asset_tag} · ${row.item_name}），可在工单台查看`)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.stat-card { margin-bottom: 14px; min-height: 96px; }
.stat-value { font-size: 26px; font-weight: 700; }
.stat-label { font-size: 12px; color: #909399; margin-top: 4px; line-height: 1.6; }
.block { margin-bottom: 14px; }
.muted { color: #909399; font-size: 12px; }
/* 第四十一批：巡检项合规率行样式（与会议管理 peak-line 图表风格统一） */
.compliance-panel { background: #fafbfc; border: 1px solid #f0f2f5; border-radius: 8px; padding: 14px 16px; }
.c-line { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.c-line:last-child { margin-bottom: 0; }
.c-name { flex-shrink: 0; width: 300px; display: flex; align-items: center; gap: 6px; overflow: hidden; font-size: 12px; }
.c-name .muted { white-space: nowrap; }
.c-name b { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12px; font-weight: 500; }
.c-num { flex-shrink: 0; white-space: nowrap; font-size: 12px; color: #5a6478; width: 52px; text-align: right; }
/* 第四十二批：部署信息字体与全站说明文字统一（12px） */
.agent-tip :deep(.el-alert__title) { font-size: 12px; line-height: 1.6; }
</style>
