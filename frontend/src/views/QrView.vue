<template>
  <div class="qr-page">
    <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon />
    <!-- 第四十一批 F1：离线兜底恢复重试按钮 -->
    <div v-if="error" style="text-align: center; margin-top: 12px">
      <el-button type="primary" plain @click="retry">重试</el-button>
    </div>
    <template v-else-if="info">
      <!-- ============ 会议室码分支（v2.12）：预约状态 / 设备说明 / 检查填报 ============ -->
      <template v-if="info.kind === 'room'">
        <!-- 维修公告：重要设备维修中才显示（扫码另弹窗提醒） -->
        <el-alert v-if="info.room.under_maintenance" type="error" :closable="false" show-icon class="room-alert">
          <template #title>⚠ 设备维修公告：{{ info.room.maintenance_notice || '该会议室重要设备维修中，暂停使用' }}</template>
        </el-alert>

        <el-card shadow="never" class="head-card">
          <div class="head">
            <el-tag type="danger" size="large">会议室</el-tag>
            <div class="head-main">
              <div class="head-title">{{ info.room.name }}</div>
              <div class="head-sub">
                <template v-if="info.room.location"><el-icon><Location /></el-icon>{{ info.room.location }}</template>
                <span class="dot">·</span>
                <span>容纳 {{ info.room.capacity }} 人</span>
                <el-tag v-if="info.latest_inspection" size="small" type="success" effect="plain" style="margin-left: 8px">
                  最近检查：{{ new Date(info.latest_inspection.inspected_at).toLocaleDateString('zh-CN') }}
                </el-tag>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 第三十九批 b：设备列表（员工判断能否满足使用需要） -->
        <el-card v-if="(info.room.equipment_list || []).length" shadow="never">
          <template #header><span>会议室设备</span></template>
          <div class="equip-grid">
            <div v-for="e in info.room.equipment_list" :key="e.name" class="equip-item">
              <span class="equip-name">{{ e.name }}<template v-if="e.count > 1"> ×{{ e.count }}</template></span>
              <el-tag size="small" :type="e.status === '正常' ? 'success' : e.status === '损坏' ? 'danger' : 'warning'" effect="plain">{{ e.status }}</el-tag>
            </div>
          </div>
        </el-card>

        <!-- 设备使用说明（全员可见） -->
        <el-card v-if="info.room.equipment_desc" shadow="never">
          <template #header><span>使用说明</span></template>
          <div class="pre-wrap equip-desc">{{ info.room.equipment_desc }}</div>
        </el-card>

        <!-- 预约状态：未来 14 天 -->
        <el-card shadow="never">
          <template #header>
            <span>预约情况（未来 14 天）</span>
            <el-button size="small" text type="primary" @click="load">刷新</el-button>
          </template>
          <el-empty v-if="!info.bookings.length" description="暂无预约，可直接在下方提交预约" :image-size="70" />
          <div v-else class="booking-list">
            <div v-for="b in info.bookings" :key="b.id" class="booking-row">
              <span class="bk-date">{{ b.date }}</span>
              <span class="bk-time">{{ b.start_time }} - {{ b.end_time }}</span>
              <el-tag :type="phaseTag[bookingPhase(b)]" size="small" effect="plain">{{ phaseLabel[bookingPhase(b)] }}</el-tag>
              <span class="bk-title">{{ b.title || '会议' }}</span>
              <span class="bk-booker">{{ b.booker?.name || '-' }}</span>
              <!-- v2.12 预约人/管理员扫码可取消未开始的预约、提前结束进行中的会议 -->
              <template v-if="authed && (is_admin || b.booker?.id === me?.id)">
                <el-button v-if="bookingPhase(b) === 'ongoing' && !b.checkin_at" size="small" text type="success" @click="checkinBooking(b)">到场签到</el-button>
                <el-tag v-if="b.checkin_at" size="small" type="success" effect="plain">已签到</el-tag>
                <el-button v-if="bookingPhase(b) === 'ongoing'" size="small" text type="warning" @click="endBooking(b)">提前结束</el-button>
                <el-button v-else-if="bookingPhase(b) === 'upcoming'" size="small" text type="danger" @click="cancelBooking(b)">取消</el-button>
              </template>
            </div>
          </div>
        </el-card>

        <!-- 预约表单：登录后可预约 -->
        <el-card shadow="never">
          <template #header><span>预约此会议室</span></template>
          <el-form v-if="authed" label-width="70px" style="max-width: 520px">
            <el-form-item label="日期" required>
              <el-date-picker
                v-model="bkForm.date" type="date" value-format="YYYY-MM-DD" :clearable="false" style="width: 100%"
                :disabled-date="(d: Date) => d.getTime() < Date.now() - 86400000"
              />
            </el-form-item>
            <el-form-item label="时段" required>
              <div style="display: flex; gap: 8px; align-items: center; width: 100%">
                <el-time-select v-model="bkForm.start" start="08:00" end="20:00" step="00:30" style="flex: 1" placeholder="开始" />
                <span>至</span>
                <el-time-select v-model="bkForm.end" start="08:00" end="21:00" step="00:30" style="flex: 1" placeholder="结束" />
              </div>
            </el-form-item>
            <el-form-item label="主题">
              <el-input v-model="bkForm.title" maxlength="200" placeholder="会议主题（选填）" />
            </el-form-item>
            <!-- v2.12 周期性预约：每周同一时段连建 N 场，冲突场次自动跳过 -->
            <el-form-item label="重复">
              <el-select v-model="bkForm.weeks" style="width: 100%">
                <el-option label="仅本次" :value="1" />
                <el-option label="每周一次，共 4 周" :value="4" />
                <el-option label="每周一次，共 8 周" :value="8" />
                <el-option label="每周一次，共 12 周" :value="12" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="booking" @click="submitBooking">提交预约</el-button>
            </el-form-item>
          </el-form>
          <el-result v-else icon="info" title="登录后可预约会议室" sub-title="查看预约状态与设备说明无需登录">
            <template #extra>
              <el-button type="primary" @click="goLogin">员工登录</el-button>
            </template>
          </el-result>
        </el-card>

        <!-- 管理员：设备检查填报（工作留痕） -->
        <el-card v-if="is_admin" shadow="never">
          <template #header><span>会议室设备检查（管理员填报，留痕可追溯）</span></template>
          <div class="check-list">
            <div v-for="c in info.check_items" :key="c[0]" class="check-row">
              <span class="check-label">{{ c[1] }}</span>
              <el-radio-group v-model="checkForm.results[c[0]]" size="small">
                <el-radio-button value="ok">正常</el-radio-button>
                <el-radio-button value="fail">异常</el-radio-button>
              </el-radio-group>
            </div>
          </div>
          <el-input
            v-model="checkForm.note" type="textarea" :rows="3" style="margin-top: 10px"
            placeholder="备注：是否有丢失、损坏、需报修的硬件（如：遥控器电池耗尽；HDMI 线破损需报修）"
          />
          <el-button type="primary" style="margin-top: 10px" :loading="checking" @click="submitCheck">提交检查结果</el-button>
        </el-card>
      </template>

      <!-- ============ 报修码分支（位置/设备/指定派单） ============ -->
      <template v-else>
      <!-- 扫码信息卡：位置 / 设备 / 指定处理人 -->
      <el-card shadow="never" class="head-card">
        <div class="head">
          <el-tag :type="kindTag[info.kind] || 'info'" size="large">{{ info.kind_label }}</el-tag>
          <div class="head-main">
            <div class="head-title">{{ info.name }}</div>
            <div class="head-sub">
              <template v-if="info.location"><el-icon><Location /></el-icon>{{ info.location }}</template>
              <span v-if="info.device && info.location" class="dot">·</span>
              <template v-if="info.device">
                <el-icon><Monitor /></el-icon>
                {{ info.device.name }}<template v-if="info.device.model">（{{ info.device.model }}）</template>
                <template v-if="info.device.ip">，IP {{ info.device.ip }}</template>
              </template>
            </div>
            <div v-if="info.forced_engineer" class="head-sub assign">
              <el-icon><User /></el-icon>本码工单将直接指派给：{{ info.forced_engineer.name }}
            </div>
          </div>
        </div>
      </el-card>

      <!-- 此码下的未结工单：处理人 / 进度 / 排队位次 -->
      <el-card shadow="never">
        <template #header>
          <span>{{ ticketListTitle }}</span>
          <el-button size="small" text type="primary" @click="load">刷新</el-button>
        </template>
        <el-empty v-if="!info.open_tickets.length" description="当前没有进行中的工单，有问题可直接在下方提交" :image-size="70" />
        <div v-else class="ticket-list">
          <div v-for="t in info.open_tickets" :key="t.id" class="ticket-row" :class="{ clickable: authed }" @click="authed && goDetail(t.id)">
            <div class="ticket-left">
              <span class="no">{{ t.no }}</span>
              <span class="title">{{ t.title }}</span>
            </div>
            <div class="ticket-right">
              <span v-if="showCreator && t.creator" class="assignee">提交人：{{ t.creator }}</span>
              <el-tag v-if="t.urgent" type="danger" size="small" effect="dark">加急</el-tag>
              <el-tag :type="statusTag[t.status] || 'info'" size="small">{{ t.status_label }}</el-tag>
              <span v-if="t.assignee" class="assignee">处理人：{{ t.assignee.name }}</span>
              <el-tag v-if="t.queue_ahead > 0" type="warning" size="small" effect="plain">前面还有 {{ t.queue_ahead }} 单</el-tag>
              <el-tag v-else type="success" size="small" effect="plain">轮到处理中</el-tag>
              <el-button
                v-if="authed && t.status !== 'pending_confirm'"
                size="small"
                :type="t.urgent ? 'info' : 'danger'"
                :plain="!!t.urgent"
                :loading="escalatingId === t.id"
                @click.stop="escalate(t)"
              >{{ t.urgent ? '再次加急' : '加急处理' }}</el-button>
            </div>
          </div>
          <div class="hint">{{ authed ? '点击任意一单可查看完整进度与留言；提交新问题不影响已提交的工单。' : '同一问题无需重复提交，工程师会按顺序统一处理。' }}</div>
        </div>
      </el-card>

      <!-- 再提交一单：预填分类/资产，扫码信息由后端自动附加 -->
      <el-card shadow="never">
        <template #header><span>提交新工单</span></template>
        <!-- 设备码需登录提交（关联设备使用人）：登录引导与会议室码样式一致 -->
        <el-result v-if="info.kind === 'device' && !authed" icon="info" title="登录后可提交工单" sub-title="设备码需登录后提交；登录后可跟踪进度、留言与加急">
          <template #extra>
            <el-button type="primary" @click="goLogin">员工登录</el-button>
          </template>
        </el-result>
        <el-form v-else label-width="80px" style="max-width: 560px">
          <el-form-item label="问题概述" required>
            <el-input v-model="form.title" maxlength="200" show-word-limit placeholder="一句话描述问题" />
          </el-form-item>
          <!-- 第二十八批+：建单知识库推荐（匿名可见 FAQ） -->
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
          <el-form-item label="问题分类">
            <el-select v-model="form.category" style="width: 100%" @change="onCategoryChange">
              <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
            </el-select>
          </el-form-item>
          <!-- 第二十九批+：账号权限/硬件设备 分类专属选项 -->
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
          <!-- 第三十八批：网络故障故障类型选项 -->
          <el-form-item v-if="form.category === '网络故障'" label="故障类型">
            <el-radio-group v-model="form.networkType">
              <el-radio-button value="无法访问网络">无法访问网络</el-radio-button>
              <el-radio-button value="无法访问网站">无法访问网站</el-radio-button>
              <el-radio-button value="网站显示异常">网站显示异常</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <!-- 第三十五批审计补齐：扫码页软件安装申请与管理台对齐（数据源用公开软件目录，匿名/登录均可读） -->
          <el-form-item v-if="form.category === '软件安装' && softwareCatalog.length" label="申请软件">
            <el-select v-model="form.software_id" clearable filterable style="width: 100%" placeholder="输入名称检索要安装的软件">
              <el-option
                v-for="s in softwareCatalog" :key="s.id"
                :label="`${s.name}（${s.category || '未分类'} · ${s.license_type}）`"
                :value="s.id"
              >
                <span>{{ s.name }}<span class="muted" style="margin-left: 8px">{{ s.category || '未分类' }}</span></span>
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
          </el-form-item>
          <el-form-item label="详细描述">
            <el-input v-model="form.description" type="textarea" :rows="3" placeholder="什么现象、从什么时候开始、影响范围…" />
          </el-form-item>
          <el-form-item v-for="f in visibleTemplateFields" :key="f.key" :label="f.label" :required="f.required">
            <el-input v-if="f.type === 'text'" v-model="form.custom_fields[f.key]" />
            <el-input v-else-if="f.type === 'textarea'" v-model="form.custom_fields[f.key]" type="textarea" :rows="2" />
            <el-select v-else-if="f.type === 'select'" v-model="form.custom_fields[f.key]" style="width: 100%">
              <el-option v-for="o in f.options" :key="o" :label="o" :value="o" />
            </el-select>
          </el-form-item>
          <el-form-item label="优先级">
            <div class="priority-row">
              <el-radio-group v-model="form.priority">
                <el-radio-button v-for="(label, key) in PRIORITY" :key="key" :value="key">{{ label }}</el-radio-button>
              </el-radio-group>
              <el-button type="primary" :loading="submitting" @click="submit">提交工单</el-button>
            </div>
          </el-form-item>
        </el-form>
      </el-card>

      <!-- 匿名登录引导（位置/指定派单码可匿名提交，引导移至底部，样式与会议室码一致） -->
      <el-card v-if="!authed && info.kind !== 'device'" shadow="never">
        <el-result icon="info" title="登录后可跟踪进度" sub-title="匿名提交 IT 可正常受理；登录后可跟踪进度、留言与加急">
          <template #extra>
            <el-button type="primary" @click="goLogin">员工登录</el-button>
          </template>
        </el-result>
      </el-card>

      <!-- 提交结果：分给了谁 + 排队情况 -->
      <el-dialog v-model="resultVisible" title="已提交" width="480px">
        <el-alert
          v-if="result?.followCode" type="success" :closable="false" show-icon style="margin-bottom: 12px"
          :title="'查询码：' + result.followCode"
          description="请截图保存。凭 工单编号 + 此查询码 可在本页查询处理进度。"
        /><el-result v-if="result" icon="success" :title="result.deferred ? '已提交，将进入接单广场等待认领' : `已分配给 ${result.assignedTo}`">
          <template #sub-title>
            <p>{{ result.no }} · {{ result.title }}</p>
            <p v-if="result.queueAhead > 0" class="muted">该工程师名下还有 {{ result.queueAhead }} 单在您之前，会依次处理</p>
            <p v-else class="muted">您是当前第一单，工程师将尽快处理</p>
          </template>
          <template #extra>
            <el-button v-if="authed" type="primary" @click="goDetail(result.id)">查看进度</el-button>
            <el-button @click="resultVisible = false">{{ authed ? '继续使用' : '完成' }}</el-button>
          </template>
        </el-result>
      </el-dialog>
      </template>

      <!-- 第四十一批 F2：匿名跟进查询卡恢复（凭 工单编号+查询码 查进度，各码型通用） -->
      <el-card shadow="never" style="margin-top: 14px">
        <template #header><span>进度查询</span></template>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-input v-model="trackForm.no" placeholder="工单编号（如 B-20261120-0001）" style="flex: 1; min-width: 200px" @keyup.enter="trackTicket" />
          <el-input v-model="trackForm.code" placeholder="6 位查询码" maxlength="6" style="width: 150px" @keyup.enter="trackTicket" />
          <el-button type="primary" @click="trackTicket">查询</el-button>
        </div>
        <div v-if="trackQueried && trackResult" style="margin-top: 12px">
          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px">
            <b>{{ trackResult.no }}</b>
            <el-tag size="small" :type="trackResult.status === 'closed' || trackResult.status === 'resolved' ? 'success' : 'primary'">{{ trackResult.status_label }}</el-tag>
          </div>
          <el-timeline style="padding-left: 4px">
            <el-timeline-item v-for="(ev, i) in trackResult.events" :key="i" :timestamp="new Date(ev.created_at).toLocaleString('zh-CN', { hour12: false })">
              <b style="margin-right: 6px">{{ ev.actor }}</b>{{ ev.content }}
            </el-timeline-item>
          </el-timeline>
        </div>
      </el-card>
    </template>
    <div v-else class="loading"><el-skeleton :rows="6" animated /></div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, del } from '@/api/http'

const route = useRoute()
const router = useRouter()

const kindTag: Record<string, string> = { location: 'primary', device: 'warning', assignee: 'danger' }
const statusTag: Record<string, string> = { pending: 'info', processing: 'primary', pending_confirm: 'warning', resolved: 'success', pending_approval: 'danger' }
const PRIORITY: Record<string, string> = { low: '低', medium: '中', high: '高', urgent: '紧急' }

const info = ref<any>(null)
const error = ref('')
const offline = ref(false)

function retry() {
  offline.value = false
  error.value = ''
  load()
}
const categories = ref<string[]>([])
const templateFields = ref<any[]>([])
const submitting = ref(false)
const resultVisible = ref(false)
const result = ref<any>(null)
const form = reactive<any>({ title: '', description: '', category: '其他问题', priority: 'medium', custom_fields: {}, accountType: '', deviceType: '', printType: '', networkType: '', software_id: null, software_outside: '' })
const softwareCatalog = ref<any[]>([])
const escalatingId = ref<number | null>(null)
// 第二十八批+：建单知识库推荐（匿名可见 FAQ）
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

watch(() => [form.title, form.description], () => { fetchKbHits() })
// v2.12 匿名跟进查询
const trackForm = reactive({ no: '', code: '' })
const trackResult = ref<any>(null)
const trackQueried = ref(false)

async function trackTicket() {
  if (!trackForm.no.trim() || !trackForm.code.trim()) return ElMessage.warning('请填写工单编号与查询码')
  try {
    trackResult.value = await get('/api/tickets/track?no=' + encodeURIComponent(trackForm.no) + '&code=' + encodeURIComponent(trackForm.code))
    trackQueried.value = true
  } catch (e: any) {
    trackResult.value = null
    trackQueried.value = true
    ElMessage.error(e.message)
  }
}

// v2.11 匿名扫码：authed = 已登录；未登录的浏览器/微信访客按匿名提交（IM 容器内仍尝试免登）
const authed = computed(() => !!info.value?.authenticated)
const is_admin = computed(() => !!info.value?.is_admin)
const ticketListTitle = computed(() => {
  if (!info.value) return ''
  if (authed.value && info.value.kind !== 'device') return '我在此码提交的未结工单'
  return '此码的未结工单'
})
const showCreator = computed(() => info.value?.kind === 'device' || !authed.value)

// ---- v2.12 会议室预约与检查 ----
const me = ref<any>(null)
const bkForm = reactive<any>({ date: new Date().toISOString().slice(0, 10), start: '', end: '', title: '', weeks: 1 })
const booking = ref(false)
const checkForm = reactive<any>({ results: {}, note: '' })
const checking = ref(false)

async function submitBooking() {
  if (!bkForm.date) return ElMessage.warning('请选择日期')
  if (!bkForm.start || !bkForm.end) return ElMessage.warning('请选择起止时段')
  booking.value = true
  try {
    if ((bkForm.weeks || 1) > 1) {
      // v2.12 周期性预约：每周同时段连建 N 场，冲突场次自动跳过
      const res = await post('/api/meetings/bookings/recurring', {
        room_id: info.value.room.id,
        start_date: bkForm.date,
        weeks: bkForm.weeks,
        start_time: bkForm.start,
        end_time: bkForm.end,
        title: bkForm.title,
      })
      ElMessage.success(res.message || `已创建 ${res.created.length} 场预约`)
    } else {
      await post('/api/meetings/bookings', {
        room_id: info.value.room.id,
        date: bkForm.date,
        start_time: bkForm.start,
        end_time: bkForm.end,
        title: bkForm.title,
      })
      ElMessage.success(`预约成功：${bkForm.date} ${bkForm.start}-${bkForm.end}`)
    }
    bkForm.title = ''
    await load()
  } catch (e: any) {
    // v2.12 时段冲突（已约满）→ 列举其他可约会议室，一键切换预约
    if ((e.message || '').includes('冲突')) {
      await suggestAlternatives(e.message)
    } else {
      ElMessage.error(e.message)
    }
  } finally {
    booking.value = false
  }
}

/** 冲突推荐：查询同时段其他空闲会议室，弹窗一键预约 */
async function suggestAlternatives(conflictMsg: string) {
  let rooms: any[] = []
  try {
    const params = new URLSearchParams({ date: bkForm.date, start_time: bkForm.start, end_time: bkForm.end })
    const res = await get(`/api/meetings/available?${params}`)
    rooms = res.items || []
  } catch { /* 查询失败时仅提示冲突 */ }
  if (!rooms.length) {
    ElMessage.warning(`${conflictMsg}；该时段暂无其他可约会议室`)
    return
  }
  const roomList = rooms.map((r: any, i: number) => `${i + 1}. ${r.name}（${r.location || '位置未填'} · 容纳 ${r.capacity} 人）`).join('\n')
  try {
    await ElMessageBox.confirm(
      `${conflictMsg}\n\n同时段（${bkForm.date} ${bkForm.start}-${bkForm.end}）可预约的会议室：\n${roomList}\n\n是否将本次预约改约到第一个可约会议室？`,
      '该时段已约满 · 推荐其他会议室',
      {
        confirmButtonText: rooms.length === 1 ? `改约到「${rooms[0].name}」` : `改约到「${rooms[0].name}」`,
        cancelButtonText: '留在当前会议室',
        type: 'warning', distinguishCancelAndClose: true,
      },
    )
  } catch { return }
  // 改约到第一个空闲会议室
  try {
    await post('/api/meetings/bookings', {
      room_id: rooms[0].id,
      date: bkForm.date,
      start_time: bkForm.start,
      end_time: bkForm.end,
      title: bkForm.title,
    })
    ElMessage.success(`已改约到「${rooms[0].name}」：${bkForm.date} ${bkForm.start}-${bkForm.end}`)
    bkForm.title = ''
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function cancelBooking(b: any) {
  try {
    await ElMessageBox.confirm(`取消预约「${b.title || b.date + ' ' + b.start_time}」？`, '取消预约', { type: 'warning' })
  } catch { return }
  try {
    await del(`/api/meetings/bookings/${b.id}`)
    ElMessage.success('已取消预约')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

/** 预约阶段：upcoming 未开始 / ongoing 进行中 / ended 已结束 */
function bookingPhase(b: any): string {
  const s = new Date(`${b.date}T${b.start_time}:00`).getTime()
  const e = new Date(`${b.date}T${b.end_time}:00`).getTime()
  const now = Date.now()
  if (now < s) return 'upcoming'
  if (now < e) return 'ongoing'
  return 'ended'
}
const phaseTag: Record<string, string> = { upcoming: 'info', ongoing: 'primary', ended: 'success' }
const phaseLabel: Record<string, string> = { upcoming: '未开始', ongoing: '进行中', ended: '已结束' }

// 第二十三批+：到场签到（no-show 统计依据；开始后当天任意时刻可签）
async function checkinBooking(b: any) {
  try {
    const res = await post(`/api/meetings/bookings/${b.id}/checkin`, {})
    b.checkin_at = res.checkin_at
    ElMessage.success(res.already ? '该预约已签到过' : '签到成功')
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function endBooking(b: any) {
  try {
    await ElMessageBox.confirm(`提前结束「${b.title || '会议'}」（结束时间改为现在，会议室立即释放）？`, '提前结束', { type: 'warning' })
  } catch { return }
  try {
    await post(`/api/meetings/bookings/${b.id}/end`)
    ElMessage.success('会议已提前结束，会议室已释放')
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function submitCheck() {
  checking.value = true
  try {
    await post(`/api/meetings/rooms/${info.value.room.id}/inspections`, {
      results: { ...checkForm.results },
      note: checkForm.note,
    })
    ElMessage.success('检查结果已保存（工作留痕）')
    checkForm.note = ''
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    checking.value = false
  }
}

function goLogin() {
  sessionStorage.setItem('itops_after_login', route.fullPath)
  router.push(`/login?redirect=${encodeURIComponent(route.fullPath)}`)
}

/** 一键加急：推送处理人；处理人排队 >2 单时同步提醒其他工程师（可转办） */
async function escalate(t: any) {
  escalatingId.value = t.id
  try {
    const d = await post(`/api/tickets/${t.id}/escalate`)
    if (d.broadcast) {
      ElMessage.success('已加急：已推送处理人，并提醒其他工程师可接手（30 分钟内勿重复加急）')
    } else {
      ElMessage.success('已加急：已推送消息提醒处理人尽快处理')
    }
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    escalatingId.value = null
  }
}

onMounted(async () => {
  // v2.11 匿名扫码：浏览器/微信未登录 → 匿名提交，不再强制跳登录页；
  // IM 容器（钉钉/飞书/企微）内仍自动免登获取员工身份
  if (!localStorage.getItem('itops_token')) {
    const ua = navigator.userAgent
    const inIm = /DingTalk|Lark|Feishu|wxwork/i.test(ua)
    if (inIm) {
      sessionStorage.setItem('itops_after_login', route.fullPath)
      ElMessage.info('正在通过 IM 免登获取员工信息…')
      setTimeout(() => (location.href = '/login'), 600)
      return
    }
  }
  await load()
})

async function load() {
  try {
    info.value = await get(`/api/qr/${route.params.code}`)
    if (info.value.kind === 'room') {
      // v2.12 会议室码：登录用户拉取个人信息（取消自己的预约用）；初始化检查表单
      if (info.value.authenticated) {
        get('/api/auth/me').then((u: any) => (me.value = u)).catch(() => {})
      }
      if (!Object.keys(checkForm.results).length) {
        for (const c of info.value.check_items || []) checkForm.results[c[0]] = 'ok'
      }
      bkForm.date = new Date().toISOString().slice(0, 10)
      // 重要设备维修中：扫码弹出公告提醒
      if (info.value.room?.under_maintenance) {
        ElMessageBox.alert(info.value.room.maintenance_notice || '该会议室重要设备维修中，暂停使用', '会议室公告', {
          confirmButtonText: '我知道了', type: 'warning',
        }).catch(() => {})
      }
      return
    }
    if (info.value.default_category) form.category = info.value.default_category
    // v2.11 分类直接来自扫码页数据接口（匿名也能拿到），不再依赖 admin 接口
    if (info.value.categories?.length) categories.value = info.value.categories
    await onCategoryChange(form.category)
  } catch (e: any) {
    // v2.12 离线兜底：网络不可达时给出明确指引（区别于二维码无效）
    if (e.status === 0 || (e.message || '').indexOf('网络') !== -1) {
      error.value = '网络连接失败：请确认已连接公司内网 Wi-Fi 后点击重试；二维码仍有效，无需重新张贴'
      offline.value = true
    } else {
      error.value = e.message || '二维码无效'
    }
  }
}

async function onCategoryChange(category: string) {
  form.custom_fields = {}
  templateFields.value = []
  if (!category) return
  if (category === '软件安装' && !softwareCatalog.value.length) {
    try {
      // 公开软件目录接口：匿名/登录均可用，仅返回已启用项
      softwareCatalog.value = (await get('/api/public/softwares')).items
    } catch { /* 目录加载失败不阻塞建单 */ }
  }
  try {
    const res = await get(`/api/tickets/templates/by-category?category=${encodeURIComponent(category)}`)
    if (res.items.length) {
      templateFields.value = res.items[0].fields
      if (res.items[0].priority) form.priority = res.items[0].priority
    }
  } catch { /* 模板加载失败不阻塞建单 */ }
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

async function submit() {
  if (!form.title.trim()) return ElMessage.warning('请填写问题概述')
  if (form.category === '软件安装' && form.software_id === -1 && !String(form.software_outside || '').trim()) {
    return ElMessage.warning('请填写列表外软件的名称')
  }
  submitting.value = true
  try {
    // 第二十九批+：账号权限/硬件设备 的类型选项写入自定义字段
    const cf = cleanCustomFields()
    if (form.category === '账号权限' && form.accountType) cf['申请类型'] = form.accountType
    if (form.category === '硬件设备' && form.deviceType) cf['设备类型'] = form.deviceType
    if (form.category === '打印设备' && form.printType) cf['故障类型'] = form.printType
    if (form.category === '网络故障' && form.networkType) cf['故障类型'] = form.networkType
    // 列表外软件：不传 software_id，写入 custom_fields 标记（与建单弹窗一致）
    if (form.category === '软件安装' && form.software_id === -1) cf['软件'] = { name: String(form.software_outside || '').trim(), outside: true }
    const t = await post('/api/tickets', {
      title: form.title.trim(),
      description: form.description,
      category: form.category,
      priority: form.priority,
      custom_fields: cf,
      qr_code: route.params.code,
      // 目录内软件传 id 形成申请关联
      ...(form.category === '软件安装' && form.software_id && form.software_id !== -1 ? { software_id: form.software_id } : {}),
    })
    await load() // 刷新后从列表读新单的真实排队位次
    const mine = (info.value?.open_tickets || []).find((o: any) => o.id === t.id)
    result.value = {
      id: t.id, no: t.no, title: t.title,
      assignedTo: t.auto_assigned || '尚未指派，将尽快分派',
      deferred: !!t.deferred,
      queueAhead: mine?.queue_ahead ?? 0,
      followCode: t.follow_code || '',
    }
    resultVisible.value = true
    form.title = ''
    form.software_id = null
    form.software_outside = ''
    form.accountType = ''
    form.deviceType = ''
    form.printType = ''
    form.networkType = ''
    // v2.10 合并提醒：15 分钟内多次扫码提交 → 提示合并到原工单（在原单上追加修改）或保留新建
    if (t.recent_ticket) {
      try {
        await ElMessageBox.confirm(
          `您在 15 分钟内已提交过工单 ${t.recent_ticket.no}（${t.recent_ticket.title}）。是否将本单合并到该工单？合并后本单内容将追加到原单统一处理。`,
          '发现疑似重复提交',
          { confirmButtonText: '合并到原工单', cancelButtonText: '保留为新工单', type: 'warning', distinguishCancelAndClose: true },
        )
        await post(`/api/tickets/${t.id}/merge`, { target_id: t.recent_ticket.id })
        ElMessage.success(`已合并到原工单 ${t.recent_ticket.no}，处理人将统一处理`)
        await load()
      } catch (e: any) {
        if (e !== 'cancel' && e?.message) ElMessage.error(e.message)
        // cancel/close = 保留新建工单
      }
    }
    form.description = ''
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

function goDetail(id: number) {
  router.push(`/tickets/${id}`)
}
</script>

<style scoped>
.qr-page { max-width: 760px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
.room-alert { --el-alert-bg-color: #ecf5ff; }
.priority-row { display: flex; align-items: center; justify-content: space-between; width: 100%; }
.head-card :deep(.el-card__body) { padding: 18px 20px; }

.head { display: flex; gap: 14px; align-items: flex-start; }
.head-main { flex: 1; }
.head-title { font-size: 17px; font-weight: 600; margin-bottom: 6px; }
.head-sub { display: flex; align-items: center; gap: 6px; color: #5a6478; font-size: 13px; margin-top: 2px; flex-wrap: wrap; }
.head-sub.assign { color: #e6a23c; }
.dot { color: #c0c4cc; }
.ticket-list { display: flex; flex-direction: column; gap: 8px; }
.ticket-row {
  display: flex; justify-content: space-between; align-items: center; gap: 10px;
  padding: 10px 14px; border: 1px solid #e6e8ee; border-radius: 8px;
}
.ticket-row.clickable { cursor: pointer; }
.ticket-row:hover { border-color: #2f6fed; }
.ticket-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.no { color: #8a93a6; font-size: 12px; white-space: nowrap; }
.title { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ticket-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; flex-wrap: wrap; justify-content: flex-end; }
.assignee { font-size: 12px; color: #5a6478; }
.hint { color: #8a93a6; font-size: 12px; }
.muted { color: #8a93a6; }
.loading { padding: 40px; }
/* v2.12 会议室 */
.pre-wrap { white-space: pre-wrap; line-height: 1.8; color: #303133; font-size: 14px; }
.equip-desc { background: #f7f9fc; border-radius: 8px; padding: 12px 14px; }
/* 第三十九批：会议室设备列表 */
.equip-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px 14px; }
.equip-item { display: flex; align-items: center; justify-content: space-between; gap: 6px; font-size: 13px; padding: 4px 8px; background: #f7f9fc; border-radius: 6px; }
.equip-name { color: #303133; }
.booking-list { display: flex; flex-direction: column; gap: 8px; }
.booking-row {
  display: flex; align-items: center; gap: 12px; padding: 9px 12px;
  border: 1px solid #e6e8ee; border-radius: 8px; font-size: 13px; flex-wrap: wrap;
}
.bk-date { color: #5a6478; font-weight: 600; }
.bk-time { color: #2f6fed; font-weight: 600; }
.bk-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bk-booker { color: #8a93a6; font-size: 12px; }
.check-list { display: flex; flex-direction: column; gap: 8px; }
.check-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.check-label { font-size: 14px; color: #303133; }
@media (max-width: 768px) {
  .qr-page { padding: 0 4px; }
  .ticket-row { flex-direction: column; align-items: flex-start; gap: 4px; }
  .ticket-right { width: 100%; justify-content: flex-start; flex-wrap: wrap; }
  .assignee { margin-left: 0; }
}
</style>

/* 建单知识库推荐（第二十八批+） */
.kb-recommend { width: 100%; display: flex; flex-direction: column; gap: 6px; }
.kb-hit { background: #f0f9eb; border: 1px solid #e1f3d8; border-radius: 6px; padding: 8px 10px; cursor: pointer; font-size: 13px; }
.kb-hit-title { font-weight: 600; color: #303133; margin-right: 8px; }
.kb-hit-arrow { color: #2f6fed; font-size: 12px; }
.kb-hit-body { margin-top: 6px; color: #5a6478; line-height: 1.7; }
.kb-sec { margin-bottom: 4px; }
