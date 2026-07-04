"""infra/sim runner.py — 폐루프(build_scenario + flight_plan 되먹임) + tick payload. TDD.

seed 결정론 시나리오 → world.tick(command) → envelope → run_cycle(실 판정) →
flight_plan 을 다음 tick command 로 되먹임. seed 이벤트(팝업 위협) 구간에 궤적이
실제로 꺾인다(회피). 같은 seed = 동일 궤적(재현성).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "sim"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runner import build_scenario, run_closed_loop, build_tick_payload  # noqa: E402

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


def test_build_scenario_deterministic():
    a = build_scenario(_BRIEF, seed=42)
    b = build_scenario(_BRIEF, seed=42)
    assert a["enemies"] == b["enemies"]
    assert a["events"] == b["events"]


def test_closed_loop_returns_frame_per_tick():
    frames = run_closed_loop(_BRIEF, seed=42, ticks=8)
    assert len(frames) == 8
    for f in frames:
        assert "world" in f and "result" in f
        assert "flight_plan" in f["result"]


def test_closed_loop_deterministic_same_seed():
    def traj(seed):
        return [(round(f["world"]["pos"]["lat"], 7), round(f["world"]["pos"]["lon"], 7))
                for f in run_closed_loop(_BRIEF, seed=seed, ticks=10)]
    assert traj(42) == traj(42)


def test_encounter_bends_trajectory_vs_no_threat():
    # seed 이벤트(팝업 위협) 구간에서 flight_action 이 MAINTAIN 을 벗어나고 헤딩이 바뀐다.
    frames = run_closed_loop(_BRIEF, seed=42, ticks=14)
    actions = [f["result"]["flight_plan"]["flight_action"] for f in frames]
    assert any(a != "MAINTAIN" for a in actions), "조우 구간에 회피 지시가 없음"
    headings = [f["world"]["heading_deg"] for f in frames]
    assert len(set(round(h, 1) for h in headings)) > 1, "궤적이 전혀 안 꺾임"


def test_tick_payload_shape():
    frames = run_closed_loop(_BRIEF, seed=42, ticks=3)
    scen = build_scenario(_BRIEF, seed=42)
    p = build_tick_payload(2, 2000, "SIM-0002", frames[2]["world"], frames[2]["result"], scen["enemies"])
    assert p["type"] == "tick" and p["seq"] == 2
    assert "world" in p and "pos" in p["world"] and "enemies" in p["world"]
    for k in ("abstraction", "threat", "risk", "response", "flight_plan"):
        assert k in p
    assert "channels" in p["abstraction"]


# --- CLI (TODO 7): 폐루프 실행 → tick payload 출력/전송 (--collector 없으면 stdout) ---


def test_cli_dry_run_prints_tick_payloads(capsys, tmp_path):
    import json as _json
    brief_p = tmp_path / "brief.json"
    brief_p.write_text(_json.dumps(_BRIEF), encoding="utf-8")
    from runner import main
    rc = main(["--seed", "42", "--ticks", "3", "--brief", str(brief_p)])
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    # tick 라인 3개, 각 JSON tick payload.
    ticks = [l for l in out if '"type": "tick"' in l or '"type":"tick"' in l]
    assert len(ticks) == 3
    p = _json.loads(ticks[0])
    assert p["type"] == "tick" and "world" in p and "flight_plan" in p


def test_cli_missing_brief_errors():
    from runner import main
    assert main(["--seed", "1", "--ticks", "1", "--brief", "/no/such.json"]) == 2
