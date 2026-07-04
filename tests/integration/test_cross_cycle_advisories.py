"""link_loss · nav_integrity cross-cycle advisory — run_cycle_chain 배선 검증 (#389).

#372/#373 으로 standalone 모듈이 추가됐으나 파이프라인에 미배선.
이 테스트는 run_cycle_chain 결과에서 link_window/nav_window 를 추출해
assess_link_loss/assess_nav_integrity 가 의미있는 advisory 를 내는지 검증한다.

CRITICAL: advisory 추가가 결정론 판정(risk/threat/response/flight_plan) 불변(SCC-1).
single run_cycle 출력(golden) 은 변경하지 않는다.
"""

from __future__ import annotations

import copy
import json
import math
import pathlib

import pytest

from onboard.layer_02_sensor.mock_source import build_normal_envelope, build_scenario_envelope
from onboard.link_loss import assess_link_loss
from onboard.nav_integrity import assess_nav_integrity
from onboard.run import (
    extract_link_cycle_seconds,
    extract_link_window,
    extract_nav_cycle_seconds,
    extract_nav_window,
    run_cycle,
    run_cycle_chain,
)

_EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _raw_link_lost(seq: int) -> dict:
    """C2 링크 완전두절 raw (rssi_dbm=-98, packet_loss_rate=1.0) — link_status anomaly 유발."""
    raw = build_normal_envelope("LL", seq, seq * 1000)
    raw["c2_link"].update({"rssi_dbm": -98, "packet_loss_rate": 1.0, "latency_ms": 400})
    return raw


def _raw_nav_lost(seq: int) -> dict:
    """GPS 스푸핑/무결성 상실 raw (hdop=10, 위치 대편차) — position_consistency anomaly 유발."""
    raw = build_normal_envelope("NL", seq, seq * 1000)
    raw["navigation"]["gps"]["hdop"] = 10.0
    raw["navigation"]["gps"]["lat"] = 38.0  # GPS↔IMU 큰 잔차 → anomaly
    return raw


def _load(name: str) -> dict:
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _brief() -> dict:
    return _load("mission_brief_t3.json")


def _raw_normal(seq: int = 0) -> dict:
    return build_normal_envelope("CCA", seq, seq * 1000)


# ── 1. 헬퍼: extract_link_window / extract_nav_window ──────────────────────────


def test_extract_link_window_returns_list_of_channel_dicts():
    """extract_link_window 가 link_status ChannelOutput 리스트를 반환해야 한다."""
    results = run_cycle_chain([(_raw_normal(0), _brief()), (_raw_normal(1), _brief())])
    window = extract_link_window(results)
    assert isinstance(window, list)
    assert len(window) == 2
    for entry in window:
        assert entry["channel"] == "link_status"
        assert "state" in entry


def test_extract_nav_window_returns_list_of_channel_dicts():
    """extract_nav_window 가 position_consistency ChannelOutput 리스트를 반환해야 한다."""
    results = run_cycle_chain([(_raw_normal(0), _brief()), (_raw_normal(1), _brief())])
    window = extract_nav_window(results)
    assert isinstance(window, list)
    assert len(window) == 2
    for entry in window:
        assert entry["channel"] == "position_consistency"
        assert "state" in entry


def test_extract_link_window_empty_chain():
    """빈 chain → 빈 window."""
    assert extract_link_window([]) == []


def test_extract_nav_window_empty_chain():
    """빈 chain → 빈 window."""
    assert extract_nav_window([]) == []


def test_extract_link_window_length_matches_chain():
    """window 길이 == chain 길이 (1사이클 = 1 window 항목)."""
    n = 4
    pairs = [(_raw_normal(i), _brief()) for i in range(n)]
    results = run_cycle_chain(pairs)
    assert len(extract_link_window(results)) == n
    assert len(extract_nav_window(results)) == n


# ── 2. assess_link_loss — real pipeline 채널 출력 소비 ────────────────────────


def test_assess_link_loss_with_real_pipeline_normal():
    """정상 링크 3사이클 → CONTINUE 권고."""
    pairs = [(_raw_normal(i), _brief()) for i in range(3)]
    results = run_cycle_chain(pairs)
    window = extract_link_window(results)
    out = assess_link_loss(window)
    assert out["advisory_only"] is True
    assert out["assessable"] is True
    assert out["recommended_action"] == "CONTINUE"


def test_assess_link_loss_required_fields():
    """assess_link_loss 반환값 필수 필드 검증."""
    results = run_cycle_chain([(_raw_normal(0), _brief())])
    out = assess_link_loss(extract_link_window(results))
    for key in ("advisory_only", "assessable", "recommended_action", "current_state"):
        assert key in out, f"필수 필드 없음: {key}"


def test_assess_link_loss_no_mutation_scc1():
    """assess_link_loss 가 입력 window 를 변이하지 않아야 한다 (SCC-1)."""
    results = run_cycle_chain([(_raw_normal(i), _brief()) for i in range(3)])
    window = extract_link_window(results)
    snap = copy.deepcopy(window)
    assess_link_loss(window)
    assert window == snap


# ── 3. assess_nav_integrity — real pipeline 채널 출력 소비 ───────────────────


def test_assess_nav_integrity_with_real_pipeline_normal():
    """정상 항법 3사이클 → CONTINUE 권고."""
    pairs = [(_raw_normal(i), _brief()) for i in range(3)]
    results = run_cycle_chain(pairs)
    window = extract_nav_window(results)
    out = assess_nav_integrity(window)
    assert out["advisory_only"] is True
    assert out["assessable"] is True
    assert out["recommended_action"] == "CONTINUE"


def test_assess_nav_integrity_required_fields():
    """assess_nav_integrity 반환값 필수 필드 검증."""
    results = run_cycle_chain([(_raw_normal(0), _brief())])
    out = assess_nav_integrity(extract_nav_window(results))
    for key in ("advisory_only", "assessable", "recommended_action", "current_state"):
        assert key in out, f"필수 필드 없음: {key}"


def test_assess_nav_integrity_no_mutation_scc1():
    """assess_nav_integrity 가 입력 window 를 변이하지 않아야 한다 (SCC-1)."""
    results = run_cycle_chain([(_raw_normal(i), _brief()) for i in range(3)])
    window = extract_nav_window(results)
    snap = copy.deepcopy(window)
    assess_nav_integrity(window)
    assert window == snap


# ── 4. run_cycle_chain — link_loss · nav_integrity 배선 ─────────────────────


def test_chain_result_contains_link_loss_key():
    """run_cycle_chain 각 결과에 link_loss advisory 키가 있어야 한다."""
    pairs = [(_raw_normal(i), _brief()) for i in range(3)]
    results = run_cycle_chain(pairs)
    for i, r in enumerate(results):
        assert "link_loss" in r, f"cycle {i} 에 link_loss 키 없음"


def test_chain_result_contains_nav_integrity_key():
    """run_cycle_chain 각 결과에 nav_integrity advisory 키가 있어야 한다."""
    pairs = [(_raw_normal(i), _brief()) for i in range(3)]
    results = run_cycle_chain(pairs)
    for i, r in enumerate(results):
        assert "nav_integrity" in r, f"cycle {i} 에 nav_integrity 키 없음"


def test_chain_link_loss_advisory_only():
    """chain 결과 link_loss 는 advisory_only=True 이어야 한다 (SCC-1)."""
    results = run_cycle_chain([(_raw_normal(0), _brief())])
    assert results[0]["link_loss"]["advisory_only"] is True


def test_chain_nav_integrity_advisory_only():
    """chain 결과 nav_integrity 는 advisory_only=True 이어야 한다 (SCC-1)."""
    results = run_cycle_chain([(_raw_normal(0), _brief())])
    assert results[0]["nav_integrity"]["advisory_only"] is True


def test_chain_scc1_core_keys_unchanged():
    """link_loss/nav_integrity 배선 후 core 판정 키(risk/threat/response/flight_plan) 불변."""
    pairs = [(_raw_normal(i), _brief()) for i in range(2)]
    # chain 으로 실행
    chain = run_cycle_chain(pairs)
    # 단독 run_cycle 로 비교 (previous_qualities 수동 스레딩)
    from onboard.run import extract_qualities, extract_flight_plan_state
    r1_solo = run_cycle(_raw_normal(0), _brief())
    r2_solo = run_cycle(_raw_normal(1), _brief(), previous_qualities=extract_qualities(r1_solo),
                        previous_flight_plan_state=extract_flight_plan_state(r1_solo))
    for key in ("risk", "threat", "response", "flight_plan"):
        assert chain[0][key] == r1_solo[key], f"cycle 0 {key} 불일치"
        assert chain[1][key] == r2_solo[key], f"cycle 1 {key} 불일치"


def test_single_run_cycle_not_affected():
    """단일 run_cycle 결과에 link_loss/nav_integrity 키가 없어야 한다 (single-cycle 계약 불변)."""
    out = run_cycle(_raw_normal(0), _brief())
    assert "link_loss" not in out, "단일 run_cycle 에 link_loss 추가됨 — single-cycle 계약 위반"
    assert "nav_integrity" not in out, "단일 run_cycle 에 nav_integrity 추가됨 — single-cycle 계약 위반"


# ── 5. 에스컬레이션 시나리오 — 실 파이프라인 채널 출력 기반 ─────────────────────


def test_link_loss_hold_after_5_cycles():
    """5사이클 C2 두절(anomaly) → link_loss HOLD 권고 (두절 5s, 임계 3s 초과)."""
    pairs = [(_raw_link_lost(i), _brief()) for i in range(5)]
    results = run_cycle_chain(pairs)
    out = results[-1]["link_loss"]
    assert out["advisory_only"] is True
    assert out["recommended_action"] == "HOLD", f"5s 두절 → HOLD 예상, got {out['recommended_action']}"
    assert out["outage_seconds"] == pytest.approx(5.0, abs=0.1)


def test_link_loss_rtl_after_15_cycles():
    """15사이클 C2 두절 → link_loss RTL 권고 (두절 15s, 10s RTL 임계 초과)."""
    pairs = [(_raw_link_lost(i), _brief()) for i in range(15)]
    results = run_cycle_chain(pairs)
    out = results[-1]["link_loss"]
    assert out["recommended_action"] == "RTL", f"15s 두절 → RTL 예상, got {out['recommended_action']}"
    assert out["outage_seconds"] == pytest.approx(15.0, abs=0.1)


def test_link_loss_recovers_to_continue():
    """C2 두절 후 복구 → 마지막 사이클 CONTINUE."""
    pairs = (
        [(_raw_link_lost(i), _brief()) for i in range(5)]
        + [(_raw_normal(i + 5), _brief()) for i in range(3)]
    )
    results = run_cycle_chain(pairs)
    # 복구 후 마지막 사이클: 두절 스트릭 0 → CONTINUE
    out = results[-1]["link_loss"]
    assert out["recommended_action"] == "CONTINUE", f"복구 후 CONTINUE 예상, got {out['recommended_action']}"


def test_nav_integrity_rtl_after_10_cycles():
    """10사이클 GPS 무결성 상실 → nav_integrity RTL 권고 (10s, RTL 임계 8s 초과)."""
    pairs = [(_raw_nav_lost(i), _brief()) for i in range(10)]
    results = run_cycle_chain(pairs)
    out = results[-1]["nav_integrity"]
    assert out["advisory_only"] is True
    assert out["recommended_action"] == "RTL", f"10s nav 상실 → RTL 예상, got {out['recommended_action']}"
    assert out["untrusted_seconds"] == pytest.approx(10.0, abs=0.1)


def test_nav_integrity_recovers_to_continue():
    """GPS 무결성 상실 후 복구 → 마지막 사이클 CONTINUE."""
    pairs = (
        [(_raw_nav_lost(i), _brief()) for i in range(5)]
        + [(_raw_normal(i + 5), _brief()) for i in range(3)]
    )
    results = run_cycle_chain(pairs)
    out = results[-1]["nav_integrity"]
    assert out["recommended_action"] == "CONTINUE", f"복구 후 CONTINUE 예상, got {out['recommended_action']}"


def test_chain_link_loss_escalates_over_cycles():
    """사이클이 쌓일수록 두절 심각도가 단조 증가해야 한다 (CONTINUE→HOLD→RTL)."""
    _SEVERITY = {"CONTINUE": 0, "MONITOR": 1, "HOLD": 2, "DR_HOLD": 2, "RTL": 3, "LAND": 4}
    pairs = [(_raw_link_lost(i), _brief()) for i in range(20)]
    results = run_cycle_chain(pairs)
    severities = [_SEVERITY.get(r["link_loss"]["recommended_action"], -1) for r in results]
    # 전체 시퀀스가 단조 비감소여야 한다 (일단 악화되면 줄지 않음)
    for i in range(1, len(severities)):
        assert severities[i] >= severities[i - 1], (
            f"cycle {i}: severity 감소 ({severities[i-1]}→{severities[i]}) — 에스컬레이션 단조성 위반"
        )


# ── 5. 분할 스트림 resume — advisory 윈도우·interval seed (codex P2) ──────────


def test_split_stream_resume_preserves_outage_streak():
    """분할 이어붙이기(윈도우 seed)가 단일 호출과 동일 advisory 를 내야 한다."""
    brief = _brief()
    mono = run_cycle_chain([(_raw_link_lost(i), brief) for i in range(12)])
    b1 = run_cycle_chain([(_raw_link_lost(i), brief) for i in range(8)])
    b2 = run_cycle_chain(
        [(_raw_link_lost(i), brief) for i in range(8, 12)],
        previous_link_window=extract_link_window(b1),
        previous_nav_window=extract_nav_window(b1),
        previous_ts_ms=7 * 1000,
        previous_link_cycle_seconds=extract_link_cycle_seconds(b1),
        previous_nav_cycle_seconds=extract_nav_cycle_seconds(b1),
    )
    assert mono[-1]["link_loss"]["recommended_action"] == "RTL"  # 12s ≥ rtl 10s
    assert b2[-1]["link_loss"]["recommended_action"] == mono[-1]["link_loss"]["recommended_action"]
    assert b2[-1]["link_loss"]["outage_seconds"] == mono[-1]["link_loss"]["outage_seconds"]


def test_three_batch_resume_accumulates_window():
    """3개 배치: 윈도우 누적 seed 로 12 두절이 온전히 카운트돼 RTL."""
    brief = _brief()
    win: list = []
    secs: list = []
    last_ts = None
    last = None
    for start in (0, 4, 8):
        batch = [(_raw_link_lost(i), brief) for i in range(start, start + 4)]
        res = run_cycle_chain(
            batch,
            previous_link_window=win,
            previous_ts_ms=last_ts,
            previous_link_cycle_seconds=secs,
        )
        win = win + extract_link_window(res)
        secs = extract_link_cycle_seconds(res)
        last_ts = (start + 3) * 1000
        last = res[-1]
    assert last["link_loss"]["recommended_action"] == "RTL"


def test_split_stream_without_seed_undercounts():
    """대조군: 미seed 이어붙이면 스트릭 리셋 → 과소집계(RTL 아님)."""
    brief = _brief()
    b2 = run_cycle_chain([(_raw_link_lost(i), brief) for i in range(8, 12)])
    assert b2[-1]["link_loss"]["recommended_action"] != "RTL"


def test_cycle_interval_derived_from_ts_ms():
    """지속시간이 ts_ms cadence 에서 도출 — 10Hz 스트림은 1Hz 처럼 오발하지 않음."""
    brief = _brief()

    def _lost_at(seq, ts_ms):
        raw = build_normal_envelope("LL", seq, ts_ms)
        raw["c2_link"].update({"rssi_dbm": -98, "packet_loss_rate": 1.0, "latency_ms": 400})
        return raw

    pairs = [(_lost_at(i, i * 100), brief) for i in range(12)]  # 10Hz × 12 ≈ 1.1s
    last = run_cycle_chain(pairs)[-1]["link_loss"]
    assert last["recommended_action"] != "RTL"
    assert last["outage_seconds"] < 3.0


def test_chain_result_contains_failsafe_key():
    """run_cycle_chain 각 결과에 failsafe 통합 advisory 키가 있어야 한다 (#399)."""
    results = run_cycle_chain([(_raw_normal(i), _brief()) for i in range(2)])
    for r in results:
        assert "failsafe" in r and r["failsafe"]["advisory_only"] is True
