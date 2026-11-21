<template>
  <div>
    <!-- 顶部状态页签（第十八批排序）：等待处理 / 自建工单 / 转交工单 / 完结工单 / 接单广场 / 工单管理(仅管理员,默认视图) -->
    <el-card shadow="never" class="tab-card">
      <el-radio-group v-model="tab" class="status-tabs" @change="onTabChange">
        <el-radio-button value="open">等待处理</el-radio-button>
        <!-- v2.12 自建工单仅管理员/工程师：用于记录员工口头求助但未走工单的补充场景 -->
        <el-radio-button v-if="auth.isStaff" value="mine">自建工单</el-radio-button>
        <el-radio-button value="transferred">转交工单</el-radio-button>
        <el-radio-button value="done">完结工单</el-radio-button>
        <el-radio-button v-if="auth.isStaff" value="pool">接单广场</el-radio-button>
        <el-radio-button v-if="auth.isAdmin" value="manage">工单管理</el-radio-button>
      </el-radio-group>
    </el-card>

    <!-- 筛选栏 -->
    <el-card shadow="never" class="filter-card">
      <div class="filters">
        <!-- 第二十七批+：点击发起人/处理人后的人员筛选（可关闭） -->
        <el-tag v-if="personFilter" closable type="primary" effect="plain" style="height: 32px; padding: 0 10px" @close="clearPersonFilter">
          {{ personFilterLabel }}
        </el-tag>
        <!-- 第四十一批：搜索框加宽（占位符「搜索标题 / 描述 / 发起人 / 工单编号」需 217px+前缀图标，原 240px 渲染 174px 被截断；300px 渲染 234px 完整显示） -->
        <el-input v-model="query.q" placeholder="搜索标题/描述/发起人/工单编号" clearable style="width: 240px" @keyup.enter="load" @clear="load">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="query.category" placeholder="分类" clearable style="width: 140px" @change="load">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
        <div style="flex: 1"></div>
        <el-dropdown trigger="click" @command="toggleColumn">
          <el-button plain>
            <el-icon style="margin-right: 4px"><Setting /></el-icon>列设置
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="c in visibleOptionalColumns" :key="c.key" :command="c.key">
                <el-checkbox :model-value="!hiddenCols.includes(c.key)" @click.prevent />
                {{ c.label }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <!-- v2.11 导出仅管理员；第二十一批+ 更名「导出工单」 -->
        <el-button v-if="auth.isAdmin" plain :loading="exporting" @click="exportVisible = true">
          <el-icon style="margin-right: 4px"><Download /></el-icon>导出工单
        </el-button>
        <!-- 第三十七批：批量指派（仅工单管理页签，勾选后可用）；第四十二批：移除批量关闭避免误关闭 -->
        <template v-if="auth.isAdmin && tab === 'manage' && selectedTickets.length">
          <el-button plain type="primary" @click="openBatchAssign">
            批量指派（{{ selectedTickets.length }}）
          </el-button>
        </template>
        <el-button type="primary" plain @click="createVisible = true">
          <el-icon style="margin-right: 4px"><Plus /></el-icon>提交工单
        </el-button>
      </div>
    </el-card>

    <!-- 导出弹窗（v2.11 仅管理员）：日/月/年/全部 -->
    <el-dialog v-model="exportVisible" title="导出工单" width="440px">
      <el-form label-width="60px">
        <el-form-item label="范围">
          <el-radio-group v-model="exportMode">
            <el-radio-button value="day">按日</el-radio-button>
            <el-radio-button value="month">按月</el-radio-button>
            <el-radio-button value="year">按年</el-radio-button>
            <el-radio-button value="all">全部</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="exportMode !== 'all'" label="日期">
          <el-date-picker
            v-if="exportMode === 'day'"
            v-model="exportDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            style="width: 200px"
          />
          <el-date-picker
            v-else-if="exportMode === 'month'"
            v-model="exportDate"
            type="month"
            value-format="YYYY-MM-DD"
            placeholder="选择月份"
            style="width: 200px"
          />
          <el-date-picker
            v-else
            v-model="exportDate"
            type="year"
            value-format="YYYY-MM-DD"
            placeholder="选择年份"
            style="width: 200px"
          />
        </el-form-item>
        <el-form-item label="条件">
          <div class="muted" style="font-size: 12px">将带上当前列表的状态/分类/优先级筛选条件</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="exportVisible = false">取消</el-button>
        <el-button type="primary" :loading="exporting" @click="exportCsv">导出</el-button>
      </template>
    </el-dialog>

    <!-- 第三十七批：批量指派弹窗 -->
    <el-dialog v-model="batchAssignVisible" title="批量指派" width="440px">
      <el-form label-width="80px">
        <el-form-item label="工程师">
          <el-select v-model="batchEngineerId" filterable style="width: 100%" placeholder="选择目标工程师">
            <el-option v-for="e in engineerOptions" :key="e.id" :label="e.name || e.username" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="已选工单">
          <div class="muted" style="font-size: 12px">
            {{ selectedTickets.length }} 张（合并源单与已结单会自动跳过并提示）
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchAssignVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchLoading" @click="doBatchAssign">确定指派</el-button>
      </template>
    </el-dialog>

    <!-- 列表 -->
    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" stripe :row-class-name="rowClass" @selection-change="onTicketSelect">
        <!-- 第三十七批：批量操作多选列（仅工单管理页签） -->
        <el-table-column v-if="auth.isAdmin && tab === 'manage'" type="selection" width="42" />
        <!-- 第二十七批+：SLA 前置到编号之前；标签统一宽度 -->
        <el-table-column v-if="!hiddenCols.includes('sla')" label="SLA" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.resolve_breached || row.response_breached" type="danger" size="small" class="sla-tag">已超时</el-tag>
            <el-tag v-else type="success" size="small" effect="plain" class="sla-tag">正常</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="工单编号" min-width="132">
          <template #default="{ row }">
            <el-link :style="{ color: priorityColor(row.priority), fontWeight: 600 }" @click="$router.push(`/tickets/${row.id}`)">{{ row.no }}</el-link>
          </template>
        </el-table-column>
        <!-- 第二十八批+：发起人/处理人移到问题概述之前；「标题」→「问题概述」、「分类」→「问题分类」（与建单弹窗名词一致） -->
        <el-table-column v-if="!hiddenCols.includes('creator')" label="发起人" min-width="100" class-name="col-sm-hide">
          <template #default="{ row }">
            <span v-if="row.creator" class="person-link" title="查看该人员当前未完结工单" @click="filterByPerson(row.creator, 'creator')">{{ row.creator.name }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!hiddenCols.includes('assignee')" label="处理人" min-width="100" class-name="col-sm-hide">
          <template #default="{ row }">
            <span v-if="row.assignee" class="person-link" title="查看该人员当前未完结工单" @click="filterByPerson(row.assignee, 'assignee')">{{ row.assignee.name }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!hiddenCols.includes('category')" prop="category" label="问题分类" min-width="92" class-name="col-sm-hide" />
        <el-table-column prop="title" label="问题概述" min-width="420" show-overflow-tooltip />
        <!-- v2.12 认领/转办操作统一在工单详情页执行，列表不再放操作列 -->
        <el-table-column v-if="!hiddenCols.includes('created')" label="创建时间" min-width="160">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="query.page"
          :page-size="query.page_size"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="load"
        />
      </div>
    </el-card>

    <!-- 建单弹窗 -->
    <el-dialog v-model="createVisible" title="提交工单" width="560px">
      <el-form label-width="80px">
        <el-form-item label="问题概述" required>
          <el-input v-model="form.title" maxlength="200" show-word-limit placeholder="一句话描述问题" />
        </el-form-item>
        <!-- 第二十八批+：建单知识库推荐——输入问题概述后自动匹配匿名可见 FAQ，自助拦截重复工单 -->
        <el-form-item v-if="kbHits.length" label="相关自助">
          <div class="kb-recommend">
            <div v-for="k in kbHits" :key="k.id" class="kb-hit" @click="toggleKb(k.id)">
              <span class="kb-hit-title">{{ k.title }}</span>
              <span class="kb-hit-arrow">{{ kbExpanded === k.id ? '收起' : '查看' }}</span>
              <div v-if="kbExpanded === k.id" class="kb-hit-body">
                <div v-if="k.problem" class="kb-sec"><b>问题描述：</b>{{ k.problem }}</div>
                <div class="kb-sec"><b>解决方法：</b>{{ k.content || '见常见问题页' }}</div>
              </div>
            </div>
            <div class="muted" style="font-size: 12px">如可自行处理，无需提交工单</div>
          </div>
        </el-form-item>
        <!-- 第二十七批+：分类上移并与详细描述互换；分类更名为「问题分类」 -->
        <el-form-item label="问题分类">
          <el-select v-model="form.category" style="width: 100%" @change="onCategoryChange">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
          <!-- 第三十八批：智能分类建议（TF-IDF 基于历史工单，点击采纳；人工复核兜底不自动改派） -->
          <div v-if="suggestItems.length" class="suggest-bar">
            <span class="muted" style="margin-right: 6px">智能推荐：</span>
            <el-tag
              v-for="s in suggestItems" :key="s.category" size="small"
              :type="s.category === form.category ? 'success' : 'primary'"
              effect="plain" class="suggest-chip"
              @click="adoptSuggest(s.category)"
            >{{ s.category }}（{{ s.confidence }}%）</el-tag>
            <el-tag v-if="suggestPriority && !form.priority" size="small" type="warning" effect="plain" class="suggest-chip" @click="form.priority = suggestPriority">
              建议优先级：{{ ({ urgent: '危急', high: '高', low: '低' } as any)[suggestPriority] }}
            </el-tag>
          </div>
        </el-form-item>
        <!-- v2.12 软件安装申请：分类选「软件安装」时可从软件目录选择，形成申请→安装闭环；
             第二十二批+ 增强：可按 名称/类型/部门 检索，支持「列表外软件」手输 -->
        <el-form-item v-if="form.category === '软件安装'" label="申请软件">
          <el-select v-model="form.software_id" clearable filterable style="width: 100%" placeholder="输入名称检索，或按 软件类型/适用部门 筛选">
            <el-option
              v-for="s in softwareCatalog" :key="s.id"
              :label="`${s.name}（${s.category || '未分类'}${s.departments ? ' · ' + s.departments : ''} · ${s.license_type}）`"
              :value="s.id"
            >
              <span>{{ s.name }}<span class="muted" style="margin-left: 8px">{{ s.category || '未分类' }}{{ s.departments ? ' · ' + s.departments : '' }}</span></span>
            </el-option>
            <el-option key="outside" label="其他（列表外软件，手动填写）" :value="-1" />
          </el-select>
          <el-input
            v-if="form.software_id === -1"
            v-model="form.software_outside"
            maxlength="100"
            placeholder="请填写需要安装的软件名称及版本（不在公司允许安装目录内）"
            style="margin-top: 8px"
          />
          <div class="muted" style="font-size: 12px; margin-top: 2px">
            目录内软件提交后自动关联软件信息；列表外软件将由 IT 评估是否允许安装
          </div>
        </el-form-item>
        <!-- 第二十九批+：申请软件/账号权限/硬件设备 分类专属选项置于详细描述上方 -->
        <el-form-item v-if="form.category === '账号权限'" label="申请类型">
          <el-radio-group v-model="form.accountType">
            <el-radio-button value="账户密码找回">账户密码找回</el-radio-button>
            <el-radio-button value="账户权限申请">账户权限申请</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.category === '硬件设备'" label="设备类型">
          <el-radio-group v-model="form.deviceType">
            <el-radio-button v-for="d in ['笔记本', '台式机', '显示器', '键盘鼠标', '其他设备']" :key="d" :value="d">{{ d }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.category === '打印设备'" label="故障类型">
          <el-radio-group v-model="form.printType">
            <el-radio-button value="连打印机">连打印机</el-radio-button>
            <el-radio-button value="打印报错">打印报错</el-radio-button>
            <el-radio-button value="设备报修">设备报修</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <!-- 第三十八批：网络故障故障类型选项置于详细描述上方 -->
        <el-form-item v-if="form.category === '网络故障'" label="故障类型">
          <el-radio-group v-model="form.networkType">
            <el-radio-button value="无法访问网络">无法访问网络</el-radio-button>
            <el-radio-button value="无法访问网站">无法访问网站</el-radio-button>
            <el-radio-button value="网站显示异常">网站显示异常</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="详细描述">
          <el-input v-model="form.description" type="textarea" :rows="4" placeholder="什么现象、从什么时候开始、影响范围…" />
        </el-form-item>
        <!-- 模板自定义字段（v2.1 支持 visible_if 级联显隐） -->
        <el-form-item
          v-for="f in visibleTemplateFields"
          :key="f.key"
          :label="f.label"
          :required="f.required"
        >
          <el-input v-if="f.type === 'text'" v-model="form.custom_fields[f.key]" />
          <el-input v-else-if="f.type === 'textarea'" v-model="form.custom_fields[f.key]" type="textarea" :rows="2" />
          <el-select v-else-if="f.type === 'select'" v-model="form.custom_fields[f.key]" style="width: 100%">
            <el-option v-for="o in f.options" :key="o" :label="o" :value="o" />
          </el-select>
        </el-form-item>
        <el-form-item label="影响范围">
          <el-radio-group v-model="form.impact">
            <el-radio-button value="individual">个人</el-radio-button>
            <el-radio-button value="department">部门</el-radio-button>
            <el-radio-button value="company">全公司</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="紧急程度">
          <el-radio-group v-model="form.urgency">
            <el-radio-button value="low">低</el-radio-button>
            <el-radio-button value="normal">普通</el-radio-button>
            <el-radio-button value="high">紧急</el-radio-button>
            <el-radio-button value="critical">危急</el-radio-button>
          </el-radio-group>
          <div class="muted" style="font-size: 12px; margin-top: 2px">优先级由系统按「影响范围 × 紧急程度」自动计算</div>
        </el-form-item>
        <el-form-item label="关联资产">
          <el-select v-model="form.asset_id" clearable filterable placeholder="选择你的设备（可选）" style="width: 100%">
            <el-option v-for="a in assets" :key="a.id" :label="`${a.asset_tag} ${a.name}`" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="代报修">
          <el-select v-model="form.requester_id" clearable filterable remote :remote-method="searchDirectory" placeholder="替谁报修？（选填，留空=自己）" style="width: 100%">
            <el-option v-for="u in directory" :key="u.id" :label="`${u.name}${u.department ? ' · ' + u.department : ''}`" :value="u.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCreate">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { download, get, post } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const loading = ref(false)
const items = ref<any[]>([])
const total = ref(0)
const categories = ref<string[]>([])

// 第二十七批+：点击发起人/处理人 → 筛选该人员当前未完结工单（切「等待处理」页签）
const personFilter = ref<{ id: number; name: string; type: 'creator' | 'assignee' } | null>(null)
const personFilterLabel = computed(() => personFilter.value ? `${personFilter.value.type === 'creator' ? '发起人' : '处理人'}：${personFilter.value.name}（未完结）` : '')

function filterByPerson(person: any, type: 'creator' | 'assignee') {
  if (!person?.id) return
  personFilter.value = { id: person.id, name: person.name || person.username, type }
  query.creator_id = type === 'creator' ? person.id : null
  query.assignee_id = type === 'assignee' ? person.id : null
  query.q = ''
  query.page = 1
  tab.value = 'open'
  load()
}

function clearPersonFilter() {
  personFilter.value = null
  query.creator_id = null
  query.assignee_id = null
  query.page = 1
  load()
}
const assets = ref<any[]>([])
const query = reactive<any>({ q: '', status: '', category: '', priority: '', page: 1, page_size: 20, creator_id: null as number | null, assignee_id: null as number | null })
// v2.11 页签：工单管理(仅管理员，默认) / 等待处理 / 自建工单 / 转交工单 / 完结工单 / 接单广场
const tab = ref<'manage' | 'open' | 'transferred' | 'done' | 'mine' | 'pool'>(auth.isAdmin ? 'manage' : 'open')

const createVisible = ref(false)
const submitting = ref(false)
const exporting = ref(false)
const exportVisible = ref(false)
const exportMode = ref<'day' | 'month' | 'year' | 'all'>('day')
const exportDate = ref(new Date().toISOString().slice(0, 10))
const claimingId = ref<number | null>(null)

// 第三十七批：批量操作（仅工单管理页签）
const selectedTickets = ref<any[]>([])
const batchAssignVisible = ref(false)
const batchLoading = ref(false)
const batchEngineerId = ref<number | null>(null)
const engineerOptions = ref<any[]>([])

function onTicketSelect(rows: any[]) {
  selectedTickets.value = rows
}

async function openBatchAssign() {
  batchEngineerId.value = null
  batchAssignVisible.value = true
  if (!engineerOptions.value.length) {
    try {
      const res = await get('/api/users?role=engineer')
      engineerOptions.value = (res.items || []).filter((u: any) => u.is_active)
    } catch { /* 下拉加载失败不阻塞 */ }
  }
}

async function doBatchAssign() {
  if (!batchEngineerId.value) return ElMessage.warning('请选择目标工程师')
  batchLoading.value = true
  try {
    const res = await post('/api/tickets/batch-assign', {
      ticket_ids: selectedTickets.value.map((t) => t.id),
      engineer_id: batchEngineerId.value,
    })
    if (res.failed?.length) {
      ElMessage.warning(`已指派 ${res.assigned} 张，${res.failed.length} 张失败：${res.failed.map((f: any) => `${f.no || f.id}(${f.reason})`).join('；')}`)
    } else {
      ElMessage.success(`已批量指派 ${res.assigned} 张工单`)
    }
    batchAssignVisible.value = false
    selectedTickets.value = []
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '批量指派失败')
  } finally {
    batchLoading.value = false
  }
}


// v2.7 列字段设置：localStorage 偏好
const OPTIONAL_COLUMNS = [
  { key: 'category', label: '问题分类' },
  { key: 'creator', label: '发起人' },
  { key: 'assignee', label: '处理人' },
  { key: 'sla', label: 'SLA' },
  { key: 'created', label: '创建时间' },
]
// v2.12 分类列默认隐藏：老用户 localStorage 无 v2 标记时应用新默认（一次性迁移）
const HIDDEN_DEFAULT = '[\"created\",\"category\"]'
const hiddenCols = ref<string[]>((() => {
  const saved = JSON.parse(
    localStorage.getItem('itops_ticket_cols_v2') || (localStorage.getItem('itops_ticket_cols') ? localStorage.getItem('itops_ticket_cols')! : HIDDEN_DEFAULT)
  )
  // 第二十八批+：问题分类列已移到处理人与问题概述之间并默认显示——历史隐藏偏好一次性迁移
  const cleaned = saved.filter((k: string) => k !== 'category')
  if (cleaned.length !== saved.length) localStorage.setItem('itops_ticket_cols_v2', JSON.stringify(cleaned))
  return cleaned
})())
function persistCols() {
  localStorage.setItem('itops_ticket_cols_v2', JSON.stringify(hiddenCols.value))
}

// v2.11 处理人列只在工单管理页签存在，列设置里也仅该页签提供此开关
const visibleOptionalColumns = computed(() =>
  OPTIONAL_COLUMNS
)
function toggleColumn(key: string) {
  const i = hiddenCols.value.indexOf(key)
  if (i >= 0) hiddenCols.value.splice(i, 1)
  else hiddenCols.value.push(key)
  persistCols()
}

/** 一键转办：认领他人的加急工单到自己名下 */
async function claim(row: any) {
  claimingId.value = row.id
  try {
    await post(`/api/tickets/${row.id}/claim`)
    ElMessage.success(`已认领：工单 ${row.no} 到您名下，可开始沟通处理`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    claimingId.value = null
  }
}
const form = reactive<any>({ title: '', description: '', category: '其他问题', priority: 'medium', impact: 'individual', urgency: 'normal', asset_id: null, custom_fields: {}, requester_id: null, software_id: null, software_outside: '', accountType: '', deviceType: '', printType: '', networkType: '' })
const templateFields = ref<any[]>([])
const directory = ref<any[]>([])
// v2.12 软件目录（分类选「软件安装」时供员工选择申请安装）
const softwareCatalog = ref<any[]>([])

async function searchDirectory(q: string) {
  try {
    const res = await get(`/api/users/directory${q ? `?q=${encodeURIComponent(q)}` : ''}`)
    directory.value = res.items
  } catch { /* ignore */ }
}

// v2.1 字段级联：visible_if 指定的参照字段值在 in 列表内才显示
function fieldVisible(f: any): boolean {
  const rule = f.visible_if
  if (!rule || !rule.field) return true
  return (rule.in || []).includes(form.custom_fields[rule.field])
}

const visibleTemplateFields = computed(() => templateFields.value.filter(fieldVisible))

/** 提交前清掉因级联被隐藏的字段值（后端同样校验） */
function cleanCustomFields(): Record<string, any> {
  const cf: Record<string, any> = { ...form.custom_fields }
  for (const f of templateFields.value) {
    if (!fieldVisible(f)) delete cf[f.key]
  }
  return cf
}

async function onCategoryChange(category: string) {
  form.custom_fields = {}
  templateFields.value = []
  if (!category) return
  // v2.12 软件安装分类：拉取软件目录供选择
  if (category === '软件安装' && !softwareCatalog.value.length) {
    try {
      softwareCatalog.value = (await get('/api/softwares')).items.filter((s: any) => s.enabled)
    } catch { /* 目录拉取失败不阻塞建单 */ }
  }
  try {
    const res = await get(`/api/tickets/templates/by-category?category=${encodeURIComponent(category)}`)
    if (res.items.length) {
      templateFields.value = res.items[0].fields
      if (res.items[0].priority && !form.priority) form.priority = res.items[0].priority
    }
  } catch { /* 模板加载失败不阻塞建单 */ }
}

async function exportCsv() {
  if (!auth.isAdmin) return ElMessage.warning('导出仅管理员可用')
  if (exportMode.value !== 'all' && !exportDate.value) return ElMessage.warning('请选择日期')
  exporting.value = true
  try {
    const params = new URLSearchParams()
    params.set('mode', exportMode.value)
    if (exportMode.value !== 'all' && exportDate.value) params.set('date', exportDate.value)
    ;['status', 'category', 'priority', 'creator_id', 'assignee_id'].forEach((k) => {
      if (query[k]) params.set(k, String(query[k]))
    })
    if (query.q && String(query.q).trim()) params.set('q', String(query.q).trim())
    const tag = exportMode.value === 'all' ? '全部' : exportDate.value
    await download(`/api/export/tickets?${params}`, `工单导出_${tag}.csv`)
    exportVisible.value = false
  } catch (e: any) {
    ElMessage.error(e.message || '导出失败')
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  try {
    const info = await get('/api/admin/info')
    categories.value = info.categories
  } catch { /* 员工无权拿 info，用默认分类 */ categories.value = ['软件安装', '账号权限', '硬件设备', '打印设备', '网络故障', '其他问题'] }
  try {
    const res = await get('/api/assets')
    assets.value = res.items
  } catch { /* ignore */ }
  searchDirectory('')
  await load()
})

function onTabChange() {
  query.page = 1
  load()
}

function reorderMerged(list: any[]) {
  const groups = new Map<number, any[]>()
  list.forEach((t) => {
    const root = t.merged_into_id || t.id
    if (!groups.has(root)) groups.set(root, [])
    groups.get(root)!.push(t)
  })
  const multi = [...groups.entries()].filter(([, arr]) => arr.length > 1)
  if (!multi.length) return list
  const out: any[] = []
  // 组间：最新创建的合并组在前
  multi.sort((a, b) => Math.max(...b[1].map((x: any) => x.id)) - Math.max(...a[1].map((x: any) => x.id)))
  multi.forEach(([, arr]) => out.push(...arr.sort((x: any, y: any) => x.id - y.id)))
  const rest = list.filter((t) => {
    const root = t.merged_into_id || t.id
    return groups.get(root)!.length === 1
  })
  out.push(...rest)
  return out
}

const rowClassMap = ref<Record<number, string>>({})

function buildRowClassMap() {
  // 第二十八批+：等待处理页签下，合并组行整行微细框线（首行上框线、尾行下框线）
  const map: Record<number, string> = {}
  if (tab.value !== 'open') { rowClassMap.value = map; return }
  const groups = new Map<number, any[]>()
  items.value.forEach((t) => {
    const root = t.merged_into_id || t.id
    if (!groups.has(root)) groups.set(root, [])
    groups.get(root)!.push(t)
  })
  groups.forEach((arr, root) => {
    if (arr.length <= 1) return
    arr.sort((x: any, y: any) => x.id - y.id)
    arr.forEach((t: any, i: number) => {
      let cls = 'merged-row'
      if (i === 0) cls += ' merged-row-first'
      if (i === arr.length - 1) cls += ' merged-row-last'
      map[t.id] = cls
    })
  })
  rowClassMap.value = map
}

function rowClass({ row }: { row: any }) {
  return rowClassMap.value[row.id] || ''
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    Object.entries(query).forEach(([k, v]) => {
      if (v !== '' && v !== null && v !== undefined) params.set(k, String(v))
    })
    if (auth.isStaff && tab.value === 'manage') params.set('scope', 'manage')
    if (tab.value === 'open') params.set('period', 'open')
    if (tab.value === 'transferred') params.set('transferred', 'true')
    if (tab.value === 'done') params.set('period', 'done')
    if (tab.value === 'mine') params.set('mine', 'true')
    if (tab.value === 'pool') {
      // v2.11 接单广场：超过 30 分钟仍未分配的工单，工程师可一键转给自己
      params.set('pool', 'true')
      params.set('pool_minutes', '30')
    }
    const data = await get(`/api/tickets?${params}`)
    // 第二十八批+：合并组置顶连续排列仅「等待处理」页签生效（工单管理等正常排序）
    items.value = tab.value === 'open' ? reorderMerged(data.items) : data.items
    buildRowClassMap()
    total.value = data.total
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

const kbHits = ref<any[]>([])
const kbExpanded = ref<number | null>(null)
let kbTimer: any = null

function toggleKb(id: number) {
  if (kbExpanded.value === id) { kbExpanded.value = null; return }
  const hit = kbHits.value.find((k) => k.id === id)
  if (hit && !hit.content) {
    get(`/api/public/knowledge/${id}`).then((res) => {
      const i = kbHits.value.findIndex((k) => k.id === id)
      if (i >= 0) kbHits.value[i] = res
    }).catch(() => {})
  }
  kbExpanded.value = id
}

function fetchKbHits() {
  clearTimeout(kbTimer)
  kbTimer = setTimeout(() => {
    const q = `title=${encodeURIComponent(form.title || '')}&description=${encodeURIComponent(form.description || '')}`
    get(`/api/public/knowledge/search?${q}`).then((res) => { kbHits.value = res.items }).catch(() => {})
  }, 600)
}

watch(() => [form.title, form.description], () => { if (createVisible.value) fetchKbHits() })

// ---- 第三十八批：智能分类建议（TF-IDF，人工复核兜底） ----
const suggestItems = ref<any[]>([])
const suggestPriority = ref('')
let sugTimer: any = null

function fetchSuggest() {
  clearTimeout(sugTimer)
  sugTimer = setTimeout(() => {
    const q = `title=${encodeURIComponent(form.title || '')}&description=${encodeURIComponent(form.description || '')}`
    get(`/api/tickets/classify-suggest?${q}`).then((res) => {
      suggestItems.value = res.items || []
      suggestPriority.value = res.priority || ''
    }).catch(() => {})
  }, 600)
}

watch(() => [form.title, form.description], () => { if (createVisible.value) fetchSuggest() })

function adoptSuggest(cat: string) {
  if (form.category === cat) return
  form.category = cat
  onCategoryChange(cat)
  ElMessage.success(`已采纳分类建议：${cat}`)
}

async function submitCreate() {
  if (!form.title.trim()) return ElMessage.warning('请填写问题概述')
  // 列表外软件必须手输名称
  if (form.software_id === -1 && !String(form.software_outside || '').trim()) {
    return ElMessage.warning('请填写需要安装的软件名称')
  }
  // 必填自定义字段校验（仅当前可见的字段）
  for (const f of visibleTemplateFields.value) {
    if (f.required && !String(form.custom_fields[f.key] || '').trim()) {
      return ElMessage.warning(`请填写「${f.label}」`)
    }
  }
  submitting.value = true
  try {
    // 第二十二批+：列表外软件（software_id=-1）→ 不传 software_id，改为 custom_fields 软件标记（outside）
    const body: any = { ...form, custom_fields: cleanCustomFields() }
    if (form.software_id === -1) {
      body.custom_fields = { ...(body.custom_fields || {}), software: { name: String(form.software_outside || '').trim(), outside: true } }
      delete body.software_id
    }
    // 第二十九批+：账号权限/硬件设备 的类型选项写入自定义字段（详情页展示）
    if (form.category === '账号权限' && form.accountType) body.custom_fields['申请类型'] = form.accountType
    if (form.category === '硬件设备' && form.deviceType) body.custom_fields['设备类型'] = form.deviceType
    if (form.category === '打印设备' && form.printType) body.custom_fields['故障类型'] = form.printType
    if (form.category === '网络故障' && form.networkType) body.custom_fields['故障类型'] = form.networkType
    const d = await post('/api/tickets', body)
    createVisible.value = false
    form.title = ''; form.description = ''; form.requester_id = null; form.software_id = null; form.software_outside = ''; form.accountType = ''; form.deviceType = ''; form.printType = ''; form.networkType = ''
    let msg = d.merged_into
      ? `您已有未完结的软件安装工单，本次申请已并入 ${d.merged_into.no} 一并处理`
      : d.deferred
        ? `工单 ${d.no} 已提交（其他问题 15 分钟内暂不指派，工程师可认领，超时自动按负载分配）`
        : `工单 ${d.no} 已提交`
    if (d.auto_assigned) msg += `，已自动指派给 ${d.auto_assigned}`
    const similar: any[] = d.similar_tickets || []
    if (similar.length) {
      msg += `。发现疑似重复工单：${similar.map((s) => s.no).join('、')}`
      ElMessage({ type: 'warning', message: msg, duration: 6000, showClose: true })
    } else {
      ElMessage.success(msg)
    }
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

function fmtTime(s: string | null) {
  if (!s) return '-'
  return new Date(s).toLocaleString('zh-CN', { hour12: false })
}
function priorityColor(p: string) {
  // 第二十八批+：A/B/C/D 四级配色增强——灰/绿/橙/红 梯度区分明显
  return ({ urgent: '#f56c6c', high: '#e6a23c', medium: '#67c23a', low: '#909399' } as any)[p] || '#67c23a'
}
</script>

<style scoped>
.filter-card { margin-bottom: 14px; }
/* 第四十二批：表格最小高度固定——切页签时高度稳定，消除行高抖动 */
:deep(.el-table) { min-height: 420px; }
.filters { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sla-tag { width: 52px; justify-content: center; }
/* 合并组行框选（第二十八批+）：整行微细框线，无背景色 */
:deep(.el-table .merged-row-first td) { border-top: 1px solid #e6c88a !important; }
:deep(.el-table .merged-row-last td) { border-bottom: 1px solid #e6c88a !important; }
.person-link { color: #2f6fed; cursor: pointer; }
.person-link:hover { text-decoration: underline; }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.muted { color: #909399; font-size: 12px; }
@media (max-width: 768px) {
  .filters { flex-wrap: wrap; }
  .filters .el-input { width: 100% !important; }
}
</style>

/* 建单知识库推荐（第二十八批+） */
.kb-recommend { width: 100%; display: flex; flex-direction: column; gap: 6px; }
.kb-hit { background: #f0f9eb; border: 1px solid #e1f3d8; border-radius: 6px; padding: 8px 10px; cursor: pointer; font-size: 13px; }
.kb-hit-title { font-weight: 600; color: #303133; margin-right: 8px; }
.kb-hit-arrow { color: #2f6fed; font-size: 12px; }
.kb-hit-body { margin-top: 6px; color: #5a6478; line-height: 1.7; }
.kb-sec { margin-bottom: 4px; }

/* 第三十八批：智能分类建议条 */
.suggest-bar { width: 100%; margin-top: 6px; display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 12px; }
.suggest-chip { cursor: pointer; }
