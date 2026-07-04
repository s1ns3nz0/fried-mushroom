"""다중 사이클 종단 통합 테스트 — issue #101.

run_cycle 을 루프로 2회 호출:
  1. 1회차 extract_qualities → 2회차 previous_qualities 주입
  2. terrain_class quality_delta ≈ -0.35 (T5 발동 조건 quality_delta < -0.3)
  3. T5 위협이 2회차 primary 로 탐지됨
  4. CLI --prev-qualities 2-run 시나리오도 잠금
"""

import copy
import io
import json
import pathlib
import sys

import pytest

from onboard.run import extract_qualities, run_cycle

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _with_terrain_confidence(base: dict, conf: float) -> dict:
    """base raw 에서 camera_confidence 만 교체한 깊은 복사본 반환."""
    raw = copy.deepcopy(base)
    terrain = raw.get("imagery", {}).get("terrain_label", {})
    raw.setdefault("imagery", {})["terrain_label"] = {
        "dominant_class": terrain.get("dominant_class", "open_field"),
        "camera_confidence": conf,
    }
    return raw


# ---------------------------------------------------------------------------
# 1. Python API — 2-사이클 quality 스레딩
# ---------------------------------------------------------------------------


def test_two_cycle_quality_threading():
    """run_cycle 2회 루프 — 1회차 extract_qualities → 2회차 previous_qualities 주입 → T5 탐지."""
    mb = _load("mission_brief_t5.json")
    raw_base = _load("raw_t5.json")

    # 1회차: camera_confidence=1.0 → terrain_class quality=1.0
    c1 = run_cycle(_with_terrain_confidence(raw_base, 1.0), mb)

    # quality 스레딩
    prev_qualities = extract_qualities(c1)
    assert prev_qualities["terrain_class"] == pytest.approx(1.0), (
        "1회차 terrain_class quality 가 1.0 이어야 함"
    )

    # 2회차: camera_confidence=0.65 (raw_t5 원본), prev=1.0 → delta=-0.35
    c2 = run_cycle(raw_base, mb, previous_qualities=prev_qualities)

    tc = next(ch for ch in c2["abstraction"]["channels"] if ch["channel"] == "terrain_class")
    assert tc["quality"] == pytest.approx(0.65)
    assert tc["quality_delta"] == pytest.approx(-0.35, abs=1e-6), (
        f"quality_delta={tc['quality_delta']} — 예상값 ≈-0.35"
    )
    assert tc["quality_delta"] < -0.3, "T5 발동 조건(quality_delta < -0.3) 미충족"

    # T5 primary 탐지
    assert c2["threat"]["primary"] is not None, "T5 위협이 primary 에 없음"
    assert c2["threat"]["primary"]["threat_event"] == "T5", (
        f"primary 위협이 T5 여야 함, 실제: {c2['threat']['primary'].get('threat_event')}"
    )
    assert c2["response"]["threat_category"] == "REMOTE", (
        "T5 대응 분류는 REMOTE 이어야 함"
    )


def test_two_cycle_no_t5_without_threading():
    """previous_qualities 미주입 시 2회차에서도 T5 미탐 — 스레딩 없는 baseline."""
    mb = _load("mission_brief_t5.json")
    raw = _load("raw_t5.json")

    c1 = run_cycle(raw, mb)
    c2 = run_cycle(raw, mb)

    for result, label in ((c1, "c1"), (c2, "c2")):
        tc = next(ch for ch in result["abstraction"]["channels"] if ch["channel"] == "terrain_class")
        assert tc["quality_delta"] == 0.0, f"{label}: prev 없으면 delta 는 0.0 이어야 함"

    primary = c2["threat"].get("primary")
    assert primary is None or primary.get("threat_event") != "T5", (
        "스레딩 없이 T5 탐지됐으면 안 됨"
    )


def test_multi_cycle_non_terrain_channels_delta_zero():
    """2회차에서 terrain_class 이외 채널의 quality_delta 는 0.0 — 채널 간 오염 없음."""
    mb = _load("mission_brief_t5.json")
    raw_base = _load("raw_t5.json")

    c1 = run_cycle(_with_terrain_confidence(raw_base, 1.0), mb)
    # 1회차와 2회차는 terrain_label 만 다름 → 나머지 채널 quality 동일 → delta=0.0
    c2 = run_cycle(raw_base, mb, previous_qualities=extract_qualities(c1))

    for ch in c2["abstraction"]["channels"]:
        if ch["channel"] == "terrain_class":
            continue
        assert ch["quality_delta"] == pytest.approx(0.0), (
            f"{ch['channel']}: 비(非)terrain 채널 delta 가 0.0 이어야 함"
        )


def test_extract_qualities_round_trips_into_next_cycle():
    """extract_qualities 반환값을 바로 previous_qualities 로 재사용 가능 — 타입 계약 확인."""
    mb = _load("mission_brief_t5.json")
    raw = _load("raw_t5.json")

    c1 = run_cycle(raw, mb)
    prev = extract_qualities(c1)

    # 값은 0~1 float, 키는 채널명
    assert all(isinstance(k, str) for k in prev)
    assert all(isinstance(v, float) for v in prev.values())
    assert all(0.0 <= v <= 1.0 for v in prev.values())

    # 바로 주입해도 오류 없이 실행돼야 함
    c2 = run_cycle(raw, mb, previous_qualities=prev)
    assert "abstraction" in c2
    assert "threat" in c2


# ---------------------------------------------------------------------------
# 2. CLI — 2-run 시나리오
# ---------------------------------------------------------------------------


def test_cli_two_run_scenario(tmp_path):
    """CLI 2-run 시나리오 — 1회차 출력을 prev-qualities 로 저장 후 2회차 --prev-qualities 주입."""
    from onboard import __main__ as cli

    mb_p = EXAMPLES / "mission_brief_t5.json"
    raw_base = _load("raw_t5.json")

    # 1회차 raw: camera_confidence=1.0
    raw_c1_p = tmp_path / "raw_c1.json"
    raw_c1_p.write_text(json.dumps(_with_terrain_confidence(raw_base, 1.0)), encoding="utf-8")

    # 2회차 raw: raw_t5 원본 (camera_confidence=0.65)
    raw_c2_p = tmp_path / "raw_c2.json"
    raw_c2_p.write_text(json.dumps(raw_base), encoding="utf-8")

    # 1회차 CLI 실행
    buf1 = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf1
    rc1 = cli.main([str(raw_c1_p), str(mb_p)])
    sys.stdout = old_stdout
    assert rc1 == 0
    c1_result = json.loads(buf1.getvalue())

    # extract_qualities → prev-qualities 파일 저장
    prev_q_p = tmp_path / "prev_qualities.json"
    prev_q_p.write_text(json.dumps(extract_qualities(c1_result)), encoding="utf-8")

    # 2회차 CLI 실행: --prev-qualities 주입
    buf2 = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf2
    rc2 = cli.main([str(raw_c2_p), str(mb_p), "--prev-qualities", str(prev_q_p)])
    sys.stdout = old_stdout
    assert rc2 == 0
    c2_result = json.loads(buf2.getvalue())

    # 검증: T5 발동
    tc = next(ch for ch in c2_result["abstraction"]["channels"] if ch["channel"] == "terrain_class")
    assert tc["quality_delta"] < -0.3, f"quality_delta={tc['quality_delta']} — T5 조건 미충족"
    assert c2_result["threat"]["primary"]["threat_event"] == "T5"
    assert c2_result["response"]["threat_category"] == "REMOTE"
