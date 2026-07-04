"""Deterministic per-tick physics evolution of the sim world's drone state.

Consumes route.py (arc-length waypoints), events.py (seed-placed threat
events) and a mission brief, and advances arc-length position s, altitude,
heading, speed and battery on tick(dt, command=None). Phases: outbound
(s 0 -> total), return (s total -> 0), complete (holds at s=0).

Closed-loop steering: `command` is the prior cycle's flight_plan dict
{flight_action, target_bearing_deg, altitude_delta_m, replan_scope,
speed_mode}. Command -> motion mapping:
- None / MAINTAIN: lateral offset and altitude offset linearly decay to 0
  (drone re-joins the planned route).
- REROUTE / ALTITUDE_CHANGE_REROUTE with target_bearing_deg: lateral offset
  accrues toward the bearing at EVADE_LATERAL_SHARE of the move rate, capped
  at EVADE_OFFSET_MAX_NORM; s still advances along the route.
- ALTITUDE_CHANGE / POSTURE_ELEVATE / ALTITUDE_CHANGE_REROUTE: alt offset
  moves toward altitude_delta_m at CLIMB_RATE_MPS.
- RTL: outbound phase flips to return immediately; offset decays.
- speed_mode (CAUTIOUS/NORMAL/MAX): scales this tick's speed via
  SPEED_MODE_FACTOR.
Final position = route point + offset; alt_m = route alt + alt_offset_m;
heading_deg = compass bearing of the actual displacement. No randomness —
with command=None behavior is identical to the plain open-loop tick.
"""
import math

import path
import terrain
import events as events_module

MAP_EXTENT_M = 3000  # matches infra/dashboard/static/app.js MAP_EXTENT_M

SPEED_MPS = 17.0
BATTERY_DRAIN_PCT_PER_SEC = 0.1  # ~200s t3 mission -> ~20% drain, small/sec

EVADE_LATERAL_SHARE = 0.5
EVADE_OFFSET_MAX_NORM = 100.0 / MAP_EXTENT_M
CLIMB_RATE_MPS = 3.0
SPEED_MODE_FACTOR = {"CAUTIOUS": 0.7, "NORMAL": 1.0, "MAX": 1.3}


class World:
    def __init__(self, route, events, brief, enemies=None):
        self.route = route
        self.events = events
        self.brief = brief
        self.enemies = enemies

        self._total_length = path.total_length(route["waypoints"])

        self.s = 0.0
        self.phase = "outbound"
        point = path.point_at_s(route["waypoints"], self.s)
        self.pos = (point["x"], point["y"])
        self.alt_m = point["alt_m"]
        self.heading_deg = point["heading_deg"]
        self.speed_mps = SPEED_MPS
        self.battery_pct = brief["drone_profile"]["battery_pct"]
        self.seq = 0
        self.ts_ms = 0
        self.offset = (0.0, 0.0)
        self.alt_offset_m = 0.0

    def tick(self, dt, command=None):
        action = command.get("flight_action") if command else None
        speed_mode = command.get("speed_mode") if command else None
        target_bearing_deg = command.get("target_bearing_deg") if command else None
        altitude_delta_m = command.get("altitude_delta_m") if command else None

        speed_mps = SPEED_MPS * SPEED_MODE_FACTOR.get(speed_mode, 1.0)
        prev_x, prev_y = self.pos

        ds = (speed_mps / MAP_EXTENT_M) * dt
        if self.phase == "outbound":
            self.s += ds
            if self.s >= self._total_length:
                self.s = self._total_length
                self.phase = "return"
        elif self.phase == "return":
            self.s -= ds
            if self.s <= 0.0:
                self.s = 0.0
                self.phase = "complete"

        if action == "RTL" and self.phase == "outbound":
            self.phase = "return"

        point = path.point_at_s(self.route["waypoints"], self.s)

        lateral_rate = (speed_mps / MAP_EXTENT_M) * dt
        if (
            action in ("REROUTE", "ALTITUDE_CHANGE_REROUTE")
            and target_bearing_deg is not None
        ):
            b = math.radians(target_bearing_deg)
            ox = self.offset[0] + math.sin(b) * EVADE_LATERAL_SHARE * lateral_rate
            oy = self.offset[1] - math.cos(b) * EVADE_LATERAL_SHARE * lateral_rate
            norm = math.hypot(ox, oy)
            if norm > EVADE_OFFSET_MAX_NORM:
                scale = EVADE_OFFSET_MAX_NORM / norm
                ox, oy = ox * scale, oy * scale
            self.offset = (ox, oy)
        else:
            ox, oy = self.offset
            norm = math.hypot(ox, oy)
            if norm <= lateral_rate:
                self.offset = (0.0, 0.0)
            else:
                scale = (norm - lateral_rate) / norm
                self.offset = (ox * scale, oy * scale)

        if action in ("ALTITUDE_CHANGE", "POSTURE_ELEVATE", "ALTITUDE_CHANGE_REROUTE"):
            alt_target = altitude_delta_m if altitude_delta_m is not None else 0.0
        else:
            alt_target = 0.0
        alt_step = CLIMB_RATE_MPS * dt
        alt_diff = alt_target - self.alt_offset_m
        if abs(alt_diff) <= alt_step:
            self.alt_offset_m = alt_target
        else:
            self.alt_offset_m += alt_step if alt_diff > 0 else -alt_step

        new_x = point["x"] + self.offset[0]
        new_y = point["y"] + self.offset[1]
        self.pos = (new_x, new_y)
        self.alt_m = point["alt_m"] + self.alt_offset_m

        dx, dy = new_x - prev_x, new_y - prev_y
        if math.hypot(dx, dy) < 1e-9:
            self.heading_deg = point["heading_deg"]
        else:
            self.heading_deg = math.degrees(math.atan2(dx, -dy)) % 360

        self.speed_mps = speed_mps
        self.battery_pct = max(0.0, self.battery_pct - BATTERY_DRAIN_PCT_PER_SEC * dt)

        self.seq += 1
        self.ts_ms += round(dt * 1000)

    def _proximity_active_events(self, x, y) -> list:
        active = []
        for e in self.enemies:
            if math.hypot(x - e["x"], y - e["y"]) < e["radius"]:
                active.append(
                    {
                        "type": e["type"],
                        "s_start": e.get("s", self.s),
                        "s_end": e.get("s", self.s),
                        "params": e.get("params", {}),
                    }
                )
        return active

    def snapshot(self) -> dict:
        x, y = self.pos
        if self.enemies is None:
            active = events_module.active_events(self.events, self.s)
        else:
            active = self._proximity_active_events(x, y)
        return {
            "seq": self.seq,
            "ts_ms": self.ts_ms,
            "s": self.s,
            "phase": self.phase,
            "x": x,
            "y": y,
            "alt_m": self.alt_m,
            "terrain_m": terrain.elev_m(terrain.height_at(x, y)),
            "heading_deg": self.heading_deg,
            "speed_mps": self.speed_mps,
            "battery_pct": self.battery_pct,
            "active_events": active,
        }
