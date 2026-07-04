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
from runner import _ENEMY_DETECT_RADIUS_M as _RUNNER_DEFAULT_RADIUS  # noqa: E402

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


def test_encounter_triggers_evasion_response_fed_back():
    # seed 이벤트(팝업 위협) 구간: 위협 탐지 + 비-MAINTAIN 회피 응답이 결정론적으로
    # 발생하고, 그 flight_plan 이 다음 tick world command 로 되먹여진다(폐루프).
    # (world 의 방위 조향 자체는 test_world 에서 명시 command 로 결정론 검증 — 여기서
    #  heading 값 단정은 파이프라인 float 응답에 의존해 py 버전 간 갈릴 수 있어 피한다.)
    frames = run_closed_loop(_BRIEF, seed=42, ticks=14)
    assert any((f["result"]["threat"].get("primary") or {}).get("threat_event")
               for f in frames), "조우 구간 위협 미탐"
    actions = [f["result"]["flight_plan"]["flight_action"] for f in frames]
    assert any(a != "MAINTAIN" for a in actions), "회피 응답(비-MAINTAIN) 없음"


def test_evade_phase_when_response_gives_bearing():
    # 회피 응답에 target_bearing(replan≠NONE)이 실리는 tick 은 world 가 EVADE 로 조향한다.
    # 응답이 방위를 제공하는 경우에 한해(파이프라인 의존) 폐루프 굴절을 확인한다.
    frames = run_closed_loop(_BRIEF, seed=42, ticks=14)
    for f in frames:
        fp = f["result"]["flight_plan"]
        if fp.get("target_bearing_deg") is not None and fp.get("replan_scope", "NONE") != "NONE":
            # 다음 tick 에서 EVADE 로 조향됨(되먹임). 최소 1회 발생하면 충분.
            assert any(fr["world"]["phase"] == "EVADE" for fr in frames)
            break


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


def test_tick_payload_ts_reflects_dt():
    frames = run_closed_loop(_BRIEF, seed=42, ticks=3, dt=2.0)
    scen = build_scenario(_BRIEF, seed=42)
    p = build_tick_payload(2, int(2 * 2.0 * 1000), "SIM-0002", frames[2]["world"], frames[2]["result"], scen["enemies"])
    assert p["ts_ms"] == 4000  # seq(2) * dt(2.0) * 1000


# --- F3: E.tracks(관측소 폼) → sim 적 배치 (#151 F3) ---

_ETRACKS_BRIEF = {
    **_BRIEF,
    "enemy_tracks": [
        {"id": "trk-1", "kind": "T3", "lat": 37.52, "lon": 127.02, "radius_m": 260, "confidence": 0.9},
        {"id": "trk-2", "kind": "T3", "lat": 37.55, "lon": 127.06, "radius_m": 220, "confidence": 0.85},
    ],
}


def test_place_enemies_uses_enemy_tracks_when_present():
    from runner import place_enemies
    enemies = place_enemies(_ETRACKS_BRIEF, seed=42)
    assert [e["id"] for e in enemies] == ["trk-1", "trk-2"]
    assert enemies[0]["pos"] == {"lat": 37.52, "lon": 127.02}
    assert enemies[0]["detect_radius_m"] == 260
    assert enemies[1]["detect_radius_m"] == 220


def test_place_enemies_seed_fallback_without_tracks():
    from runner import place_enemies
    enemies = place_enemies(_BRIEF, seed=42)  # enemy_tracks 없음
    assert len(enemies) == 1 and enemies[0]["id"] == "E1"


def test_build_scenario_route_avoids_etrack_enemies():
    from runner import build_scenario
    from route import _segment_clearance
    scen = build_scenario(_ETRACKS_BRIEF, seed=42)
    route = scen["route"]
    # feasible(끝점 원 밖) 적에 대해 모든 leg 가 detect_radius 밖.
    for e in scen["enemies"]:
        legs = [_segment_clearance(route[i], route[i + 1], e) for i in range(len(route) - 1)]
        # 회피 가능한(끝점 원 밖) 적은 leg clearance 보장.
        from route import haversine_m
        if all(haversine_m(wp, e["pos"]) >= e["detect_radius_m"] for wp in (route[0], route[-1])):
            assert all(c >= e["detect_radius_m"] for c in legs), \
                f"{e['id']} leg 위반: {[round(c,1) for c in legs]}"


def test_etracks_deterministic():
    from runner import place_enemies
    assert place_enemies(_ETRACKS_BRIEF, 42) == place_enemies(_ETRACKS_BRIEF, 7)  # seed 무관(트랙 고정)


def test_place_enemies_accepts_c4i_pos_list_shape():
    # C4I/assemble_mettc 정본 형상 {track_id, kind, pos:[lat,lon], confidence} 수용 (#195 P2).
    from runner import place_enemies
    brief = {**_BRIEF, "enemy_tracks": [
        {"track_id": "t1", "kind": "humint", "pos": [37.53, 127.03], "confidence": 0.8},
    ]}
    enemies = place_enemies(brief, seed=42)
    assert len(enemies) == 1
    assert enemies[0]["id"] == "t1"
    assert enemies[0]["pos"] == {"lat": 37.53, "lon": 127.03}
    assert enemies[0]["detect_radius_m"] == _RUNNER_DEFAULT_RADIUS  # radius 없음 → 기본


def test_place_enemies_pos_dict_shape():
    from runner import place_enemies
    brief = {**_BRIEF, "enemy_tracks": [{"track_id": "t1", "pos": {"lat": 37.53, "lon": 127.03}}]}
    assert place_enemies(brief, 42)[0]["pos"] == {"lat": 37.53, "lon": 127.03}


def test_place_enemies_all_malformed_falls_back_to_seed():
    # 형상 불일치(위치 해석 불가) 트랙만 있으면 조용히 0기가 아니라 seed 폴백 (#195 P2).
    from runner import place_enemies
    brief = {**_BRIEF, "enemy_tracks": [{"kind": "humint", "label": "위치없음"}, {"foo": 1}]}
    enemies = place_enemies(brief, seed=42)
    assert len(enemies) == 1 and enemies[0]["id"] == "E1"  # seed 폴백


def test_place_enemies_accepts_c4i_radius_field():
    # C4I/B-1 정본 형상은 radius_m 이 아니라 radius (예: docs/D4D/B-1.md {..radius:40}) (#218).
    from runner import place_enemies
    brief = {**_BRIEF, "enemy_tracks": [
        {"track_id": "t1", "kind": "humint", "pos": [37.53, 127.03], "radius": 250, "confidence": 0.8},
    ]}
    assert place_enemies(brief, seed=42)[0]["detect_radius_m"] == 250  # 400 고정이면 버그


def test_place_enemies_radius_m_takes_precedence():
    from runner import place_enemies
    brief = {**_BRIEF, "enemy_tracks": [
        {"id": "e1", "lat": 37.53, "lon": 127.03, "radius_m": 300, "radius": 999},
    ]}
    assert place_enemies(brief, seed=42)[0]["detect_radius_m"] == 300  # 폼 radius_m 우선


def test_place_enemies_malformed_radius_falls_back_to_default():
    # 운용자 폼 malformed radius(비숫자) → 크래시 대신 기본 반경.
    from runner import place_enemies, _ENEMY_DETECT_RADIUS_M
    brief = {**_BRIEF, "enemy_tracks": [{"lat": 37.55, "lon": 127.05, "radius_m": "big"}]}
    e = place_enemies(brief, seed=1)
    assert e[0]["detect_radius_m"] == _ENEMY_DETECT_RADIUS_M


def test_place_enemies_malformed_latlon_skips_track():
    # lat/lon 비숫자 → 트랙 스킵(다운스트림 haversine 크래시 방지) → seed 폴백.
    from runner import place_enemies
    brief = {**_BRIEF, "enemy_tracks": [{"lat": "x", "lon": 127.0}]}
    e = place_enemies(brief, seed=1)
    assert len(e) == 1 and e[0]["id"] == "E1"  # 유효 트랙 0 → seed 폴백


def test_build_scenario_survives_malformed_etrack():
    # malformed radius 트랙이 있어도 시나리오 빌드(route/haversine)가 크래시하지 않음.
    from runner import build_scenario
    brief = {**_BRIEF, "enemy_tracks": [{"lat": 37.55, "lon": 127.05, "radius_m": "big"}]}
    scen = build_scenario(brief, seed=1)
    assert scen["enemies"][0]["detect_radius_m"] == 400.0
