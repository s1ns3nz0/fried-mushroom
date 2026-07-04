"""CLI 엔트리포인트: `python -m onboard <raw.json> <mission_brief.json> [--log <path>]
[--prev-qualities <path>] [--flight-plan-state <path>]`.

한 사이클 실행 결과(run_cycle 반환 dict)를 stdout 에 JSON 으로 출력한다.
`--log <path>` 지정 시 사이클 로그(레이어당 1줄 JSON Lines)를 해당 파일에 append 한다.
`--prev-qualities <path>` 지정 시 직전 사이클 채널 quality 맵(JSON)을 previous_qualities 로 주입한다.
  → quality_delta 실계산 가능 → T5(레이저/광학 교란) 종단 탐지 언블록 (#83).
`--flight-plan-state <path>` 지정 시 직전 사이클 07 디바운스 상태(JSON)를
  previous_flight_plan_state 로 주입한다 → RAC 완화(de-escalation) 디바운스 이어감(신규).
  결과의 `flight_plan_state` 키를 다음 호출에 그대로 다시 넘기면 된다(extract_flight_plan_state 와 동일 값).
오케스트레이터는 순수 유지 — 로깅은 CLI(유즈사이트) 책임 (ARCHITECTURE 상태 관리).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from onboard.run import run_cycle

_USAGE = (
    "usage: python -m onboard <raw.json> <mission_brief.json> "
    "[--log <path>] [--prev-qualities <path>] [--flight-plan-state <path>]"
)

_RAW_REQUIRED = frozenset({
    "ts_ms", "navigation", "ew", "health", "environment",
    "c2_link", "acoustic", "imagery", "lidar", "mission_status",
})
_BRIEF_REQUIRED = frozenset({"mission_context", "posture", "drone_profile"})


def _check_keys(data: dict, required: frozenset, label: str) -> str | None:
    missing = sorted(required - data.keys())
    if missing:
        return f"error: {label} 필수 키 누락: {', '.join(missing)}"
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    log_path: str | None = None
    prev_qualities_path: str | None = None
    flight_plan_state_path: str | None = None

    for flag in ("--log", "--prev-qualities", "--flight-plan-state"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                print(_USAGE, file=sys.stderr)
                return 2
            val = args[i + 1]
            if flag == "--log":
                log_path = val
            elif flag == "--prev-qualities":
                prev_qualities_path = val
            else:
                flight_plan_state_path = val
            args = args[:i] + args[i + 2:]

    if len(args) < 2:
        print(_USAGE, file=sys.stderr)
        return 2
    if len(args) > 2:
        print(f"error: 인자 과다 — positional 인자는 2개 (raw, brief). 받음: {len(args)}개\n{_USAGE}",
              file=sys.stderr)
        return 2

    try:
        raw_text = Path(args[0]).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        print(f"error: raw 파일 읽기 실패: {exc}", file=sys.stderr)
        return 2
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"error: raw JSON 파싱 실패 ({args[0]}): {exc}", file=sys.stderr)
        return 2
    err = _check_keys(raw, _RAW_REQUIRED, f"raw ({args[0]})")
    if err:
        print(err, file=sys.stderr)
        return 2

    try:
        brief_text = Path(args[1]).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        print(f"error: mission_brief 파일 읽기 실패: {exc}", file=sys.stderr)
        return 2
    try:
        mission_brief = json.loads(brief_text)
    except json.JSONDecodeError as exc:
        print(f"error: mission_brief JSON 파싱 실패 ({args[1]}): {exc}", file=sys.stderr)
        return 2
    err = _check_keys(mission_brief, _BRIEF_REQUIRED, f"mission_brief ({args[1]})")
    if err:
        print(err, file=sys.stderr)
        return 2

    previous_qualities: dict | None = None
    if prev_qualities_path is not None:
        try:
            previous_qualities = json.loads(Path(prev_qualities_path).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError) as exc:
            print(f"error: --prev-qualities: {exc}", file=sys.stderr)
            return 2

    previous_flight_plan_state: dict | None = None
    if flight_plan_state_path is not None:
        try:
            previous_flight_plan_state = json.loads(
                Path(flight_plan_state_path).read_text(encoding="utf-8")
            )
        except (FileNotFoundError, OSError) as exc:
            print(f"error: --flight-plan-state: {exc}", file=sys.stderr)
            return 2

    result = run_cycle(
        raw,
        mission_brief,
        previous_qualities=previous_qualities,
        previous_flight_plan_state=previous_flight_plan_state,
    )

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
