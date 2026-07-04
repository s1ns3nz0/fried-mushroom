"""nlp_model — 임베딩 기반 시맨틱 위협신호 분류 (ADR-002 스텁→실 NLP 모델, 2번째 실 ML).

키워드 룰(nlp_extract)은 정확 일치만 잡아 **동의어/의역**("적 스나이퍼", "무장 병력 다수")을
놓친다. 이 모델은 지시서 절(clause)을 임베딩해 위협 유형별 **프로토타입 문구**와 코사인유사도로
비교, 임계 이상이면 위협신호를 보강한다. sentence-transformers 는 **선택 의존** — 미가용 시
`classify_threat` 는 None(키워드 폴백, 하위호환).

부정(negation) 가드: "적 없음"류는 임베딩상 위협에 가까워도 신호를 내지 않는다(거짓양성 차단).
SCC-1(CLAUDE.md CRITICAL): GCS 운용자 **초안 보강**(사람 확인 대상)일 뿐 결정론 RAC/판정 무관.
Signal 계약(nlp_extract)과 동일한 dict 를 낸다.
"""

from __future__ import annotations

import re

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# 다국어 bi-encoder 는 baseline 유사도가 높게 압축됨(무관 절도 ~0.65). 실측상 실 위협은 0.83+,
# 무관("날씨 맑음 정상 비행")은 0.65 → 0.75 로 분리(거짓양성 차단).
_SIM_THRESHOLD = 0.75
# 위협 부재 부정만 가드 — 위협/적 명사 바로 뒤(≤8자)에 오는 부정어. "대공 엄호 **없이** 적
# 스나이퍼"처럼 위협 아닌 걸 부정하는 절은 발화시킨다(codex P2). "미상"(unknown)은 부정 아님.
_THREAT_NEGATION = re.compile(
    r"(적|병력|인원|위협|저격|스나이퍼|무장 인원|교란|재밍|사이버|전자전|해킹|공격)"
    r"[가-힣을를이가 ]{0,8}(없|부재|전무|아님)"
)

# 위협 유형별 프로토타입 문구 — 키워드 룰과 같은 의도의 다양한 표현.
_THREAT_PROTOTYPES: dict[str, tuple[str, ...]] = {
    "T3": ("적 저격수 조우", "무장한 적 인원", "소화기 사격 위협", "근접 무장 병력"),
    "T2": ("사이버 공격", "전자전 재밍", "통신 해킹", "GPS 전파 교란"),
}


_MODEL_CACHE: dict[str, object] = {}


def _load(model_name: str):
    # import·구성 모두 broad except — 미설치(ImportError)뿐 아니라 깨진 transitive
    # 의존(torch 손상 등)·가중치 다운로드 실패도 조용히 하향(assemble_draft crash 방지).
    # 성공분만 캐시 — 일시적 실패(다운로드 부재)가 프로세스 내내 굳지 않게(codex P2).
    if model_name in _MODEL_CACHE:
        return _MODEL_CACHE[model_name]
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name)
    except Exception:
        return None
    _MODEL_CACHE[model_name] = model
    return model


def model_available(model_name: str = DEFAULT_MODEL) -> bool:
    return _load(model_name) is not None


_PROTO_CACHE: dict[str, tuple[tuple[str, tuple[float, ...]], ...]] = {}


def _proto_vecs(model_name: str) -> tuple[tuple[str, tuple[float, ...]], ...] | None:
    """(threat_code, 정규화벡터) 목록 — 프로토타입은 1회만 임베딩. 성공분만 캐시(None 미캐시)."""
    if model_name in _PROTO_CACHE:
        return _PROTO_CACHE[model_name]
    model = _load(model_name)
    if model is None:
        return None  # 캐시하지 않음 — 일시적 미가용이 굳어지지 않게.
    out: list[tuple[str, tuple[float, ...]]] = []
    try:
        for code, phrases in _THREAT_PROTOTYPES.items():
            vecs = model.encode(list(phrases), normalize_embeddings=True)
            for v in vecs:
                out.append((code, tuple(float(x) for x in v)))
    except Exception:
        return None  # encode 실패(OOM/디바이스/캐시손상) → 하향(assemble_draft crash 방지, codex P2)
    result = tuple(out)
    _PROTO_CACHE[model_name] = result
    return result


def _embed(text: str, model_name: str) -> tuple[float, ...] | None:
    model = _load(model_name)
    if model is None:
        return None
    try:
        v = model.encode([text], normalize_embeddings=True)[0]
    except Exception:
        return None
    return tuple(float(x) for x in v)


# 쉼표/접속 구분자 — 한 절 안의 복합 사실을 세그먼트로 분리("적 없음, 교란 확인"처럼
# 부정 세그먼트가 뒤의 실 위협을 억누르지 않게, codex P2).
_SEGMENT_SPLIT = re.compile(r"[,、;·]|\s및\s|\s그리고\s")


def classify_threat(clause: str, model_name: str = DEFAULT_MODEL) -> tuple[str, float, str] | None:
    """절 → (threat_code, confidence, matched_segment) 또는 None.

    세그먼트별 부정 가드 후 비-부정 세그먼트만 임베딩, 최고 유사도 세그먼트를 채택.
    matched_segment 는 신호의 source_phrase 로 쓰여 절 전체보다 좁게 근거를 남긴다.
    """
    if not clause or not clause.strip():
        return None
    # 비-부정 세그먼트만 후보 — 전부 부정/빈 세그먼트면 모델 로드 없이 None(부정절 조기반환).
    candidates = [
        s.strip()
        for s in _SEGMENT_SPLIT.split(clause)
        if s.strip() and not _THREAT_NEGATION.search(s)
    ]
    if not candidates:
        return None
    protos = _proto_vecs(model_name)
    if protos is None:
        return None
    best_code, best_sim, best_seg = None, -1.0, ""
    for seg in candidates:
        cvec = _embed(seg, model_name)
        if cvec is None:
            continue
        for code, pvec in protos:
            sim = sum(a * b for a, b in zip(cvec, pvec))  # 정규화벡터 → 코사인 = 내적
            if sim > best_sim:
                best_code, best_sim, best_seg = code, sim, seg
    if best_code is None or best_sim < _SIM_THRESHOLD:
        return None
    # 유사도 [임계,1] → confidence [0.75, 0.95] 선형 (CONFIDENCE_FLOOR=0.7 통과 보장).
    conf = 0.75 + (best_sim - _SIM_THRESHOLD) / (1.0 - _SIM_THRESHOLD) * (0.95 - 0.75)
    return best_code, round(min(conf, 0.95), 4), best_seg
