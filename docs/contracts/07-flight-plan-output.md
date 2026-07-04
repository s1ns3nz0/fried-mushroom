# FlightPlanOutput

07(Flight Planning)이 06의 `flight_action`을 받아 실제 방향·고도·재계획 범위를 계산한 MAVLink급 지시값. 오토파일럿(PX4/ArduPilot)이 소비하며, D4D 파이프라인의 최종 출력이다.

- **생산 레이어**: 07 Flight Planning
- **소비 레이어**: 기체/오토파일럿(PX4/ArduPilot, MAVLink) — D4D 시스템 범위 밖

## 필드

| 필드 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `flight_action` | `str` | 필수 | 06에서 넘어온 값 그대로(RTL/REROUTE/ALTITUDE_CHANGE_REROUTE/ALTITUDE_CHANGE/POSTURE_ELEVATE/MAINTAIN) |
| `target_bearing_deg` | `float \| None` | 필수(값은 null 가능) | 목표 방위각(0~360). PHYSICAL/REMOTE는 위협 방위각의 정반대, NAVIGATION은 최적지형 방향. 방향 결정 불가 시 `null` |
| `altitude_delta_m` | `int` | 필수 | 고도 조정량(m). flight_action별 고정값(예: ALTITUDE_CHANGE +15, POSTURE_ELEVATE +25, ALTITUDE_CHANGE_REROUTE +50, 그 외 0) |
| `replan_scope` | `Literal["NONE", "LOCAL", "FULL"]` | 필수 | 재계획 범위. flight_action별 매핑(RTL/ALTITUDE_CHANGE/POSTURE_ELEVATE→LOCAL, REROUTE류→FULL, MAINTAIN→NONE) |
| `reroute_anchor` | `str \| None` | 필수(값은 null 가능) | 방향/재계획 기준(`threat_reverse(channel)` / `terrain_fallback` / `last_known_good_position` / `optimal_terrain` / `altitude_only`) |

## 예시 JSON

[`07. Flight Planning`](../D4D/07.%20Flight%20Planning.md)의 골든 예시를 그대로 인용한다.

```json
{
  "flight_action": "RTL",
  "target_bearing_deg": 225,
  "altitude_delta_m": 0,
  "replan_scope": "LOCAL",
  "reroute_anchor": "threat_reverse(proximity_object)"
}
```

## 관련 상수

[`constants.py`](../../src/onboard/shared/constants.py) — `ALTITUDE_DELTA_PREVENTIVE_M`, `POSTURE_ELEVATE_ALTITUDE_M`, `ALTITUDE_DELTA_TERRAIN_M`. 값은 이 문서에 복제하지 않는다 — 조회는 소스 상수를 직접 참고.

## 내비게이션

◀ [이전 ResponseOutput](./06-response-output.md) | 다음 ▶ (파이프라인 종료 — 오토파일럿 소비, D4D 범위 밖)

## 소스

- 스키마: [`src/onboard/shared/schemas.py`](../../src/onboard/shared/schemas.py) — `FlightPlanOutput`
- 상세 스펙: [`docs/D4D/07. Flight Planning.md`](../D4D/07.%20Flight%20Planning.md), [`docs/D4D/F-1. Flight Planning Spec.md`](../D4D/F-1.%20Flight%20Planning%20Spec.md)
