"""07. Flight Planning — ResponseOutput → FlightPlanOutput.

run() 은 (FlightPlanOutput, debounce_state) 튜플을 반환한다 — RAC 완화 디바운스
(ADR-004 07 한정 명시적 예외, debounce.py 참고) 상태를 사이클 간 threading 하기
위함이다. debounce_state=None(기본값)이면 첫 사이클로 취급해 디바운스 없이
즉시 반영한다. FlightPlanOutput 스키마 자체는 이 상태를 포함하지 않는다.
"""

from ..shared.constants import TIME_TO_COLLISION_THRESHOLD_S
from ..shared.schemas import FlightPlanOutput, ResponseOutput
from . import altitude, bearing, debounce, route as route_gen, speed

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
    debounce_state: dict | None = None,
) -> tuple[FlightPlanOutput, dict]:
    """06의 ResponseOutput과 04의 primary_context·cycle_context → MAVLink급 지시값.

    primary_context: 04의 candidates[0].context. 위협 없거나 미탐지 시 None.
    cycle_context: obstacle_ttc_s 포함 시 CFIT 결정론적 override 적용.
        weights(mission_brief.weights) 포함 시 speed_mode 조정에 사용(speed.py 참고).
    debounce_state: 이전 사이클의 RAC 완화 디바운스 상태(없으면 첫 사이클 취급).

    반환: (FlightPlanOutput, new_debounce_state). CFIT override 는 디바운스
    결과보다 항상 우선(안전 최우선, SCC-1) 적용된다.
    """
    effective_action, new_debounce_state = debounce.apply_debounce(
        response["rac"],
        response["flight_action"],
        response["primary_threat_event"],
        response["kill_chain_stage"],
        debounce_state,
    )
    scope = _REPLAN_SCOPE[effective_action]

    threat_bearing: float | None = None
    if primary_context is not None:
        threat_bearing = primary_context.get("bearing_deg")

    tgt_bearing, b_anchor = bearing.compute_bearing(
        response["threat_category"], threat_bearing, cycle_context
    )
    delta, alt_anchor = altitude.compute_altitude_delta(effective_action)

    # CFIT 결정론적 override: TTC<3s + 고도변화 없음 → ALTITUDE_CHANGE 강제 (RAC 무관, SCC-1)
    ttc = cycle_context.get("obstacle_ttc_s")
    cfit_triggered = ttc is not None and ttc < TIME_TO_COLLISION_THRESHOLD_S and delta == 0
    if cfit_triggered:
        effective_action = "ALTITUDE_CHANGE"
        delta, alt_anchor = altitude.compute_altitude_delta("ALTITUDE_CHANGE")
        scope = _REPLAN_SCOPE["ALTITUDE_CHANGE"]

    # MAINTAIN(replan_scope=NONE) → D4D는 새 지시를 안 내지만, 오토파일럿에게 "미션시퀀서로
    # 통제권 반환"을 명시적으로 알려준다(신규 확정 — 이전 라운드의 null 계약을 뒤집음).
    # 무상태 파이프라인이라 "직전에 회피 중이었는지" 구분 없이 MAINTAIN이면 항상 이 값.
    final_anchor = "mission_corridor_resume" if scope == "NONE" else (b_anchor or alt_anchor)

    generated_route = route_gen.generate_route(effective_action, delta, scope, cycle_context)

    # CFIT override로 effective_action이 바뀌었으면 speed_mode도 override 이후 값을 따름
    # (altitude_delta_m과 동일한 처리 순서). CFIT는 안전 최우선(SCC-1)이라 weights를
    # 넘기지 않는다 — 지형충돌 임박 상황에서 스텔스 선호로 속도를 늦추면 안 되기 때문.
    weights = None if cfit_triggered else cycle_context.get("weights")
    speed_mode = speed.compute_speed_mode(effective_action, weights)

    return FlightPlanOutput(
        flight_action=effective_action,
        target_bearing_deg=tgt_bearing,
        altitude_delta_m=delta,
        replan_scope=scope,
        reroute_anchor=final_anchor,
        route=generated_route,
        speed_mode=speed_mode,
    ), new_debounce_state
