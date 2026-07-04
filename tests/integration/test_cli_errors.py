"""CLI(__main__) 인자 오류 경로 커버.

기존 TestCli 는 정상 --log 경로만 훑어 '--log 뒤 경로 누락' 에러 분기
(__main__.py: i+1 >= len(args) → usage 출력 + rc 2)가 미검증(coverage gap).
파일 접근 전에 인자 검증이 끝나므로 실제 파일은 필요 없다.
"""

from onboard import __main__ as cli


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
