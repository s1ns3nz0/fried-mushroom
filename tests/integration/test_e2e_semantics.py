"""종단 시맨틱 테스트 (step9 Acceptance, 실측 정본 기준).

run_cycle(raw, mission_brief) 종단 출력이 D4D 스펙의 시나리오별 의미를
만족하는지 검증. golden(expected_tN.json) 과 달리 스펙에서 직접 인코딩한다.

주의: RAC 는 mission_context 별 base_rate 에 의존한다(05 BASE_RATE_PHYSICAL).
- t3=정찰(0.15), t4=호송(0.12) → PHYSICAL 위협도 Serious 등급.
- DATA_WIPE/WEAPON_DROP(High+후기/중기) 경로는 타격 컨텍스트(strike)에서 검증.
"""

import json
import pathlib

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.run import run_cycle

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _run(scenario: str) -> dict:
    return run_cycle(_load(f"raw_{scenario}.json"), _load(f"mission_brief_{scenario}.json"))


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
    """t4(물리 포획, 호송): T4 탐지, PHYSICAL, Serious."""
    out = _run("t4")
    assert out["response"]["primary_threat_event"] == "T4"
    assert out["response"]["threat_category"] == "PHYSICAL"
    assert out["response"]["rac"] == "Serious"
    assert out["response"]["payload_action"] == []


def test_t7_terrain_navigation() -> None:
    """t7(지형충돌, 수송): NAVIGATION 위협으로 분류 (적대행위 아님)."""
    out = _run("t7")
    assert out["response"]["primary_threat_event"] == "T7"
    assert out["response"]["threat_category"] == "NAVIGATION"


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
