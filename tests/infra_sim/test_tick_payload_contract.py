"""tick payload 계약 회귀 (#163) — build_tick_payload 출력이 infra/sim/README 스키마와 일치.

README 의 정본 스키마(필수 키·타입·ts_ms 공식·phase enum)를 코드에 고정한다. 필드명
드리프트(F2 hobeen app.js / F3 mara E.tracks 핸드오프) 방지. 앱 로직 무변경 — 계약만.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "sim"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runner import build_scenario, build_tick_payload, run_closed_loop  # noqa: E402

_BRIEF = {
    "sortie_id": "SIM", "mission_context": "정찰",
    "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
    "drone_profile": {"armament": [], "spare_asset_available": True, "battery_pct": 80},
    "corridor": {"waypoints": [
        {"lat": 37.50, "lon": 127.00, "alt_m": 120},
        {"lat": 37.60, "lon": 127.10, "alt_m": 120},
    ], "bases": {"emergency": {"lat": 37.49, "lon": 127.0, "alt_m": 50}}},
    "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
}
_TOP_KEYS = {"type", "seq", "ts_ms", "correlation_id",
             "world", "abstraction", "threat", "risk", "response", "flight_plan"}
_WORLD_KEYS = {"pos", "heading_deg", "speed_mps", "phase", "enemies"}
_PHASES = {"TRANSIT", "ENCOUNTER", "EVADE", "RTL", "ARRIVED"}


def _payload(seq=2, dt=1.0):
    frames = run_closed_loop(_BRIEF, seed=42, ticks=seq + 1, dt=dt)
    scen = build_scenario(_BRIEF, seed=42)
    return build_tick_payload(seq, int(seq * dt * 1000), f"SIM-{seq:04d}",
                              frames[seq]["world"], frames[seq]["result"], scen["enemies"])


def test_top_level_keys_match_readme():
    assert set(_payload().keys()) == _TOP_KEYS


def test_type_and_seq_contract():
    p = _payload(seq=3)
    assert p["type"] == "tick"
    assert p["seq"] == 3 and isinstance(p["seq"], int)
    assert p["correlation_id"].startswith("SIM-")


def test_ts_ms_formula():
    # ts_ms = int(seq * dt * 1000).
    assert _payload(seq=2, dt=1.0)["ts_ms"] == 2000
    assert _payload(seq=2, dt=2.0)["ts_ms"] == 4000
    assert _payload(seq=3, dt=0.5)["ts_ms"] == 1500


def test_world_block_contract():
    w = _payload()["world"]
    assert set(w.keys()) == _WORLD_KEYS
    assert set(w["pos"].keys()) == {"lat", "lon", "alt_m"}
    assert w["phase"] in _PHASES
    for e in w["enemies"]:
        assert set(e.keys()) >= {"id", "pos", "detect_radius_m"}


def test_pipeline_blocks_are_run_cycle_output():
    p = _payload()
    assert "channels" in p["abstraction"]  # 03 실출력
    for k in ("threat", "risk", "response", "flight_plan"):
        assert isinstance(p[k], dict)
    # flight_plan 은 07 계약 키 포함.
    assert "flight_action" in p["flight_plan"]


def test_speed_mode_enum_documented_values():
    # world speed 표가 07 enum(CAUTIOUS/NORMAL/MAX)을 반영(README 명시).
    from world import _SPEED_MODE_MPS
    assert set(_SPEED_MODE_MPS.keys()) == {"CAUTIOUS", "NORMAL", "MAX"}
