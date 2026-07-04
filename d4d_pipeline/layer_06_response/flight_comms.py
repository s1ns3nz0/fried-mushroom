"""06. Response — (RAC, kill_chain_stage, threat_category) → flight/comms 조회 테이블."""

# RAC=High, kill_chain_stage=후기/중기
_HIGH_LATE: dict[str, tuple[str, str]] = {
    "PHYSICAL":   ("RTL",                     "L3"),
    "REMOTE":     ("REROUTE",                 "L2"),
    "NAVIGATION": ("ALTITUDE_CHANGE_REROUTE", "L2"),
}

# RAC=High, kill_chain_stage=초기
_HIGH_EARLY: dict[str, tuple[str, str]] = {
    "PHYSICAL":   ("POSTURE_ELEVATE", "L1"),
    "REMOTE":     ("POSTURE_ELEVATE", "L1"),
    "NAVIGATION": ("POSTURE_ELEVATE", "L1"),
}

# RAC = Serious/Medium/Low — threat_category·kill_chain_stage 무관
_LOWER_RAC: dict[str, tuple[str, str, str | None]] = {
    "Serious": ("ALTITUDE_CHANGE", "L1", "GCS_CONSULT"),
    "Medium":  ("MAINTAIN",        "L1", "INCREASE_ASSESSMENT_FREQUENCY"),
    "Low":     ("MAINTAIN",        "L0", None),
}


def resolve(
    rac: str,
    kill_chain_stage: str | None,
    threat_category: str | None,
) -> tuple[str, str, str | None]:
    """(RAC, kill_chain_stage, threat_category) → (flight_action, comms_level, special_action)."""
    if rac == "High":
        if kill_chain_stage == "초기":
            flight, comms = _HIGH_EARLY.get(
                threat_category or "", ("POSTURE_ELEVATE", "L1")
            )
            return flight, comms, "INCREASE_ASSESSMENT_FREQUENCY"
        else:
            flight, comms = _HIGH_LATE.get(
                threat_category or "", ("ALTITUDE_CHANGE_REROUTE", "L2")
            )
            return flight, comms, None

    flight, comms, special = _LOWER_RAC[rac]
    return flight, comms, special
