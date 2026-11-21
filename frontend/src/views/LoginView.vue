<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <el-icon :size="34" color="#2f6fed"><Opportunity /></el-icon>
        <h1>YiDesk</h1>
      </div>

      <el-alert v-if="oauthError" type="error" :title="oauthError" :closable="false" show-icon style="margin-bottom: 14px" />

      <!-- IM 内免登 -->
      <el-button
        v-if="detected === 'dingtalk'"
        type="primary" size="large" style="width: 100%" :loading="oauthLoading"
        @click="dingtalkJsapiLogin"
      >钉钉一键登录</el-button>
      <el-button
        v-else-if="detected === 'feishu'"
        type="primary" size="large" style="width: 100%" :loading="oauthLoading"
        @click="goFeishuOAuth"
      >飞书一键登录</el-button>
      <el-button
        v-else-if="detected === 'wecom'"
        type="primary" size="large" style="width: 100%" :loading="oauthLoading"
        @click="goWecomOAuth"
      >企业微信一键登录</el-button>

      <el-divider v-if="detected !== 'none' && anyImEnabled">或使用账号密码</el-divider>

      <el-form @submit.prevent="submit">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large">
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" show-password placeholder="密码" size="large" @keyup.enter="submit">
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" native-type="submit">
          登 录
        </el-button>
      </el-form>

      <!-- 浏览器里也可跳转 IM 授权 -->
      <div v-if="detected === 'none' && anyImEnabled" class="oauth-row">
        <el-button v-if="platforms.dingtalk?.enabled" size="small" plain @click="dingtalkJsapiLogin">钉钉登录</el-button>
        <el-button v-if="platforms.feishu?.enabled" size="small" plain @click="goFeishuOAuth">飞书登录</el-button>
        <el-button v-if="platforms.wecom?.enabled" size="small" plain @click="goWecomOAuth">企微登录</el-button>
      </div>

      <!-- 游客服务：无需登录即可使用的自助入口 -->
      <el-divider style="margin: 24px 0 16px"><span class="divider-text">无需登录，自助服务</span></el-divider>
      <div class="guest-row">
        <div class="guest-entry" @click="router.push('/public/softwares')">
          <el-icon :size="18" color="#2f6fed"><Download /></el-icon>
          <span>软件列表</span>
        </div>
        <div class="guest-entry" @click="router.push('/public/knowledge')">
          <el-icon :size="18" color="#67c23a"><Collection /></el-icon>
          <span>常见问题</span>
        </div>
        <div class="guest-entry" @click="goQuickTicket">
          <el-icon :size="18" color="#e6a23c"><Tickets /></el-icon>
          <span>提交工单</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { get, post, setToken } from '@/api/http'
import { useAuthStore, type CurrentUser } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const platforms = ref<any>({})
const anyImEnabled = ref(false)
const detected = ref<'none' | 'dingtalk' | 'feishu' | 'wecom'>('none')
const oauthLoading = ref(false)
const oauthError = ref('')

onMounted(async () => {
  try {
    platforms.value = await get('/api/auth/platform-info')
    anyImEnabled.value = ['dingtalk', 'feishu', 'wecom'].some((k) => platforms.value[k]?.enabled)
  } catch { /* ignore */ }

  const ua = navigator.userAgent
  if (/DingTalk/i.test(ua)) detected.value = 'dingtalk'
  else if (/Lark|Feishu/i.test(ua)) detected.value = 'feishu'
  else if (/wxwork/i.test(ua)) detected.value = 'wecom'

  // OAuth 回调：?code=xxx&state=feishu|wecom
  const code = route.query.code as string
  const state = (route.query.state as string) || ''
  if (code && state === 'feishu') await finishFeishuOAuth(code)
  else if (code && state === 'wecom') await finishWecomOAuth(code)

  // v2.10 扫码自动带员工信息：IM 容器内打开且有待办路径（如扫码页）→ 自动免登
  const after = sessionStorage.getItem('itops_after_login')
  if (after && !route.query.code) {
    if (detected.value === 'dingtalk' && platforms.value.dingtalk?.enabled) await dingtalkJsapiLogin()
    else if (detected.value === 'feishu' && platforms.value.feishu?.enabled) goFeishuOAuth()
    else if (detected.value === 'wecom' && platforms.value.wecom?.enabled) goWecomOAuth()
  }
})

async function onLoginSuccess(data: { token: string; user: CurrentUser }) {
  setToken(data.token)
  auth.user = data.user
  // 登录响应不含 perms，拉一次完整 me（岗位权限菜单显隐依赖它）
  await auth.fetchMe()
  // v2.10 扫码自动带员工信息：免登前记录的目标路径（如扫码页）优先回跳
  const after = sessionStorage.getItem('itops_after_login')
  if (after) {
    sessionStorage.removeItem('itops_after_login')
    router.push(after)
    return
  }
  router.push((route.query.redirect as string) || '/tickets')
}

async function submit() {
  if (!form.username || !form.password) return ElMessage.warning('请输入用户名和密码')
  loading.value = true
  try {
    // URL 带安全密钥（/login?k=xxx）时随登录请求一并提交，供管理员/工程师后台准入
    const data = await post<{ token: string; user: CurrentUser }>('/api/auth/login', {
      username: form.username,
      password: form.password,
      gate_key: (route.query.k as string) || undefined,
    })
    onLoginSuccess(data)
  } catch (e: any) {
    ElMessage.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}

// PC 端无实体码提单：取（必要时惰性创建）通用位置码后进入扫码提单页
async function goQuickTicket() {
  try {
    const res = await get('/api/public/general-qr')
    router.push(`/qr/${res.code}`)
  } catch (e: any) {
    ElMessage.error(e.message || '入口暂不可用，请稍后重试')
  }
}

// ---- 钉钉 jsapi 免登（钉钉客户端内打开工作台应用时） ----

function loadDingTalkJs(): Promise<void> {
  return new Promise((resolve, reject) => {
    if ((window as any).dd) return resolve()
    const s = document.createElement('script')
    s.src = 'https://g.alicdn.com/dingding/dingtalk-jsapi/3.0.25/dingtalk.open.js'
    s.onload = () => resolve()
    s.onerror = () => reject(new Error('钉钉 JSAPI 加载失败'))
    document.head.appendChild(s)
  })
}

async function dingtalkJsapiLogin() {
  if (!platforms.value.dingtalk?.enabled) return ElMessage.warning('钉钉渠道未启用')
  oauthLoading.value = true
  oauthError.value = ''
  try {
    await loadDingTalkJs()
    const dd = (window as any).dd
    const code = await new Promise<string>((resolve, reject) => {
      dd.ready(() => {
        dd.runtime.permission.requestAuthCode({
          corpId: platforms.value.dingtalk.corp_id,
          onSuccess: (r: any) => resolve(r.code),
          onFail: (e: any) => reject(new Error(JSON.stringify(e))),
        })
      })
      dd.error((e: any) => reject(new Error(JSON.stringify(e))))
    })
    const data = await post<{ token: string; user: CurrentUser }>('/api/auth/dingtalk-code', { code })
    onLoginSuccess(data)
  } catch (e: any) {
    oauthError.value = `钉钉免登失败：${e.message}`
  } finally {
    oauthLoading.value = false
  }
}

// ---- 飞书 OAuth（浏览器与客户端均可） ----

function goFeishuOAuth() {
  if (!platforms.value.feishu?.enabled) return ElMessage.warning('飞书渠道未启用')
  const redirect = encodeURIComponent(`${location.origin}/login`)
  location.href =
    `https://open.feishu.cn/open-apis/authen/v1/authorize?app_id=${platforms.value.feishu.app_id}` +
    `&redirect_uri=${redirect}&state=feishu`
}

async function finishFeishuOAuth(code: string) {
  oauthLoading.value = true
  oauthError.value = ''
  try {
    const data = await post<{ token: string; user: CurrentUser }>('/api/auth/feishu-code', {
      code,
      redirect_uri: `${location.origin}/login`,
    })
    onLoginSuccess(data)
  } catch (e: any) {
    oauthError.value = `飞书免登失败：${e.message}`
  } finally {
    oauthLoading.value = false
  }
}

// ---- 企微 OAuth ----

function goWecomOAuth() {
  if (!platforms.value.wecom?.enabled) return ElMessage.warning('企业微信渠道未启用')
  const redirect = encodeURIComponent(`${location.origin}/login`)
  location.href =
    `https://open.weixin.qq.com/connect/oauth2/authorize?appid=${platforms.value.wecom.corp_id}` +
    `&redirect_uri=${redirect}&response_type=code&scope=snsapi_base&agentid=${platforms.value.wecom.agent_id}&state=wecom#wechat_redirect`
}

async function finishWecomOAuth(code: string) {
  oauthLoading.value = true
  oauthError.value = ''
  try {
    const data = await post<{ token: string; user: CurrentUser }>('/api/auth/wecom-code', { code })
    onLoginSuccess(data)
  } catch (e: any) {
    oauthError.value = `企微免登失败：${e.message}`
  } finally {
    oauthLoading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #1d2535 0%, #2f6fed 130%);
}
.login-card {
  width: 400px; background: #fff; border-radius: 12px; padding: 40px 36px 28px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
}
.brand { text-align: center; margin-bottom: 24px; }
.brand h1 { font-size: 22px; margin: 10px 0 6px; color: #1d2535; }
.brand p { font-size: 12px; color: #909399; margin: 0; }
.oauth-row { display: flex; justify-content: center; gap: 8px; margin-top: 16px; }
.divider-text { font-size: 12px; color: #909399; }
.guest-row { display: flex; gap: 10px; }
.guest-entry {
  flex: 1; display: flex; flex-direction: column; align-items: center; gap: 5px;
  padding: 12px 0; border: 1px solid #e6e8ee; border-radius: 8px;
  font-size: 13px; color: #303133; cursor: pointer; transition: all 0.2s;
}
.guest-entry:hover { border-color: #2f6fed; background: #f0f7ff; }
</style>
