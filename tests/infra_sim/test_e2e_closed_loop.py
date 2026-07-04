"""폐루프 E2E 수용 테스트 (#158, #151 수용기준).

sim 코어 폐루프가 "METT+TC → 적회피 경로 → 경로상 조우(seed 팝업) → 실 run_cycle 판정
→ EVADE 궤적 굴절 → 위협 해소 후 corridor 복귀 → 임무 달성(ARRIVED)" 시퀀스를 실제로
통과하는지 종단 검증. **mock 금지 — run_cycle 실 판정**. tests-only.

주: route 가 적을 회피하므로 근접(ENCOUNTER)은 짧은 corridor 에서만 뜨고, EVADE 는
팝업 위협에 대한 run_cycle 응답(target_bearing)에서 나온다. 단위 route P2(midpoint-
enemy leg clearance)는 test_route.py 소관 — 여기선 E2E 관점 회피만 확인(중복 없음).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "sim"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from route import _segment_clearance, haversine_m  # noqa: E402
from runner import build_scenario, run_closed_loop  # noqa: E402

# 짧은 corridor(~600m) — 팝업 조우 후에도 modest tick 안에 ARRIVED 도달.
_BRIEF = {
    "sortie_id": "SIM", "mission_context": "정찰",
    "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
    "drone_profile": {"armament": [], "spare_asset_available": True, "battery_pct": 80},
    "corridor": {"waypoints": [
        {"lat": 37.5000, "lon": 127.0000, "alt_m": 120},
        {"lat": 37.5045, "lon": 127.0045, "alt_m": 120},
    ], "bases": {"emergency": {"lat": 37.499, "lon": 127.0, "alt_m": 50}}},
    "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
}


def _frames(seed=42, ticks=80):
    return run_closed_loop(_BRIEF, seed=seed, ticks=ticks)


def test_evade_transition_uses_real_target_bearing():
    # 팝업 조우 → run_cycle 이 target_bearing 산출 → 다음 tick world 가 그 방위로 EVADE.
    # heading 이 직전 tick 의 run_cycle target_bearing_deg 와 일치(실 판정, mock 아님).
    frames = _frames()
    phases = [f["world"]["phase"] for f in frames]
    assert "EVADE" in phases, "EVADE 미발생"
    evade_i = phases.index("EVADE")
    tb = frames[evade_i - 1]["result"]["flight_plan"]["target_bearing_deg"]
    assert tb is not None, "회피 방위(target_bearing_deg) 없음"
    # heading ≈ target_bearing (실 판정 반영; 마지막 자리 float 차는 무시).
    assert abs(frames[evade_i]["world"]["heading_deg"] - (tb % 360.0)) < 0.01


def test_threat_is_real_run_cycle_judgment():
    # mock 금지: 조우 구간에 04 primary 위협 event 가 실제로 산출됨.
    frames = _frames()
    assert any((f["result"]["threat"].get("primary") or {}).get("threat_event")
               for f in frames), "실 위협 판정 없음"


def test_resume_to_corridor_after_threat_clears():
    # EVADE 구간 뒤 위협 해소 → MAINTAIN + replan NONE + phase 가 EVADE 이탈(corridor 복귀).
    frames = _frames()
    phases = [f["world"]["phase"] for f in frames]
    last_evade = max(i for i, p in enumerate(phases) if p == "EVADE")
    tail = frames[last_evade + 1:]
    assert tail, "EVADE 이후 프레임 없음"
    resumed = tail[0]
    assert resumed["result"]["flight_plan"]["flight_action"] == "MAINTAIN"
    assert resumed["result"]["flight_plan"]["replan_scope"] == "NONE"
    assert resumed["world"]["phase"] != "EVADE"


def test_reaches_arrived():
    phases = [f["world"]["phase"] for f in _frames(ticks=100)]
    assert "ARRIVED" in phases, "임무 미달성(ARRIVED 없음)"


def test_full_sequence_order_transit_evade_arrived():
    # 시퀀스 순서: (초기 조우/이동) → EVADE → … → ARRIVED. EVADE 가 ARRIVED 보다 앞선다.
    phases = [f["world"]["phase"] for f in _frames(ticks=100)]
    assert phases.index("EVADE") < phases.index("ARRIVED")
    # EVADE 이전에는 ARRIVED 가 없다(도착 후 회피 없음).
    assert "ARRIVED" not in phases[:phases.index("EVADE")]


def test_deterministic_trajectory_same_seed():
    def traj(seed):
        return [(round(f["world"]["pos"]["lat"], 7), round(f["world"]["pos"]["lon"], 7),
                 f["world"]["phase"]) for f in _frames(seed=seed, ticks=50)]
    assert traj(42) == traj(42)


def test_route_avoids_feasible_enemies_e2e():
    # E2E 관점: 시나리오 적 중 회피 가능(끝점 원 밖)한 적은 경로 전 leg 가 탐지반경 밖.
    scen = build_scenario(_BRIEF, seed=42)
    route = scen["route"]
    for e in scen["enemies"]:
        feasible = all(haversine_m(wp, e["pos"]) >= e["detect_radius_m"]
                       for wp in (route[0], route[-1]))
        if feasible:
            legs = [_segment_clearance(route[i], route[i + 1], e) for i in range(len(route) - 1)]
            assert all(c >= e["detect_radius_m"] for c in legs)
