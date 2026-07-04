"""06. Response — RiskAssessmentOutput → ResponseOutput."""

from ..layer_05_risk.likelihood import THREAT_CATEGORY
from ..schemas import MissionBrief, ResponseOutput, RiskAssessmentOutput
from . import flight_comms, payload_nav


def run(risk: RiskAssessmentOutput, mission_brief: MissionBrief) -> ResponseOutput:
    candidates = risk["candidates"]

    if not candidates:
        rac = risk.get("ambient_rac") or "Low"
        flight, comms, special = flight_comms.resolve(rac, None, None)
        return ResponseOutput(
            primary_threat_event=None,
            rac=rac,
            kill_chain_stage=None,
            threat_category=None,
            flight_action=flight,
            comms_level=comms,
            payload_action=[],
            nav_mode=None,
            special_action=special,
            secondary_threats=[],
            ai_reliability="normal",
        )

    primary = candidates[0]
    tc = THREAT_CATEGORY[primary["threat_event"]]
    flight, comms, special = flight_comms.resolve(
        primary["rac"], primary["kill_chain_stage"], tc
    )
    p_actions = payload_nav.payload_actions(
        primary["threat_event"],
        primary["kill_chain_stage"],
        primary["rac"],
        tc,
        mission_brief["drone_profile"],
    )
    nav = payload_nav.nav_mode(
        primary["threat_event"], primary["rac"], primary["kill_chain_stage"]
    )

    return ResponseOutput(
        primary_threat_event=primary["threat_event"],
        rac=primary["rac"],
        kill_chain_stage=primary["kill_chain_stage"],
        threat_category=tc,
        flight_action=flight,
        comms_level=comms,
        payload_action=p_actions,
        nav_mode=nav,
        special_action=special,
        secondary_threats=[
            {
                "threat_event": c["threat_event"],
                "rac": c["rac"],
                "compound_urgency_score": c["compound_urgency_score"],
                "priority_rank": c["priority_rank"],
            }
            for c in candidates[1:]
        ],
        ai_reliability=primary["compound_risk_assessment"]["ai_reliability"],
    )
