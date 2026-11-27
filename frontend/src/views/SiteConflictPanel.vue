<template>
  <section v-if="relevant" class="panel conflict-panel" data-testid="workbench-site-conflicts">
    <header class="panel-head">
      <div>
        <h3>站点协议候选冲突</h3>
        <p class="page-desc">
          同标识报文在不同站点登记时，服务端把冲突落到具体规则字段；解码与路由只按确认页选中的结果处理。
        </p>
      </div>
      <RouterLink
        class="btn primary"
        data-testid="open-attribution"
        :to="{ path: '/site-attribution', query: focusOrder ? { order: String(focusOrder) } : undefined }"
      >
        打开归属确认页
      </RouterLink>
    </header>

    <p v-if="errorMessage" class="error-text" data-testid="workbench-conflict-error">{{ errorMessage }}</p>
    <p v-else-if="!pendingOrders.length" class="muted">当前没有待核的站点归属冲突。</p>

    <table v-else class="data-table">
      <thead>
        <tr>
          <th>确认单</th>
          <th>单据状态</th>
          <th>待核帧</th>
          <th>冲突字段</th>
          <th>涉及站点</th>
          <th>查证</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="order in pendingOrders" :key="order.id" :data-testid="`workbench-order-${order.id}`">
          <td>
            <div>{{ order.标题 }}</div>
            <code class="small">{{ order.单据编号 }}</code>
          </td>
          <td>
            <span class="pill" :class="order.status === '版本冲突' ? 'danger' : 'warn'">
              {{ order.status }}
            </span>
          </td>
          <td>{{ order.frame_counts.pending + order.frame_counts.recheck + order.frame_counts.held }}</td>
          <td>
            <span v-for="field in order.conflict_fields" :key="field" class="conflict-tag">{{ field }}</span>
            <span v-if="!order.conflict_fields.length" class="muted">—</span>
          </td>
          <td>{{ order.conflict_sites.length ? order.conflict_sites.join(' / ') : '—' }}</td>
          <td>
            <RouterLink
              class="link"
              :to="{ path: '/site-attribution', query: { order: String(order.id) } }"
              :data-testid="`inspect-${order.id}`"
            >
              核对并选站
            </RouterLink>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { loadOrders } from '@/api/site-attribution'
import type { AttributionOrder } from '@/domain/siteAttribution'

const props = defineProps<{ moduleKey: string }>()
const emit = defineEmits<{ conflicts: [fields: string[]] }>()

// 只有解码/路由这两个直接消费站点规则的模块需要在工作台给出查证入口。
const relevant = ['msg_decode', 'msg_router'].includes(props.moduleKey)

const pendingOrders = ref<AttributionOrder[]>([])
const errorMessage = ref('')
const focusOrder = ref<number | null>(null)

onMounted(async () => {
  if (!relevant) return
  try {
    const orders = await loadOrders()
    pendingOrders.value = orders.filter((order) => {
      const open =
        order.frame_counts.pending + order.frame_counts.recheck + order.frame_counts.held
      // 有字段级冲突的待核单据才需要在解码/路由工作台上给出查证入口。
      return open > 0 && order.conflict_fields.length > 0
    })
    focusOrder.value = pendingOrders.value[0]?.id ?? null
    // 把服务端给出的冲突字段回传给工作台，用于给对应列打标记。
    emit('conflicts', [...new Set(pendingOrders.value.flatMap((order) => order.conflict_fields))])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '站点冲突读取失败'
  }
})
</script>
