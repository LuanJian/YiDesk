<template>
  <el-tabs v-model="tab" class="settings" @tab-change="onTabChange">
    <!-- 用户管理 -->
    <el-tab-pane label="用户管理" name="users">      <div class="toolbar">
        <el-input v-model="userQ" placeholder="搜索用户" clearable style="width: 200px" @keyup.enter="loadUsers" @clear="loadUsers" />
        <!-- v2.12 新增筛选：角色 / 岗位 / 部门 -->
        <el-select v-model="userFilter.role" placeholder="全部角色" clearable style="width: 140px" @change="loadUsers">
          <el-option label="管理员" value="admin" />
          <el-option label="工程师" value="engineer" />
          <el-option label="员工" value="employee" />
        </el-select>
        <el-select v-model="userFilter.ops_type" placeholder="全部岗位" clearable style="width: 140px" @change="loadUsers">
          <el-option label="远程运维" value="remote" />
          <el-option label="现场运维" value="field" />
          <el-option label="其他" value="other" />
        </el-select>
        <el-select v-model="userFilter.department" placeholder="全部部门" clearable filterable style="width: 140px" @change="loadUsers">
          <el-option v-for="d in orgDepts" :key="d" :label="d" :value="d" />
        </el-select>
        <el-button type="primary" plain @click="openUser(null)"><el-icon><Plus /></el-icon>&nbsp;新增用户</el-button>
      </div>
      <!-- 第四十二批：布局对齐操作审计——筛选 toolbar 独立，表格 el-card 外框 -->
      <el-card shadow="never">
      <el-table :data="pagedUsers" v-loading="userLoading" stripe size="small">
        <!-- v2.12 列顺序：账户状态 → 账户 → 姓名 → 角色 → 部门 → 岗位 → IM绑定 → 操作 -->
        <el-table-column label="账户状态" width="90" fixed="left">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">{{ row.is_active ? '正常' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="username" label="账户" min-width="120" fixed="left" />
        <el-table-column prop="name" label="姓名" min-width="100" />
        <el-table-column label="角色" min-width="90">
          <template #default="{ row }">
            <el-tag :type="({ admin: 'danger', engineer: 'warning', employee: 'info' } as any)[row.role]" size="small">
              {{ ({ admin: '管理员', engineer: '工程师', employee: '员工' } as any)[row.role] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="department" label="部门" min-width="110" />
        <el-table-column label="岗位" min-width="90" class-name="col-sm-hide">
          <template #default="{ row }">
            <span v-if="row.role === 'engineer'">{{ ({ remote: '远程运维', field: '现场运维', other: '综合处理' } as any)[row.ops_type || 'other'] }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="IM 绑定" min-width="180" class-name="col-sm-hide">
          <template #default="{ row }">
            <el-tag v-if="row.dingtalk_userid" size="small" type="primary" effect="plain">钉钉</el-tag>
            <el-tag v-if="row.feishu_open_id" size="small" type="success" effect="plain">飞书</el-tag>
            <el-tag v-if="row.wecom_userid" size="small" effect="plain">企微</el-tag>
            <span v-if="!row.dingtalk_userid && !row.feishu_open_id && !row.wecom_userid" class="muted">未绑定</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="340" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openUser(row)">编辑</el-button>
            <!-- 第二十二批+：管理员账号不可停用（不显示停用/启用按钮） -->
            <el-button v-if="row.role !== 'admin'" size="small" :type="row.is_active ? 'danger' : 'success'" plain @click="toggleActive(row)">
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
            <!-- 第二十二批：密钥按钮移至标记请假前方 -->
            <el-button v-if="row.role === 'admin' || row.role === 'engineer'" size="small" type="primary" plain @click="openGate(row)">密钥</el-button>
            <el-button
              v-if="row.role === 'engineer'"
              size="small"
              :type="row.status === 'leave' ? 'success' : 'warning'"
              plain
              @click="toggleLeave(row)"
            >{{ row.status === 'leave' ? '恢复在岗' : '标记请假' }}</el-button>
          </template>
        </el-table-column>
      </el-table>
        <el-pagination
          v-model:current-page="userPage"
          :page-size="20"
          :total="users.length"
          layout="total, prev, pager, next"
          style="margin-top: 10px; justify-content: center"
        />
      </el-card>

      <!-- 每账号安全密钥弹窗（第二十七批+ 重设计：状态头/密钥块/步骤说明/警示区） -->
      <el-dialog v-model="gateVisible" width="620px" class="gate-dialog">
        <template #header>
          <div class="gd-header">
            <el-icon :size="20" color="#2f6fed"><Key /></el-icon>
            <b>后台访问安全密钥</b>
            <el-tag :type="gateInfo.enabled ? 'success' : 'info'" size="small" effect="plain">
              {{ gateInfo.enabled ? '已启用' : '未生成' }}
            </el-tag>
          </div>
        </template>

        <!-- 账号信息条 -->
        <div class="gd-user" v-if="gateUser">
          <el-icon :size="16"><User /></el-icon>
          <span class="gd-user-name">{{ gateUser.name || gateUser.username }}</span>
          <span class="gd-user-account">@{{ gateUser.username }}</span>
          <el-tag size="small" :type="gateUser.role === 'admin' ? 'danger' : 'warning'" effect="plain">
            {{ gateUser.role === 'admin' ? '管理员' : '工程师' }}
          </el-tag>
        </div>

        <template v-if="gateInfo.enabled">
          <!-- 准入密钥 -->
          <div class="gd-section-title">准入密钥</div>
          <div class="gd-keybox dark">
            <code>{{ gateInfo.key }}</code>
            <el-button size="small" text class="gd-copy" @click="copyGate(gateInfo.key)">
              <el-icon style="margin-right: 3px"><CopyDocument /></el-icon>复制
            </el-button>
          </div>
          <!-- 准入链接 -->
          <div class="gd-section-title">准入链接<span class="gd-section-hint">发给该账号的使用者，访问一次即完成准入</span></div>
          <div class="gd-keybox light">
            <code>{{ gateInfo.gate_url }}</code>
            <el-button size="small" text class="gd-copy" @click="copyGate(gateInfo.gate_url)">
              <el-icon style="margin-right: 3px"><CopyDocument /></el-icon>复制
            </el-button>
          </div>
          <!-- 使用方式 -->
          <div class="gd-steps">
            <div class="gd-step"><span class="gd-step-no">1</span>使用者访问准入链接，自动跳转登录页并记住该设备（30 天内免重复）</div>
            <div class="gd-step"><span class="gd-step-no">2</span>也可在登录页地址后追加 <code class="gd-inline">?k=密钥</code>，随登录提交完成准入</div>
          </div>
          <el-alert type="warning" :closable="false" show-icon class="gd-warn"
            title="重置影响" description="重置后旧密钥与该账号已准入的设备立即失效，需将新链接重新分发给使用者。" />
        </template>

        <template v-else>
          <el-result icon="info" title="该账号尚未生成安全密钥" sub-title="当前可直接登录后台；生成后必须持密钥访问后台（员工账号不使用密钥）">
            <template #extra>
              <el-button type="primary" :loading="gateGenerating" @click="resetGate">生成密钥</el-button>
            </template>
          </el-result>
        </template>

        <template #footer>
          <el-button @click="gateVisible = false">关闭</el-button>
          <el-button v-if="gateInfo.enabled" type="warning" :loading="gateGenerating" @click="resetGate">重置密钥</el-button>
        </template>
      </el-dialog>
    </el-tab-pane>

    <!-- 登录日志（第二十八批+）：独立标签页，安全审计 -->
    <el-tab-pane label="登录日志" name="loginlogs" lazy>
      <!-- 第四十二批：布局对齐操作审计——筛选 toolbar 独立，表格 el-card 外框 -->
      <div class="toolbar" style="margin-bottom: 10px">
        <el-date-picker
          v-model="logQuery.range"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始"
          end-placeholder="结束"
          style="width: 260px"
          @change="loadLogs"
        />
        <el-input v-model="logQuery.username" placeholder="按账号筛选" clearable style="width: 240px" @keyup.enter="loadLogs" @clear="loadLogs" />
        <el-select v-model="logQuery.success" placeholder="全部结果" clearable style="width: 140px" @change="loadLogs">
          <el-option label="成功" value="1" />
          <el-option label="失败" value="0" />
        </el-select>
        <el-button type="primary" @click="loadLogs">查询</el-button>
      </div>
      <!-- 第四十五批：失败原因归类统计条（随筛选联动） -->
      <div v-if="logStatGroups.length" class="log-stat-bar">
        <span v-for="g in logStatGroups" :key="g[0]" class="log-stat-item">
          {{ g[0] }} <b :class="{ 'stat-bad': g[0] !== '登录成功' }">{{ g[1] }}</b>
        </span>
      </div>
      <el-card shadow="never">
      <el-table :data="loginLogs" size="small" stripe v-loading="logLoading">
          <!-- 第四十二批：结果列前置 -->
          <el-table-column label="结果" width="80">
            <template #default="{ row }">
              <el-tag :type="row.success ? 'success' : 'danger'" size="small" effect="plain">{{ row.success ? '成功' : '失败' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="时间" width="160">
            <template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN', { hour12: false }) }}</template>
          </el-table-column>
          <el-table-column prop="username" label="账号" width="110" />
          <el-table-column prop="name" label="姓名" width="110" />
          <el-table-column prop="ip" label="来源 IP" width="130" />
          <el-table-column prop="reason" label="说明" min-width="220" />
        </el-table>
        <el-pagination
          v-model:current-page="logPage"
          :page-size="20"
          :total="logTotal"
          layout="total, prev, pager, next"
          style="margin-top: 10px; justify-content: center"
          @current-change="loadLogs(false)"
        />
      </el-card>
    </el-tab-pane>

    <!-- 操作审计（第三十五批：独立页迁回系统设置，置于登录日志与 SLA 规则之间） -->
    <el-tab-pane v-if="auth.isAdmin" label="操作审计" name="audit" lazy>
      <AuditPanel />
    </el-tab-pane>

    <!-- SLA 规则 -->
    <el-tab-pane label="SLA 规则" name="sla">
      <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px"
        title="按优先级设定响应与解决时限（分钟）；剩余时限低于 20% 时自动预警。详见 README「SLA 与满意度」章节。" />
      <el-table :data="slaRules" size="small">
        <el-table-column label="优先级" min-width="200">
          <template #default="{ row }">{{ row.priority_label }}</template>
        </el-table-column>
        <el-table-column label="响应时限（分钟）" min-width="260">
          <template #default="{ row }">
            <el-input-number v-model="row.response_minutes" :min="1" :max="10080" size="small" controls-position="right" />
          </template>
        </el-table-column>
        <el-table-column label="解决时限（分钟）" min-width="260">
          <template #default="{ row }">
            <el-input-number v-model="row.resolve_minutes" :min="1" :max="43200" size="small" controls-position="right" />
          </template>
        </el-table-column>
      </el-table>
      <el-button type="primary" style="margin-top: 14px" :loading="slaSaving" @click="saveSla">保存规则</el-button>
    </el-tab-pane>

    <!-- 智能分派与值班 -->
    <el-tab-pane label="智能分派" name="dispatch">
      <DispatchSettings />
    </el-tab-pane>

    <!-- 工单模板 -->
    <el-tab-pane label="工单模板" name="templates">
      <TemplateSettings />
    </el-tab-pane>

    <!-- 数据备份（v2.5） -->
    <el-tab-pane label="数据备份" name="backup" lazy>
      <BackupSettings />
    </el-tab-pane>

    <!-- 系统信息（合并开放平台 v2.11） -->
    <el-tab-pane label="消息推送" name="system">
      <el-row :gutter="14">
        <el-col :span="8" v-for="ch in systemInfo.channels" :key="ch.name">
          <el-card shadow="never" class="channel-card">
            <div class="channel-head">
              <b>{{ ch.display_name }}</b>
              <el-tag :type="ch.ready ? 'success' : 'info'" size="small">{{ ch.ready ? '已连接' : '未连接' }}</el-tag>
            </div>
            <div class="muted">{{ ch.mode }}</div>
          </el-card>
        </el-col>
      </el-row>
      <el-descriptions :column="2" border size="small" style="margin-top: 14px">
        <el-descriptions-item label="应用名">{{ systemInfo.app_name }}</el-descriptions-item>
        <el-descriptions-item label="对外地址">{{ systemInfo.public_base_url }}</el-descriptions-item>
        <el-descriptions-item label="数据库">{{ systemInfo.database_url }}</el-descriptions-item>
        <el-descriptions-item label="通知队列">{{ systemInfo.outbox?.pending || 0 }} 条待投递 / {{ systemInfo.outbox?.failed || 0 }} 条失败</el-descriptions-item>
      </el-descriptions>
      <el-alert type="warning" :closable="false" show-icon style="margin-top: 14px"
        title="渠道凭据在 config.yaml 中配置，修改后需重启服务生效。三家平台的申请步骤见项目 README「三平台接入指引」。" />
      <el-divider style="margin: 16px 0" />
      <OpenPlatformSettings />

      <!-- 邮件推送配置（v2.10） -->
      <el-divider style="margin: 16px 0" />
      <h4 style="margin: 0 0 12px">邮件推送</h4>
      <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px"
        title="未绑定 IM 的用户将通过 SMTP 邮箱接收通知；配置后点击「发送测试」验证。" />
      <el-form label-width="110px" size="small">
        <!-- 第四十二批：SMTP 服务器输入框与下方字段等宽；端口/启用/保存/测试右置同行 -->
        <el-form-item label="SMTP 服务器">
          <div class="smtp-host-row">
            <el-input v-model="mailForm.smtp_host" placeholder="smtp.company.com" style="width: 340px" />
            <el-input-number v-model="mailForm.smtp_port" :min="1" :max="65535" style="width: 130px" controls-position="right" />
            <el-checkbox v-model="mailForm.use_tls">SSL/TLS</el-checkbox>
            <el-divider direction="vertical" />
            <span class="muted">启用邮件</span>
            <el-switch v-model="mailForm.enabled" />
            <el-button type="primary" :loading="mailSaving" @click="saveMail">保存配置</el-button>
            <el-button :loading="mailTesting" @click="testMail">发送测试</el-button>
          </div>
        </el-form-item>
        <el-form-item label="发件账号">
          <el-input v-model="mailForm.username" placeholder="it-helpdesk@company.com" style="width: 340px" />
          <span class="muted" style="margin-left: 10px">登录 SMTP 服务器所用账号，通常为邮箱地址</span>
        </el-form-item>
        <el-form-item label="密码/授权码">
          <el-input v-model="mailForm.password" type="password" show-password :placeholder="mailForm.has_password ? '已配置，留空保留' : '邮箱密码或 SMTP 授权码'" style="width: 340px" />
        </el-form-item>
        <el-form-item label="发件地址">
          <el-input v-model="mailForm.from_addr" placeholder="默认与发件账号相同，可留空" style="width: 340px" />
          <span class="muted" style="margin-left: 10px">收件人看到的发件邮箱（与发件账号不同时才需填写）</span>
        </el-form-item>
      </el-form>
    </el-tab-pane>

    <!-- 部门管理 -->
    <el-tab-pane label="部门管理" name="org" lazy>
      <OrgSettings />
    </el-tab-pane>
  </el-tabs>

  <!-- 用户编辑弹窗 -->
  <el-dialog v-model="userVisible" :title="userForm.id ? '编辑用户' : '新增用户'" width="500px">
    <el-form label-width="80px">
      <el-form-item label="账号" required>
        <el-input v-model="userForm.username" :disabled="!!userForm.id" placeholder="登录账号" />
      </el-form-item>
      <el-form-item label="姓名" required>
        <el-input v-model="userForm.name" />
      </el-form-item>
      <el-form-item label="角色">
        <el-select v-model="userForm.role" style="width: 100%">
          <el-option label="管理员" value="admin" />
          <el-option label="工程师" value="engineer" />
          <el-option label="普通员工" value="employee" />
        </el-select>
      </el-form-item>
      <el-form-item label="部门">
        <el-select v-model="userForm.department" filterable allow-create default-first-option clearable placeholder="从部门字典选择或输入新增" style="width: 100%">
          <el-option v-for="d in orgDepts" :key="d" :label="d" :value="d" />
        </el-select>
      </el-form-item>
      <el-form-item label="邮箱"><el-input v-model="userForm.email" /></el-form-item>
      <el-form-item label="手机"><el-input v-model="userForm.phone" /></el-form-item>
      <el-form-item v-if="userForm.role === 'employee'" label="部门管理员">
        <el-switch v-model="userForm.dept_admin" />
        <span class="hint">开启后可查看本部门全部工单（仅查看权限）</span>
      </el-form-item>
      <el-form-item v-if="userForm.role === 'engineer'" label="岗位">
        <el-radio-group v-model="userForm.ops_type">
          <el-radio-button value="remote">远程运维</el-radio-button>
          <el-radio-button value="field">现场运维</el-radio-button>
          <el-radio-button value="other">其他</el-radio-button>
        </el-radio-group>
        <div class="hint">决定可用的功能模块（远程：软件问题远程处理；现场：设备报修/资产回收等），工单范围由类目权限控制</div>
      </el-form-item>
      <el-form-item v-if="userForm.role === 'engineer'" label="类目权限">
        <el-select
          v-model="userForm.category_scope"
          multiple
          collapse-tags
          clearable
          placeholder="全部类目（不选 = 不限）"
          style="width: 100%"
        >
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <div class="hint">限定该工程师可见/可派单的工单类目，留空不限制（v2.1）</div>
      </el-form-item>
      <el-form-item :label="userForm.id ? '重置密码' : '初始密码'">
        <el-input v-model="userForm.password" type="password" show-password :placeholder="userForm.id ? '留空则不修改' : '至少 6 位，留空则暂不可网页登录'" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="userVisible = false">取消</el-button>
      <el-button type="primary" @click="saveUser">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, patch, post, put } from '@/api/http'
import DispatchSettings from '@/components/DispatchSettings.vue'
import TemplateSettings from '@/components/TemplateSettings.vue'
import OpenPlatformSettings from '@/components/OpenPlatformSettings.vue'
import BackupSettings from '@/components/BackupSettings.vue'
import AuditPanel from '@/components/AuditPanel.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
import OrgSettings from '@/components/OrgSettings.vue'

// v2.12 部门字典联动：用户编辑部门改为下拉（选项来自「部门与岗位」字典），新部门保存后自动沉淀
const orgDepts = ref<string[]>([])

const userFilter = reactive({ role: '', ops_type: '', department: '' })

async function loadOrgDepts() {
  try {
    orgDepts.value = (await get('/api/org-tags')).depts || []
  } catch { /* ignore */ }
}

async function syncOrgDept(department: string) {
  const d = (department || '').trim()
  if (!d || orgDepts.value.includes(d)) return
  try {
    await post('/api/org-tags', { type: 'dept', name: d })
    orgDepts.value.push(d)
  } catch { /* ignore */ }
}

const tab = ref('users')

// ---- 用户 ----
const users = ref<any[]>([])
const userLoading = ref(false)
const userPage = ref(1)
const pagedUsers = computed(() => users.value.slice((userPage.value - 1) * 20, userPage.value * 20))
const userQ = ref('')
const userVisible = ref(false)
const userForm = reactive<any>({})
const categories = ref<string[]>([])

onMounted(() => {
  loadOrgDepts()
  loadUsers()
  loadSla()
  loadSystem()
  get('/api/admin/info').then((info) => (categories.value = info.categories || [])).catch(() => {})
  loadMail()
  loadLogs()
})

// ---- 登录日志（第二十八批+） ----
const loginLogs = ref<any[]>([])
const logTotal = ref(0)
const logPage = ref(1)
const logLoading = ref(false)
const logQuery = reactive<any>({ username: '', range: null, success: '' })
// 第四十五批：失败原因归类统计（同筛选条件聚合，前端映射展示为顶部计数条）
const logReasonStats = ref<{ reason: string; success: boolean; count: number }[]>([])
function reasonGroup(reason: string, success: boolean): string {
  if (success) return '登录成功'
  if (reason.includes('安全密钥')) return '门禁未通过'
  if (reason.includes('冻结')) return '账户冻结'
  if (reason.includes('锁定')) return '临时锁定'
  if (reason.includes('密码')) return '密码错误'
  if (reason.includes('AD') || reason.includes('域')) return 'AD 认证失败'
  return reason || '其他'
}
const logStatGroups = computed(() => {
  const map = new Map<string, number>()
  for (const it of logReasonStats.value) {
    const g = reasonGroup(it.reason, it.success)
    map.set(g, (map.get(g) || 0) + it.count)
  }
  return [...map.entries()].sort((a, b) => b[1] - a[1])
})

function loadLogs(reset = true) {
  if (reset) logPage.value = 1
  logLoading.value = true
  const p = new URLSearchParams()
  p.set('page', String(logPage.value))
  p.set('page_size', '20')
  if (logQuery.username) p.set('username', logQuery.username.trim())
  if (logQuery.range?.length) {
    p.set('start', logQuery.range[0])
    p.set('end', logQuery.range[1])
  }
  if (logQuery.success) p.set('success', logQuery.success)
  get(`/api/users/login-logs?${p}`).then((res) => {
    loginLogs.value = res.items
    logTotal.value = res.total
    logReasonStats.value = res.reason_stats || []
  }).catch((e: any) => ElMessage.error(e.message)).finally(() => (logLoading.value = false))
}

// ---- 后台访问安全密钥（第二十一批+：每账号一枚） ----
const gateVisible = ref(false)
const gateUser = ref<any>(null)
const gateInfo = ref<any>({ enabled: false, key: '', gate_url: '' })
const gateGenerating = ref(false)

function openGate(row: any) {
  gateUser.value = row
  gateInfo.value = { enabled: false, key: '', gate_url: '' }
  gateVisible.value = true
  get(`/api/users/${row.id}/gate-key`).then((res) => (gateInfo.value = res)).catch((e: any) => ElMessage.error(e.message))
}

async function resetGate() {
  if (!gateUser.value) return
  const verb = gateInfo.value.enabled ? '重置' : '生成'
  try {
    await ElMessageBox.confirm(
      `${verb}后${gateInfo.value.enabled ? '旧密钥与该账号已准入设备立即失效，' : ''}请将新准入链接分发给「${gateUser.value.name || gateUser.value.username}」。确定${verb}？`,
      `${verb}安全密钥`, { type: 'warning', confirmButtonText: `确定${verb}` },
    )
  } catch { return }
  gateGenerating.value = true
  try {
    const res = await post(`/api/users/${gateUser.value.id}/gate-key/reset`, {})
    gateInfo.value = res
    ElMessage.success(`密钥已${verb}，请复制准入链接分发给该账号使用者`)
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    gateGenerating.value = false
  }
}

async function copyGate(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

// ---- 邮件推送配置（v2.10） ----
const mailForm = reactive<any>({ enabled: false, smtp_host: '', smtp_port: 465, username: '', password: '', use_tls: true, from_addr: '', has_password: false })
const mailSaving = ref(false)
const mailTesting = ref(false)

async function loadMail() {
  try {
    const res = await get('/api/admin/mail-config')
    Object.assign(mailForm, { ...res, password: '' })
  } catch { /* ignore */ }
}

async function saveMail() {
  if (!mailForm.smtp_host.trim()) return ElMessage.warning('请填写 SMTP 服务器地址')
  mailSaving.value = true
  try {
    await put('/api/admin/mail-config', {
      enabled: mailForm.enabled,
      smtp_host: mailForm.smtp_host,
      smtp_port: mailForm.smtp_port,
      username: mailForm.username,
      password: mailForm.password || '',
      use_tls: mailForm.use_tls,
      from_addr: mailForm.from_addr,
    })
    ElMessage.success('邮件推送配置已保存（密码留空则保留原值）')
    mailForm.password = ''
    await loadMail()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    mailSaving.value = false
  }
}

async function testMail() {
  mailTesting.value = true
  try {
    // 先保存再测试（确保最新配置被使用）
    await put('/api/admin/mail-config', {
      enabled: true, smtp_host: mailForm.smtp_host, smtp_port: mailForm.smtp_port,
      username: mailForm.username, password: mailForm.password || '', use_tls: mailForm.use_tls, from_addr: mailForm.from_addr,
    })
    await post('/api/admin/mail-config/test')
    ElMessage.success('测试邮件已发送，请查收')
  } catch (e: any) {
    ElMessage.error(e.message || '发送失败')
  } finally {
    mailTesting.value = false
  }
}

async function loadUsers() {
  userLoading.value = true
  try {
    const parts: string[] = []
    if (userQ.value) parts.push(`q=${encodeURIComponent(userQ.value)}`)
    if (userFilter.role) parts.push(`role=${userFilter.role}`)
    const qs = parts.length ? `?${parts.join('&')}` : ''
    const all = (await get(`/api/users${qs}`)).items
    // 岗位/部门为前端过滤（后端无对应参数）
    users.value = all.filter((u: any) => {
      if (userFilter.ops_type && (u.role !== 'engineer' || (u.ops_type || 'other') !== userFilter.ops_type)) return false
      if (userFilter.department && (u.department || '') !== userFilter.department) return false
      return true
    })
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    userLoading.value = false
  }
}

function openUser(row: any) {
  Object.assign(userForm, row
    ? { id: row.id, username: row.username, name: row.name, role: row.role, department: row.department, email: row.email, phone: row.phone, password: '', category_scope: row.category_scope || [], ops_type: row.ops_type || 'other', dept_admin: !!row.dept_admin }
    : { id: null, username: '', name: '', role: 'employee', department: '', email: '', phone: '', password: '', category_scope: [], ops_type: 'remote', dept_admin: false })
  userVisible.value = true
}

async function saveUser() {
  if (!userForm.username.trim() || !userForm.name.trim()) return ElMessage.warning('请填写账号和姓名')
  try {
    if (userForm.id) {
      // 类目权限仅工程师生效，其他角色不带该字段
      const payload: any = { ...userForm }
      if (userForm.role !== 'engineer') {
        delete payload.category_scope
        delete payload.ops_type
      }
      if (userForm.role !== 'employee') delete payload.dept_admin
      await patch(`/api/users/${userForm.id}`, payload)
    } else {
      await post('/api/users', userForm)
    }
    await syncOrgDept(userForm.department)
    ElMessage.success('已保存')
    userVisible.value = false
    await loadUsers()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function toggleLeave(row: any) {
  const toLeave = row.status !== 'leave'
  try {
    await ElMessageBox.confirm(
      toLeave
        ? `将「${row.name}」标记为请假？请假期间不再参与自动分派，也无法被手动指派。`
        : `将「${row.name}」恢复为在岗？`,
      '在岗状态', { type: 'warning' },
    )
    await patch(`/api/users/${row.id}`, { status: toLeave ? 'leave' : 'on_duty' })
    ElMessage.success(toLeave ? '已标记请假' : '已恢复在岗')
    await loadUsers()
  } catch (e: any) {
    if (e !== 'cancel' && e?.message) ElMessage.error(e.message)
  }
}

async function toggleActive(row: any) {
  try {
    await patch(`/api/users/${row.id}`, { is_active: !row.is_active })
    await loadUsers()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

// ---- SLA ----
const slaRules = ref<any[]>([])
const slaSaving = ref(false)

async function loadSla() {
  try {
    slaRules.value = (await get('/api/admin/sla')).items
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function saveSla() {
  slaSaving.value = true
  try {
    await put('/api/admin/sla', slaRules.value.map((r) => ({ priority: r.priority, response_minutes: r.response_minutes, resolve_minutes: r.resolve_minutes })))
    ElMessage.success('SLA 规则已保存')
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    slaSaving.value = false
  }
}

// ---- 系统 ----
const systemInfo = ref<any>({})

async function loadSystem() {
  try {
    systemInfo.value = await get('/api/admin/info')
  } catch { /* ignore */ }
}
</script>

<style scoped>
.hint { font-size: 12px; color: #909399; margin-top: 2px; }
.settings { background: #fff; padding: 14px 18px; border-radius: 4px; }
.toolbar { display: flex; gap: 10px; margin-bottom: 12px; }
/* 第四十五批：登录日志归类统计条 */
.log-stat-bar {
  display: flex; gap: 18px; flex-wrap: wrap; align-items: center;
  background: #f5f6f8; border-radius: 6px; padding: 7px 14px; margin-bottom: 10px;
  font-size: 12px; color: #5a6478;
}
.log-stat-item b { font-weight: 600; color: #303133; margin-left: 2px; }
.log-stat-item b.stat-bad { color: #e6a23c; }
.muted { color: #909399; font-size: 12px; }
.channel-card { margin-bottom: 8px; }
.channel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
/* 后台访问安全密钥 */
/* 安全密钥弹窗（第二十七批+ 重设计） */
.gd-header { display: flex; align-items: center; gap: 8px; }
.gd-user {
  display: flex; align-items: center; gap: 8px;
  background: #f0f7ff; border: 1px solid #d6e8ff; border-radius: 8px;
  padding: 9px 14px; margin-bottom: 16px; color: #303133; font-size: 13px;
}
.gd-user-name { font-weight: 600; }
.gd-user-account { color: #8a93a6; }
.gd-section-title { font-size: 13px; font-weight: 600; color: #303133; margin: 4px 0 8px; }
.gd-section-hint { font-size: 12px; color: #909399; font-weight: 400; margin-left: 10px; }
.gd-keybox {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  border-radius: 8px; padding: 11px 14px; margin-bottom: 14px;
}
.gd-keybox code {
  font-family: Menlo, Consolas, monospace; font-size: 13px;
  white-space: nowrap; overflow-x: auto; line-height: 1.6; flex: 1;
}
.gd-keybox .gd-copy { flex-shrink: 0; }
.gd-keybox.dark { background: #1d2535; border: 1px solid #2a3550; }
.gd-keybox.dark code { color: #7fd7a4; }
.gd-keybox.dark .gd-copy { color: #aeb6c5; }
.gd-keybox.light { background: #f0f7ff; border: 1px solid #d6e8ff; }
.gd-keybox.light code { color: #2f6fed; }
.gd-steps { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }
.gd-step { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; color: #5a6478; line-height: 1.7; }
.gd-step-no {
  flex-shrink: 0; width: 18px; height: 18px; border-radius: 50%;
  background: #2f6fed; color: #fff; font-size: 11px;
  display: flex; align-items: center; justify-content: center; margin-top: 2px;
}
.gd-inline { font-family: Menlo, Consolas, monospace; background: #f4f4f5; padding: 1px 6px; border-radius: 4px; color: #303133; }
.gd-warn { margin-bottom: 4px; }
/* 邮件推送表单（第二十一批+） */
.smtp-host-row { display: flex; align-items: center; gap: 10px; width: 100%; }
.mail-foot-row { display: flex; align-items: center; gap: 14px; }
</style>
