"""threat_event 종단 커버리지 잠금(메타 테스트).

목적: THREAT_CATALOG 의 "actionable" threat_event(= 실제로 candidates/primary 로
탐지되는 위협)가 examples/expected_*.json 골든(정본)으로 종단 커버되는지 잠근다.
신규 T-이벤트가 constants 에 추가됐는데 골든이 없으면 이 테스트가 시끄럽게 실패한다.

분류 근거(docs/D4D/04. Threat Modeling.md):
  - T6(환경노출도) 은 "threat_event 아님 — 배경 트랙"(§T6). candidates/primary 에 절대
    올라오지 않고 background_exposure_score 로만 소비되므로 커버리지 후보에서 제외.
  - 그 외 T1·T2·T3·T4·T5·T7 은 actionable.

T5 블로커 해소(#79, #97):
  T5 는 proximity_object/terrain_class 의 quality_delta < -0.3 로만 탐지된다. quality_delta
  는 03 이 previous_quality 대비 계산하는 "사이클 간 파생필드"라, previous_qualities 없이는
  항상 0.0 이다(_common.make_output: previous_quality is None → delta 0.0).
  #97 이 orchestrator/CLI 에 previous_qualities 스레딩(`--prev-qualities`)을 추가해
  이 블로커를 해소했다. examples/qualities_t5_primed.json(terrain_class=1.0) 을 주입하면
  raw_t5(terrain camera_confidence=0.65) 에서 delta=-0.35<-0.3 → T5 종단 탐지된다.
  golden(expected_t5.json)·test_e2e_golden.test_golden_t5 가 이를 정본으로 잠근다.
  따라서 KNOWN_UNCOVERED_BLOCKED 는 비어 있고, 전 actionable threat_event(T1·T2·T3·T4·T5·T7)
  가 골든으로 종단 커버된다.
"""

import json
import pathlib

from onboard.shared.constants import THREAT_CATALOG

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"

# 배경 트랙(threat_event 아님) — 커버리지 후보에서 제외 (04 §T6).
BACKGROUND_ONLY_EVENTS = frozenset({"T6"})

# 블로커 없음 — T5 는 #97 previous_qualities 스레딩으로 해소, 골든 커버됨 (위 docstring 참조).
KNOWN_UNCOVERED_BLOCKED: frozenset[str] = frozenset()


def _actionable_threats() -> set[str]:
    """THREAT_CATALOG 전체 중 배경 트랙(T6) 을 뺀 실제 탐지 대상."""
    return set(THREAT_CATALOG) - BACKGROUND_ONLY_EVENTS


def _golden_covered_primaries() -> set[str]:
    """examples/expected_*.json 골든들의 primary.threat_event(non-None) 집합."""
    covered: set[str] = set()
    for path in sorted(EXAMPLES.glob("expected_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        primary = data.get("threat", {}).get("primary")
        if primary and primary.get("threat_event"):
            covered.add(primary["threat_event"])
    return covered


def test_no_hidden_uncovered_actionable_threats() -> None:
    """actionable 이벤트는 모두 (골든 커버) 또는 (명시된 블로커) 여야 한다.

    신규 actionable T-이벤트가 골든 없이 추가되면 여기서 실패한다.
    """
    actionable = _actionable_threats()
    covered = _golden_covered_primaries()
    uncovered_unaccounted = actionable - covered - KNOWN_UNCOVERED_BLOCKED
    assert not uncovered_unaccounted, (
        f"골든 커버도 블로커 등록도 없는 actionable threat_event: {sorted(uncovered_unaccounted)}. "
        f"examples/expected_*.json 골든을 추가하거나 KNOWN_UNCOVERED_BLOCKED 에 사유와 함께 등록하라."
    )


def test_covered_events_match_expected_actionable_set() -> None:
    """골든이 실제 커버하는 집합 == actionable - 블로커 (은닉 미탐 0)."""
    assert _golden_covered_primaries() == (_actionable_threats() - KNOWN_UNCOVERED_BLOCKED)


def test_blocked_events_are_not_actually_covered() -> None:
    """블로커 목록은 아직 골든으로 커버되지 않은 상태여야 한다.

    블로커가 해소돼 골든이 생기면 KNOWN_UNCOVERED_BLOCKED 에서 제거하도록 강제한다.
    """
    still_blocked = KNOWN_UNCOVERED_BLOCKED & _golden_covered_primaries()
    assert not still_blocked, (
        f"블로커 해소됨 — KNOWN_UNCOVERED_BLOCKED 에서 제거 필요: {sorted(still_blocked)}"
    )


def test_t6_is_background_only_never_primary() -> None:
    """T6 은 어떤 골든에서도 primary 로 올라오지 않는다(배경 트랙, 04 §T6)."""
    assert "T6" not in _golden_covered_primaries()
