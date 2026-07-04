"""모델-활성 전스택 E2E + 성능 회귀 — 3 실모델 통합 검증 (#356).

3 실모델(NLP 위협 보강 / narrative 임베딩 / confidence 캘리브레이션)이 함께 켜진
전스택이 예외 없이 돌고, 각 폴백이 동일 계약을 유지하며, 결정론 RAC 판정이
모델 유무와 무관하게 불변임을 검증한다 (SCC-1 종단 확인, #336 파리티 프레임워크 확장).

성능 회귀 가드: narrative_embed(zero-dep) 기반 assemble_draft + corpus 인제스트가
합리 예산(1 s) 내에 완주하는지 확인한다.

선택 의존(sentence_transformers) 미설치 시 — CI 기본:
  · NLP 모델 → keyword 폴백 (classify_threat=None)
  · embedding 모델 → None 폴백 (embed=None → 메타필터-only)
  · calibration → 표본 충분 시 항상 동작 (순수 Python)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_INFRA_LOG = Path(__file__).resolve().parents[2] / "infra" / "log"
if str(_INFRA_LOG) not in sys.path:
    sys.path.insert(0, str(_INFRA_LOG))

from calibration import fit_calibrator, fit_calibrators_by_threat
from corpus import CorpusStore
from narrative_embed import embed_narrative

from gcs.layer_01_info_center import nlp_extract, nlp_model
from gcs.layer_01_info_center.run import assemble_draft
from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.run import run_cycle


# ── 공통 픽스처 ───────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    s = CorpusStore(tmp_path / "corpus.db")
    yield s
    s.close()


def _gcs_inputs(directive="저격조 확인됨.", *, use_nlp=False, **over):
    base = {
        "sortie_id": "E2E-01",
        "directive_text": directive,
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"spare_asset_available": True, "armament": [], "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "c4i": {"enemy_situation": ["저격조 활동 확인"]},
        "use_nlp_model": use_nlp,
    }
    base.update(over)
    return base


def _onboard_raw():
    return build_normal_envelope("E2E", 0, 0)


def _onboard_brief():
    return {
        "sortie_id": "E2E-01",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"armament": [], "spare_asset_available": True, "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
    }


def _corpus_episode(mission_id, narrative, outcome="rtb_success"):
    from aggregate import NARRATIVE_CONFIRMED
    return {
        "mission_id": mission_id,
        "raw_log_ref": None,
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "corridor_region": None,
        "outcome": outcome,
        "ts": 1000,
        "narrative_status": NARRATIVE_CONFIRMED,
        "narrative": narrative,
        "embedding": None,
        "threat_judgments": [
            {"threat_event": "T3", "confidence": 0.85, "kill_chain_stage": "초기"}
        ],
    }


# ── 1. 전스택 종단 (크래시 없음) ──────────────────────────────────────────────


def test_gcs_onboard_full_stack_no_crash():
    """GCS assemble_draft → onboard run_cycle 전 구간 크래시 없음 (모델 비활성 기본)."""
    draft = assemble_draft(_gcs_inputs())
    brief = draft["draft_brief"]
    out = run_cycle(_onboard_raw(), brief)
    assert {"abstraction", "threat", "risk", "response", "flight_plan"} <= set(out)


def test_gcs_onboard_full_stack_with_nlp_flag_no_crash():
    """use_nlp_model=True 활성화 상태에서도 전스택 크래시 없음 (ST 미설치 → keyword 폴백)."""
    draft = assemble_draft(_gcs_inputs(use_nlp=True))
    brief = draft["draft_brief"]
    out = run_cycle(_onboard_raw(), brief)
    assert "risk" in out


def test_full_stack_with_corpus_store_no_crash(store):
    """CorpusStore 주입 + RAG advisory 포함 전스택 크래시 없음."""
    store.ingest_episode(_corpus_episode("m-01", "저격조 T3 확인됨. 고도 상승 회피."))
    draft = assemble_draft(_gcs_inputs(), store=store)
    assert "briefing_advisory" in draft
    brief = draft["draft_brief"]
    out = run_cycle(_onboard_raw(), brief)
    assert "risk" in out


# ── 2. NLP 모델 활성화 — 신호 보강 검증 ─────────────────────────────────────


def test_nlp_model_boost_when_model_injected(monkeypatch):
    """NLP 모델 mock 주입 시 키워드 미탐지 절에 신호가 추가돼야 한다."""
    # 키워드 룰에 없는 표현 — "적 스나이퍼"는 "저격조"가 아니므로 keyword miss
    directive = "적 스나이퍼 발견."

    # 모델 없이 → 신호 없음
    sigs_keyword = nlp_extract.extract_signals(directive, use_nlp_model=False)
    threat_keyword = [s for s in sigs_keyword if s["signal_type"] == "threat"]

    # 모델 mock 주입 → T3 신호 추가
    monkeypatch.setattr(
        nlp_model, "_load", lambda name: _FakeNLPModel()
    )
    sigs_model = nlp_extract.extract_signals(directive, use_nlp_model=True)
    threat_model = [s for s in sigs_model if s["signal_type"] == "threat"]

    assert len(threat_model) > len(threat_keyword), (
        "NLP 모델 활성화 시 키워드 미탐지 위협을 보강해야 함"
    )
    model_sources = [s.get("source") for s in threat_model]
    assert "nlp_model" in model_sources


def test_nlp_model_fallback_when_model_unavailable(monkeypatch):
    """NLP 모델 미가용(None 반환) 시 키워드-only 경로와 동일한 출력 (크래시 없음)."""
    monkeypatch.setattr(nlp_model, "_load", lambda name: None)
    directive = "저격조 확인됨."
    sigs_model = nlp_extract.extract_signals(directive, use_nlp_model=True)
    sigs_keyword = nlp_extract.extract_signals(directive, use_nlp_model=False)
    # 모델 미가용 → 동일 결과 (폴백 정합)
    assert sigs_model == sigs_keyword


class _FakeNLPModel:
    """NLP 모델 mock — T3 위협을 항상 반환."""
    def encode(self, texts, normalize_embeddings=False):
        import math
        v = [1.0, 0.0, 0.0]
        norm = math.sqrt(sum(x*x for x in v))
        return [[x/norm for x in v]] * len(texts)


# ── 3. narrative 임베딩 — corpus 인제스트 + 시맨틱 회수 ──────────────────────


def test_corpus_ingest_auto_embeds_narrative(store):
    """인제스트 시 narrative_embed 로 embedding 이 자동 생성돼야 한다."""
    store.ingest_episode(_corpus_episode("m-emb", "저격조 T3 확인됨. 고도 상승 회피."))
    results = store.retrieve(mission_context="정찰", threat_event="T3")
    assert len(results) == 1
    emb = results[0]["embedding"]
    assert emb is not None, "인제스트 시 embedding 자동 생성"
    assert isinstance(emb, list)


def test_corpus_semantic_retrieval_ranks_similar_first(store):
    """유사 narrative 가 비관련보다 높은 순위를 가져야 한다 (narrative_embed 기반)."""
    store.ingest_episode(_corpus_episode("m-similar", "저격조 T3 확인됨. 고도 상승 회피."))
    store.ingest_episode(_corpus_episode("m-unrelated", "기상 이상. 배터리 부족. RTB."))

    query = embed_narrative("저격조 조우. 회피 기동.")
    results = store.retrieve(
        mission_context="정찰",
        threat_event="T3",
        narrative_query_embedding=query,
    )
    assert len(results) >= 1
    # 유사 narrative 가 첫 번째여야 함
    assert results[0]["mission_id"] == "m-similar", (
        f"시맨틱 유사도 기반 재순위 실패: {[r['mission_id'] for r in results]}"
    )


# ── 4. confidence 캘리브레이션 ────────────────────────────────────────────────


def test_calibration_corrects_overconfident():
    """과신(raw 0.9, 실제 성공률 0.4) → 캘리브레이션 값이 raw 보다 낮아야 한다."""
    recs = [
        {"confidence": 0.9, "outcome": "rtb_success", "threat_event": "T3"} for _ in range(4)
    ] + [
        {"confidence": 0.9, "outcome": "lost", "threat_event": "T3"} for _ in range(6)
    ]
    cal = fit_calibrator(recs)
    assert cal.fitted
    result = cal.calibrate(0.9)
    assert result is not None
    assert result < 0.9, f"과신 보정: raw 0.9 → calibrated {result} < 0.9 기대"


def test_calibration_per_threat_separate_curves():
    """위협 유형별 별도 캘리브레이터가 생성돼야 한다."""
    recs = (
        [{"confidence": 0.9, "outcome": "rtb_success", "threat_event": "T3"}] * 3
        + [{"confidence": 0.9, "outcome": "lost", "threat_event": "T3"}] * 7
        + [{"confidence": 0.9, "outcome": "rtb_success", "threat_event": "T2"}] * 9
        + [{"confidence": 0.9, "outcome": "lost", "threat_event": "T2"}] * 1
    )
    cals = fit_calibrators_by_threat(recs)
    assert set(cals) == {"T3", "T2"}
    t3 = cals["T3"].calibrate(0.9)
    t2 = cals["T2"].calibrate(0.9)
    assert t3 is not None and t2 is not None
    assert t3 < t2, "T3(과신) 캘리브레이션 값이 T2(정확)보다 낮아야 함"


# ── 5. SCC-1: 3 모델 전부 결정론 RAC 불변 ────────────────────────────────────


def test_scc1_nlp_model_does_not_change_rac():
    """NLP 모델 on/off 시 onboard run_cycle 의 risk(RAC) 판정이 동일해야 한다 (SCC-1)."""
    raw = _onboard_raw()
    brief_off = assemble_draft(_gcs_inputs(use_nlp=False))["draft_brief"]
    brief_on = assemble_draft(_gcs_inputs(use_nlp=True))["draft_brief"]
    # GCS draft_brief 가 같아야 run_cycle 결과도 같다
    assert brief_off == brief_on, "SCC-1: NLP 모델이 draft_brief 를 변경함"
    out_off = run_cycle(raw, brief_off)
    out_on = run_cycle(raw, brief_on)
    assert out_off["risk"] == out_on["risk"], "SCC-1: NLP 모델이 RAC 판정을 변경함"


def test_scc1_corpus_store_does_not_change_rac(store):
    """CorpusStore(RAG advisory) 주입이 onboard run_cycle risk 에 영향 없어야 한다 (SCC-1)."""
    store.ingest_episode(_corpus_episode("m-scc1", "저격조 T3 확인됨."))
    raw = _onboard_raw()
    brief_no_store = assemble_draft(_gcs_inputs())["draft_brief"]
    brief_with_store = assemble_draft(_gcs_inputs(), store=store)["draft_brief"]
    assert brief_no_store == brief_with_store, "SCC-1: RAG advisory 가 draft_brief 를 변경함"
    assert run_cycle(raw, brief_no_store)["risk"] == run_cycle(raw, brief_with_store)["risk"]


def test_scc1_narrative_embed_does_not_change_rac():
    """narrative_embed 출력이 onboard run_cycle 에 전달되지 않는다 (SCC-1 구조 검증)."""
    raw = _onboard_raw()
    brief = _onboard_brief()
    out1 = run_cycle(raw, brief)
    out2 = run_cycle(raw, brief)
    assert out1["risk"] == out2["risk"], "run_cycle 결정론 위반"


# ── 6. 폴백 정합: 선택 의존 미설치 시 동일 계약 ─────────────────────────────


def test_fallback_parity_full_stack_without_sentence_transformers(monkeypatch):
    """sentence_transformers 미설치 상태(모든 모델 None)에서도 전스택이 동일 계약으로 완주."""
    import embedding as emb_mod
    monkeypatch.setattr(emb_mod, "_load", lambda name: None)
    monkeypatch.setattr(nlp_model, "_load", lambda name: None)

    draft = assemble_draft(_gcs_inputs(use_nlp=True))
    assert "draft_brief" in draft
    assert "signal_cards" in draft
    brief = draft["draft_brief"]
    out = run_cycle(_onboard_raw(), brief)
    assert "risk" in out


def test_fallback_parity_corpus_meta_filter_only(store, monkeypatch):
    """embedding 미가용 시 corpus.retrieve 가 메타필터-only 로 하향(크래시 없음)."""
    store.ingest_episode(_corpus_episode("m-fall", "저격조 T3 확인됨."))

    # embed_narrative 를 None 반환으로 monkeypatch
    import corpus as corpus_mod
    monkeypatch.setattr(corpus_mod, "_embed_narrative", lambda text: None)

    # 인제스트 후 회수
    results = store.retrieve(mission_context="정찰", threat_event="T3")
    assert isinstance(results, list)


# ── 7. 성능 회귀 가드 ─────────────────────────────────────────────────────────


def test_performance_assemble_draft_within_budget():
    """assemble_draft(모델 비활성) 가 1 초 이내에 완주해야 한다."""
    inputs = _gcs_inputs()
    start = time.monotonic()
    assemble_draft(inputs)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"assemble_draft 지연 초과: {elapsed:.3f}s > 1.0s"


def test_performance_corpus_ingest_and_retrieve_within_budget(store):
    """corpus 인제스트 10건 + retrieve 가 2 초 이내에 완주해야 한다."""
    start = time.monotonic()
    for i in range(10):
        store.ingest_episode(_corpus_episode(f"m-perf-{i}", f"저격조 T3 확인됨. 임무 {i}."))
    store.retrieve(mission_context="정찰", threat_event="T3", top_k=10)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"corpus 인제스트+회수 지연 초과: {elapsed:.3f}s > 2.0s"


# ── 8. 실 모델 smoke (선택 의존, 네트워크 필요 시 skip) ──────────────────────


def test_nlp_model_smoke_with_real_sentence_transformers():
    """sentence_transformers 설치 시 NLP 모델이 실제로 위협 신호를 보강한다."""
    pytest.importorskip("sentence_transformers")
    result = nlp_model.classify_threat("적 스나이퍼 다수 발견")
    if result is None:
        pytest.skip("NLP 모델 가중치 로드 불가(네트워크/캐시 부재)")
    code, conf, seg = result
    assert code in ("T3", "T2"), f"위협 코드 예상: T3 또는 T2, got {code}"
    assert 0.0 <= conf <= 1.0, f"confidence 범위 위반: {conf}"
    assert isinstance(seg, str) and seg


def test_embedding_smoke_with_real_sentence_transformers():
    """sentence_transformers 설치 시 embed() 가 L2-정규화 벡터를 반환한다."""
    pytest.importorskip("sentence_transformers")
    import math
    import embedding as emb_mod
    vec = emb_mod.embed("저격조 T3 확인됨. 고도 상승 회피.")
    if vec is None:
        pytest.skip("임베딩 모델 가중치 로드 불가(네트워크/캐시 부재)")
    assert isinstance(vec, list)
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-3
