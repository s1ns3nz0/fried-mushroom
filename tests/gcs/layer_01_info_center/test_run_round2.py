"""run 라운드2 — mettc_state 포함 2단계 오케스트레이션 검증 (TDD).

assemble_draft → {mettc_state, draft_brief, signal_cards, warnings}
finalize(approved) → {mission_brief, mettc_state, approved_ts_ms}
킬러 ②(투영본 → run_cycle 종단)는 test_integration_onboard.py 회귀가 커버.
"""

from gcs.layer_01_info_center.run import assemble_draft, finalize

_METTC_KEYS = {"M", "E", "T_terrain", "T_troops", "T_time", "C"}
_BRIEF_KEYS = {"sortie_id", "mission_context", "posture", "drone_profile", "corridor", "weights"}


def _inputs(**over):
    base = {
        "sortie_id": "R2-01",
        "directive_text": "적 저격조 첩보 확인됨. 박격포 진지 식별. 민가 인접 확인. 본 임무는 정찰이다.",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"spare_asset_available": False, "armament": [], "battery_pct": 65,
                          "endurance_rated_s": 1800},
        "corridor_spec": {"type": "polyline_buffer", "axis": [[37.70, 127.20], [37.72, 127.22]],
                          "half_width": 20, "alt_min": 50, "alt_max": 300},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "bases": [{"id": "home", "pos": [37.70, 127.20], "type": "home", "available": True}],
        "c4i": {
            "enemy_tracks": [{"track_id": "t1", "kind": "humint", "pos": [37.71, 127.21],
                              "confidence": 0.8, "label": "적 저격조 활동"}],
            "civil_density_draft": [{"id": "c-1", "center": [37.7, 127.2], "radius": 10, "density": "high"}],
            "asset_management": {"spare_asset_available": False},
        },
    }
    base.update(over)
    return base


def test_draft_carries_mettc_state_and_projected_brief() -> None:
    out = assemble_draft(_inputs())
    assert set(out) >= {"mettc_state", "draft_brief", "signal_cards", "warnings"}
    assert set(out["mettc_state"]["mettc"]) == _METTC_KEYS
    assert set(out["draft_brief"]) == _BRIEF_KEYS
    assert out["draft_brief"]["corridor"]["waypoints"][0]["lat"] == 37.70


def test_cards_reflect_round2_signals_with_corroboration() -> None:
    out = assemble_draft(_inputs())
    cards = out["signal_cards"]
    types = {c["signal_type"] for c in cards}
    assert {"threat", "severity", "civil"} <= types
    sniper = next(c for c in cards if c["source_phrase"] == "저격조")
    assert sniper["adjust_reason"]  # ① tracks 확증
    civil = next(c for c in cards if c["signal_type"] == "civil")
    assert civil["adjust_reason"]  # ④ 밀집도 확증


def test_finalize_returns_state_and_brief() -> None:
    res = finalize(assemble_draft(_inputs()), approved=True, ts_ms=42)
    assert set(res) >= {"mission_brief", "mettc_state", "approved_ts_ms"}
    assert res["approved_ts_ms"] == 42
    assert set(res["mission_brief"]) == _BRIEF_KEYS


def test_finalize_rejected_still_pending_no_brief() -> None:
    res = finalize(assemble_draft(_inputs()), approved=False, ts_ms=1)
    assert res["status"] == "pending_approval"
    assert "mission_brief" not in res


def test_legacy_flat_inputs_backward_compatible() -> None:
    # 기존 flat set_mission (corridor 형·c4i 레거시) — 계속 동작.
    legacy = {
        "sortie_id": "LEG-01",
        "directive_text": "적 저격조 확인됨",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"spare_asset_available": True, "armament": [], "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "c4i": {"enemy_situation": ["적 저격조 확인"]},
    }
    out = assemble_draft(legacy)
    assert set(out["draft_brief"]) == _BRIEF_KEYS
    assert out["draft_brief"]["mission_context"] == "정찰"
    sniper = next(c for c in out["signal_cards"] if c["source_phrase"] == "저격조")
    assert sniper["adjust_reason"]  # 레거시 승격 경유 확증
