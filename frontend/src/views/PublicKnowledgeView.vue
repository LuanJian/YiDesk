<template>
  <div class="pub-page">
    <div class="pub-topbar">
      <div class="pub-brand">
        <el-icon :size="20" color="#2f6fed"><Opportunity /></el-icon>
        <span>YiDesk · 常见问题</span>
      </div>
      <el-button size="small" plain @click="router.push('/login')">返回登录</el-button>
    </div>

    <div class="pub-body">
      <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px"
        title="遇到问题可先在此自查，无法解决再提交工单。" />

      <el-row :gutter="14">
        <!-- 第三十八批：PC 端放宽容器与左列表列宽，标题展示更完整 -->
        <el-col :xs="24" :md="9">
          <el-card shadow="never" class="list-card">
            <el-input v-model="q" placeholder="搜索标题 / 标签" clearable style="margin-bottom: 10px" />
            <el-empty v-if="!loading && !filtered.length" description="暂无常见问题" :image-size="70" />
            <div
              v-for="a in filtered" :key="a.id" class="kb-item"
              :class="{ active: current?.id === a.id }"
              @click="openDetail(a)"
            >
              <div class="kb-title">{{ a.title }}</div>
              <div class="kb-meta">
                <el-tag size="small" effect="plain">{{ a.category }}</el-tag>
                <span v-for="t in a.tags" :key="t" class="kb-tag">{{ t }}</span>
              </div>
            </div>
            <div v-if="loading" class="muted" style="text-align: center; padding: 20px">加载中…</div>
          </el-card>
        </el-col>
        <el-col :xs="24" :md="15">
          <el-card shadow="never" class="viewer">
            <template v-if="current">
              <div class="viewer-head">
                <div class="viewer-main">
                  <h2>{{ current.title }}</h2>
                  <div class="meta">
                    <el-tag size="small" effect="plain">{{ current.category }}</el-tag>
                    <span v-for="t in current.tags" :key="t" class="kb-tag">{{ t }}</span>
                  </div>
                  <div class="meta-info muted">
                    <span v-if="current.source">信息来源：{{ current.source }}</span>
                    <span v-else>更新于 {{ (current.updated_at || '').slice(0, 10) }}</span>
                  </div>
                </div>
              </div>
              <div v-if="current.problem" class="problem-block">
                <div class="problem-label">问题描述</div>
                <div class="pre-wrap">{{ current.problem }}</div>
              </div>
              <div class="solve-label">解决方法</div>
              <div class="content pre-wrap">{{ current.content }}</div>
            </template>
            <el-empty v-else description="选择左侧文章查看" />
          </el-card>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '@/api/http'

const router = useRouter()
const q = ref('')
const items = ref<any[]>([])
const current = ref<any>(null)
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const res = await get('/api/public/knowledge')
    items.value = res.items
  } catch { /* 公开页静默 */ }
  loading.value = false
})

const filtered = computed(() => {
  const kw = q.value.trim().toLowerCase()
  if (!kw) return items.value
  return items.value.filter(a => a.title.toLowerCase().includes(kw) || (a.tags || []).some((t: string) => t.toLowerCase().includes(kw)))
})

function openDetail(a: any) {
  current.value = a
  get(`/api/public/knowledge/${a.id}`).then((res) => { current.value = res }).catch(() => {})
}
</script>

<style scoped>
.pub-page { min-height: 100vh; background: #f5f6f8; }
.pub-topbar {
  height: 52px; background: #1d2535; color: #fff; display: flex;
  align-items: center; justify-content: space-between;
  padding: 0 20px;
}
.pub-brand { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 15px; }
.pub-body { max-width: 1440px; margin: 0 auto; padding: 18px 16px; }
.list-card :deep(.el-card__body) { padding: 14px; }
.kb-item {
  padding: 10px 12px; border: 1px solid #e6e8ee; border-radius: 8px;
  margin-bottom: 8px; cursor: pointer; transition: border-color 0.2s;
}
.kb-item:hover { border-color: #2f6fed; }
.kb-item.active { border-color: #2f6fed; background: #f0f7ff; }
.kb-title { font-weight: 500; margin-bottom: 6px; }
.kb-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.kb-tag { font-size: 12px; color: #5a6478; background: #f4f4f5; border-radius: 4px; padding: 1px 8px; }
.viewer { min-height: 420px; }
.viewer-head {
  display: flex; align-items: flex-start;
  padding-bottom: 14px; margin-bottom: 16px; border-bottom: 1px solid #f0f2f5;
}
.viewer-head h2 { margin: 0 0 12px; font-size: 18px; color: #1d2535; }
.meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.meta-info { margin-top: 10px; }
.problem-block {
  margin-bottom: 16px; padding: 12px 16px; background: #fdf6ec;
  border: 1px solid #faecd8; border-radius: 8px;
}
.problem-label, .solve-label { font-size: 12px; color: #909399; margin-bottom: 6px; font-weight: 600; }
.content {
  padding: 16px 18px; line-height: 1.9; color: #303133;
  background: #fafbfc; border-radius: 8px; border: 1px solid #f0f2f5;
  font-size: 14px;
}
.pre-wrap { white-space: pre-wrap; word-break: break-word; }
.muted { color: #909399; font-size: 12px; }
</style>
