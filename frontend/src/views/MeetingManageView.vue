<template>

  <div>

    <!-- 综合统计：新增会议室按钮移入标题行右侧；高峰/部门左右两列 + 热力图整行下方 -->

    <el-card shadow="never" class="stats-card">

      <template #header>

        <div class="stats-head">

          <b>综合统计</b>

          <span class="muted">各会议室数据见下方卡片 · 使用率按工作时段 08:00–20:00 折算</span>

          <div style="flex: 1"></div>

          <el-button type="primary" plain @click="openEditor(null)">

            <el-icon style="margin-right: 4px"><Plus /></el-icon>新增会议室

          </el-button>

        </div>

      </template>

      <el-row :gutter="16" style="margin-top: 6px" type="flex" align="stretch">

        <el-col :xs="24" :md="12" class="left-col">

          <div class="peak-panel">

            <div class="sub-title">使用高峰时段（按开始小时分布）</div>

            <div class="peak-line" v-for="p in roomStats.peak_top || []" :key="p.hour">

              <span class="peak-hour">{{ p.hour }}</span>

              <el-progress :percentage="peakPct(p.count)" :stroke-width="8" color="#409eff" style="flex: 1" />

              <span class="peak-num">{{ p.count }} 场</span>

            </div>

            <div v-if="!(roomStats.peak_top || []).length" class="muted">暂无预约数据</div>

          </div>

        </el-col>

        <el-col :xs="24" :md="12">

          <div class="peak-panel right-col-panel">

            <div class="sub-title">各部门使用频次（含人均，公平对比大小部门）</div>

            <div class="peak-line" v-for="d in roomStats.dept_freq || []" :key="d.department">

              <span class="peak-hour">{{ d.department }}</span>

              <el-progress :percentage="deptPct(d.count)" :stroke-width="8" color="#67c23a" :show-text="false" style="flex: 1" />

              <el-tooltip :content="`部门 ${d.headcount} 人，共预约 ${d.count} 场`" placement="top">

                <span class="peak-num">{{ d.count }} 场<span v-if="d.per_capita != null" class="muted"> · 人均 {{ d.per_capita }}</span></span>

              </el-tooltip>

            </div>

            <div v-if="!(roomStats.dept_freq || []).length" class="muted">暂无预约记录</div>

          </div>

        </el-col>

      </el-row>

      <!-- 热力图整行放下方 -->

      <div class="peak-panel" style="margin-top: 14px">

        <div class="sub-title">时段热力图（星期 × 开始小时，越深预约越多）</div>

        <div class="heatmap" v-if="(roomStats.heatmap_max || 0) > 0">

          <div class="hm-row hm-head">

            <span class="hm-corner"></span>

            <span class="hm-col" v-for="h in 12" :key="h">{{ h + 7 }}时</span>

          </div>

          <div class="hm-row" v-for="(row, wi) in roomStats.heatmap || []" :key="wi">

            <span class="hm-name">{{ (roomStats.weekday_names || [])[wi] }}</span>

            <span

              class="hm-cell" v-for="(c, hi) in row" :key="hi"

              :style="{ background: c ? `rgba(47, 111, 237, ${0.15 + 0.85 * c / (roomStats.heatmap_max || 1)})` : '#f5f6f8', color: c / (roomStats.heatmap_max || 1) > 0.55 ? '#fff' : '#5a6478' }"

            >{{ c || '' }}</span>

          </div>

        </div>

        <div v-else class="muted">暂无预约数据</div>

      </div>

    </el-card>

    <el-row :gutter="14">

      <el-col v-for="r in pagedRooms" :key="r.id" :xs="24" :md="12" :lg="8">

        <el-card shadow="never" class="room-card">

          <div class="room-head">

            <span class="room-name">{{ r.name }}</span>

            <el-tag v-if="r.under_maintenance" type="danger" size="small">维修中</el-tag>

            <el-tag v-else-if="!r.enabled" type="info" size="small">停用</el-tag>

            <el-tag v-else type="success" size="small">可用</el-tag>

            <el-tooltip v-if="roomTagQr(r.id)" content="查看预约二维码" placement="top">

              <el-button size="small" circle text type="primary" class="qr-mini" @click="showQr(r)">

                <el-icon><Grid /></el-icon>

              </el-button>

            </el-tooltip>

          </div>

          <div class="room-meta">

            <span v-if="r.location">{{ r.location }}</span>

            <span class="dot">·</span>

            <span>容纳 {{ r.capacity }} 人</span>

            <span class="dot">·</span>

            <span>未开始预约 {{ r.upcoming_count }} 场</span>

          </div>

          <!-- 会议室单独使用数据（近 30 天）直接记录在卡片上 -->

          <div class="room-usage" v-if="roomStatOf(r.id)">

            <span class="ru-item">预约 <b>{{ roomStatOf(r.id).bookings_30 }}</b> 场</span>

            <span class="ru-item">取消率 <b :style="{ color: roomStatOf(r.id).cancel_rate > 20 ? '#f56c6c' : '#303133' }">{{ roomStatOf(r.id).cancel_rate }}%</b></span>

            <span class="ru-item">爽约 <b>{{ roomStatOf(r.id).no_show_30 }}</b> 场</span>

            <span class="ru-item">均长 <b>{{ roomStatOf(r.id).avg_minutes }}</b> 分</span>

            <span class="ru-item">占用 <b>{{ roomStatOf(r.id).hours_30 }}</b> 小时</span>

            <span class="ru-item">使用率 <b :style="{ color: utilColor(roomStatOf(r.id).utilization) }">{{ roomStatOf(r.id).utilization }}%</b></span>

          </div>

          <div class="room-usage" v-else>近 30 天无预约记录</div>

          <!-- 设备列表摘要（损坏/维修中标红，员工与运维共同关注） -->

          <!-- 设备列表移入「巡检 → 检查结果」抽屉；卡片设备状态行标记问题设备 -->

          <div class="room-check">

            <div class="ck-line">

              <span class="ck-label">最近检查</span>

              <span v-if="r.latest_inspection" class="ck-ellipsis">{{ fmtTime(r.latest_inspection.inspected_at) }}（{{ r.latest_inspection.inspector?.name }}）</span>

              <span v-else class="ck-muted">尚未进行设备检查</span>

            </div>

            <div class="ck-line" v-if="r.latest_inspection || (r.equipment_list || []).length">

              <span class="ck-label">设备状态</span>

              <template v-if="badEquipNames(r)">

                <el-tag type="danger" size="small" effect="plain">异常 {{ (r.equipment_list || []).filter((e: any) => e.status !== '正常').length }} 台</el-tag>

                <span class="ck-ellipsis ck-bad-text" :title="badEquipNames(r)">{{ badEquipNames(r) }}</span>

              </template>

              <el-tag v-else type="success" size="small" effect="plain">全部正常</el-tag>

            </div>

            <div class="ck-line" v-if="cycleValueOf(r) > 0">

              <span class="ck-label">巡检周期</span>

              <span class="ck-ellipsis">每 {{ cycleValueOf(r) }} {{ cycleLabelOf(r) }} · {{ cycleProgressOf(r) }}</span>

              <el-tag v-if="inspectionOverdue(r)" type="danger" size="small" effect="plain"

                title="已超期：将自动生成巡检工单并派给现场运维">已超期</el-tag>

            </div>

          </div>

          <el-divider style="margin: 12px 0" />

          <div class="room-ops">

            <el-button size="small" @click="openBookings(r)">预约</el-button>

            <!-- 原「检查」按钮并入巡检下拉，改名「检查结果」 -->

            <el-dropdown trigger="click" @command="(t: string) => onInspectCommand(r, t)">

              <el-button size="small" type="warning" plain>巡检<el-icon style="margin-left: 2px"><ArrowDown /></el-icon></el-button>

              <template #dropdown>

                <el-dropdown-menu>

                  <el-dropdown-item command="定期巡检">定期巡检</el-dropdown-item>

                  <el-dropdown-item command="手动报修">手动报修</el-dropdown-item>

                  <el-dropdown-item command="检查结果" divided>检查结果</el-dropdown-item>

                </el-dropdown-menu>

              </template>

            </el-dropdown>

            <el-button size="small" type="primary" plain @click="openEditor(r)">编辑</el-button>

            <el-button size="small" type="danger" plain @click="remove(r)">删除</el-button>

          </div>

        </el-card>

      </el-col>

      <el-col v-if="!rooms.length" :span="24"><el-empty description="还没有会议室，先新增一个" /></el-col>

    </el-row>

    <el-pagination

      v-model:current-page="roomPage"

      :page-size="20"

      :total="rooms.length"

      layout="total, prev, pager, next"

      style="margin-top: 4px; justify-content: center"

    />

    <!-- 编辑会议室 -->

    <el-dialog v-model="editorVisible" :title="form.id ? '编辑会议室' : '新增会议室'" width="600px">

      <el-form label-width="90px">

        <el-form-item label="名称" required><el-input v-model="form.name" placeholder="如：大会议室" /></el-form-item>

        <el-form-item label="位置"><el-input v-model="form.location" placeholder="如 3F-301" /></el-form-item>

        <el-form-item label="容纳人数"><el-input-number v-model="form.capacity" :min="1" :max="999" /></el-form-item>

        <!-- b+c：设备列表（员工扫码判断能否满足需要，运维维护标注使用情况） -->

        <el-form-item label="设备列表">

          <div style="width: 100%">

            <div v-for="(e, i) in form.equipment_list" :key="i" style="display: flex; gap: 6px; margin-bottom: 6px">

              <el-input v-model="e.name" placeholder="设备名称（如 无线麦克风）" style="flex: 1" />

              <el-input-number v-model="e.count" :min="1" :max="99" style="width: 90px" />

              <el-select v-model="e.status" style="width: 100px">

                <el-option label="正常" value="正常" />

                <el-option label="维修中" value="维修中" />

                <el-option label="损坏" value="损坏" />

              </el-select>

              <el-button size="small" text type="danger" @click="form.equipment_list.splice(i, 1)">删除</el-button>

            </div>

            <el-button size="small" plain @click="form.equipment_list.push({ name: '', count: 1, status: '正常' })">

              <el-icon style="margin-right: 4px"><Plus /></el-icon>添加设备

            </el-button>

            <div class="muted" style="font-size: 12px; margin-top: 4px">员工扫码可见设备与状态，方便判断能否满足使用需要；异常设备会体现在巡检工单中</div>

          </div>

        </el-form-item>

        <el-form-item label="使用说明">

          <el-input v-model="form.equipment_desc" type="textarea" :rows="4" placeholder="员工扫码可见：投屏步骤、遥控器用法、常见问题等" />

        </el-form-item>

        <!-- f：巡检周期支持 天/周/场次 -->

        <el-form-item label="巡检周期">

          <div style="width: 100%">

            <div style="display: flex; align-items: center; gap: 8px">

              <el-input-number v-model="form.check_cycle_value" :min="1" :max="999" style="width: 120px" />

              <el-select v-model="form.check_cycle_unit" style="width: 110px">

                <el-option label="天" value="day" />

                <el-option label="周" value="week" />

                <el-option label="场次" value="session" />

              </el-select>

            </div>

            <div class="muted" style="font-size: 12px; margin-top: 6px">到期自动生成巡检工单，轮询派发给现场运维</div>

          </div>

        </el-form-item>

        <el-form-item label="维修公告">

          <el-switch v-model="form.under_maintenance" active-text="维修中（扫码弹出公告并暂停预约）" />

          <el-input

            v-model="form.maintenance_notice" type="textarea" :rows="3" style="margin-top: 8px"

            placeholder="公告内容：故障设备、影响、预计恢复时间"

          />

        </el-form-item>

        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>

      </el-form>

      <template #footer>

        <el-button @click="editorVisible = false">取消</el-button>

        <el-button type="primary" :loading="saving" @click="save">保存</el-button>

      </template>

    </el-dialog>

    <!-- 预约情况 -->

    <el-drawer v-model="bkVisible" :title="`预约情况 · ${current?.name || ''}`" size="560px">

      <el-empty v-if="!bkItems.length" description="未来 14 天暂无预约" :image-size="70" />

      <div v-else class="bk-list">

        <div v-for="b in bkItems" :key="b.id" class="bk-row">

          <span class="bk-date">{{ b.date }}</span>

          <span class="bk-time">{{ b.start_time }}-{{ b.end_time }}</span>

          <span class="bk-title">{{ b.title || '会议' }}</span>

          <span class="bk-booker">{{ b.booker?.name }}</span>

          <el-button size="small" text type="danger" @click="cancelBooking(b)">取消</el-button>

        </div>

      </div>

    </el-drawer>

    <!-- 检查记录（表格样式） -->

    <el-drawer v-model="insVisible" :title="`检查结果 · ${current?.name || ''}`" size="820px">

      <!-- 设备列表从卡片移入此处查看 -->

      <div v-if="(current?.equipment_list || []).length" class="drawer-equip">

        <div class="drawer-equip-title">会议室设备</div>

        <div class="room-equip">

          <span class="equip-chip" v-for="e in current.equipment_list" :key="e.name">

            <i class="equip-dot" :class="{ bad: e.status === '损坏', warn: e.status === '维修中' }"></i>

            {{ e.name }}<template v-if="e.count > 1">×{{ e.count }}</template>

            <b v-if="e.status !== '正常'" :class="e.status === '损坏' ? 'fail' : 'warn'">{{ e.status }}</b>

          </span>

        </div>

      </div>

      <el-empty v-if="!insItems.length" description="还没有检查记录（管理员扫会议室码可填报）" :image-size="70" />

      <el-table v-else :data="insItems" size="small" stripe>

        <el-table-column label="检查时间" width="150">

          <template #default="{ row }">{{ fmtTime(row.inspected_at) }}</template>

        </el-table-column>

        <el-table-column label="检查人" width="100">

          <template #default="{ row }">{{ row.inspector?.name || '-' }}</template>

        </el-table-column>

        <el-table-column label="检查结果" min-width="240">

          <template #default="{ row }">

            <div class="ins-grid">

              <span v-for="c in checkItems" :key="c[0]" class="ins-item" :class="row.results[c[0]] === 'fail' ? 'bad' : 'good'">

                {{ row.results[c[0]] === 'fail' ? '✗' : '✓' }} {{ c[1] }}

              </span>

            </div>

          </template>

        </el-table-column>

        <el-table-column label="备注（丢失/损坏/报修）" min-width="200" show-overflow-tooltip>

          <template #default="{ row }">

            <span v-if="row.note">{{ row.note }}</span>

            <span v-else class="muted">-</span>

          </template>

        </el-table-column>

      </el-table>

    </el-drawer>

    <!-- v2.12 会议室预约二维码弹窗 -->

    <el-dialog v-model="qrVisible" :title="`预约二维码 · ${qrCurrent?.room?.name || ''}`" width="420px">

      <div style="text-align: center">

        <img v-if="qrDataUrl" :src="qrDataUrl" alt="会议室二维码" style="width: 300px; height: 300px" />

        <div class="muted" style="margin-top: 10px">

          扫码进入「{{ qrCurrent?.room?.name }}」预约页；短码 {{ qrCurrent?.tag?.code }}

        </div>

        <el-button type="primary" plain style="margin-top: 10px" @click="downloadQr">下载二维码图片</el-button>

      </div>

    </el-dialog>

  </div>

</template>

<script setup lang="ts">

import { computed, onMounted, reactive, ref } from 'vue'

import { ElMessage, ElMessageBox } from 'element-plus'

import { ArrowDown } from '@element-plus/icons-vue'

import { del, get, patch, post } from '@/api/http'

const rooms = ref<any[]>([])

const roomPage = ref(1)

const pagedRooms = computed(() => rooms.value.slice((roomPage.value - 1) * 20, roomPage.value * 20))

const checkItems = ref<any[]>([])

const editorVisible = ref(false)

const saving = ref(false)

const form = reactive<any>({})

const roomStats = ref<any>({ days: 30, items: [] })

// v2.12 会议室二维码：查找该会议室的会议室码标签

const roomTags = ref<any[]>([])

const qrVisible = ref(false)

const qrCurrent = ref<any>(null)

const qrDataUrl = ref('')

async function loadRoomTags() {

  try {

    roomTags.value = (await get('/api/qr-tags?kind=room')).items

  } catch { /* ignore */ }

}

function roomTagQr(roomId: number) {

  return roomTags.value.some((t) => t.room?.id === roomId && t.enabled)

}

async function showQr(room: any) {

  const tag = roomTags.value.find((t) => t.room?.id === room.id)

  if (!tag) return

  qrCurrent.value = { tag, room }

  qrVisible.value = true

  try {

    const resp = await fetch(`/api/qr-tags/${tag.id}/qr.png`, {

      headers: { Authorization: 'Bearer ' + localStorage.getItem('itops_token') },

    })

    const blob = await resp.blob()

    qrDataUrl.value = URL.createObjectURL(blob)

  } catch {

    qrDataUrl.value = ''

  }

}

function downloadQr() {

  if (!qrDataUrl.value) return

  const a = document.createElement('a')

  a.href = qrDataUrl.value

  a.download = `会议室二维码_${qrCurrent.value.room.name}.png`

  a.click()

}

function utilColor(v: number) {

  if (v >= 60) return '#f56c6c'

  if (v >= 30) return '#e6a23c'

  return '#67c23a'

}

const current = ref<any>(null)

const bkVisible = ref(false)

const bkItems = ref<any[]>([])

const insVisible = ref(false)

const insItems = ref<any[]>([])

onMounted(load)

async function load() {

  loadRoomTags()

  try {

    const res = await get('/api/meetings/rooms')

    rooms.value = res.items

    if (res.check_items?.length) checkItems.value = res.check_items

  } catch (e: any) {

    ElMessage.error(e.message)

  }

  // v2.12 使用率统计

  try {

    roomStats.value = await get('/api/meetings/stats?days=30')

  } catch { /* 统计失败不阻塞页面 */ }

}

/** v2.12 巡检是否超期；兼容 day/week/session 三种周期单位 */

function inspectionOverdue(r: any) {

  const value = cycleValueOf(r)

  if (!value) return false

  const unit = r.check_cycle_unit || 'day'

  if (unit === 'session') {

    return (r.sessions_since_inspection ?? 0) >= value

  }

  if (!r.latest_inspection) return true

  const days = r.inspection_due_days ?? 0

  return days >= value * (unit === 'week' ? 7 : 1)

}

// 周期单位辅助显示

function cycleValueOf(r: any): number {

  return r.check_cycle_value || r.check_cycle_days || 0

}

function cycleLabelOf(r: any): string {

  const unit = r.check_cycle_unit || 'day'

  return unit === 'week' ? '周' : unit === 'session' ? '场次' : '天'

}

function cycleProgressOf(r: any): string {

  const unit = r.check_cycle_unit || 'day'

  if (unit === 'session') {

    return `自上次检查已使用 ${r.sessions_since_inspection ?? 0} 场`

  }

  return r.inspection_due_days == null ? '从未检查' : `距上次检查 ${r.inspection_due_days} 天`

}

// 会议室卡片直接显示该房间近 30 天使用数据

function roomStatOf(roomId: number) {

  return (roomStats.value.items || []).find((it: any) => it.room_id === roomId) || null

}

// 全局质量指标（平均时长/取消率/爽约总数）

function peakPct(count: number) {

  const max = Math.max(...(roomStats.value.peak_top || []).map((p) => p.count), 1)

  return Math.round((100 * count) / max)

}

function deptPct(count: number) {

  const max = Math.max(...(roomStats.value.dept_freq || []).map((d) => d.count), 1)

  return Math.round((100 * count) / max)

}

function fmtTime(s: string | null) {

  if (!s) return '-'

  return new Date(s).toLocaleString('zh-CN', { hour12: false })

}

function openEditor(room: any) {

  Object.assign(form, room

    ? { ...room, equipment_list: (room.equipment_list || []).map((e: any) => ({ ...e })), check_cycle_unit: room.check_cycle_unit || 'day', check_cycle_value: room.check_cycle_value > 0 ? room.check_cycle_value : 1 }

    : { id: null, name: '', location: '', capacity: 10, equipment_desc: '', equipment_list: [], under_maintenance: false, maintenance_notice: '', enabled: true, check_cycle_unit: 'day', check_cycle_value: 1 })

  editorVisible.value = true

}

async function save() {

  if (!form.name.trim()) return ElMessage.warning('请填写会议室名称')

  if ((form.equipment_list || []).some((e: any) => !e.name?.trim())) return ElMessage.warning('设备列表存在未填写名称的行')

  saving.value = true

  try {

    // 兼容旧字段：day 单位时同步 check_cycle_days（老版本读数与统计兼容）

    const payload = { ...form, check_cycle_days: form.check_cycle_unit === 'day' ? (form.check_cycle_value || 0) : (form.check_cycle_days || 0) }

    delete (payload as any).latest_inspection

    delete (payload as any).upcoming_count

    delete (payload as any).inspection_due_days

    delete (payload as any).sessions_since_inspection

    if (form.id) await patch(`/api/meetings/rooms/${form.id}`, payload)

    else await post('/api/meetings/rooms', payload)

    ElMessage.success('已保存')

    editorVisible.value = false

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  } finally {

    saving.value = false

  }

}

// 巡检下拉分发——检查结果走检查抽屉，其余为发起巡检工单

function onInspectCommand(r: any, cmd: string) {

  if (cmd === '检查结果') openInspections(r)

  else inspectRoom(r, cmd)

}

// 设备台账异常设备名串（空=全部正常）

function badEquipNames(r: any): string {

  const bad = (r.equipment_list || []).filter((e: any) => e.status !== '正常')

  return bad.map((e: any) => `${e.name}（${e.status}）`).join('、')

}

// 手动发起巡检工单（类型枚举），生成后提示工单号

async function inspectRoom(r: any, inspectType: string) {

  try {

    await ElMessageBox.confirm(

      `为「${r.name}」发起${inspectType}巡检工单？已有未结巡检工单时将被拦截。`,

      '发起巡检', { type: 'warning', confirmButtonText: '发起' },

    )

  } catch { return }

  try {

    const res = await post(`/api/meetings/rooms/${r.id}/inspect`, { inspect_type: inspectType })

    ElMessage.success(`巡检工单已生成：${res.ticket.no}`)

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

async function remove(room: any) {

  try {

    await ElMessageBox.confirm(`确认删除会议室「${room.name}」？其历史预约与检查记录将一并删除。`, '删除确认', { type: 'warning' })

  } catch { return }

  try {

    await del(`/api/meetings/rooms/${room.id}`)

    ElMessage.success('已删除')

    await load()

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

async function openBookings(room: any) {

  current.value = room

  bkItems.value = [] // 切换房间时先清空，避免显示上一间的旧数据

  try {

    const res = await get(`/api/meetings/bookings?room_id=${room.id}`)

    bkItems.value = res.items

  } catch (e: any) {

    ElMessage.error(e.message)

  }

  bkVisible.value = true

}

async function cancelBooking(b: any) {

  try {

    await ElMessageBox.confirm(`取消 ${b.date} ${b.start_time}-${b.end_time} 的预约（${b.booker?.name}）？`, '取消预约', { type: 'warning' })

  } catch { return }

  try {

    await del(`/api/meetings/bookings/${b.id}`)

    ElMessage.success('已取消')

    await openBookings(current.value)

  } catch (e: any) {

    ElMessage.error(e.message)

  }

}

async function openInspections(room: any) {

  current.value = room

  insItems.value = []

  try {

    const res = await get(`/api/meetings/rooms/${room.id}/inspections`)

    insItems.value = res.items

    if (res.check_labels) checkItems.value = Object.entries(res.check_labels)

  } catch (e: any) {

    ElMessage.error(e.message)

  }

  insVisible.value = true

}

</script>

<style scoped>

.room-actions { margin-bottom: 16px; }

.sub-title { font-size: 13px; color: #5a6478; margin-bottom: 8px; font-weight: 600; }

.peak-line { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }

.peak-line { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }

.peak-hour { font-size: 12px; color: #303133; flex-shrink: 0; }

/* 部门列标签定宽对齐（旧 width:110px 是时间标签遗留，致部门名与进度条间隔 74px 且人均被挤出） */

.right-col-panel .peak-hour { width: 44px; }

/* peak-num 规则合并——删除旧 width:46px 定宽（右侧「N 场 · 人均 X」内容需 ~92px，被 46px 裁剪致人均溢出灰色框格） */

.peak-num { font-size: 12px; color: #5a6478; text-align: right; white-space: nowrap; flex-shrink: 0; }

.right-col-panel .peak-num { width: 138px; }

.stats-card { margin-bottom: 16px; }

/* 左右两栏等高：el-row flex + panel 填满，消除热力图下方留白 */

.stats-card .el-row.el-row--flex { align-items: stretch; }

.stats-card .el-row--flex > .el-col { display: flex; }

/* 热力图格加高，配合等高填充 */

.hm-cell { height: 26px; }

.hm-row { gap: 5px; }

/* 使用明细：数字列弱化零值、会议室名加粗、高峰/部门浅色面板 */

.room-cell-name { font-weight: 600; color: #1d2535; }

.num-muted { color: #c0c4cc; }

.peak-panel { background: #fafbfc; border: 1px solid #f0f2f5; border-radius: 8px; padding: 14px 16px; min-height: 120px; }

/* 左列（高峰/部门）与右侧热力图等高；两侧面板等高、行紧凑单行（num 不换行） */

.left-col { display: flex; flex-direction: column; gap: 14px; }

.left-col .peak-panel { flex: 1; min-height: 0; }

.right-col-panel { height: 100%; }

.util-line { display: flex; align-items: center; gap: 8px; }

.util-num { font-size: 12px; width: 46px; text-align: right; }

/* 无论是否有异常记录，卡片高度统一（内容少时按钮区贴底） */

.room-card { margin-bottom: 16px; height: 100%; min-height: 262px; display: flex; flex-direction: column; }

.room-card :deep(.el-card__body) { flex: 1; display: flex; flex-direction: column; }

.room-card .room-ops { margin-top: auto; }

.room-card :deep(.el-card__body) { padding: 20px 22px; }

.room-head { display: flex; align-items: center; gap: 12px; }

.room-name { font-size: 17px; font-weight: 600; color: #1d2535; }

.room-meta { color: #5a6478; font-size: 13px; margin: 14px 0 10px; display: flex; align-items: center; gap: 8px; }

.dot { color: #c0c4cc; }

/* 会议室卡片使用数据行 */

.room-usage {

  display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px 10px;

  font-size: 12px; color: #5a6478;

  background: #fafbfc; border: 1px solid #f0f2f5; border-radius: 8px;

  padding: 8px 12px; margin-top: 10px;

}

/* 质量指标行 */

.quality-row { display: flex; gap: 14px; }

.quality-item {

  flex: 1; background: #fafbfc; border: 1px solid #f0f2f5; border-radius: 8px;

  padding: 10px 14px; display: flex; flex-direction: column; gap: 3px;

}

.quality-item .q-label { font-size: 12px; color: #5a6478; }

.quality-item .q-value { font-size: 20px; font-weight: 700; color: #303133; }

.quality-item .q-hint { font-size: 11px; color: #a8afbd; }

/* 时段热力图 */

.heatmap { display: flex; flex-direction: column; gap: 3px; }

.hm-row { display: grid; grid-template-columns: 40px repeat(12, 1fr); gap: 3px; align-items: stretch; }

.hm-head .hm-col, .hm-name, .hm-corner { font-size: 11px; color: #8a93a6; text-align: center; }

.hm-name { text-align: left; line-height: 22px; }

.hm-cell {

  height: 22px; border-radius: 4px; font-size: 11px;

  display: flex; align-items: center; justify-content: center;

}

.room-usage.ru-muted { padding: 8px 12px; }

.room-usage b { font-weight: 600; }

.room-check { font-size: 13px; display: flex; flex-direction: column; gap: 6px; margin-top: 14px; }

/* 设备 chip 与检查行排版 */

.room-equip { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }

.equip-chip {

  display: inline-flex; align-items: center; gap: 5px;

  background: #f5f6f8; border-radius: 5px; padding: 3px 9px;

  font-size: 12px; color: #303133;

}

.equip-dot { width: 7px; height: 7px; border-radius: 50%; background: #67c23a; flex-shrink: 0; }

.equip-dot.warn { background: #e6a23c; }

.equip-dot.bad { background: #f56c6c; }

.equip-chip b.fail { color: #f56c6c; font-weight: 600; margin-left: 2px; }

.equip-chip b.warn { color: #e6a23c; font-weight: 600; margin-left: 2px; }

.ck-line { display: flex; align-items: center; gap: 8px; min-width: 0; }

.ck-label { color: #909399; font-size: 12px; flex-shrink: 0; width: 52px; }

.ck-ellipsis { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.ck-muted { color: #a8afbd; font-size: 12px; }

.ck-bad-text { color: #f56c6c; font-size: 12px; }

/* 检查结果抽屉设备块 */

.drawer-equip { margin-bottom: 16px; padding-bottom: 14px; border-bottom: 1px dashed #ebeef5; }

.drawer-equip-title { font-size: 12px; color: #909399; margin-bottom: 8px; font-weight: 600; }

.room-check .ck-line.ok { color: #67c23a; }

.room-check .ck-line.fail { color: #f56c6c; font-weight: 600; }

.room-check .ck-line.muted { color: #909399; }

.room-ops { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }

.room-ops .el-button { margin-left: 0; width: 100%; padding-left: 0; padding-right: 0; }

.qr-mini { margin-left: auto; }

.stats-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }

/* 窄屏标题/提示/按钮允许换行，标题不竖排；peak-num（场次/人均）不压缩不竖排 */

@media (max-width: 768px) {

  .stats-head { flex-wrap: wrap; row-gap: 6px; }

  .stats-head b { white-space: nowrap; }

  .stats-head .muted { flex-basis: 100%; order: 3; }

  .peak-num { white-space: nowrap; flex-shrink: 0; font-size: 11px; }

  .peak-line .el-progress { min-width: 60px; }

}

.stat-card { text-align: center; }

.stat-value { font-size: 26px; font-weight: 700; }

.stat-label { font-size: 12px; color: #909399; margin-top: 4px; }

.muted { color: #909399; font-size: 12px; }

.bk-list { display: flex; flex-direction: column; gap: 8px; }

.bk-row {

  display: flex; align-items: center; gap: 10px; padding: 9px 12px;

  border: 1px solid #e6e8ee; border-radius: 8px; font-size: 13px; flex-wrap: wrap;

}

.bk-date { color: #5a6478; font-weight: 600; }

.bk-time { color: #2f6fed; font-weight: 600; }

.bk-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.bk-booker { color: #8a93a6; font-size: 12px; }

.ins-grid { display: flex; flex-wrap: wrap; gap: 4px 12px; }

.ins-item { font-size: 12px; white-space: nowrap; }

.ins-item.good { color: #67c23a; }

.ins-item.bad { color: #f56c6c; font-weight: 600; }

.muted { color: #909399; }

</style>
