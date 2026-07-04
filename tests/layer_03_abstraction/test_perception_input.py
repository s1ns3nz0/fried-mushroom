"""03 perception 실프레임 데이터 경로 계약 (#355, ADR-002).

resolve_frame: 실 프레임 소스(eo_frame) → PerceptionFrame, 없으면 None(mock 폴백).
하위호환(기존 mock imagery → None) + 계약(PerceptionFrame 키/치수/bytes) 잠금. TDD.
"""

import base64
import json
from pathlib import Path

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction.perception_input import (
    PerceptionFrame,
    has_real_frame,
    resolve_frame,
)

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
_FRAME_KEYS = set(PerceptionFrame.__annotations__)


def _synth_imagery():
    bundle = json.loads((_EXAMPLES / "imagery_frame_synth.json").read_text(encoding="utf-8"))
    return {"eo_frame": bundle["eo_frame"]}


# --- 하위호환: mock imagery 는 실 프레임 없음 → None (폴백) ---


def test_mock_imagery_has_no_real_frame():
    raw = build_normal_envelope("s", 0, 0)
    assert has_real_frame(raw["imagery"]) is False
    assert resolve_frame(raw["imagery"]) is None


def test_absent_eo_frame_returns_none():
    assert resolve_frame({"object_label": {"class": "person"}}) is None
    assert resolve_frame({"eo_frame_ref": "buf://mock/123"}) is None  # mock ref ≠ 실프레임


# --- 실 프레임: eo_frame(b64) → PerceptionFrame 계약 ---


def test_resolve_b64_frame_contract():
    frame = resolve_frame(_synth_imagery())
    assert frame is not None
    assert set(frame.keys()) == _FRAME_KEYS
    assert frame["kind"] == "eo" and frame["fmt"] == "raw"
    assert frame["width"] == 4 and frame["height"] == 4 and frame["channels"] == 3
    assert isinstance(frame["raw_bytes"], bytes) and len(frame["raw_bytes"]) == 48
    assert frame["meta"]["gimbal_deg"] == 15.0


def test_resolve_path_frame(tmp_path):
    raw = bytes(range(24))
    p = tmp_path / "f.raw"
    p.write_bytes(raw)
    frame = resolve_frame({"eo_frame": {"kind": "ir", "fmt": "raw", "width": 2,
                                        "height": 4, "channels": 1, "path": str(p)}})
    assert frame is not None and frame["raw_bytes"] == raw and frame["kind"] == "ir"


def test_raw_fmt_array_none_without_decode():
    # raw 포맷은 decode 불필요 → array None, raw_bytes 로 전달(모델이 치수로 해석).
    frame = resolve_frame(_synth_imagery())
    assert frame["array"] is None


def test_corrupt_b64_returns_none():
    assert resolve_frame({"eo_frame": {"bytes_b64": "!!!not-base64!!!"}}) is None


def test_missing_source_returns_none():
    # eo_frame 있으나 bytes/path 없음 → 실프레임 아님.
    assert resolve_frame({"eo_frame": {"kind": "eo", "fmt": "raw"}}) is None


# --- 견고성: malformed eo_frame 은 크래시 대신 안전 파싱(#357 경화) ---


def _b64(data=b"xxxx"):
    import base64
    return base64.b64encode(data).decode()


def test_malformed_dims_do_not_crash():
    # 비숫자/None/float-str 치수 → 크래시 없이 안전 기본값(폴백 아닌 프레임, bytes 유효).
    for bad in ("abc", None, "4.5", [1, 2]):
        frame = resolve_frame({"eo_frame": {"bytes_b64": _b64(), "width": bad,
                                            "height": bad, "channels": bad}})
        assert frame is not None
        assert isinstance(frame["width"], int) and isinstance(frame["channels"], int)


def test_float_str_dim_truncated():
    frame = resolve_frame({"eo_frame": {"bytes_b64": _b64(), "width": "4.5"}})
    assert frame["width"] == 4


def test_non_dict_meta_does_not_crash():
    frame = resolve_frame({"eo_frame": {"bytes_b64": _b64(), "meta": "notadict"}})
    assert frame is not None and frame["meta"] == {}
