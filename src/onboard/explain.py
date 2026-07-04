"""explain — 🔵 파생 읽기전용. 온보드 사이클 결정의 구조화 근거(설명).

`run_cycle` 결과(03→07 출력)를 조립해 "무엇을 관측→무엇으로 추론→왜 이 결정→어떤 행동"을
사람이 읽을 수 있는 단계별 근거로 만든다. 방위·좌표를 새로 계산하지 않고 이미 산출된 값과
provenance(confidence_source / kill_chain_stage / RAC / reroute_anchor 등)를 설명으로 엮는다.

용도: 운용자 신뢰·감사(auditability), 대시보드 "AI 결정 설명"의 실데이터 소스, 사후 debrief.

CRITICAL: 파생 읽기전용. 결정을 절대 바꾸지 않고 입력 결과 dict 를 변이하지 않는다. 결정론
로직·상수를 읽거나 쓰지 않으며 shared.THREAT_CATALOG(설명 조회, 읽기전용)만 참조한다.
"""

from __future__ import annotations

from typing import Any

from onboard.shared.constants import THREAT_CATALOG


def _abstraction_step(abstraction: dict[str, Any]) -> dict[str, Any]:
    channels = abstraction.get("channels") or []
    abnormal = [c.get("channel") for c in channels if c.get("state") not in (None, "normal")]
    if abnormal:
        obs = f"{len(channels)}개 채널 중 비정상 {len(abnormal)}개: {', '.join(str(a) for a in abnormal)}"
    else:
        obs = f"{len(channels)}개 채널 전부 normal — 이상 신호 없음"
    return {
        "layer": "03", "title": "센서 추상화",
        "observation": obs,
        "conclusion": obs,
        "detail": {"channel_count": len(channels), "abnormal_channels": abnormal},
    }


def _threat_step(threat: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    primary = threat.get("primary")
    candidates = threat.get("candidates") or []
    if not primary:
        return ({
            "layer": "04", "title": "위협 판정",
            "observation": f"위협 후보 {len(candidates)}건",
            "conclusion": "위협 없음 — 지배 위협 미검출",
            "detail": {"candidate_count": len(candidates)},
        }, None)
    te = primary.get("threat_event")
    desc = THREAT_CATALOG.get(te, te)
    conf = primary.get("confidence")
    conf_txt = f"확신도 {conf:.3f}" if isinstance(conf, (int, float)) else "확신도 미상"
    return ({
        "layer": "04", "title": "위협 판정",
        "observation": f"후보 {len(candidates)}건 중 지배 위협 선정",
        "conclusion": f"{te} ({desc}) {conf_txt}",
        "detail": {
            "threat_event": te, "threat_desc": desc, "confidence": conf,
            "confidence_source": primary.get("confidence_source"),
            "kill_chain_stage": primary.get("kill_chain_stage"),
            "potential_outcome": primary.get("potential_outcome"),
            "match_count": primary.get("match_count"),
        },
    }, te)


def _risk_step(risk: dict[str, Any]) -> dict[str, Any]:
    candidates = risk.get("candidates") or []
    if candidates:
        top = min(candidates, key=lambda c: c.get("priority_rank", 0))
        rac = top.get("rac")
        detail = {
            "rac": rac,
            "l_class_final": top.get("l_class_final"),
            "severity_label_final": top.get("severity_label_final"),
            "compound_urgency_score": top.get("compound_urgency_score"),
            "source": "primary_candidate",
        }
        concl = f"RAC={rac} (L={top.get('l_class_final')}, S={top.get('severity_label_final')})"
    else:
        rac = risk.get("ambient_rac")
        detail = {"rac": rac, "source": "ambient_rac"}
        concl = f"RAC={rac} (후보 없음 → 환경 RAC)"
    return {
        "layer": "05", "title": "위험 평가",
        "observation": f"위험 후보 {len(candidates)}건",
        "conclusion": concl, "detail": detail,
    }


def _response_step(response: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    fa = response.get("flight_action")
    secondary = response.get("secondary_threats") or []
    return ({
        "layer": "06", "title": "대응 결정",
        "observation": f"RAC={response.get('rac')}, 킬체인={response.get('kill_chain_stage')}, "
                       f"위협군={response.get('threat_category')}",
        "conclusion": f"비행행동={fa}",
        "detail": {
            "flight_action": fa,
            "comms_level": response.get("comms_level"),
            "nav_mode": response.get("nav_mode"),
            "payload_action": response.get("payload_action"),
            "special_action": response.get("special_action"),
            "threat_category": response.get("threat_category"),
            "rac": response.get("rac"),
            "secondary_threat_count": len(secondary),
        },
    }, fa)


def _plan_step(plan: dict[str, Any]) -> dict[str, Any]:
    fa = plan.get("flight_action")
    scope = plan.get("replan_scope")
    bearing = plan.get("target_bearing_deg")
    speed = plan.get("speed_mode")
    route = plan.get("route") or []
    parts = [f"replan={scope}"]
    if bearing is not None:
        parts.append(f"방위={bearing}°")
    if plan.get("altitude_delta_m"):
        parts.append(f"고도Δ={plan.get('altitude_delta_m')}m")
    parts.append(f"속도={speed}")
    return {
        "layer": "07", "title": "비행 계획",
        "observation": f"비행행동={fa}",
        "conclusion": ", ".join(parts),
        "detail": {
            "flight_action": fa, "replan_scope": scope,
            "reroute_anchor": plan.get("reroute_anchor"),
            "target_bearing_deg": bearing,
            "altitude_delta_m": plan.get("altitude_delta_m"),
            "speed_mode": speed, "route_waypoints": len(route),
        },
    }


def explain_cycle(result: dict[str, Any]) -> dict[str, Any]:
    """run_cycle 결과 → 구조화 의사결정 근거. 파생 읽기전용(결정·입력 무변경).

    반환: {flight_action, primary_threat_event, summary, steps[03..07], derived_readonly}.
    부분/빈 결과에도 예외 없이 best-effort 로 동작한다.
    """
    result = result or {}
    abstraction = result.get("abstraction") or {}
    threat = result.get("threat") or {}
    risk = result.get("risk") or {}
    response = result.get("response") or {}
    plan = result.get("flight_plan") or {}

    s03 = _abstraction_step(abstraction)
    s04, primary_te = _threat_step(threat)
    s05 = _risk_step(risk)
    s06, flight_action = _response_step(response)
    s07 = _plan_step(plan)

    # 07 이 flight_action 을 담으면 그것을 정본으로(디바운스로 06 과 다를 수 있음).
    flight_action = plan.get("flight_action") or flight_action

    if primary_te:
        desc = THREAT_CATALOG.get(primary_te, primary_te)
        rac = s05["detail"].get("rac")
        summary = f"{flight_action} — {primary_te}({desc}) 위협, RAC={rac}"
    else:
        summary = f"{flight_action} — 위협 없음"

    return {
        "flight_action": flight_action,
        "primary_threat_event": primary_te,
        "summary": summary,
        "steps": [s03, s04, s05, s06, s07],
        "derived_readonly": True,
    }


def format_explanation(explanation: dict[str, Any]) -> str:
    """explain_cycle 결과 → 사람이 읽는 다중행 텍스트(로그·CLI·debrief 표시용)."""
    lines = [f"결정: {explanation.get('summary', '')}"]
    for s in explanation.get("steps", []):
        lines.append(f"  [{s.get('layer')}] {s.get('title')}: {s.get('conclusion')}")
        prov = s.get("detail", {}).get("confidence_source")
        if prov:
            lines.append(f"        provenance: confidence_source={prov}, "
                         f"kill_chain_stage={s['detail'].get('kill_chain_stage')}")
    return "\n".join(lines)
