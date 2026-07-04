"""finalize 운용자 오버라이드 — AI 초안을 사람이 필드단위로 확정/수정 (SCC-1). TDD.

스펙 원칙(run.py): AI 는 후보만, 최종 결정은 사람. 기존 finalize 는 전체 승인/반려만 가능했다.
이 확장은 운용자가 승인 시 GCS-소유 결정필드를 수정(override)하고, 무엇을 바꿨는지 감사기록한다.
오버라이드는 알려진 결정필드로만 제한(온보드-소유·미지 필드 주입 금지) — 레이어 계약/SCC-1 보호.
"""

import copy

import pytest

from gcs.layer_01_info_center.run import assemble_draft, finalize


def _draft():
    return assemble_draft({
        "sortie_id": "S-01",
        "directive_text": "적 저격조 첩보 확인됨.",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"spare_asset_available": True, "armament": [], "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "c4i": {"enemy_situation": ["적 저격조"], "known_mission": "정찰"},
    })


def test_no_overrides_unchanged_backward_compat():
    out = finalize(_draft(), approved=True, ts_ms=1)
    assert out["mission_brief"]["posture"]["defcon"] == 3
    assert not out.get("applied_overrides")


def test_override_posture_field_and_audit_record():
    out = finalize(_draft(), approved=True, ts_ms=1,
                   overrides={"posture": {"watchcon": 2, "defcon": 2, "infocon": 3}})
    assert out["mission_brief"]["posture"]["defcon"] == 2, "운용자 수정이 브리핑에 반영"
    rec = out["applied_overrides"]["posture"]
    assert rec["from"] == {"watchcon": 3, "defcon": 3, "infocon": 4}
    assert rec["to"] == {"watchcon": 2, "defcon": 2, "infocon": 3}


def test_override_unknown_field_rejected():
    with pytest.raises(ValueError):
        finalize(_draft(), approved=True, ts_ms=1, overrides={"secret_backdoor": 1})


def test_override_sortie_id_locked():
    # sortie_id 는 식별자(운용자 결정필드 아님) — 수정 금지.
    with pytest.raises(ValueError):
        finalize(_draft(), approved=True, ts_ms=1, overrides={"sortie_id": "HIJACK"})


def test_overrides_require_approval():
    with pytest.raises(ValueError):
        finalize(_draft(), approved=False, ts_ms=1, overrides={"mission_context": "타격"})


def test_no_override_keeps_mettc_state():
    out = finalize(_draft(), approved=True, ts_ms=1)
    assert out["mettc_state"] is not None, "오버라이드 없으면 mettc_state 유지(하위호환)"


def test_mettc_state_superseded_when_overridden():
    # 오버라이드 시 mettc_state(AI 초안)는 브리핑과 불일치 → 정본 아님. 노출 대신 브리핑 authoritative.
    out = finalize(_draft(), approved=True, ts_ms=1, overrides={"posture": {"watchcon": 1, "defcon": 1, "infocon": 1}})
    assert out.get("mettc_state") is None, "오버라이드 시 stale mettc_state 는 omit"
    assert out["mission_brief"]["posture"]["defcon"] == 1
    assert out["applied_overrides"]["posture"]["to"]["defcon"] == 1


def test_partial_dict_override_merges_not_drops():
    # posture 부분 오버라이드 → 나머지 키 보존 (병합, codex P2).
    out = finalize(_draft(), approved=True, ts_ms=1, overrides={"posture": {"defcon": 1}})
    p = out["mission_brief"]["posture"]
    assert p == {"watchcon": 3, "defcon": 1, "infocon": 4}, "defcon 만 바뀌고 나머지 보존"


def test_override_invalid_mission_context_rejected():
    with pytest.raises(ValueError):
        finalize(_draft(), approved=True, ts_ms=1, overrides={"mission_context": "없는임무"})


def test_override_valid_mission_context_ok():
    out = finalize(_draft(), approved=True, ts_ms=1, overrides={"mission_context": "타격"})
    assert out["mission_brief"]["mission_context"] == "타격"


def test_override_wrong_type_rejected():
    # 형태가 틀린 값(예: posture=정수)은 하류 crash 유발 → 거부 (codex P2).
    with pytest.raises(ValueError):
        finalize(_draft(), approved=True, ts_ms=1, overrides={"posture": 1})
    with pytest.raises(ValueError):
        finalize(_draft(), approved=True, ts_ms=1, overrides={"corridor": None})
    with pytest.raises(ValueError):
        finalize(_draft(), approved=True, ts_ms=1, overrides={"mission_context": {"x": 1}})


def test_original_draft_not_mutated():
    draft = _draft()
    before = copy.deepcopy(draft["draft_brief"])
    finalize(draft, approved=True, ts_ms=1, overrides={"mission_context": "타격"})
    assert draft["draft_brief"] == before, "오버라이드는 원본 draft 를 변형하지 않음(복사)"
