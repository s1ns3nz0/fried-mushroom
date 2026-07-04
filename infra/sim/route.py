"""METT+TC route generator: maps a mission brief's lat/lon corridor onto the
normalized [0,1] plane shared with terrain.py, inserts a midpoint between each
consecutive skeleton waypoint pair, and biases those midpoints (and route
altitude) using weights.stealth / weights.timeliness / posture.watchcon.
Deterministic — no randomness.
"""
import math

import terrain

MARGIN = 0.1
SPAN = 1.0 - 2 * MARGIN  # 0.8

CLEARANCE_MAX_M = 100.0  # clearance above terrain when stealth ~= 0
CLEARANCE_FLOOR_M = 20.0  # clearance above terrain when stealth ~= 1 (floor)

WATCHCON_BASELINE = 5  # least alert; lower watchcon = higher alert
WATCHCON_AMP_STEP = 0.15  # amplification per level below baseline

OFFSET_BASE = 0.06  # max lateral midpoint offset, normalized plane units

ENEMY_AVOID_MARGIN = 0.02  # extra keep-out distance beyond enemy radius

SEGMENT_DETOUR_BUFFER = 0.005  # extra push past keep-out for inserted detours
SEGMENT_AVOID_MAX_ITER = 8  # cap on re-check passes to guarantee termination


def compute_bbox(waypoints):
    lats = [wp["lat"] for wp in waypoints]
    lons = [wp["lon"] for wp in waypoints]
    return {
        "lat_min": min(lats),
        "lat_max": max(lats),
        "lon_min": min(lons),
        "lon_max": max(lons),
    }


def to_norm(lat, lon, bbox):
    lat_range = (bbox["lat_max"] - bbox["lat_min"]) or 1.0
    lon_range = (bbox["lon_max"] - bbox["lon_min"]) or 1.0
    x = MARGIN + (lon - bbox["lon_min"]) / lon_range * SPAN
    y = MARGIN + (bbox["lat_max"] - lat) / lat_range * SPAN
    return (x, y)


def to_geo(x, y, bbox):
    lat_range = (bbox["lat_max"] - bbox["lat_min"]) or 1.0
    lon_range = (bbox["lon_max"] - bbox["lon_min"]) or 1.0
    lon = bbox["lon_min"] + (x - MARGIN) / SPAN * lon_range
    lat = bbox["lat_max"] - (y - MARGIN) / SPAN * lat_range
    return (lat, lon)


def _effective_stealth(weights, posture):
    stealth = weights.get("stealth", 0.0)
    watchcon = posture.get("watchcon", WATCHCON_BASELINE)
    amplification = 1.0 + max(0, WATCHCON_BASELINE - watchcon) * WATCHCON_AMP_STEP
    return min(1.0, stealth * amplification)


def _clearance_m(effective_stealth):
    return CLEARANCE_FLOOR_M + (1.0 - effective_stealth) * (
        CLEARANCE_MAX_M - CLEARANCE_FLOOR_M
    )


def _offset_scale(effective_stealth, timeliness):
    timeliness = max(0.0, min(1.0, timeliness))
    return OFFSET_BASE * effective_stealth * (1.0 - timeliness)


def _clamp01(v):
    return max(0.0, min(1.0, v))


def _biased_midpoint(a, b, offset_scale):
    ax, ay = a
    bx, by = b
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length == 0.0 or offset_scale == 0.0:
        return (_clamp01(mx), _clamp01(my))

    # Unit perpendicular to the AB segment.
    px, py = -dy / length, dx / length
    cand1 = (_clamp01(mx + px * offset_scale), _clamp01(my + py * offset_scale))
    cand2 = (_clamp01(mx - px * offset_scale), _clamp01(my - py * offset_scale))

    # Nudge toward the lower-terrain candidate (stealth heuristic).
    h1 = terrain.height_at(*cand1)
    h2 = terrain.height_at(*cand2)
    return cand1 if h1 <= h2 else cand2


def _point_segment_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _avoid_enemies(points, enemies):
    adjusted = list(points)
    for i in range(1, len(adjusted) - 1):
        for enemy in enemies:
            ex, ey = enemy["x"], enemy["y"]
            keep_out = enemy["radius"] + ENEMY_AVOID_MARGIN
            px, py = adjusted[i]
            dx, dy = px - ex, py - ey
            dist = math.hypot(dx, dy)
            if dist >= keep_out:
                continue
            if dist == 0.0:
                # Point sits exactly on the enemy center: displace along the
                # neighbor segment's perpendicular toward lower terrain.
                ax, ay = adjusted[i - 1]
                bx, by = adjusted[i + 1]
                sx, sy = bx - ax, by - ay
                length = math.hypot(sx, sy)
                if length == 0.0:
                    ux, uy = 1.0, 0.0
                else:
                    ux, uy = -sy / length, sx / length
                cand1 = (_clamp01(px + ux * keep_out), _clamp01(py + uy * keep_out))
                cand2 = (_clamp01(px - ux * keep_out), _clamp01(py - uy * keep_out))
                h1 = terrain.height_at(*cand1)
                h2 = terrain.height_at(*cand2)
                adjusted[i] = cand1 if h1 <= h2 else cand2
            else:
                adjusted[i] = (
                    _clamp01(ex + dx / dist * keep_out),
                    _clamp01(ey + dy / dist * keep_out),
                )
    return adjusted


def _push_point_out(x, y, enemies, push_extra):
    # Radially push a point out of every enemy keep-out circle. Overlapping
    # circles may re-capture the point, so iterate with a cap (deterministic;
    # if the cap is hit the point is returned as-is).
    for _ in range(SEGMENT_AVOID_MAX_ITER):
        moved = False
        for enemy in enemies:
            ex, ey = enemy["x"], enemy["y"]
            keep_out = enemy["radius"] + ENEMY_AVOID_MARGIN
            dx, dy = x - ex, y - ey
            dist = math.hypot(dx, dy)
            if dist >= keep_out:
                continue
            if dist == 0.0:
                ux, uy = 1.0, 0.0
            else:
                ux, uy = dx / dist, dy / dist
            x = _clamp01(ex + ux * (keep_out + push_extra))
            y = _clamp01(ey + uy * (keep_out + push_extra))
            moved = True
        if not moved:
            break
    return (x, y)


def _avoid_enemy_segments(points, enemies):
    adjusted = list(points)
    # Iterate because an inserted detour creates two new segments that may
    # themselves clip a keep-out circle. Capped to guarantee termination; if
    # the cap is hit a residual violation may remain (deterministic either way).
    for _ in range(SEGMENT_AVOID_MAX_ITER):
        inserted = False
        i = 0
        while i < len(adjusted) - 1:
            ax, ay = adjusted[i]
            bx, by = adjusted[i + 1]
            inserted_here = False
            for enemy in enemies:
                ex, ey = enemy["x"], enemy["y"]
                keep_out = enemy["radius"] + ENEMY_AVOID_MARGIN
                if _point_segment_dist(ex, ey, ax, ay, bx, by) >= keep_out:
                    continue
                dx, dy = bx - ax, by - ay
                seg_len_sq = dx * dx + dy * dy
                if seg_len_sq == 0.0:
                    # Degenerate segment: endpoint case is handled by the
                    # waypoint push-out pass.
                    continue
                t = max(0.0, min(1.0, ((ex - ax) * dx + (ey - ay) * dy) / seg_len_sq))
                cx, cy = ax + t * dx, ay + t * dy
                ox, oy = cx - ex, cy - ey
                olen = math.hypot(ox, oy)
                push = keep_out + SEGMENT_DETOUR_BUFFER
                if olen == 0.0:
                    # Enemy center lies exactly on the segment: push along the
                    # perpendicular toward the lower-terrain side.
                    seg_len = math.sqrt(seg_len_sq)
                    ux, uy = -dy / seg_len, dx / seg_len
                    cand1 = (_clamp01(ex + ux * push), _clamp01(ey + uy * push))
                    cand2 = (_clamp01(ex - ux * push), _clamp01(ey - uy * push))
                    h1 = terrain.height_at(*cand1)
                    h2 = terrain.height_at(*cand2)
                    detour = cand1 if h1 <= h2 else cand2
                else:
                    detour = (
                        _clamp01(ex + ox / olen * push),
                        _clamp01(ey + oy / olen * push),
                    )
                # Overlapping keep-outs: make sure the inserted point itself
                # clears every enemy circle, not just the triggering one.
                detour = _push_point_out(
                    detour[0], detour[1], enemies, SEGMENT_DETOUR_BUFFER
                )
                if detour == (ax, ay) or detour == (bx, by):
                    # Clamping collapsed the detour onto an endpoint; inserting
                    # it cannot improve the segment.
                    continue
                adjusted.insert(i + 1, detour)
                inserted = True
                inserted_here = True
                break
            # Skip past a freshly inserted detour within this pass; the outer
            # loop re-checks the new segments on the next iteration.
            i += 2 if inserted_here else 1
        if not inserted:
            break
    return adjusted


def generate_route(brief, enemies=None):
    corridor = brief["corridor"]
    weights = brief.get("weights", {})
    posture = brief.get("posture", {})

    bbox = compute_bbox(corridor["waypoints"])
    skeleton = [to_norm(wp["lat"], wp["lon"], bbox) for wp in corridor["waypoints"]]

    effective_stealth = _effective_stealth(weights, posture)
    timeliness = weights.get("timeliness", 0.0)
    clearance = _clearance_m(effective_stealth)
    offset_scale = _offset_scale(effective_stealth, timeliness)

    points = [skeleton[0]]
    for a, b in zip(skeleton, skeleton[1:]):
        points.append(_biased_midpoint(a, b, offset_scale))
        points.append(b)

    if enemies:
        points = _avoid_enemies(points, enemies)
        points = _avoid_enemy_segments(points, enemies)

    waypoints = []
    for x, y in points:
        elev = terrain.elev_m(terrain.height_at(x, y))
        waypoints.append({"x": x, "y": y, "alt_m": elev + clearance})

    return {"waypoints": waypoints}
