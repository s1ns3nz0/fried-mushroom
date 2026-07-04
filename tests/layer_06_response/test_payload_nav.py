from onboard.layer_06_response.payload_nav import nav_mode, payload_actions


def test_t3_high_late_with_expendable():
    profile = {"armament": [{"id": "grenade", "expendable": True}]}
    assert payload_actions("T3", "후기", "High", "PHYSICAL", profile) == ["DATA_WIPE", "WEAPON_DROP"]


def test_t3_high_late_without_expendable():
    assert payload_actions("T3", "후기", "High", "PHYSICAL", {"armament": []}) == ["DATA_WIPE"]


def test_t4_high_late_no_weapon_drop():
    assert payload_actions("T4", "후기", "High", "PHYSICAL", {"armament": []}) == ["DATA_WIPE"]


def test_t3_serious_late_no_payload():
    assert payload_actions("T3", "후기", "Serious", "PHYSICAL", {"armament": []}) == []


def test_t1_high_late_no_payload():
    assert payload_actions("T1", "후기", "High", "REMOTE", {"armament": []}) == []


def test_t7_high_late_no_payload():
    assert payload_actions("T7", "후기", "High", "NAVIGATION", {"armament": []}) == []


def test_t1_high_late_ins_only():
    assert nav_mode("T1", "High", "후기") == "INS_ONLY"


def test_t1_high_mid_ins_only():
    assert nav_mode("T1", "High", "중기") == "INS_ONLY"


def test_t7_high_late_no_nav():
    assert nav_mode("T7", "High", "후기") is None


def test_t1_serious_no_nav():
    assert nav_mode("T1", "Serious", "후기") is None


def test_t1_high_early_no_nav():
    assert nav_mode("T1", "High", "초기") is None


def test_t2_high_late_no_nav_mode():
    assert nav_mode("T2", "High", "후기") is None


def test_t2_high_mid_no_nav_mode():
    assert nav_mode("T2", "High", "중기") is None
