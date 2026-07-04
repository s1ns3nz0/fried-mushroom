"""Regression guard: world movement must not fabricate a T1 (GPS-spoofing) threat.

envelope.synthesize moves the drone's gps lat/lon along the route each tick.
The 03 position_consistency channel compares gps vs the imu inertial estimate
(gps_imu_residual_m); if the envelope only advances gps and leaves the imu
estimate at its baseline, the growing residual trips T1 falsely on ticks with
no active threat event (a phantom threat on the dashboard).

This test runs a baseline flight and asserts that on every tick WITHOUT an
active threat event, the onboard pipeline does not report T1 as the primary
threat. The team infra/sim envelope holds gps == imu to keep this invariant;
infra/vizsim must too.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))       # vizsim 패키지
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vizsim import runner  # noqa: E402

BRIEF_PATH = Path(__file__).resolve().parents[2] / "examples" / "mission_brief_t3.json"


def _load_brief() -> dict:
    return json.loads(BRIEF_PATH.read_text(encoding="utf-8"))


def test_baseline_ticks_without_events_never_report_t1_primary():
    brief = _load_brief()
    records = runner.run_ticks(42, brief, 40, 1.0)

    baseline = [rec for rec in records if not rec["snapshot"]["active_events"]]
    assert baseline, "expected at least one tick with no active threat event"

    for rec in baseline:
        primary = rec["result"]["threat"]["primary"] or {}
        assert primary.get("threat_event") != "T1", (
            f"tick seq={rec['snapshot']['seq']} (no active_events) falsely "
            f"reported a T1 GPS-spoofing threat from world movement"
        )
