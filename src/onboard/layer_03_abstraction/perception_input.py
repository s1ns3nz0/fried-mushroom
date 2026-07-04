"""03 perception 실프레임 데이터 경로 — 실모델(YOLO/YAMNet/segmentation) 언블록 (#355, ADR-002).

현 `imagery` 는 mock 힌트(`object_label`, `eo_frame_ref="buf://..."`)만 담는다. 실 perception
모델은 실 픽셀이 필요하므로, 이 모듈이 **02 raw imagery → 03 perception 표준 입력**을 잇는다:

- `imagery.eo_frame`(선택, 하위호환): 실 프레임 소스 — 파일경로 또는 base64 bytes + 포맷/치수/메타.
- `resolve_frame(imagery)` → `PerceptionFrame | None`: 실 소스가 있으면 정규화(가능 시 decode),
  없으면 None(호출부는 기존 mock 힌트로 폴백 — **결정론 판정·골든 무변경**).

**계약**: perception 실모델 PR 은 `PerceptionFrame` 만 소비하면 된다(이미지 배열 또는 raw
bytes + 치수/메타). 무거운 모델 로딩·decode 는 이 태스크 범위 밖 — decode 라이브러리(cv2/PIL)가
있으면 `array` 를 채우고, 없으면 `array=None` + `raw_bytes` 로 넘겨 모델이 자체 decode 하게 한다.

**SCC-1**: perception 은 03 AI 채널(병렬 참고). 이 경로는 결정론 채널 판정에 영향을 주지 않는다.
"""

from __future__ import annotations

import base64
from typing import Any, Optional, TypedDict


class PerceptionFrame(TypedDict):
    """perception 실모델이 소비하는 정규화 프레임 인터페이스 (03 계약).

    array 는 decode 가능(cv2/PIL 존재)할 때만 채워지고, 아니면 None(raw_bytes 로 대체).
    """
    kind: str                # "eo" | "ir"
    fmt: str                 # "raw" | "png" | "jpg" | ...
    width: int
    height: int
    channels: int            # RGB=3, gray/IR=1
    raw_bytes: bytes         # 항상 존재(원본 인코딩 바이트 또는 raw 픽셀)
    array: Optional[Any]     # decode 된 ndarray(가능 시), 아니면 None
    meta: dict               # gimbal_deg, ts, source 등 부가정보


def _load_bytes(src: dict) -> Optional[bytes]:
    """eo_frame 소스에서 원본 bytes 추출 — `bytes_b64`(base64) 또는 `path`(파일)."""
    b64 = src.get("bytes_b64")
    if b64:
        try:
            return base64.b64decode(b64)
        except (ValueError, TypeError):
            return None
    path = src.get("path")
    if path:
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None
    return None


def _try_decode(raw: bytes, fmt: str) -> Optional[Any]:
    """가용한 라이브러리로 decode 시도(cv2 → PIL). 없으면 None(모델이 자체 decode).

    무거운 의존은 lazy import — 코어 파이프라인은 이 함수를 강제하지 않는다.
    """
    if fmt == "raw":
        return None  # raw 픽셀은 치수와 함께 raw_bytes 로 그대로 전달.
    try:
        import numpy as np  # noqa: PLC0415
        try:
            import cv2  # noqa: PLC0415
            arr = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
            return arr
        except Exception:
            pass
        try:
            import io  # noqa: PLC0415
            from PIL import Image  # noqa: PLC0415
            return np.asarray(Image.open(io.BytesIO(raw)))
        except Exception:
            return None
    except Exception:
        return None


def has_real_frame(imagery: dict) -> bool:
    """imagery 에 실 프레임 소스(eo_frame + bytes/path)가 있는지 — mock 힌트와 구분."""
    src = imagery.get("eo_frame")
    return isinstance(src, dict) and bool(src.get("bytes_b64") or src.get("path"))


def resolve_frame(imagery: dict) -> Optional[PerceptionFrame]:
    """02 raw imagery → 정규화 PerceptionFrame. 실 소스 없으면 None(mock 폴백).

    imagery.eo_frame(선택): {kind, fmt, width, height, channels, bytes_b64|path, meta}.
    """
    if not has_real_frame(imagery):
        return None
    src = imagery["eo_frame"]
    raw = _load_bytes(src)
    if raw is None:
        return None
    fmt = str(src.get("fmt", "raw"))
    frame: PerceptionFrame = {
        "kind": str(src.get("kind", "eo")),
        "fmt": fmt,
        "width": int(src.get("width", 0)),
        "height": int(src.get("height", 0)),
        "channels": int(src.get("channels", 3)),
        "raw_bytes": raw,
        "array": _try_decode(raw, fmt),
        "meta": dict(src.get("meta") or {}),
    }
    return frame


# --- 음향(acoustic) 실 파형 데이터 경로 — YAMNet 실모델 언블록 (perception 후속) ---


class AudioClip(TypedDict):
    """acoustic 실모델(YAMNet)이 소비하는 정규화 오디오 인터페이스.

    samples 는 decode 가능(numpy 등)할 때만 채워지고, 아니면 None(raw_bytes 로 대체).
    """
    fmt: str                 # "pcm16" | "wav" | "raw" | ...
    sample_rate: int
    channels: int
    raw_bytes: bytes         # 원본 파형 바이트
    samples: Optional[Any]   # decode 된 파형 배열(가능 시), 아니면 None
    meta: dict


def has_real_audio(acoustic: dict) -> bool:
    """acoustic 에 실 파형 소스(waveform + bytes/path)가 있는지 — mock 힌트와 구분."""
    src = acoustic.get("waveform")
    return isinstance(src, dict) and bool(src.get("bytes_b64") or src.get("path"))


def resolve_audio(acoustic: dict) -> Optional[AudioClip]:
    """02 raw acoustic → 정규화 AudioClip. 실 소스 없으면 None(mock 폴백).

    acoustic.waveform(선택): {fmt, sample_rate, channels, bytes_b64|path, meta}.
    """
    if not has_real_audio(acoustic):
        return None
    src = acoustic["waveform"]
    raw = _load_bytes(src)
    if raw is None:
        return None
    return {
        "fmt": str(src.get("fmt", "pcm16")),
        "sample_rate": int(src.get("sample_rate", 16000)),
        "channels": int(src.get("channels", 1)),
        "raw_bytes": raw,
        "samples": None,   # 실모델이 자체 decode(pcm16→float 등) — 무거운 decode 는 모델측.
        "meta": dict(src.get("meta") or {}),
    }
