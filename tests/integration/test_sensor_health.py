"""sensor_health — 03 전 채널 센서 건전성 종합 advisory 검증.

단일 사이클 다채널 집계. AbstractionOutput channels 계약(quality/state)만 소비.
"""

from onboard.sensor_health import assess_sensor_health


def _ch(name, quality, state="normal"):
    return {"channel": name, "state": state, "quality": quality, "quality_delta": 0.0, "payload": {}}


def _abs(*chans):
    return {"schema_version": "1.0", "id": "x-1", "ts": 0, "channels": list(chans)}


def test_empty_unknown():
    r = assess_sensor_health(_abs())
    assert r["assessable"] is False
    assert r["health"] == "UNKNOWN"
    assert r["confidence_discount"] == 1.0


def test_all_healthy_nominal():
    r = assess_sensor_health(_abs(_ch("a", 0.95), _ch("b", 0.8), _ch("c", 0.7)))
    assert r["health"] == "NOMINAL"
    assert r["impaired"] == []
    assert r["confidence_discount"] == 1.0
    assert r["channel_count"] == 3


def test_low_quality_degraded():
    r = assess_sensor_health(_abs(_ch("a", 0.9), _ch("b", 0.5)))  # 0.5 < 0.6 → degraded
    assert r["health"] == "DEGRADED"
    assert r["confidence_discount"] == 0.85
    assert [i["channel"] for i in r["impaired"]] == ["b"]
    assert r["impaired"][0]["tier"] == "degraded"


def test_high_quality_anomaly_is_healthy():
    # state=anomaly 는 위협 탐지 신호(총성/스푸핑 감지) — 센서 고장 아님.
    # 고품질 anomaly → 센서 정상, 건전성에 영향 없음.
    r = assess_sensor_health(_abs(_ch("a", 0.95), _ch("b", 0.9, state="anomaly")))
    assert r["health"] == "NOMINAL"
    assert r["impaired"] == []
    assert r["confidence_discount"] == 1.0


def test_low_quality_anomaly_flagged_by_quality():
    # 같은 anomaly 라도 quality 낮으면 열화 — state 아닌 quality 가 판정.
    r = assess_sensor_health(_abs(_ch("a", 0.2, state="anomaly")))
    assert r["health"] == "CRITICAL"
    assert r["impaired"][0]["state"] == "anomaly"  # state 는 참고 보고


def test_very_low_quality_critical():
    r = assess_sensor_health(_abs(_ch("a", 0.2)))  # 0.2 < 0.3 → critical
    assert r["health"] == "CRITICAL"


def test_impaired_sorted_worst_first():
    r = assess_sensor_health(_abs(_ch("a", 0.55), _ch("b", 0.1), _ch("c", 0.25)))
    # critical(b 0.1, c 0.25) 먼저 quality 오름차순, degraded(a 0.55) 마지막.
    assert [i["channel"] for i in r["impaired"]] == ["b", "c", "a"]
    assert r["impaired"][0]["tier"] == "critical"
    assert r["impaired"][-1]["tier"] == "degraded"


def test_min_and_mean_quality():
    r = assess_sensor_health(_abs(_ch("a", 1.0), _ch("b", 0.5)))
    assert r["min_quality"] == 0.5
    assert r["mean_quality"] == 0.75


def test_accepts_channels_list():
    r = assess_sensor_health([_ch("a", 0.9), _ch("b", 0.9)])
    assert r["assessable"] is True and r["health"] == "NOMINAL"


def test_non_numeric_quality_skipped():
    r = assess_sensor_health(_abs(_ch("a", 0.9), {"channel": "b", "state": "normal", "quality": None}))
    assert r["channel_count"] == 1  # None quality 제외


def test_input_not_mutated():
    a = _abs(_ch("x", 0.5))
    before = [dict(c) for c in a["channels"]]
    assess_sensor_health(a)
    assert a["channels"] == before
    assert a["channels"][0].get("tier") is None  # 원본에 tier 오염 없음
