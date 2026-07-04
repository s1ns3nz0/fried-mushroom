"""step3 — AbstractionOutput / ChannelOutput 스키마 형태 테스트."""

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction.run import run

_TOP_KEYS = {"schema_version", "id", "ts", "channels"}
_CHANNEL_KEYS = {"channel", "state", "quality", "quality_delta", "payload"}


def test_top_level_keys_exact():
    out = run(build_normal_envelope("GIREOGI-0704", 7, 1730620801200))
    assert set(out.keys()) == _TOP_KEYS


def test_each_channel_keys_exact():
    out = run(build_normal_envelope("s", 0, 0))
    for ch in out["channels"]:
        assert set(ch.keys()) == _CHANNEL_KEYS


def test_id_format():
    out = run(build_normal_envelope("GIREOGI-0704", 7, 0))
    assert out["id"] == "GIREOGI-0704-7"


def test_ts_passthrough():
    out = run(build_normal_envelope("s", 0, 1730620801200))
    assert out["ts"] == 1730620801200
