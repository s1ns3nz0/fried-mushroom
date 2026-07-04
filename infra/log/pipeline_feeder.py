"""온보드 파이프라인 → 실시간 로그수집기 브리지.

`onboard.run.run_cycle` 결과(dict)를 로그수집기 계약(`API.md`)의
`POST /log` body 리스트로 변환해 전송한다. 변환(`cycle_to_log_entries`)은
순수 함수, 전송(`post_entries`)/실행 루프(`run_scenarios`)는 IO 담당.

사용:
    PYTHONPATH=src python infra/log/pipeline_feeder.py \\
        [--collector URL] [--delay 1.0] [--loop] [--repeat N] \\
        [raw.json:mission_brief.json ...]

SCENARIO 미지정 시 repo `examples/` 의 raw_*/mission_brief_* 쌍을 자동 탐색.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import httpx  # noqa: E402

from onboard.run import run_cycle  # noqa: E402

DEFAULT_COLLECTOR_URL = "http://localhost:8500/log"

_LAYER_ORDER = ["abstraction", "threat", "risk", "response", "flight_plan"]


def _abstraction_log(layer_out: dict) -> tuple[str, str]:
    channels = layer_out.get("channels") or []
    n = len(channels)
    a = sum(1 for ch in channels if isinstance(ch, dict) and ch.get("state") == "anomaly")
    log = f"03 추상화 · {n}채널 · anomaly {a}건"
    return log, ("warn" if a > 0 else "info")


def _threat_log(layer_out: dict) -> tuple[str, str]:
    primary = layer_out.get("primary")
    if not primary:
        return "04 위협 · 후보 없음", "info"
    event = primary.get("threat_event", "?")
    try:
        conf = float(primary.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    killchain = primary.get("kill_chain_stage", "-") or "-"
    return (
        f"04 위협 · primary={event} conf={conf:.2f} killchain={killchain}",
        "warn",
    )


def _risk_log(layer_out: dict) -> tuple[str, str]:
    candidates = layer_out.get("candidates") or []
    if not candidates:
        log = "05 위험 · 위협 없음"
        ambient_rac = layer_out.get("ambient_rac")
        if ambient_rac:
            log += f" ambient={ambient_rac}"
        return log, "info"
    c = min(
        candidates,
        key=lambda cand: cand.get("priority_rank", float("inf"))
        if isinstance(cand, dict)
        else float("inf"),
    )
    if not isinstance(c, dict):
        c = {}
    rac = c.get("rac", "-")
    try:
        urgency = float(c.get("compound_urgency_score", 0.0))
    except (TypeError, ValueError):
        urgency = 0.0
    rank = c.get("priority_rank", "-")
    log = f"05 위험 · RAC={rac} urgency={urgency:.2f} rank={rank}"
    return log, ("error" if rac in {"High", "Serious"} else "warn")


def _response_log(layer_out: dict) -> tuple[str, str]:
    flight_action = layer_out.get("flight_action")
    comms_level = layer_out.get("comms_level", "-")
    log = f"06 대응 · {flight_action or '-'} comms={comms_level}"
    nav_mode = layer_out.get("nav_mode")
    if nav_mode:
        log += f" nav={nav_mode}"
    special_action = layer_out.get("special_action")
    if special_action:
        log += f" special={special_action}"
    level = "warn" if flight_action and flight_action != "MAINTAIN" else "info"
    if layer_out.get("ai_reliability") == "low":
        level = "warn"
        log += " [ai_reliability=low]"
    return log, level


def _flight_plan_log(layer_out: dict) -> tuple[str, str]:
    flight_action = layer_out.get("flight_action", "-") or "-"
    bearing = layer_out.get("target_bearing_deg", "-")
    altitude_delta = layer_out.get("altitude_delta_m", "-")
    replan = layer_out.get("replan_scope", "NONE") or "NONE"
    log = f"07 비행 · {flight_action} brg={bearing} Δalt={altitude_delta}m replan={replan}"
    return log, ("warn" if replan != "NONE" else "info")


_LAYER_FORMATTERS = {
    "abstraction": _abstraction_log,
    "threat": _threat_log,
    "risk": _risk_log,
    "response": _response_log,
    "flight_plan": _flight_plan_log,
}


def cycle_to_log_entries(correlation_id: str, result: dict) -> list[dict]:
    """run_cycle 결과 1건 → 로그수집기 entry 리스트 (레이어당 1건, 파이프라인 순서)."""
    entries = []
    for layer in _LAYER_ORDER:
        if layer not in result:
            continue
        layer_out = result[layer]
        if not isinstance(layer_out, dict):
            layer_out = {}
        log, level = _LAYER_FORMATTERS[layer](layer_out)
        entries.append(
            {
                "correlation_id": correlation_id,
                "layer": layer,
                "log": log,
                "level": level,
            }
        )
    return entries


def post_entries(entries, collector_url: str = DEFAULT_COLLECTOR_URL, *, client=None) -> int:
    """entry 들을 collector 에 POST. 2xx 건수 반환 (연결 실패는 stderr 보고 후 계속)."""
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=3.0)
    ok = 0
    try:
        for entry in entries:
            try:
                resp = client.post(collector_url, json=entry)
            except Exception as exc:
                print(
                    f"[pipeline_feeder] POST {collector_url} 실패: {exc}",
                    file=sys.stderr,
                )
                continue
            if 200 <= resp.status_code < 300:
                ok += 1
    finally:
        if owns_client:
            client.close()
    return ok


def run_scenarios(
    pairs,
    collector_url: str = DEFAULT_COLLECTOR_URL,
    *,
    repeat: int = 1,
    delay: float = 1.0,
    loop: bool = False,
) -> int:
    """(raw, mission_brief) 쌍 목록을 사이클 단위로 실행·전송. 총 2xx 건수 반환."""
    seq = 0
    passes = 0
    total_posted = 0
    while True:
        for raw_path, brief_path in pairs:
            raw = json.loads(Path(raw_path).read_text(encoding="utf-8"))
            mission_brief = json.loads(Path(brief_path).read_text(encoding="utf-8"))
            result = run_cycle(raw, mission_brief)
            seq += 1
            sortie = mission_brief.get("sortie_id", "SORTIE")
            correlation_id = f"{sortie}-{seq:04d}"
            entries = cycle_to_log_entries(correlation_id, result)
            posted = post_entries(entries, collector_url)
            total_posted += posted
            print(f"[{correlation_id}] {raw_path} → {len(entries)} entries, {posted} posted")
            time.sleep(delay)
        passes += 1
        if not loop and passes >= repeat:
            return total_posted


def discover_pairs(examples_dir: Path) -> list[tuple[str, str]]:
    """examples/ 에서 raw_*.json ↔ mission_brief_*.json 이 모두 있는 쌍만 수집."""
    pairs = []
    for raw in sorted(examples_dir.glob("raw_*.json")):
        tag = raw.stem[len("raw_"):]
        brief = examples_dir / f"mission_brief_{tag}.json"
        if brief.exists():
            pairs.append((str(raw), str(brief)))
    return pairs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="onboard run_cycle 결과를 로그수집기(POST /log)로 스트리밍",
    )
    parser.add_argument(
        "scenarios",
        nargs="*",
        metavar="SCENARIO",
        help="raw.json:mission_brief.json (미지정 시 examples/ 자동 탐색)",
    )
    parser.add_argument("--collector", default=DEFAULT_COLLECTOR_URL)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args(argv)

    if args.scenarios:
        pairs = []
        for scenario in args.scenarios:
            if ":" not in scenario:
                parser.error(f"SCENARIO 는 raw.json:mission_brief.json 형식이어야 함: {scenario}")
            raw_path, brief_path = scenario.split(":", 1)
            pairs.append((raw_path, brief_path))
    else:
        examples_dir = Path(__file__).resolve().parents[2] / "examples"
        pairs = discover_pairs(examples_dir)
        for raw_path, brief_path in pairs:
            print(f"discovered: {raw_path} : {brief_path}")

    if not pairs:
        print("[pipeline_feeder] 실행할 시나리오 쌍이 없음", file=sys.stderr)
        return 1

    run_scenarios(
        pairs,
        args.collector,
        repeat=args.repeat,
        delay=args.delay,
        loop=args.loop,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
