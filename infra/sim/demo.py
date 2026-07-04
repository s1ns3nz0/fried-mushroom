"""infra/sim 종단 데모 브리지 — 지시서(set_mission) → GCS 승인 → 폐루프 sim.

#151 폐루프 데모의 front-of-loop. `runner`(브리핑→폐루프)와 `gcs`(지시서→브리핑)를
이어붙여 **지시서 한 장에서 UAV 임무 달성까지**를 모킹 없이 한 커맨드로 돌린다:

  지시서(METT+TC/C4I) → GCS 01 finalize(운용자 승인) → MissionBrief
    → runner.run_closed_loop(적 사전배치→회피경로→run_cycle 실판정→궤적 굴절) → ARRIVED

runner 와 동일한 tick payload 를 내보내므로 대시보드는 브리핑-소스와 무관하게 동일 소비한다.
새 파일 — mara #154 runner.py 무수정(스택 충돌 회피). src/onboard/gcs 무수정.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parents[1] / "src"
for _p in (str(_HERE), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import runner  # noqa: E402  (infra/sim 형제 모듈 — 폐루프 실행/payload 재사용)
from gcs.layer_01_info_center.run import assemble_draft, finalize  # noqa: E402


def directive_to_brief(directive: dict, ts_ms: int = 0) -> dict:
    """지시서(set_mission) → GCS 승인 게이트 통과 → 온보드 MissionBrief(6필드).

    finalize(approved=True) 로 운용자 승인을 모사한다 — 데모용 자동 승인.
    실운용에선 사람이 승인하지만, 재현 가능한 종단 데모는 승인을 고정한다.
    """
    draft = assemble_draft(directive)
    return finalize(draft, approved=True, ts_ms=ts_ms)["mission_brief"]


def run_from_directive(
    directive: dict, seed: int = 42, ticks: int = 300, dt: float = 1.0, ts_ms: int = 0
) -> list[dict]:
    """지시서 → 브리핑 → 폐루프 프레임 리스트({world, result})."""
    brief = directive_to_brief(directive, ts_ms=ts_ms)
    return runner.run_closed_loop(brief, seed, ticks, dt=dt)


def _summarize(frames: list[dict]) -> dict:
    phases = [f["world"]["phase"] for f in frames]
    actions = sorted({f["result"]["flight_plan"]["flight_action"] for f in frames})
    return {
        "ticks": len(frames),
        "phases_seen": sorted(set(phases)),
        "evaded": "EVADE" in phases,
        "arrived": "ARRIVED" in phases,
        "arrived_at_tick": phases.index("ARRIVED") if "ARRIVED" in phases else None,
        "flight_actions": actions,
    }


def main(argv: list[str] | None = None) -> int:
    """지시서 폐루프 데모 CLI — 요약(기본) 또는 tick payload(JSONL) 출력."""
    parser = argparse.ArgumentParser(description="infra/sim 지시서→폐루프 데모 (#151)")
    parser.add_argument("directive", help="set_mission JSON 경로(지시서+C4I)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ticks", type=int, default=300)
    parser.add_argument("--dt", type=float, default=1.0)
    parser.add_argument("--jsonl", action="store_true",
                        help="tick payload 를 JSONL 로 출력(대시보드 소비용). 기본은 요약.")
    args = parser.parse_args(argv)

    path = Path(args.directive)
    if not path.exists():
        print(f"error: directive 파일 없음: {args.directive}", file=sys.stderr)
        return 2
    directive = json.loads(path.read_text(encoding="utf-8"))

    brief = directive_to_brief(directive)
    scen = runner.build_scenario(brief, args.seed)
    frames = runner.run_closed_loop(brief, args.seed, args.ticks, dt=args.dt)

    if args.jsonl:
        sortie = brief.get("sortie_id", "SIM")
        for seq, f in enumerate(frames):
            payload = runner.build_tick_payload(
                seq, int(seq * args.dt * 1000),
                f"{sortie}-{seq:04d}", f["world"], f["result"], scen["enemies"],
            )
            print(json.dumps(payload, ensure_ascii=False))
    else:
        print(json.dumps(_summarize(frames), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
