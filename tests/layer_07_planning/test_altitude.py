import pytest
from onboard.layer_07_planning.altitude import compute_altitude_delta


def test_altitude_change():
    assert compute_altitude_delta("ALTITUDE_CHANGE") == (15, "altitude_only")


def test_posture_elevate():
    assert compute_altitude_delta("POSTURE_ELEVATE") == (25, "altitude_only")


def test_altitude_change_reroute():
    assert compute_altitude_delta("ALTITUDE_CHANGE_REROUTE") == (50, None)


def test_rtl():
    assert compute_altitude_delta("RTL") == (0, None)


def test_reroute():
    assert compute_altitude_delta("REROUTE") == (0, None)


def test_maintain():
    assert compute_altitude_delta("MAINTAIN") == (0, None)


def test_unknown_raises():
    with pytest.raises(KeyError):
        compute_altitude_delta("INVALID_ACTION")
