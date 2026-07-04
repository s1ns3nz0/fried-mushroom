"""Arc-length parameterization of a waypoint list.

Waypoint: {"x": float, "y": float, "alt_m": float}, x/y normalized [0,1]
plane coords with y=0 at top.

Heading convention: compass bearing of the segment direction vector
(dx, dy) where dx = x2 - x1, dy = y2 - y1.
  heading_deg = atan2(dx, -dy) in degrees, normalized to [0, 360).
North (-y, "up" on screen) = 0 deg, east (+x) = 90 deg,
south (+y, "down" on screen) = 180 deg, west (-x) = 270 deg.
"""
import math


def total_length(wps):
    length = 0.0
    for a, b in zip(wps, wps[1:]):
        length += math.hypot(b["x"] - a["x"], b["y"] - a["y"])
    return length


def _heading_deg(dx, dy):
    return math.degrees(math.atan2(dx, -dy)) % 360


def point_at_s(wps, s):
    if s <= 0:
        a, b = wps[0], wps[1]
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        return {
            "x": a["x"],
            "y": a["y"],
            "alt_m": a["alt_m"],
            "heading_deg": _heading_deg(dx, dy),
            "seg_index": 0,
        }

    remaining = s
    n_segments = len(wps) - 1
    for i in range(n_segments):
        a, b = wps[i], wps[i + 1]
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        seg_len = math.hypot(dx, dy)
        if remaining <= seg_len and i < n_segments - 1:
            t = remaining / seg_len if seg_len else 0.0
            return {
                "x": a["x"] + dx * t,
                "y": a["y"] + dy * t,
                "alt_m": a["alt_m"] + (b["alt_m"] - a["alt_m"]) * t,
                "heading_deg": _heading_deg(dx, dy),
                "seg_index": i,
            }
        if i == n_segments - 1:
            t = remaining / seg_len if seg_len else 0.0
            t = min(max(t, 0.0), 1.0)
            return {
                "x": a["x"] + dx * t,
                "y": a["y"] + dy * t,
                "alt_m": a["alt_m"] + (b["alt_m"] - a["alt_m"]) * t,
                "heading_deg": _heading_deg(dx, dy),
                "seg_index": i,
            }
        remaining -= seg_len
