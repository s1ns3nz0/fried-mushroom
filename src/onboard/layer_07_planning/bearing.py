"""07. Flight Planning — threat_category별 target bearing 결정."""


def compute_bearing(
    threat_category: str | None,
    threat_bearing_deg: float | None,
    cycle_context: dict,
) -> tuple[float | None, str | None]:
    """(threat_category, threat_bearing_deg, cycle_context) → (target_bearing_deg, reroute_anchor).

    PHYSICAL / REMOTE:
      bearing 있으면 반대 방향(+180 %) → anchor="threat_reverse(channel)"
      PHYSICAL 없으면 lowest_exposure_bearing_deg → anchor="terrain_fallback"
      REMOTE 없으면 (None, "last_known_good_position")
    NAVIGATION:
      optimal_terrain_bearing_deg → anchor="optimal_terrain"
    None:
      (None, None)
    """
    if threat_category is None:
        return None, None

    if threat_category in ("PHYSICAL", "REMOTE"):
        if threat_bearing_deg is not None:
            return (threat_bearing_deg + 180) % 360, "threat_reverse(channel)"
        if threat_category == "PHYSICAL":
            return cycle_context.get("lowest_exposure_bearing_deg"), "terrain_fallback"
        return None, "last_known_good_position"

    if threat_category == "NAVIGATION":
        return cycle_context.get("optimal_terrain_bearing_deg"), "optimal_terrain"

    return None, None
