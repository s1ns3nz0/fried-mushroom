"""03 채널 quality 경계 불변식: 어떤 raw 입력에도 quality ∈ [0,1].

각 채널의 quality 프록시 공식(예: position_consistency = 1 - hdop*0.1 - ...,
link_status = 1 - loss*2 - ...)은 극단 입력(재밍 GPS, 죽은 링크)에서 음수를
낼 수 있으나 _common.make_output 의 clamp01 이 [0,1] 로 보정한다. 이 테스트는
그 계약을 고정한다 — 미래에 clamp 를 빠뜨린 공식이 들어오면 실패한다.
"""

import copy

import pytest

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction import run as l3


def _deep_merge(base: dict, overrides: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _envelope(overrides: dict) -> dict:
    return _deep_merge(build_normal_envelope("Q", 37.5, 127.1), overrides)


# (id, raw 극단 override) — 결정론 채널 quality 공식을 음수 영역으로 밀어넣는 값.
_EXTREME = [
    ("jammed_gps", {"navigation": {"gps": {"hdop": 50.0, "vdop": 40.0}}, "ew": {"satellite_count": 0, "cn0_avg_db": 5.0}}),
    ("dead_link", {"c2_link": {"packet_loss_rate": 0.99, "rssi_dbm": -100, "noise_floor_dbm": -90, "checksum_fail_rate": 0.9, "seq_gap_count": 50}}),
    ("all_degraded", {
        "navigation": {"gps": {"hdop": 30.0}},
        "ew": {"satellite_count": 1},
        "c2_link": {"packet_loss_rate": 0.8, "rssi_dbm": -110, "noise_floor_dbm": -92},
    }),
    ("pristine", {}),  # 정상 입력도 확인.
]


@pytest.mark.parametrize("cid,overrides", _EXTREME, ids=[c[0] for c in _EXTREME])
def test_all_channel_qualities_in_unit_interval(cid, overrides) -> None:
    out = l3.run(_envelope(overrides))
    for ch in out["channels"]:
        q = ch["quality"]
        assert isinstance(q, (int, float)), f"{ch['channel']} quality 비수치: {q!r}"
        assert 0.0 <= q <= 1.0, f"{ch['channel']} quality 범위 밖: {q} ({cid})"
        # quality_delta = q - prev (prev None → 0.0). prev 없음 경로는 항상 0.0.
        assert ch["quality_delta"] == 0.0


def test_quality_delta_bounded_with_previous() -> None:
    # previous_quality 제공 시 delta = q - prev ∈ [-1, 1] (둘 다 [0,1]).
    env = _envelope({"navigation": {"gps": {"hdop": 50.0}}, "ew": {"satellite_count": 0}})
    prev = {name: 1.0 for name in (
        "position_consistency", "link_status", "link_integrity", "encryption_status",
        "rf_spectrum", "mission_phase", "obstacle_proximity", "operational_margin",
        "proximity_object", "terrain_class", "acoustic_event",
    )}
    out = l3.run(env, prev)
    for ch in out["channels"]:
        assert -1.0 <= ch["quality_delta"] <= 1.0, f"{ch['channel']} delta 범위 밖: {ch['quality_delta']}"
