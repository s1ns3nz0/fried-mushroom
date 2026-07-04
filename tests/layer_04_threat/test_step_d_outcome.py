"""Step D (potential_outcome 매핑) 검증."""

from __future__ import annotations

import pytest

from onboard.layer_04_threat import step_d_outcome
from onboard.shared.constants import POTENTIAL_OUTCOME_MAP


def _scored(threat: str) -> dict:
    return {
        "threat_event": threat,
        "match_count": 1,
        "confidence": 0.7,
        "confidence_source": "deterministic",
        "kill_chain_stage": "중기",
        "_avg_weight": 0.35,
    }


@pytest.mark.parametrize("threat", ["T1", "T2", "T3", "T4", "T5", "T7"])
def test_potential_outcome_matches_map(threat: str) -> None:
    candidates = step_d_outcome.run([_scored(threat)])
    assert len(candidates) == 1
    assert candidates[0]["potential_outcome"] == POTENTIAL_OUTCOME_MAP[threat]


def test_preserves_scored_fields() -> None:
    candidates = step_d_outcome.run([_scored("T3")])
    c = candidates[0]
    assert c["threat_event"] == "T3"
    assert c["match_count"] == 1
    assert c["confidence"] == 0.7
    assert c["confidence_source"] == "deterministic"
    assert c["kill_chain_stage"] == "중기"


def test_empty() -> None:
    assert step_d_outcome.run([]) == []
