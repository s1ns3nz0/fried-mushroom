"""코퍼스 라이프사이클 종단 통합 테스트 (#202).

episode 로그 → aggregate → CorpusStore 저장 → retrieve → advisory 리포트까지
모듈 경계 계약(필드 전달, pending 제외 전파, 멱등)을 실제 함수 체인으로 종단 검증한다.
conftest.py가 infra/log를 sys.path에 이미 얹어두므로 개별 sys.path 조작은 불필요.

- 계약 소스 오브 트루스: docs/RAG-corpus.md (episode 매핑, pending 제외, 회수 정렬)
- SCC-1: 이 파일은 shared/constants를 import하지 않는다. episode/record는 순수 dict로만 구성.
"""

from aggregate import (
    NARRATIVE_CONFIRMED,
    aggregate_threat_judgments,
    build_episode_index,
)
from corpus import CorpusStore, episode_to_corpus_records
from weight_advisor import build_advisory_report


def _raw_log(mission_id, threat_modeling_log):
    return {"mission_id": mission_id, "threat_modeling_log": threat_modeling_log}


def _confirm(episode, mission_context, posture, outcome, ts):
    """build_episode_index 산출(narrative_status=pending, mission_context 미집계)에
    운영자 승인 + 미구현 집계항목(outcome/mission_context/posture/ts)을 순수 dict로 보강한다.
    aggregate_outcome/aggregate_terrain_composition은 NotImplementedError 스텁이므로 호출하지 않는다.
    """
    episode = dict(episode)
    episode["mission_context"] = mission_context
    episode["posture"] = posture
    episode["outcome"] = outcome
    episode["ts"] = ts
    episode["narrative_status"] = NARRATIVE_CONFIRMED
    return episode


def test_lifecycle_end_to_end(tmp_path):
    # ── 1) 종단 파이프라인: raw_log → aggregate → episode → corpus_record ──────

    # ep_high: 최신 ts, 단일 위협(T7), outcome=mission_abort(실패)
    raw_high = _raw_log(
        "m-high",
        [{"ts": 10, "threat_event": "T7", "confidence": 0.75, "kill_chain_stage": "후기"}],
    )
    ep_high = build_episode_index(raw_high, "raw/m-high.json")
    assert ep_high["threat_judgments"] == aggregate_threat_judgments(
        raw_high["threat_modeling_log"]
    )
    ep_high = _confirm(
        ep_high, "정찰", {"watchcon": 3, "defcon": 3, "infocon": 4}, "mission_abort", ts=3000
    )

    # ep_mid: 두 위협(T3 초기->후기 발전, T5) 같은 episode-level ts → 회수 시 confidence 역순 검증
    raw_mid = _raw_log(
        "m-mid",
        [
            {"ts": 10, "threat_event": "T3", "confidence": 0.10, "kill_chain_stage": "초기"},
            {"ts": 20, "threat_event": "T3", "confidence": 0.30, "kill_chain_stage": "중기"},
            {"ts": 30, "threat_event": "T5", "confidence": 0.90, "kill_chain_stage": "초기"},
        ],
    )
    ep_mid = build_episode_index(raw_mid, "raw/m-mid.json")
    # 같은 threat_event(T3)의 최신 판정(ts=20, confidence=0.30)이 이겨야 한다(계약 §2-2/§3-1).
    t3_judgment = next(j for j in ep_mid["threat_judgments"] if j["threat_event"] == "T3")
    assert t3_judgment["confidence"] == 0.30
    ep_mid = _confirm(
        ep_mid, "정찰", {"watchcon": 3, "defcon": 3, "infocon": 4}, "rtb_success", ts=2000
    )

    # ep_low: 가장 오래된 ts, outcome=lost(실패)
    raw_low = _raw_log(
        "m-low",
        [{"ts": 10, "threat_event": "T1", "confidence": 0.50, "kill_chain_stage": "초기"}],
    )
    ep_low = build_episode_index(raw_low, "raw/m-low.json")
    ep_low = _confirm(
        ep_low, "정찰", {"watchcon": 3, "defcon": 3, "infocon": 4}, "lost", ts=1000
    )

    # ep_pending: narrative_status가 build_episode_index 기본값(pending)에서 승인되지 않은 채 남는다.
    # ts=2500(ep_high와 ep_mid 사이) + confidence=0.99(가장 높음) → 새어나오면 정렬 위치로 바로 들통난다.
    raw_pending = _raw_log(
        "m-pending",
        [{"ts": 10, "threat_event": "T9", "confidence": 0.99, "kill_chain_stage": "초기"}],
    )
    ep_pending = build_episode_index(raw_pending, "raw/m-pending.json")
    assert ep_pending["narrative_status"] == "pending"  # build_episode_index 기본값 확인
    ep_pending["mission_context"] = "정찰"
    ep_pending["posture"] = {"watchcon": 3, "defcon": 3, "infocon": 4}
    ep_pending["outcome"] = "rtb_success"
    ep_pending["ts"] = 2500
    # narrative_status는 승인되지 않았으므로 건드리지 않는다(그대로 "pending").

    store = CorpusStore(tmp_path / "corpus.db")
    try:
        for ep in (ep_high, ep_mid, ep_low, ep_pending):
            records = episode_to_corpus_records(ep)
            count = store.upsert_records(records)
            assert count == len(records)

        # ep_mid는 T3(1건, 최신 판정으로 병합됨) + T5(1건) = 2 레코드.
        assert len(episode_to_corpus_records(ep_mid)) == 2

        # ── 2) retrieve 종단 계약: pending 제외 + ts DESC, confidence DESC 정렬 ──

        all_confirmed = store.retrieve(mission_context="정찰", top_k=100)
        mission_ids = [r["mission_id"] for r in all_confirmed]

        # (a) pending 제외: m-pending(T9)은 ts/confidence 모두 두드러지지만 결과에 없어야 한다.
        assert "m-pending" not in mission_ids
        assert all(r["threat_event"] != "T9" for r in all_confirmed)
        assert store.retrieve(threat_event="T9") == []

        # (b) ts DESC 우선, 동일 ts(ep_mid의 T3/T5)는 confidence DESC.
        threat_events_in_order = [r["threat_event"] for r in all_confirmed]
        assert threat_events_in_order == ["T7", "T5", "T3", "T1"]
        assert mission_ids == ["m-high", "m-mid", "m-mid", "m-low"]

        # ── 3) 재집계 멱등: 동일 episode 2회 ingest → 레코드 수/회수 결과 불변 ──

        before_total = len(store.retrieve(top_k=100))
        replay_count = store.ingest_episode(ep_mid)
        assert replay_count == 2  # ingest_episode는 변환된 레코드 건수를 그대로 반환(신규 여부 무관)
        after_total = len(store.retrieve(top_k=100))
        assert after_total == before_total  # UNIQUE(mission_id, threat_event) upsert → 중복 없음

        t3_hits = store.retrieve(threat_event="T3")
        assert len(t3_hits) == 1
        assert t3_hits[0]["confidence"] == 0.30  # 재집계로 값이 바뀌지 않았음(같은 episode 재전송)

        # ── 4) advisory 연동: 저장 레코드 → build_advisory_report ──────────────

        report = build_advisory_report(all_confirmed, generated_ts=1751600000000)
        assert report["generated_ts"] == 1751600000000
        assert report["corpus_size"] == len(all_confirmed)
        assert report["guardrails"]["advisory_only"] is True
        assert report["guardrails"]["applied"] is False
        assert report["channel_weight_proposals"] == []  # advisory-only, 상수 미변경

        calibration = report["confidence_calibration"]
        # outcome이 성공/실패로 분류 가능한 threat_event만 등장(모든 confirmed 레코드가 해당).
        assert {row["threat_event"] for row in calibration} == {"T7", "T5", "T3", "T1"}
        for row in calibration:
            assert set(row.keys()) == {
                "threat_event", "n", "mean_confidence", "hit_rate",
                "calib_error", "low_sample", "note",
            }
            assert row["n"] == 1
            assert row["low_sample"] is True  # n=1 < _LOW_SAMPLE_N
    finally:
        store.close()
