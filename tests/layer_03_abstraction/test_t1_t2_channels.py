"""T1(GPS 스푸핑)/T2(사이버) 시나리오 → 03 채널 이상 산출 검증.

02 mock_source 가 심은 신호를 03 결정론 채널이 anomaly 로 잡는지 확인한다.
(04 탐지까지의 종단은 T1 만 test_e2e_semantics 에서 검증 — T2 는 04 Q_MIN
게이트 이슈로 종단 미탐지, 별도 이슈 참조.)
"""

from onboard.layer_02_sensor.mock_source import build_scenario_envelope
from onboard.layer_03_abstraction import run as layer_03


def _channels(scenario: str) -> dict:
    out = layer_03.run(build_scenario_envelope(scenario, 0, 0))
    return {c["channel"]: c for c in out["channels"]}


def test_t1_position_and_rf_anomaly() -> None:
    ch = _channels("t1")
    # GPS 스푸핑: 위치 잔차 > 5m + RF 광대역 이상
    assert ch["position_consistency"]["state"] == "anomaly"
    assert ch["position_consistency"]["payload"]["gps_imu_residual_m"] > 5.0
    assert ch["rf_spectrum"]["state"] == "anomaly"


def test_t2_encryption_and_link_anomaly() -> None:
    ch = _channels("t2")
    # 사이버: 암호 다운그레이드 + 링크 무결성 손상
    assert ch["encryption_status"]["state"] == "anomaly"
    assert ch["encryption_status"]["payload"]["downgrade_detected"] is True
    assert ch["link_integrity"]["state"] == "anomaly"
    assert (
        ch["link_integrity"]["payload"]["checksum_fail_rate"] > 0.05
        or ch["link_integrity"]["payload"]["seq_gap_count"] > 0
    )
