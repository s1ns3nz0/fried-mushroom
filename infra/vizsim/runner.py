"""Sim runner CLI — drives the in-process world sim tick-by-tick, feeds each
cycle's onboard pipeline result into the log collector (POST /log, /tick)
and posts a one-time /init snapshot (terrain/route/corridor/events).

Usage:
    PYTHONPATH=src python infra/sim/runner.py \\
        --seed 42 --brief examples/mission_brief_t3.json \\
        [--rate 1.0] [--speed 1.0] [--duration 30] [--collector http://localhost:8500]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

# Mirror pipeline_feeder.py / envelope.py's sys.path setup: this module needs
# repo src/ (onboard), infra/log/ (pipeline_feeder) and its own directory
# (flat sim modules: terrain/route/path/events/world/envelope) importable
# regardless of how it is invoked (script vs. import from elsewhere).
_SIM_DIR = Path(__file__).resolve().parent
_INFRA_DIR = _SIM_DIR.parent
_SRC = _INFRA_DIR.parent / "src"
_LOG_DIR = _INFRA_DIR / "log"

for _path in (_SIM_DIR, _INFRA_DIR, _LOG_DIR, _SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from vizsim import envelope  # noqa: E402
from vizsim import events as events_module  # noqa: E402
from vizsim import path  # noqa: E402
from vizsim import route  # noqa: E402
from vizsim import terrain  # noqa: E402
from vizsim import world  # noqa: E402

from onboard.run import run_cycle  # noqa: E402
from pipeline_feeder import cycle_to_log_entries, post_entries  # noqa: E402

DEFAULT_COLLECTOR_URL = "http://localhost:8500"

EVENT_KIND = {
    "T1_jamming": "T1",
    "T2_link_degrade": "T2",
    "T3_ambush": "T3",
    "T4_capture": "T4",
    "T7_obstacle": "T7",
}

KIND_EVENT = {kind: event_type for event_type, kind in EVENT_KIND.items()}

ENEMY_OFFSET = 0.04  # normalized-coord distance the marker sits beside the route

BRIEFED_ENEMY_COUNT = 2  # enemies known from pre-mission intel; the rest are popups
POPUP_ENEMY_COUNT = 3  # 임무 중 신규식별(팝업) 최대 수 — seed가 더 만들어도 이만큼만

_ENEMY_DETECT_RADIUS_M = 400.0  # default keep-out radius when track omits radius_m/radius


def load_briefing(directive_path: str) -> dict:
    """Read a set_mission json's directive_text and extract GCS threat signals.

    Returns {"directive": <text>, "threats": [{"threat","confidence","source_phrase"}...],
    "enemy_tracks": [<pre-briefed enemy positions from the directive json>...]}.
    A missing/broken gcs module degrades to an empty threats list (runner keeps going).
    """
    data = json.loads(Path(directive_path).read_text(encoding="utf-8"))
    text = data.get("directive_text", "")
    enemy_tracks = data.get("enemy_tracks", [])
    try:
        from gcs.layer_01_info_center.nlp_extract import extract_signals
    except Exception as exc:
        print(f"[runner] gcs nlp_extract unavailable: {exc}", file=sys.stderr)
        return {"directive": text, "threats": [], "enemy_tracks": enemy_tracks}
    threats = [
        {
            "threat": s["threat"],
            "confidence": s["confidence"],
            "source_phrase": s["source_phrase"],
        }
        for s in extract_signals(text)
        if s.get("signal_type") == "threat"
    ]
    return {"directive": text, "threats": threats, "enemy_tracks": enemy_tracks}


def build_enemies(
    waypoints: list[dict], evs: list[dict], briefed_threats: dict | None = None
) -> list[dict]:
    """Compute a pre-briefed enemy marker (map position) for each event.

    Position = route point at the event's midpoint s, pushed ENEMY_OFFSET off
    the route: along params.bearing_deg when present (T3), otherwise
    perpendicular to the local heading, side alternating by event index
    (deterministic, no RNG).

    briefed_threats: optional {kind: confidence} from the GCS directive.
    Positions stay sim-derived (GCS has no coordinates) — a matching kind only
    sets briefed=True and overrides confidence with the GCS signal's.
    """
    enemies = []
    for i, event in enumerate(evs):
        s = (event["s_start"] + event["s_end"]) / 2.0
        pt = path.point_at_s(waypoints, s)
        params = event.get("params", {})
        bearing = params.get("bearing_deg")
        if bearing is not None:
            angle = math.radians(bearing)
        else:
            side = 1.0 if i % 2 == 0 else -1.0
            angle = math.radians(pt["heading_deg"] + 90.0 * side)
        # Compass bearing -> screen vector: (sin a, -cos a), y=0 at top.
        ex = pt["x"] + math.sin(angle) * ENEMY_OFFSET
        ey = pt["y"] - math.cos(angle) * ENEMY_OFFSET
        intensity = params.get("intensity", 0.5)
        kind = EVENT_KIND.get(event["type"], event["type"])
        briefed_conf = (briefed_threats or {}).get(kind)
        enemies.append(
            {
                "type": event["type"],
                "kind": kind,
                "x": ex,
                "y": ey,
                "radius": 0.05 + intensity * 0.05,
                "confidence": briefed_conf if briefed_conf is not None
                else params.get("confidence", 0.8),
                "briefed": briefed_conf is not None,
                "s": s,
            }
        )
    return enemies


def _select_spread_popups(popups: list[dict], count: int) -> list[dict]:
    """경로 전반(arc-length s)에 고루 퍼진 count개 팝업을 결정론적으로 선택.
    이벤트 목록 앞쪽이 출발지에 군집돼 즉시 전부 식별되는 것을 방지 —
    s로 정렬 후 균등 간격 샘플링."""
    if len(popups) <= count:
        return popups
    ordered = sorted(popups, key=lambda e: e.get("s", 0.0))
    n = len(ordered)
    return [ordered[int(n * (k + 0.5) / count)] for k in range(count)]


def split_enemies(enemies: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split enemies into (briefed, popup), both preserving original order.

    briefed = at most BRIEFED_ENEMY_COUNT enemies, preferring GCS-matched ones
    (briefed=True from build_enemies) first, then filling with the rest.
    popup = everything else — hidden from /init and only revealed at runtime
    when the drone enters their detection radius. If the seed yields fewer
    than BRIEFED_ENEMY_COUNT+1 enemies there may be no popup; the demo seed 0
    with the recon directive yields 3 enemies -> 2 briefed + 1 popup.
    """
    preferred = [e for e in enemies if e.get("briefed")]
    rest = [e for e in enemies if not e.get("briefed")]
    briefed_ids = {id(e) for e in (preferred + rest)[:BRIEFED_ENEMY_COUNT]}
    briefed = [e for e in enemies if id(e) in briefed_ids]
    popup = [e for e in enemies if id(e) not in briefed_ids]
    return briefed, popup


def _track_lat_lon(pos) -> tuple[float, float]:
    """Normalize an enemy_track's `pos` field to (lat, lon).

    Accepts both shapes seen in the wild: the flat dashboard dict
    {"lat":.., "lon":..} and the C4I/B-1 canonical list [lat, lon]
    (#195/#219/#255 P2-1).
    """
    if isinstance(pos, (list, tuple)):
        return pos[0], pos[1]
    return pos["lat"], pos["lon"]


def build_scenario(
    seed: int,
    brief: dict,
    briefed_threats: dict | None = None,
    enemy_tracks: list[dict] | None = None,
) -> dict:
    """Build the full sim scenario deterministically (pure — no network/sleep).

    Enemies-first flow: a provisional no-enemy route anchors the events and
    enemy markers, then the final route avoids the BRIEFED enemies only (popup
    enemies are unknown pre-mission, so the route does not avoid them), and
    events are re-anchored on the final route's arc length.

    enemy_tracks: optional pre-briefed enemy positions (geo) from the GCS
    directive. When provided they become the BRIEFED enemies at their exact
    positions and ALL seed-derived enemies become popups; when None the
    briefed/popup split stays seed-based.

    Popup enemies are rebuilt on the FINAL route/events (after avoidance),
    not the provisional rt0/evs0 — otherwise, whenever avoidance actually
    changes the route's arc length, popup positions/`s` would stay anchored
    to a discarded scale, desyncing from the `events` this function returns
    and from what gets injected into World (#255 P2-2). BRIEFED enemies keep
    their rt0/evs0-anchored positions since the returned route was generated
    specifically to keep out of them.
    """
    frame = brief.get("frame")
    bbox = route.frame_to_bbox(frame) if frame else route.compute_bbox(brief["corridor"]["waypoints"])
    rt0 = route.generate_route(brief)
    total0 = path.total_length(rt0["waypoints"])
    evs0 = events_module.generate_events(seed, total0)
    if enemy_tracks is not None:
        briefed = []
        for trk in enemy_tracks:
            # flat dashboard shape (lat/lon/radius_m) + C4I/B-1 canonical shape
            # (pos/radius) both accepted (#195/#219).
            pos = trk.get("pos") or trk
            lat, lon = _track_lat_lon(pos)
            x, y = route.to_norm(lat, lon, bbox)
            radius_m = float(trk.get("radius_m") or trk.get("radius") or _ENEMY_DETECT_RADIUS_M)
            kind = trk.get("kind")
            briefed.append(
                {
                    "id": trk.get("id") or trk.get("track_id") or "E?",
                    "type": KIND_EVENT.get(kind, kind),
                    "kind": kind,
                    "x": x,
                    "y": y,
                    "radius": radius_m / world.MAP_EXTENT_M,
                    "confidence": trk.get("confidence"),
                    "briefed": True,
                }
            )
    else:
        all_enemies0 = build_enemies(rt0["waypoints"], evs0, briefed_threats)
        briefed, _popup0 = split_enemies(all_enemies0)
    rt = route.generate_route(brief, enemies=briefed)
    total_s = path.total_length(rt["waypoints"])
    evs = events_module.generate_events(seed, total_s)
    if enemy_tracks is not None:
        popup = _select_spread_popups(build_enemies(rt["waypoints"], evs), POPUP_ENEMY_COUNT)
    else:
        all_final = build_enemies(rt["waypoints"], evs, briefed_threats)
        _briefed_final, popup = split_enemies(all_final)
    all_enemies = briefed + popup
    return {
        "bbox": bbox,
        "route": rt,
        "events": evs,
        "enemies": briefed,
        "popup_enemies": popup,
        "all_enemies": all_enemies,
        "total_s": total_s,
    }


def build_tick_payload(
    snapshot: dict,
    result: dict,
    discovered_enemies: list[dict] | None = None,
    raw: dict | None = None,
    brief: dict | None = None,
) -> dict:
    """Assemble the /tick payload from a world snapshot and a run_cycle result (pure).

    discovered_enemies: cumulative list of popup enemies the drone has already
    discovered (caller tracks the discovered set across ticks).
    raw/brief: this tick's synthesize() envelope and the mission brief — feed
    the per-layer input/output `debug` block (always included; the dashboard
    decides whether to show it).
    """
    response = result.get("response") or {}
    flight_plan = result.get("flight_plan") or {}
    threat = result.get("threat") or {}
    primary = threat.get("primary")
    if primary is not None:
        primary = {
            k: primary[k]
            for k in ("threat_event", "confidence", "kill_chain_stage")
            if k in primary
        }
    candidates = (result.get("risk") or {}).get("candidates") or []
    if candidates:
        top = min(candidates, key=lambda c: c.get("priority_rank", float("inf")))
        risk = {
            "rac": top.get("rac"),
            "compound_urgency_score": top.get("compound_urgency_score"),
        }
    else:
        risk = None
    return {
        **snapshot,
        "flight_action": response.get("flight_action"),
        "rac": response.get("rac"),
        "discovered_enemies": discovered_enemies or [],
        "channels": result["abstraction"]["channels"],
        "decision": {
            "threat": {"primary": primary},
            "risk": risk,
            "response": {
                "flight_action": response.get("flight_action"),
                "comms_level": response.get("comms_level"),
                "rac": response.get("rac"),
                "threat_category": response.get("threat_category"),
            },
            "flight_plan": {
                "flight_action": flight_plan.get("flight_action"),
                "target_bearing_deg": flight_plan.get("target_bearing_deg"),
                "altitude_delta_m": flight_plan.get("altitude_delta_m"),
                "replan_scope": flight_plan.get("replan_scope"),
                "speed_mode": flight_plan.get("speed_mode"),
            },
        },
        "debug": {
            "layers": [
                {
                    "layer": "02→03 센서 추상화",
                    "input": raw,
                    "output": result["abstraction"],
                },
                {
                    "layer": "03→04 위협 모델링",
                    "input": result["abstraction"],
                    "output": result["threat"],
                },
                {
                    "layer": "04→05 위험 평가",
                    "input": result["threat"],
                    "output": result["risk"],
                },
                {
                    "layer": "05→06 대응 결정",
                    "input": result["risk"],
                    "output": result["response"],
                },
                {
                    "layer": "06→07 비행 계획",
                    "input": result["response"],
                    "output": result["flight_plan"],
                },
            ]
        },
    }


def run_ticks(seed: int, brief: dict, n_ticks: int, dt: float) -> list[dict]:
    """Run `n_ticks` world ticks in-process (no network, no sleep).

    Builds the scenario once, then advances the world and onboard pipeline
    deterministically in closed loop: each cycle's flight_plan steers the next
    world tick, and its flight_plan_state feeds the next run_cycle. `ts_ms`
    comes from world.tick's own seq*dt accumulation, not wall-clock time —
    this makes the result of two calls with the same arguments byte-identical.
    """
    scenario = build_scenario(seed, brief)
    bbox = scenario["bbox"]
    w = world.World(
        scenario["route"], scenario["events"], brief, enemies=scenario["all_enemies"]
    )
    sortie_id = brief.get("sortie_id", "SORTIE")

    previous_qualities: dict | None = None
    command: dict | None = None
    prev_fps: dict | None = None
    records = []
    for _ in range(n_ticks):
        w.tick(dt, command)
        snapshot = w.snapshot()
        raw = envelope.synthesize(snapshot, sortie_id, bbox)
        result = run_cycle(
            raw,
            brief,
            previous_qualities,
            cycle_context=None,
            previous_flight_plan_state=prev_fps,
        )
        command = result["flight_plan"]
        prev_fps = result.get("flight_plan_state")
        previous_qualities = {
            ch["channel"]: ch["quality"] for ch in result["abstraction"]["channels"]
        }
        records.append(
            {
                "seq": snapshot["seq"],
                "s": snapshot["s"],
                "snapshot": snapshot,
                "result": result,
                "flight_plan": result["flight_plan"],
            }
        )
    return records


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="In-process world sim runner — feeds onboard pipeline results to the log collector",
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--brief", required=True, help="mission brief JSON path")
    parser.add_argument("--rate", type=float, default=1.0, help="cycle rate in Hz")
    parser.add_argument("--speed", type=float, default=1.0, help="sim speed multiplier")
    parser.add_argument(
        "--duration", type=float, default=None, help="sim seconds to run (default: infinite)"
    )
    parser.add_argument("--collector", default=DEFAULT_COLLECTOR_URL)
    parser.add_argument(
        "--directive",
        default=None,
        help="set_mission JSON path — GCS directive_text biases briefed enemy types",
    )
    args = parser.parse_args(argv)

    brief = json.loads(Path(args.brief).read_text(encoding="utf-8"))
    sortie_id = brief.get("sortie_id", "SORTIE")
    corridor = brief["corridor"]

    briefing = load_briefing(args.directive) if args.directive else None
    briefed_threats: dict | None = None
    enemy_tracks: list[dict] | None = None
    if briefing is not None:
        briefed_threats = {}
        for t in briefing["threats"]:
            briefed_threats[t["threat"]] = max(
                briefed_threats.get(t["threat"], 0.0), t["confidence"]
            )
        enemy_tracks = briefing.get("enemy_tracks") or None

    scenario = build_scenario(args.seed, brief, briefed_threats, enemy_tracks)
    bbox = scenario["bbox"]
    rt = scenario["route"]
    evs = scenario["events"]
    popup_enemies = scenario["popup_enemies"]
    all_enemies = scenario["all_enemies"]
    discovered: set[int] = set()  # indices into popup_enemies, persists across ticks
    w = world.World(rt, evs, brief, enemies=all_enemies)

    import httpx  # lazy — only the network-driving CLI path needs it (CI 미설치 대응)

    client = httpx.Client(timeout=3.0)

    init_payload = {
        "terrain": terrain.build_terrain_grid(),
        "route": rt,
        "corridor": corridor,
        "events": [
            {"type": e["type"], "s_start": e["s_start"], "s_end": e["s_end"]} for e in evs
        ],
        "enemies": scenario["enemies"],
        "popup_count": len(popup_enemies),
        "background": "satellite" if brief.get("frame") else "procedural",
    }
    if briefing is not None:
        init_payload["briefing"] = briefing
    try:
        client.post(f"{args.collector}/init", json=init_payload)
    except Exception as exc:
        print(f"[runner] POST {args.collector}/init failed: {exc}", file=sys.stderr)

    # Seed the collector's control channel so dashboard readout and runner agree.
    try:
        client.post(f"{args.collector}/control", json={"speed": args.speed})
    except Exception as exc:
        print(f"[runner] POST {args.collector}/control failed: {exc}", file=sys.stderr)

    effective_speed = args.speed
    last_paused = False
    last_reset = None
    max_cycles = None if args.duration is None else max(1, round(args.duration * args.rate))
    previous_qualities: dict | None = None
    command: dict | None = None
    prev_fps: dict | None = None

    try:
        cycle = 0
        while max_cycles is None or cycle < max_cycles:
            # Poll the collector's control channel; on failure keep last known speed.
            try:
                control = client.get(f"{args.collector}/control").json()
                polled = float(control.get("speed", args.speed))
                paused = bool(control.get("paused", False))
                reset = control.get("reset")
            except Exception:
                polled = effective_speed
                paused = last_paused
                reset = last_reset
            if reset is not None and reset != last_reset:
                # Reset nonce changed — rebuild the world from the same
                # seed/brief (identical run from s=0) and re-post /init so
                # the dashboard rebuilds terrain/route and clears its trail.
                print(f"[runner] reset → {reset}")
                w = world.World(rt, evs, brief, enemies=all_enemies)
                previous_qualities = None
                command = None
                prev_fps = None
                discovered.clear()
                try:
                    client.post(f"{args.collector}/init", json=init_payload)
                except Exception as exc:
                    print(
                        f"[runner] POST {args.collector}/init failed: {exc}", file=sys.stderr
                    )
                last_reset = reset
            if polled != effective_speed:
                print(f"[runner] speed → {polled}")
                effective_speed = polled
            if paused != last_paused:
                print(f"[runner] paused → {paused}")
                last_paused = paused
            # When paused, freeze the world (dt=0) but keep emitting tick/log
            # so the dashboard stays connected and shows the frozen position.
            dt = 0.0 if paused else effective_speed / args.rate

            w.tick(dt, command)
            snapshot = w.snapshot()
            raw = envelope.synthesize(snapshot, sortie_id, bbox)
            result = run_cycle(
                raw,
                brief,
                previous_qualities,
                cycle_context=None,
                previous_flight_plan_state=prev_fps,
            )
            command = result["flight_plan"]
            prev_fps = result.get("flight_plan_state")
            previous_qualities = {
                ch["channel"]: ch["quality"] for ch in result["abstraction"]["channels"]
            }
            cycle += 1

            correlation_id = f"{sortie_id}-{snapshot['seq']}"
            post_entries(
                cycle_to_log_entries(correlation_id, result),
                f"{args.collector}/log",
                client=client,
            )

            # A popup enemy is "discovered" once the drone enters its detection
            # radius; the discovered set persists across ticks (cumulative).
            for i, en in enumerate(popup_enemies):
                if i in discovered:
                    continue
                if math.hypot(snapshot["x"] - en["x"], snapshot["y"] - en["y"]) < en["radius"]:
                    discovered.add(i)
                    print(f"[runner] popup enemy discovered: {en['kind']}")
            discovered_list = [en for i, en in enumerate(popup_enemies) if i in discovered]

            tick_payload = build_tick_payload(
                snapshot, result, discovered_list, raw=raw, brief=brief
            )
            try:
                client.post(f"{args.collector}/tick", json=tick_payload)
            except Exception as exc:
                print(f"[runner] POST {args.collector}/tick failed: {exc}", file=sys.stderr)

            flight_action = result.get("response", {}).get("flight_action")
            print(f"{snapshot['seq']} · s={snapshot['s']:.4f} · flight_action={flight_action}")

            time.sleep(1.0 / args.rate)
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
