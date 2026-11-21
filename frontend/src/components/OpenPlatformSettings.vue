<template>
  <div>
    <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px"
      title="Webhook：工单事件（创建/更新/解决/关闭）以 HMAC-SHA256 签名 POST 到订阅地址，失败自动重试最多 5 次；默认仅允许 https 且拒绝内网地址（config.yaml 可放开内网）。" />

    <!-- 第四十二批：排版统一为 el-card 卡片结构（Webhook 订阅 / 只读 API Key 两块） -->
    <el-card shadow="never" style="margin-bottom: 14px">
      <template #header>
        <div class="card-head">
          <b>Webhook 订阅</b>
          <el-button size="small" type="primary" plain @click="openEditor(null)"><el-icon><Plus /></el-icon>&nbsp;新建订阅</el-button>
        </div>
      </template>
      <el-table :data="subs" v-loading="loading" stripe size="small">
        <el-table-column prop="url" label="订阅地址" min-width="220" show-overflow-tooltip />
        <el-table-column label="事件" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="e in row.events" :key="e" size="small" effect="plain" style="margin-right: 4px">{{ e }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="secret_masked" label="签名密钥" min-width="130" />
        <el-table-column label="状态" min-width="70">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="testHook(row)">测试</el-button>
            <el-button size="small" @click="showDeliveries(row)">投递记录</el-button>
            <el-button size="small" @click="openEditor(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <b>只读 API Key</b>
          <span class="hint">供 ITSM/CRM 以 X-API-Key 头调用 GET /api/open/tickets 拉取工单；明文仅创建时显示一次</span>
          <div style="flex: 1"></div>
          <el-button size="small" type="primary" plain @click="openKey(null)"><el-icon><Key /></el-icon>&nbsp;新建 API Key</el-button>
        </div>
      </template>
      <el-table :data="keys" stripe size="small">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="key_masked" label="Key 指纹" min-width="160" />
        <el-table-column prop="created_at" label="创建时间" min-width="180">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN', { hour12: false }) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="100">
          <template #default="{ row }">
            <el-button size="small" type="danger" plain @click="removeKey(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑订阅 -->
    <el-dialog v-model="editorVisible" :title="form.id ? '编辑订阅' : '新建订阅'" width="560px">
      <el-form label-width="90px">
        <el-form-item label="订阅地址" required>
          <el-input v-model="form.url" placeholder="https://itsm.example.com/hook" />
        </el-form-item>
        <el-form-item label="签名密钥" required>
          <el-input v-model="form.secret" placeholder="HMAC-SHA256 密钥（≥8 位）" show-password />
        </el-form-item>
        <el-form-item label="订阅事件">
          <el-checkbox-group v-model="form.events">
            <el-checkbox v-for="e in EVENTS" :key="e" :value="e">{{ e }}</el-checkbox>
          </el-checkbox-group>
          <div class="hint">不选 = 订阅全部事件</div>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 投递记录 -->
    <el-dialog v-model="delivVisible" title="最近 20 条投递记录" width="720px">
      <el-table :data="deliveries" size="small" stripe>
        <el-table-column prop="event" label="事件" min-width="140" />
        <el-table-column prop="ticket_id" label="工单ID" min-width="80" />
        <el-table-column label="状态" min-width="90">
          <template #default="{ row }">
            <el-tag :type="({ sent: 'success', failed: 'danger' } as any)[row.status] || 'info'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="attempts" label="次数" min-width="60" />
        <el-table-column prop="last_error" label="错误" min-width="200" show-overflow-tooltip />
        <el-table-column prop="sent_at" label="投递时间" min-width="170">
          <template #default="{ row }">{{ row.sent_at ? new Date(row.sent_at).toLocaleString('zh-CN', { hour12: false }) : '-' }}</template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- API Key 明文展示 -->
    <el-dialog v-model="keyVisible" title="API Key 已创建" width="480px">
      <el-alert type="warning" :closable="false" title="请立即复制保存，关闭后无法再次查看" />
      <div class="key-box">{{ plaintextKey }}</div>
      <template #footer>
        <el-button type="primary" @click="keyVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { del, get, patch, post } from '@/api/http'

const EVENTS = ['ticket.created', 'ticket.updated', 'ticket.resolved', 'ticket.closed']

const loading = ref(false)
const subs = ref<any[]>([])
const keys = ref<any[]>([])
const editorVisible = ref(false)
const form = reactive<any>({})
const delivVisible = ref(false)
const deliveries = ref<any[]>([])
const keyVisible = ref(false)
const plaintextKey = ref('')

onMounted(load)

async function load() {
  loading.value = true
  try {
    subs.value = (await get('/api/webhooks')).items
    keys.value = (await get('/api/webhooks/api-keys')).items
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function openEditor(row: any) {
  Object.assign(form, row
    ? { id: row.id, url: row.url, secret: '', events: [...row.events], enabled: row.enabled }
    : { id: null, url: '', secret: '', events: [...EVENTS], enabled: true })
  editorVisible.value = true
}

async function save() {
  if (!form.url.trim()) return ElMessage.warning('请填写订阅地址')
  if (form.secret && form.secret.length < 8) return ElMessage.warning('密钥至少 8 位')
  try {
    if (form.id) {
      const payload: any = { url: form.url, events: form.events, enabled: form.enabled }
      if (form.secret) payload.secret = form.secret  // 留空不改密钥
      await patch(`/api/webhooks/${form.id}`, payload)
    } else {
      await post('/api/webhooks', { url: form.url, secret: form.secret, events: form.events, enabled: form.enabled })
    }
    ElMessage.success('已保存')
    editorVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`确认删除订阅「${row.url}」？`, '删除确认', { type: 'warning' })
  try {
    await del(`/api/webhooks/${row.id}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function testHook(row: any) {
  try {
    const res = await post(`/api/webhooks/${row.id}/test`)
    if (res.sent > 0) ElMessage.success('测试投递已发送（可在投递记录查看结果）')
    else ElMessage.warning('已生成投递任务但未立即送达，请查看投递记录')
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function showDeliveries(row: any) {
  try {
    deliveries.value = (await get(`/api/webhooks/${row.id}/deliveries`)).items
    delivVisible.value = true
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function openKey(_row: any) {
  try {
    const { value } = await ElMessageBox.prompt('Key 名称（如：ITSM 集成）', '新建 API Key', {
      inputValidator: (v: string) => !!v.trim() || '请填写名称',
      confirmButtonText: '生成', cancelButtonText: '取消',
    })
    const res = await post('/api/webhooks/api-keys', { name: value.trim() })
    plaintextKey.value = res.key
    keyVisible.value = true
    await load()
  } catch (e: any) {
    if (e !== 'cancel' && e?.message) ElMessage.error(e.message)
  }
}

async function removeKey(row: any) {
  await ElMessageBox.confirm(`确认删除 Key「${row.name}」？外部系统将立即失去访问权限。`, '删除确认', { type: 'warning' })
  try {
    await del(`/api/webhooks/api-keys/${row.id}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.card-head { display: flex; align-items: center; gap: 10px; }
.hint { color: #909399; font-size: 12px; }
.key-box {
  margin-top: 12px; padding: 12px; background: #f5f7fa; border-radius: 8px;
  font-family: monospace; white-space: nowrap; overflow-x: auto; user-select: all;
}
</style>
