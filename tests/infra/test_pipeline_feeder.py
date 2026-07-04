"""pipeline_feeder 단위 테스트 (네트워크 없음).

이 테스트는 루트 CI(`python -m pytest`, testpaths=["tests"])가 수집하도록 tests/
아래에 둔다 — infra/log 의 pipeline_feeder 는 sys.path 로 임포트한다.
pipeline_feeder 는 표준 라이브러리만 사용(httpx 는 post_entries 내 지연 임포트)하므로
importorskip 불필요.
"""

from __future__ import annotations

import sys
from pathlib import Path

_INFRA_LOG = Path(__file__).resolve().parents[2] / "infra" / "log"
sys.path.insert(0, str(_INFRA_LOG))

from pipeline_feeder import cycle_to_log_entries, post_entries  # noqa: E402

LAYER_ORDER = ["abstraction", "threat", "risk", "response", "flight_plan"]


def _full_result_high_rac():
    return {
        "abstraction": {
            "channels": [
                {"channel": "position_consistency", "state": "normal"},
                {"channel": "link_status", "state": "anomaly"},
                {"channel": "proximity_object", "state": "anomaly"},
                {"channel": "terrain_class", "state": "normal"},
            ],
        },
        "threat": {
            "primary": {
                "threat_event": "T3",
                "confidence": 0.917,
                "kill_chain_stage": "후기",
            },
            "candidates": [{"threat_event": "T3"}],
        },
        "risk": {
            "candidates": [
                {
                    "threat_event": "T3",
                    "rac": "High",
                    "l_class_final": "B",
                    "severity_label_final": "Critical",
                    "compound_urgency_score": 0.4179,
                    "priority_rank": 1,
                },
                {
                    "threat_event": "T6",
                    "rac": "Medium",
                    "l_class_final": "D",
                    "severity_label_final": "Marginal",
                    "compound_urgency_score": 0.11,
                    "priority_rank": 2,
                },
            ],
            "ambient_rac": None,
        },
        "response": {
            "flight_action": "ALTITUDE_CHANGE",
            "comms_level": "L1",
            "nav_mode": None,
            "special_action": "GCS_CONSULT",
            "ai_reliability": "normal",
        },
        "flight_plan": {
            "flight_action": "ALTITUDE_CHANGE",
            "target_bearing_deg": 128.4,
            "altitude_delta_m": 15,
            "replan_scope": "LOCAL",
        },
    }


def test_full_result_five_entries_in_order():
    entries = cycle_to_log_entries("GIREOGI-0001", _full_result_high_rac())
    assert len(entries) == 5
    assert [e["layer"] for e in entries] == LAYER_ORDER
    for e in entries:
        assert e["correlation_id"] == "GIREOGI-0001"
        assert "ts" not in e
        assert e["level"] in {"info", "warn", "error"}
        assert isinstance(e["log"], str) and e["log"]


def test_abstraction_anomaly_count_and_level():
    entries = cycle_to_log_entries("C1", _full_result_high_rac())
    abstraction = entries[0]
    assert "4채널" in abstraction["log"]
    assert "anomaly 2건" in abstraction["log"]
    assert abstraction["level"] == "warn"


def test_threat_primary_line():
    entries = cycle_to_log_entries("C1", _full_result_high_rac())
    threat = entries[1]
    assert "primary=T3" in threat["log"]
    assert "conf=0.92" in threat["log"]
    assert "killchain=후기" in threat["log"]
    assert threat["level"] == "warn"


def test_risk_high_rac_is_error_and_uses_rank1():
    entries = cycle_to_log_entries("C1", _full_result_high_rac())
    risk = entries[2]
    assert risk["level"] == "error"
    assert "RAC=High" in risk["log"]
    assert "urgency=0.42" in risk["log"]
    assert "rank=1" in risk["log"]


def test_response_non_maintain_is_warn():
    entries = cycle_to_log_entries("C1", _full_result_high_rac())
    response = entries[3]
    assert response["level"] == "warn"
    assert "ALTITUDE_CHANGE" in response["log"]
    assert "comms=L1" in response["log"]
    assert "special=GCS_CONSULT" in response["log"]
    assert "nav=" not in response["log"]


def test_response_maintain_is_info_and_low_reliability_bumps():
    result = {"response": {"flight_action": "MAINTAIN", "comms_level": "L0"}}
    entry = cycle_to_log_entries("C1", result)[0]
    assert entry["level"] == "info"

    result = {
        "response": {
            "flight_action": "MAINTAIN",
            "comms_level": "L0",
            "ai_reliability": "low",
        }
    }
    entry = cycle_to_log_entries("C1", result)[0]
    assert entry["level"] == "warn"
    assert "[ai_reliability=low]" in entry["log"]


def test_flight_plan_replan_warn():
    entries = cycle_to_log_entries("C1", _full_result_high_rac())
    flight_plan = entries[4]
    assert flight_plan["level"] == "warn"
    assert "brg=128.4" in flight_plan["log"]
    assert "Δalt=15m" in flight_plan["log"]
    assert "replan=LOCAL" in flight_plan["log"]


def test_stub_result_never_raises():
    result = {layer: {} for layer in LAYER_ORDER}
    entries = cycle_to_log_entries("STUB-0001", result)
    assert len(entries) == 5
    assert [e["layer"] for e in entries] == LAYER_ORDER
    for e in entries:
        assert e["level"] in {"info", "warn", "error"}
        assert isinstance(e["log"], str) and e["log"]
    # 전부 기본치 → 경보 없이 info
    assert all(e["level"] == "info" for e in entries)


def test_missing_layers_are_skipped():
    entries = cycle_to_log_entries("C1", {"risk": {"candidates": [], "ambient_rac": "Medium"}})
    assert len(entries) == 1
    assert entries[0]["layer"] == "risk"
    assert entries[0]["level"] == "info"
    assert "ambient=Medium" in entries[0]["log"]


# ── 결정 로그 항목 계약 (#105 04 탐지 / #104 05 평가) — 라인 포맷 고정 ──


def test_threat_decision_line_exact_contract():
    """#105: primary 위협의 threat_event·confidence·kill_chain_stage + 후보 수."""
    entries = cycle_to_log_entries("C1", _full_result_high_rac())
    threat = entries[1]
    assert threat["log"] == "04 위협 · primary=T3 conf=0.92 killchain=후기 cands=1"
    assert threat["level"] == "warn"


def test_threat_no_candidates_exact_contract():
    """#105: 후보 없음 케이스 표기(실 04 출력 형태: primary=None, candidates=[])."""
    result = {"threat": {"primary": None, "candidates": [], "mission_phase": "unknown"}}
    entry = cycle_to_log_entries("C1", result)[0]
    assert entry["log"] == "04 위협 · 후보 없음"
    assert entry["level"] == "info"


def test_risk_decision_line_exact_contract():
    """#104: rank-1 후보의 rac·l_class_final·severity·urgency·priority 표기."""
    entries = cycle_to_log_entries("C1", _full_result_high_rac())
    risk = entries[2]
    assert risk["log"] == "05 위험 · RAC=High L=B S=Critical urgency=0.42 rank=1"
    assert risk["level"] == "error"


def test_risk_rank1_selected_when_list_unordered():
    """#104: candidates 가 rank 순이 아니어도 priority_rank=1 후보를 표기."""
    result = {
        "risk": {
            "candidates": [
                {
                    "threat_event": "T6",
                    "rac": "Medium",
                    "l_class_final": "D",
                    "severity_label_final": "Marginal",
                    "compound_urgency_score": 0.11,
                    "priority_rank": 2,
                },
                {
                    "threat_event": "T3",
                    "rac": "Serious",
                    "l_class_final": "B",
                    "severity_label_final": "Critical",
                    "compound_urgency_score": 0.4179,
                    "priority_rank": 1,
                },
            ],
            "ambient_rac": None,
        }
    }
    entry = cycle_to_log_entries("C1", result)[0]
    assert entry["log"] == "05 위험 · RAC=Serious L=B S=Critical urgency=0.42 rank=1"
    assert entry["level"] == "error"


def test_risk_ambient_exact_contract():
    """#104: ambient_rac(위협 없음) 케이스 표기(실 05 출력: candidates=[], ambient_rac='Low')."""
    entry = cycle_to_log_entries("C1", {"risk": {"candidates": [], "ambient_rac": "Low"}})[0]
    assert entry["log"] == "05 위험 · 위협 없음 ambient=Low"
    assert entry["level"] == "info"


def test_risk_level_mapping_by_rac():
    """#104: High/Serious→error, 그 외(rank-1 존재)→warn 레벨 매핑 고정."""

    def _entry(rac):
        result = {
            "risk": {
                "candidates": [
                    {
                        "rac": rac,
                        "l_class_final": "C",
                        "severity_label_final": "Marginal",
                        "compound_urgency_score": 0.2,
                        "priority_rank": 1,
                    }
                ],
                "ambient_rac": None,
            }
        }
        return cycle_to_log_entries("C1", result)[0]

    assert _entry("Serious")["level"] == "error"
    assert _entry("Medium")["level"] == "warn"
    assert _entry("Low")["level"] == "warn"


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeClient:
    def __init__(self, status_codes):
        self._status_codes = list(status_codes)
        self.posted = []

    def post(self, url, json=None):
        self.posted.append((url, json))
        return _FakeResponse(self._status_codes[len(self.posted) - 1])


def test_post_entries_counts_2xx_and_posts_collector_format():
    entries = cycle_to_log_entries("C1", _full_result_high_rac())
    client = _FakeClient([200, 200, 200, 500, 200])
    count = post_entries(entries, "http://collector/log", client=client)
    assert count == 4
    assert len(client.posted) == 5
    url, body = client.posted[0]
    assert url == "http://collector/log"
    assert set(body.keys()) == {"correlation_id", "layer", "log", "level"}


def test_post_entries_connection_error_partial_count(capsys):
    class _FlakyClient:
        def __init__(self):
            self.calls = 0

        def post(self, url, json=None):
            self.calls += 1
            if self.calls == 2:
                raise ConnectionError("refused")
            return _FakeResponse(200)

    entries = cycle_to_log_entries("C1", _full_result_high_rac())
    count = post_entries(entries, "http://collector/log", client=_FlakyClient())
    assert count == 4
    assert "실패" in capsys.readouterr().err
