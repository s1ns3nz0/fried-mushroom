# RAG 코퍼스 — episode → 학습레코드 스키마 · 회수 계약 (라운드 1)

> **범위(라운드 1)**: raw_log → episode_index 집계 위에 얹는 **RAG 코퍼스 축적**의
> ① 코퍼스 스키마(episode → 학습레코드 매핑) ② episode → 코퍼스 변환기 + 저장
> ③ 회수(retrieval) 계약 초안 을 정의한다. **doc-first** — 이 문서가 코드(`infra/log/corpus.py`,
> `infra/log/schema.sql` corpus 테이블)의 소스 오브 트루스다.
>
> RAG 코퍼스 축적은 PRD "MVP 제외 사항"이다(`docs/PRD.md` §MVP 제외 — "RAG 코퍼스 축적 및
> CHANNEL_WEIGHTS 재학습"). 이 라운드는 그 킥오프이며, MVP 온보드 파이프라인(`src/onboard/`)은
> 일절 건드리지 않는다(infra/log + docs 전용).

## 1. 배경 — 왜 코퍼스인가

`docs/D4D/01. 지상 정보 센터 AI.md` ⑥ 임무 브리핑 확정 절 말미:

> 임무가 끝난 뒤 실제로 무슨 일이 있었는지는 별도의 학습 파이프라인(RAG 코퍼스 축적)으로
> 흘러가서, **다음 임무 때 NLP가 확신도(confidence)를 판단하는 데 참고자료로** 쓰입니다.

즉 코퍼스의 소비 시나리오는 **"다음 임무 브리핑 시, 지금 상황(임무유형·경계태세·후보 위협)과 닮은
과거 사례에서 NLP가 어떤 confidence를 줬고 실제 outcome이 무엇이었는지"** 를 조회하는 것이다.
이 문서는 그 조회(회수)를 가능케 하는 **학습레코드 스키마 + 회수 계약**을 정의한다.

## 2. 소스 — episode(집계 산출) 구조

코퍼스 학습레코드는 무(無)에서 만들지 않는다. 기존 2계층 파이프의 산출을 조인한다
(`infra/log/README.md`, `collector.py`, `aggregate.py`, `store.py` 참조).

### 2-1. raw_log (무손실 원본, `collector.RAW_LOG_KEYS`)

| 키 | 형태 |
|---|---|
| `mission_id` | str |
| `gps_track` | `[{ts, lat, lon, terrain_class}]` |
| `aircraft_state_series` | `[{ts, battery_pct, attitude{roll,pitch,yaw}, speed_mps}]` |
| `threat_modeling_log` | `[{ts, threat_event, confidence, kill_chain_stage}]` ← **판정 confidence 원천** |
| `risk_assessment_log` | `[{ts, l_class, severity, rac}]` |

### 2-2. episode_index (검색 인덱스, `aggregate.build_episode_index` / `schema.sql`)

| 필드 | 형태 | 비고 |
|---|---|---|
| `mission_id` | str | PK |
| `raw_log_ref` | str | raw_log 파일 포인터 |
| `corridor_region` | str | 회랑 지역 코드 (예: `KR-hill-07`) |
| `threat_events` | JSON 배열 | 예: `["T3","T1"]` (등장 위협 유니크) |
| `outcome` | str | 임무 결과 (예: `rtb_success`) ← **실제 outcome 원천** |
| `terrain_composition` | JSON 객체 | |
| `narrative` / `narrative_status` | str | pending / human_confirmed |

### 2-3. mission_brief (임무 시작 확정, `src/onboard/shared/schemas.py:MissionBrief`)

| 필드 | 형태 | 비고 |
|---|---|---|
| `mission_context` | `"정찰"｜"타격"｜"호송"｜"수송"` | ← **mission_context 원천** |
| `posture` | dict `{watchcon, defcon, infocon}` | ← **posture 원천** |

## 3. 코퍼스 학습레코드 스키마

한 임무(episode)는 **위협 판정(threat judgment) 하나당 학습레코드 하나**로 펼쳐진다.
회수 키가 `(mission_context, posture, threat_event)` 이고 confidence·outcome이 위협별로
의미를 갖기 때문이다. 위협 판정이 없는 episode는 학습레코드를 만들지 않는다(회수 대상 아님).

| 필드 | 타입 | 필수 | 출처(provenance) | 설명 |
|---|---|:---:|---|---|
| `mission_id` | TEXT | ✅ | episode_index.mission_id | 임무 식별자 |
| `raw_log_ref` | TEXT | | episode_index.raw_log_ref | 원본 추적 포인터 |
| `mission_context` | TEXT | ✅ | mission_brief.mission_context | 임무유형 (회수 키) |
| `posture` | JSON | | mission_brief.posture | 경계태세 `{watchcon,defcon,infocon}` (회수 키, 표준 JSON 직렬화) |
| `threat_event` | TEXT | ✅ | threat_modeling_log[*].threat_event | 위협 이벤트 코드 (회수 키, 예: `T3`) |
| `confidence` | REAL | | threat_modeling_log[*].confidence | **판정 confidence** (04/NLP가 그때 준 확신도) |
| `outcome` | TEXT | | episode_index.outcome | **실제 outcome** (임무 종료 후 집계된 결과) |
| `corridor_region` | TEXT | | episode_index.corridor_region | 지역 코드(보조 필터) |
| `kill_chain_stage` | TEXT | | threat_modeling_log[*].kill_chain_stage | 킬체인 단계(보조) |
| `ts` | INTEGER | | episode.ts | 집계/편입 시각(epoch) |

**핵심 5필드**(태스크 요구) = `mission_context`, `posture`, `threat_event`, `confidence`(판정),
`outcome`(실제). 나머지는 추적·보조 필터용.

### 3-1. 변환기 입력 — enriched episode

`aggregate.build_episode_index`가 내는 episode_index는 `threat_events`를 **문자열 배열**로만
보관해 위협별 confidence/kill_chain_stage를 잃는다. 코퍼스는 이를 보존해야 하므로, 변환기 입력은
episode_index + mission_brief 컨텍스트 + 위협 판정 상세를 조인한 **enriched episode** dict다:

```jsonc
{
  "mission_id": "m-0417",
  "raw_log_ref": "raw/m-0417.json",
  "mission_context": "정찰",              // mission_brief
  "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},  // mission_brief
  "corridor_region": "KR-hill-07",       // episode_index
  "outcome": "rtb_success",              // episode_index (aggregate_outcome)
  "ts": 1751600000000,
  "threat_judgments": [                  // threat_modeling_log 위협별 집계(유니크)
    {"threat_event": "T3", "confidence": 0.92, "kill_chain_stage": "후기"},
    {"threat_event": "T1", "confidence": 0.71, "kill_chain_stage": "중기"}
  ]
}
```

> **설계 결정(Lead 확인 요망)**: `threat_judgments`는 현재 episode_index에 없다.
> 라운드 1은 코퍼스 스키마·계약·변환기·회수 초안까지만 확정하고, `aggregate.py`가
> `threat_modeling_log` → `threat_judgments`(위협별 confidence 보존)를 실제로 집계하도록
> 확장하는 것은 **다음 라운드**(집계기 구현 라운드)에 둔다. 변환기는 이 계약 형태를 입력으로 받는다.

## 4. episode → 학습레코드 변환 규칙

`infra/log/corpus.py:episode_to_corpus_records(episode) -> list[dict]`

1. `mission_id`, `mission_context` 누락 시 `ValueError`(신뢰경계 입력 검증).
2. `threat_judgments`의 각 판정 `j`마다 학습레코드 1건 생성:
   - 핵심 5필드 + 추적/보조 필드를 §3 표대로 매핑.
   - `j.threat_event` 누락 판정은 건너뛴다(위협 식별 불가 → 회수 키 성립 안 함).
3. `threat_judgments`가 비면 `[]` 반환.

## 5. 저장 — corpus_record 테이블

`infra/log/schema.sql`에 `corpus_record` 테이블을 추가한다(episode_index와 동일 SQLite 파일에
공존 가능). `infra/log/corpus.py:CorpusStore`가 `store.py:EpisodeStore` 스타일을 미러링해
CRUD/회수를 제공한다.

- 유니크 키 `(mission_id, threat_event)` — 재집계 시 `ON CONFLICT DO UPDATE`(멱등).
- `posture`는 표준 JSON(`sort_keys=True`)으로 직렬화해 저장 → 회수 시 동일 직렬화로 정확일치 비교.
- 인덱스: `mission_context`, `threat_event`(회수 1단계 후보 축소).

## 6. 회수(retrieval) 계약 초안

`infra/log/corpus.py:CorpusStore.retrieve(...)`

### 입력

| 파라미터 | 타입 | 필수 | 의미 |
|---|---|:---:|---|
| `mission_context` | str｜None | | 임무유형 일치 필터 |
| `posture` | dict｜None | | 경계태세 정확일치 필터(표준 JSON 직렬화 비교) |
| `threat_event` | str｜None | | 위협 이벤트 일치 필터 |
| `top_k` | int | | 최대 반환 수(기본 20) |

- 세 필터는 AND 결합. 모두 None이면 전체(top_k 한도).
- 회수 시나리오: 다음 임무 브리핑의 `(mission_context, posture)` + NLP가 뽑은 후보 `threat_event`로
  질의 → 과거 유사 사례의 판정 confidence·실제 outcome 참고.

### 출력

학습레코드 dict의 리스트. 각 dict = §3 스키마 필드(`posture`는 dict로 역직렬화). `ts` 내림차순
→ `confidence` 내림차순 정렬(최신·고확신 우선).

```jsonc
[
  {
    "mission_id": "m-0417", "raw_log_ref": "raw/m-0417.json",
    "mission_context": "정찰", "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
    "threat_event": "T3", "confidence": 0.92, "outcome": "rtb_success",
    "corridor_region": "KR-hill-07", "kill_chain_stage": "후기", "ts": 1751600000000
  }
]
```

> **초안 한계(다음 라운드 후보)**: 현 회수는 스칼라 정확일치(메타필터)만 한다. posture 근접
> 매칭(예: watchcon ±1), narrative 임베딩 벡터유사도(sqlite-vec, `store.py`와 동형), pending 제외
> 정책 연동은 초안 범위 밖이다. `store.EpisodeStore.search`(벡터 하이브리드)와 통합하는 것은
> 별도 라운드에서 다룬다.

## 7. 경계 — 이번 라운드 범위 밖 (CRITICAL)

- **CHANNEL_WEIGHTS 재학습은 이번 라운드 범위 밖이다.** 코퍼스는 "참고자료 축적·회수"까지만
  담당한다. 축적된 코퍼스로 `src/onboard/shared/constants.py`의 `CHANNEL_WEIGHTS`(및
  `RAC_MATRIX`, `SIGNAL_TO_THREAT`, `PHASE_THREAT_MULTIPLIER`) 값을 재학습/변경하는 것은
  **금지**된다.
- 근거: `CLAUDE.md` CRITICAL — "RAC 매트릭스는 AI가 절대 바꾸지 않는다(MIL-STD-882E SCC-1)",
  "D4D 문서의 파라미터 표에 나온 값을 임의로 바꾸지 말 것. 값 변경은 D4D 문서를 먼저 수정한 뒤
  코드에 반영." 즉 상수 변경은 **D4D 문서-우선(doc-first) + Lead 승인**을 거친 **별도 라운드**에서만
  가능하다.
- 이 라운드의 산출물(스키마·변환기·저장·회수)은 어떤 상수도 읽거나 쓰지 않으며, `eval`/`exec`도
  사용하지 않는다.
