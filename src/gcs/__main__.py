"""CLI 엔트리포인트: `python -m gcs <set_mission.json> [--approve] [--out <path>] [--ts-ms <int>]`.

지상통제센터 AI(layer 01) 오케스트레이터를 구동해 finalize 결과를 stdout 에 JSON 으로 출력한다.
--approve      운용자 승인 게이트 통과 — 온보드 MissionBrief 확정 (AI 는 후보만, 최종 결정은 사람).
--out <path>   확정된 mission_brief(6필드)만 파일로 기록 — `python -m onboard <raw> <path>` 에 그대로 투입.
               --approve 없이 지정하면 usage 오류 (미승인 브리핑은 존재하지 않음).
--ts-ms <int>  approved_ts_ms 주입(결정론 재현용). 미지정 시 현재 시각 — 시간 조회는 CLI(유즈사이트) 책임.
--override K=V 운용자가 승인 시 결정필드 수정(반복 가능). V 는 JSON. 예: --override posture='{"defcon":2}'.
               --approve 필수, 허용 필드만(finalize 계약). AI 초안을 사람이 필드단위 확정 (SCC-1).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from gcs.layer_01_info_center.run import assemble_draft, finalize

_USAGE = ("usage: python -m gcs <set_mission.json> [--approve] [--out <path>] "
          "[--ts-ms <int>] [--override K=<json> ...]")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    approve = "--approve" in args
    if approve:
        args.remove("--approve")

    # --override K=V (반복 가능) 수집.
    overrides: dict = {}
    while "--override" in args:
        i = args.index("--override")
        if i + 1 >= len(args) or "=" not in args[i + 1]:
            print(_USAGE, file=sys.stderr)
            return 2
        key, _, raw = args[i + 1].partition("=")
        try:
            overrides[key] = json.loads(raw)
        except json.JSONDecodeError:
            print(f"error: --override 값이 JSON 이 아님: {key}={raw}", file=sys.stderr)
            return 2
        args = args[:i] + args[i + 2:]

    out_path: str | None = None
    ts_ms: int | None = None
    for flag in ("--out", "--ts-ms"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                print(_USAGE, file=sys.stderr)
                return 2
            val = args[i + 1]
            if flag == "--out":
                out_path = val
            else:
                try:
                    ts_ms = int(val)
                except ValueError:
                    print(_USAGE, file=sys.stderr)
                    return 2
            args = args[:i] + args[i + 2:]

    if len(args) != 1 or ((out_path is not None or overrides) and not approve):
        print(_USAGE, file=sys.stderr)
        return 2

    inputs = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    draft = assemble_draft(inputs)
    try:
        result = finalize(
            draft, approved=approve,
            ts_ms=ts_ms if ts_ms is not None else int(time.time() * 1000),
            overrides=overrides or None,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if approve and out_path is not None:
        Path(out_path).write_text(
            json.dumps(result["mission_brief"], ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
