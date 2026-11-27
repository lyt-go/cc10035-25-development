/** 站点归属确认接口封装：统一返回结果，错误信息直接来自服务端。 */
import { request } from './client'
import type {
  ActionOutcome,
  AttributionOrder,
  AttributionStats,
  DetectionResult,
  OrderStatus,
  Site,
} from '@/domain/siteAttribution'

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
  const payload = (await response.json()) as T
  return payload
}

export async function loadSites(): Promise<Site[]> {
  const response = await request('/api/site-attribution/sites')
  if (!response.ok) throw new Error('站点与规则读取失败')
  const payload = (await response.json()) as { items: Site[] }
  return payload.items
}

export async function loadStats(): Promise<AttributionStats> {
  const response = await request('/api/site-attribution/stats')
  if (!response.ok) throw new Error('归属确认统计读取失败')
  return (await response.json()) as AttributionStats
}

export async function loadOrders(status?: OrderStatus | ''): Promise<AttributionOrder[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  const response = await request(`/api/site-attribution/orders${query}`)
  if (!response.ok) throw new Error('归属确认单读取失败')
  const payload = (await response.json()) as { items: AttributionOrder[] }
  return payload.items
}

export async function loadOrder(orderId: number): Promise<AttributionOrder> {
  const response = await request(`/api/site-attribution/orders/${orderId}`)
  if (!response.ok) throw new Error(`归属确认单 ${orderId} 读取失败`)
  return (await response.json()) as AttributionOrder
}

export function detect(rawHex: string, identifier = 'A1'): Promise<DetectionResult> {
  return postJson<DetectionResult>('/api/site-attribution/detect', {
    raw_hex: rawHex,
    identifier,
  })
}

export function selectFrame(
  orderId: number,
  frameId: number,
  body: {
    site_code: string
    decode_rule_code: string
    route_rule_code?: string | null
    expected_version?: number
    operator?: string
    remark?: string
  },
): Promise<ActionOutcome> {
  return postJson<ActionOutcome>(
    `/api/site-attribution/orders/${orderId}/frames/${frameId}/select`,
    body,
  )
}

export function dispatchFrame(
  orderId: number,
  frameId: number,
  body: { expected_version?: number; request_id?: string; operator?: string },
): Promise<ActionOutcome> {
  return postJson<ActionOutcome>(
    `/api/site-attribution/orders/${orderId}/frames/${frameId}/dispatch`,
    body,
  )
}

export function holdFrame(
  orderId: number,
  frameId: number,
  body: { expected_version?: number; remark?: string },
): Promise<ActionOutcome> {
  return postJson<ActionOutcome>(
    `/api/site-attribution/orders/${orderId}/frames/${frameId}/hold`,
    body,
  )
}

export function setSiteStatus(
  siteCode: string,
  status: string,
  reason = '',
): Promise<{ ok: boolean; message: string; affected_rules?: number }> {
  return postJson(`/api/site-attribution/sites/${siteCode}/status`, { status, reason })
}

export function approveRule(
  siteCode: string,
  ruleCode: string,
  basis?: string,
): Promise<{ ok: boolean; message: string }> {
  return postJson(`/api/site-attribution/sites/${siteCode}/rules/${ruleCode}/approve`, { basis })
}
