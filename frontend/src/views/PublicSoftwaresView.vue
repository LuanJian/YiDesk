<template>
  <div class="pub-page">
    <div class="pub-topbar">
      <div class="pub-brand">
        <el-icon :size="20" color="#2f6fed"><Opportunity /></el-icon>
        <span>YiDesk · 软件列表</span>
      </div>
      <div class="pub-actions">
        <el-button size="small" plain @click="goQuickTicket">提交其他工单</el-button>
        <el-button size="small" plain @click="router.push('/login')">返回登录</el-button>
      </div>
    </div>

    <div class="pub-body">
      <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px"
        :title="`公司允许安装的软件目录（${filtered.length} 款），点击「申请安装」发起安装工单；未列出的软件请联系 IT。`" />

      <el-card shadow="never" class="filter-card">
        <div class="filters">
          <el-input v-model="q" placeholder="搜索软件名称 / 描述" clearable style="width: 240px" />
          <!-- 第三十八批：软件类型筛选下拉 -->
          <el-select v-model="cat" placeholder="软件类型" clearable style="width: 160px">
            <el-option v-for="c in catOptions" :key="c" :label="c" :value="c" />
          </el-select>
          <el-select v-model="dept" placeholder="适用部门" clearable style="width: 160px">
            <el-option v-for="d in deptOptions" :key="d" :label="d" :value="d" />
          </el-select>
        </div>
      </el-card>

      <el-card shadow="never">
        <el-table :data="pagedSw" v-loading="loading" stripe>
          <el-table-column prop="name" label="软件名称" min-width="150">
            <template #default="{ row }"><b>{{ row.name }}</b></template>
          </el-table-column>
          <el-table-column prop="category" label="软件类型" width="95" />
          <el-table-column prop="license_type" label="授权类型" width="100">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ row.license_type }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="适用部门" width="120">
            <template #default="{ row }">
              <span v-if="row.departments.length">{{ row.departments.join("、") }}</span>
              <span v-else class="muted">全部部门</span>
            </template>
          </el-table-column>
          <!-- 描述列占最大宽度；超出折叠，点「查看更多」看完整介绍 -->
          <el-table-column prop="description" label="软件描述" min-width="380">
            <template #default="{ row }">
              <span class="desc-text">{{ row.description || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click="openDetail(row)">查看更多</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="swPage"
          :page-size="20"
          :total="filtered.length"
          layout="total, prev, pager, next"
          style="margin-top: 10px; justify-content: center"
        />
        <el-empty v-if="!loading && !filtered.length" description="没有符合条件的软件" :image-size="80" />
      </el-card>
    </div>

    <!-- 软件详情弹窗（完整介绍 + 申请安装入口） -->
    <el-dialog v-model="detailVisible" :title="current?.name || '软件详情'" width="560px">
      <template v-if="current">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="软件类型">{{ current.category }}</el-descriptions-item>
          <el-descriptions-item label="授权类型">{{ current.license_type }}</el-descriptions-item>
          <el-descriptions-item label="适用部门" :span="2">
            {{ current.departments.length ? current.departments.join("、") : "全部部门" }}
          </el-descriptions-item>
          <!-- 第二十三批+：匿名页不展示来源（下载地址仅工程师在管理台可见） -->
        </el-descriptions>
        <div class="detail-desc">{{ current.description || "暂无详细介绍" }}</div>
        <div style="text-align: center; margin-top: 14px">
          <el-button type="primary" @click="openApply(current)">申请安装此软件</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 申请安装弹窗：匿名提交，工单自动关联所选软件 -->
    <el-dialog v-model="applyVisible" title="软件安装申请" width="480px">
      <template v-if="applySw">
        <el-descriptions :column="1" border size="small" style="margin-bottom: 14px">
          <el-descriptions-item label="申请软件">{{ applySw.name }}（{{ applySw.category }} · {{ applySw.license_type }}）</el-descriptions-item>
        </el-descriptions>
        <el-input
          v-model="applyNote" type="textarea" :rows="3"
          placeholder="补充说明（选填）：安装对象/电脑位置、特殊版本要求等"
        />
        <div class="muted" style="margin-top: 8px">
          提交后自动创建「软件安装」工单并关联该软件，无需手动填写软件明细；凭工单编号 + 查询码可跟踪进度。
        </div>
      </template>
      <template #footer>
        <el-button @click="applyVisible = false">取消</el-button>
        <el-button type="primary" :loading="applying" @click="submitApply">提交申请</el-button>
      </template>
    </el-dialog>

    <!-- 提交结果：编号 + 查询码（已并入既有工单时提示合并） -->
    <el-dialog v-model="resultVisible" title="已提交" width="460px">
      <el-result v-if="result && result.merged_into" icon="success" :title="`已并入工单 ${result.merged_into.no}`">
        <template #sub-title>
          <p>您已有未完结的软件安装工单，本次申请已并入一并处理，避免重复安装。</p>
          <p class="muted">凭工单编号 {{ result.merged_into.no }} 可跟踪进度（登录后查看）</p>
        </template>
        <template #extra>
          <el-button type="primary" @click="resultVisible = false">完成</el-button>
        </template>
      </el-result>
      <el-result v-else-if="result" icon="success" :title="`已创建工单 ${result.no}`">
        <template #sub-title>
          <p>{{ result.title }}</p>
          <p class="muted">查询码：{{ result.followCode }}（请截图保存，凭 工单编号 + 查询码 跟踪进度）</p>
        </template>
        <template #extra>
          <el-button type="primary" @click="resultVisible = false">完成</el-button>
        </template>
      </el-result>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { get, post } from '@/api/http'

const router = useRouter()
const items = ref<any[]>([])
const loading = ref(false)
const q = ref('')
const dept = ref('')
const cat = ref('')

const detailVisible = ref(false)
const current = ref<any>(null)
const applyVisible = ref(false)
const applySw = ref<any>(null)
const applyNote = ref('')
const applying = ref(false)
const resultVisible = ref(false)
const result = ref<any>(null)

onMounted(async () => {
  loading.value = true
  try {
    const res = await get('/api/public/softwares')
    items.value = res.items
  } catch { /* 公开页静默 */ }
  loading.value = false
})

const deptOptions = computed(() => {
  const set = new Set<string>()
  items.value.forEach((s) => s.departments.forEach((d: string) => set.add(d)))
  return [...set]
})

const catOptions = computed(() => {
  const set = new Set<string>()
  items.value.forEach((s) => s.category && set.add(s.category))
  return [...set]
})

const filtered = computed(() => {
  const kw = q.value.trim().toLowerCase()
  return items.value.filter((s) => {
    if (cat.value && s.category !== cat.value) return false
    if (dept.value && !s.departments.includes(dept.value)) return false
    if (!kw) return true
    return s.name.toLowerCase().includes(kw) || (s.description || "").toLowerCase().includes(kw)
  })
})

const swPage = ref(1)
const pagedSw = computed(() => filtered.value.slice((swPage.value - 1) * 20, swPage.value * 20))

function openDetail(row: any) {
  current.value = row
  detailVisible.value = true
}

function openApply(row: any) {
  applySw.value = row
  applyNote.value = ""
  applyVisible.value = true
}

// 匿名发起软件安装工单：通用报修码准入 + software_id 关联（工单自动带软件快照）
async function submitApply() {
  if (!applySw.value) return
  applying.value = true
  try {
    const qr = await get('/api/public/general-qr')
    const res = await post('/api/tickets', {
      title: `软件安装申请：${applySw.value.name}`,
      description: applyNote.value.trim() || `申请安装 ${applySw.value.name}（${applySw.value.category}，${applySw.value.license_type}）`,
      category: '软件安装',
      priority: 'medium',
      qr_code: qr.code,
      software_id: applySw.value.id,
    })
    applyVisible.value = false
    detailVisible.value = false
    result.value = res
    resultVisible.value = true
  } catch (e: any) {
    ElMessage.error(e.message || '提交失败，请稍后重试')
  } finally {
    applying.value = false
  }
}

// PC 端提交其他类型工单：跳通用提单页
async function goQuickTicket() {
  try {
    const qr = await get('/api/public/general-qr')
    router.push(`/qr/${qr.code}`)
  } catch { /* ignore */ }
}
</script>

<style scoped>
.pub-page { min-height: 100vh; background: #f5f6f8; }
.pub-topbar {
  height: 52px; background: #1d2535; color: #fff; display: flex;
  align-items: center; justify-content: space-between; padding: 0 20px;
}
.pub-brand { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 15px; }
.pub-actions { display: flex; gap: 8px; }
.pub-body { max-width: 1100px; margin: 0 auto; padding: 18px 16px; }
.filter-card { margin-bottom: 14px; }
.filters { display: flex; gap: 10px; align-items: center; }
.muted { color: #909399; font-size: 12px; }
.desc-text {
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; line-height: 1.6;
}
.detail-desc {
  margin-top: 14px; padding: 14px 16px; line-height: 1.9; color: #303133;
  background: #fafbfc; border-radius: 8px; border: 1px solid #f0f2f5; font-size: 14px;
  white-space: pre-wrap; word-break: break-word;
}
</style>
