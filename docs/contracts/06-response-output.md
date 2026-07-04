# ResponseOutput

06(Response)이 05가 정렬한 `candidates[]` 중 `priority_rank=1`인 후보 하나에 대해 실제 행동(비행/통신/무장/항법)을 결정한 출력. AI는 이 레이어에서 완전히 배제된 결정론적 상태기계 결과다. 07(Flight Planning)의 입력이다.

- **생산 레이어**: 06 Response
- **소비 레이어**: 07 Flight Planning

## 필드

| 필드 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `primary_threat_event` | `str \| None` | 필수(값은 null 가능) | 1순위 위협 ID. candidates가 비어있으면(위협 미탐지) `null` |
| `rac` | `str` | 필수 | 1순위 위협의 RAC(05 산출값). 위협 미탐지 시 05의 `ambient_rac`을 그대로 사용 |
| `kill_chain_stage` | `str \| None` | 필수(값은 null 가능) | 1순위 위협의 킬체인 단계(04 산출값) |
| `threat_category` | `Literal["PHYSICAL", "REMOTE", "NAVIGATION"] \| None` | 필수(값은 null 가능) | 위협 성격 3분류. PHYSICAL=T3/T4, REMOTE=T1/T2/T5, NAVIGATION=T7 |
| `flight_action` | `str` | 필수 | 전략적 비행 행동. `(RAC, kill_chain_stage, threat_category)` 조회 결과(예: `RTL`, `REROUTE`, `ALTITUDE_CHANGE_REROUTE`, `ALTITUDE_CHANGE`, `POSTURE_ELEVATE`, `MAINTAIN`) |
| `comms_level` | `str` | 필수 | 통신 등급(예: `L0`~`L3`). 같은 조회 테이블에서 결정 |
| `payload_action` | `list[str]` | 필수 | 전술적 개별 오버라이드 리스트(threat_event별, 비어있을 수 있음). RAC=High이고 kill_chain_stage가 후기/중기일 때만 적용(예: `DATA_WIPE`, `WEAPON_DROP`) |
| `nav_mode` | `str \| None` | 필수(값은 null 가능) | 항법모드 오버라이드(예: T1 → `INS_ONLY`). 해당 없으면 `null` |
| `special_action` | `str \| None` | 필수(값은 null 가능) | Serious/Medium 및 High+초기(POSTURE_ELEVATE) 전용 부가 지시(예: `GCS_CONSULT`, `INCREASE_ASSESSMENT_FREQUENCY`) |
| `secondary_threats` | `list[dict]` | 필수 | 2순위 이하 위협 요약(`threat_event`/`rac`/`compound_urgency_score`/`priority_rank`만 포함) |
| `ai_reliability` | `Literal["normal", "low"]` | 필수 | 05에서 넘어온 값. 행동 자체엔 영향 없이 지상국 통보에만 참고 |

## 예시 JSON

[`06. Response`](../D4D/06.%20Response.md)의 골든 예시를 그대로 인용한다.

```json
{
  "primary_threat_event": "T3",
  "rac": "High",
  "kill_chain_stage": "후기",
  "threat_category": "PHYSICAL",
  "flight_action": "RTL",
  "comms_level": "L3",
  "payload_action": ["DATA_WIPE"],
  "nav_mode": null,
  "special_action": null,
  "secondary_threats": [],
  "ai_reliability": "normal"
}
```

## 관련 상수

`schemas.py`의 `ResponseOutput` 계약 자체는 `constants.py` 상수를 참조하지 않는다(06의 `(RAC, kill_chain_stage, threat_category)` → `flight_action`/`comms_level` 조회 테이블, `DATA_WIPE`/`WEAPON_DROP` 대상 규칙은 팀원 자료 기반 하드코딩이며 `constants.py`가 아닌 06 레이어 코드 소관 — 상세는 [`docs/D4D/06. Response.md`](../D4D/06.%20Response.md) "파라미터 출처 정리" 참고).

## 내비게이션

◀ [이전 RiskAssessmentOutput](./05-risk-assessment-output.md) | [다음 ▶ FlightPlanOutput](./07-flight-plan-output.md)

## 소스

- 스키마: [`src/onboard/shared/schemas.py`](../../src/onboard/shared/schemas.py) — `ResponseOutput`
- 상세 스펙: [`docs/D4D/06. Response.md`](../D4D/06.%20Response.md), [`docs/D4D/E-1. Response Spec.md`](../D4D/E-1.%20Response%20Spec.md)
