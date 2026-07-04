# RiskAssessmentOutput (+ RiskCandidate)

05(Risk Assessment)가 04의 `candidates[]` 각각에 L(발생가능성)×S(심각도)→RAC 매트릭스 조회를 적용하고, 여러 후보의 대응 우선순위(`priority_rank`)를 매긴 출력. 06(Response)이 `priority_rank=1`만 소비한다.

- **생산 레이어**: 05 Risk Assessment
- **소비 레이어**: 06 Response

## RiskCandidate — `ThreatCandidate`(04)를 상속 + 위험평가 필드 추가

`RiskCandidate`는 `ThreatCandidate`를 상속하므로 `threat_event`/`match_count`/`confidence`/`confidence_source`/`kill_chain_stage`/`potential_outcome`/`context`(선택) 필드를 그대로 포함한다(상세는 [04 계약 문서](./04-threat-modeling-output.md) 참고). 아래는 `RiskCandidate`가 추가하는 필드다.

| 필드 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `rac` | `Literal["High", "Serious", "Medium", "Low"]` | 필수 | 결정론적 RAC 등급. `RAC_MATRIX[(l_class_final, severity_num_final)]` 조회 결과. AI가 절대 바꾸지 않음(MIL-STD-882E SCC-1) |
| `l_class_final` | `Literal["A", "B", "C", "D", "E", "F"]` | 필수 | 발생가능성(L) 등급. `l_value_to_class(base_rate)` 후 `posture_shift_steps`로 보정된 최종값 |
| `severity_label_final` | `Literal["Catastrophic", "Critical", "Marginal", "Negligible"]` | 필수 | 심각도(S) 라벨. `OUTCOME_TO_SEVERITY[potential_outcome]` 후 예비기체/강제격상 override 반영 |
| `compound_risk_assessment` | `dict` | 필수 | AI 강화판 병렬 참고지표 `{continuous_L, continuous_S, rac_ai_equivalent, ai_reliability}`. RAC 자체에는 영향 없음 |
| `compound_urgency_score` | `float` | 필수 | 우선순위 정렬 기준 점수(`continuous_L × continuous_S` + kill_chain_stage 후기 보너스) |
| `priority_rank` | `int` | 필수 | 1부터, `compound_urgency_score` 내림차순(동률 시 severity_num_final 오름차순 → match_count 내림차순) |

## RiskAssessmentOutput

| 필드 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `candidates` | `list[RiskCandidate]` | 필수 | `priority_rank`로 정렬된 위험평가 결과 배열 |
| `ambient_rac` | `Literal["Medium", "Low"] \| None` | 선택(`NotRequired`) | candidates가 비었을 때만 값이 있으며 항상 `"Low"`(issue #24 Lead 결정, 2026-07-04 — exposure≥0.7→Medium 승격 규칙 폐기). `Medium`은 스키마 타입상 남아있으나 05는 더 이상 생성하지 않는다. `background_exposure_score`(04)는 참고 지표로 별도 유지되며 06 등에서 소비 가능 |

## 예시 JSON

[`05. Risk Assessment`](../D4D/05.%20Risk%20Assessment.md)의 골든 예시를 그대로 인용한다.

```json
{
  "candidates": [
    {
      "threat_event": "T3", "rac": "Serious",
      "l_class_final": "C", "severity_label_final": "Catastrophic",
      "kill_chain_stage": "후기", "match_count": 2,
      "compound_risk_assessment": {
        "continuous_L": 0.1965, "continuous_S": 0.95,
        "rac_ai_equivalent": "Serious", "ai_reliability": "normal"
      },
      "compound_urgency_score": 0.2867, "priority_rank": 1
    }
  ],
  "ambient_rac": null
}
```

주의: 이 예시는 D4D 문서의 골든 예시를 그대로 인용한 것으로, `ThreatCandidate` 필드 중 `confidence`/`confidence_source`/`potential_outcome`이 표기 생략돼 있다(문서 원문 그대로). 실제 `RiskCandidate`는 상속 규칙상 이 필드들도 포함해야 한다.

## 관련 상수

[`constants.py`](../../src/onboard/shared/constants.py) — `MISSION_CONTEXTS`, `BASE_RATE_PHYSICAL`, `BASE_RATE_REMOTE_NAV`, `L_VALUE_TO_CLASS_THRESHOLDS`, `RAC_MATRIX`, `RAC_ORDER`, `CONTINUOUS_S_BASE_SCORE`, `CONTINUOUS_S_TO_NUM_THRESHOLDS`, `AMBIENT_EXPOSURE_THRESHOLD`, `AI_RELIABILITY_DELTA_THRESHOLD`, `KILL_CHAIN_LATE_BONUS`, `COMPOUND_UPPER_BOUND`, `CONFIDENCE_ANCHOR`. 값은 이 문서에 복제하지 않는다 — 조회는 소스 상수를 직접 참고.

## 내비게이션

◀ [이전 ThreatModelingOutput](./04-threat-modeling-output.md) | [다음 ▶ ResponseOutput](./06-response-output.md)

## 소스

- 스키마: [`src/onboard/shared/schemas.py`](../../src/onboard/shared/schemas.py) — `RiskCandidate`, `RiskAssessmentOutput`
- 상세 스펙: [`docs/D4D/05. Risk Assessment.md`](../D4D/05.%20Risk%20Assessment.md), [`docs/D4D/D-1. Risk Assessment Spec.md`](../D4D/D-1.%20Risk%20Assessment%20Spec.md)
