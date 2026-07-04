"""T1(GPS 스푸핑)/T2(사이버) 시나리오 → 03 채널 이상 산출 검증.

02 mock_source 가 심은 신호를 03 결정론 채널이 anomaly 로 잡는지 확인한다.
(04 탐지까지의 종단은 T1 만 test_e2e_semantics 에서 검증 — T2 는 04 Q_MIN
게이트 이슈로 종단 미탐지, 별도 이슈 참조.)
"""

from onboard.layer_02_sensor.mock_source import build_scenario_envelope
from onboard.layer_03_abstraction import run as layer_03
from onboard.shared.constants import Q_MIN


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


def test_t2_anomaly_channels_survive_qmin_gate() -> None:
    # 회귀 방지(#28): 이상 증거는 state/payload 로, quality 는 판독기 건전성.
    # anomaly 여도 quality 가 Q_MIN(0.65) 아래로 떨어지지 않아야 04 게이트를 통과한다.
    ch = _channels("t2")
    assert ch["encryption_status"]["quality"] >= Q_MIN
    assert ch["link_integrity"]["quality"] >= Q_MIN
