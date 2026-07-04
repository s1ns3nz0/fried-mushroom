"""06. Response — threat_event별 payload_action / nav_mode overlay."""

_LATE_STAGES = {"후기", "중기"}


def payload_actions(
    threat_event: str,
    kill_chain_stage: str,
    rac: str,
    threat_category: str,
    drone_profile: dict,
) -> list[str]:
    """RAC=High + 후기/중기 조합에서만 payload_action 발동. 그 외 []."""
    if not (rac == "High" and kill_chain_stage in _LATE_STAGES):
        return []

    if threat_category == "PHYSICAL":
        actions: list[str] = ["DATA_WIPE"]
        if threat_event == "T3":
            armament: list[dict] = drone_profile.get("armament", [])
            if any(item.get("expendable") is True for item in armament):
                actions.append("WEAPON_DROP")
        return actions

    return []


def nav_mode(threat_event: str, rac: str, kill_chain_stage: str) -> str | None:
    """RAC=High + 후기/중기 + T1 → INS_ONLY. 그 외 None."""
    if rac == "High" and kill_chain_stage in _LATE_STAGES and threat_event == "T1":
        return "INS_ONLY"
    return None
