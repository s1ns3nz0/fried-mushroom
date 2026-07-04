"""CLI 엔트리포인트: `python -m onboard <raw.json> <mission_brief.json>` (step9.md).

한 사이클 실행 결과(run_cycle 반환 dict)를 stdout 에 JSON 으로 출력한다.
로깅·파일쓰기는 하지 않는다 (결과만 stdout — 유즈사이트가 리다이렉트로 골든 저장).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from onboard.run import run_cycle


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        print("usage: python -m onboard <raw.json> <mission_brief.json>", file=sys.stderr)
        return 2

    raw = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    mission_brief = json.loads(Path(args[1]).read_text(encoding="utf-8"))
    result = run_cycle(raw, mission_brief)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
