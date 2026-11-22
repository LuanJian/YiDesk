<template>

  <div>

    <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 14px"

      title="按分类配置工单模板：员工建单选择该分类时，动态渲染自定义字段（提交值随工单保存并在详情展示）。" />

    <div class="toolbar">

      <el-button type="primary" plain @click="openEditor(null)"><el-icon><Plus /></el-icon>&nbsp;新建模板</el-button>

    </div>

    <el-table :data="templates" size="small" >

      <el-table-column prop="name" label="模板名" min-width="140" />

      <el-table-column prop="category" label="分类" min-width="120" />

      <el-table-column prop="priority" label="默认优先级" min-width="100" />

      <el-table-column label="字段" min-width="220">

        <template #default="{ row }">

          <el-tag v-for="f in row.fields" :key="f.key" size="small" effect="plain" style="margin-right: 4px">

            {{ f.label }}{{ f.required ? '*' : '' }}

          </el-tag>

        </template>

      </el-table-column>

      <el-table-column label="启用" min-width="70">

        <template #default="{ row }">

          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '停用' }}</el-tag>

        </template>

      </el-table-column>

      <el-table-column label="操作" width="150" fixed="right">

        <template #default="{ row }">

          <el-button size="small" @click="openEditor(row)">编辑</el-button>

          <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>

        </template>

      </el-table-column>

    </el-table>

    <!-- 编辑弹窗 -->

    <el-dialog v-model="visible" :title="form.id ? '编辑模板' : '新建模板'" width="720px">

      <el-form label-width="90px">

        <el-form-item label="模板名" required>

          <el-input v-model="form.name" placeholder="如：网络故障单" />

        </el-form-item>

        <el-form-item label="分类" required>

          <el-select v-model="form.category" filterable allow-create style="width: 240px">

            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />

          </el-select>

        </el-form-item>

        <el-form-item label="默认优先级">

          <el-select v-model="form.priority" style="width: 160px">

            <el-option label="低" value="low" /><el-option label="中" value="medium" />

            <el-option label="高" value="high" /><el-option label="紧急" value="urgent" />

          </el-select>

        </el-form-item>

        <el-form-item label="主管审批">

          <el-switch v-model="form.require_approval" />

          <span class="casc-hint">开启后该分类建单先进入「待审批」，管理员通过才进入待受理（SLA 从通过起算）</span>

        </el-form-item>

        <el-form-item label="预估时长">

          <el-input-number v-model="form.estimated_minutes" :min="0" :max="1440" style="width: 140px" />

          <span class="casc-hint">分钟；≥ 派单阈值（dispatch.long_task_minutes）的工单触发长耗时隔离与打散（0=未设置）</span>

        </el-form-item>

        <el-form-item v-if="form.require_approval" label="AD 脚本">

          <el-input v-model="form.ad_script" placeholder="审批通过后触发的脚本名（可选，如 Unlock-AdAccount.ps1）" />

          <span class="casc-hint">脚本须位于 ad_integration 配置的授权目录内，由域内代理机（AdJobRunner.ps1）执行</span>

        </el-form-item>

      </el-form>

      <div class="fields-title">自定义字段</div>

      <el-table :data="form.fields" size="small">

        <el-table-column label="字段 key" min-width="130">

          <template #default="{ row }"><el-input v-model="row.key" size="small" placeholder="floor" /></template>

        </el-table-column>

        <el-table-column label="显示名" min-width="120">

          <template #default="{ row }"><el-input v-model="row.label" size="small" /></template>

        </el-table-column>

        <el-table-column label="类型" min-width="110">

          <template #default="{ row }">

            <el-select v-model="row.type" size="small">

              <el-option label="单行文本" value="text" />

              <el-option label="多行文本" value="textarea" />

              <el-option label="下拉选择" value="select" />

            </el-select>

          </template>

        </el-table-column>

        <el-table-column label="选项(逗号分隔)" min-width="150">

          <template #default="{ row }">

            <el-input v-model="row.optionsText" size="small" :disabled="row.type !== 'select'" placeholder="3F,5F" />

          </template>

        </el-table-column>

        <el-table-column label="必填" min-width="60">

          <template #default="{ row }"><el-switch v-model="row.required" size="small" /></template>

        </el-table-column>

        <el-table-column label="显示条件（v2.1 级联）" min-width="190">

          <template #default="{ row }">

            <div class="casc">

              <el-select v-model="row.ifField" size="small" clearable placeholder="参照字段" style="width: 88px">

                <el-option v-for="p in form.fields.filter((x: any) => x !== row && x.key)" :key="p.key" :label="p.label || p.key" :value="p.key" />

              </el-select>

              <el-select v-model="row.ifValues" size="small" multiple collapse-tags placeholder="等于以下值时显示" style="flex: 1" :disabled="!row.ifField">

                <el-option v-for="v in (form.fields.find((x: any) => x.key === row.ifField)?.optionsText || '').split(/[,，]/).map((s: string) => s.trim()).filter(Boolean)" :key="v" :label="v" :value="v" />

              </el-select>

            </div>

          </template>

        </el-table-column>

        <el-table-column label="" min-width="60">

          <template #default="{ $index }">

            <el-button size="small" type="danger" plain @click="form.fields.splice($index, 1)">删</el-button>

          </template>

        </el-table-column>

      </el-table>

      <el-button size="small" style="margin-top: 8px" @click="addField">+ 添加字段</el-button>

      <template #footer>

        <el-button @click="visible = false">取消</el-button>

        <el-button type="primary" @click="save">保存</el-button>

      </template>

    </el-dialog>

  </div>

</template>

<script setup lang="ts">

import { onMounted, reactive, ref } from 'vue'

import { ElMessage } from 'element-plus'

import { del, get, patch, post } from '@/api/http'

const categories = ref<string[]>([])

const templates = ref<any[]>([])

const visible = ref(false)

const form = reactive<any>({})

onMounted(async () => {

  try { categories.value = (await get('/api/admin/info')).categories || [] } catch { /* ignore */ }

  await load()

})

async function load() {

  try { templates.value = (await get('/api/admin/templates')).items } catch (e: any) { ElMessage.error(e.message) }

}

function addField() {

  form.fields.push({ key: '', label: '', type: 'text', optionsText: '', required: false, ifField: '', ifValues: [] })

}

function openEditor(row: any) {

  if (row) {

    Object.assign(form, {

      id: row.id, name: row.name, category: row.category, priority: row.priority,

      require_approval: !!row.require_approval, ad_script: row.ad_script || '',

      estimated_minutes: row.estimated_minutes || 0,

      fields: row.fields.map((f: any) => ({

        ...f,

        optionsText: (f.options || []).join(','),

        ifField: f.visible_if?.field || '',

        ifValues: f.visible_if?.in || [],

      })),

    })

  } else {

    Object.assign(form, { id: null, name: '', category: categories.value[0] || '', priority: 'medium', require_approval: false, ad_script: '', estimated_minutes: 0, fields: [] })

  }

  visible.value = true

}

async function save() {

  if (!form.name.trim() || !form.category) return ElMessage.warning('请填写模板名与分类')

  const fields = form.fields.map((f: any) => ({

    key: (f.key || '').trim(), label: (f.label || '').trim(), type: f.type,

    options: f.type === 'select' ? f.optionsText.split(/[,，]/).map((s: string) => s.trim()).filter(Boolean) : [],

    required: !!f.required,

    visible_if: f.ifField && (f.ifValues || []).length ? { field: f.ifField, in: f.ifValues } : null,

  }))

  if (fields.some((f: any) => !f.key || !f.label)) return ElMessage.warning('字段 key 与显示名不能为空')

  const body = { name: form.name, category: form.category, priority: form.priority, fields, enabled: true, require_approval: !!form.require_approval, ad_script: (form.ad_script || '').trim(), estimated_minutes: form.estimated_minutes || 0 }

  try {

    if (form.id) await patch(`/api/admin/templates/${form.id}`, body)

    else await post('/api/admin/templates', body)

    ElMessage.success('模板已保存')

    visible.value = false

    await load()

  } catch (e: any) { ElMessage.error(e.message) }

}

async function remove(row: any) {

  try { await del(`/api/admin/templates/${row.id}`); await load() } catch (e: any) { ElMessage.error(e.message) }

}

</script>

<style scoped>

.toolbar { margin-bottom: 12px; }

.fields-title { font-weight: 600; margin: 8px 0 6px; }

.casc { display: flex; gap: 4px; align-items: center; }

.casc-hint { font-size: 12px; color: #909399; margin-left: 8px; }

</style>
