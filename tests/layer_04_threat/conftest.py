"""layer_04_threat 테스트 공용 fixture.

layer 03 이 아직 미구현이라, D4D 문서(03/04/C-1)의 예시 값을 그대로 옮긴
AbstractionOutput mock 을 fixture 로 제공한다 (README '충돌 방지' 규칙).

- t3: C-1 8절 GIREOGI-0704-01 (근접 소화기)
- t4: C-1 9절 물리 포획 (다중채널 AND) + link_integrity anomaly (T2 동반)
- t7: 지형충돌/CFIT (LAND 국면 배수 1.2)
- normal: 이상 신호 없음
"""

from __future__ import annotations

import pytest

from onboard.shared.schemas import AbstractionOutput, ChannelOutput


def _ch(
    channel: str,
    state: str,
    quality: float,
    payload: dict,
    quality_delta: float = 0.0,
) -> ChannelOutput:
    return {
        "channel": channel,
        "state": state,
        "quality": quality,
        "quality_delta": quality_delta,
        "payload": payload,
    }


def _envelope(id_: str, channels: list[ChannelOutput]) -> AbstractionOutput:
    return {
        "schema_version": "1.0",
        "id": id_,
        "ts": 1730620801200,
        "channels": channels,
    }


@pytest.fixture
def abstraction_t3() -> AbstractionOutput:
    """C-1 8절 — proximity_object(무기형상) + acoustic_event(총성) → T3."""
    return _envelope(
        "GIREOGI-0704-01-01",
        [
            _ch("position_consistency", "normal", 0.95, {"gps_imu_residual_m": 0.8}),
            _ch(
                "mission_phase",
                "normal",
                0.90,
                {
                    "declared": "LOITER_ROI",
                    "behavioral": "LOITER_ROI",
                    "match": True,
                    "mission_phase_confidence": 0.9,
                },
            ),
            _ch(
                "proximity_object",
                "anomaly",
                0.90,
                {"class": "person", "weapon_shape": True, "closing": False},
            ),
            _ch("acoustic_event", "anomaly", 0.92, {"event_type": "gunshot"}),
            _ch("terrain_class", "normal", 0.85, {"exposure_score": 0.4}),
        ],
    )


@pytest.fixture
def abstraction_t4() -> AbstractionOutput:
    """C-1 9절 — proximity(vehicle,closing) + mission_phase(match=False) + link_status(anomaly) → T4.

    link_integrity anomaly 를 함께 넣어 T2 동반 매칭도 확인한다.
    """
    return _envelope(
        "CONVOY-0704-02-01",
        [
            _ch("position_consistency", "normal", 0.95, {"gps_imu_residual_m": 0.8}),
            _ch(
                "mission_phase",
                "normal",
                0.80,
                {
                    "declared": "WAYPOINT",
                    "behavioral": "LOITER_ROI",
                    "match": False,
                    "mission_phase_confidence": 0.8,
                },
            ),
            _ch(
                "proximity_object",
                "anomaly",
                0.88,
                {"class": "vehicle", "weapon_shape": False, "closing": True},
            ),
            _ch("link_status", "anomaly", 0.70, {"rssi_dbm": -95}),
            _ch(
                "link_integrity",
                "anomaly",
                0.90,
                {"checksum_fail_rate": 0.1, "seq_gap_count": 0},
            ),
        ],
    )


@pytest.fixture
def abstraction_t7() -> AbstractionOutput:
    """obstacle_proximity 충돌예상시간 2.0초(<3.0) → T7, LAND 국면 배수 1.2."""
    return _envelope(
        "TRANSPORT-0704-03-01",
        [
            _ch("position_consistency", "normal", 0.95, {"gps_imu_residual_m": 0.8}),
            _ch(
                "mission_phase",
                "normal",
                0.90,
                {
                    "declared": "LAND",
                    "behavioral": "LAND",
                    "match": True,
                    "mission_phase_confidence": 0.9,
                },
            ),
            _ch(
                "obstacle_proximity",
                "anomaly",
                0.90,
                {"distance_m": 20.0, "closure_rate_mps": 10.0},
            ),
            _ch("terrain_class", "normal", 0.85, {"exposure_score": 0.5}),
        ],
    )


@pytest.fixture
def abstraction_stub() -> AbstractionOutput:
    """layer 03 미구현 시 orchestrator 가 넘기는 stub (mission_phase 채널 없음)."""
    return {
        "schema_version": "0.0-stub",
        "id": "stub",
        "ts": 0,
        "channels": [],
    }


@pytest.fixture
def abstraction_normal() -> AbstractionOutput:
    """이상 신호 없음 → 매칭 없음."""
    return _envelope(
        "NORMAL-0704-04-01",
        [
            _ch("position_consistency", "normal", 0.96, {"gps_imu_residual_m": 0.8}),
            _ch(
                "mission_phase",
                "normal",
                0.95,
                {
                    "declared": "WAYPOINT",
                    "behavioral": "WAYPOINT",
                    "match": True,
                    "mission_phase_confidence": 0.95,
                },
            ),
            _ch(
                "proximity_object",
                "normal",
                0.93,
                {"class": "none", "weapon_shape": False, "closing": False},
            ),
            _ch("acoustic_event", "normal", 0.90, {"event_type": "none"}),
            _ch(
                "link_integrity",
                "normal",
                0.94,
                {"checksum_fail_rate": 0.0, "seq_gap_count": 0},
            ),
            _ch("encryption_status", "normal", 0.95, {"downgrade_detected": False}),
            _ch("rf_spectrum", "normal", 0.90, {"wideband_anomaly": False}),
            _ch("link_status", "normal", 0.92, {"rssi_dbm": -70}),
            _ch(
                "obstacle_proximity",
                "normal",
                0.90,
                {"distance_m": 500.0, "closure_rate_mps": 5.0},
            ),
            _ch("terrain_class", "normal", 0.88, {"exposure_score": 0.2}),
        ],
    )
