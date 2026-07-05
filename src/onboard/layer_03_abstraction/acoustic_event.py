"""acoustic_event — 🔵 1차 임계값 매칭 + 🟡 YAMNet 2차(게이팅).

peak_db·rise_time_ms 로 총성을 1차 확정한다. 1차가 애매한 경우(event_type="ambiguous")
에만 YAMNet stub 을 2차로 호출해 덮어쓴다 — 트리거 기반 게이팅(SWaP 예산, 03 문서).
명확한 케이스에는 stub 을 호출하지 않는다.
"""

from onboard.ai_stubs.yamnet_stub import classify_acoustic
from onboard.layer_03_abstraction import acoustic_model
from onboard.layer_03_abstraction._common import make_output
from onboard.layer_03_abstraction.perception_input import has_real_audio, resolve_audio
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput

_GUNSHOT_PEAK_DB = 90.0
_GUNSHOT_RISE_MS = 3.0
_AMBIGUOUS_PEAK_DB = 75.0

# YAMNet event_type → A-1 어휘 정규화.
_YAMNET_EVENT_MAP = {
    "gunshot": "gunshot",
    "explosion": "explosion",
    "propeller": "propeller_approach",
    "unknown": "ambiguous",
}
# 2차 결과 event_type → 채널 state.
_EVENT_TO_STATE = {
    "gunshot": "anomaly",
    "explosion": "anomaly",
    "propeller_approach": "degraded",
    "ambiguous": "degraded",
}


def _classify_secondary(acoustic: dict) -> dict:
    """YAMNet 2차 — opt-in 실모델(실 파형 존재 시) 우선, 실패/미가용/미활성 시 stub 폴백.

    실모델은 stub 과 동일 키셋({event_type, yamnet_confidence})을 반환하므로 아래 게이팅
    로직은 무변경(결정론·골든 유지).
    """
    if acoustic_model.enabled() and has_real_audio(acoustic):
        clip = resolve_audio(acoustic)
        if clip is not None:
            res = acoustic_model.classify_acoustic_model(clip)
            if res is not None:
                return res
    return classify_acoustic(acoustic)


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    acoustic = raw["acoustic"]
    peak_db = acoustic["peak_db"]
    rise_time_ms = acoustic["rise_time_ms"]

    if peak_db > _GUNSHOT_PEAK_DB and rise_time_ms < _GUNSHOT_RISE_MS:
        event_type, state, quality = "gunshot", "anomaly", 0.92
    elif peak_db >= _AMBIGUOUS_PEAK_DB:
        # 1차만으로 애매 — YAMNet 2차 대상.
        event_type, state, quality = "ambiguous", "degraded", 0.6
    else:
        event_type, state, quality = "none", "normal", 0.9

    payload = {
        "event_type": event_type,
        "detection_stage": "threshold_only",
        "peak_db": peak_db,
        "bearing_deg": acoustic["bearing_deg"],
    }

    # 게이팅: 애매한 경우에만 YAMNet 2차 승격 (opt-in 실모델 또는 stub).
    if event_type == "ambiguous":
        secondary = _classify_secondary(acoustic)
        resolved = _YAMNET_EVENT_MAP.get(secondary["event_type"], "ambiguous")
        payload["event_type"] = resolved
        payload["detection_stage"] = "yamnet_secondary"
        payload["yamnet_confidence"] = secondary["yamnet_confidence"]
        state = _EVENT_TO_STATE.get(resolved, "degraded")
        quality = secondary["yamnet_confidence"]

    return make_output("acoustic_event", state, quality, payload, previous_quality)
