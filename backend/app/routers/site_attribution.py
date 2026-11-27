"""站点归属确认接口：探测、确认单、选站、试投与站点规则维护。"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.site_attribution import site_attribution_service

router = APIRouter(prefix="/api/site-attribution", tags=["站点归属确认"])

# 同一帧的选站与试投串行处理，避免并发点击生成第二条消息。
_write_lock = threading.Lock()


class DetectPayload(BaseModel):
    raw_hex: str = Field(..., description="报文hex内容")
    identifier: str = Field(default="A1", description="报文标识")


class SelectPayload(BaseModel):
    site_code: str
    decode_rule_code: str
    route_rule_code: str | None = None
    expected_version: int | None = None
    operator: str = "值班员"
    remark: str = ""


class DispatchPayload(BaseModel):
    expected_version: int | None = None
    request_id: str | None = None
    operator: str = "值班员"


class HoldPayload(BaseModel):
    expected_version: int | None = None
    remark: str = ""


class SiteStatusPayload(BaseModel):
    status: str
    reason: str = ""
    operator: str = "值班员"


class RuleApprovePayload(BaseModel):
    basis: str | None = None
    operator: str = "协议组"


def _respond(payload: dict[str, Any]) -> JSONResponse:
    status_code = int(payload.get("status_code", 200)) if not payload.get("ok", True) else 200
    return JSONResponse(payload, status_code=status_code)


@router.get("/sites")
def list_sites() -> dict[str, Any]:
    """站点及其解码/路由规则，供确认页核对候选归属。"""
    return {"items": site_attribution_service.list_sites()}


@router.get("/orders")
def list_orders(status: str | None = None) -> dict[str, Any]:
    """归属确认单列表；可按单据状态筛选。"""
    return {"items": site_attribution_service.list_orders(status)}


@router.get("/orders/{order_id}")
def get_order(order_id: int) -> JSONResponse:
    """确认单详情：含帧、候选、字段冲突与已有消息。"""
    order = site_attribution_service.get_order(order_id)
    if order is None:
        return JSONResponse(
            {"ok": False, "code": "ORDER_NOT_FOUND", "message": f"归属确认单 {order_id} 不存在"},
            status_code=404,
        )
    return JSONResponse(order)


@router.get("/stats")
def stats() -> dict[str, Any]:
    """确认页顶部指标。"""
    return site_attribution_service.stats()


@router.post("/detect")
def detect(payload: DetectPayload) -> dict[str, Any]:
    """协议探测：列出同标识的全部站点候选，并标出字段冲突。

    只采用一个命中作为预选，但预选不授予投递资格。
    """
    return site_attribution_service.detect(payload.raw_hex, payload.identifier)


@router.post("/orders/{order_id}/frames/{frame_id}/select")
def select_frame(order_id: int, frame_id: int, payload: SelectPayload) -> JSONResponse:
    """为帧确定站点与规则；成功后该帧才取得投递资格。"""
    with _write_lock:
        result = site_attribution_service.select(
            order_id,
            frame_id,
            site_code=payload.site_code,
            decode_rule_code=payload.decode_rule_code,
            route_rule_code=payload.route_rule_code,
            expected_version=payload.expected_version,
            operator=payload.operator,
            remark=payload.remark,
        )
    return _respond(result)


@router.post("/orders/{order_id}/frames/{frame_id}/dispatch")
def dispatch_frame(order_id: int, frame_id: int, payload: DispatchPayload) -> JSONResponse:
    """试投：后台真正发送前校验解释是否有有效核准依据；重复提交幂等。"""
    with _write_lock:
        result = site_attribution_service.dispatch(
            order_id,
            frame_id,
            expected_version=payload.expected_version,
            request_id=payload.request_id,
            operator=payload.operator,
        )
    return _respond(result)


@router.post("/orders/{order_id}/frames/{frame_id}/hold")
def hold_frame(order_id: int, frame_id: int, payload: HoldPayload) -> JSONResponse:
    """把不明确的帧留待核对，仍保留在原确认单。"""
    with _write_lock:
        result = site_attribution_service.hold(
            order_id,
            frame_id,
            expected_version=payload.expected_version,
            remark=payload.remark,
        )
    return _respond(result)


@router.post("/sites/{site_code}/status")
def set_site_status(site_code: str, payload: SiteStatusPayload) -> JSONResponse:
    """停用/启用站点；停用会推进版本，使在途解释快照失效。"""
    with _write_lock:
        result = site_attribution_service.set_site_status(
            site_code, payload.status, reason=payload.reason, operator=payload.operator
        )
    return _respond(result)


@router.post("/sites/{site_code}/rules/{rule_code}/approve")
def approve_rule(site_code: str, rule_code: str, payload: RuleApprovePayload) -> JSONResponse:
    """重新核准站点规则并保留依据。"""
    with _write_lock:
        result = site_attribution_service.approve_rule(
            site_code, rule_code, basis=payload.basis, operator=payload.operator
        )
    return _respond(result)
