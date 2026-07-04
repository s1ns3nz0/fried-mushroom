# GCS Layer 01 — 유사사례 참고 카드 배선 (설계)

날짜: 2026-07-04 · 범위: `src/gcs/layer_01_info_center/` + `infra/log/log_server.py` 연동
배경: `2026-07-04-gcs-layer01-architecture-review.md` 세션에서 이어진 grill-me. "지상통제센터 AI가 과거 UAV 임무 데이터를 학습해 다음 운항에 활용할 수 있는가"라는 질문에서 출발.

## 1. 목적

`docs/RAG-corpus.md`(1~3라운드) + `infra/log/weight_advisor.py`(캘리브레이션 advisory)로 이미 구현된 학습 코퍼스(스키마·저장·회수)가 실제로는 어디서도 소비되지 않고 있었다(`grep CorpusStore src/gcs` 0건, `log_server.py`에 corpus 관련 엔드포인트 0건). 이번 설계는 **새 인프라 없이 기존 `CorpusStore.retrieve()` 계약만 배선**해, 운용자가 신호 카드를 검토할 때 "이 위협 신호와 비슷한 과거 사례에서 confidence·실제 결과가 어땠는지"를 참고할 수 있게 한다.

**원칙 계승**: `01` 문서 ⑥ "임무가 끝난 뒤 실제로 무슨 일이 있었는지는 학습 파이프라인으로 흘러가 다음 임무 때 NLP가 confidence를 판단하는 데 참고자료로 쓰인다." — 어디까지나 **참고자료**다. 과거 사례가 현재 신호의 confidence를 자동으로 바꾸지 않는다(cross_check의 결정론 조정 로직은 무변). 운용자가 카드를 읽고 판단에 참고하는 것까지만.

## 2. 조회 위치와 순수성 (grill-me 결정)

`assemble_draft()`는 순수 함수(`ts_ms` 유즈사이트 주입 원칙과 동형 — 파이프라인 안에서 시간·DB 조회 금지). `CorpusStore.retrieve()`는 SQLite I/O이므로 `assemble_draft` 내부에서 직접 호출하지 않는다. 또한 `src/gcs`(결정 레이어)가 `infra/log`(배포 인프라)를 import하는 것은 현재 `log_server.py`가 `gcs.layer_01_info_center.run`을 import하는 의존 방향과 반대로 꼬인다.

**결정**: 호출측(`infra/log/log_server.py`의 `/gcs/assemble` 핸들러, 이미 async I/O 컨텍스트)이 `CorpusStore.retrieve()`를 먼저 호출하고, 결과를 `assemble_draft(inputs)`의 `inputs["similar_cases"]`로 주입한다. `src/gcs` 패키지는 `infra.log`를 전혀 모른다 — `similar_cases`는 그냥 dict 리스트로 받는다(레이어 계약과 동일 패턴: JSON 직렬화 가능한 값만 경계를 넘는다).

## 3. 조회 시점 문제 — threat_event 닭-달걀 (grill-me 결정)

`retrieve()`는 `threat_event`를 필터로 받지만, 후보 threat_event는 `nlp_extract`가 지시서를 읽어야 나온다 — `assemble_draft` **내부**에서. `log_server`가 `assemble_draft` 호출 **전에** 미리 조회해야 하므로 이 시점에 threat_event 후보를 알 수 없다.

**결정**: `threat_event=None`으로 조회해 해당 `(mission_context, posture)` 조합의 **모든** 위협 코드에 대한 과거 레코드 부분집합을 한 번에 가져온다. `assemble_draft` 내부(카드 빌더)가 각 신호의 `threat` 값과 일치하는 레코드만 걸러 카드에 붙인다. 조회는 1회로 끝난다.

```python
# log_server.py, /gcs/assemble 핸들러 내부, assemble_draft 호출 전
store = CorpusStore(DB_PATH)
similar_cases = store.retrieve(
    mission_context=set_mission.get("mission_context"),
    posture=set_mission.get("posture"),
    posture_tolerance=POSTURE_TOLERANCE,  # 설정값, 기본 1
    threat_event=None,
    top_k=CORPUS_TOP_K,  # 설정값, 기본 50 — 카드별 필터링 여유를 위해 signal_cards top_k보다 넉넉히
)
draft = assemble_draft({**set_mission, "similar_cases": similar_cases})
```

`CorpusStore`/DB 파일이 없거나 조회 실패 시 `similar_cases=[]`로 폴백(경고 로그만, 조립은 계속 진행 — 기존 c4i 부재 처리와 동일한 graceful degradation 패턴).

## 4. 카드 데이터 모양 — 원본 레코드 노출 (집계·분류 로직 미추가)

`weight_advisor.py`는 이미 outcome을 성공/실패로 분류해 캘리브레이션(과신/과소) 통계를 낸다. 이 분류 로직(`_SUCCESS_OUTCOMES`/`_FAILURE_OUTCOMES`)을 `src/gcs`가 다시 구현하거나 import하면 (a) infra→gcs 역의존 반복, (b) 두 곳에 분류 기준이 중복돼 드리프트 위험이 생긴다.

**결정**: `run.py`의 `_card()`가 **원본 레코드를 그대로** 몇 건 붙인다 — 집계·성공률 계산 없이. 판단은 운용자가 직접 한다(AI는 후보만 원칙의 연장).

```python
def _similar_cases_for(sig: dict, similar_cases: list[dict], limit: int = 3) -> list[dict]:
    """신호의 threat 값과 일치하는 과거 코퍼스 레코드 최근 N건 (ts 내림차순, retrieve()가 이미 정렬)."""
    threat = sig.get("threat")
    if not threat:
        return []
    matches = [c for c in similar_cases if c.get("threat_event") == threat]
    return [
        {"mission_id": c["mission_id"], "confidence": c.get("confidence"),
         "outcome": c.get("outcome"), "corridor_region": c.get("corridor_region"), "ts": c.get("ts")}
        for c in matches[:limit]
    ]
```

`_card()` 반환에 `"similar_past_cases": _similar_cases_for(sig, inputs.get("similar_cases", []))` 필드를 추가한다. 신호에 `threat` 키가 없는 타입(logistics/civil/mission_purpose)은 빈 리스트.

## 5. 테스트 (TDD)

- `_similar_cases_for`: threat 일치 필터링, limit 적용, 빈 similar_cases 입력 시 `[]`.
- `assemble_draft`: `inputs["similar_cases"]` 없어도(생략 시) 기존 동작 무변(하위호환 — 기본값 `[]`).
- `run.py` 기존 테스트(`test_run.py`, `test_run_round2.py`) 전부 회귀 무변.
- **통합(킬러)**: corpus에 미리 넣어둔 골든 레코드(`(mission_context, posture, threat_event)` 일치) → `assemble_draft` 호출 시 해당 신호 카드에 `similar_past_cases` non-empty로 나타남.
- `log_server.py` 신규: `/gcs/assemble`이 DB 없음/조회 실패 시에도 503이 아니라 `similar_cases=[]`로 정상 응답(graceful).

## 6. 범위 밖

- confidence 자동 재조정(캘리브레이션 결과를 cross_check에 피드백하는 것) — SCC-1 위반, 금지.
- `CHANNEL_WEIGHTS`/`RAC_MATRIX` 등 상수 자동 갱신 — `docs/RAG-corpus.md` §7과 동일하게 범위 밖.
- narrative 임베딩 기반 벡터 재순위 활용 — 이번 라운드는 메타필터(mission_context/posture) 결과만 사용, 라운드 3의 벡터 하이브리드는 다음 라운드 후보.
- `weight_advisor` 리포트의 대시보드 노출 — 별건(이전 grill-me 세션에서 2순위로 미룸).
