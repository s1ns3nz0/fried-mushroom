"""gcs CLI(`python -m gcs`) — 승인 게이트 통과한 MissionBrief 산출 검증 (TDD).

계약: <set_mission.json> 입력 → assemble_draft → finalize.
--approve 시 mission_brief(온보드 6필드)를 --out 파일로 기록, 미승인 시 pending 페이로드만 stdout.
ts_ms 는 --ts-ms 로 주입 가능(결정론 테스트) — 파이프라인 순수성은 CLI(유즈사이트)가 책임.
"""

import json
from pathlib import Path

from gcs.__main__ import main
from gcs.layer_01_info_center.assemble import MISSION_BRIEF_FIELDS

_EXAMPLE = "examples/set_mission_recon.json"


def test_approve_writes_onboard_mission_brief(tmp_path, capsys) -> None:
    out = tmp_path / "brief.json"
    rc = main([_EXAMPLE, "--approve", "--out", str(out), "--ts-ms", "1000"])
    assert rc == 0
    brief = json.loads(out.read_text(encoding="utf-8"))
    assert set(brief) == set(MISSION_BRIEF_FIELDS), "출력 파일은 온보드 6필드 계약만"
    assert brief["sortie_id"] == "RECON-0704-01"
    result = json.loads(capsys.readouterr().out)
    assert result["approved_ts_ms"] == 1000
    assert result["mission_brief"] == brief


def test_pending_without_approve(capsys) -> None:
    rc = main([_EXAMPLE])
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "pending_approval"
    assert "signal_cards" in result and "warnings" in result
    assert "mission_brief" not in result, "미승인 시 브리핑 미확정 (사람이 최종 결정)"


def test_out_requires_approve(tmp_path, capsys) -> None:
    out = tmp_path / "brief.json"
    rc = main([_EXAMPLE, "--out", str(out)])
    assert rc == 2, "--out 은 --approve 없이 무의미 — usage 오류"
    assert not out.exists()


def test_usage_error_on_missing_input() -> None:
    assert main([]) == 2


def test_override_applies_at_approval(capsys) -> None:
    rc = main([_EXAMPLE, "--approve", "--ts-ms", "1",
               "--override", 'posture={"watchcon": 2, "defcon": 2, "infocon": 3}'])
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mission_brief"]["posture"]["defcon"] == 2
    assert result["applied_overrides"]["posture"]["to"]["defcon"] == 2


def test_override_unknown_field_errors() -> None:
    assert main([_EXAMPLE, "--approve", "--ts-ms", "1", "--override", "secret=1"]) == 2


def test_override_requires_approve() -> None:
    assert main([_EXAMPLE, "--ts-ms", "1", "--override", 'mission_context="타격"']) == 2


def test_override_without_approve_errors_before_load() -> None:
    # 나쁜 파일 경로여도 override/approve 계약 위반이 먼저 usage 오류 (codex P3).
    assert main(["/nonexistent/path.json", "--override", 'posture={"defcon":2}']) == 2


def test_override_bad_json_errors() -> None:
    assert main([_EXAMPLE, "--approve", "--ts-ms", "1", "--override", "posture={bad"]) == 2


def test_override_missing_equals_errors() -> None:
    assert main([_EXAMPLE, "--approve", "--ts-ms", "1", "--override", "posture"]) == 2


def test_usage_error_on_non_integer_ts_ms(capsys) -> None:
    rc = main([_EXAMPLE, "--approve", "--ts-ms", "abc"])
    assert rc == 2, "비정수 --ts-ms 는 traceback 아닌 usage 오류"
