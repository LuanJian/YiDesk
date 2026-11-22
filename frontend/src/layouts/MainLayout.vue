<template>

  <el-container class="layout">

    <el-aside :width="isMobile ? '64px' : '210px'" class="sidebar" :class="{ collapsed: isMobile }">

      <div class="logo">

        <el-icon :size="22"><Opportunity /></el-icon>

        <span>YiDesk</span>

      </div>

      <el-menu :default-active="$route.path" router class="menu" :collapse="isMobile" background-color="#1d2535" text-color="#aeb6c5" active-text-color="#ffffff">

        <el-menu-item index="/screen" v-if="auth.isAdmin">

          <el-icon><Monitor /></el-icon><span>实时大屏</span>

        </el-menu-item>

        <el-menu-item index="/tickets">

          <el-icon><Tickets /></el-icon><span>工单列表</span>

        </el-menu-item>

        <el-menu-item index="/knowledge">

          <el-icon><Collection /></el-icon><span>常见问题</span>

        </el-menu-item>

        <el-menu-item index="/licenses" v-if="auth.can('licenses.read')">

          <el-icon><Key /></el-icon><span>软件列表</span>

        </el-menu-item>

        <el-menu-item index="/devices" v-if="auth.can('assets.read')">

          <el-icon><Monitor /></el-icon><span>设备管理</span>

        </el-menu-item>

        <el-menu-item index="/compliance" v-if="auth.can('compliance')">

          <el-icon><CircleCheck /></el-icon><span>合规检查</span>

        </el-menu-item>

        <el-menu-item index="/qr-tags" v-if="auth.can('qr-tags')">

          <el-icon><Grid /></el-icon><span>标签制作</span>

        </el-menu-item>

        <el-menu-item index="/meetings" v-if="auth.isStaff">

          <el-icon><Calendar /></el-icon><span>会议管理</span>

        </el-menu-item>

        <el-menu-item index="/analytics" v-if="auth.isStaff">

          <el-icon><TrendCharts /></el-icon><span>数据看板</span>

        </el-menu-item>

        <el-menu-item index="/settings" v-if="auth.isAdmin">

          <el-icon><Setting /></el-icon><span>系统设置</span>

        </el-menu-item>

      </el-menu>

    </el-aside>

    <el-container>

      <el-header class="header" height="56px">

        <div class="header-title">

          <el-icon v-if="isMobile" class="mobile-toggle" @click="sidebarVisible = !sidebarVisible"><Fold /></el-icon>

          {{ $route.meta.title || '' }}

        </div>

        <div class="header-right">

          <template v-if="auth.user">

            <el-tag :type="roleTagType" size="small" effect="plain">{{ roleLabel }}</el-tag>

            <el-dropdown @command="onCommand">

              <span class="user-name">

                {{ auth.user?.name || auth.user?.username }}

                <el-icon><ArrowDown /></el-icon>

              </span>

              <template #dropdown>

                <el-dropdown-menu>

                  <el-dropdown-item command="password">修改密码</el-dropdown-item>

                  <el-dropdown-item v-if="auth.user && auth.user.role !== 'employee'" command="gate">安全密钥</el-dropdown-item>

                  <el-dropdown-item command="notify">通知偏好</el-dropdown-item>

                  <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>

                </el-dropdown-menu>

              </template>

            </el-dropdown>

          </template>

          <span v-else class="user-name">匿名访客</span>

        </div>

      </el-header>

      <el-main class="main">

        <router-view />

      </el-main>

    </el-container>

    <!-- 安全密钥自助管理（右上角菜单入口，工程师/管理员自助查看/重置/重新准入） -->

    <el-dialog v-model="gateVisible" width="620px">

      <template #header>

        <div class="gd-header">

          <el-icon :size="18" color="#2f6fed"><Key /></el-icon>

          <b>我的安全密钥</b>

          <el-tag :type="gateInfo.enabled ? 'success' : 'info'" size="small" effect="plain">

            {{ gateInfo.enabled ? '已启用' : '未生成' }}

          </el-tag>

        </div>

      </template>

      <!-- 简约重构——仅保留准入链接核心块 + 一句用法说明 + 一句重置提示（样式随本组件自带，避免跨组件依赖失效） -->

      <template v-if="gateInfo.enabled">

        <div class="gself-account">{{ auth.user?.name || auth.user?.username }}（@{{ auth.user?.username }}）</div>

        <div class="gself-label">准入链接</div>

        <div class="gself-linkbox">

          <code>{{ gateInfo.gate_url }}</code>

          <el-button size="small" text class="gself-copy" @click="copyGate(gateInfo.gate_url)">

            <el-icon style="margin-right: 3px"><CopyDocument /></el-icon>复制

          </el-button>

        </div>

        <div class="gself-hint">

          在其他设备访问一次此链接即完成准入（记住设备 30 天）；当前设备已准入，点下方「重新准入」可续期。

        </div>

        <div class="gself-reset-hint">重置密钥后，旧密钥与已准入设备立即失效，需用新链接重新准入。</div>

      </template>

      <template v-else>

        <el-result icon="info" title="尚未生成安全密钥" sub-title="当前可直接登录后台；生成后必须持密钥访问后台。" />

      </template>

      <template #footer>

        <el-button v-if="gateInfo.enabled" plain @click="reAdmit">重新准入（当前设备）</el-button>

        <el-button @click="gateVisible = false">关闭</el-button>

        <el-button type="warning" :loading="gateGenerating" @click="resetMyGate">{{ gateInfo.enabled ? '重置密钥' : '生成密钥' }}</el-button>

      </template>

    </el-dialog>

    <!-- 首次部署安全设置引导（默认密码未修改时登录后弹出） -->

    <el-dialog v-model="setupVisible" title="完成初始安全设置" width="480px" :close-on-click-modal="false">

      <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 14px"

        title="当前仍在使用部署时的初始密码，请立即设置正式密码。" />

      <div class="muted" style="font-size: 12px; margin-bottom: 12px">

        如需启用安全密钥，可在设置完成后点击右上角菜单中的「安全密钥」开启。

      </div>

      <el-form label-width="90px">

        <el-form-item label="新密码">

          <el-input v-model="setupForm.pwd" type="password" show-password placeholder="至少 6 位" />

        </el-form-item>

        <el-form-item label="确认密码">

          <el-input v-model="setupForm.pwd2" type="password" show-password placeholder="再次输入新密码" />

        </el-form-item>

      </el-form>

      <template #footer>

        <el-button @click="setupVisible = false">稍后再说</el-button>

        <el-button type="primary" :loading="setupSaving" @click="finishSetup">完成设置</el-button>

      </template>

    </el-dialog>

    <el-dialog v-model="pwdVisible" title="修改密码" width="420px">

      <el-form label-width="80px">

        <el-form-item label="原密码" v-if="auth.user?.has_password !== false">

          <el-input v-model="pwdForm.old" type="password" show-password />

        </el-form-item>

        <el-form-item label="新密码">

          <el-input v-model="pwdForm.new" type="password" show-password placeholder="至少 6 位" />

        </el-form-item>

      </el-form>

      <template #footer>

        <el-button @click="pwdVisible = false">取消</el-button>

        <el-button type="primary" @click="changePwd">确定</el-button>

      </template>

    </el-dialog>

    <!-- 个人通知偏好（自助开关，避免通知轰炸） -->

    <el-dialog v-model="notifyVisible" title="通知偏好" width="440px">

      <div class="muted" style="font-size: 12px; margin-bottom: 12px">关闭后将不再接收对应类型的 IM/站内提醒；评价、审批等关键流程通知不受影响。</div>

      <div v-for="item in NOTIFY_ITEMS" :key="item.key" style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0">

        <div>

          <div>{{ item.label }}</div>

          <div class="muted" style="font-size: 12px">{{ item.desc }}</div>

        </div>

        <el-switch v-model="notifyForm[item.key]" />

      </div>

      <template #footer>

        <el-button @click="notifyVisible = false">取消</el-button>

        <el-button type="primary" :loading="notifySaving" @click="saveNotifyPrefs">保存</el-button>

      </template>

    </el-dialog>

  </el-container>

</template>

<script setup lang="ts">

import { computed, reactive, ref, watch } from 'vue'

import { ElMessage, ElMessageBox } from 'element-plus'

import { get, patch, post } from '@/api/http'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const isMobile = ref(window.innerWidth < 768)

const sidebarVisible = ref(true)

function onResizeM() { isMobile.value = window.innerWidth < 768 }

window.addEventListener('resize', onResizeM)

const roleLabel = computed(() => {

  const u = auth.user

  if (!u) return ''

  if (u.role === 'admin') return '管理员'

  if (u.role === 'engineer') {

    const ops = { remote: '远程运维', field: '现场运维', other: '工程师' }[u.ops_type || 'other'] || '工程师'

    return ops

  }

  return '员工'

})

const roleTagType = computed(() => ({ admin: 'danger', engineer: 'warning', employee: 'info' }[auth.user?.role || 'employee'] || 'info'))

// 首次部署安全设置引导（admin 默认密码未修改时自动弹出）

const setupVisible = ref(false)

const setupSaving = ref(false)

const setupForm = reactive({ pwd: '', pwd2: '' })

watch(() => auth.user?.default_password, (v) => {

  if (v) {

    setupVisible.value = true

    setupForm.pwd = ''

    setupForm.pwd2 = ''

    setupForm.enableGate = true

  }

}, { immediate: true })

async function finishSetup() {

  if (setupForm.pwd.length < 6) return ElMessage.warning('新密码至少 6 位')

  if (setupForm.pwd !== setupForm.pwd2) return ElMessage.warning('两次输入的密码不一致')

  setupSaving.value = true

  try {

    await post('/api/auth/finish-setup', { new_password: setupForm.pwd })

    ElMessage.success('初始密码已设置。如需启用安全密钥，请点击右上角菜单中的「安全密钥」')

    setupVisible.value = false

    await auth.fetchMe()

  } catch (e: any) {

    ElMessage.error(e.message || '设置失败')

  } finally {

    setupSaving.value = false

  }

}

const pwdVisible = ref(false)

const pwdForm = reactive({ old: '', new: '' })

function onCommand(cmd: string) {

  if (cmd === 'logout') auth.logout()

  if (cmd === 'password') {

    pwdForm.old = ''

    pwdForm.new = ''

    pwdVisible.value = true

  }

  if (cmd === 'gate') openGate()

  if (cmd === 'notify') openNotifyPrefs()

}

// 个人通知偏好

const NOTIFY_ITEMS = [

  { key: 'status_change', label: '状态变更', desc: '工单受理、流转、完结等进展提醒' },

  { key: 'urge', label: '催办提醒', desc: '发起人对您的工单发起催办时提醒' },

  { key: 'urgent', label: '加急提醒', desc: '工单被加急或加急广播可转办时提醒' },

] as const

const notifyVisible = ref(false)

const notifySaving = ref(false)

const notifyForm = reactive<Record<string, boolean>>({ status_change: true, urge: true, urgent: true })

async function openNotifyPrefs() {

  notifyVisible.value = true

  try {

    const res = await get('/api/users/me/notify-prefs')

    NOTIFY_ITEMS.forEach((i) => (notifyForm[i.key] = res.prefs?.[i.key] !== false))

  } catch { /* 保持默认全开 */ }

}

async function saveNotifyPrefs() {

  notifySaving.value = true

  try {

    await patch('/api/users/me/notify-prefs', { ...notifyForm })

    ElMessage.success('通知偏好已保存')

    notifyVisible.value = false

  } catch (e: any) {

    ElMessage.error(e.message || '保存失败')

  } finally {

    notifySaving.value = false

  }

}

// 我的安全密钥（自助）

const gateVisible = ref(false)

const gateInfo = ref<any>({ enabled: false, key: '', gate_url: '' })

const gateGenerating = ref(false)

function openGate() {

  gateInfo.value = { enabled: false, key: '', gate_url: '' }

  gateVisible.value = true

  get('/api/users/me/gate-key').then((res) => (gateInfo.value = res)).catch((e: any) => ElMessage.error(e.message))

}

async function resetMyGate() {

  const verb = gateInfo.value.enabled ? '重置' : '生成'

  try {

    await ElMessageBox.confirm(

      `${verb}后旧密钥与本账号已准入的设备立即失效，需使用新密钥/新链接重新准入。确定${verb}？`,

      `${verb}安全密钥`, { type: 'warning', confirmButtonText: `确定${verb}` },

    )

  } catch { return }

  gateGenerating.value = true

  try {

    gateInfo.value = await post('/api/users/me/gate-key/reset', {})

    ElMessage.success(`密钥已${verb}，当前设备请点击「重新准入」完成绑定`)

  } catch (e: any) {

    ElMessage.error(e.message)

  } finally {

    gateGenerating.value = false

  }

}

function reAdmit() {

  if (!gateInfo.value.gate_url) return

  window.open(gateInfo.value.gate_url, '_blank')

  ElMessage.success('已在新标签页打开准入链接，访问后本设备 30 天内免重复准入')

}

async function copyGate(text: string) {

  try {

    await navigator.clipboard.writeText(text)

    ElMessage.success('已复制')

  } catch {

    ElMessage.warning('复制失败，请手动选择复制')

  }

}

async function changePwd() {

  if (pwdForm.new.length < 6) return ElMessage.warning('新密码至少 6 位')

  try {

    await post('/api/auth/change-password', { old_password: pwdForm.old, new_password: pwdForm.new })

    ElMessage.success('密码已修改')

    pwdVisible.value = false

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

</script>

<style scoped>

.layout { height: 100vh; }

.sidebar {

  background: #1d2535; display: flex; flex-direction: column; transition: width 0.3s;

  /* v2.12 修复：下拉 popper/loading 残留遮罩会覆盖侧边栏导致无法点击，置顶保证可交互 */

  position: relative; z-index: 3001;

}

.sidebar.collapsed .logo span,

.sidebar.collapsed .menu span { display: none; }

.sidebar.collapsed .sidebar-footer { display: none; }

.mobile-toggle { cursor: pointer; margin-right: 8px; color: #409eff; }

.logo {

  color: #fff; font-weight: 600; font-size: 16px;

  display: flex; align-items: center; gap: 8px;

  padding: 18px 20px; letter-spacing: 0.5px;

}

.menu { border-right: none; flex: 1; }

.menu :deep(.el-menu-item.is-active) { background: #2f6fed !important; }

.sidebar-footer { color: #5a6478; font-size: 11px; text-align: center; padding: 14px 0; }

.header {

  background: #fff; display: flex; align-items: center; justify-content: space-between;

  border-bottom: 1px solid #e6e8ee;

}

.header-title { font-size: 15px; font-weight: 600; }

.header-right { display: flex; align-items: center; gap: 12px; }

.user-name { cursor: pointer; display: flex; align-items: center; gap: 4px; color: #303133; }

.main { padding: 16px; overflow: auto; background: #f5f7fa; }

</style>

<!-- 我的安全密钥弹窗自带样式（非 scoped——弹窗挂载在 body 下，此前依赖 SettingsView 的 scoped 类导致全部失效裸文本堆积） -->

<style>

.gself-account {

  font-size: 13px; color: #5a6478;

  background: #f5f6f8; border-radius: 6px;

  display: inline-block; padding: 4px 10px; margin-bottom: 14px;

}

.gself-label {

  font-size: 12px; font-weight: 600; color: #909399;

  letter-spacing: 0.5px; margin-bottom: 6px;

}

.gself-linkbox {

  display: flex; align-items: center; gap: 10px;

  background: #f0f7ff; border: 1px solid #d6e8ff; border-radius: 8px;

  padding: 11px 14px;

}

.gself-linkbox code {

  flex: 1; font-family: Menlo, Consolas, monospace; font-size: 13px;

  color: #2f6fed; white-space: nowrap; overflow-x: auto; line-height: 1.6;

}

.gself-linkbox .gself-copy { flex-shrink: 0; color: #2f6fed; }

.gself-hint { font-size: 12px; color: #909399; line-height: 1.7; margin-top: 10px; }

.gself-reset-hint {

  font-size: 12px; color: #b88230;

  background: #fdf6ec; border-radius: 6px;

  padding: 7px 10px; margin-top: 12px;

}

.gd-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }

</style>
