# 아키텍처

## 디렉토리 구조

소스는 `src/` 아래로 나뉜다.
- `src/onboard/` — UAV 온보드 (비행 중): layer 02..07 + shared/ + ai_stubs/
- `src/gcs/` — 지상통제센터 AI (비행 전): layer 01 info center — set_mission → mission_brief 조립
- `src/mission_pipeline.py` — 01→07 종단 CLI. gcs layer 01 + onboard 를 중립 조합(둘은 서로 import 안 함)

```
src/
├── onboard/
│   ├── __init__.py
│   ├── run.py                    # 온보드 파이프라인 오케스트레이터 (03→07 체인, run_cycle)
│   ├── __main__.py               # CLI 엔트리포인트 (python -m onboard raw.json brief.json)
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── schemas.py            # 레이어 간 공통 스키마 (TypedDict/dataclass)
│   │   └── constants.py          # THREAT_CATALOG, POTENTIAL_OUTCOME_MAP, SEVERITY_ORDER, RAC_MATRIX 등
│   ├── layer_02_sensor/
│   │   ├── __init__.py
│   │   └── mock_source.py        # mock 원시 센서 데이터 생성/로딩
│   ├── layer_03_abstraction/
│   │   ├── __init__.py
│   │   ├── run.py                # 11채널 산출 오케스트레이터
│   │   ├── position_consistency.py   # GPS/IMU 잔차 계산
│   │   ├── link_status.py            # RSSI/SNR 판독
│   │   ├── link_integrity.py         # 체크섬/시퀀스 갭
│   │   ├── encryption_status.py      # 프로토콜 모드 판독
│   │   ├── rf_spectrum.py            # 광대역 이상탐지 (임계값)
│   │   ├── mission_phase.py          # declared vs behavioral 대조
│   │   ├── terrain_class.py          # GIS 조회 + 카메라 stub
│   │   ├── proximity_object.py       # AI stub (고정 detection)
│   │   ├── acoustic_event.py         # 임계값 매칭 + YAMNet stub
│   │   ├── obstacle_proximity.py     # 거리/접근속도 판독
│   │   └── operational_margin.py     # 5개 마진 worst-case 집계
│   ├── layer_04_threat/
│   │   ├── __init__.py
│   │   ├── run.py                # Step A→B→C→D
│   │   ├── catalog.py            # THREAT_CATALOG, SIGNAL_TO_THREAT, PHASE_THREAT_MULTIPLIER, CHANNEL_WEIGHTS
│   │   ├── step_a_phase.py       # 임무 국면 확인
│   │   ├── step_b_mapping.py     # 신호→위협 매핑 (T4 다중채널 특수처리 포함)
│   │   ├── step_c_confidence.py  # 확신도·킬체인단계 산출 (결정론적 + AI 강화판)
│   │   └── step_d_outcome.py     # potential_outcome 매핑
│   ├── layer_05_risk/
│   │   ├── __init__.py
│   │   ├── run.py
│   │   ├── likelihood.py         # base_rate 조회 + posture_shift
│   │   ├── severity.py           # potential_outcome + spare_asset override
│   │   ├── rac_matrix.py         # 6×4 매트릭스 (immutable)
│   │   └── compound.py           # continuous_L/S, urgency_score, cross-check
│   ├── layer_06_response/
│   │   ├── __init__.py
│   │   ├── run.py
│   │   ├── flight_comms.py       # (RAC, kill_chain_stage, threat_category) 조회
│   │   └── payload_nav.py        # threat_event별 payload_action/nav_mode
│   ├── layer_07_planning/
│   │   ├── __init__.py
│   │   ├── run.py
│   │   ├── bearing.py            # threat_category별 방향 결정
│   │   └── altitude.py           # flight_action별 고도 조정량
│   └── ai_stubs/
│       ├── __init__.py
│       ├── yolo_stub.py          # proximity_object AI 채널용
│       ├── segmentation_stub.py  # terrain_class 카메라 보조용
│       └── yamnet_stub.py        # acoustic_event 2차 판정용
├── gcs/
│   ├── __init__.py
│   └── layer_01_info_center/     # 지상 정보 센터 AI (구현됨)
│       ├── __init__.py
│       ├── nlp_extract.py        # 결정론 키워드룰 지시서 해석 (실 NLP 모델 stub)
│       ├── cross_check.py        # NLP 신호/운용자 입력 vs C4I 사실 대조
│       ├── assemble.py           # set_mission → 온보드 MissionBrief 6필드
│       └── run.py                # 2단계 오케스트레이터 (assemble_draft → finalize)
└── mission_pipeline.py           # 01→07 종단 CLI (gcs+onboard 중립 조합)

examples/
├── raw_t1.json / mission_brief_t1.json   # GPS 스푸핑 시나리오
├── raw_t2.json / mission_brief_t2.json   # 사이버(C2 하이재킹)
├── raw_t3.json / mission_brief_t3.json   # 근접 소화기 (정찰)
├── raw_t4.json / mission_brief_t4.json   # 물리 포획 (호송)
├── raw_t7.json / mission_brief_t7.json   # 지형충돌 (수송)
└── mission_brief_strike.json             # 타격 컨텍스트 (High RAC 경로 검증용)

tests/
├── test_constants.py
├── test_schemas.py
├── test_smoke.py
├── helpers/                  # 계약 검증 유틸 (assert_matches_schema 등)
├── layer_02_sensor/
├── layer_03_abstraction/
├── layer_04_threat/
├── layer_05_risk/
├── layer_06_response/
├── layer_07_planning/
└── integration/              # 종단 시맨틱·배선·fixture 검증
```

pytest 는 `pythonpath = ["src"]` (pyproject.toml) 설정으로 `src/` 를 자동 추가한다. 따라서 test import 는 `from onboard.shared import constants` 형태이다.

## 패턴
- **레이어 = 순수 함수**: 각 `src/onboard/layer_XX_*/run.py`는 `run(input: dict, ...) -> dict`. 부수효과 없음. 로깅은 호출자(`src/onboard/run.py`)가 담당.
- **결정론적 + AI 강화판 이중 트랙**: 결정론이 산출한 값에 병렬로 AI 값을 계산하고 교차검증. 불일치 시 결정론 값으로 폴백하되 AI 계산 결과는 `ai_*` 필드로 나란히 보존해 지상국에 통보.
- **레이어 간 계약은 스키마로**: `src/onboard/shared/schemas.py`에 각 레이어의 입/출력 타입을 TypedDict로 선언. 런타임 검증(pydantic 등)은 후순위.
- **AI stub은 별도 모듈**: `ai_stubs/`의 함수를 03 채널이 호출. 나중에 실제 모델로 교체해도 03 채널 코드는 그대로.

## 데이터 흐름

`run_cycle(raw, mission_brief, previous_qualities, cycle_context)` → `{abstraction, threat, risk, response, flight_plan}`

```
raw sensor JSON
  → 03 Sensor Abstraction  → {schema_version, id, ts, channels[11]}
    → 04 Threat Modeling   → {declared_phase, mission_phase_confidence, candidates[], primary, background_exposure_score}
      → 05 Risk Assessment → {candidates[] with rac/compound_urgency_score/priority_rank, ambient_rac?}
        → 06 Response      → {primary_threat_event, flight_action, comms_level, payload_action[], nav_mode, special_action, secondary_threats[], ai_reliability}
          → 07 Flight Plan → {flight_action, target_bearing_deg, altitude_delta_m, replan_scope, reroute_anchor}
```

각 화살표 = JSON-직렬화 가능한 dict 전달. 사이클 = 위 흐름 1회 완주.

각 화살표의 필드 단위 계약(스키마 해설·예시 JSON)은 [`docs/contracts/README.md`](./contracts/README.md) 참고.

## 상태 관리
- 파이프라인 자체는 stateless. 사이클 간 상태(예: `quality_delta` 계산용 이전 사이클 quality)는 호출자가 명시적으로 `previous_state` dict로 넘긴다.
- mission_brief(임무 시작 시 확정되어 사이클 동안 불변)는 파이프라인 시작 시 한 번 로드해 모든 레이어에 read-only로 넘긴다.
- 로그는 파이프라인 밖에서 관리 (JSONL append), 파이프라인은 순수 함수 유지.
