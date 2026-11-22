import { defineStore } from 'pinia'

import { ref, computed } from 'vue'

import { get, post, setToken, clearToken } from '@/api/http'

export interface CurrentUser {

  id: number

  username: string

  name: string

  role: 'admin' | 'engineer' | 'employee'

  department: string

  email: string

  phone: string

  ops_type?: 'remote' | 'field' | 'other'

  perms?: string[]

}

export const OPS_LABELS: Record<string, string> = { remote: '远程运维', field: '现场运维', other: '综合处理' }

export const useAuthStore = defineStore('auth', () => {

  const user = ref<CurrentUser | null>(null)

  const loading = ref(true)

  const isStaff = computed(() => user.value?.role === 'admin' || user.value?.role === 'engineer')

  const isAdmin = computed(() => user.value?.role === 'admin')

  const opsLabel = computed(() => {

    const u = user.value

    if (!u) return ''

    if (u.role === 'admin') return '管理员'

    return OPS_LABELS[u.ops_type || 'other'] || ''

  })

  /** 岗位权限判断：管理员恒真；后端为唯一执行点，这里仅控制菜单/按钮显隐 */

  function can(perm: string): boolean {

    const u = user.value

    if (!u) return false

    if (u.role === 'admin') return true

    return (u.perms || []).includes(perm)

  }

  async function login(username: string, password: string) {

    const data = await post<{ token: string; user: CurrentUser }>('/api/auth/login', { username, password })

    setToken(data.token)

    user.value = data.user

    // 登录响应不含 perms，拉一次完整 me

    await fetchMe()

  }

  async function fetchMe() {

    if (!localStorage.getItem('itops_token')) {

      loading.value = false

      return

    }

    try {

      user.value = await get<CurrentUser>('/api/auth/me')

    } catch {

      user.value = null

    } finally {

      loading.value = false

    }

  }

  function logout() {

    clearToken()

    user.value = null

    location.href = '/login'

  }

  return { user, loading, isStaff, isAdmin, opsLabel, can, login, fetchMe, logout }

})
