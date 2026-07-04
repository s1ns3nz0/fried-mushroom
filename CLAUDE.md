# 프로젝트: D4D (Decision for Drone)

## 개요
국방 UAV 임무기반 위험평가·자동대응 파이프라인. MBCRA(Mission-Based Cyber Risk Assessment, DoD Cyber OT&E Guidebook 2025) 방법론을 UAV 작전 위험평가로 확장한다. 6계층(Sensor → Sensor Abstraction → Threat Modeling → Risk Assessment → Response → Flight Planning)이 사이클마다 순차 실행되어, 원시 센서 데이터에서 MAVLink급 비행 지시값까지 산출한다.

## 기술 스택
- Python 3.11+
- 순수 함수형 파이프라인 (레이어 = 순수 함수, JSON I/O)
- pytest (단위/통합 테스트)
- 표준 라이브러리 우선. 외부 의존성은 pytest, numpy 정도로 최소화
- 데이터 스키마: TypedDict / dataclass (런타임 검증은 후순위)

## 코드 구조
소스는 `src/` 아래 두 축으로 나뉜다:
- `src/onboard/` — UAV 온보드 파이프라인 (layer 02..07 + shared/ + ai_stubs/). MVP 스코프.
- `src/gcs/` — 지상통제센터 AI (layer 01). MVP 밖 skeleton (`layer_01_info_center/`).

공유 계약(`shared/schemas.py`, `shared/constants.py`)은 `src/onboard/shared/` 에 위치하며 모든 온보드 레이어가 이곳에서 import 한다.

## 아키텍처 규칙
- CRITICAL: 각 온보드 레이어는 `src/onboard/{layer_name}/` 패키지로 분리. 레이어 간 통신은 오직 JSON-직렬화 가능한 dict로만. 레이어가 다른 레이어의 내부 모듈을 직접 import 금지.
- CRITICAL: 결정론적 로직(임계값 비교, 매트릭스 조회, GIS 조회, 잔차 계산)과 AI 강화판(로그오즈 결합, continuous_L/S)은 반드시 분리. AI 강화판은 병렬 참고지표로만 산출하고 결정론적 값이 최종 판정을 지배한다. RAC 매트릭스는 AI가 절대 바꾸지 않는다 (MIL-STD-882E SCC-1 원칙).
- CRITICAL: 05 Risk Assessment의 `RAC_MATRIX`(6×4)와 04 Threat Modeling의 `PHASE_THREAT_MULTIPLIER`, `SIGNAL_TO_THREAT` 매핑은 `src/onboard/shared/constants.py` 에 하드코딩 상수로 두고 함수 인자로 오버라이드 불가.
- 03 Sensor Abstraction Layer의 AI 채널(proximity_object, terrain_class 보조, acoustic YAMNet 2차)은 MVP에서 stub으로 고정값 반환. 실제 모델 로딩은 후순위.
- 각 레이어 출력은 정형 스키마를 따라야 한다 (D4D 문서 각 레이어 "최종 출력 스키마" 표 참조).

## 개발 프로세스
- CRITICAL: 새 기능 구현 시 반드시 테스트를 먼저 작성하고, 테스트가 통과하는 구현을 작성할 것 (TDD)
- CRITICAL: D4D 문서의 파라미터 표(예: 05 RAC_MATRIX, 04 CHANNEL_WEIGHTS)에 나온 값을 임의로 바꾸지 말 것. 값 변경은 D4D 문서를 먼저 수정한 뒤 코드에 반영.
- 커밋 메시지는 conventional commits 형식 (feat:, fix:, docs:, refactor:, test:)
- 레이어별 통합 테스트는 D4D 문서의 예시 JSON(입력/출력)을 골든 케이스로 사용한다.

## 명령어
```bash
python3 -m pytest                            # 전체 테스트
python3 -m pytest tests/layer_04_threat/     # 특정 레이어
python3 -m onboard.run examples/scenario_t3.json  # 종단 실행 (pythonpath=src)
```
