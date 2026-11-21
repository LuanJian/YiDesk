import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus, { ElMessage } from 'element-plus'
import 'element-plus/dist/index.css'
import './assets/global.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'

// chunk 加载失败自动刷新后：跳回用户原本想去的页面，并复位防循环标记
const redirectTarget = sessionStorage.getItem('itops_after_reload_redirect')
if (redirectTarget) {
  sessionStorage.removeItem('itops_after_reload_redirect')
  sessionStorage.removeItem('itops_chunk_reload')
  router.push(redirectTarget)
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}
// 全局兜底：组件渲染报错不再静默空白，给出可见提示（此前 MeetingManageView 缺 computed 导入即表现为整页空白无任何提示）
app.config.errorHandler = (err) => {
  console.error('[app]', err)
  ElMessage.error('页面渲染出错：' + String((err as any)?.message || err).slice(0, 120) + '，请刷新重试')
}
app.mount('#app')
