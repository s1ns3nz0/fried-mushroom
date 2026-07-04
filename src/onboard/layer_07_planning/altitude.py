"""07. Flight Planning — flight_action별 고도 조정량."""

from ..shared.constants import (
    ALTITUDE_DELTA_PREVENTIVE_M,
    ALTITUDE_DELTA_TERRAIN_M,
    POSTURE_ELEVATE_ALTITUDE_M,
)

_DELTA_MAP: dict[str, tuple[int, str | None]] = {
    "ALTITUDE_CHANGE":          (ALTITUDE_DELTA_PREVENTIVE_M, "altitude_only"),
    "POSTURE_ELEVATE":          (POSTURE_ELEVATE_ALTITUDE_M,  "altitude_only"),
    "ALTITUDE_CHANGE_REROUTE":  (ALTITUDE_DELTA_TERRAIN_M,    None),
    "RTL":                      (0,                            None),
    "REROUTE":                  (0,                            None),
    "MAINTAIN":                 (0,                            None),
}


def compute_altitude_delta(flight_action: str) -> tuple[int, str | None]:
    """flight_action → (altitude_delta_m, anchor_hint)."""
    return _DELTA_MAP[flight_action]
