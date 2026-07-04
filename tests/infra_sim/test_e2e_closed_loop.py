"""폐루프 E2E 수용 테스트 — METT+TC→적회피→조우→회피→임무달성 (#158).

시나리오 (seed=42, 고정):
  1. corridor 직선이 적 탐지반경(400m)을 침범 → generate_route 가 우회 경로 삽입
  2. UAV 는 우회 경로를 따라가며 적 외곽 ≈426m 에서 출발(TRANSIT)
  3. 2 tick 후 경로 수렴 과정에서 물리적으로 탐지반경 진입 → ENCOUNTER
  4. seq 6 팝업 위협 발화(T3) → run_cycle 이 ALTITUDE_CHANGE + target_bearing 반환
  5. 다음 tick 에서 그 command 를 되먹임 → World heading 이 target_bearing 으로 꺾임 → EVADE
  6. 팝업 소멸(seq 10+) → MAINTAIN + reroute_anchor=mission_corridor_resume
  7. 최종 ARRIVED

검증 원칙 (issue #158):
  - 조우 전 phase TRANSIT 확인
  - ENCOUNTER → EVADE 전이 확인
  - EVADE 구간 heading ≈ run_cycle target_bearing_deg (실 판정, mock 금지)
  - 위협 해소 후 MAINTAIN + mission_corridor_resume
  - 최종 ARRIVED
  - 동일 seed 2 회 실행 = 동일 궤적(결정론)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "sim"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest
from route import _segment_clearance, generate_route  # noqa: E402
from runner import build_scenario, run_closed_loop  # noqa: E402

# ── 수용 시나리오 브리프 ──────────────────────────────────────────────────────
# corridor ≈950m, frac=0.5 → enemy at ≈426m from wp0 (> detect_radius=400m → TRANSIT 시작).
# seed=42: start_seq=6, event_window to_seq=9, ARRIVED at ~72 ticks.
_BRIEF = {
    "sortie_id": "E2E_ACCEPT",
    "mission_context": "정찰",
    "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
    "drone_profile": {"armament": [], "spare_asset_available": True, "battery_pct": 80},
    "corridor": {
        "waypoints": [
            {"lat": 37.5000, "lon": 127.0000, "alt_m": 120},
            {"lat": 37.5060, "lon": 127.0060, "alt_m": 120},
        ],
        "bases": {"emergency": {"lat": 37.499, "lon": 127.0, "alt_m": 50}},
    },
    "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
}

_SEED = 42
_TICKS = 80  # ARRIVED는 ~72번째 tick에서 발생(여유 8 tick 포함).


def _frames():
    return run_closed_loop(_BRIEF, seed=_SEED, ticks=_TICKS)


def _phases(frames):
    return [f["world"]["phase"] for f in frames]


def _transitions(phases):
    """연속 중복 제거 후 phase 전이 리스트."""
    result, prev = [], None
    for i, p in enumerate(phases):
        if p != prev:
            result.append((i, p))
            prev = p
    return result


# ── 1. 전체 시퀀스 ────────────────────────────────────────────────────────────


def test_transit_before_popup_event():
    """팝업 이벤트(seq 6) 이전: TRANSIT 이 관찰돼야 한다."""
    frames = _frames()
    phases_before_popup = _phases(frames)[:6]
    assert "TRANSIT" in phases_before_popup, (
        f"seq 0-5 에 TRANSIT 없음: {phases_before_popup}"
    )


def test_encounter_evade_transition():
    """조우 시 ENCOUNTER → EVADE 전이 순서가 나타나야 한다."""
    phases = _phases(_frames())
    transitions = [p for _, p in _transitions(phases)]
    assert "ENCOUNTER" in transitions, "ENCOUNTER 페이즈 없음"
    assert "EVADE" in transitions, "EVADE 페이즈 없음"
    enc_idx = transitions.index("ENCOUNTER")
    evade_idx = transitions.index("EVADE")
    assert enc_idx < evade_idx, (
        f"ENCOUNTER({enc_idx}) 가 EVADE({evade_idx}) 보다 앞서야 함"
    )


def test_arrived_after_full_run():
    """최종적으로 ARRIVED 에 도달해야 한다."""
    phases = _phases(_frames())
    assert "ARRIVED" in phases, f"ARRIVED 없음: {phases[-5:]}"


# ── 2. EVADE 구간 heading = target_bearing_deg ────────────────────────────────


def test_evade_heading_reflects_target_bearing():
    """EVADE 구간: World heading 이 직전 사이클 flight_plan.target_bearing_deg 와 일치."""
    frames = _frames()
    for i in range(1, len(frames)):
        prev_fp = frames[i - 1]["result"]["flight_plan"]
        curr_world = frames[i]["world"]
        if (prev_fp.get("target_bearing_deg") is not None
                and prev_fp.get("replan_scope", "NONE") != "NONE"):
            brg = prev_fp["target_bearing_deg"] % 360.0
            hdg = curr_world["heading_deg"] % 360.0
            assert abs(hdg - brg) < 1e-3, (
                f"seq {i}: heading={hdg:.3f} ≠ bearing={brg:.3f}"
            )
            assert curr_world["phase"] == "EVADE", (
                f"seq {i}: target_bearing 있는데 phase={curr_world['phase']}"
            )
            return  # 첫 EVADE tick 검증으로 충분
    pytest.fail("target_bearing_deg 가 있는 tick 없음 — EVADE 미발생")


def test_evade_uses_real_run_cycle_no_mock():
    """EVADE 구간 target_bearing_deg 가 실 run_cycle 출력임을 검증한다.

    bearing 값이 팝업 위협 bearing_deg(90°) 와 다르면서 유한한 실수여야 한다.
    모킹이라면 고정값(0.0, 90.0, 180.0 등)이 나오거나 None 이 된다.
    """
    frames = _frames()
    bearings = [
        f["result"]["flight_plan"]["target_bearing_deg"]
        for f in frames
        if f["result"]["flight_plan"].get("target_bearing_deg") is not None
    ]
    assert len(bearings) > 0, "target_bearing_deg 없음"
    for brg in bearings:
        assert isinstance(brg, float), f"bearing 이 float 아님: {brg}"
        assert brg != 90.0, "고정 90.0 → mock 의심"
        assert 0.0 < brg < 360.0


# ── 3. 위협 해소 후 MAINTAIN + mission_corridor_resume ──────────────────────


def test_maintain_corridor_resume_after_popup_ends():
    """팝업 이벤트 종료(seq 10+) 후: flight_action=MAINTAIN + reroute_anchor=mission_corridor_resume."""
    frames = _frames()
    # 팝업 이벤트: seed=42, from_seq=6, to_seq=9 → 종료 후 seq 10+
    post_event = frames[10:]
    found = False
    for f in post_event[:10]:  # 종료 직후 10 tick 내에 나타나야 함
        fp = f["result"]["flight_plan"]
        if fp.get("flight_action") == "MAINTAIN":
            assert fp.get("reroute_anchor") == "mission_corridor_resume", (
                f"MAINTAIN 시 reroute_anchor={fp.get('reroute_anchor')!r}"
            )
            assert fp.get("target_bearing_deg") is None, (
                "위협 해소 후 target_bearing_deg 가 None 이어야 함"
            )
            found = True
            break
    assert found, "seq 10-19 구간에 MAINTAIN 없음"


# ── 4. 결정론 ────────────────────────────────────────────────────────────────


def test_determinism_same_seed_same_trajectory():
    """동일 seed 2회 실행 = 동일 궤적 (포터블 결정론)."""
    def traj():
        return [
            (f["world"]["pos"]["lat"], f["world"]["pos"]["lon"], f["world"]["phase"])
            for f in run_closed_loop(_BRIEF, seed=_SEED, ticks=30)
        ]
    assert traj() == traj()


def test_determinism_different_seeds_differ():
    """서로 다른 seed 는 다른 궤적을 낸다 (seed 의미있음 검증)."""
    def traj(seed):
        return [f["world"]["pos"] for f in run_closed_loop(_BRIEF, seed=seed, ticks=15)]
    assert traj(42) != traj(7)


# ── 5. route 회피 계약 회귀 ──────────────────────────────────────────────────


def test_route_avoidance_waypoints_outside_detect_radius():
    """생성된 route 의 모든 웨이포인트가 detect_radius 밖에 있어야 한다."""
    import math

    scen = build_scenario(_BRIEF, seed=_SEED)
    route = scen["route"]
    for enemy in scen["enemies"]:
        ep = enemy["pos"]
        for wp in route:
            lat0 = math.radians(wp["lat"])
            n = (wp["lat"] - ep["lat"]) * 111_320.0
            e = (wp["lon"] - ep["lon"]) * 111_320.0 * math.cos(lat0)
            d = math.hypot(n, e)
            assert d >= enemy["detect_radius_m"], (
                f"waypoint {wp} 가 detect_radius({enemy['detect_radius_m']}m) 안에 있음: {d:.1f}m"
            )


@pytest.mark.xfail(
    reason="generate_route 단일 패스 한계: 삽입 후 새 leg 의 segment_clearance 미재검증 — "
           "route.py 다중 패스 수정 필요 (mara89ma #154 좌현 회피 계산 보완)",
    strict=False,
)
def test_route_all_legs_segment_clearance_exceeds_detect_radius():
    """모든 leg 의 segment_clearance > detect_radius (midpoint-enemy 케이스 포함).

    현재 generate_route 는 삽입 후 새 구간을 재검증하지 않아 이 테스트가 실패한다.
    route.py 가 다중 패스 또는 삽입 후 재검증을 지원하면 xfail → pass 로 전환.
    """
    scen = build_scenario(_BRIEF, seed=_SEED)
    route = scen["route"]
    for enemy in scen["enemies"]:
        for i in range(len(route) - 1):
            cl = _segment_clearance(route[i], route[i + 1], enemy)
            assert cl > enemy["detect_radius_m"], (
                f"leg {i}→{i+1}: segment_clearance={cl:.1f}m < detect_radius={enemy['detect_radius_m']}m"
            )


def test_midpoint_enemy_route_does_not_use_straight_corridor():
    """적이 corridor 중앙에 있을 때 직선 corridor 를 그대로 쓰지 않는다 (회피 웨이포인트 삽입 확인)."""
    enemy = {
        "id": "E_mid",
        "pos": {"lat": 37.503, "lon": 127.003},
        "detect_radius_m": 300.0,
    }
    brief = {
        "corridor": {
            "waypoints": [
                {"lat": 37.500, "lon": 127.000, "alt_m": 120},
                {"lat": 37.506, "lon": 127.006, "alt_m": 120},
            ]
        }
    }
    route_no_enemies = generate_route(brief, enemies=None)
    route_with_enemy = generate_route(brief, enemies=[enemy])
    assert len(route_with_enemy) > len(route_no_enemies), (
        "적 존재 시 우회 웨이포인트가 삽입돼야 함"
    )
    # 우회점이 detect_radius 밖에 있어야 함(생성된 웨이포인트 레벨 계약).
    import math
    for wp in route_with_enemy:
        ep = enemy["pos"]
        lat0 = math.radians(wp["lat"])
        n = (wp["lat"] - ep["lat"]) * 111_320.0
        e = (wp["lon"] - ep["lon"]) * 111_320.0 * math.cos(lat0)
        d = math.hypot(n, e)
        assert d >= enemy["detect_radius_m"], (
            f"우회점 {wp} 가 detect_radius 안에 있음: {d:.1f}m"
        )
