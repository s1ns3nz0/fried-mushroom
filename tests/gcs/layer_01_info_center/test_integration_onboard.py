"""통합(킬러): GCS layer 01 이 낸 mission_brief 가 온보드 01→07 을 구동한다.

layer 01 finalize 출력(mission_brief)을 온보드 run_cycle 에 그대로 먹여
종단이 완주하고 올바른 위협(T3)을 산출하는지 검증 — 01 출력이 실제 온보드
MissionBrief 계약과 정합함을 증명한다.
"""

import json
import pathlib

from gcs.layer_01_info_center.run import assemble_draft, finalize
from onboard.run import run_cycle

_EXAMPLES = pathlib.Path(__file__).resolve().parents[3] / "examples"


def _load(name: str) -> dict:
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _set_mission(**over) -> dict:
    base = {
        "sortie_id": "GIREOGI-0704-01",
        "directive_text": "적 저격조 및 대구경화기 첩보 확인됨. 가용 예비기체 없음.",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"armament": [], "spare_asset_available": True, "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "c4i": {
            "enemy_situation": ["적 저격조 활동 확인"],
            "asset_management": {"spare_asset_available": True},
            "known_mission": "정찰 감시",
        },
    }
    base.update(over)
    return base


def test_layer01_brief_drives_onboard_end_to_end() -> None:
    draft = assemble_draft(_set_mission())
    res = finalize(draft, approved=True, ts_ms=1720051200000)
    mb = res["mission_brief"]
    assert set(mb) == {"sortie_id", "mission_context", "posture", "drone_profile", "corridor", "weights"}
    # 라운드2: mettc 상태모델이 조립·확정본에 동반되며, 투영본이 온보드를 구동한다.
    assert set(res["mettc_state"]["mettc"]) == {"M", "E", "T_terrain", "T_troops", "T_time", "C"}

    out = run_cycle(_load("raw_t3.json"), mb)  # 01 출력 → 온보드 입력
    assert set(out) == {
        "abstraction", "threat", "risk", "response", "flight_plan", "flight_plan_state", "endurance", "corridor",
    }
    # 정찰 브리핑 + t3 센서 → T3 탐지 종단.
    assert out["response"]["primary_threat_event"] == "T3"
    assert out["response"]["threat_category"] == "PHYSICAL"


def test_signal_cards_reflect_directive() -> None:
    draft = assemble_draft(_set_mission())
    phrases = {c["source_phrase"] for c in draft["signal_cards"]}
    assert "저격조" in phrases  # 지시서 위협
    assert "예비기체 없음" in phrases  # 병참 신호


def test_spare_mismatch_warns_but_brief_still_finalizes() -> None:
    # 등록 spare True vs C4I False → 경고, 그래도 승인 시 브리핑 확정 가능.
    inp = _set_mission(c4i={"asset_management": {"spare_asset_available": False}})
    draft = assemble_draft(inp)
    assert [w for w in draft["warnings"] if w["field"] == "spare_available"]
    res = finalize(draft, approved=True, ts_ms=1)
    out = run_cycle(_load("raw_t3.json"), res["mission_brief"])
    assert out["response"]["primary_threat_event"] == "T3"
