# MissionBrief

임무 시작 시 01(지상 정보 센터 AI)이 운용자 승인을 거쳐 1회 확정하고, 온보드 파이프라인 전 레이어(02~07)가 사이클 동안 read-only로 참조하는 임무 브리핑. 임무 동안 값이 바뀌지 않는다(ARCHITECTURE.md "상태 관리" 참고).

- **생산 레이어**: 01 GCS(지상 정보 센터 AI)
- **소비 레이어**: 02~07 온보드 레이어 전체(직접 소비 예: 04 `declared_phase` 대조, 05 `mission_context`/`posture`/`drone_profile.spare_available`, 06 `drone_profile.armament`, 07 `corridor`)

## 필드

| 필드 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `sortie_id` | `str` | 필수 | 이번 출격 식별자. 03 `AbstractionOutput.id`가 `{sortie_id}-{순번}` 형태로 이 값을 이어받는다 |
| `mission_context` | `Literal["정찰", "타격", "호송", "수송"]` | 필수 | 임무 전체 성격. `declared_phase`(비행 국면, 매 사이클 바뀜)와 다른 축 — 05의 `base_rate` 조회 키(`(threat_event, mission_context)`)로 쓰인다 |
| `posture` | `dict` | 필수 | 경계태세 `{defcon, infocon, watchcon}`. 05의 `posture_shift_steps`가 물리·EW계는 `min(watchcon, defcon)`, 사이버계(T2)는 `infocon`을 기준으로 사용 |
| `drone_profile` | `dict` | 필수 | 기체 고정 스펙(`id`, `type`, `endurance_rated_s`, `spare_available`, `armament`, `sensor_suite`). 05의 예비기체 override와 06의 `WEAPON_DROP` 조건부 실행이 여기서 값을 읽는다 |
| `corridor` | `dict` | 필수 | 이동 가능 회랑 `{type, axis, half_width, alt_min, alt_max}`. 01의 "GCS 항로정보"에 해당하며 회랑 이탈은 위험평가 하드 제약 |
| `weights` | `dict` | 필수 | 임무 가치 가중치 `{stealth, survival, info_quality, timeliness}`, 각 축 0~1. 운용자가 GCS에서 직접 설정 |

## 예시 JSON

`docs/D4D/B-1. 지상통제센터 AI 세부`의 골든 예시 중 `MissionBrief`(schemas.py) 필드에 대응하는 부분만 발췌해 재구성했다.

```json
{
  "sortie_id": "GIREOGI-0704-01",
  "mission_context": "정찰",
  "posture": { "defcon": 3, "infocon": 4, "watchcon": 3 },
  "drone_profile": {
    "id": "uav-7",
    "type": "quadrotor",
    "endurance_rated_s": 1800,
    "spare_available": true,
    "armament": [{ "type": "eo_camera", "expendable": false }],
    "sensor_suite": ["eo", "ir", "rf", "gnss", "imu", "acoustic"]
  },
  "corridor": {
    "type": "polyline_buffer",
    "axis": [[57, 42], [120, 110], [183, 183]],
    "half_width": 20,
    "alt_min": 50,
    "alt_max": 300
  },
  "weights": { "stealth": 0.9, "survival": 0.8, "info_quality": 0.6, "timeliness": 0.3 }
}
```

## 관련 상수

이 계약 자체는 `constants.py` 상수를 직접 참조하지 않는다. `mission_context`의 허용값(`정찰`/`타격`/`호송`/`수송`)은 [`constants.py`](../../src/onboard/shared/constants.py)의 `MISSION_CONTEXTS`와 대응한다.

## 내비게이션

◀ (파이프라인 시작) | [다음 ▶ AbstractionOutput](./03-abstraction-output.md)

## 소스

- 스키마: [`src/onboard/shared/schemas.py`](../../src/onboard/shared/schemas.py) — `MissionBrief`
- 상세 스펙: [`docs/D4D/01. 지상 정보 센터 AI.md`](../D4D/01.%20지상%20정보%20센터%20AI.md), [`docs/D4D/B-1. 지상통제센터 AI 세부.md`](../D4D/B-1.%20지상통제센터%20AI%20세부.md)

참고: `schemas.py`의 `MissionBrief`는 B-1의 전체 METT+TC 상태 모델(`mettc.E.tracks`, `T_troops`, `T_time`, `C` 등 포함) 중 온보드 파이프라인이 실제로 소비하는 필드만 추린 축약 계약이다. 나머지 필드(적 트랙, 자기상태 등)는 B-1을 참고하되 이 계약 문서의 범위 밖이다.
