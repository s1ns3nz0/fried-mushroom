# 레이어 간 JSON 계약 인덱스

D4D 온보드 파이프라인은 01(GCS)~07(Flight Planning) 레이어가 사이클마다 순차 실행되며, 레이어 간 통신은 **오직 JSON-직렬화 가능한 dict**로만 이뤄진다(CLAUDE.md CRITICAL). 이 폴더는 그 dict들의 필드 단위 계약을 정리한다.

**소스 오브 트루스는 [`src/onboard/shared/schemas.py`](../../src/onboard/shared/schemas.py)이며, 이 문서들은 그 해설이다. 스키마 변경 시 문서를 함께 갱신한다(Lead 승인 필요).**

## 파이프라인 체인

```
01 GCS ──── MissionBrief ────────────────▶ 02~07 온보드 레이어 전체
             (임무 시작 시 1회 확정,           (사이클 동안 read-only, 불변)
              모든 레이어가 참조)

02 Sensor ── 원시 센서 dict(타입 미정) ───▶ 03 Sensor Abstraction
                                              │
03 Sensor Abstraction ── AbstractionOutput ──▶ 04 Threat Modeling
                                              │
04 Threat Modeling ── ThreatModelingOutput ──▶ 05 Risk Assessment
                                              │
05 Risk Assessment ── RiskAssessmentOutput ──▶ 06 Response
                                              │
06 Response ── ResponseOutput ──────────────▶ 07 Flight Planning
                                              │
07 Flight Planning ── FlightPlanOutput ─────▶ 기체/오토파일럿(PX4/ArduPilot, MAVLink) — D4D 범위 밖
```

## 계약 표

| 계약명 | 생산 레이어 | 소비 레이어 | 문서 링크 | schemas.py 심볼 |
|---|---|---|---|---|
| MissionBrief | 01 GCS(지상 정보 센터 AI) | 02~07 온보드 레이어 전체(read-only, 사이클 동안 불변) | [`01-mission-brief.md`](./01-mission-brief.md) | `MissionBrief` |
| AbstractionOutput | 03 Sensor Abstraction | 04 Threat Modeling | [`03-abstraction-output.md`](./03-abstraction-output.md) | `AbstractionOutput`, `ChannelOutput` |
| ThreatModelingOutput | 04 Threat Modeling | 05 Risk Assessment | [`04-threat-modeling-output.md`](./04-threat-modeling-output.md) | `ThreatModelingOutput`, `ThreatCandidate` |
| RiskAssessmentOutput | 05 Risk Assessment | 06 Response | [`05-risk-assessment-output.md`](./05-risk-assessment-output.md) | `RiskAssessmentOutput`, `RiskCandidate` |
| ResponseOutput | 06 Response | 07 Flight Planning | [`06-response-output.md`](./06-response-output.md) | `ResponseOutput` |
| FlightPlanOutput | 07 Flight Planning | 기체/MAVLink(오토파일럿, D4D 범위 밖) | [`07-flight-plan-output.md`](./07-flight-plan-output.md) | `FlightPlanOutput` |

02(UAV Sensor Layer) → 03(Sensor Abstraction) 사이의 원시 센서 dict는 `schemas.py`에 타입으로 정의돼 있지 않다. 새 계약 문서를 발명하지 않고 [`docs/D4D/02. UAV Sensor Layer.md`](../D4D/02.%20UAV%20Sensor%20Layer.md)를 그대로 참조한다(스키마 타입 미정).

## 관련 문서

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — 디렉토리 구조 및 데이터 흐름 개요
- [`../D4D/`](../D4D/) — 레이어별 상세 스펙 + 최종 출력 스키마 표 + 예시 JSON(팀원 소유, 이 폴더에서는 수정하지 않음)
- [`../../src/onboard/shared/schemas.py`](../../src/onboard/shared/schemas.py) — TypedDict 정의(소스 오브 트루스)
- [`../../src/onboard/shared/constants.py`](../../src/onboard/shared/constants.py) — 계약에 등장하는 enum성 상수(RAC_MATRIX, SIGNAL_TO_THREAT 등)
