"""failsafe_arbiter — 🔵 파생 읽기전용. 온보드 안전 4축 failsafe 통합 중재 advisory.

온보드 안전 권고는 네 축에서 독립적으로 나온다:
  - energy: `endurance.assess_endurance` (bingo-fuel RTL)
  - comms:  `link_loss.assess_link_loss` (통신두절 failsafe)
  - nav:    `nav_integrity.assess_nav_integrity` (GNSS 무결성 failsafe)
  - ew:     `ew_jamming.assess_ew_jamming` (EW 광대역 재밍 → EMCON·회피)

각 축은 서로 다른 위급을 보지만 운용자·06 Response 는 **하나의 실행 권고**가 필요하다. 이 모듈은
네 축의 권고를 **most-conservative-wins**(가장 급한 축이 지배)로 융합해 단일 failsafe 를 낸다.
통합 심각도:

  CONTINUE(0) < MONITOR(1) < HOLD/DR_HOLD(2) < RTL/EMCON_EVADE(3) < LAND(4)

EMCON_EVADE(재밍 회피 기동)는 능동 보호기동이라 RTL 과 동급(3). 동률 최상위가 여러 축이면 축
우선순위(nav > comms > ew > energy — 자기 위치 상실이 가장 근본적, 능동 공격 대응인 ew 는
comms 다음, 시간여유 있는 energy 는 최후)로 실행 action 을 정하고 기여 축을 모두 보고한다.

CRITICAL (SCC-1): advisory 만 산출한다. 각 축 advisory 의 **출력 report dict**(recommended_action)
만 데이터 계약으로 소비하며 endurance/link_loss/nav_integrity/ew_jamming 모듈을 import 하지
않는다(레이어 격리, 배선은 상위 오케스트레이터/#360 소관). 어떤 결정론 판정도 대체하지 않고
입력을 변이하지 않으며 상수를 쓰거나 바꾸지 않는다.
"""

from __future__ import annotations

from typing import Any

# 통합 심각도 순위 — 축을 가로질러 "가장 급한" action 을 고르는 유일 척도.
_SEVERITY = {
    "CONTINUE": 0,
    "UNKNOWN": 0,
    "MONITOR": 1,
    "HOLD": 2,          # comms 선회대기
    "DR_HOLD": 2,       # nav 추측항법 선회
    "RTL": 3,
    "EMCON_EVADE": 3,   # ew 재밍 회피 기동 — 능동 보호기동이라 RTL 동급
    "LAND": 4,
}
# 동률 최상위 tie-break — 항법상실이 가장 근본적(자기 위치 상실) → nav, 이어 comms,
# 능동 공격 대응 ew, 시간여유 있는 energy 순.
_AXIS_PRECEDENCE = ("nav", "comms", "ew", "energy")


def _action_of(report: Any) -> str | None:
    """축 report → recommended_action. assessable=False/None/미보고 → None(기여 제외)."""
    if not isinstance(report, dict):
        return None
    if report.get("assessable") is False:
        return None
    action = report.get("recommended_action")
    if not isinstance(action, str) or action == "UNKNOWN":
        return None
    return action


def assess_failsafe(axis_reports: dict[str, Any] | None) -> dict[str, Any]:
    """축→advisory report 매핑 → 통합 단일 failsafe 권고. advisory.

    axis_reports 예: {"energy": <endurance report>, "comms": <link_loss report>,
                      "nav": <nav_integrity report>, "ew": <ew_jamming report>}.
    미보고/None/assessable=False 축은 제외.
    반환: {assessable, recommended_action(CONTINUE|MONITOR|HOLD|DR_HOLD|RTL|EMCON_EVADE|
           LAND|UNKNOWN), severity, driving_axes, contributions, advisory_only, note}.
    """
    reports = axis_reports or {}
    # 기여 가능한 축을 인식(_SEVERITY 등재)/미인식으로 분리한다. 미인식 action 을 severity 0
    # 으로 뭉개면 안전권고가 조용히 CONTINUE 로 하향됨(codex P2) — 별도 추적해 명시 처리.
    contrib: dict[str, str] = {}
    unknown_actions: dict[str, str] = {}
    for axis, rep in reports.items():
        action = _action_of(rep)
        if action is None:
            continue
        (contrib if action in _SEVERITY else unknown_actions)[axis] = action

    if not contrib and not unknown_actions:
        return {
            "assessable": False, "recommended_action": "UNKNOWN", "severity": 0,
            "driving_axes": [], "contributions": {}, "advisory_only": True,
            "note": "판정 가능한 안전 축 없음 — 통합 failsafe 불가.",
        }

    max_sev = max((_SEVERITY[a] for a in contrib.values()), default=0)

    # 미인식 action + 인식된 에스컬레이션 없음 → 심각도 불가지. CONTINUE 하향은 위험하므로
    # 불가지(UNKNOWN)로 보고한다(미인식 action 이 더 급할 수 있음). 인식된 에스컬레이션이
    # 있으면(max_sev>0) 그 값이 지배하고 미인식 action 은 병기만 한다(하향 없음).
    if unknown_actions and max_sev == 0:
        return {
            "assessable": False, "recommended_action": "UNKNOWN", "severity": 0,
            "driving_axes": [], "contributions": {**contrib, **unknown_actions},
            "advisory_only": True,
            "note": f"미인식 failsafe action {unknown_actions} — 심각도 판정 불가, 안전상 CONTINUE 하향 금지.",
        }

    if max_sev == 0:
        return {
            "assessable": True, "recommended_action": "CONTINUE", "severity": 0,
            "driving_axes": [], "contributions": contrib, "advisory_only": True,
            "note": "전 축 정상 — 임무 지속 가능.",
        }

    # 최상위 심각도 축들 → 축 우선순위로 실행 action 결정(인식된 축만 지배 후보).
    top_axes = [ax for ax, a in contrib.items() if _SEVERITY[a] == max_sev]
    top_axes.sort(key=lambda ax: _AXIS_PRECEDENCE.index(ax) if ax in _AXIS_PRECEDENCE else len(_AXIS_PRECEDENCE))
    action = contrib[top_axes[0]]
    n_axes = len(contrib) + len(unknown_actions)  # 실제 기여 축 수(3축 하드코딩 금지, codex P3)
    note = f"안전 {n_axes}축 융합 → {action} (지배 축: {', '.join(top_axes)}, 심각도 {max_sev})."
    if unknown_actions:
        note += f" · 미인식 action 병기: {unknown_actions}"
    return {
        "assessable": True, "recommended_action": action, "severity": max_sev,
        "driving_axes": top_axes, "contributions": {**contrib, **unknown_actions},
        "advisory_only": True, "note": note,
    }
