<template>
  <section class="page attribution-page" data-testid="site-attribution">
    <header class="page-head">
      <div>
        <h2>报文归属确认</h2>
        <p class="page-desc">
          协议探测只采用一个命中；同标识多站点候选时在此确认归属。只有维护员明确选定站点与规则的那一帧才取得投递资格。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="refresh-all" type="button" :disabled="loading" @click="reloadAll">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="card in statCards" :key="card.label" class="stat-card" :data-testid="`stat-${card.key}`">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>

    <p v-if="banner" class="banner" :class="banner.kind" data-testid="banner">{{ banner.text }}</p>

    <section class="panel probe-panel" data-testid="probe-panel">
      <header class="panel-head">
        <div>
          <h3>协议探测</h3>
          <p class="page-desc">粘贴报文后探测同标识的全部站点候选；探测只采用一个命中，且不授予投递资格。</p>
        </div>
      </header>
      <div class="probe-form">
        <label class="inline-field">
          <span>报文 hex</span>
          <input v-model="probeHex" data-testid="probe-hex" placeholder="如 41310A1B00001122" />
        </label>
        <label class="inline-field">
          <span>报文标识</span>
          <input v-model="probeIdentifier" data-testid="probe-identifier" />
        </label>
        <button class="btn" type="button" data-testid="probe-run" :disabled="probeBusy || !probeHex" @click="runProbe">
          {{ probeBusy ? '探测中…' : '探测候选' }}
        </button>
      </div>
      <div v-if="probeResult" class="probe-result" data-testid="probe-result">
        <p>
          <strong>{{ probeResult.summary }}</strong>
          <span class="muted small">
            （候选 {{ probeResult.candidate_count }}，可投递 {{ probeResult.eligible_count }}）
          </span>
        </p>
        <p v-if="probeResult.adopted_rule" class="muted small">
          预选：{{ probeResult.adopted_rule.site_code }} / {{ probeResult.adopted_rule.rule_code }}
          —— {{ probeResult.adopted_rule.reason }}
        </p>
        <p v-if="probeResult.ambiguous" class="muted small">
          存在候选冲突，未自动采用任一站点；请到下方确认单确定归属。
        </p>
        <table class="data-table">
          <thead>
            <tr>
              <th>站点</th>
              <th>解码规则</th>
              <th>字段偏移/长度</th>
              <th>字节序</th>
              <th>解码值</th>
              <th>目标Topic</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="candidate in probeResult.candidates" :key="candidate.rule_code">
              <td>{{ candidate.site_name }}（{{ candidate.site_code }}）</td>
              <td>
                <code>{{ candidate.rule_code }}</code>
                <div class="muted small">{{ candidate.rule_status }} · 标识 {{ candidate.identifier }}</div>
              </td>
              <td>{{ candidate.offset }} / {{ candidate.length }}</td>
              <td>{{ candidate.byte_order }}</td>
              <td>
                <code v-if="candidate.preview.ok">{{ candidate.preview.value }}</code>
                <span v-else class="error-text">{{ candidate.preview.message }}</span>
              </td>
              <td><code>{{ candidate.target_topic ?? '—' }}</code></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="attribution-layout">
      <aside class="panel orders-panel">
        <header class="panel-head">
          <h3>归属确认单</h3>
          <select v-model="orderFilter" data-testid="order-filter" @change="reloadOrders">
            <option value="">全部状态</option>
            <option v-for="status in orderStatuses" :key="status" :value="status">{{ status }}</option>
          </select>
        </header>
        <ul class="order-list">
          <li
            v-for="order in orders"
            :key="order.id"
            class="order-item"
            :class="{ active: order.id === activeOrderId, conflict: order.status === '版本冲突' }"
            :data-testid="`order-${order.id}`"
            @click="openOrder(order.id)"
          >
            <div class="order-title">{{ order.标题 }}</div>
            <div class="order-meta">
              <code>{{ order.单据编号 }}</code>
              <span class="pill" :class="`order-status-${order.status}`">{{ order.status }}</span>
            </div>
            <div class="order-meta">
              <span>帧 {{ order.frame_total }}</span>
              <span>待核 {{ order.frame_counts.pending + order.frame_counts.recheck }}</span>
              <span>已投递 {{ order.frame_counts.delivered }}</span>
            </div>
          </li>
          <li v-if="!orders.length" class="empty-state">暂无符合条件的确认单</li>
        </ul>
      </aside>

      <main class="panel detail-panel">
        <div v-if="!activeOrder" class="empty-state">请选择左侧的归属确认单</div>
        <template v-else>
          <header class="panel-head">
            <div>
              <h3>{{ activeOrder.标题 }}</h3>
              <p class="page-desc">
                <code>{{ activeOrder.单据编号 }}</code>
                · 单据状态 <strong :data-testid="`order-status-${activeOrder.id}`">{{ activeOrder.status }}</strong>
                · 版本 v{{ activeOrder.version }}
              </p>
            </div>
          </header>

          <article
            v-for="frame in activeOrder.frames ?? []"
            :key="frame.id"
            class="frame-card"
            :data-testid="`frame-${frame.id}`"
            :data-frame-status="frame.status"
          >
            <header class="frame-head">
              <div>
                <strong>{{ frame.帧编号 }}</strong>
                <span class="muted"> · 标识 {{ frame.报文标识 }} · {{ frame.源Topic }}</span>
              </div>
              <div class="frame-badges">
                <span class="pill" :class="`frame-status-${frame.status}`" :data-testid="`frame-status-${frame.id}`">
                  {{ frame.status }}
                </span>
                <span v-if="frame.delivery_eligible" class="pill ok" :data-testid="`eligible-${frame.id}`">
                  有投递资格
                </span>
                <span v-else class="pill muted-pill">无投递资格</span>
              </div>
            </header>

            <p class="frame-wire"><code>{{ frame.报文内容 }}</code></p>

            <p class="detect-note" :data-testid="`detect-${frame.id}`">
              探测：{{ frame.detection.summary }}
            </p>

            <div v-if="frame.conflict" class="conflict-box" :data-testid="`conflict-${frame.id}`">
              <strong>版本冲突（{{ frame.conflict.code }}）</strong>
              <ul>
                <li v-for="reason in frame.conflict.reasons" :key="reason">{{ reason }}</li>
              </ul>
              <p class="muted">
                冲突检出 {{ frame.conflict.detected_at }}；原选定快照仍保留作为追责依据，需重新选择后才能再次投递。
              </p>
            </div>

            <div v-if="frame.selected" class="selection-box" :data-testid="`selection-${frame.id}`">
              <div class="selection-line">
                <span>选定站点</span><strong>{{ frame.selected.site_name }}</strong>
                <span>解码规则</span><strong>{{ frame.selected.decode_rule_code }}</strong>
                <span>路由规则</span><strong>{{ frame.selected.route_rule_code }}</strong>
                <span v-if="frame.selected.stale" class="pill danger">快照已失效</span>
              </div>
              <div class="selection-line muted">
                依据：{{ frame.selected.basis }}
              </div>
            </div>

            <!-- 候选对比：同标识各站点规则，字段差异由服务端标注 -->
            <div class="candidate-wrap">
              <table class="data-table candidate-table">
                <thead>
                  <tr>
                    <th>规则字段</th>
                    <th v-for="candidate in frame.candidates" :key="candidate.site_code">
                      <label class="candidate-pick">
                        <input
                          type="radio"
                          :name="`site-${frame.id}`"
                          :value="candidate.site_code"
                          :disabled="!candidate.eligible || frame.status === '已投递'"
                          :checked="draft(frame.id).site_code === candidate.site_code"
                          :data-testid="`pick-${frame.id}-${candidate.site_code}`"
                          @change="chooseSite(frame, candidate.site_code)"
                        />
                        <span>{{ candidate.site_name }}</span>
                      </label>
                      <div class="muted small">
                        {{ candidate.site_code }} · 站点 v{{ candidate.site_version }} ·
                        {{ candidate.site_status }}
                      </div>
                      <div class="muted small">
                        {{ candidate.rule_code }} · 规则 v{{ candidate.rule_version }} ·
                        {{ candidate.rule_status }}
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in CANDIDATE_FIELDS"
                    :key="row.field"
                    :class="{ 'conflict-row': hasConflict(frame, row.field) }"
                    :data-testid="`cand-row-${frame.id}-${row.field}`"
                    :data-conflict="hasConflict(frame, row.field) ? 'true' : 'false'"
                  >
                    <th>{{ row.field }}</th>
                    <td
                      v-for="candidate in frame.candidates"
                      :key="candidate.site_code"
                      :class="{ 'conflict-cell': hasConflict(frame, row.field) }"
                    >
                      {{ row.label(candidate) || '—' }}
                    </td>
                  </tr>
                  <tr>
                    <th>站点独立解码</th>
                    <td v-for="candidate in frame.candidates" :key="candidate.site_code">
                      <template v-if="candidate.preview.ok">
                        <code>{{ candidate.preview.value }}</code>
                        <div class="muted small">字段 {{ candidate.preview.field_hex }}</div>
                      </template>
                      <span v-else class="error-text">{{ candidate.preview.message }}</span>
                    </td>
                  </tr>
                  <tr>
                    <th>核准依据</th>
                    <td v-for="candidate in frame.candidates" :key="candidate.site_code">
                      <div class="small">{{ candidate.basis }}</div>
                      <div class="muted small">{{ candidate.approved_by }} · {{ candidate.approved_at }}</div>
                    </td>
                  </tr>
                  <tr>
                    <th>目标Topic</th>
                    <td v-for="candidate in frame.candidates" :key="candidate.site_code">
                      <code>{{ candidate.target_topic ?? '—' }}</code>
                    </td>
                  </tr>
                </tbody>
              </table>
              <p v-if="frame.field_conflicts.length" class="muted small" :data-testid="`field-conflicts-${frame.id}`">
                字段冲突：
                <span v-for="item in frame.field_conflicts" :key="item.field" class="conflict-tag">
                  {{ item.field }}（{{ item.sites.join(' / ') }}）
                </span>
              </p>
            </div>

            <p v-if="frame.status === '待核对' || frame.status === '待再次核对'" class="frame-guide muted small">
              该帧尚无投递资格：请在上方候选表选定站点，确认后才会进入可试投状态；不明确的请点「留待核对」。
            </p>
            <div class="frame-actions">
              <label class="inline-field">
                <span>路由规则</span>
                <select
                  v-model="draft(frame.id).route_rule_code"
                  :data-testid="`route-${frame.id}`"
                  :disabled="!draft(frame.id).site_code"
                >
                  <option :value="null">按站点自动匹配</option>
                  <option
                    v-for="route in routeOptions(frame, draft(frame.id).site_code)"
                    :key="route['规则编号']"
                    :value="route['规则编号']"
                  >
                    {{ route['规则编号'] }} → {{ route['目标Topic'] }}（{{ route.status }}）
                  </option>
                </select>
              </label>
              <label class="inline-field">
                <span>备注</span>
                <input v-model="draft(frame.id).remark" :data-testid="`remark-${frame.id}`" placeholder="选站说明" />
              </label>
              <button
                class="btn primary"
                type="button"
                :data-testid="`select-${frame.id}`"
                :disabled="busy || !draft(frame.id).site_code || frame.status === '已投递'"
                @click="confirmSelection(frame)"
              >
                确认站点与规则
              </button>
              <button
                class="btn"
                type="button"
                :data-testid="`dispatch-${frame.id}`"
                :disabled="busy || frame.status === '已投递' || frame.status === '留待核对'"
                @click="dispatch(frame)"
              >
                试投（受控发送）
              </button>
              <button
                class="btn ghost"
                type="button"
                :data-testid="`hold-${frame.id}`"
                :disabled="busy || frame.status === '已投递' || frame.status === '留待核对'"
                @click="hold(frame)"
              >
                留待核对
              </button>
              <span v-if="frame.message" class="pill ok" :data-testid="`message-${frame.id}`">
                消息 {{ frame.message.message_id }} → {{ frame.message.目标Topic }}
              </span>
            </div>

            <p v-if="frameErrors[frame.id]" class="error-text" :data-testid="`frame-error-${frame.id}`">
              {{ frameErrors[frame.id] }}
            </p>
            <p v-if="frameNotices[frame.id]" class="notice-text" :data-testid="`frame-notice-${frame.id}`">
              {{ frameNotices[frame.id] }}
            </p>
          </article>
        </template>
      </main>

      <aside class="panel sites-panel">
        <header class="panel-head"><h3>站点与规则</h3></header>
        <article v-for="site in sites" :key="site['站点编号']" class="site-card" :data-testid="`site-${site['站点编号']}`">
          <div class="site-head">
            <strong>{{ site['站点名称'] }}</strong>
            <span class="muted small">{{ site['站点编号'] }} · {{ site['区域'] }}</span>
          </div>
          <div class="selection-line">
            <span class="pill" :class="site.status === '启用中' ? 'ok' : 'danger'">{{ site.status }}</span>
            <span class="muted small">站点 v{{ site.version }}</span>
            <span v-if="site['停用原因']" class="muted small">（{{ site['停用原因'] }}）</span>
          </div>
          <ul class="rule-list">
            <li v-for="rule in site.decode_rules" :key="rule['规则编号']">
              <code>{{ rule['规则编号'] }}</code>
              <span class="muted small">标识 {{ rule['报文标识'] }} · {{ rule.status }} v{{ rule.version }}</span>
              <button
                v-if="rule.status !== '已核准'"
                class="link"
                type="button"
                :disabled="busy || site.status !== '启用中'"
                :data-testid="`approve-${rule['规则编号']}`"
                @click="reApprove(site['站点编号'], rule['规则编号'])"
              >
                重新核准
              </button>
            </li>
            <li v-for="rule in site.route_rules" :key="rule['规则编号']">
              <code>{{ rule['规则编号'] }}</code>
              <span class="muted small">路由 {{ rule['匹配Topic'] }} → {{ rule['目标Topic'] }} · {{ rule.status }}</span>
            </li>
          </ul>
          <button
            class="btn ghost small"
            type="button"
            :disabled="busy"
            :data-testid="`toggle-site-${site['站点编号']}`"
            @click="toggleSite(site)"
          >
            {{ site.status === '启用中' ? '停用站点（模拟现场变更）' : '启用站点' }}
          </button>
        </article>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import {
  approveRule,
  detect,
  dispatchFrame,
  holdFrame,
  loadOrder,
  loadOrders,
  loadSites,
  loadStats,
  selectFrame,
  setSiteStatus,
} from '@/api/site-attribution'
import {
  CANDIDATE_FIELDS,
  conflictFor,
  type AttributionFrame,
  type AttributionOrder,
  type AttributionStats,
  type DetectionResult,
  type OrderStatus,
  type Site,
} from '@/domain/siteAttribution'

const route = useRoute()
const ORDER_STATUSES: OrderStatus[] = ['待核对', '办理中', '版本冲突', '已完成']
const orderStatuses = ORDER_STATUSES

type Draft = { site_code: string; route_rule_code: string | null; remark: string }

const orders = ref<AttributionOrder[]>([])
const activeOrder = ref<AttributionOrder | null>(null)
const activeOrderId = ref<number | null>(null)
const sites = ref<Site[]>([])
const stats = ref<AttributionStats | null>(null)
const orderFilter = ref<OrderStatus | ''>('')
const drafts = reactive<Record<number, Draft>>({})
const frameErrors = reactive<Record<number, string>>({})
const frameNotices = reactive<Record<number, string>>({})
const busy = ref(false)
const loading = ref(false)
const banner = ref<{ kind: string; text: string } | null>(null)
const probeHex = ref('41310A1B00001122')
const probeIdentifier = ref('A1')
const probeResult = ref<DetectionResult | null>(null)
const probeBusy = ref(false)

const statCards = computed(() => {
  const value = stats.value
  return [
    { key: 'orders', label: '确认单', value: value?.orders ?? 0 },
    { key: 'pending', label: '待核对帧', value: value?.pending ?? 0 },
    { key: 'in-flight', label: '已选定/在途', value: value?.in_flight ?? 0 },
    { key: 'delivered', label: '已投递', value: value?.delivered ?? 0 },
    { key: 'conflicts', label: '待再次核对', value: value?.conflicts ?? 0 },
    { key: 'messages', label: '试投消息', value: value?.messages ?? 0 },
  ]
})

function draft(frameId: number): Draft {
  if (!drafts[frameId]) {
    drafts[frameId] = { site_code: '', route_rule_code: null, remark: '' }
  }
  return drafts[frameId]
}

function syncDraft(frame: AttributionFrame) {
  if (!frame.selected) return
  // 重开旧单时保留上次选择供参考；站点或规则失效后仍需重新确认才算投递资格。
  const current = draft(frame.id)
  current.site_code = frame.selected.site_code
  current.route_rule_code = frame.selected.route_rule_code
}

function chooseSite(frame: AttributionFrame, siteCode: string) {
  const current = draft(frame.id)
  const previousSite = current.site_code
  current.site_code = siteCode
  // 换站后不能沿用上一站的路由规则，交回服务端按新站点自动匹配。
  if (previousSite !== siteCode) current.route_rule_code = null
  const conflict = frame.field_conflicts.find((item) => item.field === '字段偏移')
  if (conflict) {
    const picked = conflict.values.find((item) => item.site_code === siteCode)
    if (picked) frameNotices[frame.id] = `已按 ${picked.site_name} 的解释预览字段，未沿用其他站点规则。`
  }
}

function routeOptions(frame: AttributionFrame, siteCode: string) {
  const site = sites.value.find((item) => item['站点编号'] === siteCode)
  const rules = site?.route_rules ?? []
  // 路由候选只来自已选站点的规则，绝不跨站复用。
  return rules.filter((rule) => rule['匹配Topic'] === frame.源Topic)
}

function hasConflict(frame: AttributionFrame, field: string) {
  return conflictFor(frame, field) !== null
}

function setBanner(kind: string, text: string) {
  banner.value = { kind, text }
}

function describeOutcome(outcome: { message: string; reasons?: string[]; duplicate?: boolean }) {
  const parts = [outcome.message]
  if (outcome.reasons?.length) parts.push(`原因：${outcome.reasons.join('；')}`)
  if (outcome.duplicate) parts.push('重复提交未生成新记录')
  return parts.join('。')
}

async function runProbe() {
  probeBusy.value = true
  banner.value = null
  try {
    probeResult.value = await detect(probeHex.value.trim(), probeIdentifier.value.trim() || 'A1')
  } catch (error) {
    setBanner('error', error instanceof Error ? error.message : '探测失败')
  } finally {
    probeBusy.value = false
  }
}

async function reloadOrders() {
  try {
    orders.value = await loadOrders(orderFilter.value || undefined)
  } catch (error) {
    setBanner('error', error instanceof Error ? error.message : '确认单读取失败')
  }
}

async function reloadSites() {
  try {
    sites.value = await loadSites()
  } catch (error) {
    setBanner('error', error instanceof Error ? error.message : '站点读取失败')
  }
}

async function reloadStats() {
  try {
    stats.value = await loadStats()
  } catch (error) {
    setBanner('error', error instanceof Error ? error.message : '统计读取失败')
  }
}

async function openOrder(orderId: number) {
  try {
    activeOrder.value = await loadOrder(orderId)
    activeOrderId.value = orderId
    for (const frame of activeOrder.value.frames ?? []) {
      syncDraft(frame)
      frameErrors[frame.id] = ''
      frameNotices[frame.id] = ''
    }
  } catch (error) {
    setBanner('error', error instanceof Error ? error.message : '确认单详情读取失败')
  }
}

async function refreshAll() {
  await Promise.all([reloadOrders(), reloadSites(), reloadStats()])
  if (activeOrderId.value !== null) await openOrder(activeOrderId.value)
}

async function reloadAll() {
  loading.value = true
  banner.value = null
  try {
    await refreshAll()
  } finally {
    loading.value = false
  }
}

async function confirmSelection(frame: AttributionFrame) {
  const current = draft(frame.id)
  if (!current.site_code) return
  const candidate = frame.candidates.find((item) => item.site_code === current.site_code)
  if (!candidate) {
    frameErrors[frame.id] = `未找到 ${current.site_code} 的候选规则，请刷新后重试`
    return
  }
  busy.value = true
  frameErrors[frame.id] = ''
  try {
    const outcome = await selectFrame(frame.order_id, frame.id, {
      site_code: candidate.site_code,
      decode_rule_code: candidate.rule_code,
      route_rule_code: current.route_rule_code,
      expected_version: frame.version,
      remark: current.remark,
    })
    await applyOutcome(frame, outcome)
  } catch (error) {
    frameErrors[frame.id] = error instanceof Error ? error.message : '选站失败'
  } finally {
    busy.value = false
  }
}

async function dispatch(frame: AttributionFrame) {
  busy.value = true
  frameErrors[frame.id] = ''
  try {
    const outcome = await dispatchFrame(frame.order_id, frame.id, {
      expected_version: frame.version,
      request_id: `REQ-${frame.帧编号}-${frame.version}`,
    })
    const message = outcome.trial_message
    const notice = outcome.ok
      ? (message
        ? `试投消息 ${message.message_id} → ${message.目标Topic}（${message.站点名称} / ${message.规则编号}）`
        : describeOutcome(outcome))
      : ''
    await applyOutcome(frame, outcome, { notice })
  } catch (error) {
    frameErrors[frame.id] = error instanceof Error ? error.message : '试投失败'
  } finally {
    busy.value = false
  }
}

async function hold(frame: AttributionFrame) {
  busy.value = true
  frameErrors[frame.id] = ''
  try {
    const outcome = await holdFrame(frame.order_id, frame.id, {
      expected_version: frame.version,
      remark: draft(frame.id).remark,
    })
    await applyOutcome(frame, outcome)
  } catch (error) {
    frameErrors[frame.id] = error instanceof Error ? error.message : '留待核对失败'
  } finally {
    busy.value = false
  }
}

async function applyOutcome(
  frame: AttributionFrame,
  outcome: { ok: boolean; message: string; reasons?: string[]; duplicate?: boolean; code?: string },
  options: { notice?: string } = {},
) {
  const errorText = outcome.ok ? '' : describeOutcome(outcome)
  const noticeText = outcome.ok ? (options.notice ?? describeOutcome(outcome)) : ''
  if (!outcome.ok) {
    if (outcome.code === 'VERSION_CONFLICT') {
      setBanner('error', '试投前的核准依据校验未通过：已转入待再次核对，未产生任何消息。')
    } else if (outcome.code === 'FRAME_VERSION_MISMATCH') {
      setBanner('warn', '该帧版本已变化，页面已刷新，请重新核对后提交。')
    }
  }
  if (activeOrderId.value !== null) await openOrder(activeOrderId.value)
  // 详情刷新会清空逐帧提示，这里重新落一次，保证提示与最新帧状态一起展示。
  if (errorText) frameErrors[frame.id] = errorText
  if (noticeText) frameNotices[frame.id] = noticeText
  await Promise.all([reloadOrders(), reloadStats()])
}

async function toggleSite(site: Site) {
  busy.value = true
  banner.value = null
  try {
    const target = site.status === '启用中' ? '已停用' : '启用中'
    const outcome = await setSiteStatus(
      site['站点编号'],
      target,
      target === '已停用' ? '现场变更：站点搬迁' : '',
    )
    setBanner(target === '已停用' ? 'warn' : 'notice', outcome.message)
    if (activeOrderId.value !== null) await openOrder(activeOrderId.value)
    await Promise.all([reloadSites(), reloadOrders(), reloadStats()])
  } catch (error) {
    setBanner('error', error instanceof Error ? error.message : '站点状态更新失败')
  } finally {
    busy.value = false
  }
}

async function reApprove(siteCode: string, ruleCode: string) {
  busy.value = true
  try {
    const outcome = await approveRule(siteCode, ruleCode, `现场复核补签 ${new Date().toISOString().slice(0, 10)}`)
    setBanner(outcome.ok ? 'notice' : 'error', outcome.message)
    await Promise.all([reloadSites(), reloadStats()])
    if (activeOrderId.value !== null) await openOrder(activeOrderId.value)
  } catch (error) {
    setBanner('error', error instanceof Error ? error.message : '规则核准失败')
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await refreshAll()
    const requested = Number(route.query.order)
    const target = orders.value.find((order) => order.id === requested)
    if (target) await openOrder(target.id)
    else if (orders.value.length) await openOrder(orders.value[0].id)
  } finally {
    loading.value = false
  }
})
</script>