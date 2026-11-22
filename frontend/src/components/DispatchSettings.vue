<template>

  <div>

    <!-- 说明合并为单行 title（原 title+description 两行） -->

    <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 14px"

      :title="`智能分派${info.dispatch_auto_assign ? '已开启' : '未开启'}（config.yaml: dispatch.auto_assign），建单时按「分类规则 → 值班表」顺序自动指派工程师`" />

    <!-- 分类分派规则（v2.11 工程师视角：选人 → 勾分类） -->

    <h4>分类分派规则（选择工程师，勾选其负责的分类；勾选后该工程师进入此分类的轮询池）</h4>

    <el-card shadow="never" class="assign-card">

      <div class="assign-editor">

        <el-select

          v-model="pickedEngineer" filterable placeholder="选择工程师" size="small"

          style="width: 220px; flex-shrink: 0" @change="onPickEngineer"

        >

          <el-option v-for="e in activeEngineers" :key="e.id" :label="e.name || e.username" :value="e.id" />

        </el-select>

        <div class="assign-cats">

          <el-checkbox-group v-model="pickedCategories" :disabled="!pickedEngineer">

            <el-checkbox-button v-for="c in categories" :key="c" :value="c" size="small">{{ c }}</el-checkbox-button>

          </el-checkbox-group>

        </div>

        <div class="assign-actions">

          <el-button size="small" text type="primary" :disabled="!pickedEngineer" @click="pickedCategories = [...categories]">全选</el-button>

          <el-button size="small" text :disabled="!pickedEngineer" @click="pickedCategories = []">清空</el-button>

          <el-button size="small" type="primary" :disabled="!pickedEngineer" :loading="savingAssign" @click="saveEngineerCats">保存</el-button>

        </div>

      </div>

      <div class="muted" style="font-size: 12px">取消勾选并保存 = 该工程师退出此分类轮询池；某分类无人负责时自动移除该分类规则（回退值班表轮询）。</div>

    </el-card>

    <el-table :data="engineerSummary" size="small" style="margin-top: 10px">

      <el-table-column label="工程师" width="160">

        <template #default="{ row }">{{ row.name }}</template>

      </el-table-column>

      <el-table-column label="负责分类">

        <template #default="{ row }">

          <template v-if="row.categories.length">

            <el-tag v-for="c in row.categories" :key="c" size="small" style="margin-right: 6px">{{ c }}</el-tag>

          </template>

          <span v-else class="muted">未分配（走值班表轮询）</span>

        </template>

      </el-table-column>

      <el-table-column label="操作" width="80">

        <template #default="{ row }">

          <el-button size="small" text type="primary" @click="editEngineer(row.id)">编辑</el-button>

        </template>

      </el-table-column>

    </el-table>

    <el-divider />

    <!-- 关键词派单规则（v2.7） -->

    <h4>关键词派单规则（标题/描述命中 → 直派工程师或改判分类，优先于分类规则）</h4>

    <el-table :data="keywordRules" size="small">

      <el-table-column label="名称" min-width="120">

        <template #default="{ row }"><el-input v-model="row.name" size="small" placeholder="规则名" /></template>

      </el-table-column>

      <el-table-column label="关键词（逗号分隔）" min-width="160">

        <template #default="{ row }"><el-input v-model="row.keywords_text" size="small" placeholder="投屏,投影仪" /></template>

      </el-table-column>

      <el-table-column label="动作" min-width="280">

        <template #default="{ row }">

          <div style="display: flex; gap: 6px; align-items: center">

            <el-select v-model="row.action_type" size="small" style="width: 110px; flex-shrink: 0">

              <el-option label="直派工程师" value="engineer" />

              <el-option label="改判分类" value="category" />

            </el-select>

            <el-select v-if="row.action_type === 'engineer'" v-model="row.target_engineer_id" filterable size="small" style="flex: 1; min-width: 0" placeholder="工程师">

              <el-option v-for="e in engineers" :key="e.id" :label="e.name || e.username" :value="e.id" />

            </el-select>

            <el-select v-if="row.action_type === 'category'" v-model="row.target_category" filterable allow-create size="small" style="flex: 1; min-width: 0" placeholder="分类">

              <el-option v-for="c in categories" :key="c" :label="c" :value="c" />

            </el-select>

          </div>

        </template>

      </el-table-column>

      <el-table-column label="优先级" width="90">

        <template #default="{ row }"><el-input-number v-model="row.priority" size="small" :min="1" :max="999" controls-position="right" style="width: 70px" /></template>

      </el-table-column>

      <el-table-column label="启用" width="60">

        <template #default="{ row }"><el-switch v-model="row.enabled" size="small" /></template>

      </el-table-column>

      <el-table-column label="操作" width="130">

        <template #default="{ row }">

          <el-button size="small" type="primary" plain @click="saveKeyword(row)">保存</el-button>

          <el-button v-if="row.id" size="small" type="danger" plain @click="removeKeyword(row)">删</el-button>

        </template>

      </el-table-column>

    </el-table>

    <el-button size="small" style="margin-top: 10px" @click="addKeywordRow">+ 新增关键词规则</el-button>

    <el-divider />

    <!-- 组织架构路由（v2.7） -->

    <h4>组织架构路由（提单部门 → 工程师池，优先于分类规则）</h4>

    <el-table :data="deptRoutes" size="small">

      <el-table-column label="提单部门" min-width="160">

        <!-- 部门字典已统一维护，改下拉选择（allow-create 兼容未沉淀的新部门） -->

        <template #default="{ row }">

          <el-select v-model="row.department" size="small" filterable allow-create default-first-option placeholder="选择提单部门" style="width: 100%">

            <el-option v-for="d in orgDepts" :key="d" :label="d" :value="d" />

          </el-select>

        </template>

      </el-table-column>

      <el-table-column label="处理工程师（该部门工单派给他们）">

        <template #default="{ row }">

          <el-select v-model="row.engineer_ids" multiple filterable size="small" style="width: 100%">

            <el-option v-for="e in engineers" :key="e.id" :label="e.name || e.username" :value="e.id" />

          </el-select>

        </template>

      </el-table-column>

      <el-table-column label="启用" width="70">

        <template #default="{ row }"><el-switch v-model="row.enabled" size="small" /></template>

      </el-table-column>

      <el-table-column label="操作" width="140">

        <template #default="{ row }">

          <el-button size="small" type="primary" plain @click="saveDeptRoute(row)">保存</el-button>

          <el-button v-if="row.id" size="small" type="danger" plain @click="removeDeptRoute(row)">删</el-button>

        </template>

      </el-table-column>

    </el-table>

    <el-button size="small" style="margin-top: 10px" @click="addDeptRouteRow">+ 新增部门路由</el-button>

    <el-divider />

    <!-- 值班表 -->

    <h4>值班表（无分类规则时按当日值班轮询）</h4>

    <el-table :data="dutyRules" size="small">

      <el-table-column prop="weekday_label" label="时间" min-width="90" />

      <el-table-column label="值班工程师">

        <template #default="{ row }">

          <el-select v-model="row.engineer_ids" multiple filterable size="small" style="width: 100%" @change="saveDuty(row)">

            <el-option v-for="e in engineers" :key="e.id" :label="e.name || e.username" :value="e.id" />

          </el-select>

        </template>

      </el-table-column>

    </el-table>

  </div>

</template>

<script setup lang="ts">

import { computed, onMounted, ref } from 'vue'

import { ElMessage } from 'element-plus'

import { get, patch, post, put, del } from '@/api/http'

const info = ref<any>({})

const categories = ref<string[]>([])

const engineers = ref<any[]>([])

const dispatchRules = ref<any[]>([])

const dutyRules = ref<any[]>([])

const keywordRules = ref<any[]>([])

const deptRoutes = ref<any[]>([])

const orgDepts = ref<string[]>([])

// ---- 分类分派规则·工程师视角（v2.11） ----

const pickedEngineer = ref<number | null>(null)

const pickedCategories = ref<string[]>([])

const savingAssign = ref(false)

const engineerCatsMap = computed<Record<number, string[]>>(() => {

  const m: Record<number, string[]> = {}

  for (const r of dispatchRules.value) {

    for (const id of r.engineer_ids || []) {

      (m[id] = m[id] || []).push(r.category)

    }

  }

  return m

})

const activeEngineers = computed(() => engineers.value.filter((e) => e.is_active !== false))

const engineerSummary = computed(() => {

  const rows = activeEngineers.value.map((e) => ({ id: e.id, name: e.name || e.username, categories: engineerCatsMap.value[e.id] || [] }))

  // 兜底：规则里存在但用户列表缺失的工程师（如管理员）也展示

  for (const [id, cats] of Object.entries(engineerCatsMap.value)) {

    if (!rows.some((r) => r.id === Number(id))) rows.push({ id: Number(id), name: `用户 #${id}`, categories: cats })

  }

  return rows

})

function onPickEngineer(id: number) {

  pickedCategories.value = [...(engineerCatsMap.value[id] || [])]

}

function editEngineer(id: number) {

  pickedEngineer.value = id

  onPickEngineer(id)

}

async function saveEngineerCats() {

  if (!pickedEngineer.value) return

  savingAssign.value = true

  try {

    await put('/api/admin/dispatch-v2/category-rules', { engineer_id: pickedEngineer.value, categories: pickedCategories.value })

    ElMessage.success('分类分工已保存')

    await loadDispatch()

    // 保存后同步勾选态（服务端可能合并/清理了规则）

    pickedCategories.value = [...(engineerCatsMap.value[pickedEngineer.value] || [])]

  } catch (e: any) { ElMessage.error(e.message) } finally { savingAssign.value = false }

}

onMounted(async () => {

  try { info.value = await get('/api/admin/info'); categories.value = info.value.categories || [] } catch { /* ignore */ }

  try { engineers.value = (await get('/api/users?role=engineer')).items } catch { /* ignore */ }

  await loadDispatch()

  await loadDuty()

  await loadKeyword()

  await loadDeptRoute()

})

// ---- 关键词规则（v2.7） ----

async function loadKeyword() {

  try {

    keywordRules.value = (await get('/api/admin/dispatch-v2/keyword-rules')).items.map((r: any) => ({

      ...r, keywords_text: r.keywords.join(','), action_type: r.target_engineer_id ? 'engineer' : 'category',

    }))

  } catch (e: any) { ElMessage.error(e.message) }

}

function addKeywordRow() {

  keywordRules.value.push({ id: null, name: '', keywords_text: '', action_type: 'engineer', target_engineer_id: null, target_category: '', priority: 100, enabled: true, note: '' })

}

async function saveKeyword(row: any) {

  const kws = row.keywords_text.split(/[,，]/).map((s: string) => s.trim()).filter(Boolean)

  if (!kws.length) return ElMessage.warning('请填写关键词')

  try {

    const body = { name: row.name, keywords: kws, target_engineer_id: row.action_type === 'engineer' ? row.target_engineer_id : null,

                   target_category: row.action_type === 'category' ? row.target_category : null,

                   priority: row.priority, enabled: row.enabled, note: row.note || '' }

    if (row.id) await patch(`/api/admin/dispatch-v2/keyword-rules/${row.id}`, body)

    else await post('/api/admin/dispatch-v2/keyword-rules', body)

    ElMessage.success('关键词规则已保存')

    await loadKeyword()

  } catch (e: any) { ElMessage.error(e.message) }

}

async function removeKeyword(row: any) {

  try { await del(`/api/admin/dispatch-v2/keyword-rules/${row.id}`); await loadKeyword() } catch (e: any) { ElMessage.error(e.message) }

}

// ---- 组织架构路由（v2.7） ----

async function loadDeptRoute() {

  try { deptRoutes.value = (await get('/api/admin/dispatch-v2/dept-routes')).items } catch (e: any) { ElMessage.error(e.message) }

  try { orgDepts.value = (await get('/api/org-tags')).depts || [] } catch { /* 部门字典失败不阻塞 */ }

}

function addDeptRouteRow() {

  deptRoutes.value.push({ id: null, department: '', engineer_ids: [], enabled: true })

}

async function saveDeptRoute(row: any) {

  if (!row.department?.trim()) return ElMessage.warning('请填写部门名')

  if (!row.engineer_ids.length) return ElMessage.warning('请选择工程师')

  try {

    if (row.id) await patch(`/api/admin/dispatch-v2/dept-routes/${row.id}`, { department: row.department, engineer_ids: row.engineer_ids, enabled: row.enabled })

    else await post('/api/admin/dispatch-v2/dept-routes', { department: row.department, engineer_ids: row.engineer_ids, enabled: row.enabled })

    ElMessage.success('部门路由已保存')

    await loadDeptRoute()

  } catch (e: any) { ElMessage.error(e.message) }

}

async function removeDeptRoute(row: any) {

  try { await del(`/api/admin/dispatch-v2/dept-routes/${row.id}`); await loadDeptRoute() } catch (e: any) { ElMessage.error(e.message) }

}

async function loadDispatch() {

  try { dispatchRules.value = (await get('/api/admin/dispatch-rules')).items } catch (e: any) { ElMessage.error(e.message) }

}

async function loadDuty() {

  try {

    dutyRules.value = (await get('/api/admin/duty-rules')).items

    if (!dutyRules.value.length) {

      dutyRules.value = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map((l, i) => ({ weekday: i, weekday_label: l, engineer_ids: [] }))

    }

  } catch (e: any) { ElMessage.error(e.message) }

}

async function saveDuty(row: any) {

  try {

    await put('/api/admin/duty-rules', { weekday: row.weekday, engineer_ids: row.engineer_ids })

    ElMessage.success(`${row.weekday_label} 值班已保存`)

  } catch (e: any) { ElMessage.error(e.message) }

}

</script>

<style scoped>

h4 { margin: 4px 0 10px; color: #303133; }

.assign-card :deep(.el-card__body) { padding: 14px; }

.assign-editor { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 8px; }

.assign-cats { flex: 1; min-width: 0; }

.assign-cats :deep(.el-checkbox-button__inner) { padding: 5px 10px; }

.assign-actions { display: flex; flex-shrink: 0; }

.muted { color: #909399; }

</style>
