# ThreatModelingOutput (+ ThreatCandidate)

04(Threat Modeling)가 Step A(국면 확인) → B(신호→위협 매핑) → C(확신도·킬체인단계 산출) → D(potential_outcome 매핑)를 거쳐 산출한 위협 후보 목록. 05(Risk Assessment)의 L×S 계산 입력이다.

- **생산 레이어**: 04 Threat Modeling
- **소비 레이어**: 05 Risk Assessment

## ThreatCandidate — 위협 후보 1건

| 필드 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `threat_event` | `str` | 필수 | 위협 ID(`T1`~`T7`). `SIGNAL_TO_THREAT` 매핑 결과 |
| `match_count` | `int` | 필수 | 매칭된 채널 수(quality 하한 제외 이후, Step C 계산) |
| `confidence` | `float` | 필수 | 확신도(0~0.95). 결정론적 표(`CONFIDENCE_BY_MATCH_COUNT`) 또는 AI 강화판(로그오즈 결합) 중 교차검증을 통과한 값 |
| `confidence_source` | `Literal["ai", "deterministic"]` | 필수 | confidence가 AI 강화판 값인지 결정론적 값인지(교차검증 결과) |
| `kill_chain_stage` | `Literal["초기", "중기", "후기"]` | 필수 | Step C 계산 — `avg_weight ≥ 0.35`이고 매칭 채널 2개 이상이면 후기, 1개 이상이면 중기, 없으면 초기 |
| `potential_outcome` | `str` | 필수 | 예상 결과 카테고리(`mission_abort`/`hull_loss`/`attrition_kill`). `POTENTIAL_OUTCOME_MAP` 룩업 |
| `context` | `dict` | 선택(`NotRequired`) | threat_event별 위치·분류 정보 `{bearing_deg, bearing_source, class}`. 04→06/07 연동용(배선은 보류 상태, `docs/D4D/06. Response.md` "04와의 연동" 참고) |

## ThreatModelingOutput — Step D 최종 출력

| 필드 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `declared_phase` | `str` | 필수 | 선언된 임무 국면(TAKEOFF/WAYPOINT/LOITER_ROI/RTL/LAND). `mission_phase` 채널(03)에서 그대로 읽음(재계산 안 함) |
| `mission_phase_confidence` | `float` | 필수 | 국면 판정 확신도. `mission_phase` 채널(03)에서 계산됨 |
| `candidates` | `list[ThreatCandidate]` | 필수 | 이번 사이클에 매칭된 위협 후보 전부(하나만 골라 버리지 않음) |
| `primary` | `ThreatCandidate \| None` | 필수(값은 null 가능) | candidates 중 대표값(match_count 최다, 동률이면 avg_weight 높은 쪽). 후보가 없으면 `null` |
| `background_exposure_score` | `float` | 필수 | T6(환경노출도, 배경) 값. `terrain_class.exposure_score`(03)를 가공 없이 전달 |
| `cycle_context` | `dict` | 선택(`NotRequired`) | 사이클 단위 지형 정보 `{optimal_terrain_bearing_deg, lowest_exposure_bearing_deg}`. 07의 방향 결정 폴백용(배선 보류) |

## 예시 JSON

[`04. Threat Modeling`](../D4D/04.%20Threat%20Modeling.md)의 골든 예시를 그대로 인용한다.

```json
{
  "declared_phase": "LOITER_ROI",
  "mission_phase_confidence": 0.9,
  "candidates": [
    { "threat_event": "T3", "match_count": 2, "confidence": 0.917, "confidence_source": "ai",
      "kill_chain_stage": "후기", "potential_outcome": "attrition_kill" }
  ],
  "primary": { "threat_event": "T3", "match_count": 2, "confidence": 0.917, "confidence_source": "ai",
               "kill_chain_stage": "후기", "potential_outcome": "attrition_kill" },
  "background_exposure_score": 0.4
}
```

## 관련 상수

[`constants.py`](../../src/onboard/shared/constants.py) — `THREAT_CATALOG`, `SIGNAL_TO_THREAT`, `T4_MULTI_CHANNEL_CONDITIONS`, `PHASE_THREAT_MULTIPLIER`, `CHANNEL_WEIGHTS`, `DEFAULT_CHANNEL_WEIGHT`, `CONFIDENCE_BY_MATCH_COUNT`, `W_MIN`, `Q_MIN`, `CROSS_CHECK_TOLERANCE`, `CONFIDENCE_UPPER_BOUND`, `POTENTIAL_OUTCOME_MAP`, `OUTCOME_TO_SEVERITY`, `SEVERITY_ORDER`, `TIME_TO_COLLISION_THRESHOLD_S`, `QUALITY_DELTA_DROP_THRESHOLD`. 값은 이 문서에 복제하지 않는다 — 조회는 소스 상수를 직접 참고.

## 내비게이션

◀ [이전 AbstractionOutput](./03-abstraction-output.md) | [다음 ▶ RiskAssessmentOutput](./05-risk-assessment-output.md)

## 소스

- 스키마: [`src/onboard/shared/schemas.py`](../../src/onboard/shared/schemas.py) — `ThreatCandidate`, `ThreatModelingOutput`
- 상세 스펙: [`docs/D4D/04. Threat Modeling.md`](../D4D/04.%20Threat%20Modeling.md), [`docs/D4D/C-1. Threat Modeling Spec.md`](../D4D/C-1.%20Threat%20Modeling%20Spec.md)
