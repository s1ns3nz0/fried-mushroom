"""rf_spectrum._detect_anomaly — 스펙트럼 샘플 기반 이상탐지 경로 커버.

fixture(build_scenario_envelope)는 wideband_anomaly 불리언만 심어 샘플 기반
분석 경로(max/median 비율)를 훑지 못한다(coverage gap). 이 파일이 그 위협탐지
분기를 직접 검증하고, 기대 입력 단위(양수 선형 전력)를 문서화한다.

판정: samples 가 있으면 median>0 일 때 max/median > 8.0 이면 anomaly.
그 외(빈 배열·median<=0)는 wideband_anomaly 불리언으로 폴백.
"""

from onboard.layer_02_sensor.mock_source import build_scenario_envelope
from onboard.layer_03_abstraction import rf_spectrum
from onboard.layer_03_abstraction.rf_spectrum import _detect_anomaly


class TestDetectAnomalySamples:
    def test_spike_exceeds_ratio_is_anomaly(self) -> None:
        # 양수 선형 전력에 스파이크: max/median = 20/1 = 20 > 8 → 재밍 탐지.
        assert _detect_anomaly({"samples": [1, 1, 1, 1, 20]}) is True

    def test_flat_spectrum_is_normal(self) -> None:
        # 평탄: max/median = 1 → 임계 미만.
        assert _detect_anomaly({"samples": [5, 5, 5, 5]}) is False

    def test_ratio_exactly_at_threshold_is_not_anomaly(self) -> None:
        # 경계: 8/1 = 8, '> 8' 이므로 False (strict).
        assert _detect_anomaly({"samples": [1, 1, 8]}) is False

    def test_median_zero_falls_back_to_flag(self) -> None:
        # median 0 (0으로 나눔 방지) → wideband_anomaly 불리언 폴백.
        assert _detect_anomaly({"samples": [0, 0, 1], "wideband_anomaly": True}) is True
        assert _detect_anomaly({"samples": [0, 0, 1], "wideband_anomaly": False}) is False

    def test_empty_samples_falls_back_to_flag(self) -> None:
        assert _detect_anomaly({"samples": [], "wideband_anomaly": True}) is True

    def test_no_samples_key_uses_flag(self) -> None:
        assert _detect_anomaly({"wideband_anomaly": True}) is True
        assert _detect_anomaly({}) is False

    def test_negative_dbm_scale_falls_back(self) -> None:
        # 문서화: 샘플은 '양수 선형 전력' 가정. 음수(dBm) 이면 median<=0 → 폴백.
        assert _detect_anomaly({"samples": [-90, -88, -40]}) is False


class TestRunWithSamples:
    def test_run_marks_anomaly_from_samples(self) -> None:
        raw = build_scenario_envelope("t1", 0, 0)
        raw["ew"]["rf_wideband_scan"] = {"samples": [2, 2, 2, 40]}  # 40/2=20 > 8
        out = rf_spectrum.run(raw)
        assert out["state"] == "anomaly"
        assert out["payload"]["wideband_anomaly"] is True
