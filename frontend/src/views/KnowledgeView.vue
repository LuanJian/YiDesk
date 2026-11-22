<template>

  <div>

    <el-card shadow="never" class="filter-card">

      <div class="filters">

        <el-input v-model="q" placeholder="搜索标题 / 正文 / 标签" clearable style="width: 240px" @keyup.enter="load" @clear="load">

          <template #prefix><el-icon><Search /></el-icon></template>

        </el-input>

        <el-select v-model="category" placeholder="全部分类" clearable style="width: 140px" @change="load">

          <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />

        </el-select>

        <el-select v-model="sort" style="width: 130px" @change="load">

          <el-option label="按热度排序" value="heat" />

          <el-option label="按更新时间" value="updated" />

        </el-select>

        <el-button type="primary" @click="load">搜索</el-button>

        <div style="flex: 1"></div>

        <el-button v-if="auth.isStaff" type="primary" plain @click="openEditor(null)">

          <el-icon style="margin-right: 4px"><Plus /></el-icon>新建文章

        </el-button>

      </div>

    </el-card>

    <el-row :gutter="14">

      <el-col :span="9">

        <el-card shadow="never">

          <el-table :data="pagedArticles" v-loading="loading" size="small" highlight-current-row @current-change="select" stripe>

            <el-table-column prop="title" label="文章" min-width="220" show-overflow-tooltip />

            <el-table-column prop="category" label="分类" min-width="80" />

            <el-table-column label="热度" min-width="70" sortable>

              <template #default="{ row }">

                <el-tooltip content="按文章关联的历史工单量统计" placement="top">

                  <span :style="{ color: (row.heat || 0) >= 3 ? '#f56c6c' : '#909399', fontWeight: (row.heat || 0) >= 3 ? 600 : 400 }">{{ row.heat || 0 }}</span>

                </el-tooltip>

              </template>

            </el-table-column>

            <el-table-column prop="updated_at" label="更新时间" min-width="110">

              <template #default="{ row }">{{ (row.updated_at || '').slice(0, 10) }}</template>

            </el-table-column>

          </el-table>

        <el-pagination

          v-model:current-page="kbPage"

          :page-size="20"

          :total="items.length"

          layout="total, prev, pager, next"

          style="margin-top: 10px; justify-content: center"

        />

        </el-card>

      </el-col>

      <el-col :span="15">

        <el-card shadow="never" class="viewer">

          <template v-if="current">

            <div class="viewer-head">

              <div class="viewer-main">

                <h2>{{ current.title }}</h2>

                <div class="meta">

                  <el-tag size="small" effect="plain">{{ current.category }}</el-tag>

                  <el-tag v-for="t in current.tags" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>

                  <el-tooltip content="按文章关联的历史工单量统计" placement="top">

                    <span class="heat-badge" :class="{ hot: (current.heat || 0) >= 3 }">热度 {{ current.heat || 0 }}</span>

                  </el-tooltip>

                </div>

                <!-- 来源与更新时间合并为一行元信息，与标题/标签分层 -->

                <div class="meta-info muted">

                  <span>更新于 {{ fmtTime(current.updated_at) }}</span>

                  <template v-if="current.source">

                    <span class="meta-sep">·</span>

                    <span>信息来源：</span>

                    <template v-if="current.source.startsWith('http')">

                      <el-link type="primary" :href="current.source" target="_blank" style="vertical-align: baseline">{{ current.source }}</el-link>

                    </template>

                    <span v-else>{{ current.source }}</span>

                  </template>

                </div>

              </div>

              <div v-if="auth.isStaff" class="viewer-ops">

                <el-button size="small" @click="openEditor(current)">编辑</el-button>

                <el-button size="small" type="danger" plain @click="remove(current)">删除</el-button>

              </div>

            </div>

            <div v-if="current.problem" class="problem-block">

              <div class="problem-label">问题描述</div>

              <div class="pre-wrap">{{ current.problem }}</div>

            </div>

            <div class="solve-label">解决方法</div>

            <!-- 正文支持配图——独立成行的图片链接渲染为内嵌图片 -->

            <div class="content pre-wrap">

              <template v-for="(line, i) in contentLines" :key="i">

                <img v-if="isImageLine(line)" :src="isImageLine(line)!" class="kb-img" alt="配图" />

                <template v-else>{{ line }}</template>

              </template>

            </div>

          </template>

          <el-empty v-else description="选择左侧文章查看，或新建一篇" />

        </el-card>

      </el-col>

    </el-row>

    <el-dialog v-model="editorVisible" :title="editorForm.id ? '编辑文章' : '新建文章'" width="760px">

      <el-form label-width="86px">

        <el-form-item label="标题">

          <el-input v-model="editorForm.title" maxlength="200" />

        </el-form-item>

        <el-form-item label="分类">

          <el-select v-model="editorForm.category" style="width: 220px" allow-create filterable>

            <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />

          </el-select>

        </el-form-item>

        <el-form-item label="标签">

          <el-input v-model="tagsText" placeholder="逗号分隔，如：VPN,打印机" />

        </el-form-item>

        <el-form-item label="信息来源">

          <el-input v-model="editorForm.source" placeholder="自述 / 官方文档 / 内部 Wiki / 链接（http 开头可点击）" />

        </el-form-item>

        <el-form-item label="问题描述">

          <el-input v-model="editorForm.problem" type="textarea" :rows="3" placeholder="详细说明问题现象、影响范围、复现条件等" />

        </el-form-item>

        <el-form-item label="解决方法">

          <!-- 支持粘贴/选择截图，图片以独立行 URL 插入正文 -->

          <el-input

            v-model="editorForm.content"

            type="textarea"

            :rows="12"

            placeholder="处理步骤与方法（可直接粘贴截图，或纯文本）"

            @paste="onContentPaste"

          />

          <div style="margin-top: 6px">

            <el-button size="small" plain :loading="imgUploading" @click="pickImage">插入图片</el-button>

            <input ref="imgInput" type="file" accept="image/png,image/jpeg,image/gif,image/webp" style="display: none" @change="onPickImage" />

            <span class="muted" style="font-size: 12px; margin-left: 8px">粘贴或插入的截图上传后以独立一行链接嵌入正文，匿名 FAQ 同样可见</span>

          </div>

        </el-form-item>

        <!-- 匿名可见（登录页公开 FAQ 仅展示勾选文章） -->

        <el-form-item label="匿名可见">

          <el-checkbox v-model="editorForm.public_visible">勾选后，未登录员工可在登录页「常见问题」中查看该文章</el-checkbox>

        </el-form-item>

      </el-form>

      <template #footer>

        <el-button @click="editorVisible = false">取消</el-button>

        <el-button type="primary" @click="save">保存</el-button>

      </template>

    </el-dialog>

  </div>

</template>

<script setup lang="ts">

import { computed, onMounted, reactive, ref } from 'vue'

import { ElMessage, ElMessageBox } from 'element-plus'

import { del, get, patch, post, upload } from '@/api/http'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const loading = ref(false)

const items = ref<any[]>([])

const kbPage = ref(1)

const pagedArticles = computed(() => items.value.slice((kbPage.value - 1) * 20, kbPage.value * 20))

const current = ref<any>(null)

const q = ref('')

// 分类更名（网络故障→网络问题、账号权限→账户相关、硬件设备→硬件维修、安全防护→系统安全）

const categoryOptions = ['常见问题', '网络问题', '账户相关', '硬件维修', '系统安全', '办公软件', '软件安装', '打印设备', '会议设备', '其他']

const category = ref('')

const sort = ref('heat')

const editorVisible = ref(false)

const editorForm = reactive<any>({ id: null, title: '', content: '', problem: '', category: '常见问题', tags: [], source: '', public_visible: false })

// 正文配图（粘贴/选择上传，独立行 URL 渲染为内嵌图片）

const imgUploading = ref(false)

const imgInput = ref<HTMLInputElement | null>(null)

const IMAGE_URL_RE = /^\/api\/public\/knowledge-images\/[0-9a-f]{32}\.(png|jpg|jpeg|gif|webp)$/

const contentLines = computed(() => (current.value?.content || '').split('\n'))

function isImageLine(line: string): string | null {

  const t = line.trim()

  if (!t) return null

  // 兼容裸 URL 与 ![xx](url) 两种写法

  const m = t.match(/^!\[[^\]]*\]\(([^)]+)\)$/)

  const url = m ? m[1] : t

  return IMAGE_URL_RE.test(url) ? url : null

}

async function uploadImageFile(file: File) {

  imgUploading.value = true

  try {

    const res = await upload('/api/knowledge/images', file)

    const url: string = res.url

    editorForm.content = (editorForm.content || '').replace(/\s*$/, '') + `\n${url}\n`

    ElMessage.success('图片已插入正文')

  } catch (e: any) {

    ElMessage.error(e.message || '图片上传失败')

  } finally {

    imgUploading.value = false

  }

}

function onContentPaste(e: ClipboardEvent) {

  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith('image/'))

  if (!item) return

  const file = item.getAsFile()

  if (!file) return

  e.preventDefault()

  void uploadImageFile(file)

}

function pickImage() {

  imgInput.value?.click()

}

function onPickImage(e: Event) {

  const file = (e.target as HTMLInputElement).files?.[0]

  if (file) void uploadImageFile(file)

  ;(e.target as HTMLInputElement).value = ''

}

const tagsText = ref('')

onMounted(load)

async function load() {

  loading.value = true

  try {

    const params = new URLSearchParams()

    if (q.value) params.set('q', q.value)

    if (category.value) params.set('category', category.value)

    params.set('sort', sort.value)

    const res = await get(`/api/knowledge?${params}`)

    items.value = res.items

    if (!current.value && items.value.length) await select(items.value[0])

  } catch (e: any) {

    ElMessage.error(e.message)

  } finally {

    loading.value = false

  }

}

async function select(row: any) {

  if (!row) return

  current.value = await get(`/api/knowledge/${row.id}`)

}

function openEditor(row: any) {

  if (row) {

    Object.assign(editorForm, { id: row.id, title: current.value.title, content: current.value.content, problem: current.value.problem || '', category: current.value.category, tags: current.value.tags, source: current.value.source || '', public_visible: !!current.value.public_visible })

    tagsText.value = (current.value.tags || []).join(',')

  } else {

    Object.assign(editorForm, { id: null, title: '', content: '', problem: '', category: '常见问题', tags: [], source: '', public_visible: false })

    tagsText.value = ''

  }

  editorVisible.value = true

}

async function save() {

  if (!editorForm.title.trim()) return ElMessage.warning('请填写标题')

  const body = { ...editorForm, tags: tagsText.value.split(/[,，]/).map((t: string) => t.trim()).filter(Boolean) }

  try {

    if (editorForm.id) await patch(`/api/knowledge/${editorForm.id}`, body)

    else await post('/api/knowledge', body)

    ElMessage.success('已保存')

    editorVisible.value = false

    current.value = null

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

async function remove(row: any) {

  await ElMessageBox.confirm(`确认删除「${row.title}」？`, '删除确认', { type: 'warning' })

  try {

    await del(`/api/knowledge/${row.id}`)

    current.value = null

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

function fmtTime(s: string | null) {

  if (!s) return '-'

  return new Date(s).toLocaleString('zh-CN', { hour12: false })

}

</script>

<style scoped>

.filter-card { margin-bottom: 14px; }

.filters { display: flex; gap: 10px; align-items: center; }

.viewer { min-height: 420px; }

/* 详情头部：标题 / 标签 / 元信息三层分明，底部分隔线与正文区隔开 */

.viewer-head {

  display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;

  padding-bottom: 14px; margin-bottom: 16px; border-bottom: 1px solid #f0f2f5;

}

.viewer-main { flex: 1; min-width: 0; }

.viewer-head h2 { margin: 0 0 12px; font-size: 18px; line-height: 1.4; color: #1d2535; }

.meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }

.meta-info { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 10px; }

.meta-info .muted { margin-left: 0; }

.meta-sep { color: #c0c4cc; }

.viewer-ops { flex-shrink: 0; }

.problem-block {

  margin-bottom: 16px; padding: 12px 16px; background: #fdf6ec;

  border: 1px solid #faecd8; border-radius: 8px;

}

.problem-label, .solve-label { font-size: 12px; color: #909399; margin-bottom: 6px; font-weight: 600; }

/* 正文配图样式 */

.kb-img { max-width: 100%; max-height: 420px; display: block; margin: 6px 0; border-radius: 6px; border: 1px solid #ebeef5; cursor: zoom-in; }

.heat-badge {

  font-size: 12px; color: #909399; background: #f4f4f5;

  border-radius: 10px; padding: 1px 10px;

}

.heat-badge.hot { color: #f56c6c; background: #fef0f0; font-weight: 600; }

.content {

  padding: 16px 18px; line-height: 1.9; color: #303133;

  background: #fafbfc; border-radius: 8px; border: 1px solid #f0f2f5;

  font-size: 14px;

}

.pre-wrap { white-space: pre-wrap; word-break: break-word; }

.muted { color: #909399; font-size: 12px; }

</style>
