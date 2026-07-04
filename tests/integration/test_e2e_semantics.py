"""종단 시맨틱 테스트 (step9 Acceptance, 실측 정본 기준).

run_cycle(raw, mission_brief) 종단 출력이 D4D 스펙의 시나리오별 의미를
만족하는지 검증. golden(expected_tN.json) 과 달리 스펙에서 직접 인코딩한다.

주의: RAC 는 mission_context 별 base_rate 에 의존한다(05 BASE_RATE_PHYSICAL).
- t3=정찰(0.15), t4=호송(0.12) → PHYSICAL 위협도 Serious 등급.
- DATA_WIPE/WEAPON_DROP(High+후기/중기) 경로는 타격 컨텍스트(strike)에서 검증.

(#24 T7 CFIT 판정은 07 CFIT override 로 해소됨 → test_t7_terrain_navigation 이
ALTITUDE_CHANGE + altitude_delta_m>0 을 직접 검증한다. 잔존 xfail 없음, Refs #41.)
"""

import json
import pathlib

import pytest

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.run import run_cycle

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _run(scenario: str, prev_qualities_name: str | None = None) -> dict:
    previous_qualities = _load(prev_qualities_name) if prev_qualities_name is not None else None
    return run_cycle(
        _load(f"raw_{scenario}.json"),
        _load(f"mission_brief_{scenario}.json"),
        previous_qualities=previous_qualities,
    )


def test_t3_proximity_smallarms_recon() -> None:
    """t3(근접 소화기, 정찰): T3 탐지, PHYSICAL, 정찰 base_rate 로 Serious."""
    out = _run("t3")
    assert out["response"]["primary_threat_event"] == "T3"
    assert out["response"]["threat_category"] == "PHYSICAL"
    assert out["response"]["rac"] == "Serious"
    assert out["response"]["flight_action"] == "ALTITUDE_CHANGE"
    assert out["response"]["payload_action"] == []  # High 아니므로 DATA_WIPE 없음
    assert out["flight_plan"]["replan_scope"] == "LOCAL"


def test_t4_physical_capture_convoy() -> None:
    """t4(물리 포획, 호송): T4 탐지, PHYSICAL, Serious → ALTITUDE_CHANGE, LOCAL."""
    out = _run("t4")
    assert out["response"]["primary_threat_event"] == "T4"
    assert out["response"]["threat_category"] == "PHYSICAL"
    assert out["response"]["rac"] == "Serious"
    assert out["response"]["flight_action"] == "ALTITUDE_CHANGE"
    assert out["response"]["payload_action"] == []
    assert out["flight_plan"]["altitude_delta_m"] == 15
    assert out["flight_plan"]["replan_scope"] == "LOCAL"


def test_t1_gps_spoof_remote() -> None:
    """t1(GPS 스푸핑, 정찰): T1 탐지, REMOTE, Medium → MAINTAIN + last_known_good_position."""
    out = _run("t1")
    assert out["response"]["primary_threat_event"] == "T1"
    assert out["response"]["threat_category"] == "REMOTE"
    assert out["response"]["rac"] == "Medium"
    assert out["response"]["flight_action"] == "MAINTAIN"
    assert out["response"]["comms_level"] == "L1"
    assert out["response"]["nav_mode"] is None
    assert out["flight_plan"]["replan_scope"] == "NONE"
    assert out["flight_plan"]["reroute_anchor"] == "mission_corridor_resume"  # MAINTAIN → 미션시퀀서 복귀 신호(신규 확정)


def test_t5_laser_optical_remote() -> None:
    """t5(레이저/광학 교란, 정찰): terrain_class quality_delta 급락(1.0→0.65=-0.35<-0.3) → T5.

    REMOTE, base_rate 0.08 → l_class D, watchcon/defcon=3 → +1 → C, mission_abort→Marginal(3),
    RAC_MATRIX[(C,3)]=Medium. 단일채널 det confidence 0.7(교차검증 폴백), 중기.
    previous_qualities 정본 주입 필요(quality_delta 파생, #79/#97).
    """
    out = _run("t5", "qualities_t5_primed.json")
    primary = out["threat"]["primary"]
    assert primary["threat_event"] == "T5"
    assert primary["potential_outcome"] == "mission_abort"
    assert primary["confidence"] == 0.7
    assert primary["confidence_source"] == "deterministic"
    assert primary["kill_chain_stage"] == "중기"
    assert out["response"]["primary_threat_event"] == "T5"
    assert out["response"]["threat_category"] == "REMOTE"
    assert out["response"]["rac"] == "Medium"
    assert out["response"]["flight_action"] == "MAINTAIN"
    assert out["response"]["comms_level"] == "L1"
    assert out["response"]["nav_mode"] is None
    assert out["response"]["payload_action"] == []
    assert out["flight_plan"]["replan_scope"] == "NONE"
    assert out["flight_plan"]["reroute_anchor"] == "mission_corridor_resume"


def test_t2_cyber_hijack_remote() -> None:
    """t2(C2 하이재킹): T2 탐지, REMOTE, High → REROUTE + last_known_good_position (#28 수정 후 잠금)."""
    out = _run("t2")
    assert out["response"]["primary_threat_event"] == "T2"
    assert out["response"]["threat_category"] == "REMOTE"
    assert out["response"]["rac"] == "High"
    assert out["response"]["flight_action"] == "REROUTE"
    assert out["response"]["comms_level"] == "L2"
    assert out["response"]["nav_mode"] is None
    assert out["response"]["payload_action"] == []
    assert out["flight_plan"]["replan_scope"] == "FULL"
    assert out["flight_plan"]["reroute_anchor"] == "last_known_good_position"


def test_t7_terrain_navigation() -> None:
    """t7(지형충돌, 수송): NAVIGATION, 07 CFIT override → TTC<3s이므로 altitude_delta_m>0."""
    out = _run("t7")
    assert out["response"]["primary_threat_event"] == "T7"
    assert out["response"]["threat_category"] == "NAVIGATION"
    assert out["response"]["rac"] == "Medium"
    assert out["flight_plan"]["flight_action"] == "ALTITUDE_CHANGE"
    assert out["flight_plan"]["altitude_delta_m"] > 0
    assert out["flight_plan"]["replan_scope"] == "LOCAL"


def test_strike_high_rac_triggers_payload_overrides() -> None:
    """타격 컨텍스트(raw_t3 + strike brief): High → RTL + DATA_WIPE + WEAPON_DROP.

    High+후기/중기 에서만 발동하는 payload override 경로를 검증한다.
    """
    out = run_cycle(_load("raw_t3.json"), _load("mission_brief_strike.json"))
    assert out["response"]["rac"] == "High"
    assert out["response"]["flight_action"] == "RTL"
    assert out["response"]["payload_action"] == ["DATA_WIPE", "WEAPON_DROP"]


def test_normal_envelope_no_primary_threat() -> None:
    """정상 envelope: 위협 후보 없음 → primary_threat_event None."""
    out = run_cycle(build_normal_envelope("NORMAL", 0, 0), _load("mission_brief_t3.json"))
    assert out["response"]["primary_threat_event"] is None
