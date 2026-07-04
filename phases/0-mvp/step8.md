# Step 8: layer-07-flight-planning

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/CLAUDE.md`
- `/src/onboard/shared/schemas.py` (`FlightPlanOutput`, `ResponseOutput`)
- `/src/onboard/shared/constants.py` (`ALTITUDE_DELTA_PREVENTIVE_M`, `POSTURE_ELEVATE_ALTITUDE_M`, `ALTITUDE_DELTA_TERRAIN_M`)
- `/src/onboard/layer_06_response/run.py` (Step 7)
- `/src/onboard/layer_04_threat/run.py` (`cycle_context` 필드가 여기서 07으로 전달됨)

D4D 원문 문서 (레포 내 `/docs/D4D/`):

- `/docs/D4D/07. Flight Planning.md` — replan_scope 매핑(RTL=LOCAL, REROUTE류=FULL, POSTURE_ELEVATE=LOCAL, MAINTAIN=NONE), threat_category별 bearing 결정(PHYSICAL 반대방향, REMOTE bearing 있으면 반대 없으면 last_known_good, NAVIGATION은 optimal_terrain), altitude_delta_m 표
- `/docs/D4D/F-1. Flight Planning Spec.md` — 손계산 검증

## 작업

06의 `ResponseOutput`과 04의 `cycle_context`, 그리고 03의 `candidates[].context`(bearing_deg)를 받아 MAVLink급 지시값 산출.

`context`는 04의 candidates에서 개별 threat별로 넘어와야 하는데, 06이 `ResponseOutput`에 다시 담아주지 않았다. MVP에서는 08의 `run()` 시그니처에 별도 인자로 넘긴다.

### 1) 파일 구성

`src/onboard/layer_07_planning/`:

- `run.py`
- `bearing.py` — threat_category별 방향 결정
- `altitude.py` — flight_action별 고도 조정량

### 2) `bearing.py`

```python
def compute_bearing(threat_category: str | None,
                    threat_bearing_deg: float | None,
                    cycle_context: dict) -> tuple[float | None, str | None]:
    """
    return (target_bearing_deg, reroute_anchor)

    PHYSICAL:
      threat_bearing_deg 있으면 (b + 180) % 360, anchor="threat_reverse(channel)"
      없으면 cycle_context["lowest_exposure_bearing_deg"], anchor="terrain_fallback"
    REMOTE:
      threat_bearing_deg 있으면 위와 동일, anchor="threat_reverse(channel)"
      없으면 (None, "last_known_good_position")
    NAVIGATION:
      cycle_context["optimal_terrain_bearing_deg"], anchor="optimal_terrain"
    None (위협 없음):
      (None, None)
    """
```

### 3) `altitude.py`

```python
def compute_altitude_delta(flight_action: str) -> tuple[int, str | None]:
    """
    return (delta_m, anchor_hint)

    ALTITUDE_CHANGE          → (+15, "altitude_only")
    POSTURE_ELEVATE          → (+25, "altitude_only")
    ALTITUDE_CHANGE_REROUTE  → (+50, None)  # anchor는 bearing에서 결정
    RTL / REROUTE / MAINTAIN → (0, None)
    """
```

### 4) `run.py`

```python
def run(response: ResponseOutput,
        primary_context: dict | None,
        cycle_context: dict) -> FlightPlanOutput:
    """
    primary_context = 04의 candidates[0].context. 없거나 위협 없으면 None.
    """
    scope = _REPLAN_SCOPE[response["flight_action"]]

    threat_bearing = None
    if primary_context is not None:
        threat_bearing = primary_context.get("bearing_deg")

    bearing, anchor = bearing.compute_bearing(
        response["threat_category"], threat_bearing, cycle_context,
    )
    delta, alt_anchor = altitude.compute_altitude_delta(response["flight_action"])

    final_anchor = anchor or alt_anchor
    return {
        "flight_action": response["flight_action"],
        "target_bearing_deg": bearing,
        "altitude_delta_m": delta,
        "replan_scope": scope,
        "reroute_anchor": final_anchor,
    }
```

`_REPLAN_SCOPE`:

```python
_REPLAN_SCOPE: dict[str, str] = {
    "RTL":                     "LOCAL",
    "REROUTE":                 "FULL",
    "ALTITUDE_CHANGE_REROUTE": "FULL",
    "ALTITUDE_CHANGE":         "LOCAL",
    "POSTURE_ELEVATE":         "LOCAL",
    "MAINTAIN":                "NONE",
}
```

### 5) 테스트

`tests/layer_07_planning/test_bearing.py`:
- PHYSICAL + threat_bearing=45 → (225.0, "threat_reverse(channel)")
- PHYSICAL + threat_bearing=None + cycle_context.lowest_exposure_bearing_deg=90 → (90, "terrain_fallback")
- REMOTE + threat_bearing=None → (None, "last_known_good_position")
- NAVIGATION + cycle_context.optimal_terrain_bearing_deg=180 → (180, "optimal_terrain")
- None + None → (None, None)

`tests/layer_07_planning/test_altitude.py`:
- ALTITUDE_CHANGE → (15, "altitude_only")
- POSTURE_ELEVATE → (25, "altitude_only")
- ALTITUDE_CHANGE_REROUTE → (50, None)
- RTL, REROUTE, MAINTAIN → (0, None)

`tests/layer_07_planning/test_run_golden.py`:
- t3 (PHYSICAL, RTL): `flight_action="RTL"`, `target_bearing_deg`가 primary_context.bearing_deg의 반대각, `altitude_delta_m=0`, `replan_scope="LOCAL"`, `reroute_anchor="threat_reverse(channel)"`
- t7 (NAVIGATION, ALTITUDE_CHANGE_REROUTE): `altitude_delta_m=50`, `target_bearing_deg == cycle_context.optimal_terrain_bearing_deg`, `replan_scope="FULL"`, `reroute_anchor="optimal_terrain"`
- 정상 (MAINTAIN): 전부 0/None, `replan_scope="NONE"`

## Acceptance Criteria

```bash
python3 -m pytest tests/layer_07_planning/ -v
```

- 모든 테스트 PASSED

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - waypoint 좌표를 계산하지 않는가? (MAVLink 상위 지시값까지만)
   - `flight_action` 미지원 값(문자열 매치 실패)이 들어오면 KeyError로 명시적 실패하는가?
3. 결과에 따라 `phases/0-mvp/index.json`의 step 8을 업데이트한다.

## 금지사항

- 실제 웨이포인트 시퀀스나 궤적 최적화를 계산하지 마라. 이유: ARCHITECTURE.md 스코프 경계 — 오토파일럿 몫.
- `terrain_class` 채널을 직접 다시 조회하지 마라. 이유: 04가 이미 `cycle_context.optimal_terrain_bearing_deg`, `lowest_exposure_bearing_deg`로 정리해 넘긴다. 07은 소비만.
- MAINTAIN에서 `altitude_delta_m=0`이 아닌 값을 반환하지 마라. 이유: MAINTAIN = 아무것도 안 함.
