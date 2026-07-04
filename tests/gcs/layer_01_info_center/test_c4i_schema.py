"""c4i_schema — 구조화 C4I 입력 정규화 검증 (TDD, B-1 §5.2)."""

from gcs.layer_01_info_center.c4i_schema import normalize_c4i


def test_structured_tracks_pass_through() -> None:
    raw = {
        "enemy_tracks": [
            {"track_id": "trk-1", "kind": "radar_track", "pos": [37.7, 127.2],
             "velocity": [1.2, -0.3], "confidence": 0.72, "label": "적 저격조 활동"}
        ],
        "asset_management": {"spare_asset_available": True},
        "known_mission": "정찰 감시",
    }
    c4i = normalize_c4i(raw)
    assert len(c4i["enemy_tracks"]) == 1
    t = c4i["enemy_tracks"][0]
    assert t["kind"] == "radar_track" and t["confidence"] == 0.72
    assert c4i["asset_management"]["spare_asset_available"] is True


def test_legacy_enemy_situation_promoted_to_tracks() -> None:
    # 레거시 문자열 배열 → report 트랙 승격 (B-1 §5.2).
    c4i = normalize_c4i({"enemy_situation": ["적 저격조 활동 확인", "차량 이동"]})
    assert len(c4i["enemy_tracks"]) == 2
    for t in c4i["enemy_tracks"]:
        assert t["kind"] == "report"
        assert t["confidence"] == 0.5
    assert c4i["enemy_tracks"][0]["label"] == "적 저격조 활동 확인"


def test_mixed_structured_and_legacy_merged() -> None:
    c4i = normalize_c4i({
        "enemy_tracks": [{"track_id": "t1", "kind": "radar_track", "pos": [0, 0], "confidence": 0.9, "label": "레이더"}],
        "enemy_situation": ["보고 항목"],
    })
    kinds = {t["kind"] for t in c4i["enemy_tracks"]}
    assert kinds == {"radar_track", "report"}


def test_empty_input_yields_empty_shape() -> None:
    c4i = normalize_c4i({})
    assert c4i["enemy_tracks"] == []
    assert c4i["civil_density_draft"] == []
    assert c4i["asset_management"] == {}
    assert c4i["known_mission"] is None


def test_none_input_tolerated() -> None:
    assert normalize_c4i(None)["enemy_tracks"] == []


def test_civil_density_draft_passthrough() -> None:
    c4i = normalize_c4i({"civil_density_draft": [{"id": "c-1", "center": [37.7, 127.2], "radius": 15, "density": "high"}]})
    assert c4i["civil_density_draft"][0]["density"] == "high"
