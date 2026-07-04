# PRD: D4D (Decision for Drone)

## 목표
UAV 작전 중 발생하는 다양한 위협(GPS 스푸핑, 사이버 하이재킹, 근접 소화기, 물리 포획, 레이저, 지형충돌 등)을 임무 성공에 대한 기여도 기준으로 평가하고, 사이클마다 자동으로 최적의 비행/통신/무장/항법 대응을 산출하는 온보드 AI 파이프라인.

## 사용자
- UAV 온보드 컴퓨트: 파이프라인이 매 사이클 실행되어 오토파일럿(PX4/ArduPilot)에 MAVLink급 지시값을 넘긴다.
- 지상통제센터 운용자: 이륙 전 mission_brief를 확정하고, 비행 중에는 파이프라인이 산출한 상태·2순위 위협 요약을 통보받는다.

## 핵심 기능
1. **6계층 파이프라인 (사이클 단위 실행)**
   - 02 UAV Sensor Layer — 원시 센서 데이터 수집 (본 레포는 mock 입력)
   - 03 Sensor Abstraction Layer — 원시 데이터를 11개 semantic 채널로 재구성 (position_consistency, link_status, terrain_class, proximity_object, acoustic_event 등)
   - 04 Threat Modeling — 채널→위협(T1~T7) 매핑, 확신도/킬체인단계/potential_outcome 산출
   - 05 Risk Assessment — L(발생가능성)×S(심각도) 매트릭스 조회로 RAC(High/Serious/Medium/Low), compound_urgency_score 정렬
   - 06 Response — flight_action/comms_level/payload_action/nav_mode 결정
   - 07 Flight Planning — replan_scope, target_bearing_deg, altitude_delta_m 산출
2. **MBCRA 기반 3단계 구조** — 핵심기능 식별 → 위협경로 이해 → 위험 우선순위화
3. **결정론적 + AI 강화판 이중 트랙** — 매 단계 결정론적 값이 정답이고 AI는 병렬 참고지표. 교차검증 실패 시 결정론적 값으로 폴백.

## MVP 제외 사항
- 실제 AI 모델 로딩 (YOLOv8n, MobileNetV3, YAMNet, 1D-CNN GPS 스푸핑) — stub 함수로 대체
- 지상통제센터 AI (01, B-1) — mission_brief를 하드코딩 fixture로 대체
- RAG 코퍼스 축적 및 CHANNEL_WEIGHTS 재학습
- 오토파일럿 연동 (07 출력을 MAVLink로 실제 송신)
- UI (지상통제센터 대시보드, 승인 화면)
- 실제 데이터셋 다운로드 (02 문서의 AI Hub/GitHub 데이터셋)
- HMM 기반 임무국면 추적, 오토인코더 기반 rf_spectrum 이상탐지 (문서의 TO-DO 항목)

## 성공 기준
- `examples/scenario_t3.json`(근접 소화기 위협) 입력을 넣으면 06이 `flight_action=RTL`, `payload_action=[DATA_WIPE]`를 산출한다.
- 6개 레이어 각각에 대해 D4D 문서의 예시 JSON을 골든 케이스로 통과.
- 결정론적 경로와 AI 강화판이 각각 계산되고, 교차검증 결과(`ai_reliability`)가 통보 페이로드에 포함된다.

## 디자인
- UI 없음. CLI로 JSON 입력받아 JSON 출력.
- 로그는 사이클별 각 레이어 출력을 JSON Lines로 append.
