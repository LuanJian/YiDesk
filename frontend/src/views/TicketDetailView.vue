<template>

  <div v-if="ticket">

    <el-page-header @back="$router.back()" class="page-header">

      <template #content>

        <div class="detail-title">

          <span class="no">{{ ticket.no }}</span>

          <span class="title">{{ ticket.title }}</span>

          <el-tag :type="statusType(ticket.status)" size="small">{{ ticket.status_label }}</el-tag>

          <el-tag :type="priorityType(ticket.priority)" size="small">{{ ticket.priority_label }}</el-tag>

          <el-tag v-if="ticket.sla_suspended" type="info" size="small" effect="dark">

            SLA 已挂起{{ ticket.sla_remaining_minutes != null ? `（剩余 ${ticket.sla_remaining_minutes} 分钟）` : '' }}

          </el-tag>

          <el-button

            v-if="auth.isStaff"

            size="small"

            :type="isFollowing ? 'warning' : 'default'"

            plain

            @click="toggleFollow"

          >{{ isFollowing ? '取消关注' : '关注' }}</el-button>

        </div>

      </template>

    </el-page-header>

    <el-row :gutter="14">

      <!-- 左侧：信息 + 时间线 -->

      <el-col :span="16">

        <el-card shadow="never" class="block">

          <el-descriptions :column="isMobile ? 1 : 3" border size="small" :label-width="isMobile ? 78 : 96">

            <el-descriptions-item label="发起人">{{ ticket.creator?.name || '-' }}</el-descriptions-item>

            <el-descriptions-item v-if="ticket.requester && ticket.requester.id !== ticket.creator?.id" label="提出者">

              {{ ticket.requester.name }}（由 {{ ticket.creator?.name }} 代报）

            </el-descriptions-item>

            <el-descriptions-item v-if="ticket.followers?.length" label="关注人">

              {{ ticket.followers.map((f: any) => f.name).join('、') }}

            </el-descriptions-item>

            <el-descriptions-item label="处理人">{{ ticket.assignee?.name || '未指派' }}</el-descriptions-item>

            <el-descriptions-item label="来源">{{ channelLabel(ticket.channel) }}</el-descriptions-item>

            <el-descriptions-item label="问题分类">{{ ticket.category }}</el-descriptions-item>

            <el-descriptions-item label="创建时间"><span class="nowrap">{{ fmtTime(ticket.created_at) }}</span></el-descriptions-item>

            <!-- v2.12 响应/解决时限拆分独立单元格，并展示实际响应/解决时间 -->

            <el-descriptions-item label="响应时限">

              <span class="nowrap" :class="{ breach: overdue(ticket.sla_response_deadline) && !ticket.first_responded_at }">{{ fmtTime(ticket.sla_response_deadline) }}</span>

            </el-descriptions-item>

            <el-descriptions-item label="解决时限">

              <span class="nowrap" :class="{ breach: ticket.resolve_breached }">{{ fmtTime(ticket.sla_resolve_deadline) }}</span>

            </el-descriptions-item>

            <el-descriptions-item label="实际响应">

              <span v-if="ticket.first_responded_at" class="nowrap">{{ fmtTime(ticket.first_responded_at) }}</span>

              <span v-else class="muted">未响应</span>

            </el-descriptions-item>

            <el-descriptions-item label="实际解决">

              <span v-if="ticket.resolved_at" class="nowrap" style="color: #67c23a">{{ fmtTime(ticket.resolved_at) }}</span>

              <span v-else class="muted">未解决</span>

            </el-descriptions-item>

            <el-descriptions-item v-if="ticket.custom_fields?.location" label="扫码位置">{{ ticket.custom_fields.location }}</el-descriptions-item>

            <!-- v2.11 设备码信息拆分独立单元格：设备 / 位置 / IP 分行展示 -->

            <el-descriptions-item v-if="ticket.custom_fields?.device" label="扫码设备">{{ deviceText(ticket.custom_fields.device) }}</el-descriptions-item>

            <el-descriptions-item v-if="ticket.custom_fields?.device?.location" label="设备位置">{{ ticket.custom_fields.device.location }}</el-descriptions-item>

            <el-descriptions-item v-if="ticket.custom_fields?.device?.ip" label="设备 IP">{{ ticket.custom_fields.device.ip }}</el-descriptions-item>

            <!-- v2.12 软件安装申请：快照展示软件名/授权类型/来源（闭环：申请→工单→安装） -->

            <el-descriptions-item v-if="ticket.custom_fields?.software_list?.length" label="申请安装软件">

              <div v-for="(sw, i) in ticket.custom_fields.software_list" :key="i">

                {{ i + 1 }}. {{ sw.name }}{{ sw.outside ? '（列表外软件，需 IT 评估）' : sw.license_type ? `（${sw.license_type}）` : '' }}

              </div>

            </el-descriptions-item>

            <el-descriptions-item v-else-if="ticket.custom_fields?.software" label="申请安装软件">

              <template v-if="ticket.custom_fields.software.outside">

                {{ ticket.custom_fields.software.name }}（列表外软件，需 IT 评估）

              </template>

              <template v-else>

                {{ ticket.custom_fields.software.name }}（{{ ticket.custom_fields.software.license_type }}{{ ticket.custom_fields.software.source ? ' · ' + ticket.custom_fields.software.source : '' }}）

              </template>

            </el-descriptions-item>

            <el-descriptions-item

              v-for="(val, key) in displayCustomFields"

              :key="key"

              :label="fieldLabel(key)"

            >{{ val }}</el-descriptions-item>

          </el-descriptions>

          <!-- 问题描述 / 解决方案（与上方信息表同列宽，视觉对齐） -->

          <el-descriptions :column="1" border size="small" class="desc-table" label-width="96px">

            <el-descriptions-item label="详细描述">

              <span class="pre-wrap">{{ ticket.description || '（无）' }}</span>

            </el-descriptions-item>

            <el-descriptions-item v-if="ticket.solution" label="解决方案">

              <span class="pre-wrap">{{ ticket.solution }}</span>

            </el-descriptions-item>

          </el-descriptions>

          <!-- 附件（v2.9 移入上方框架，问题描述之后） -->

          <el-card shadow="never" class="inner-card">

          <template #header>

            <div class="attach-head">

              <b>附件（{{ ticket.attachments?.length || 0 }}）</b>

              <el-upload

                :show-file-list="false"

                :http-request="doUpload"

                :disabled="uploading"

                style="display: inline-block"

              >

                <el-button size="small" type="primary" plain :loading="uploading">

                  <el-icon><Upload /></el-icon>&nbsp;上传附件

                </el-button>

              </el-upload>

            </div>

          </template>

          <div v-if="ticket.attachments?.length" class="attach-list">

            <div v-for="att in ticket.attachments" :key="att.id" class="attach-item">

              <!-- 缩略图/大图用带认证的 blob URL（原直连 API URL 无 token 会 401 裂图） -->

              <el-image

                v-if="att.is_image"

                :src="attBlobs[att.id] || ''"

                :preview-src-list="attBlobs[att.id] ? [attBlobs[att.id]] : []"

                preview-teleported

                fit="cover"

                class="attach-thumb"

              />

              <el-icon v-else :size="26" class="attach-file-icon"><Document /></el-icon>

              <div class="attach-info">

                <el-link :underline="false" @click="downloadFile(att)">{{ att.filename }}</el-link>

                <div class="muted">

                  {{ (att.size / 1024).toFixed(0) }}KB · {{ att.source }}

                  <!-- PDF 在线预览（浏览器原生查看器） -->

                  <el-link

                    v-if="isPdf(att)"

                    type="primary"

                    :underline="false"

                    style="margin-left: 8px"

                    @click="previewAtt(att)"

                  >在线预览</el-link>

                </div>

              </div>

            </div>

          </div>

          <div v-else class="muted">暂无附件。截图、照片、文档均可上传（≤10MB）。</div>

          </el-card>

        </el-card>

        <!-- 评论沟通移至左侧处理记录上方；服务评价移回右侧工单操作下方 -->

        <el-card shadow="never" class="block">

          <template #header><b>评论沟通</b></template>

          <div class="comment-list">

            <div v-for="ev in commentEvents" :key="ev.id" class="comment-item">

              <b class="actor">{{ ev.actor?.name || '系统' }}</b>

              <span class="muted">{{ fmtTime(ev.created_at) }}</span>

              <el-tag v-if="ev.edited" size="small" type="info" effect="plain">已修改</el-tag>

              <el-button

                v-if="canEditComment(ev)" size="small" text type="primary"

                style="margin-left: auto" @click="openEditComment(ev)"

              >编辑</el-button>

              <div class="content pre-wrap">{{ ev.content }}</div>

            </div>

            <div v-if="!commentEvents.length" class="muted">暂无评论，可在下方补充说明</div>

          </div>

          <div class="comment-input">

            <el-input v-model="commentText" type="textarea" :rows="3" placeholder="补充说明、进展同步…" />

            <el-button type="primary" size="small" style="margin-top: 10px" :loading="commenting" @click="submitComment">发送</el-button>

          </div>

        </el-card>

        <!-- 时间线 -->

        <el-card shadow="never" class="block">

          <template #header><b>处理记录</b></template>

          <el-timeline>

            <el-timeline-item

              v-for="ev in [...ticket.events].reverse()"

              :key="ev.id"

              :timestamp="fmtTime(ev.created_at)"

              :type="ev.type === 'transition' ? 'primary' : ev.type === 'comment' ? 'success' : ''"

            >

              <div class="event">

                <b class="actor">{{ ev.actor?.name || '系统' }}</b>

                <span v-if="ev.type === 'comment'" class="content pre-wrap">{{ ev.content }}</span>

                <span v-else class="content">{{ ev.content }}</span>

              </div>

            </el-timeline-item>

          </el-timeline>

        </el-card>

      </el-col>

      <!-- 右侧：工单操作 / 评论沟通 / 评价 / 相似 / 知识 -->

      <el-col :span="8">

        <!-- v2.12 操作区移至右列顶部（评论沟通上方），全宽按钮便于触达 -->

        <el-card shadow="never" class="block op-card">

          <template #header><b>工单操作</b></template>

          <!-- 合并源单：操作收敛到主工单，仅提示不渲染按钮 -->

          <div v-if="ticket.merged_into_id" class="muted" style="font-size: 13px">

            该工单已并入主工单，转出与完结请在主工单上操作（将同步全部关联工单）

          </div>

          <div v-else class="actions actions-grid">

            <!-- grid 一行 3 个等宽；核心顺序 完结→指派→搜索合并→加急→编辑→挂起 SLA -->

            <el-button v-if="ticket.available_actions?.includes('finish')" type="success" @click="openConfirm('finish')">完结工单</el-button>

            <el-button v-if="ticket.available_actions?.includes('confirm_resolved')" type="success" @click="openConfirm('confirm_resolved')">确认已解决</el-button>

            <el-button v-if="ticket.available_actions?.includes('accept')" type="primary" @click="doTransition('accept', '')">接单受理</el-button>

            <el-button v-if="canAssign" plain @click="openAssign">指派 / 改派</el-button>

            <el-button v-if="auth.isStaff && isOpen" plain @click="openMergeSearch">搜索合并</el-button>

            <el-button v-if="canUrge && !ticket.sla_suspended" type="danger" plain @click="escalate">加急</el-button>

            <el-button v-if="canEdit" plain @click="openEdit">编辑</el-button>

            <el-button v-if="auth.isStaff && isOpen" plain @click="ticket.sla_suspended ? slaResume() : slaSuspend()">

              {{ ticket.sla_suspended ? '恢复 SLA' : '挂起 SLA' }}

            </el-button>

            <el-button v-if="ticket.available_actions?.includes('approve')" type="success" @click="doApprove">审批通过</el-button>

            <el-button v-if="ticket.available_actions?.includes('reject')" type="danger" plain @click="doReject">驳回</el-button>

            <el-button v-if="ticket.available_actions?.includes('claim')" type="warning" @click="claimTicket">转给我处理</el-button>

            <el-button v-if="ticket.available_actions?.includes('reject_solution')" plain @click="doTransition('reject_solution', '')">退回解决方案</el-button>

            <el-button v-if="ticket.available_actions?.includes('cancel')" plain @click="doTransition('cancel', '')">撤销工单</el-button>

            <el-button v-if="ticket.available_actions?.includes('close')" plain @click="doTransition('close', '')">关闭工单</el-button>

            <el-button v-if="ticket.available_actions?.includes('reopen')" plain @click="doTransition('reopen', '')">重开工单</el-button>

            <div v-if="ticket.followers?.length" class="follower-hint">关注：{{ ticket.followers.map((f: any) => f.name).join('、') }}</div>

          </div>

        </el-card>

        <!-- 服务评价放回右侧工单操作下方 -->

        <el-card shadow="never" class="block">

          <template #header><b>服务评价</b></template>

          <template v-if="ticket.rating">

            <el-rate :model-value="ticket.rating.stars" disabled />

            <div class="muted" v-if="ticket.rating.comment">{{ ticket.rating.comment }}</div>

          </template>

          <template v-else-if="canRate && !ticket.merged_into_id">

            <el-rate v-model="ratingForm.stars" />

            <el-input v-model="ratingForm.comment" type="textarea" :rows="2" placeholder="评价（可选）" style="margin-top: 10px" />

            <el-button type="primary" size="small" style="margin-top: 10px" @click="submitRating">提交评价</el-button>

          </template>

          <div v-else-if="ticket.merged_into_id" class="muted">该工单已并入主工单，请在主工单中评价一次即可</div>

          <div v-else class="muted">工单解决后可评价</div>

        </el-card>

        <el-card shadow="never" class="block" v-if="similarTickets.length">

          <template #header><b>疑似重复工单</b></template>

          <div v-for="s in similarTickets" :key="s.id" class="side-row">

            <el-link type="primary" :underline="false" @click="$router.push(`/tickets/${s.id}`)">{{ s.no }}</el-link>

            <span class="muted">{{ s.title }}（相似度 {{ Math.round(s.similarity * 100) }}%）</span>

            <el-button v-if="auth.isStaff && ticket.is_open !== false" size="small" type="warning" plain @click="mergeInto(s)">并入此单</el-button>

          </div>

        </el-card>

        <el-card shadow="never" class="block" v-if="knowledgeSugs.length">

          <template #header><b>相关知识</b></template>

          <div v-for="k in knowledgeSugs" :key="k.id" class="side-row">

            <el-link type="primary" :underline="false" @click="$router.push('/knowledge')">{{ k.title }}</el-link>

            <el-tag size="small" effect="plain">{{ k.category }}</el-tag>

          </div>

        </el-card>

        <el-card shadow="never" class="block" v-if="canSink">

          <el-button type="primary" plain style="width: 100%" @click="openSink">

            <el-icon><Document /></el-icon>&nbsp;沉淀为知识库文章

          </el-button>

        </el-card>

      </el-col>

    </el-row>

    <!-- 沉淀知识库弹窗 -->

    <el-dialog v-model="sinkVisible" title="沉淀为知识库文章" width="640px">

      <el-form label-width="60px">

        <el-form-item label="标题"><el-input v-model="sinkForm.title" /></el-form-item>

        <el-form-item label="分类">

          <el-select v-model="sinkForm.category" style="width: 220px" allow-create filterable>

            <el-option v-for="c in ['常见问题', '网络', '账号', '办公软件', '硬件', '安全']" :key="c" :label="c" :value="c" />

          </el-select>

        </el-form-item>

        <el-form-item label="正文">

          <el-input v-model="sinkForm.content" type="textarea" :rows="10" />

        </el-form-item>

      </el-form>

      <template #footer>

        <el-button @click="sinkVisible = false">取消</el-button>

        <el-button type="primary" @click="sinkKnowledge">保存</el-button>

      </template>

    </el-dialog>

    <!-- v2.12 完结弹窗（finish=工程师完结 / confirm_resolved=提交人确认），按耗时决定必填 -->

    <el-dialog v-model="confirmVisible" :title="confirmAction === 'finish' ? '完结工单' : '确认已解决'" width="560px">

      <el-alert

        :type="confirmNeedSolution ? 'warning' : 'info'" :closable="false" show-icon style="margin-bottom: 12px"

        :title="`本工单已历时 ${confirmElapsed} 分钟`"

        :description="confirmNeedSolution

          ? '耗时超过 1 小时：解决方案（内部归档）与反馈处理结果均为必填'

          : confirmNeedFeedback ? '耗时超过 30 分钟：请填写反馈处理结果（展示给提交人）；解决方案选填'

          : '耗时 30 分钟以内：两项均可选填，便于归档与反馈'"

      />

      <el-form label-width="110px">

        <el-form-item label="解决方案">

          <el-input

            v-model="confirmForm.solution" type="textarea" :rows="4"

            :placeholder="confirmNeedSolution && !ticket?.solution ? '必填：处理过程与结果（仅内部归档查看，不展示给提交人）' : (ticket?.solution ? '将在已有方案基础上追加【补充】说明（不改写原内容）' : '内部归档查看（选填）')"

          />

        </el-form-item>

        <el-form-item label="反馈处理结果">

          <el-input

            v-model="confirmForm.feedback" type="textarea" :rows="4"

            :placeholder="confirmNeedFeedback ? '必填：将展示给工单提交人并随完结通知发送' : '将展示给工单提交人（选填）'"

          />

        </el-form-item>

      </el-form>

      <template #footer>

        <el-button @click="confirmVisible = false">取消</el-button>

        <el-button type="success" @click="submitConfirm">{{ confirmAction === 'finish' ? '确认完结' : '确认已解决' }}</el-button>

      </template>

    </el-dialog>

    <!-- PDF 在线预览（浏览器原生查看器） -->

    <el-dialog v-model="pdfVisible" :title="pdfTitle" width="820px" destroy-on-close top="6vh">

      <iframe v-if="pdfUrl" :src="pdfUrl" style="width: 100%; height: 65vh; border: 0" />

    </el-dialog>

    <!-- v2.12 评论编辑弹窗 -->

    <el-dialog v-model="editCommentVisible" title="编辑评论" width="520px">

      <el-input v-model="editCommentText" type="textarea" :rows="4" placeholder="评论内容" />

      <div class="muted" style="margin-top: 8px">保存后该评论将标注「已修改」。</div>

      <template #footer>

        <el-button @click="editCommentVisible = false">取消</el-button>

        <el-button type="primary" :loading="savingComment" @click="saveEditComment">保存</el-button>

      </template>

    </el-dialog>

    <!-- 指派弹窗 -->

    <el-dialog v-model="assignVisible" title="指派工程师" width="460px">

      <el-select v-model="assignEngineerId" filterable style="width: 100%" placeholder="选择工程师">

        <el-option v-for="e in engineers" :key="e.id" :label="e.name || e.username" :value="e.id" />

      </el-select>

      <el-input

        v-if="isReassign"

        v-model="assignReason"

        type="textarea"

        :rows="2"

        placeholder="改派原因（必填，如：该类目由张伟负责 / 原处理人今日请假）"

        style="margin-top: 10px"

      />

      <div v-if="isReassign" class="muted" style="margin-top: 4px">改派必须填写原因（审计留痕）</div>

      <template #footer>

        <el-button @click="assignVisible = false">取消</el-button>

        <el-button type="primary" @click="submitAssign">确定</el-button>

      </template>

    </el-dialog>

    <!-- 编辑工单（v2.0） -->

    <el-dialog v-model="editVisible" title="编辑工单" width="560px">

      <el-form label-width="80px">

        <el-form-item label="问题概述">

          <el-input v-model="editForm.title" maxlength="200" show-word-limit />

        </el-form-item>

        <el-form-item label="详细描述">

          <el-input v-model="editForm.description" type="textarea" :rows="4" />

        </el-form-item>

        <el-form-item label="优先级">

          <el-radio-group v-model="editForm.priority">

            <el-radio-button v-for="(label, key) in PRIORITY" :key="key" :value="key">{{ label }}</el-radio-button>

          </el-radio-group>

          <div v-if="ticket && editForm.priority !== ticket.priority" class="muted" style="font-size: 12px">

            优先级变化将按新优先级重算 SLA 时限

          </div>

        </el-form-item>

      </el-form>

      <template #footer>

        <el-button @click="editVisible = false">取消</el-button>

        <el-button type="primary" :loading="editing" @click="submitEdit">保存</el-button>

      </template>

    </el-dialog>

    <!-- 搜索合并（v2.0）：按关键词/工单号找目标单 -->

    <el-dialog v-model="mergeSearchVisible" title="搜索并合并工单" width="640px">

      <div class="merge-search">

        <el-input

          v-model="mergeQ"

          placeholder="输入关键词或工单号（如 B-20261120-0001 / 打印机）"

          clearable

          @keyup.enter="searchMerge"

        />

        <el-button type="primary" :loading="mergeSearching" @click="searchMerge">搜索</el-button>

      </div>

      <div v-if="mergeItems.length" class="merge-list">

        <div v-for="c in mergeItems" :key="c.id" class="side-row">

          <el-link type="primary" :underline="false" @click="$router.push(`/tickets/${c.id}`)">{{ c.no }}</el-link>

          <span class="muted">{{ c.title }}（{{ c.status_label }}）</span>

          <el-button size="small" type="warning" plain @click="mergeInto(c)">并入此单</el-button>

        </div>

      </div>

      <div v-else-if="mergeSearched" class="muted" style="padding: 12px 0">未找到匹配的未结工单</div>

      <div v-else class="muted" style="padding: 12px 0">找到目标工单后点「并入此单」：当前工单将关闭并指向目标单。</div>

    </el-dialog>

  </div>

</template>

<script setup lang="ts">

import { computed, onMounted, reactive, ref } from 'vue'

import { useRoute } from 'vue-router'

import { ElMessage, ElMessageBox } from 'element-plus'

import { download, fetchBlobUrl, get, patch, post, upload } from '@/api/http'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const route = useRoute()

// 窄屏判定（信息表单列/标签宽度收窄）

const isMobile = ref(window.innerWidth < 768)

const ticketId = route.params.id as string

const ticket = ref<any>(null)

const commentText = ref('')

const commenting = ref(false)

const commentEvents = computed(() => (ticket.value?.events || []).filter((e: any) => e.type === 'comment'))

// v2.12 完结工单弹窗：解决方案（内部归档）+ 反馈处理结果（展示给提交人）

const confirmVisible = ref(false)

const confirmForm = reactive({ solution: '', feedback: '' })

const assignVisible = ref(false)

const assignEngineerId = ref<number | null>(null)

const assignReason = ref('')

const isReassign = computed(() => !!ticket.value?.assignee && assignEngineerId.value !== null && ticket.value.assignee.id !== assignEngineerId.value)

const engineers = ref<any[]>([])

const ratingForm = reactive({ stars: 5, comment: '' })

const uploading = ref(false)

const similarTickets = ref<any[]>([])

const knowledgeSugs = ref<any[]>([])

const sinkVisible = ref(false)

const sinkForm = reactive<any>({ title: '', content: '', category: '常见问题' })

// v2.0：编辑 / 关注 / SLA 挂起 / 搜索合并

const PRIORITY: Record<string, string> = { low: '低', medium: '中', high: '高', urgent: '紧急' }

const editVisible = ref(false)

const editing = ref(false)

const editForm = reactive<any>({ title: '', description: '', priority: 'medium' })

const mergeSearchVisible = ref(false)

const mergeQ = ref('')

const mergeItems = ref<any[]>([])

const mergeSearched = ref(false)

const mergeSearching = ref(false)

const isOpen = computed(() => ticket.value && ['pending', 'processing', 'pending_confirm'].includes(ticket.value.status))

const isFollowing = computed(

  () => !!ticket.value?.followers?.some((f: any) => f.id === auth.user?.id),

)

const canEdit = computed(() => {

  if (!ticket.value) return false

  if (auth.isStaff) return isOpen.value

  return isOpen.value && ticket.value.status === 'pending' && ticket.value.creator?.id === auth.user?.id

})

function openEdit() {

  editForm.title = ticket.value.title

  editForm.description = ticket.value.description

  editForm.priority = ticket.value.priority

  editVisible.value = true

}

async function submitEdit() {

  if (!editForm.title.trim()) return ElMessage.warning('标题不能为空')

  editing.value = true

  try {

    ticket.value = await patch(`/api/tickets/${ticketId}`, {

      title: editForm.title.trim(),

      description: editForm.description,

      priority: editForm.priority,

    })

    editVisible.value = false

    ElMessage.success('已保存')

  } catch (e: any) {

    ElMessage.error(e.message)

  } finally {

    editing.value = false

  }

}

async function toggleFollow() {

  try {

    await post(`/api/tickets/${ticketId}/${isFollowing.value ? 'unfollow' : 'follow'}`)

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

async function slaSuspend() {

  try {

    const { value } = await ElMessageBox.prompt('挂起原因（可选，如：等厂商配件）', '挂起 SLA', {

      inputPlaceholder: '原因（可留空）', inputValue: '',

      confirmButtonText: '挂起', cancelButtonText: '取消',

    })

    ticket.value = await post(`/api/tickets/${ticketId}/sla-suspend`, { note: value || '' })

    ElMessage.success('SLA 已挂起，计时暂停')

  } catch (e: any) {

    if (e !== 'cancel' && e?.message) ElMessage.error(e.message)

  }

}

async function slaResume() {

  try {

    ticket.value = await post(`/api/tickets/${ticketId}/sla-resume`)

    ElMessage.success('SLA 已恢复计时')

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

function openMergeSearch() {

  mergeQ.value = ''

  mergeItems.value = []

  mergeSearched.value = false

  mergeSearchVisible.value = true

}

async function searchMerge() {

  mergeSearching.value = true

  try {

    const res = await get(`/api/tickets/${ticketId}/merge-candidates?q=${encodeURIComponent(mergeQ.value)}`)

    mergeItems.value = res.items

    mergeSearched.value = true

  } catch (e: any) {

    ElMessage.error(e.message)

  } finally {

    mergeSearching.value = false

  }

}

const canSink = computed(

  () =>

    auth.isStaff &&

    ticket.value &&

    ['resolved', 'closed'].includes(ticket.value.status) &&

    (ticket.value.solution || ticket.value.description)

)

const fieldLabels = ref<Record<string, string>>({})

function fieldLabel(key: string) {

  return fieldLabels.value[key] || CF_LABELS[key] || key

}

// 扫码带入的键单独成行展示，模板字段区过滤掉它们（software 同理）

// meeting_room_id（内部关联 ID）、follow_code（查询码在扫码页跟进卡展示）过滤；meeting_room 映射中文

const QR_INTERNAL_KEYS = new Set(['qr_code', 'location', 'device', 'software', 'software_list', 'meeting_room_id', 'follow_code'])

const CF_LABELS: Record<string, string> = { meeting_room: '会议室' }

const displayCustomFields = computed(() => {

  const cf: Record<string, any> = ticket.value?.custom_fields || {}

  const out: Record<string, any> = {}

  for (const [k, v] of Object.entries(cf)) if (!QR_INTERNAL_KEYS.has(k)) out[k] = v

  return out

})

function deviceText(d: any) {

  if (!d) return ''

  const parts = [d.name]

  if (d.model) parts.push(d.model)

  if (d.asset_tag) parts.push(d.asset_tag)

  return parts.join(' · ') // 位置/IP 已拆分独立单元格，不再挤在此行

}

const canUrge = computed(

  () =>

    ticket.value &&

    ['pending', 'processing', 'pending_confirm'].includes(ticket.value.status) &&

    auth.user &&

    (ticket.value.creator?.id === auth.user.id || auth.isAdmin)

)

const canAssign = computed(() => auth.isStaff && isOpen.value)

// ---- v2.12 完结工单弹窗（finish=工程师完结 / confirm_resolved=提交人确认）：耗时决定必填项 ----

const confirmAction = ref<'finish' | 'confirm_resolved'>('finish')

const confirmElapsed = computed(() => {

  if (!ticket.value?.created_at) return 0

  return Math.floor((Date.now() - new Date(ticket.value.created_at).getTime()) / 60000)

})

const confirmNeedSolution = computed(() => confirmElapsed.value > 60)

const confirmNeedFeedback = computed(() => confirmElapsed.value > 30)

function openConfirm(action: 'finish' | 'confirm_resolved') {

  confirmAction.value = action

  confirmForm.solution = ''

  confirmForm.feedback = ''

  confirmVisible.value = true

}

async function submitConfirm() {

  if (confirmNeedSolution.value && !confirmForm.solution.trim())

    return ElMessage.warning('完结耗时已超过 1 小时，请填写解决方案（内部归档）')

  if (confirmNeedFeedback.value && !confirmForm.feedback.trim())

    return ElMessage.warning(`完结耗时超过 ${confirmNeedSolution.value ? '1 小时' : '30 分钟'}，请填写反馈处理结果`)

  confirmVisible.value = false

  await doTransition(confirmAction.value, confirmForm.feedback, confirmForm.solution)

}

// ---- v2.12 评论编辑（作者/管理员），编辑后时间线标注「已修改」 ----

const editCommentVisible = ref(false)

const editCommentId = ref<number | null>(null)

const editCommentText = ref('')

const savingComment = ref(false)

function openEditComment(ev: any) {

  editCommentId.value = ev.id

  editCommentText.value = ev.content

  editCommentVisible.value = true

}

function canEditComment(ev: any) {

  return auth.isAdmin || (auth.user && ev.actor?.id === auth.user.id)

}

async function saveEditComment() {

  if (!editCommentText.value.trim()) return ElMessage.warning('评论内容不能为空')

  savingComment.value = true

  try {

    await patch(`/api/tickets/${ticketId}/comments/${editCommentId.value}`, { content: editCommentText.value })

    ElMessage.success('评论已修改')

    editCommentVisible.value = false

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  } finally {

    savingComment.value = false

  }

}

const canRate = computed(

  () =>

    ticket.value &&

    !ticket.value.rating &&

    (ticket.value.status === 'resolved' || ticket.value.status === 'closed') &&

    auth.user &&

    ticket.value.creator?.id === auth.user.id

)

onMounted(async () => {

  await load()

  if (auth.isStaff) {

    try {

      const res = await get('/api/users?role=engineer')

      // 请假/停用工程师不进指派列表，避免误派与接单广场积压

      engineers.value = (res.items || []).filter((u: any) => u.is_active && (u.status || 'on_duty') !== 'leave')

    } catch { /* ignore */ }

  }

  // 模板字段名（自定义字段展示用）

  try {

    const res = await get(`/api/tickets/templates/by-category?category=${encodeURIComponent(ticket.value?.category || '')}`)

    const map: Record<string, string> = {}

    res.items.forEach((t: any) => t.fields.forEach((f: any) => { map[f.key] = f.label }))

    fieldLabels.value = map

  } catch { /* ignore */ }

  // 相似工单与知识推荐

  try {

    similarTickets.value = (await get(`/api/tickets/${ticketId}/similar`)).items

  } catch { /* ignore */ }

  try {

    knowledgeSugs.value = (await get(`/api/tickets/${ticketId}/knowledge-suggestions`)).items

  } catch { /* ignore */ }

})

async function load() {

  try {

    ticket.value = await get(`/api/tickets/${ticketId}`)

    void loadAttBlobs()

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

async function doTransition(action: string, note: string, solution = '') {

  try {

    ticket.value = await post(`/api/tickets/${ticketId}/transition`, { action, note, solution })

    confirmVisible.value = false

    confirmForm.solution = ''

    confirmForm.feedback = ''

    ElMessage.success('操作成功')

    // 完结合并组内工单时提醒同组还有未完结的已合并工单

    const pendingMerged: string[] = ticket.value?.pending_merged || []

    if (pendingMerged.length) {

      await ElMessageBox.alert(

        `该工单存在合并关系，同组还有 ${pendingMerged.length} 张已合并工单待处理：${pendingMerged.join('、')}`,

        '合并工单提醒', { type: 'warning', confirmButtonText: '知道了' },

      )

    }

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

/** v2.12 接单广场：未指派工单在详情页一键认领到自己名下 */

async function claimTicket() {

  try {

    await post(`/api/tickets/${ticketId}/claim`)

    ElMessage.success('已认领到您名下')

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

async function doApprove() {

  try {

    const { value } = await ElMessageBox.prompt('审批意见（可选）', '审批通过', {

      inputPlaceholder: '意见（可留空）', inputValue: '',

      confirmButtonText: '通过', cancelButtonText: '取消',

    })

    ticket.value = await post(`/api/tickets/${ticketId}/transition`, { action: 'approve', note: value || '' })

    ElMessage.success('已审批通过，SLA 从此刻起算')

  } catch (e: any) {

    if (e !== 'cancel' && e?.message) ElMessage.error(e.message)

  }

}

async function doReject() {

  try {

    const { value } = await ElMessageBox.prompt('驳回原因', '审批驳回', {

      inputPlaceholder: '驳回原因（必填）', inputValue: '',

      inputValidator: (v: string) => !!v.trim() || '请填写驳回原因',

      confirmButtonText: '驳回', cancelButtonText: '取消', type: 'warning',

    })

    ticket.value = await post(`/api/tickets/${ticketId}/transition`, { action: 'reject', note: value })

    ElMessage.success('已驳回并关闭工单')

  } catch (e: any) {

    if (e !== 'cancel' && e?.message) ElMessage.error(e.message)

  }

}

async function submitComment() {

  if (!commentText.value.trim()) return

  commenting.value = true

  try {

    await post(`/api/tickets/${ticketId}/comment`, { content: commentText.value })

    commentText.value = ''

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  } finally {

    commenting.value = false

  }

}

function openAssign() {

  assignEngineerId.value = ticket.value.assignee?.id || null

  assignReason.value = ''

  assignVisible.value = true

}

async function submitAssign() {

  if (!assignEngineerId.value) return ElMessage.warning('请选择工程师')

  // v2.4.1 改派（已有处理人且换成别人）必填原因

  const reassign = !!ticket.value.assignee && ticket.value.assignee.id !== assignEngineerId.value

  if (reassign && !assignReason.value.trim()) return ElMessage.warning('改派必须填写原因')

  try {

    ticket.value = await post(`/api/tickets/${ticketId}/assign`, {

      engineer_id: assignEngineerId.value,

      reason: assignReason.value.trim(),

    })

    assignVisible.value = false

    ElMessage.success(reassign ? '已改派（原因已留痕）' : '已指派')

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

async function submitRating() {

  try {

    await post(`/api/tickets/${ticketId}/rating`, { stars: ratingForm.stars, comment: ratingForm.comment })

    ElMessage.success('感谢评价')

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

async function doUpload(opt: any) {

  uploading.value = true

  try {

    await upload(`/api/tickets/${ticketId}/attachments`, opt.file)

    ElMessage.success('附件已上传')

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  } finally {

    uploading.value = false

  }

}

async function downloadFile(att: any) {

  try {

    await download(att.url, att.filename)

  } catch (e: any) {

    ElMessage.error(e.message || '下载失败')

  }

}

// 附件在线预览（图片 blob 缩略图/大图、PDF iframe）

const attBlobs = ref<Record<number, string>>({})

const pdfVisible = ref(false)

const pdfUrl = ref('')

const pdfTitle = ref('')

function isPdf(att: any): boolean {

  return (att.content_type || '').includes('pdf') || String(att.filename || '').toLowerCase().endsWith('.pdf')

}

async function loadAttBlobs() {

  for (const att of ticket.value?.attachments || []) {

    if (att.is_image && !attBlobs.value[att.id]) {

      try {

        attBlobs.value[att.id] = await fetchBlobUrl(att.url)

      } catch { /* 预览失败保持下载可用 */ }

    }

  }

}

async function previewAtt(att: any) {

  try {

    pdfTitle.value = att.filename

    pdfUrl.value = await fetchBlobUrl(att.url)

    pdfVisible.value = true

  } catch (e: any) {

    ElMessage.error(e.message || '预览失败')

  }

}

async function urge() {

  try {

    await post(`/api/tickets/${ticketId}/urge`)

    ElMessage.success('已催办，工程师会收到提醒')

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

async function mergeInto(s: any) {

  try {

    await ElMessageBox.confirm(

      `确认把本工单并入 ${s.no}（${s.title}）？本单将关闭并标记为重复。`,

      '合并确认',

      { type: 'warning' }

    )

  } catch {

    return

  }

  try {

    await post(`/api/tickets/${ticketId}/merge`, { target_id: s.id })

    ElMessage.success('已合并')

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

function openSink() {

  sinkForm.title = `${ticket.value.title}（处理记录）`

  sinkForm.content = `【问题】${ticket.value.description || ''}\n\n【解决方案】${ticket.value.solution || ''}`

  sinkVisible.value = true

}

async function sinkKnowledge() {

  try {

    await post('/api/knowledge', { title: sinkForm.title, content: sinkForm.content, category: sinkForm.category, tags: [] })

    ElMessage.success('已保存到知识库')

    sinkVisible.value = false

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

function overdue(deadline: string | null) {

  return deadline && new Date(deadline) < new Date()

}

function fmtTime(s: string | null) {

  if (!s) return '-'

  return new Date(s).toLocaleString('zh-CN', { hour12: false })

}

function channelLabel(c: string) {

  return ({ web: 'Web 网页', dingtalk: '钉钉', feishu: '飞书', wecom: '企业微信' } as any)[c] || c

}

function statusType(s: string) {

  return ({ pending: 'warning', processing: 'primary', pending_confirm: '', resolved: 'success', closed: 'info', pending_approval: 'danger' } as any)[s] || 'info'

}

function priorityType(p: string) {

  return ({ low: 'info', medium: '', high: 'warning', urgent: 'danger' } as any)[p] || 'info'

}

</script>

<style scoped>

.page-header { margin-bottom: 14px; }

.detail-title { display: flex; align-items: center; gap: 10px; }

.detail-title .no { color: #909399; font-size: 13px; }

.detail-title .title { font-weight: 600; font-size: 15px; }

/* 窄屏头部纵向堆叠，标题不压缩不竖排 */

@media (max-width: 768px) {

  .page-header :deep(.el-page-header__back) { flex-shrink: 0; }

  .page-header :deep(.el-page-header__back .el-page-header__title) { white-space: nowrap; }

  .page-header :deep(.el-page-header__content) { display: block; width: 100%; }

  .detail-title { flex-wrap: wrap; }

  .detail-title .title { white-space: normal; word-break: break-all; flex: 1 1 100%; line-height: 1.5; }

  .detail-title .no { flex-basis: 100%; }

}

.block { margin-bottom: 14px; }

.desc { margin-top: 14px; }

.desc .label { font-size: 12px; color: #909399; margin-bottom: 4px; }

.desc .text { color: #303133; line-height: 1.7; }

.pre-wrap { white-space: pre-wrap; word-break: break-word; }

.nowrap { white-space: nowrap; }

.actions { margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

/* 工单操作按钮一行 3 个等宽（grid），不再 flex 换行 */

.actions-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 0; }

.actions-grid .el-button { margin-left: 0; width: 100%; padding-left: 0; padding-right: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.actions-grid .follower-hint { grid-column: 1 / -1; margin-left: 0; }

.op-card .actions { margin-top: 0; }

.op-card :deep(.el-button) { margin-left: 0; }

.actions-col .follower-hint { width: 100%; }

.follower-hint { color: #909399; font-size: 12px; margin-left: 4px; }

.attach-head { display: flex; justify-content: space-between; align-items: center; }

.attach-list { display: flex; flex-wrap: wrap; gap: 12px; }

.attach-item { display: flex; gap: 8px; align-items: center; padding: 6px 10px; border: 1px solid #e6e8ee; border-radius: 8px; }

.attach-thumb { width: 44px; height: 44px; border-radius: 6px; }

.attach-file-icon { color: #909399; }

.attach-info { display: flex; flex-direction: column; }

.comment-input { }

.event { line-height: 1.6; }

.event .actor { margin-right: 8px; }

.breach { color: #f56c6c; font-weight: 600; }

.muted { color: #909399; font-size: 12px; }

.side-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; }

.side-row .muted { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.merge-search { display: flex; gap: 8px; margin-bottom: 10px; }

.merge-list { max-height: 320px; overflow: auto; }

.inner-card { margin-top: 10px; }

.desc-table { margin-top: 10px; }

.comment-list { max-height: 260px; overflow: auto; margin-bottom: 10px; }

.comment-item { padding: 6px 0; border-bottom: 1px dashed #ebeef5; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }

.comment-item .actor { margin-right: 6px; }

.comment-item .content { width: 100%; }

@media (max-width: 768px) {

  .el-col-16, .el-col-14, .el-col-12, .el-col-10, .el-col-9, .el-col-8 { max-width: 100%; flex: 0 0 100%; }

  .actions { gap: 6px; }

  .actions .el-button { margin-bottom: 4px; }

}

</style>
