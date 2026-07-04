# D4D (Decision for Drone)

국방 UAV 임무기반 위험평가·자동대응 파이프라인.
MBCRA (DoD Cyber OT&E Guidebook 2025) 방법론을 UAV 작전 위험평가로 확장한 6계층 파이프라인.

**센서 원시 데이터 → 위협 모델링 → 위험 평가 → 대응 → MAVLink급 비행 지시값**

---

## 문서 지도

작업 시작 전 반드시 읽어야 할 문서:

| 문서 | 목적 |
|------|------|
| [`CLAUDE.md`](./CLAUDE.md) | 프로젝트 CRITICAL 규칙 (레이어 격리, 결정론-AI 분리, RAC_MATRIX 불변) |
| [`docs/PRD.md`](./docs/PRD.md) | 제품 요구사항 |
| [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) | 6계층 구조, 디렉토리 레이아웃, JSON I/O 계약 |
| [`docs/ADR.md`](./docs/ADR.md) | 기술 스택 결정 근거 |
| [`docs/D4D/*.md`](./docs/D4D/) | 각 레이어별 상세 스펙 + 최종 출력 스키마 표 + 예시 JSON |
| [`phases/0-mvp/`](./phases/0-mvp/) | MVP 10개 step 지시서 (step0 → step9) |

---

## 팀 & 브랜치 배정

| 이름 | 역할 | 담당 브랜치 | 담당 step |
|------|------|-------------|-----------|
| **양진수** | Lead | `feat/bootstrap` → `feat/orchestrator` | step0 (skeleton), step1 (shared schemas/constants), step9 (E2E orchestrator) |
| **김수지** | Dev | `feat/layer-02-sensor`, `feat/layer-03-abstraction` | step2 (mock sensor), step3 (deterministic channels), step4 (AI stub channels) |
| **김호빈** | Dev | `feat/layer-04-threat`, `feat/layer-05-risk` | step5 (threat modeling), step6 (risk assessment) |
| **루닛** | Dev | `feat/layer-06-response`, `feat/layer-07-planning` | step7 (response), step8 (flight planning) |

### 진행 순서 (반드시 지킬 것)

```
[T0] 양진수: feat/bootstrap 에서 step0 + step1 완료 → PR → main merge
              ↓ (schema/constants 확정)
[T1] 김수지, 김호빈, 루닛 병렬 진행
       - 각자 자기 layer 브랜치에서 step 실행
       - upstream layer 미완성 시 D4D 문서의 예시 JSON 을 mock fixture 로 사용
              ↓ (모든 layer merge 완료)
[T2] 양진수: feat/orchestrator 에서 step9 (E2E) → PR → main merge
```

**T0 전에는 layer 브랜치 작업 착수 금지.** shared schema 가 안 잡히면 downstream 재작업 대량 발생.

---

## 초기 세팅 (팀원용)

### 1. Prerequisites

- **Python 3.11+** (`python3 --version` 로 확인)
- **git 2.30+**
- (선택) **GitHub CLI (`gh`)** — PR 생성 편의

### 2. 클론 & 브랜치 checkout

```bash
git clone https://github.com/s1ns3nz0/fried-mushroom.git
cd fried-mushroom

# 자기 담당 브랜치로 이동 (예: 김수지)
git fetch origin
git checkout feat/layer-02-sensor

# T0 완료 후에는 main 을 자기 브랜치에 rebase
git fetch origin
git rebase origin/main
```

### 3. Python 환경

```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows

# step0 완료 후 pyproject.toml 생기면
pip install -e '.[dev]'
```

### 4. 테스트 실행

```bash
python3 -m pytest                            # 전체
python3 -m pytest tests/layer_04_threat/     # 특정 레이어
python3 -m onboard.run examples/scenario_t3.json  # E2E (step9 이후)
```

### 5. Harness 실행 (Claude Code 사용자 대상)

```bash
python3 scripts/execute.py 0-mvp             # phases/0-mvp/ 순차 실행
python3 scripts/execute.py 0-mvp --push      # 실행 후 push
```

harness 워크플로우 상세: [`.claude/commands/harness.md`](./.claude/commands/harness.md)

---

## 개발 워크플로우

### 각 step 착수 전

1. `phases/0-mvp/step{N}.md` 를 읽는다.
2. 지정된 참조 문서(`CLAUDE.md`, `docs/ARCHITECTURE.md`, D4D 스펙)를 읽는다.
3. 이전 step 산출 파일(있다면)을 읽어 설계 의도를 파악한다.

### TDD 강제

- **CRITICAL**: 테스트를 먼저 작성한다. 통과하는 구현을 나중에 작성한다.
- 골든 케이스는 D4D 문서의 예시 입력/출력 JSON 을 그대로 사용한다.

### 커밋 규칙

- Conventional Commits 형식: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- 예: `feat(layer-04): add threat channel weighting`
- CLAUDE.md 의 CRITICAL 규칙 위반 시 커밋 금지 (아키텍처 리뷰에서 반려)

### PR & Merge

- PR 대상: **`main`**
- 리뷰어: 팀원 **1명** approve 필요
- Merge 전략: **Squash merge** (main history 깔끔 유지)
- CI(pytest) 통과 필수

### 충돌 방지

- **shared schema (step1 산출)** 는 lock 상태. 변경 필요 시 반드시 Lead(양진수)에게 요청.
- downstream layer 는 upstream 미완성 시 D4D 예시 JSON 을 mock 으로 사용.
- 다른 사람 branch 에 직접 커밋 금지.

---

## 아키텍처 CRITICAL 규칙 요약

전문은 [`CLAUDE.md`](./CLAUDE.md) 참조. 위반 시 PR 반려.

1. **레이어 격리**: `src/onboard/layer_XX/` 는 다른 layer 의 내부 모듈을 import 금지. 통신은 오직 JSON-직렬화 가능한 dict.
2. **결정론 vs AI 분리**: RAC_MATRIX(6×4) 는 AI 가 절대 변경 불가 (MIL-STD-882E SCC-1). AI 강화판은 병렬 참고지표.
3. **하드코딩 상수**: `RAC_MATRIX`, `PHASE_THREAT_MULTIPLIER`, `SIGNAL_TO_THREAT`, `CHANNEL_WEIGHTS` 는 모듈 상수. 함수 인자로 오버라이드 금지.
4. **AI 스텁 고정**: layer 03 의 AI 채널(proximity_object, terrain_class 보조, acoustic YAMNet 2차) 은 MVP 에서 stub 고정값 반환.
5. **출력 스키마**: 각 layer 출력은 D4D 문서의 "최종 출력 스키마" 표를 그대로 따른다.

---

## 자주 쓰는 명령어

```bash
# 자기 브랜치 최신화
git fetch origin && git rebase origin/main

# 커밋 + 푸시
git add <files>
git commit -m "feat(layer-XX): <설명>"
git push origin feat/layer-XX-<name>

# PR 생성 (gh CLI)
gh pr create --base main --title "feat(layer-XX): <설명>" --body "..."

# 테스트
python3 -m pytest -v
python3 -m pytest tests/layer_04_threat/ -v

# harness (Claude Code)
python3 scripts/execute.py 0-mvp
```

---

## 질문 & 소통

- **아키텍처/스키마 관련**: Lead (양진수) 에게 문의
- **레이어 간 인터페이스**: 인접 레이어 담당자와 직접 논의
- **버그/이슈**: GitHub Issues 로 등록
