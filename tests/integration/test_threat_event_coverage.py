"""threat_event 종단 커버리지 잠금(메타 테스트).

목적: THREAT_CATALOG 의 "actionable" threat_event(= 실제로 candidates/primary 로
탐지되는 위협)가 examples/expected_*.json 골든(정본)으로 종단 커버되는지 잠근다.
신규 T-이벤트가 constants 에 추가됐는데 골든이 없으면 이 테스트가 시끄럽게 실패한다.

분류 근거(docs/D4D/04. Threat Modeling.md):
  - T6(환경노출도) 은 "threat_event 아님 — 배경 트랙"(§T6). candidates/primary 에 절대
    올라오지 않고 background_exposure_score 로만 소비되므로 커버리지 후보에서 제외.
  - 그 외 T1·T2·T3·T4·T5·T7 은 actionable.

T5 블로커(#79):
  T5 는 proximity_object/terrain_class 의 quality_delta < -0.3 로만 탐지된다. quality_delta
  는 03 이 previous_quality 대비 계산하는 "사이클 간 파생필드"라, 단일 사이클에서는 항상
  0.0 이다(_common.make_output: previous_quality is None → delta 0.0). 골든 정본을 만드는
  CLI(`python -m onboard raw brief`) 와 test_e2e_golden 은 둘 다 run_cycle 을
  previous_qualities 없이 1회 호출하므로, 현재 배선으로는 T5 골든을 만들 수 없다
  (orchestrator/CLI 가 previous_qualities 를 스레딩하도록 바꿔야 가능 — src 변경 필요).
  따라서 T5 는 KNOWN_UNCOVERED_BLOCKED 로 명시 제외하고, 블로커가 해소되면 아래 두 assert
  가 강제로 목록 갱신을 요구한다.
"""

import json
import pathlib

from onboard.shared.constants import THREAT_CATALOG

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"

# 배경 트랙(threat_event 아님) — 커버리지 후보에서 제외 (04 §T6).
BACKGROUND_ONLY_EVENTS = frozenset({"T6"})

# 현재 배선으로 종단 골든 재현 불가 — 블로커 해소 시 여기서 제거 (위 docstring 참조).
KNOWN_UNCOVERED_BLOCKED = frozenset({"T5"})


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
