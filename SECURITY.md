# 보안 정책 (Security Policy)

D4D(Decision for Drone) — 국방 UAV 임무기반 위험평가 파이프라인. 안전·보안 결함은
비행 안전과 직결되므로 아래 절차로 처리한다 (NIST SP 800-218 SSDF RV: 취약점 대응).

## 지원 범위

| 버전 | 지원 |
|------|------|
| `main` (최신) | ✅ |
| 그 외 | ❌ |

MVP 단계로 `0.0.x` 만 유지한다. 릴리스 태깅 시 이 표를 갱신한다.

## 취약점 신고

**공개 이슈로 올리지 말 것.** 다음 경로로 비공개 신고한다:

- GitHub **Security Advisories** (Repository → Security → *Report a vulnerability*) — 우선 경로.
- 불가 시 저장소 관리자에게 비공개 연락.

신고 시 포함:
- 영향 레이어/모듈 (예: 04 threat, 05 risk, run.py 오케스트레이터)
- 재현 입력 (raw/mission_brief JSON) 과 기대 vs 실제 동작
- 안전 영향 추정 (예: 오탐으로 인한 잘못된 비행 지시)

## 대응 목표

- **확인(triage):** 신고 후 3영업일 이내 접수 확인.
- **평가:** 결정론 안전 경로(RAC 매트릭스, CFIT 회피, 위협 판정) 결함은 최우선.
- **수정:** TDD 로 재현 테스트 선작성 → 결정론 경로 우선 수정 → golden 재생성.

## 범위 참고

- 결정론 경로(임계값·매트릭스·GIS 조회)와 AI 강화판은 분리 설계이며, AI 강화판은
  참고지표로만 산출된다(SCC-1). RAC 매트릭스를 우회/변조하는 결함은 심각도 최상.
- CI(GitHub Actions)는 액션을 커밋 SHA 로 고정하고 최소권한(`contents: read`)으로 운영한다.
