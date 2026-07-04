"""mission_pipeline — 01→07 종단 CLI (중립 조합 하니스).

    python -m mission_pipeline <set_mission.json> <raw.json> [--approve]

지상통제센터 AI(layer 01)가 set_mission 으로 mission_brief 를 만들고, 운용자 승인
(--approve) 시 온보드 run_cycle 로 종단(02..07)을 실행한다. GCS·온보드는 서로를
import 하지 않는 독립 시스템이며, 이 모듈이 둘을 조합한다(데모/검증 seam).

승인 없으면 리뷰(draft_brief·signal_cards·warnings)만 출력하고 온보드는 돌리지 않는다
— 스펙의 사람-최종결정 원칙(HITL)을 CLI 계약으로 보존.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from gcs.layer_01_info_center.run import assemble_draft, finalize
from onboard.run import run_cycle

_USAGE = "usage: python -m mission_pipeline <set_mission.json> <raw.json> [--approve]"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    approve = "--approve" in args
    positionals = [a for a in args if a != "--approve"]
    if len(positionals) < 2:
        print(_USAGE, file=sys.stderr)
        return 2

    set_mission = json.loads(Path(positionals[0]).read_text(encoding="utf-8"))
    raw = json.loads(Path(positionals[1]).read_text(encoding="utf-8"))

    draft = assemble_draft(set_mission)

    if not approve:
        # 리뷰만 — 온보드 미실행 (운용자 승인 대기).
        result: dict = {"status": "review", **draft}
    else:
        ts_ms = int(time.time() * 1000)  # 유즈사이트(CLI) 시계 — 파이프라인은 순수 유지
        finalized = finalize(draft, approved=True, ts_ms=ts_ms)
        cycle = run_cycle(raw, finalized["mission_brief"])
        result = {
            "mission_brief": finalized["mission_brief"],
            "approved_ts_ms": finalized["approved_ts_ms"],
            "cycle": cycle,
        }

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
