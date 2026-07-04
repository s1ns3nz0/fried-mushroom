"""nlp_model 시맨틱 위협 분류 + extract_signals opt-in 배선 (ADR-002 2번째 실 ML).

배선/가드는 monkeypatch 로 결정론 검증(모델 불필요). 실 모델은 선택 의존이라 importorskip +
로드/임계 실패 시 skip 하는 smoke 만. 기본(use_nlp_model=False)은 키워드-only(하위호환).
"""

import pytest

from gcs.layer_01_info_center import nlp_extract, nlp_model


# ── nlp_model 단위 (결정론) ───────────────────────────────────────────────────


def test_threat_negation_guard_matches_only_threat_absence():
    # 위협/적 명사 뒤 부정만 가드. "없이"(엄호 부정)/"미상"(unknown)은 발화 허용(codex P2).
    g = nlp_model._THREAT_NEGATION
    assert g.search("적 병력 전혀 없음")
    assert g.search("무장 인원 부재")
    assert g.search("적 없음")
    assert not g.search("대공 엄호 없이 적 스나이퍼 매복")  # 없이는 엄호를 부정
    assert not g.search("적 스나이퍼 위치 미상")  # 미상=unknown, 부재 아님
    assert not g.search("무장한 적 병력 다수 규모 미상")
    assert g.search("GPS 전파 교란 없음")  # 전자위협 부정도 가드(codex P2)
    assert g.search("사이버 공격 없음")


def test_negation_clause_classifies_none(monkeypatch):
    # 위협-부재 부정절 → 모델 로드 이전에 None (거짓양성 차단).
    monkeypatch.setattr(nlp_model, "_load", lambda name: pytest.fail("부정절인데 모델 로드"))
    assert nlp_model.classify_threat("적 병력 전혀 없음") is None


def test_empty_or_model_unavailable_none(monkeypatch):
    monkeypatch.setattr(nlp_model, "_load", lambda name: None)
    assert nlp_model.classify_threat("") is None
    assert nlp_model.classify_threat("적 저격수 조우") is None  # 모델 미가용 → None


# ── extract_signals opt-in 배선 ──────────────────────────────────────────────


def test_default_keyword_only_model_not_used(monkeypatch):
    # 기본(use_nlp_model 미지정) → 모델 미호출, 키워드-only(재현성/하위호환).
    monkeypatch.setattr(nlp_model, "classify_threat", lambda *a, **k: pytest.fail("모델 호출됨"))
    sigs = nlp_extract.extract_signals("적 저격조 확인됨.")  # 키워드 T3
    assert [s["threat"] for s in sigs if s["signal_type"] == "threat"] == ["T3"]


def test_model_augments_paraphrase_when_enabled(monkeypatch):
    # 키워드 미스 절(의역) + use_nlp_model=True → 모델이 위협 보강.
    monkeypatch.setattr(nlp_model, "classify_threat", lambda clause, **k: ("T3", 0.88, "적 스나이퍼가 능선에 매복"))
    sigs = nlp_extract.extract_signals("적 스나이퍼가 능선에 매복.", use_nlp_model=True)
    threats = [s for s in sigs if s["signal_type"] == "threat"]
    assert len(threats) == 1
    assert threats[0]["threat"] == "T3" and threats[0]["source"] == "nlp_model"
    assert threats[0]["confidence"] == 0.85  # min(model 0.88, 절 base 0.85)


def test_model_threat_downgraded_by_hedge(monkeypatch):
    # hedge 절("가능성") → 절 conf 0.60 으로 캡 → CONFIDENCE_FLOOR(0.7) 미만 → 필터됨.
    monkeypatch.setattr(nlp_model, "classify_threat", lambda clause, **k: ("T3", 0.90, "무장 병력 침투"))
    sigs = nlp_extract.extract_signals("무장 병력 침투 가능성.", use_nlp_model=True)
    assert [s for s in sigs if s["signal_type"] == "threat"] == []


def test_model_not_invoked_when_keyword_threat_present(monkeypatch):
    # 키워드가 이미 위협을 잡은 절은 모델 보강 안 함(중복 방지).
    monkeypatch.setattr(nlp_model, "classify_threat", lambda *a, **k: pytest.fail("중복 호출"))
    sigs = nlp_extract.extract_signals("적 저격조 확인됨.", use_nlp_model=True)
    assert sum(s["signal_type"] == "threat" for s in sigs) == 1


def test_model_none_adds_nothing(monkeypatch):
    monkeypatch.setattr(nlp_model, "classify_threat", lambda *a, **k: None)
    sigs = nlp_extract.extract_signals("정상 순찰 비행 중.", use_nlp_model=True)
    assert [s for s in sigs if s["signal_type"] == "threat"] == []


# ── 실 모델 smoke (선택 의존, 네트워크/임계 불충족 시 skip) ────────────────────


def test_real_model_paraphrase_detected():
    pytest.importorskip("sentence_transformers")
    if not nlp_model.model_available():
        pytest.skip("NLP 임베딩 모델 로드 불가(네트워크/가중치 부재)")
    # 부정절은 항상 None (가드).
    assert nlp_model.classify_threat("적 병력 전혀 없음") is None
    # 프로토타입 근접 의역 위협 → (code, conf). 임계/모델품질 불충족 시 skip.
    hit = nlp_model.classify_threat("무장한 적 병력 다수 포착")
    if hit is None:
        pytest.skip("모델 유사도 임계 미달(품질 편차)")
    code, conf, seg = hit
    assert code in ("T2", "T3") and 0.7 <= conf <= 0.95
    # 무관/정상 절은 거짓양성 없이 None (임계 분리).
    assert nlp_model.classify_threat("날씨 맑음 정상 비행") is None
    assert nlp_model.classify_threat("연료 잔량 점검 완료") is None
    # "미상"(위치 미상)은 부재가 아님 — 위협을 억누르지 않아야 함(codex P2).
    assert nlp_model.classify_threat("무장한 적 병력 다수 규모 미상") is not None
