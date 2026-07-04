# Step 1: shared-schemas-constants

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-003, ADR-004)
- `/pyproject.toml` (Step 0 산출물)
- `/src/onboard/__init__.py` (Step 0 산출물)

또한 아래 D4D 원문 문서를 반드시 읽는다 (레포 내 `/docs/D4D/`):

- `/docs/D4D/03. Sensor Abstraction Layer.md` — 11개 채널 payload 필드 목록, quality/state/quality_delta 정의
- `/docs/D4D/04. Threat Modeling.md` — THREAT_CATALOG (T1~T7), SIGNAL_TO_THREAT 매핑표, PHASE_THREAT_MULTIPLIER, CHANNEL_WEIGHTS 표, CONFIDENCE_BY_MATCH_COUNT, potential_outcome 매핑
- `/docs/D4D/05. Risk Assessment.md` — mission_context 4종, BASE_RATE 표(PHYSICAL 8칸/REMOTE·NAVIGATION 4칸), l_value_to_class 임계값, RAC_MATRIX 6×4, SEVERITY_ORDER
- `/docs/D4D/06. Response.md` — threat_category 3분류, flight_action/comms_level 테이블
- `/docs/D4D/07. Flight Planning.md` — replan_scope 매핑, altitude_delta_m 표
- `/docs/D4D/A-1. 추상 결과 세부 내용.md` — 03 payload 필드 확정본
- `/docs/D4D/서비스 소개.md` — 프로젝트 개요·5레이어 아키텍처 배경

## 작업

레이어 간 계약이 되는 모든 스키마와 상수를 두 파일에 모은다. 이 값들은 이후 step에서 import 전용이며 함수 인자로 오버라이드하지 않는다.

### 1) `src/onboard/shared/schemas.py`

`TypedDict`로 레이어 간 I/O 스키마를 선언한다. 런타임 검증(`__required_keys__`)은 넣지 않는다. IDE 힌트용.

시그니처 수준 요구사항 (payload 내부 필드는 D4D 문서를 그대로 반영):

```python
from typing import TypedDict, Literal, NotRequired

ChannelState = Literal["normal", "degraded", "anomaly"]

class ChannelOutput(TypedDict):
    channel: str
    state: ChannelState
    quality: float
    quality_delta: float
    payload: dict  # 채널별 payload 타입은 이 step에서는 dict로 남긴다

class AbstractionOutput(TypedDict):
    schema_version: str
    id: str
    ts: int
    channels: list[ChannelOutput]

class ThreatCandidate(TypedDict):
    threat_event: str        # "T1" ~ "T7"
    match_count: int
    confidence: float
    confidence_source: Literal["ai", "deterministic"]
    kill_chain_stage: Literal["초기", "중기", "후기"]
    potential_outcome: str
    context: NotRequired[dict]  # {bearing_deg, bearing_source, class}

class ThreatModelingOutput(TypedDict):
    declared_phase: str
    mission_phase_confidence: float
    candidates: list[ThreatCandidate]
    primary: ThreatCandidate | None
    background_exposure_score: float
    cycle_context: NotRequired[dict]  # {optimal_terrain_bearing_deg, lowest_exposure_bearing_deg}

class RiskCandidate(ThreatCandidate):
    rac: Literal["High", "Serious", "Medium", "Low"]
    l_class_final: Literal["A", "B", "C", "D", "E", "F"]
    severity_label_final: Literal["Catastrophic", "Critical", "Marginal", "Negligible"]
    compound_risk_assessment: dict
    compound_urgency_score: float
    priority_rank: int

class RiskAssessmentOutput(TypedDict):
    candidates: list[RiskCandidate]
    ambient_rac: NotRequired[Literal["Medium", "Low"] | None]

class ResponseOutput(TypedDict):
    primary_threat_event: str | None
    rac: str
    kill_chain_stage: str | None
    threat_category: Literal["PHYSICAL", "REMOTE", "NAVIGATION"] | None
    flight_action: str
    comms_level: str
    payload_action: list[str]
    nav_mode: str | None
    special_action: str | None
    secondary_threats: list[dict]
    ai_reliability: Literal["normal", "low"]

class FlightPlanOutput(TypedDict):
    flight_action: str
    target_bearing_deg: float | None
    altitude_delta_m: int
    replan_scope: Literal["NONE", "LOCAL", "FULL"]
    reroute_anchor: str | None

class MissionBrief(TypedDict):
    sortie_id: str
    mission_context: Literal["정찰", "타격", "호송", "수송"]
    posture: dict            # {watchcon, defcon, infocon}
    drone_profile: dict      # {armament: [{expendable: bool, ...}, ...], spare_asset_available: bool, ...}
    corridor: dict           # {waypoints, bases: {emergency, alternate}}
    weights: dict            # {stealth, survival, info_value, timeliness}
```

11 채널 개별 payload 스키마(예: `PositionConsistencyPayload`)는 만들지 말고 `dict`로 두라. 이유: MVP 스코프. 다음 step들이 각자 채널에서 실제 필드를 채우며 검증한다.

### 2) `src/onboard/shared/constants.py`

D4D 문서 표를 그대로 옮긴다. 값 하나라도 변경 금지. 문서에 없는 값을 임의로 추가하지 말 것.

- `THREAT_CATALOG: dict[str, str]` — T1~T7 → 한글 이름
- `POTENTIAL_OUTCOME_MAP: dict[str, str]` — threat_event → potential_outcome (04 Step D 표)
- `OUTCOME_TO_SEVERITY: dict[str, str]` — potential_outcome → severity_label (04 Step D 표)
- `SEVERITY_ORDER: dict[str, int]` — Catastrophic=1, Critical=2, Marginal=3, Negligible=4
- `SIGNAL_TO_THREAT: list[dict]` — 04 Step B 매핑표 (channel, condition, threat). condition은 문자열로 두고 실제 판정은 05 이후 step에서 lambda/함수로 컴파일한다.
- `T4_MULTI_CHANNEL_CONDITIONS: list[dict]` — 04 Step B의 T4 특수 3조건
- `PHASE_THREAT_MULTIPLIER: dict[tuple[str, str], float]` — 04 Step A 표. 표에 없는 조합은 기본 1.0 (조회 시 `.get(..., 1.0)`).
- `CHANNEL_WEIGHTS: dict[str, float]` — 04 Step C 표
- `CONFIDENCE_BY_MATCH_COUNT: dict[int, float]` — {1: 0.7, 2: 0.9, 3: 0.95} (3 이상은 0.95 상한)
- `W_MIN: float = 0.20`, `Q_MIN: float = 0.65`, `CROSS_CHECK_TOLERANCE: float = 0.15`
- `MISSION_CONTEXTS: tuple = ("정찰", "타격", "호송", "수송")`
- `BASE_RATE_PHYSICAL: dict[tuple[str, str], float]` — 05의 (threat_event, mission_context) → base_rate (T3/T4만)
- `BASE_RATE_REMOTE_NAV: dict[str, float]` — T1/T2/T5/T7 단일값
- `L_VALUE_TO_CLASS_THRESHOLDS: list[tuple[float, str]]` — [(0.5, "A"), (0.3, "B"), (0.15, "C"), (0.05, "D"), (0.01, "E")], 그 밑은 "F"
- `RAC_MATRIX: dict[tuple[str, int], str]` — (l_class, severity_num) → RAC. 6×4 = 24개 전부.
- `RAC_ORDER: dict[str, int]` — High=1, Serious=2, Medium=3, Low=4 (교차검증용 거리 계산)
- `CONTINUOUS_S_BASE_SCORE: dict[str, float]` — {Catastrophic: 0.90, Critical: 0.60, Marginal: 0.30, Negligible: 0.10}
- `CONTINUOUS_S_TO_NUM_THRESHOLDS: list[tuple[float, int]]` — [(0.75, 1), (0.45, 2), (0.20, 3)], 그 밑은 4
- `AMBIENT_EXPOSURE_THRESHOLD: float = 0.7` — 05
- `TIME_TO_COLLISION_THRESHOLD_S: float = 3.0`
- `QUALITY_DELTA_DROP_THRESHOLD: float = -0.3`
- `ALTITUDE_DELTA_PREVENTIVE_M: int = 15`
- `POSTURE_ELEVATE_ALTITUDE_M: int = 25`
- `ALTITUDE_DELTA_TERRAIN_M: int = 50`

`RAC_MATRIX`를 하드코딩 상수로 두는 이유는 ADR-003(SCC-1 원칙). 이 dict를 mutable로 노출하지 말고 `types.MappingProxyType`으로 감싸 read-only로 만든다.

### 3) 테스트

`tests/test_constants.py`:

- `RAC_MATRIX`가 24개 키를 가진다 (6 × 4)
- `RAC_MATRIX[("A", 1)] == "High"`, `RAC_MATRIX[("F", 4)] == "Low"` — 매트릭스 네 코너 검증
- `POTENTIAL_OUTCOME_MAP["T2"] == "hull_loss"`, `OUTCOME_TO_SEVERITY["hull_loss"] == "Catastrophic"`
- `SEVERITY_ORDER["Catastrophic"] < SEVERITY_ORDER["Negligible"]`
- `RAC_MATRIX`를 수정하려고 하면 `TypeError` (MappingProxyType 확인)
- `PHASE_THREAT_MULTIPLIER.get(("LOITER_ROI", "T3"), 1.0) == 1.1`
- `CHANNEL_WEIGHTS["proximity_object"] == 0.40`
- `MISSION_CONTEXTS`에 4종이 정확히 있다

`tests/test_schemas.py`:

- `ChannelOutput`, `ThreatCandidate`, `ResponseOutput` 등이 정의돼 있고 필수 키 이름이 문서와 일치 (`typing.get_type_hints` 로 확인)

## Acceptance Criteria

```bash
python3 -m pytest tests/test_constants.py tests/test_schemas.py -v
```

- 모두 PASSED

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - `ADR-003` 원칙 대로 `RAC_MATRIX`가 immutable인가?
   - 값이 D4D 문서 표와 100% 일치하는가? (T3/LOITER_ROI = 1.1, RAC[A,1]=High 등 스팟체크)
   - 외부 의존성을 추가하지 않았는가?
3. 결과에 따라 `phases/0-mvp/index.json`의 step 1을 업데이트한다.

## 금지사항

- 값을 임의로 반올림·정정하지 마라. D4D 문서 값을 그대로 옮긴다. 이유: RAG 재학습·손계산 검증이 문서 값 기준.
- 채널별 payload TypedDict를 세밀하게 만들지 마라. 이유: 아직 각 채널이 실제로 어떤 필드를 채우는지 다음 step에서 결정된다. 지금 세부화하면 다음 step에서 재수정 필요.
- `pydantic` 등 검증 라이브러리를 도입하지 마라. 이유: ADR-004 (런타임 검증은 후순위).
- `src/onboard/shared/schemas.py`에 함수를 정의하지 마라. 이유: 이 파일은 타입 선언 전용.
