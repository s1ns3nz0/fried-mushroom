"""CLI(__main__) 인자 오류 경로 커버 (#204).

에러 경로(누락 파일/깨진 JSON/스키마 위반/인자 과부족)가 스택트레이스 대신
명확한 에러 메시지 + 비-0 종료코드로 그레이스풀 실패하는지 검증.
UX 갭이 남은 경우 pytest.mark.xfail 로 문서화.
"""

import json
import os
import subprocess
import sys

import pytest

from onboard import __main__ as cli

_EXAMPLES = __import__("pathlib").Path(__file__).resolve().parents[2] / "examples"
_SRC = str(__import__("pathlib").Path(__file__).resolve().parents[2] / "src")


def _run(*args):
    """subprocess 로 CLI 실행 → (returncode, stdout, stderr)."""
    r = subprocess.run(
        [sys.executable, "-m", "onboard", *args],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": _SRC},
    )
    return r.returncode, r.stdout, r.stderr


# ── 기존 테스트 (변경 금지) ────────────────────────────────────────────────────


def test_log_flag_without_path_is_usage_error(capsys) -> None:
    # --log 가 마지막 인자 → 뒤에 경로 없음 → usage 에러.
    rc = cli.main(["raw.json", "brief.json", "--log"])
    assert rc == 2
    assert "usage" in capsys.readouterr().err


def test_log_flag_strips_from_positionals(tmp_path, capsys) -> None:
    # --log 소비 후 남은 positional 이 2개 미만이면 usage 에러.
    rc = cli.main(["--log", str(tmp_path / "x.jsonl")])
    assert rc == 2
    assert "usage" in capsys.readouterr().err


# ── 1. 누락 파일 ──────────────────────────────────────────────────────────────


def test_missing_raw_file_exits_nonzero():
    """존재하지 않는 raw 경로 → 비-0 exit."""
    rc, _, _ = _run("no_such_raw.json", str(_EXAMPLES / "mission_brief_t3.json"))
    assert rc != 0


def test_missing_raw_file_graceful_message():
    """존재하지 않는 raw 경로 → 사람이 읽는 에러 메시지 (스택트레이스 아님)."""
    rc, _, err = _run("no_such_raw.json", str(_EXAMPLES / "mission_brief_t3.json"))
    assert rc != 0
    assert "Traceback" not in err, f"스택트레이스 노출 (UX gap): {err[:200]}"
    assert "error" in err.lower()


def test_missing_brief_file_exits_nonzero():
    """존재하지 않는 mission_brief 경로 → 비-0 exit."""
    rc, _, _ = _run(str(_EXAMPLES / "raw_t3.json"), "no_such_brief.json")
    assert rc != 0


def test_missing_brief_file_graceful_message():
    """존재하지 않는 mission_brief 경로 → 사람이 읽는 에러 메시지."""
    rc, _, err = _run(str(_EXAMPLES / "raw_t3.json"), "no_such_brief.json")
    assert rc != 0
    assert "Traceback" not in err, f"스택트레이스 노출 (UX gap): {err[:200]}"
    assert "error" in err.lower()


# ── 2. 깨진 JSON ──────────────────────────────────────────────────────────────


def test_broken_raw_json_exits_nonzero(tmp_path):
    """문법 오류 raw JSON → 비-0 exit."""
    bad = tmp_path / "bad_raw.json"
    bad.write_text("{not valid json}")
    rc, _, _ = _run(str(bad), str(_EXAMPLES / "mission_brief_t3.json"))
    assert rc != 0


def test_broken_raw_json_graceful_message(tmp_path):
    """문법 오류 raw JSON → 사람이 읽는 파싱 에러 메시지 (스택트레이스 아님)."""
    bad = tmp_path / "bad_raw.json"
    bad.write_text("{not valid json}")
    rc, _, err = _run(str(bad), str(_EXAMPLES / "mission_brief_t3.json"))
    assert rc != 0
    assert "Traceback" not in err, f"스택트레이스 노출 (UX gap): {err[:200]}"
    assert "error" in err.lower()


def test_broken_brief_json_exits_nonzero(tmp_path):
    """문법 오류 brief JSON → 비-0 exit."""
    bad = tmp_path / "bad_brief.json"
    bad.write_text("{not valid json}")
    rc, _, _ = _run(str(_EXAMPLES / "raw_t3.json"), str(bad))
    assert rc != 0


def test_broken_brief_json_graceful_message(tmp_path):
    """문법 오류 brief JSON → 사람이 읽는 파싱 에러 메시지."""
    bad = tmp_path / "bad_brief.json"
    bad.write_text("{not valid json}")
    rc, _, err = _run(str(_EXAMPLES / "raw_t3.json"), str(bad))
    assert rc != 0
    assert "Traceback" not in err, f"스택트레이스 노출 (UX gap): {err[:200]}"
    assert "error" in err.lower()


# ── 3. 스키마 위반 브리핑 (필수 키 누락) ──────────────────────────────────────


def test_schema_violation_brief_exits_nonzero(tmp_path):
    """필수 키 누락 mission_brief → 비-0 exit."""
    minimal = tmp_path / "minimal_brief.json"
    minimal.write_text(json.dumps({"sortie_id": "x"}))
    rc, _, _ = _run(str(_EXAMPLES / "raw_t3.json"), str(minimal))
    assert rc != 0


def test_schema_violation_brief_graceful_message(tmp_path):
    """필수 키 누락 brief → 어떤 키가 누락인지 명시하는 에러 메시지 (스택트레이스 아님, #209)."""
    minimal = tmp_path / "minimal_brief.json"
    minimal.write_text(json.dumps({"sortie_id": "x"}))
    rc, _, err = _run(str(_EXAMPLES / "raw_t3.json"), str(minimal))
    assert rc != 0
    assert "Traceback" not in err, f"스택트레이스 노출: {err[:300]}"
    assert "error" in err.lower()
    # 누락 키(예: posture/weights)를 명시해야 운용자가 무엇을 고칠지 앎.
    assert "posture" in err and "weights" in err, f"누락 키 미명시: {err[:300]}"


def test_brief_not_object_graceful_message(tmp_path):
    """mission_brief 가 dict 아님(예: 리스트) → 명확한 에러 + 비-0 exit."""
    notobj = tmp_path / "list_brief.json"
    notobj.write_text(json.dumps(["not", "a", "dict"]))
    rc, _, err = _run(str(_EXAMPLES / "raw_t3.json"), str(notobj))
    assert rc != 0
    assert "Traceback" not in err
    assert "error" in err.lower()


# ── 3b. 스키마 위반 raw (필수 키 누락) ────────────────────────────────────────


def test_schema_violation_raw_exits_nonzero(tmp_path):
    """필수 키 누락 raw → 비-0 exit (#214)."""
    minimal = tmp_path / "minimal_raw.json"
    minimal.write_text(json.dumps({"ts_ms": 1000}))
    rc, _, _ = _run(str(minimal), str(_EXAMPLES / "mission_brief_t3.json"))
    assert rc != 0


def test_schema_violation_raw_graceful_message(tmp_path):
    """필수 키 누락 raw → 스택트레이스 아닌 명확한 에러 메시지 (#214)."""
    minimal = tmp_path / "minimal_raw.json"
    minimal.write_text(json.dumps({"ts_ms": 1000}))
    rc, _, err = _run(str(minimal), str(_EXAMPLES / "mission_brief_t3.json"))
    assert rc != 0
    assert "Traceback" not in err, f"스택트레이스 노출: {err[:300]}"
    assert "error" in err.lower()
    assert any(k in err for k in ("navigation", "ew", "health", "environment", "c2_link")), (
        f"누락 키 이름이 에러 메시지에 없음: {err[:300]}"
    )


def test_raw_not_object_graceful_message(tmp_path):
    """raw 가 dict 아님(예: 리스트) → 명확한 에러 + 비-0 exit (#214)."""
    notobj = tmp_path / "list_raw.json"
    notobj.write_text(json.dumps(["not", "a", "dict"]))
    rc, _, err = _run(str(notobj), str(_EXAMPLES / "mission_brief_t3.json"))
    assert rc != 0
    assert "Traceback" not in err
    assert "error" in err.lower()


# ── 4. 인자 개수 오류 ─────────────────────────────────────────────────────────


def test_no_positional_args_usage_error(capsys):
    """positional 인자 없음 → usage + rc 2."""
    rc = cli.main([])
    assert rc == 2
    assert "usage" in capsys.readouterr().err


def test_one_positional_arg_usage_error(capsys):
    """positional 인자 1개 → usage + rc 2."""
    rc = cli.main(["only_one.json"])
    assert rc == 2
    assert "usage" in capsys.readouterr().err


def test_excess_positional_args_exits_nonzero(capsys):
    """positional 인자 3개 이상 → 비-0 exit + 에러 메시지."""
    rc = cli.main(["raw.json", "brief.json", "extra.json"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "error" in err.lower() or "usage" in err.lower()


# ── 5. 정상 경로 회귀 ─────────────────────────────────────────────────────────


def test_valid_input_exits_zero():
    """유효한 입력 → exit 0, stdout 에 JSON 출력."""
    rc, out, err = _run(
        str(_EXAMPLES / "raw_t3.json"), str(_EXAMPLES / "mission_brief_t3.json")
    )
    assert rc == 0, f"정상 경로에서 비-0 exit: {err}"
    assert "flight_plan" in json.loads(out)


def test_valid_input_with_prev_qualities_exits_zero():
    """유효한 입력 + --prev-qualities → exit 0."""
    rc, out, err = _run(
        str(_EXAMPLES / "raw_t5.json"), str(_EXAMPLES / "mission_brief_t5.json"),
        "--prev-qualities", str(_EXAMPLES / "qualities_t5_primed.json"),
    )
    assert rc == 0, f"--prev-qualities 정상 경로 비-0 exit: {err}"
    assert "flight_plan" in json.loads(out)
