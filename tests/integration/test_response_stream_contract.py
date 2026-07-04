"""issue #103 — 06 Response 출력의 스트림 어댑터 계약 검증.

수용 기준:
1. _response_log 가 6개 필드(flight_action/comms_level/payload_action/nav_mode/
   special_action/ai_reliability)를 모두 반영
2. 실 run_cycle 대응값과 pipeline_feeder 로그 엔트리의 필드 일치
"""

import json
import pathlib
import sys

import pytest

# pipeline_feeder 는 infra/log/ 아래에 있어서 sys.path 명시 필요
_INFRA_LOG = pathlib.Path(__file__).resolve().parents[2] / "infra" / "log"
if str(_INFRA_LOG) not in sys.path:
    sys.path.insert(0, str(_INFRA_LOG))

from pipeline_feeder import cycle_to_log_entries  # noqa: E402
from onboard.run import run_cycle  # noqa: E402

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _response_entry(result: dict) -> dict:
    entries = cycle_to_log_entries("CONTRACT-TEST", result)
    return next(e for e in entries if e["layer"] == "response")


# ---------------------------------------------------------------------------
# 1. payload_action 반영 (unit-level, mocked response)
# ---------------------------------------------------------------------------


def test_response_log_includes_payload_action_when_present():
    """payload_action 이 비어 있지 않으면 로그에 actions=[...] 형태로 포함된다."""
    result = {
        "response": {
            "flight_action": "ALTITUDE_CHANGE",
            "comms_level": "L1",
            "payload_action": ["DATA_WIPE", "WEAPON_DROP"],
            "nav_mode": None,
            "special_action": None,
            "ai_reliability": "normal",
        }
    }
    entry = _response_entry(result)
    assert "actions=[DATA_WIPE,WEAPON_DROP]" in entry["log"], (
        f"payload_action 이 log에 없음: {entry['log']!r}"
    )


def test_response_log_omits_payload_action_when_empty():
    """payload_action=[] 이면 log 에 'actions=' 가 나타나지 않는다."""
    result = {
        "response": {
            "flight_action": "ALTITUDE_CHANGE",
            "comms_level": "L1",
            "payload_action": [],
            "nav_mode": None,
            "special_action": None,
            "ai_reliability": "normal",
        }
    }
    entry = _response_entry(result)
    assert "actions=" not in entry["log"], (
        f"payload_action=[] 인데 actions= 가 나타남: {entry['log']!r}"
    )


def test_response_log_includes_all_six_fields():
    """6개 필드(flight_action/comms/payload/nav/special/ai_reliability)를 모두 반영."""
    result = {
        "response": {
            "flight_action": "REROUTE",
            "comms_level": "L2",
            "payload_action": ["DATA_WIPE"],
            "nav_mode": "INS_ONLY",
            "special_action": "GCS_CONSULT",
            "ai_reliability": "low",
        }
    }
    entry = _response_entry(result)
    log = entry["log"]
    assert "REROUTE" in log
    assert "comms=L2" in log
    assert "actions=[DATA_WIPE]" in log
    assert "nav=INS_ONLY" in log
    assert "special=GCS_CONSULT" in log
    assert "[ai_reliability=low]" in log


# ---------------------------------------------------------------------------
# 2. 실 run_cycle 대응값과 로그 엔트리 일치
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tag", ["t3", "t2", "t4"])
def test_response_log_matches_actual_run_cycle(tag):
    """실 run_cycle 의 response 출력과 pipeline_feeder log entry 가 일치한다."""
    result = run_cycle(_load(f"raw_{tag}.json"), _load(f"mission_brief_{tag}.json"))
    resp = result["response"]
    entry = _response_entry(result)
    log = entry["log"]

    # flight_action 반영
    assert resp["flight_action"] in log, f"[{tag}] flight_action={resp['flight_action']} 미포함"

    # comms_level 반영
    assert f"comms={resp['comms_level']}" in log, (
        f"[{tag}] comms_level={resp['comms_level']} 미포함"
    )

    # nav_mode: non-None 이면 반영
    if resp.get("nav_mode"):
        assert f"nav={resp['nav_mode']}" in log, (
            f"[{tag}] nav_mode={resp['nav_mode']} 미포함"
        )

    # special_action: non-None 이면 반영
    if resp.get("special_action"):
        assert f"special={resp['special_action']}" in log, (
            f"[{tag}] special_action={resp['special_action']} 미포함"
        )

    # payload_action 반영 (비어 있지 않을 때)
    if resp.get("payload_action"):
        actions_str = ",".join(resp["payload_action"])
        assert f"actions=[{actions_str}]" in log, (
            f"[{tag}] payload_action={resp['payload_action']} 미포함"
        )

    # level 계약: MAINTAIN 이면 info, 그 외 warn 이상
    if resp["flight_action"] == "MAINTAIN" and resp.get("ai_reliability") != "low":
        assert entry["level"] == "info", f"[{tag}] MAINTAIN 은 info 여야 함"
    else:
        assert entry["level"] in {"warn", "error"}, (
            f"[{tag}] non-MAINTAIN 은 warn/error 여야 함"
        )
