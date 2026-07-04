"""07 debounce.py — RAC 완화(de-escalation) 디바운스 단위 테스트.

비대칭 디바운스: 악화(RAC_ORDER 숫자 감소)는 즉시 반영, 완화(숫자 증가)는
FLIGHT_ACTION_DEESCALATE_DEBOUNCE_CYCLES(3) 사이클 연속일 때만 반영.
RAC_ORDER: High=1 < Serious=2 < Medium=3 < Low=4 (05 재사용, 숫자가 작을수록 심각).

(신규, grill-me 라운드3 발견) flight_comms.resolve()는 RAC=High 구간에서
kill_chain_stage(초기/중기/후기)와 threat_category에도 좌우된다 — RAC_ORDER만
비교하면 RAC=High가 유지된 채 kill_chain_stage가 진행(초기→후기)돼도, 또는
primary_threat_event 자체가 바뀌어도 "변화 없음"으로 오판해 committed_flight_action을
그대로 고정하는 버그가 있었다. 이제 다음 조건도 즉시 반영(디바운스 없음) 대상이다:
  - primary_threat_event 변경 → 완전히 다른 위협이므로 상태 리셋(첫 사이클처럼 즉시 반영)
  - RAC_ORDER 동일 + kill_chain_stage 진행(KILL_CHAIN_STAGE_ORDER 증가) → 악화로 간주, 즉시 반영

CFIT override는 이 모듈 책임범위 밖(run.py에서 이 함수 호출 이후 별도 적용).
"""

from onboard.layer_07_planning.debounce import apply_debounce
from onboard.shared.constants import FLIGHT_ACTION_DEESCALATE_DEBOUNCE_CYCLES, RAC_ORDER


def _apply(rac, flight_action, state, threat_event="T3", stage="초기"):
    return apply_debounce(rac, flight_action, threat_event, stage, state)


def test_first_cycle_immediate_passthrough():
    """state=None(첫 사이클) → 디바운스 없이 그대로 위임, committed 초기화."""
    action, state = _apply("High", "RTL", None)
    assert action == "RTL"
    assert state["committed_rac_order"] == RAC_ORDER["High"]
    assert state["committed_flight_action"] == "RTL"
    assert state["candidate_streak"] == 0


def test_escalation_applies_immediately():
    """Medium(RTL 아님, 이전 committed) → High(악화) 전환은 즉시 반영."""
    _, state = _apply("Medium", "MAINTAIN", None)
    action, new_state = _apply("High", "RTL", state)
    assert action == "RTL", "악화는 디바운스 없이 즉시 반영돼야 함"
    assert new_state["committed_rac_order"] == RAC_ORDER["High"]
    assert new_state["committed_flight_action"] == "RTL"
    assert new_state["candidate_streak"] == 0


def test_deescalation_held_until_streak_completes():
    """High(RTL) → Medium(MAINTAIN) 완화는 N사이클 연속이어야 반영."""
    _, state = _apply("High", "RTL", None)  # committed = High/RTL

    action1, state1 = _apply("Medium", "MAINTAIN", state)
    assert action1 == "RTL", "1사이클차 완화는 아직 committed(RTL) 유지"
    assert state1["candidate_streak"] == 1

    action2, state2 = _apply("Medium", "MAINTAIN", state1)
    assert action2 == "RTL", "2사이클차도 아직 유지 (N=3 미달)"
    assert state2["candidate_streak"] == 2

    action3, state3 = _apply("Medium", "MAINTAIN", state2)
    assert action3 == "MAINTAIN", f"N={FLIGHT_ACTION_DEESCALATE_DEBOUNCE_CYCLES}사이클차에는 반영돼야 함"
    assert state3["committed_flight_action"] == "MAINTAIN"
    assert state3["committed_rac_order"] == RAC_ORDER["Medium"]
    assert state3["candidate_streak"] == 0


def test_deescalation_streak_resets_on_interruption():
    """완화 스트릭 도중 다시 committed 등급으로 돌아오면 스트릭 리셋."""
    _, state = _apply("High", "RTL", None)
    _, state1 = _apply("Medium", "MAINTAIN", state)  # streak=1
    assert state1["candidate_streak"] == 1

    action2, state2 = _apply("High", "RTL", state1)  # 다시 committed와 동일 등급
    assert action2 == "RTL"
    assert state2["candidate_streak"] == 0

    action3, state3 = _apply("Medium", "MAINTAIN", state2)  # streak 처음부터 재시작
    assert action3 == "RTL", "리셋 후 1사이클차이므로 아직 미반영"
    assert state3["candidate_streak"] == 1


def test_deescalation_streak_resets_on_non_matching_candidate():
    """완화 후보 등급 자체가 사이클마다 바뀌면(Medium→Low) 스트릭이 새로 시작된다."""
    _, state = _apply("High", "RTL", None)
    _, state1 = _apply("Medium", "MAINTAIN", state)  # candidate=Medium, streak=1
    assert state1["candidate_streak"] == 1

    action2, state2 = _apply("Low", "MAINTAIN", state1)  # candidate 등급이 바뀜(Medium→Low)
    assert action2 == "RTL", "committed 미달, candidate 변경으로 streak 재시작"
    assert state2["candidate_streak"] == 1
    assert state2["candidate_rac_order"] == RAC_ORDER["Low"]


def test_no_change_keeps_committed_and_resets_candidate():
    """RAC_ORDER 변화 없음(threat_event/stage도 동일) → committed 유지, candidate 상태 리셋."""
    _, state = _apply("Medium", "ALTITUDE_CHANGE", None)
    action, new_state = _apply("Medium", "ALTITUDE_CHANGE", state)
    assert action == "ALTITUDE_CHANGE"
    assert new_state["committed_flight_action"] == "ALTITUDE_CHANGE"
    assert new_state["candidate_streak"] == 0
    assert new_state["candidate_rac_order"] is None


def test_full_deescalation_cycle_end_to_end():
    """High(RTL) 진입 → Low(MAINTAIN)까지 완화 → 3사이클 연속 후 반영, 그 전엔 RTL 고정."""
    action0, state = _apply("High", "RTL", None)
    assert action0 == "RTL"

    actions = []
    for _ in range(FLIGHT_ACTION_DEESCALATE_DEBOUNCE_CYCLES):
        action, state = _apply("Low", "MAINTAIN", state)
        actions.append(action)

    assert actions[:-1] == ["RTL"] * (FLIGHT_ACTION_DEESCALATE_DEBOUNCE_CYCLES - 1)
    assert actions[-1] == "MAINTAIN"


# ---------------------------------------------------------------------------
# 신규(grill-me 라운드3) — kill_chain_stage 진행 / threat_event 변경 시 즉시 반영
# ---------------------------------------------------------------------------


def test_kill_chain_stage_progression_at_same_rac_escalates_immediately():
    """RAC=High 유지 + kill_chain_stage 초기→후기 진행 → 디바운스 없이 즉시 반영.

    flight_comms.resolve(): High+초기=POSTURE_ELEVATE, High+후기+PHYSICAL=RTL.
    RAC_ORDER는 둘 다 1(변화 없음)이지만 진짜 위협 임박이므로 즉시 반영돼야 한다.
    """
    _, state = apply_debounce("High", "POSTURE_ELEVATE", "T3", "초기", None)
    action, new_state = apply_debounce("High", "RTL", "T3", "후기", state)
    assert action == "RTL", "kill_chain_stage 진행은 RAC_ORDER 불변이어도 즉시 반영돼야 함"
    assert new_state["committed_flight_action"] == "RTL"
    assert new_state["candidate_streak"] == 0


def test_kill_chain_stage_progression_to_mid_also_escalates():
    """초기→중기 진행도 즉시 반영(중기도 초기보다 임박)."""
    _, state = apply_debounce("High", "POSTURE_ELEVATE", "T1", "초기", None)
    action, new_state = apply_debounce("High", "REROUTE", "T1", "중기", state)
    assert action == "REROUTE"
    assert new_state["committed_flight_action"] == "REROUTE"


def test_kill_chain_stage_regression_does_not_escalate():
    """후기→초기 역행(비정상적이지만 방어)은 악화로 취급하지 않음 — RAC_ORDER 불변이면 변화 없음 처리."""
    _, state = apply_debounce("High", "RTL", "T3", "후기", None)
    action, new_state = apply_debounce("High", "POSTURE_ELEVATE", "T3", "초기", state)
    assert action == "RTL", "stage 역행은 즉시반영 트리거가 아님 — committed(RTL) 유지"
    assert new_state["committed_flight_action"] == "RTL"


def test_primary_threat_event_change_resets_state_immediately():
    """primary_threat_event 자체가 바뀌면(T3→T1) 완전히 다른 상황이므로 즉시(첫 사이클처럼) 반영.

    디바운스 완화 홀드 중이라도(RTL 유지 중) 새 위협 식별자가 나타나면 그 위협의
    현재 판단을 그대로 신뢰한다 — 이전 위협에 대한 디바운스 메모리는 의미가 없음.
    """
    _, state = apply_debounce("High", "RTL", "T3", "후기", None)
    _, state1 = apply_debounce("Medium", "MAINTAIN", "T3", "후기", state)  # 완화 1사이클차, 아직 보류 중
    assert state1["candidate_streak"] == 1

    action2, state2 = apply_debounce("Medium", "MAINTAIN", "T1", "초기", state1)  # 위협 식별자 변경
    assert action2 == "MAINTAIN", "새 threat_event 등장 → 디바운스 없이 현재 판단 즉시 반영"
    assert state2["committed_flight_action"] == "MAINTAIN"
    assert state2["committed_primary_threat_event"] == "T1"
    assert state2["candidate_streak"] == 0


def test_primary_threat_event_change_to_worse_also_immediate():
    """threat_event 변경이 악화 방향이어도(원래도 즉시 반영 대상) 정상 동작."""
    _, state = apply_debounce("Medium", "MAINTAIN", "T1", "초기", None)
    action, new_state = apply_debounce("High", "RTL", "T3", "후기", state)
    assert action == "RTL"
    assert new_state["committed_primary_threat_event"] == "T3"


def test_no_primary_threat_event_none_to_none_is_not_a_change():
    """primary_threat_event=None(무위협)이 계속 유지되는 경우는 '변경'이 아니다 — 정상 디바운스 동작."""
    _, state = apply_debounce("High", "RTL", None, "후기", None)
    action1, state1 = apply_debounce("Medium", "MAINTAIN", None, None, state)
    assert action1 == "RTL", "threat_event 그대로 None → 완화는 정상적으로 디바운스 대상"
    assert state1["candidate_streak"] == 1
