from d4d_pipeline.layer_06_response.flight_comms import resolve


def test_high_late_physical():
    assert resolve("High", "후기", "PHYSICAL") == ("RTL", "L3", None)


def test_high_mid_physical():
    assert resolve("High", "중기", "PHYSICAL") == ("RTL", "L3", None)


def test_high_early_physical():
    assert resolve("High", "초기", "PHYSICAL") == (
        "POSTURE_ELEVATE", "L1", "INCREASE_ASSESSMENT_FREQUENCY"
    )


def test_high_late_remote():
    assert resolve("High", "후기", "REMOTE") == ("REROUTE", "L2", None)


def test_high_late_navigation():
    assert resolve("High", "후기", "NAVIGATION") == ("ALTITUDE_CHANGE_REROUTE", "L2", None)


def test_serious():
    assert resolve("Serious", None, None) == ("ALTITUDE_CHANGE", "L1", "GCS_CONSULT")


def test_medium():
    assert resolve("Medium", None, None) == (
        "MAINTAIN", "L1", "INCREASE_ASSESSMENT_FREQUENCY"
    )


def test_low():
    assert resolve("Low", None, None) == ("MAINTAIN", "L0", None)
