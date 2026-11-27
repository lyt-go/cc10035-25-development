"""站点归属确认测试：候选冲突、选站、试投、重复提交与版本冲突。"""
from __future__ import annotations

import json

import pytest

from app.services.site_attribution import SiteAttributionService


@pytest.fixture
def service(monkeypatch):
    """用独立实例替换路由层单例，避免用例之间互相污染。"""
    instance = SiteAttributionService()
    from app.routers import site_attribution as api

    monkeypatch.setattr(api, "site_attribution_service", instance)
    return instance


def _select_west(service, order_id=1, frame_id=1, **kwargs):
    return service.select(
        order_id,
        frame_id,
        site_code="SITE-Q",
        decode_rule_code="DR-Q-A1",
        route_rule_code="RT-Q-A1",
        **kwargs,
    )


class TestDetection:
    def test_same_identifier_two_sites_is_ambiguous(self, service):
        result = service.detect("41310A1B00001122", "A1")
        assert result["candidate_count"] == 2
        assert result["ambiguous"] is True
        assert result["adopted_rule"] is None
        assert {c["site_code"] for c in result["candidates"]} == {"SITE-P", "SITE-Q"}

    def test_each_site_decoded_by_own_rule(self, service):
        result = service.detect("41310A1B00001122", "A1")
        by_site = {c["site_code"]: c for c in result["candidates"]}
        assert by_site["SITE-P"]["preview"]["value"] == 0x0A1B
        assert by_site["SITE-P"]["preview"]["byte_order"] == "big"
        assert by_site["SITE-Q"]["preview"]["value"] == 0x2211
        assert by_site["SITE-Q"]["preview"]["byte_order"] == "little"

    def test_field_conflicts_exposed_for_workbench(self, service):
        result = service.detect("41310A1B00001122", "A1")
        fields = {item["field"] for item in result["field_conflicts"]}
        assert {"协议类型", "字段偏移", "字节序"} <= fields
        for conflict in result["field_conflicts"]:
            assert len({v["value"] for v in conflict["values"]}) > 1


class TestSelection:
    def test_unselected_frame_has_no_delivery_eligibility(self, service):
        order = service.get_order(1)
        assert all(not frame["delivery_eligible"] for frame in order["frames"])
        result = service.dispatch(1, 1)
        assert result["ok"] is False
        assert result["code"] == "NO_DELIVERY_ELIGIBILITY"
        assert service.stats()["messages"] == 0

    def test_cross_site_rule_rejected(self, service):
        result = service.select(
            1, 1, site_code="SITE-Q", decode_rule_code="DR-P-A1",
        )
        assert result["ok"] is False
        assert result["code"] == "RULE_SITE_MISMATCH"

    def test_select_west_then_dispatch_uses_west_interpretation(self, service):
        assert _select_west(service)["ok"] is True
        result = service.dispatch(1, 1)
        assert result["ok"] is True
        message = result["trial_message"]
        assert message["站点编号"] == "SITE-Q"
        assert message["目标Topic"] == "west/normalized/A1"
        assert message["解码值"] == 0x2211
        assert message["解释依据"]

    def test_repeat_submit_does_not_create_second_message(self, service):
        _select_west(service)
        first = service.dispatch(1, 1)
        second = service.dispatch(1, 1)
        assert first["ok"] and second["ok"]
        assert second["duplicate"] is True
        assert first["trial_message"]["message_id"] == second["trial_message"]["message_id"]
        assert service.stats()["messages"] == 1

    def test_duplicate_selection_keeps_version(self, service):
        first = _select_west(service)
        second = _select_west(service)
        assert second["ok"] and second["duplicate"] is True
        assert second["version"] == first["version"]

    def test_other_frames_in_order_stay_pending(self, service):
        _select_west(service)
        service.dispatch(1, 1)
        order = service.get_order(1)
        frame2 = next(f for f in order["frames"] if f["id"] == 2)
        assert frame2["status"] == "待核对"
        assert frame2["selected"] is None


class TestVersionConflict:
    def test_site_stop_conflicts_with_in_flight_frame(self, service):
        # 第 3 单的帧在站点停用前已选定西站，属于在途试投。
        stopped = service.set_site_status("SITE-Q", "已停用", reason="西站搬迁")
        assert stopped["ok"] is True
        assert stopped["affected_rules"] >= 2

        result = service.dispatch(3, 4)
        assert result["ok"] is False
        assert result["code"] == "VERSION_CONFLICT"
        assert result["reasons"]
        assert service.stats()["messages"] == 0

        frame = next(f for f in service.get_order(3)["frames"] if f["id"] == 4)
        assert frame["status"] == "待再次核对"
        assert frame["selected"]["stale"] is True
        assert frame["conflict"]["code"] == "VERSION_CONFLICT"
        assert frame["conflict"]["snapshot"]["site_version"] == 1

    def test_conflicted_frame_can_be_reopened_and_reselected(self, service):
        service.set_site_status("SITE-Q", "已停用", reason="西站搬迁")
        service.dispatch(3, 4)
        assert service.get_order(3)["status"] == "版本冲突"

        # 重新打开旧单，西站仍不可用：不能选择其规则。
        blocked = service.select(3, 4, site_code="SITE-Q", decode_rule_code="DR-Q-A1")
        assert blocked["ok"] is False
        assert blocked["code"] in ("SITE_UNAVAILABLE", "RULE_NOT_APPROVED")

        # 改选东站：必须用东站自己的解码与路由规则。
        assert service.approve_rule("SITE-P", "DR-P-A1")["ok"] is True
        picked = service.select(
            3, 4, site_code="SITE-P", decode_rule_code="DR-P-A1",
            route_rule_code="RT-P-A1",
        )
        assert picked["ok"] is True
        sent = service.dispatch(3, 4)
        assert sent["ok"] is True
        assert sent["trial_message"]["站点编号"] == "SITE-P"
        assert sent["trial_message"]["目标Topic"] == "east/normalized/A1"
        assert sent["trial_message"]["解码值"] == 0x0A1B

    def test_rule_version_drift_after_selection_blocks_dispatch(self, service):
        _select_west(service)
        service.approve_rule("SITE-Q", "DR-Q-A1", basis="西站二次复核记录 Q-A1-08")
        result = service.dispatch(1, 1)
        assert result["ok"] is False
        assert result["code"] == "VERSION_CONFLICT"
        assert service.stats()["messages"] == 0

    def test_stale_version_expected_rejected(self, service):
        _select_west(service)
        result = service.dispatch(1, 1, expected_version=1)
        assert result["ok"] is False
        assert result["code"] == "FRAME_VERSION_MISMATCH"
        # 帧版本不一致只要求刷新，不把帧打成冲突待核。
        assert service.get_order(1)["frames"][0]["status"] == "已选定"


class TestHold:
    def test_held_frame_remains_in_original_order(self, service):
        result = service.hold(1, 2, remark="标识不明确")
        assert result["ok"] is True
        order = service.get_order(1)
        held = next(f for f in order["frames"] if f["id"] == 2)
        assert held["status"] == "留待核对"
        assert held["delivery_eligible"] is False
        assert service.dispatch(1, 2)["ok"] is False
        # 其他帧仍可独立办理。
        assert _select_west(service)["ok"] is True

    def test_ambiguous_frame_without_choice_stays_pending(self, service):
        order = service.get_order(1)
        assert all(frame["detection"]["ambiguous"] for frame in order["frames"])
        assert all(frame["status"] == "待核对" for frame in order["frames"])
        assert service.stats()["messages"] == 0


class TestInFlightContinuation:
    def test_in_flight_frame_can_still_be_dispatched_when_basis_unchanged(self, service):
        order = service.get_order(3)
        frame = order["frames"][0]
        assert frame["status"] == "在途"
        assert frame["delivery_eligible"] is True
        result = service.dispatch(3, 4)
        assert result["ok"] is True
        assert result["trial_message"]["站点名称"] == "西站"
        assert result["trial_message"]["目标Topic"] == "west/normalized/A1"

    def test_recovered_site_can_resume_after_reapproval(self, service):
        service.set_site_status("SITE-Q", "已停用", reason="搬迁")
        assert service.dispatch(3, 4)["ok"] is False
        # 站点恢复后规则仍需重新核准，核准后旧单可继续办理。
        service.set_site_status("SITE-Q", "启用中")
        assert service.select(3, 4, site_code="SITE-Q", decode_rule_code="DR-Q-A1")["ok"] is False
        assert service.approve_rule("SITE-Q", "DR-Q-A1", basis="西站复工复核 Q-A1-09")["ok"] is True
        assert service.approve_rule("SITE-Q", "RT-Q-A1", basis="西站复工路由复核 RT-Q-12")["ok"] is True
        picked = service.select(
            3, 4, site_code="SITE-Q", decode_rule_code="DR-Q-A1", route_rule_code="RT-Q-A1"
        )
        assert picked["ok"] is True
        sent = service.dispatch(3, 4)
        assert sent["ok"] is True
        assert sent["trial_message"]["站点名称"] == "西站"
        assert sent["trial_message"]["快照"]["decode_rule_version"] == 3
        assert sent["trial_message"]["站点编号"] == "SITE-Q"


class TestEastIndependentTrial:
    def test_east_trial_does_not_reuse_west_rules(self, service):
        # 东站单独试投：即使西站登记了同标识 A1，也不得沿用西站解码或路由。
        picked = service.select(
            2, 3, site_code="SITE-P", decode_rule_code="DR-P-A1", route_rule_code="RT-P-A1"
        )
        assert picked["ok"] is True
        result = service.dispatch(2, 3)
        assert result["ok"] is True
        message = result["trial_message"]
        assert message["站点编号"] == "SITE-P"
        assert message["规则编号"] == "DR-P-A1"
        assert message["路由规则"] == "RT-P-A1"
        assert message["目标Topic"] == "east/normalized/A1"
        assert message["解码值"] == 0x0A1B
        assert message["快照"]["decode_rule_code"] == "DR-P-A1"


class TestApi:
    """直接调用路由函数，验证接口层与领域层的接线（环境未装 TestClient 依赖）。"""

    def test_detect_endpoint(self, service):
        from app.routers import site_attribution as api

        payload = api.detect(api.DetectPayload(raw_hex="41310A1B00001122"))
        assert payload["ambiguous"] is True

    def test_select_and_dispatch_endpoints(self, service):
        from app.routers import site_attribution as api

        selected = api.select_frame(
            1, 1,
            api.SelectPayload(
                site_code="SITE-P", decode_rule_code="DR-P-A1", route_rule_code="RT-P-A1"
            ),
        )
        assert selected.status_code == 200
        response = api.dispatch_frame(1, 1, api.DispatchPayload())
        assert response.status_code == 200
        body = json.loads(response.body)
        assert body["trial_message"]["站点名称"] == "东站"
        # 东站试投没有混用西站规则。
        assert body["trial_message"]["规则编号"] == "DR-P-A1"
        assert body["trial_message"]["路由规则"] == "RT-P-A1"
        assert body["trial_message"]["解码值"] == 0x0A1B

    def test_conflict_endpoint_returns_409(self, service):
        from app.routers import site_attribution as api

        api.set_site_status("SITE-Q", api.SiteStatusPayload(status="已停用", reason="搬迁"))
        response = api.dispatch_frame(3, 4, api.DispatchPayload())
        assert response.status_code == 409
        assert json.loads(response.body)["code"] == "VERSION_CONFLICT"
