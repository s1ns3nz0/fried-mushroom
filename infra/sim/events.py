"""Seed-based pre-placement of scenario events bound to arc-length position s.

No tick/time/dt concept here: every event is placed once, up front, at
generation time using a single random.Random(seed) instance. Downstream
consumers query which events are active at a given s via active_events().
"""
import random

T1_JAMMING_PROB = 0.7
T1_JAMMING_ZONE_FRAC = 0.15
T1_JAMMING_INTENSITY_RANGE = (0.3, 1.0)

T2_LINK_DEGRADE_PROB = 0.7
T2_LINK_DEGRADE_ZONE_FRAC = 0.10
T2_LINK_DEGRADE_INTENSITY_RANGE = (0.3, 1.0)

T3_AMBUSH_PROB = 0.6
T3_AMBUSH_COUNT_RANGE = (1, 2)
T3_AMBUSH_INTENSITY_RANGE = (0.5, 1.0)

T4_CAPTURE_PROB = 0.5
T4_CAPTURE_COUNT_RANGE = (1, 1)
T4_CAPTURE_INTENSITY_RANGE = (0.5, 1.0)

T7_OBSTACLE_PROB = 0.8
T7_OBSTACLE_COUNT_RANGE = (1, 3)
T7_OBSTACLE_INTENSITY_RANGE = (0.3, 1.0)


def _make_zone_event(rng, event_type, total_s, zone_frac, intensity_range):
    zone_len = min(total_s * zone_frac, total_s)
    max_start = max(total_s - zone_len, 0.0)
    s_start = rng.uniform(0.0, max_start) if max_start > 0 else 0.0
    s_end = s_start + zone_len
    return {
        "type": event_type,
        "s_start": s_start,
        "s_end": s_end,
        "params": {"intensity": rng.uniform(*intensity_range)},
    }


def _make_point_event(rng, event_type, total_s, intensity_range):
    s = rng.uniform(0.0, total_s)
    return {
        "type": event_type,
        "s_start": s,
        "s_end": s,
        "params": {"intensity": rng.uniform(*intensity_range)},
    }


def _make_ambush_event(rng, total_s):
    s = rng.uniform(0.0, total_s)
    return {
        "type": "T3_ambush",
        "s_start": s,
        "s_end": s,
        "params": {
            "bearing_deg": rng.uniform(0.0, 360.0),
            "intensity": rng.uniform(*T3_AMBUSH_INTENSITY_RANGE),
        },
    }


def generate_events(seed: int, total_s: float) -> list[dict]:
    rng = random.Random(seed)
    result = []

    if rng.random() < T1_JAMMING_PROB:
        result.append(
            _make_zone_event(rng, "T1_jamming", total_s, T1_JAMMING_ZONE_FRAC, T1_JAMMING_INTENSITY_RANGE)
        )

    if rng.random() < T2_LINK_DEGRADE_PROB:
        result.append(
            _make_zone_event(
                rng, "T2_link_degrade", total_s, T2_LINK_DEGRADE_ZONE_FRAC, T2_LINK_DEGRADE_INTENSITY_RANGE
            )
        )

    if rng.random() < T3_AMBUSH_PROB:
        count = rng.randint(*T3_AMBUSH_COUNT_RANGE)
        for _ in range(count):
            result.append(_make_ambush_event(rng, total_s))

    if rng.random() < T4_CAPTURE_PROB:
        count = rng.randint(*T4_CAPTURE_COUNT_RANGE)
        for _ in range(count):
            result.append(_make_point_event(rng, "T4_capture", total_s, T4_CAPTURE_INTENSITY_RANGE))

    if rng.random() < T7_OBSTACLE_PROB:
        count = rng.randint(*T7_OBSTACLE_COUNT_RANGE)
        for _ in range(count):
            result.append(_make_point_event(rng, "T7_obstacle", total_s, T7_OBSTACLE_INTENSITY_RANGE))

    result.sort(key=lambda e: e["s_start"])
    return result


def active_events(events: list[dict], s: float) -> list[dict]:
    return [e for e in events if e["s_start"] <= s <= e["s_end"]]
