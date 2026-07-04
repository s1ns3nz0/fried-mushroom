"""07. Flight Planning — RAC 완화(de-escalation) 디바운스 (ADR-004 07 한정 명시적 예외).

06 은 RAC 를 매 사이클 결정론적으로 재계산하는 무상태 함수라, 링크 열화·센서
노이즈로 RAC 가 흔들리면 RTL<->MAINTAIN 이 매 사이클 진동할 수 있다. 05 가 이미
쓰는 RAC_ORDER(High=1 < Serious=2 < Medium=3 < Low=4, 숫자가 작을수록 심각)를
재사용해 비대칭 디바운스를 적용한다:

  악화(RAC_ORDER 숫자 감소) -> 즉시 반영 (SCC-1 안전 우선, 디바운스 없음)
  완화(RAC_ORDER 숫자 증가) -> FLIGHT_ACTION_DEESCALATE_DEBOUNCE_CYCLES 사이클
                                연속 유지될 때만 반영

(신규, grill-me 라운드3) flight_comms.resolve()는 RAC=High 구간에서 flight_action이
RAC뿐 아니라 kill_chain_stage(초기/중기/후기)·threat_category에도 좌우된다
(예: High+초기=POSTURE_ELEVATE, High+후기+PHYSICAL=RTL — 둘 다 RAC_ORDER=1).
RAC_ORDER만 비교하면 RAC=High가 유지된 채 kill_chain_stage가 진행돼도(진짜 위협
임박) "변화 없음"으로 오판해 committed_flight_action을 고정하는 버그가 있었다.
다음 두 조건도 디바운스 없이 즉시 반영한다:
  - primary_threat_event 변경 -> 완전히 다른 위협이므로 상태 리셋(첫 사이클처럼 즉시 반영)
  - RAC_ORDER 동일 + kill_chain_stage 진행(KILL_CHAIN_STAGE_ORDER 증가, 같은 threat_event) -> 악화로 간주, 즉시 반영

CFIT override(07/run.py, TTC<3s)는 이 모듈 책임범위 밖 — run.py 에서 이 함수
호출 이후 별도로, 이 함수의 결과보다 항상 우선 적용된다.

상태(debounce_state)는 03의 previous_qualities/extract_qualities 선례와 동일한
방식(별도 채널)으로 사이클 간 threading 된다. FlightPlanOutput 스키마는 이
상태를 포함하지 않는다.
"""

from __future__ import annotations

from ..shared.constants import (
    FLIGHT_ACTION_DEESCALATE_DEBOUNCE_CYCLES,
    KILL_CHAIN_STAGE_ORDER,
    RAC_ORDER,
)


def apply_debounce(
    rac: str,
    flight_action: str,
    primary_threat_event: str | None,
    kill_chain_stage: str | None,
    state: dict | None,
) -> tuple[str, dict]:
    """(현재 rac/flight_action/primary_threat_event/kill_chain_stage, 이전 debounce_state)
    -> (effective_action, new_state).

    state 가 None(첫 사이클)이거나 primary_threat_event 가 committed 값과 다르면
    (완전히 다른 위협) 디바운스 없이 즉시 위임하고 committed 상태를 초기화한다.
    """
    current_order = RAC_ORDER[rac]

    if state is None or primary_threat_event != state.get("committed_primary_threat_event"):
        return flight_action, _committed(
            current_order, flight_action, primary_threat_event, kill_chain_stage
        )

    committed_order = state["committed_rac_order"]
    stage_progressed = _stage_order(kill_chain_stage) > _stage_order(
        state.get("committed_kill_chain_stage")
    )

    if current_order < committed_order or (current_order == committed_order and stage_progressed):
        # 악화(RAC_ORDER 감소, 또는 동일 RAC에서 kill_chain_stage 진행) — 즉시 반영
        return flight_action, _committed(
            current_order, flight_action, primary_threat_event, kill_chain_stage
        )

    if current_order > committed_order:
        # 완화 — N사이클 연속일 때만 반영
        if state.get("candidate_rac_order") == current_order:
            streak = state["candidate_streak"] + 1
        else:
            streak = 1

        if streak >= FLIGHT_ACTION_DEESCALATE_DEBOUNCE_CYCLES:
            return flight_action, _committed(
                current_order, flight_action, primary_threat_event, kill_chain_stage
            )

        return state["committed_flight_action"], {
            **state,
            "candidate_rac_order": current_order,
            "candidate_streak": streak,
        }

    # 변화 없음(RAC_ORDER 동일, stage 진행 없음) — committed 유지, candidate 리셋
    return state["committed_flight_action"], {
        **state,
        "candidate_rac_order": None,
        "candidate_streak": 0,
    }


def _stage_order(kill_chain_stage: str | None) -> int:
    """kill_chain_stage 순서값(없으면 0 — 항상 가장 낮은 취급, 진행으로 오판 안 되게)."""
    if kill_chain_stage is None:
        return 0
    return KILL_CHAIN_STAGE_ORDER[kill_chain_stage]


def _committed(
    rac_order: int,
    flight_action: str,
    primary_threat_event: str | None,
    kill_chain_stage: str | None,
) -> dict:
    """committed 상태 초기화/갱신 (candidate 추적 리셋)."""
    return {
        "committed_rac_order": rac_order,
        "committed_flight_action": flight_action,
        "committed_primary_threat_event": primary_threat_event,
        "committed_kill_chain_stage": kill_chain_stage,
        "candidate_rac_order": None,
        "candidate_streak": 0,
    }
