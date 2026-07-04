"""07. Flight Planning — ResponseOutput → FlightPlanOutput."""

from ..shared.schemas import FlightPlanOutput, ResponseOutput
from . import altitude, bearing

_REPLAN_SCOPE: dict[str, str] = {
    "RTL":                     "LOCAL",
    "REROUTE":                 "FULL",
    "ALTITUDE_CHANGE_REROUTE": "FULL",
    "ALTITUDE_CHANGE":         "LOCAL",
    "POSTURE_ELEVATE":         "LOCAL",
    "MAINTAIN":                "NONE",
}


def run(
    response: ResponseOutput,
    primary_context: dict | None,
    cycle_context: dict,
) -> FlightPlanOutput:
    """06의 ResponseOutput과 04의 primary_context·cycle_context → MAVLink급 지시값.

    primary_context: 04의 candidates[0].context. 위협 없거나 미탐지 시 None.
    """
    scope = _REPLAN_SCOPE[response["flight_action"]]

    threat_bearing: float | None = None
    if primary_context is not None:
        threat_bearing = primary_context.get("bearing_deg")

    tgt_bearing, b_anchor = bearing.compute_bearing(
        response["threat_category"], threat_bearing, cycle_context
    )
    delta, alt_anchor = altitude.compute_altitude_delta(response["flight_action"])

    final_anchor = b_anchor or alt_anchor

    return FlightPlanOutput(
        flight_action=response["flight_action"],
        target_bearing_deg=tgt_bearing,
        altitude_delta_m=delta,
        replan_scope=scope,
        reroute_anchor=final_anchor,
    )
