import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = createRouter({

  history: createWebHistory(),

  routes: [

    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },

    // v2.11 实时大屏全屏显示：脱离管理台布局，无侧边栏/顶栏（仅管理员）

    { path: '/screen', name: 'screen', component: () => import('@/views/ScreenView.vue'), meta: { title: '实时大屏', admin: true } },

    // v2.11 扫码报修独立页：无侧边栏（员工/匿名扫码提交不需要管理台导航）

    { path: '/qr/:code', name: 'qr-scan', component: () => import('@/views/QrView.vue'), meta: { title: '扫码报修', public: true } },

    // 登录页游客入口：未登录可浏览软件目录与常见问题（公开只读页）

    { path: '/public/softwares', name: 'public-softwares', component: () => import('@/views/PublicSoftwaresView.vue'), meta: { title: '软件列表', public: true } },

    { path: '/public/knowledge', name: 'public-knowledge', component: () => import('@/views/PublicKnowledgeView.vue'), meta: { title: '常见问题', public: true } },

    {

      path: '/',

      component: () => import('@/layouts/MainLayout.vue'),

      redirect: '/tickets',

      children: [

        { path: 'tickets', name: 'tickets', component: () => import('@/views/TicketListView.vue'), meta: { title: '工单列表' } },

        { path: 'tickets/:id', name: 'ticket-detail', component: () => import('@/views/TicketDetailView.vue'), meta: { title: '工单详情' } },

        { path: 'analytics', name: 'analytics', component: () => import('@/views/AnalyticsView.vue'), meta: { title: '数据看板', staff: true } },

        { path: 'dashboard', redirect: '/analytics' },  // 原统计看板已并入数据看板（v2.3 合并）

        { path: 'knowledge', name: 'knowledge', component: () => import('@/views/KnowledgeView.vue'), meta: { title: '常见问题' } },

        // v2.11 设备管理：资产管理 + 网络设备合并

        { path: 'devices', name: 'devices', component: () => import('@/views/DeviceView.vue'), meta: { title: '设备管理', staff: true } },

        { path: 'assets', redirect: '/devices' },

        { path: 'network-devices', redirect: '/devices' },

        { path: 'qr-tags', name: 'qr-tags', component: () => import('@/views/QrTagView.vue'), meta: { title: '标签制作', staff: true } },

        { path: 'licenses', name: 'licenses', component: () => import('@/views/LicenseView.vue'), meta: { title: '软件列表', staff: true } },

        { path: 'compliance', name: 'compliance', component: () => import('@/views/ComplianceView.vue'), meta: { title: '合规检查', staff: true } },

        { path: 'meetings', name: 'meetings', component: () => import('@/views/MeetingManageView.vue'), meta: { title: '会议管理', staff: true } },

        { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { title: '系统设置', staff: true } },

      ],

    },

    { path: '/:pathMatch(.*)*', redirect: '/tickets' },

  ],

})

router.beforeEach(async (to) => {

  const auth = useAuthStore()

  if (auth.loading) await auth.fetchMe()

  // v2.11 扫码报修页公开：未登录按匿名访客提交，不走登录拦截

  if (to.path !== '/login' && !to.meta.public && !auth.user) return { path: '/login', query: { redirect: to.fullPath } }

  if (to.path === '/login' && auth.user && !sessionStorage.getItem('itops_after_login')) return '/tickets'

  if (to.meta.admin && !auth.isAdmin) return '/tickets'

  if (to.meta.staff && !auth.isStaff) return '/tickets'

  return true

})

router.afterEach((to) => {

  document.title = to.meta.title ? `${to.meta.title} · YiDesk` : 'YiDesk'

})

// v2.12 兜底：懒加载 chunk 拉取失败（典型场景：服务已更新，旧页面内存路由表仍指向被删除的旧 chunk）

// 导航会静默中止表现为「点击菜单无反应」——自动刷新一次加载新版本；每会话仅刷一次防死循环

router.onError((error, to) => {

  const msg = String((error as any)?.message || error)

  if (/Failed to fetch dynamically imported|Importing a module script|dynamically imported module|Loading chunk/i.test(msg)) {

    if (!sessionStorage.getItem('itops_chunk_reload')) {

      sessionStorage.setItem('itops_chunk_reload', '1')

      if (to?.fullPath) sessionStorage.setItem('itops_after_reload_redirect', to.fullPath)

      location.reload()

      return

    }

  }

  console.error('[router]', error)

})

export default router
