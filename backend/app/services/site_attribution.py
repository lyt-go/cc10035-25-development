"""站点归属确认领域服务：解决同一报文标识被多个站点协议候选命中的归属问题。

背景
----
协议探测对一条报文只会采用一个命中；当东站、西站各自登记了相同报文标识
（例如 ``A1``）时，探测结果本身不足以证明这条帧属于哪个站点。维护员过去没有
可查证、可签发、可追责的入口。本服务提供「归属确认单」：

* 一条报文帧只有被维护员明确选定「站点 + 解码规则 + 路由规则」后才取得投递资格；
* 解码与路由都只使用被选中站点自己的规则，两个站点可以复用标识，但不能复用
  对方的解码方式；
* 真正投递（试投）时再次校验所选解释的依据：站点、规则均须处于已核准/启用
  状态，且版本与选定时的快照一致，否则视为版本冲突，不产生任何消息；
* 同一帧重复提交投递不会生成第二条消息；同一确认单里的其他待核帧保持原状；
* 发生版本冲突的帧重新进入「待再次核对」，重新打开旧单仍可为它继续选择。

数据都放在服务实例内存里，和仓库里其他领域服务保持同一实现风格。
"""
from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone
from typing import Any

CST = timezone(timedelta(hours=8))

# 报文帧状态
FRAME_PENDING = "待核对"
FRAME_SELECTED = "已选定"
FRAME_IN_FLIGHT = "在途"
FRAME_DELIVERED = "已投递"
FRAME_RECHECK = "待再次核对"
FRAME_HELD = "留待核对"

# 确认单状态
ORDER_PENDING = "待核对"
ORDER_PROCESSING = "办理中"
ORDER_CONFLICT = "版本冲突"
ORDER_DONE = "已完成"

# 站点/规则状态
SITE_ACTIVE = "启用中"
SITE_STOPPED = "已停用"
RULE_APPROVED = "已核准"
RULE_DRAFT = "草稿"
RULE_STOPPED = "已停用"

CONFLICT_FIELDS = ["协议类型", "字段偏移", "字段长度", "数据类型", "字节序", "校验方式"]


def _now() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


class SiteAttributionService:
    """归属确认单、待核帧、站点规则与试投消息的领域服务。"""

    MODULE = "site_attribution"
    ENTITY = "归属确认单"

    def __init__(self) -> None:
        self.reset()

    # ------------------------------------------------------------------
    # 种子数据
    # ------------------------------------------------------------------
    def reset(self) -> None:
        """恢复演示数据；测试和本地排查时可重新播种子。"""
        self.sites: dict[str, dict[str, Any]] = {
            "SITE-P": {
                "站点编号": "SITE-P",
                "站点名称": "东站",
                "区域": "东区",
                "协议类型": "MODBUS-P",
                "status": SITE_ACTIVE,
                "version": 1,
                "停用原因": "",
                "更新时间": "2026-11-26T09:00:00+08:00",
            },
            "SITE-Q": {
                "站点编号": "SITE-Q",
                "站点名称": "西站",
                "区域": "西区",
                "协议类型": "MODBUS-Q",
                "status": SITE_ACTIVE,
                "version": 1,
                "停用原因": "",
                "更新时间": "2026-11-26T09:00:00+08:00",
            },
        }
        self.decode_rules: dict[str, dict[str, Any]] = {
            "DR-P-A1": {
                "规则编号": "DR-P-A1",
                "站点编号": "SITE-P",
                "协议类型": "MODBUS-P",
                "报文标识": "A1",
                "字段偏移": "0",
                "字段长度": "2",
                "数据类型": "uint16",
                "字节序": "big",
                "校验方式": "none",
                "status": RULE_APPROVED,
                "version": 1,
                "核准依据": "东站 2026-10 现场报文勘察记录 P-A1-01",
                "核准人": "协议组-林工",
                "核准时间": "2026-10-18T14:20:00+08:00",
            },
            "DR-Q-A1": {
                "规则编号": "DR-Q-A1",
                "站点编号": "SITE-Q",
                "协议类型": "MODBUS-Q",
                "报文标识": "A1",
                "字段偏移": "4",
                "字段长度": "2",
                "数据类型": "uint16",
                "字节序": "little",
                "校验方式": "none",
                "status": RULE_APPROVED,
                "version": 1,
                "核准依据": "西站报文台账 Q-A1-07（现场复核签字）",
                "核准人": "协议组-周工",
                "核准时间": "2026-10-21T10:05:00+08:00",
            },
        }
        self.route_rules: dict[str, dict[str, Any]] = {
            "RT-P-A1": {
                "规则编号": "RT-P-A1",
                "站点编号": "SITE-P",
                "匹配Topic": "plant/A1/data",
                "目标Topic": "east/normalized/A1",
                "转发方式": "direct",
                "status": RULE_APPROVED,
                "version": 1,
                "核准依据": "东站接入联调单 RT-P-03",
                "核准人": "接入组-陈工",
                "核准时间": "2026-10-19T09:40:00+08:00",
            },
            "RT-Q-A1": {
                "规则编号": "RT-Q-A1",
                "站点编号": "SITE-Q",
                "匹配Topic": "plant/A1/data",
                "目标Topic": "west/normalized/A1",
                "转发方式": "direct",
                "status": RULE_APPROVED,
                "version": 1,
                "核准依据": "西站接入联调单 RT-Q-11",
                "核准人": "接入组-邓工",
                "核准时间": "2026-10-22T16:10:00+08:00",
            },
        }
        self.orders: dict[int, dict[str, Any]] = {
            1: {
                "id": 1,
                "单据编号": "ATTR-20261126-001",
                "标题": "A1 报文归属核对",
                "status": ORDER_PENDING,
                "version": 1,
                "created_at": "2026-11-26T09:10:00+08:00",
                "updated_at": "2026-11-26T09:10:00+08:00",
            },
            2: {
                "id": 2,
                "单据编号": "ATTR-20261126-002",
                "标题": "东站 A1 独立试投复核",
                "status": ORDER_PENDING,
                "version": 1,
                "created_at": "2026-11-26T09:25:00+08:00",
                "updated_at": "2026-11-26T09:25:00+08:00",
            },
            3: {
                "id": 3,
                "单据编号": "ATTR-20261125-003",
                "标题": "西站 A1 在途试投续办",
                "status": ORDER_PROCESSING,
                "version": 1,
                "created_at": "2026-11-25T17:40:00+08:00",
                "updated_at": "2026-11-26T08:55:00+08:00",
            },
        }
        self.frames: dict[int, dict[str, Any]] = {}
        seeds = [
            (1, 1, "FRM-0001", "41310A1B00001122", "plant/A1/data", "2026-11-26T09:10:00+08:00"),
            (2, 1, "FRM-0002", "4131030405060708", "plant/A1/data", "2026-11-26T09:11:00+08:00"),
            (3, 2, "FRM-0003", "41310A1B00001122", "plant/A1/data", "2026-11-26T09:25:00+08:00"),
            (4, 3, "FRM-0004", "41310A1B00001122", "plant/A1/data", "2026-11-25T17:40:00+08:00"),
        ]
        for frame_id, order_id, code, raw, topic, created_at in seeds:
            frame = self._new_frame(order_id, code, raw, topic, created_at)
            frame["id"] = frame_id
            self.frames[frame_id] = frame
        # 第 3 单的帧在站点停用之前已由值班员选定西站，属于「在途」帧。
        self._apply_selection(
            self.frames[4], "SITE-Q", "DR-Q-A1", "RT-Q-A1",
            operator="值班员-许工", remark="西站现场试投前指定",
            now="2026-11-25T17:42:00+08:00",
        )
        self.frames[4]["status"] = FRAME_IN_FLIGHT
        self.messages: dict[int, dict[str, Any]] = {}

    def _new_frame(
        self, order_id: int, code: str, raw: str, topic: str, created_at: str
    ) -> dict[str, Any]:
        return {
            "id": 0,
            "帧编号": code,
            "order_id": order_id,
            "报文标识": "A1",
            "报文内容": raw,
            "源Topic": topic,
            "status": FRAME_PENDING,
            "version": 1,
            "selected": None,
            "conflict": None,
            "message_id": None,
            "备注": "",
            "created_at": created_at,
            "updated_at": created_at,
        }

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def list_sites(self) -> list[dict[str, Any]]:
        """站点及其当前有效的协议规则，供页面核对候选归属。"""
        result = []
        for site in sorted(self.sites.values(), key=lambda item: item["站点编号"]):
            code = site["站点编号"]
            result.append({
                **site,
                "decode_rules": [
                    dict(rule) for rule in self.decode_rules.values()
                    if rule["站点编号"] == code
                ],
                "route_rules": [
                    dict(rule) for rule in self.route_rules.values()
                    if rule["站点编号"] == code
                ],
            })
        return result

    def list_orders(self, status: str | None = None) -> list[dict[str, Any]]:
        orders = sorted(self.orders.values(), key=lambda item: item["id"])
        if status:
            orders = [order for order in orders if order["status"] == status]
        return [self._order_summary(order) for order in orders]

    def get_order(self, order_id: int) -> dict[str, Any] | None:
        order = self.orders.get(order_id)
        if order is None:
            return None
        frames = self._frames_of(order_id)
        counts = self._frame_counts(frames)
        return {
            **order,
            "frame_total": len(frames),
            "frame_counts": counts,
            "frames": [self._frame_detail(frame) for frame in frames],
        }

    def stats(self) -> dict[str, int]:
        frames = list(self.frames.values())
        return {
            "orders": len(self.orders),
            "frames": len(frames),
            "pending": sum(1 for f in frames if f["status"] == FRAME_PENDING),
            "in_flight": sum(
                1 for f in frames if f["status"] in (FRAME_SELECTED, FRAME_IN_FLIGHT)
            ),
            "delivered": sum(1 for f in frames if f["status"] == FRAME_DELIVERED),
            "conflicts": sum(1 for f in frames if f["status"] == FRAME_RECHECK),
            "held": sum(1 for f in frames if f["status"] == FRAME_HELD),
            "messages": len(self.messages),
        }

    def detect(self, raw_hex: str, identifier: str = "A1") -> dict[str, Any]:
        """协议探测：按报文标识找出所有站点候选。

        探测只给出预选结果：仅当只有一个可投递候选时才给出 ``adopted_rule``，
        且该预选不授予投递资格——投递资格必须由维护员在确认页确定站点与规则。
        """
        candidates = self._build_candidates(raw_hex, identifier)
        eligible = [item for item in candidates if item["eligible"]]
        adopted = None
        if len(eligible) == 1:
            adopted = {
                "site_code": eligible[0]["site_code"],
                "rule_code": eligible[0]["rule_code"],
                "reason": f"仅命中{eligible[0]['site_name']}的已核准规则，作为预选",
            }
        return {
            "identifier": identifier,
            "candidate_count": len(candidates),
            "eligible_count": len(eligible),
            "ambiguous": len(eligible) > 1,
            "adopted_rule": adopted,
            "summary": (
                f"探到 {len(eligible)} 个站点命中，候选冲突，需人工确认归属"
                if len(eligible) > 1
                else ("未找到可投递候选，留待核对" if not eligible else "仅一个命中，可预选，投递前仍需确认")
            ),
            "candidates": candidates,
            "field_conflicts": self._field_conflicts(candidates),
        }

    # ------------------------------------------------------------------
    # 维护动作
    # ------------------------------------------------------------------
    def select(
        self,
        order_id: int,
        frame_id: int,
        *,
        site_code: str,
        decode_rule_code: str,
        route_rule_code: str | None = None,
        expected_version: int | None = None,
        operator: str = "值班员",
        remark: str = "",
    ) -> dict[str, Any]:
        """为帧确定站点与规则，选定后才取得投递资格。"""
        frame, error = self._require_frame(order_id, frame_id)
        if error:
            return error
        if frame["message_id"]:
            return self._conflict_response(frame, "ALREADY_DELIVERED", "该帧已投递，不能改选解释")
        if expected_version is not None and int(expected_version) != int(frame["version"]):
            return self._conflict_response(
                frame, "FRAME_VERSION_MISMATCH",
                f"帧版本已变化（提交 {expected_version}，当前 {frame['version']}），请刷新后重选",
                mark=False,
            )

        site = self.sites.get(site_code)
        if site is None:
            return self._error(404, "SITE_NOT_FOUND", f"站点 {site_code} 不存在")
        rule = self.decode_rules.get(decode_rule_code)
        if rule is None:
            return self._error(404, "RULE_NOT_FOUND", f"解码规则 {decode_rule_code} 不存在")
        if rule["站点编号"] != site_code:
            return self._error(
                409, "RULE_SITE_MISMATCH",
                f"解码规则 {decode_rule_code} 属于 {rule['站点编号']}，不能用于 {site_code}",
            )
        if rule["报文标识"] != frame["报文标识"]:
            return self._error(
                409, "IDENTIFIER_MISMATCH",
                f"解码规则标识 {rule['报文标识']} 与帧标识 {frame['报文标识']} 不一致",
            )

        # 站点必须先满足启用条件，否则不能继续沿用该站解释。
        if site["status"] != SITE_ACTIVE:
            return self._error(
                409, "SITE_UNAVAILABLE",
                f"{site['站点名称']}当前为{site['status']}，不能选择其规则",
            )
        if rule["status"] != RULE_APPROVED:
            return self._error(
                409, "RULE_NOT_APPROVED",
                f"解码规则 {decode_rule_code} 当前为{rule['status']}，不具备有效核准依据",
            )

        route = self._pick_route(
            site_code, route_rule_code, frame["源Topic"]
        )
        if isinstance(route, dict) and route.get("__error"):
            return self._error(409, "ROUTE_NOT_APPROVED", route["__error"])

        preview = self._decode(frame["报文内容"], rule)
        if not preview.get("ok"):
            return self._error(
                422, "DECODE_FAILED",
                f"按 {decode_rule_code} 无法解码该帧：{preview.get('message', '未知原因')}",
            )

        signature = (site_code, decode_rule_code, route["规则编号"], int(rule["version"]),
                     int(site["version"]), int(route["version"]))
        previous = frame.get("selected")
        if (
            previous
            and frame.get("signature") == signature
            and frame["status"] not in (FRAME_RECHECK, FRAME_HELD)
        ):
            # 重复点提交：保持同一解释，不推进版本、不产生额外状态。
            return self._ok(frame, "站点与规则已确认，无需重复提交", extra={
                "delivery_eligible": self._delivery_eligible(frame),
                "duplicate": True,
            })

        self._apply_selection(
            frame, site_code, decode_rule_code, route["规则编号"],
            operator=operator, remark=remark,
        )
        frame["version"] = int(frame["version"]) + 1
        frame["status"] = FRAME_SELECTED
        frame["conflict"] = None
        frame["updated_at"] = _now()
        self._refresh_order(frame["order_id"])
        return self._ok(frame, "站点与规则已确认，该帧取得投递资格", extra={
            "delivery_eligible": True,
            "duplicate": False,
        })

    def dispatch(
        self,
        order_id: int,
        frame_id: int,
        *,
        expected_version: int | None = None,
        request_id: str | None = None,
        operator: str = "值班员",
    ) -> dict[str, Any]:
        """真正投递前的二次校验：解释必须有可追溯且当前有效的核准依据。

        * 没有确定站点与规则的帧没有投递资格；
        * 站点停用、规则停用或规则版本变化都会造成版本冲突，不产生消息；
        * 同一帧重复提交返回同一条消息，不会生成第二条。
        """
        frame, error = self._require_frame(order_id, frame_id)
        if error:
            return error

        existing = self._message_of(frame)
        if existing is not None:
            # 幂等：重复点击提交仍指向第一次生成的消息。
            return self._ok(frame, "该帧已投递，返回既有消息", extra={
                "trial_message": self._message_detail(existing),
                "duplicate": True,
            })

        if frame["status"] == FRAME_HELD:
            return self._error(409, "FRAME_HELD", "该帧已留待核对，请重新选择后再试投")
        if not frame.get("selected"):
            return self._error(
                409, "NO_DELIVERY_ELIGIBILITY",
                "该帧尚未由维护员确定站点与规则，不具备投递资格，留待核对",
            )
        if expected_version is not None and int(expected_version) != int(frame["version"]):
            return self._conflict_response(
                frame, "FRAME_VERSION_MISMATCH",
                f"帧版本已变化（提交 {expected_version}，当前 {frame['version']}）",
                mark=False,
            )

        reasons = self._basis_problems(frame)
        if reasons:
            return self._conflict_response(
                frame, "VERSION_CONFLICT",
                "所选解释的核准依据已失效，已转入待再次核对，未产生消息",
                reasons=reasons,
            )

        selected = frame["selected"]
        rule = self.decode_rules[selected["decode_rule_code"]]
        route = self.route_rules[selected["route_rule_code"]]
        preview = self._decode(frame["报文内容"], rule)
        if not preview.get("ok"):
            return self._conflict_response(
                frame, "DECODE_FAILED",
                f"投递前复核解码失败：{preview.get('message', '未知原因')}",
                reasons=[preview.get("message", "解码失败")],
            )

        message_uid = f"TRIAL-{frame['帧编号']}"
        message = {
            "id": len(self.messages) + 1,
            "message_id": message_uid,
            "frame_id": frame["id"],
            "帧编号": frame["帧编号"],
            "order_id": frame["order_id"],
            "request_id": request_id or "",
            "站点编号": selected["site_code"],
            "站点名称": self.sites[selected["site_code"]]["站点名称"],
            "规则编号": selected["decode_rule_code"],
            "路由规则": selected["route_rule_code"],
            "目标Topic": route["目标Topic"],
            "解码值": preview["value"],
            "解码字段hex": preview["field_hex"],
            "解释依据": selected["basis"],
            "快照": selected["snapshot"],
            "投递人": operator,
            "投递时间": _now(),
        }
        self.messages[frame["id"]] = message
        frame["message_id"] = message_uid
        frame["status"] = FRAME_DELIVERED
        frame["version"] = int(frame["version"]) + 1
        frame["updated_at"] = _now()
        self._refresh_order(frame["order_id"])
        return self._ok(frame, f"试投已投递到 {route['目标Topic']}", extra={
            "trial_message": self._message_detail(message),
            "duplicate": False,
        })

    def hold(
        self,
        order_id: int,
        frame_id: int,
        *,
        expected_version: int | None = None,
        remark: str = "",
    ) -> dict[str, Any]:
        """把不明确的帧留待核对；同单其他帧不受影响。"""
        frame, error = self._require_frame(order_id, frame_id)
        if error:
            return error
        if frame["message_id"]:
            return self._error(409, "ALREADY_DELIVERED", "该帧已投递，不能再次留待核对")
        if expected_version is not None and int(expected_version) != int(frame["version"]):
            return self._conflict_response(
                frame, "FRAME_VERSION_MISMATCH",
                f"帧版本已变化（提交 {expected_version}，当前 {frame['version']}）",
                mark=False,
            )
        if frame["status"] == FRAME_HELD:
            return self._ok(frame, "该帧已留待核对", extra={"duplicate": True})
        frame["status"] = FRAME_HELD
        frame["version"] = int(frame["version"]) + 1
        frame["备注"] = remark or frame.get("备注", "")
        frame["updated_at"] = _now()
        self._refresh_order(frame["order_id"])
        return self._ok(frame, "该帧留待核对，仍保留在原确认单", extra={"duplicate": False})

    def set_site_status(
        self, site_code: str, status: str, *, reason: str = "", operator: str = "值班员"
    ) -> dict[str, Any]:
        """停用/启用站点；停用会推进站点与规则版本，使在途快照失效。"""
        site = self.sites.get(site_code)
        if site is None:
            return self._error(404, "SITE_NOT_FOUND", f"站点 {site_code} 不存在")
        if status not in (SITE_ACTIVE, SITE_STOPPED):
            return self._error(400, "INVALID_STATUS", f"不支持的站点状态：{status}")
        if site["status"] == status:
            return {
                "ok": True,
                "message": f"站点 {site['站点名称']} 已是{status}",
                "site": dict(site),
                "affected_rules": 0,
            }

        site["status"] = status
        site["version"] = int(site["version"]) + 1
        site["停用原因"] = reason if status == SITE_STOPPED else ""
        site["更新时间"] = _now()
        affected = 0
        if status == SITE_STOPPED:
            for rule in list(self.decode_rules.values()) + list(self.route_rules.values()):
                if rule["站点编号"] == site_code and rule["status"] != RULE_STOPPED:
                    rule["status"] = RULE_STOPPED
                    rule["version"] = int(rule["version"]) + 1
                    affected += 1
        else:
            # 重新启用站点不会自动恢复规则，规则仍需重新核准。
            affected = 0
        return {
            "ok": True,
            "message": (
                f"站点 {site['站点名称']} 已停用，{affected} 条规则随之失效"
                if status == SITE_STOPPED
                else f"站点 {site['站点名称']} 已启用，规则需重新核准后才能使用"
            ),
            "site": dict(site),
            "affected_rules": affected,
            "operator": operator,
        }

    def approve_rule(
        self, site_code: str, rule_code: str, *, basis: str | None = None,
        operator: str = "协议组",
    ) -> dict[str, Any]:
        """重新核准站点规则：保留可追溯依据，并推进规则版本。"""
        site = self.sites.get(site_code)
        if site is None:
            return self._error(404, "SITE_NOT_FOUND", f"站点 {site_code} 不存在")
        if site["status"] != SITE_ACTIVE:
            return self._error(409, "SITE_UNAVAILABLE", "站点未启用，不能核准其规则")
        rule = self.decode_rules.get(rule_code) or self.route_rules.get(rule_code)
        if rule is None:
            return self._error(404, "RULE_NOT_FOUND", f"规则 {rule_code} 不存在")
        if rule["站点编号"] != site_code:
            return self._error(409, "RULE_SITE_MISMATCH", "规则与站点不匹配")
        if basis:
            rule["核准依据"] = basis
        rule["status"] = RULE_APPROVED
        rule["version"] = int(rule["version"]) + 1
        rule["核准人"] = operator
        rule["核准时间"] = _now()
        return {"ok": True, "message": f"规则 {rule_code} 已重新核准", "rule": dict(rule)}

    # ------------------------------------------------------------------
    # 内部结构
    # ------------------------------------------------------------------
    def _frames_of(self, order_id: int) -> list[dict[str, Any]]:
        return sorted(
            (frame for frame in self.frames.values() if frame["order_id"] == order_id),
            key=lambda item: item["id"],
        )

    def _frame_counts(self, frames: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "pending": sum(1 for f in frames if f["status"] == FRAME_PENDING),
            "selected": sum(1 for f in frames if f["status"] == FRAME_SELECTED),
            "in_flight": sum(1 for f in frames if f["status"] == FRAME_IN_FLIGHT),
            "delivered": sum(1 for f in frames if f["status"] == FRAME_DELIVERED),
            "recheck": sum(1 for f in frames if f["status"] == FRAME_RECHECK),
            "held": sum(1 for f in frames if f["status"] == FRAME_HELD),
        }

    def _order_summary(self, order: dict[str, Any]) -> dict[str, Any]:
        frames = self._frames_of(order["id"])
        counts = self._frame_counts(frames)
        conflict_fields: list[str] = []
        conflict_sites: list[str] = []
        for frame in frames:
            candidates = self._build_candidates(frame["报文内容"], frame["报文标识"])
            if len([item for item in candidates if item["eligible"]]) < 2:
                continue
            for item in self._field_conflicts(candidates):
                if item["field"] not in conflict_fields:
                    conflict_fields.append(item["field"])
                for site_name in item["sites"]:
                    if site_name not in conflict_sites:
                        conflict_sites.append(site_name)
        return {
            **order,
            "frame_total": len(frames),
            "frame_counts": counts,
            "needs_attention": counts["recheck"] + counts["pending"],
            "conflict_fields": conflict_fields,
            "conflict_sites": conflict_sites,
        }

    def _frame_detail(self, frame: dict[str, Any]) -> dict[str, Any]:
        candidates = self._build_candidates(frame["报文内容"], frame["报文标识"])
        eligible = [item for item in candidates if item["eligible"]]
        selected = frame.get("selected")
        return {
            "id": frame["id"],
            "帧编号": frame["帧编号"],
            "order_id": frame["order_id"],
            "报文标识": frame["报文标识"],
            "报文内容": frame["报文内容"],
            "源Topic": frame["源Topic"],
            "status": frame["status"],
            "version": frame["version"],
            "selected": selected,
            "conflict": frame.get("conflict"),
            "message": self._message_detail(self._message_of(frame)),
            "delivery_eligible": self._delivery_eligible(frame),
            "detection": {
                "candidate_count": len(candidates),
                "eligible_count": len(eligible),
                "ambiguous": len(eligible) > 1,
                "summary": (
                    f"探到 {len(eligible)} 个站点命中，存在候选冲突，需人工确认"
                    if len(eligible) > 1
                    else ("未找到可投递候选，应留待核对" if not eligible else "仅一个候选命中")
                ),
            },
            "candidates": candidates,
            "field_conflicts": self._field_conflicts(candidates),
            "updated_at": frame["updated_at"],
        }

    def _build_candidates(self, raw_hex: str, identifier: str) -> list[dict[str, Any]]:
        """列出同标识的全部站点规则，并逐站点独立解码，绝不跨站套用。"""
        candidates = []
        for rule in self.decode_rules.values():
            if rule["报文标识"] != identifier:
                continue
            site = self.sites.get(rule["站点编号"])
            if site is None:
                continue
            preview = self._decode(raw_hex, rule)
            route = self._pick_route(site["站点编号"], None, "plant/A1/data")
            candidates.append({
                "site_code": site["站点编号"],
                "site_name": site["站点名称"],
                "site_status": site["status"],
                "site_version": site["version"],
                "rule_code": rule["规则编号"],
                "rule_status": rule["status"],
                "rule_version": rule["version"],
                "protocol_type": rule["协议类型"],
                "identifier": rule["报文标识"],
                "offset": rule["字段偏移"],
                "length": rule["字段长度"],
                "data_type": rule["数据类型"],
                "byte_order": rule["字节序"],
                "checksum": rule["校验方式"],
                "basis": rule["核准依据"],
                "approved_by": rule["核准人"],
                "approved_at": rule["核准时间"],
                "route_rule": route.get("规则编号") if isinstance(route, dict) and not route.get("__error") else None,
                "target_topic": route.get("目标Topic") if isinstance(route, dict) and not route.get("__error") else None,
                "eligible": (
                    site["status"] == SITE_ACTIVE
                    and rule["status"] == RULE_APPROVED
                    and preview.get("ok", False)
                ),
                "preview": preview,
            })
        candidates.sort(key=lambda item: item["site_code"])
        return candidates

    def _field_conflicts(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把候选差异映射回字段，供工作台在对应列上显示冲突标记。

        返回结构由服务端计算，前端只负责把 ``field`` 对应到字段列。
        """
        if len(candidates) < 2:
            return []
        conflicts = []
        for field in CONFLICT_FIELDS:
            values = [
                {
                    "site_code": item["site_code"],
                    "site_name": item["site_name"],
                    "rule_code": item["rule_code"],
                    "value": str(item[{
                        "协议类型": "protocol_type",
                        "字段偏移": "offset",
                        "字段长度": "length",
                        "数据类型": "data_type",
                        "字节序": "byte_order",
                        "校验方式": "checksum",
                    }[field]]),
                }
                for item in candidates
            ]
            if len({item["value"] for item in values}) > 1:
                conflicts.append({
                    "field": field,
                    "values": values,
                    "sites": [item["site_name"] for item in values],
                })
        return conflicts

    def _pick_route(
        self, site_code: str, route_code: str | None, source_topic: str
    ) -> dict[str, Any]:
        if route_code:
            route = self.route_rules.get(route_code)
            if route is None:
                return {"__error": f"路由规则 {route_code} 不存在"}
            if route["站点编号"] != site_code:
                return {"__error": f"路由规则 {route_code} 不属于站点 {site_code}"}
            if route["status"] != RULE_APPROVED:
                return {"__error": f"路由规则 {route_code} 当前为{route['status']}，无有效核准依据"}
            return route
        for route in self.route_rules.values():
            if route["站点编号"] == site_code and route["status"] == RULE_APPROVED:
                if self._topic_match(source_topic, route["匹配Topic"]):
                    return route
        return {"__error": f"站点 {site_code} 没有匹配 {source_topic} 的已核准路由规则"}

    @staticmethod
    def _topic_match(source: str, pattern: str) -> bool:
        source_parts = source.split("/")
        pattern_parts = pattern.split("/")
        for index, part in enumerate(pattern_parts):
            if part == "#":
                return index <= len(source_parts)
            if index >= len(source_parts):
                return False
            if part == "+":
                continue
            if part != source_parts[index]:
                return False
        return len(source_parts) == len(pattern_parts)

    def _apply_selection(
        self,
        frame: dict[str, Any],
        site_code: str,
        decode_rule_code: str,
        route_rule_code: str,
        *,
        operator: str,
        remark: str,
        now: str | None = None,
    ) -> None:
        site = self.sites[site_code]
        rule = self.decode_rules[decode_rule_code]
        route = self.route_rules[route_rule_code]
        selection_time = now or _now()
        basis_parts = [
            f"{site['站点名称']}站点版本 v{site['version']}",
            f"解码规则 {decode_rule_code} v{rule['version']}（核准人 {rule['核准人']}，{rule['核准时间']}）",
            f"路由规则 {route_rule_code} v{route['version']}",
        ]
        snapshot = {
            "site_code": site_code,
            "site_name": site["站点名称"],
            "site_version": int(site["version"]),
            "decode_rule_code": decode_rule_code,
            "decode_rule_version": int(rule["version"]),
            "decode_rule_basis": rule["核准依据"],
            "decode_rule_approved_by": rule["核准人"],
            "decode_rule_approved_at": rule["核准时间"],
            "route_rule_code": route_rule_code,
            "route_rule_version": int(route["version"]),
            "route_rule_basis": route["核准依据"],
            "selected_at": selection_time,
            "selected_by": operator,
        }
        frame["selected"] = {
            "site_code": site_code,
            "site_name": site["站点名称"],
            "decode_rule_code": decode_rule_code,
            "route_rule_code": route_rule_code,
            "operator": operator,
            "remark": remark,
            "selected_at": selection_time,
            "basis": "；".join(basis_parts),
            "snapshot": snapshot,
            "stale": False,
        }
        # 签名只在服务内部用于判断重复提交，不对外暴露。
        frame["signature"] = (
            site_code, decode_rule_code, route_rule_code,
            int(rule["version"]), int(site["version"]), int(route["version"]),
        )

    def _basis_problems(self, frame: dict[str, Any]) -> list[str]:
        selected = frame.get("selected") or {}
        snapshot = selected.get("snapshot") or {}
        problems: list[str] = []

        site = self.sites.get(selected.get("site_code", ""))
        if site is None:
            problems.append("选定站点已不存在")
        else:
            if site["status"] != SITE_ACTIVE:
                problems.append(
                    f"{site['站点名称']}状态为{site['status']}（快照 v{snapshot.get('site_version')}，"
                    f"当前 v{site['version']}）"
                )
            elif int(site["version"]) != int(snapshot.get("site_version", -1)):
                problems.append(
                    f"{site['站点名称']}版本变化（快照 v{snapshot.get('site_version')}，"
                    f"当前 v{site['version']}），原解释不再有效"
                )

        rule = self.decode_rules.get(selected.get("decode_rule_code", ""))
        if rule is None:
            problems.append("选定解码规则已不存在")
        else:
            if rule["status"] != RULE_APPROVED:
                problems.append(
                    f"解码规则 {rule['规则编号']} 状态为{rule['status']}"
                    f"（快照 v{snapshot.get('decode_rule_version')}，当前 v{rule['version']}）"
                )
            elif int(rule["version"]) != int(snapshot.get("decode_rule_version", -1)):
                problems.append(
                    f"解码规则 {rule['规则编号']} 版本变化"
                    f"（快照 v{snapshot.get('decode_rule_version')}，当前 v{rule['version']}）"
                )
            if rule["站点编号"] != selected.get("site_code"):
                problems.append("解码规则归属站点已变化")

        route = self.route_rules.get(selected.get("route_rule_code", ""))
        if route is None:
            problems.append("选定路由规则已不存在")
        else:
            if route["status"] != RULE_APPROVED:
                problems.append(
                    f"路由规则 {route['规则编号']} 已{route['status']}"
                    f"（快照 v{snapshot.get('route_rule_version')}，当前 v{route['version']}）"
                )
            elif int(route["version"]) != int(snapshot.get("route_rule_version", -1)):
                problems.append(
                    f"路由规则 {route['规则编号']} 版本变化"
                    f"（快照 v{snapshot.get('route_rule_version')}，当前 v{route['version']}）"
                )
            if route["站点编号"] != selected.get("site_code"):
                problems.append("路由规则归属站点已变化")
        return problems

    def _delivery_eligible(self, frame: dict[str, Any]) -> bool:
        return bool(
            frame.get("selected")
            and not frame.get("message_id")
            and frame["status"] not in (FRAME_RECHECK, FRAME_HELD)
        )

    def _decode(self, raw_hex: str, rule: dict[str, Any]) -> dict[str, Any]:
        """严格只使用给定站点规则解码；字段不够或标识缺失时返回失败。"""
        compact = str(raw_hex or "").replace(" ", "").replace("\n", "")
        if not compact:
            return {"ok": False, "message": "报文内容为空"}
        try:
            binary = bytes.fromhex(compact)
        except ValueError:
            return {"ok": False, "message": "报文不是合法的 hex 字符串"}

        identifier = rule.get("报文标识", "")
        if identifier:
            ident = identifier.encode()
            index = binary.find(ident)
            if index < 0:
                return {"ok": False, "message": f"报文中未找到标识 {identifier}"}
            payload = binary[index + len(ident):]
        else:
            payload = binary

        try:
            offset = int(rule.get("字段偏移", "0"))
            length = int(rule.get("字段长度", "0"))
        except (TypeError, ValueError):
            return {"ok": False, "message": "字段偏移/长度配置不是整数"}
        if offset < 0 or length <= 0:
            return {"ok": False, "message": "字段偏移/长度配置无效"}
        chunk = payload[offset:offset + length]
        if len(chunk) < length:
            return {"ok": False, "message": "报文长度不足，无法截取字段"}

        data_type = str(rule.get("数据类型", "hex")).lower()
        byte_order = str(rule.get("字节序", "big")).lower()
        endian = "little" if byte_order == "little" else "big"
        try:
            if data_type == "uint8":
                value: Any = chunk[0]
            elif data_type == "uint16":
                value = int.from_bytes(chunk[:2], endian, signed=False)
            elif data_type == "int16":
                value = int.from_bytes(chunk[:2], endian, signed=True)
            elif data_type == "uint32":
                value = int.from_bytes(chunk[:4], endian, signed=False)
            elif data_type == "int32":
                value = int.from_bytes(chunk[:4], endian, signed=True)
            elif data_type == "float32":
                value = struct.unpack((">" if endian == "big" else "<") + "f", chunk[:4])[0]
            elif data_type == "float64":
                value = struct.unpack((">" if endian == "big" else "<") + "d", chunk[:8])[0]
            else:
                value = chunk.hex()
        except (struct.error, ValueError) as exc:
            return {"ok": False, "message": f"字段解析失败：{exc}"}

        checksum_type = str(rule.get("校验方式", "none")).lower()
        checksum_valid = True
        if checksum_type == "xor8":
            xor_sum = 0
            for byte in payload:
                xor_sum ^= byte
            checksum_valid = xor_sum == 0
        elif checksum_type == "sum8":
            checksum_valid = sum(payload) % 256 == 0

        return {
            "ok": True,
            "message": "解码完成",
            "site_code": rule["站点编号"],
            "rule_code": rule["规则编号"],
            "rule_version": rule["version"],
            "protocol_type": rule["协议类型"],
            "identifier": identifier,
            "payload_hex": payload.hex(),
            "field_offset": offset,
            "field_length": length,
            "field_hex": chunk.hex(),
            "data_type": data_type,
            "byte_order": byte_order,
            "value": value,
            "checksum_type": checksum_type,
            "checksum_valid": checksum_valid,
        }

    def _message_of(self, frame: dict[str, Any]) -> dict[str, Any] | None:
        return self.messages.get(frame["id"])

    @staticmethod
    def _message_detail(message: dict[str, Any] | None) -> dict[str, Any] | None:
        return dict(message) if message else None

    def _refresh_order(self, order_id: int) -> None:
        order = self.orders.get(order_id)
        if order is None:
            return
        frames = self._frames_of(order_id)
        if any(frame["status"] == FRAME_RECHECK for frame in frames):
            status = ORDER_CONFLICT
        elif frames and all(frame["status"] == FRAME_DELIVERED for frame in frames):
            status = ORDER_DONE
        elif any(
            frame["status"] in (FRAME_SELECTED, FRAME_IN_FLIGHT, FRAME_DELIVERED, FRAME_HELD)
            for frame in frames
        ):
            status = ORDER_PROCESSING
        else:
            status = ORDER_PENDING
        if status != order["status"]:
            order["status"] = status
            order["version"] = int(order["version"]) + 1
            order["updated_at"] = _now()

    def _require_frame(
        self, order_id: int, frame_id: int
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        order = self.orders.get(order_id)
        if order is None:
            return {}, self._error(404, "ORDER_NOT_FOUND", f"归属确认单 {order_id} 不存在")
        frame = self.frames.get(frame_id)
        if frame is None or frame["order_id"] != order_id:
            return {}, self._error(404, "FRAME_NOT_FOUND", f"帧 {frame_id} 不在确认单 {order_id} 中")
        return frame, None

    def _conflict_response(
        self,
        frame: dict[str, Any],
        code: str,
        message: str,
        *,
        reasons: list[str] | None = None,
        mark: bool = True,
    ) -> dict[str, Any]:
        reasons = reasons or [message]
        if mark and frame["status"] != FRAME_RECHECK:
            # 版本冲突的帧保留原选择快照作为追责依据，但必须重新选择才能再次投递。
            if frame.get("selected"):
                frame["selected"]["stale"] = True
            frame["status"] = FRAME_RECHECK
            frame["version"] = int(frame["version"]) + 1
            frame["updated_at"] = _now()
            frame["conflict"] = {
                "code": code,
                "message": message,
                "reasons": reasons,
                "detected_at": _now(),
                "snapshot": (frame.get("selected") or {}).get("snapshot"),
                "previous_message_count": len(self.messages),
            }
            self._refresh_order(frame["order_id"])
        return self._error(409, code, message, extra={
            "reasons": reasons,
            "frame": self._frame_detail(frame),
            "conflict": frame.get("conflict"),
        })

    @staticmethod
    def _error(
        status_code: int, code: str, message: str, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = {
            "ok": False,
            "code": code,
            "message": message,
            "status_code": status_code,
        }
        if extra:
            payload.update(extra)
        return payload

    @staticmethod
    def _ok(
        frame: dict[str, Any], message: str, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = {
            "ok": True,
            "message": message,
            "frame_id": frame["id"],
            "帧编号": frame["帧编号"],
            "status": frame["status"],
            "version": frame["version"],
            "selected": frame.get("selected"),
            "message_id": frame.get("message_id"),
        }
        if extra:
            payload.update(extra)
        return payload


site_attribution_service = SiteAttributionService()
