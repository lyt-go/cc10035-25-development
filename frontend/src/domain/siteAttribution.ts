/** 站点归属确认的领域类型：与后端 /api/site-attribution 返回结构一一对应。 */

export type SiteStatus = '启用中' | '已停用'
export type RuleStatus = '已核准' | '草稿' | '已停用'
export type FrameStatus =
  | '待核对'
  | '已选定'
  | '在途'
  | '已投递'
  | '待再次核对'
  | '留待核对'
export type OrderStatus = '待核对' | '办理中' | '版本冲突' | '已完成'

export type DecodePreview = {
  ok: boolean
  message: string
  site_code?: string
  rule_code?: string
  rule_version?: number
  protocol_type?: string
  identifier?: string
  payload_hex?: string
  field_offset?: number
  field_length?: number
  field_hex?: string
  data_type?: string
  byte_order?: string
  value?: string | number
  checksum_type?: string
  checksum_valid?: boolean
}

export type Candidate = {
  site_code: string
  site_name: string
  site_status: SiteStatus
  site_version: number
  rule_code: string
  rule_status: RuleStatus
  rule_version: number
  protocol_type: string
  identifier: string
  offset: string
  length: string
  data_type: string
  byte_order: string
  checksum: string
  basis: string
  approved_by: string
  approved_at: string
  route_rule: string | null
  target_topic: string | null
  eligible: boolean
  preview: DecodePreview
}

/** 服务端把站点冲突映射到具体字段，前端按 field 对应到列。 */
export type FieldConflict = {
  field: string
  sites: string[]
  values: { site_code: string; site_name: string; rule_code: string; value: string }[]
}

export type SelectionSnapshot = {
  site_code: string
  site_name: string
  site_version: number
  decode_rule_code: string
  decode_rule_version: number
  decode_rule_basis: string
  decode_rule_approved_by: string
  decode_rule_approved_at: string
  route_rule_code: string
  route_rule_version: number
  route_rule_basis: string
  selected_at: string
  selected_by: string
}

export type Selection = {
  site_code: string
  site_name: string
  decode_rule_code: string
  route_rule_code: string
  operator: string
  remark: string
  selected_at: string
  basis: string
  snapshot: SelectionSnapshot
  stale: boolean
}

export type FrameConflict = {
  code: string
  message: string
  reasons: string[]
  detected_at: string
  snapshot: SelectionSnapshot | null
  previous_message_count: number
}

export type TrialMessage = {
  id: number
  message_id: string
  frame_id: number
  frame_no?: string
  帧编号: string
  order_id: number
  request_id: string
  站点编号: string
  站点名称: string
  规则编号: string
  路由规则: string
  目标Topic: string
  解码值: string | number
  解码字段hex: string
  解释依据: string
  快照: SelectionSnapshot
  投递人: string
  投递时间: string
}

export type AttributionFrame = {
  id: number
  帧编号: string
  order_id: number
  报文标识: string
  报文内容: string
  源Topic: string
  status: FrameStatus
  version: number
  selected: Selection | null
  conflict: FrameConflict | null
  message: TrialMessage | null
  delivery_eligible: boolean
  detection: {
    candidate_count: number
    eligible_count: number
    ambiguous: boolean
    summary: string
  }
  candidates: Candidate[]
  field_conflicts: FieldConflict[]
  updated_at: string
}

export type FrameCounts = {
  pending: number
  selected: number
  in_flight: number
  delivered: number
  recheck: number
  held: number
}

export type AttributionOrder = {
  id: number
  单据编号: string
  标题: string
  status: OrderStatus
  version: number
  created_at: string
  updated_at: string
  frame_total: number
  frame_counts: FrameCounts
  needs_attention?: number
  /** 服务端算好的字段级冲突，供工作台直接展示。 */
  conflict_fields: string[]
  conflict_sites: string[]
  frames?: AttributionFrame[]
}

export type AttributionStats = {
  orders: number
  frames: number
  pending: number
  in_flight: number
  delivered: number
  conflicts: number
  held: number
  messages: number
}

export type SiteRule = {
  规则编号: string
  站点编号: string
  协议类型?: string
  报文标识: string
  字段偏移?: string
  字段长度?: string
  数据类型?: string
  字节序?: string
  校验方式?: string
  匹配Topic?: string
  目标Topic?: string
  转发方式?: string
  status: RuleStatus
  version: number
  核准依据: string
  核准人: string
  核准时间: string
}

export type Site = {
  站点编号: string
  站点名称: string
  区域: string
  协议类型: string
  status: SiteStatus
  version: number
  停用原因: string
  更新时间: string
  decode_rules: SiteRule[]
  route_rules: SiteRule[]
}

export type ActionOutcome = {
  ok: boolean
  code?: string
  message: string
  status_code?: number
  frame_id?: number
  帧编号?: string
  status?: FrameStatus
  version?: number
  selected?: Selection | null
  message_id?: string | null
  duplicate?: boolean
  delivery_eligible?: boolean
  reasons?: string[]
  trial_message?: TrialMessage | null
  frame?: AttributionFrame
  conflict?: FrameConflict | null
}

export type DetectionResult = {
  identifier: string
  candidate_count: number
  eligible_count: number
  ambiguous: boolean
  adopted_rule: { site_code: string; rule_code: string; reason: string } | null
  summary: string
  candidates: Candidate[]
  field_conflicts: FieldConflict[]
}

/** 候选对比表里可对比的规则字段。 */
export const CANDIDATE_FIELDS: { field: string; label: (c: Candidate) => string }[] = [
  { field: '协议类型', label: (c) => c.protocol_type },
  { field: '报文标识', label: (c) => c.identifier },
  { field: '字段偏移', label: (c) => c.offset },
  { field: '字段长度', label: (c) => c.length },
  { field: '数据类型', label: (c) => c.data_type },
  { field: '字节序', label: (c) => c.byte_order },
  { field: '校验方式', label: (c) => c.checksum },
]

export function conflictFor(frame: { field_conflicts: FieldConflict[] }, field: string) {
  return frame.field_conflicts.find((item) => item.field === field) ?? null
}
