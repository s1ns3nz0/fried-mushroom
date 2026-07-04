"""step4 — 11채널 파이프라인 계약 테스트."""

import json
from pathlib import Path

from onboard.layer_03_abstraction.run import run

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"

_EXPECTED_ORDER = [
    "position_consistency",
    "link_status",
    "link_integrity",
    "encryption_status",
    "rf_spectrum",
    "mission_phase",
    "obstacle_proximity",
    "operational_margin",
    "proximity_object",
    "terrain_class",
    "acoustic_event",
]


def test_eleven_channels_exact_order():
    raw = json.loads((EXAMPLES_DIR / "raw_t3.json").read_text("utf-8"))
    out = run(raw)
    assert [c["channel"] for c in out["channels"]] == _EXPECTED_ORDER
