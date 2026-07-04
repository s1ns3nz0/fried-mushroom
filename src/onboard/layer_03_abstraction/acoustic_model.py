"""03 acoustic 실모델 — YAMNet 2차 음향분류 (AudioClip 소비, perception 후속).

#357(imagery 데이터경로)·#364(YOLO/segmentation) 에 이은 perception 세 번째 축: 음향.
1차 임계매칭이 애매(ambiguous)할 때만 게이팅으로 호출되는 YAMNet 2차를 실모델로.
`perception_input.resolve_audio` 의 AudioClip 을 소비한다.

**opt-in + graceful fallback**(#364 perception 실모델과 동일 패턴, 같은 env 플래그):
- `ONBOARD_PERCEPTION_MODEL=1` 일 때만 활성. 기본은 yamnet_stub 힌트.
- tensorflow_hub YAMNet lazy import(broad except → None). 미설치/decode 불가 등 어떤 실패든
  None → acoustic_event 가 stub 으로 하향(크래시 0, 골든·결정론 무변경).

반환 계약은 yamnet_stub.classify_acoustic 와 **동일 키셋**: {event_type, yamnet_confidence}.
event_type 어휘도 stub 과 동일(gunshot/explosion/propeller/unknown) — acoustic_event 의
_YAMNET_EVENT_MAP 이 그대로 소비.

**SCC-1**: acoustic 은 03 AI 채널(병렬 참고). 결정론 채널·RAC_MATRIX 와 무관.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .perception_input import AudioClip

_ENV_FLAG = "ONBOARD_PERCEPTION_MODEL"  # #364 perception 실모델과 동일 opt-in.
_MODEL_CACHE: dict[str, Any] = {}

# YAMNet AudioSet 상위 라벨(소문자 부분일치) → stub 어휘. 여기 없으면 "unknown".
_AUDIOSET_MAP = (
    ("gunshot", "gunshot"), ("gunfire", "gunshot"), ("machine gun", "gunshot"),
    ("explosion", "explosion"), ("boom", "explosion"), ("artillery", "explosion"),
    ("propeller", "propeller"), ("aircraft", "propeller"), ("helicopter", "propeller"),
    ("fixed-wing", "propeller"),
)


def enabled(explicit: bool | None = None) -> bool:
    """실모델 경로 활성 여부 — 인자 우선, 없으면 환경변수 opt-in."""
    if explicit is not None:
        return explicit
    return os.environ.get(_ENV_FLAG) == "1"


def _load_yamnet():
    """tensorflow_hub YAMNet lazy load — 미설치/실패 시 None(성공분만 캐시)."""
    if "yamnet" in _MODEL_CACHE:
        return _MODEL_CACHE["yamnet"]
    try:
        import tensorflow_hub as hub  # noqa: PLC0415

        model = hub.load("https://tfhub.dev/google/yamnet/1")
    except Exception:
        return None  # 캐시하지 않음(일시적 미가용이 굳지 않게 — nlp_model 선례).
    _MODEL_CACHE["yamnet"] = model
    return model


def model_available() -> bool:
    return _load_yamnet() is not None


# TF Hub YAMNet 입력 요구사항 — 16kHz mono 파형.
_YAMNET_SAMPLE_RATE = 16000
_YAMNET_CHANNELS = 1


def _decode_waveform(clip: AudioClip):
    """AudioClip.raw_bytes(pcm16) → float32 [-1,1] 파형(numpy). 실패/비호환 시 None.

    YAMNet 은 **16kHz mono** 를 요구한다. 44.1/48kHz·스테레오면 리샘플/다운믹스가 필요한데
    그건 무거운 의존(scipy/librosa)이라 MVP 스코프 밖 → **검증 후 폴백**(None)이 안전
    (codex #375 P2). 잘못된 sample_rate/channels 로 raw PCM 을 그대로 투입하면 타이밍·채널이
    틀어져 오분류하므로 하지 않는다.
    """
    if clip.get("samples") is not None:
        return clip["samples"]
    if clip.get("fmt") != "pcm16":
        return None  # 그 외 포맷은 모델측 decode 필요 — 여기선 미지원 → 폴백.
    if clip.get("sample_rate") != _YAMNET_SAMPLE_RATE or clip.get("channels") != _YAMNET_CHANNELS:
        return None  # 16kHz mono 아님 → 리샘플/다운믹스 없이 폴백(오분류 방지).
    try:
        import numpy as np  # noqa: PLC0415

        pcm = np.frombuffer(clip["raw_bytes"], dtype=np.int16).astype(np.float32) / 32768.0
        return pcm
    except Exception:
        return None


def _map_label(label: str) -> str:
    low = label.lower()
    for needle, event in _AUDIOSET_MAP:
        if needle in low:
            return event
    return "unknown"


def classify_acoustic_model(clip: AudioClip) -> Optional[dict]:
    """AudioClip → 2차 음향분류(yamnet_stub 와 동일 키셋). 실패/미가용 시 None(폴백).

    반환: {event_type∈{gunshot,explosion,propeller,unknown}, yamnet_confidence}.
    """
    model = _load_yamnet()
    if model is None:
        return None
    wav = _decode_waveform(clip)
    if wav is None:
        return None
    try:
        scores, _embeddings, _spec = model(wav)
        import numpy as np  # noqa: PLC0415

        mean_scores = np.mean(scores.numpy(), axis=0)
        top_idx = int(np.argmax(mean_scores))
        confidence = float(mean_scores[top_idx])
        # AudioSet class map 은 모델 자산(class_map_path). 라벨 조회 실패 시 unknown.
        try:
            import csv  # noqa: PLC0415

            class_map_path = model.class_map_path().numpy().decode("utf-8")
            with open(class_map_path) as f:
                labels = [row["display_name"] for row in csv.DictReader(f)]
            label = labels[top_idx]
        except Exception:
            label = "unknown"
    except Exception:
        return None
    return {"event_type": _map_label(label), "yamnet_confidence": round(confidence, 6)}
