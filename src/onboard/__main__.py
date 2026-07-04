"""CLI 엔트리포인트: `python -m onboard <raw.json> <mission_brief.json> [--log <path>]`.

한 사이클 실행 결과(run_cycle 반환 dict)를 stdout 에 JSON 으로 출력한다.
`--log <path>` 지정 시 사이클 로그(레이어당 1줄 JSON Lines)를 해당 파일에 append 한다.
오케스트레이터는 순수 유지 — 로깅은 CLI(유즈사이트) 책임 (ARCHITECTURE 상태 관리).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from onboard.run import run_cycle

_USAGE = "usage: python -m onboard <raw.json> <mission_brief.json> [--log <path>]"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv

    log_path: str | None = None
    if "--log" in args:
        i = args.index("--log")
        if i + 1 >= len(args):
            print(_USAGE, file=sys.stderr)
            return 2
        log_path = args[i + 1]
        args = args[:i] + args[i + 2 :]

    if len(args) < 2:
        print(_USAGE, file=sys.stderr)
        return 2

    raw = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    mission_brief = json.loads(Path(args[1]).read_text(encoding="utf-8"))
    result = run_cycle(raw, mission_brief)

    if log_path is not None:
        _append_cycle_log(log_path, raw.get("seq"), result)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _append_cycle_log(path: str, seq, result: dict) -> None:
    """사이클 결과를 레이어당 1줄(JSON Lines)로 append. 각 줄 = {seq, layer, output}."""
    lines = [
        json.dumps({"seq": seq, "layer": layer, "output": output}, ensure_ascii=False)
        for layer, output in result.items()
    ]
    with Path(path).open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
