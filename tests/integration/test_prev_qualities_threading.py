"""previous_qualities CLI 스레딩 — T5 종단 언블록 (issue #83).

CLI --prev-qualities 플래그로 직전 사이클 채널 quality 를 현재 사이클에 주입,
quality_delta 실계산 → T5(레이저/광학 교란) 종단 탐지.

1. extract_qualities 단위 — run_cycle 결과에서 채널별 quality 맵 추출
2. CLI --prev-qualities 플래그 — 파일 로드 후 run_cycle 에 전달
3. T5 종단 — terrain_class prev=1.0, curr=0.65 → quality_delta<-0.3 → T5 REMOTE 탐지
"""

import json
import pathlib

import pytest

from onboard.run import extract_qualities, run_cycle

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


# --- 1. extract_qualities 단위 ---

def test_extract_qualities_returns_channel_quality_map():
    """run_cycle 결과에서 채널명→quality 맵을 추출한다."""
    result = run_cycle(_load("raw_t3.json"), _load("mission_brief_t3.json"))
    qualities = extract_qualities(result)
    assert isinstance(qualities, dict)
    # 11개 채널 모두 존재해야 함
    assert "terrain_class" in qualities
    assert "link_status" in qualities
    assert "position_consistency" in qualities
    # 값은 0~1 float
    for ch, q in qualities.items():
        assert 0.0 <= q <= 1.0, f"{ch}: quality={q} 범위 이탈"


def test_extract_qualities_matches_abstraction_channels():
    """extract_qualities 값이 abstraction.channels 의 quality 와 일치한다."""
    result = run_cycle(_load("raw_t3.json"), _load("mission_brief_t3.json"))
    qualities = extract_qualities(result)
    for ch in result["abstraction"]["channels"]:
        assert qualities[ch["channel"]] == ch["quality"]


# --- 2. CLI --prev-qualities 플래그 ---

def test_cli_prev_qualities_flag(tmp_path):
    """--prev-qualities 파일을 넘기면 run_cycle 에 previous_qualities 가 전달된다."""
    from onboard import __main__ as cli

    raw_p = tmp_path / "raw.json"
    brief_p = tmp_path / "brief.json"
    prev_p = tmp_path / "prev.json"
    out_p = tmp_path / "out.json"

    raw_p.write_text(json.dumps(_load("raw_t3.json")), encoding="utf-8")
    brief_p.write_text(json.dumps(_load("mission_brief_t3.json")), encoding="utf-8")
    prev_p.write_text(json.dumps({"terrain_class": 1.0}), encoding="utf-8")

    import io, sys
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    rc = cli.main([str(raw_p), str(brief_p), "--prev-qualities", str(prev_p)])
    sys.stdout = old_stdout

    assert rc == 0
    out = json.loads(buf.getvalue())
    # terrain_class quality_delta 가 주입값(prev=1.0)으로 계산돼야 함
    for ch in out["abstraction"]["channels"]:
        if ch["channel"] == "terrain_class":
            # raw_t3 terrain_class quality ≈ 0.9 (default camera_confidence)
            # prev=1.0 → delta = 0.9-1.0 = -0.1 (T5 미발동, 하지만 delta 실계산 됨)
            assert ch["quality_delta"] != 0.0, "prev-qualities 주입 시 delta 가 0.0 이면 안 된다"
            break
    else:
        pytest.fail("terrain_class 채널 없음")


def test_cli_prev_qualities_invalid_path(tmp_path):
    """--prev-qualities 파일 경로가 없으면 오류 종료(rc!=0)."""
    from onboard import __main__ as cli

    raw_p = tmp_path / "raw.json"
    brief_p = tmp_path / "brief.json"
    raw_p.write_text(json.dumps(_load("raw_t3.json")), encoding="utf-8")
    brief_p.write_text(json.dumps(_load("mission_brief_t3.json")), encoding="utf-8")

    rc = cli.main([str(raw_p), str(brief_p), "--prev-qualities", str(tmp_path / "nonexistent.json")])
    assert rc != 0


# --- 3. T5 종단 — previous_qualities 주입으로 quality_delta 실계산 ---

def test_t5_quality_delta_triggers_with_prev_qualities():
    """terrain_class prev=1.0, curr=0.65 → delta=-0.35 → T5(REMOTE) 탐지."""
    raw = _load("raw_t5.json")
    mb = _load("mission_brief_t5.json")
    prev = {"terrain_class": 1.0}

    out = run_cycle(raw, mb, previous_qualities=prev)

    # quality_delta 실계산 확인
    tc = next(ch for ch in out["abstraction"]["channels"] if ch["channel"] == "terrain_class")
    assert tc["quality_delta"] < -0.3, f"quality_delta={tc['quality_delta']} — T5 발동 조건 미충족"

    # T5 위협 탐지 확인
    assert out["threat"]["primary"] is not None, "T5 위협이 primary 에 없음"
    assert out["threat"]["primary"]["threat_event"] == "T5"
    assert out["response"]["threat_category"] == "REMOTE"


def test_t5_no_detection_without_prev_qualities():
    """previous_qualities 없으면 quality_delta=0.0 → T5 미탐 (정상 baseline)."""
    out = run_cycle(_load("raw_t5.json"), _load("mission_brief_t5.json"))

    tc = next(ch for ch in out["abstraction"]["channels"] if ch["channel"] == "terrain_class")
    assert tc["quality_delta"] == 0.0

    # T5 위협 없어야 함
    primary = out["threat"].get("primary")
    assert primary is None or primary.get("threat_id") != "T5"
