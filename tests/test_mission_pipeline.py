"""mission_pipeline — 01→07 종단 CLI 검증 (TDD).

set_mission → layer 01 → mission_brief → run_cycle. 승인 게이트(--approve):
없으면 리뷰만(온보드 미실행), 있으면 종단 실행.
"""

import json
import pathlib

import mission_pipeline as mp

_EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples"


def _set_mission() -> dict:
    return {
        "sortie_id": "E2E-01",
        "directive_text": "적 저격조 첩보 확인됨. 가용 예비기체 없음.",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"armament": [], "spare_asset_available": True, "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "c4i": {"enemy_situation": ["적 저격조 활동 확인"], "asset_management": {"spare_asset_available": True}, "known_mission": "정찰 감시"},
    }


def _write(tmp_path):
    sm = tmp_path / "sm.json"
    sm.write_text(json.dumps(_set_mission(), ensure_ascii=False), encoding="utf-8")
    raw = tmp_path / "raw.json"
    raw.write_text((_EXAMPLES / "raw_t3.json").read_text(encoding="utf-8"), encoding="utf-8")
    return sm, raw


_BRIEF_KEYS = {"sortie_id", "mission_context", "posture", "drone_profile", "corridor", "weights"}
_CYCLE_KEYS = {"abstraction", "threat", "risk", "response", "flight_plan"}


def test_approve_runs_full_01_to_07(tmp_path, capsys) -> None:
    sm, raw = _write(tmp_path)
    rc = mp.main([str(sm), str(raw), "--approve"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out["mission_brief"]) == _BRIEF_KEYS
    assert isinstance(out["approved_ts_ms"], int) and out["approved_ts_ms"] > 0
    assert set(out["cycle"]) == _CYCLE_KEYS
    assert out["cycle"]["response"]["primary_threat_event"] == "T3"


def test_no_approve_is_review_only(tmp_path, capsys) -> None:
    sm, raw = _write(tmp_path)
    rc = mp.main([str(sm), str(raw)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "review"
    assert set(out["draft_brief"]) == _BRIEF_KEYS
    assert "signal_cards" in out and "warnings" in out
    assert "cycle" not in out  # 미승인 → 온보드 미실행


def test_review_surfaces_directive_signals(tmp_path, capsys) -> None:
    sm, raw = _write(tmp_path)
    mp.main([str(sm), str(raw)])
    out = json.loads(capsys.readouterr().out)
    phrases = {c["source_phrase"] for c in out["signal_cards"]}
    assert "저격조" in phrases


def test_missing_args_usage_error(capsys) -> None:
    rc = mp.main([])
    assert rc == 2
    assert "usage" in capsys.readouterr().err


def test_ts_flag_injects_deterministic_timestamp(tmp_path, capsys) -> None:
    sm, raw = _write(tmp_path)
    rc = mp.main([str(sm), str(raw), "--approve", "--ts", "1720051200000"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["approved_ts_ms"] == 1720051200000


def test_ts_flag_makes_output_reproducible(tmp_path, capsys) -> None:
    sm, raw = _write(tmp_path)
    mp.main([str(sm), str(raw), "--approve", "--ts", "42"])
    first = capsys.readouterr().out
    mp.main([str(sm), str(raw), "--approve", "--ts", "42"])
    second = capsys.readouterr().out
    assert first == second  # 동일 입력+ts → 동일 출력 (골든 재현 전제)
