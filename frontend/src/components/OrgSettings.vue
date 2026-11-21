<template>
  <div>
    <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px"
      title="部门为全局字典：软件目录与用户管理引用此处；登记软件时的新部门会自动沉淀，也可手动维护。" />

    <el-row :gutter="14">
      <el-col v-for="col in columns" :key="col.type" :span="24">
        <el-card shadow="never" class="org-card">
          <template #header>
            <div class="org-head">
              <b>{{ col.label }}</b>
              <el-input
                v-model="col.draft" size="small" :placeholder="`新增${col.label}名称`"
                style="width: 200px" @keyup.enter="add(col)"
              >
                <template #append>
                  <el-button @click="add(col)">添加</el-button>
                </template>
              </el-input>
            </div>
          </template>
          <div class="org-tags">
            <span v-for="t in items.filter((x) => x.type === col.type)" :key="t.id" class="org-tag">
              {{ t.name }}
              <el-icon class="del" @click="remove(t)"><Close /></el-icon>
            </span>
            <span v-if="!items.some((x) => x.type === col.type)" class="muted">暂无{{ col.label }}，请添加</span>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { del, get, post } from '@/api/http'

const items = ref<any[]>([])
const columns = reactive([
  { type: 'dept', label: '部门', draft: '' },
])

onMounted(load)

async function load() {
  try {
    const res = await get('/api/org-tags')
    items.value = res.items
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function add(col: { type: string; label: string; draft: string }) {
  const name = col.draft.trim()
  if (!name) return ElMessage.warning(`请输入${col.label}名称`)
  try {
    await post('/api/org-tags', { type: col.type, name })
    ElMessage.success(`已添加${col.label}「${name}」`)
    col.draft = ''
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function remove(t: any) {
  try {
    await ElMessageBox.confirm(`删除${t.type_label}「${t.name}」？已有引用（如软件目录）不受影响，仅从字典移除。`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await del('/api/org-tags/' + t.id)
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.org-card { margin-bottom: 14px; }
.org-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.org-tags { display: flex; flex-wrap: wrap; gap: 8px; min-height: 32px; }
.org-tag {
  display: inline-flex; align-items: center; gap: 6px;
  background: #f4f4f5; border-radius: 6px; padding: 6px 12px; font-size: 13px;
}
.org-tag .del { cursor: pointer; color: #909399; }
.org-tag .del:hover { color: #f56c6c; }
.muted { color: #909399; font-size: 13px; }
</style>
