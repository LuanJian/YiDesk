<template>

  <div>

    <!-- 操作审计并入系统设置（原独立页迁回），置于登录日志与 SLA 规则之间 -->

    <div class="toolbar">

      <el-date-picker

        v-model="auditRange"

        type="daterange"

        value-format="YYYY-MM-DD"

        range-separator="至"

        start-placeholder="开始"

        end-placeholder="结束"

        style="width: 260px"

        @change="loadAudit"

      />

      <el-select v-model="auditType" placeholder="全部类型" clearable style="width: 140px" @change="loadAudit">

        <el-option v-for="(label, k) in AUDIT_TYPES" :key="k" :label="label" :value="k" />

      </el-select>

      <el-select v-model="auditActor" placeholder="全部操作人" clearable filterable style="width: 140px" @change="loadAudit">

        <el-option v-for="u in users" :key="u.id" :label="u.name || u.username" :value="u.id" />

      </el-select>

      <el-input v-model="auditQ" placeholder="搜索内容 / 工单号" clearable style="width: 240px" @keyup.enter="loadAudit" />

      <el-button type="primary" @click="loadAudit">查询</el-button>

    </div>

    <!-- 明细表包进 el-card 外框，与登录日志/用户管理表格样式统一 -->

    <el-card shadow="never">

      <!-- 完整工单变动明细；移除右上角视图切换（左侧筛选已覆盖），恢复平铺单表 -->

      <el-table :data="auditEvents" v-loading="auditLoading" size="small" stripe>

        <el-table-column label="类型" width="100">

          <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.audit_label }}</el-tag></template>

        </el-table-column>

        <el-table-column label="时间" width="150">

          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN', { hour12: false }) }}</template>

        </el-table-column>

        <el-table-column label="工单" min-width="130">

          <template #default="{ row }">

            <el-link type="primary" :underline="false" @click="$router.push(`/tickets/${row.ticket_id}`)">{{ row.ticket_no }}</el-link>

          </template>

        </el-table-column>

        <el-table-column label="操作人" width="100">

          <template #default="{ row }">{{ row.actor }}</template>

        </el-table-column>

        <el-table-column prop="content" label="内容" min-width="420" show-overflow-tooltip />

      </el-table>

      <el-pagination

        v-model:current-page="auditPage"

        :page-size="20"

        :total="auditTotal"

        layout="total, prev, pager, next"

        style="margin-top: 12px; justify-content: center"

        @current-change="loadAudit(false)"

      />

    </el-card>

  </div>

</template>

<script setup lang="ts">

import { onMounted, ref } from 'vue'

import { ElMessage } from 'element-plus'

import { get } from '@/api/http'

const AUDIT_TYPES: Record<string, string> = {

  edit: '编辑工单', assign: '指派/改派', sla_suspend: 'SLA 挂起',

  sla_resume: 'SLA 恢复', merge: '合并', dispatch: '自动派单',

}

const auditRange = ref<[string, string] | null>(null)

const auditType = ref('')

const auditActor = ref<number | null>(null)

const auditQ = ref('')

const auditEvents = ref<any[]>([])

const auditTotal = ref(0)

const auditPage = ref(1)

const auditLoading = ref(false)

const users = ref<any[]>([])

function loadAudit(reset = true) {

  if (reset) auditPage.value = 1

  const params = new URLSearchParams()

  if (auditRange.value) {

    params.set('start', auditRange.value[0])

    params.set('end', auditRange.value[1])

  }

  if (auditType.value) params.set('audit_type', auditType.value)

  if (auditActor.value) params.set('actor_id', String(auditActor.value))

  if (auditQ.value) params.set('q', auditQ.value)

  params.set('page', String(auditPage.value))

  auditLoading.value = true

  get(`/api/admin/audit/events?${params}`)

    .then((e) => {

      auditEvents.value = e.items

      auditTotal.value = e.total

    })

    .catch((err: any) => ElMessage.error(err.message))

    .finally(() => (auditLoading.value = false))

}

onMounted(() => {

  loadAudit()

  get('/api/users').then((res) => (users.value = res.items)).catch(() => {})

})

</script>

<style scoped>

.toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }

</style>
