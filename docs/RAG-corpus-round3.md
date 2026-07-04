# RAG 코퍼스 라운드 3 — 결과검증 advisory (신뢰도 캘리브레이션 + 채널가중치 제안)

라운드 1(스키마·변환·회수)·라운드 2(threat_judgments 집계·posture 근접매칭)에서 축적된 코퍼스를
**참고지표(advisory)** 로 소비하는 첫 라운드. 산출물은 어떤 결정론 상수도 바꾸지 않는다 — 오직
**제안 리포트**만 낸다. 상수 반영은 이 문서-우선 설계에 대한 Lead 승인 후 **별도 라운드**에서만.

## 0. 불변 원칙 (CRITICAL — SCC-1)

- **결정론 지배.** `CHANNEL_WEIGHTS`·`RAC_MATRIX`·`SIGNAL_TO_THREAT`·`PHASE_THREAT_MULTIPLIER`
  는 `src/onboard/shared/constants.py` 하드코딩 상수로 남는다. 이 라운드 코드는 상수를 **읽지도
  쓰지도** 않으며 `eval`/`exec` 도 없다 (라운드 1·2 원칙 유지).
- **advisory-only.** 산출물은 "이 채널 가중치를 이렇게 조정하는 것을 **검토**하라"는 사람이 읽는
  리포트다. 자동 적용 경로는 존재하지 않는다. MIL-STD-882E SCC-1: AI 는 결정론 안전판정을 못 바꾼다.
- **doc-first 게이트.** 리포트가 제안한 수치를 실제로 반영하려면 (1) D4D 문서(04. Threat Modeling
  §Step C) 를 먼저 수정하고 (2) Lead 승인 후 (3) 코드에 반영한다 — `CLAUDE.md` 개발프로세스 그대로.

## 1. 스키마 갭 — 채널 귀속(attribution) 부재

현 `corpus_record`(라운드 1)는 위협 판정당 `{threat_event, confidence, outcome, kill_chain_stage,
posture, mission_context, ...}` 를 담지만, **어떤 채널이 그 판정에 기여했는지**는 없다. 따라서 현
스키마만으로는 `CHANNEL_WEIGHTS`(채널→가중치)를 직접 재학습할 수 없다.

- **지금 가능(스키마 무변경):** 판정 `confidence` vs 실제 `outcome` 의 **신뢰도 캘리브레이션**.
  "T3 를 confidence 0.9 로 부른 판정이 실제로 얼마나 맞았나"는 채널 귀속 없이 계산된다.
- **채널 가중치 제안에 필요(스키마 확장 — 후속):** 판정별 기여 채널 목록.
  제안 확장: 레코드에 `contributing_channels: {channel: {quality, matched}}` 추가
  (04 Step C 가 산출하는 채널별 신호강도/매칭 여부). 확장은 라운드 3.5 로 분리 — 이 문서에서 계약만 못박고
  구현은 후속(로그 스키마·변환기 동시 변경이라 별도 PR).

## 2. 신뢰도 캘리브레이션 (이번 라운드 구현 대상)

**입력:** `CorpusStore.retrieve(...)` 로 얻은 레코드(또는 전체 스캔).
**메트릭 (threat_event 별):**

- `outcome` 을 이진 라벨로 사상: 성공계열(`rtb_success`, `mission_success`, `evaded` 등)=1,
  실패계열(`lost`, `captured`, `mission_abort` 등)=0. 매핑표는 §4 `OUTCOME_LABELS` 정본.
- **캘리브레이션 오차** `calib_error = mean(confidence) - hit_rate`
  (hit_rate = 라벨 1 비율). >0 이면 과신(overconfident), <0 이면 과소.
- **표본수** `n` 을 함께 보고 — n 작으면 신뢰구간 넓다는 경고 플래그(`low_sample: n < 5`).

**해석 (advisory):** 특정 위협을 일관되게 과신/과소하면, 그 위협을 트리거하는 채널군의 가중치나
`CONFIDENCE_BY_MATCH_COUNT` 표를 **검토**하라는 신호. 자동 조정 아님.

## 3. 채널 가중치 advisory (설계 — 스키마 확장 후 구현)

`contributing_channels` 확장 후:

- 채널 `c` 의 **기여 정확도** `ctrib(c) = 결과성공 판정에서 c 가 매칭된 비율 −
  결과실패 판정에서 c 가 매칭된 비율` (판별력 proxy, −1..+1).
- 판별력이 현 가중치와 어긋나면(예: 낮은 가중치인데 판별력 높음) **제안 델타**를 리포트.
  델타는 **유계**(`|Δw| ≤ 0.05`/라운드)이며 CHANNEL_WEIGHTS 범위(0.15..0.40) 밖 제안 금지.
- **RAC_MATRIX 는 대상 아님** — 채널 가중치는 04 위협 confidence 에만 영향, 05 RAC 조회표는 불가침.

## 4. Advisory 리포트 스키마

```json
{
  "generated_ts": 0,
  "corpus_size": 0,
  "confidence_calibration": [
    {"threat_event": "T3", "n": 12, "mean_confidence": 0.88,
     "hit_rate": 0.75, "calib_error": 0.13, "low_sample": false,
     "note": "overconfident — T3 트리거 채널군 가중치 검토 권고"}
  ],
  "channel_weight_proposals": [],
  "guardrails": {
    "advisory_only": true, "applied": false,
    "requires": "D4D 04.md §Step C 문서수정 + Lead 승인 후 별도 라운드"
  }
}
```

`OUTCOME_LABELS`(정본): 성공=`{rtb_success, mission_success, evaded, arrived}`,
실패=`{lost, captured, mission_abort, shotdown}`, 그 외/None=제외(캘리브레이션 표본 아님).

## 5. 검증

- **결정론:** 같은 코퍼스 → 같은 리포트(정렬·반올림 고정).
- **백테스트(채널가중치 후속):** 제안 델타를 코퍼스 held-out 분할에 적용해 hit_rate 개선 여부만
  **오프라인 계산**(런타임 상수 무변경). 개선 없으면 제안 폐기.
- **안전 회귀:** 이 라운드 코드가 `shared/constants` 를 import 하지 않음을 정적 테스트로 잠근다
  (기존 `tests/test_layer_boundaries.py` 패턴 재사용).

## 6. 이번 라운드 경계

- **구현:** §2 신뢰도 캘리브레이션 분석기(`infra/log/weight_advisor.py`) + 리포트 §4 의
  `confidence_calibration` 부분. read-only, 상수 무접촉. `tests/infra/`.
- **범위 밖(후속):** §1 스키마 확장, §3 채널가중치 제안 구현, §5 백테스트 — `contributing_channels`
  로그 계약이 선행돼야 함. 상수 반영은 영구히 doc-first + Lead 승인 게이트.
