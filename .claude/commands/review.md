---
description: Codex 를 코드 리뷰 에이전트로 이 프로젝트의 변경 사항을 리뷰한다 (read-only, no fixes).
argument-hint: '[--base <ref>] (기본 main)'
allowed-tools: Bash(codex review*), Bash(git:*), Read
---

이 프로젝트의 변경 사항 리뷰는 **Codex 를 코드 리뷰 에이전트로 위임**한다.
직접 판정하지 말고, 아래 절차로 Codex 를 돌리고 결과를 **그대로(verbatim)** 전달한다.

## 절차

1. 스코프 파악:
   ```bash
   git status --short --untracked-files=all
   git diff --shortstat ${BASE:-main}...HEAD
   ```
2. Codex 코드 리뷰 실행 (미병합 diff 를 base 대비 리뷰). `--base` 인자 없으면 `main`:
   ```bash
   codex review --base ${BASE:-main}
   ```
   - `codex review` 는 `--base` 와 커스텀 프롬프트(positional)를 **동시에 못 쓴다**. 커스텀 지시가 꼭 필요하면 `--base` 없이 `codex review "<프롬프트>"` (uncommitted diff) 로 분리 실행한다.
   - Codex CLI: PATH 의 `codex` (nvm). 미설치/미로그인 시 `codex doctor` 로 진단 후 사용자에게 보고.
3. Codex 출력을 요약/의역 없이 그대로 반환한다. 스스로 수정하지 않는다 (read-only).
4. Codex findings 를 아래 표로 매핑해 마무리한다.

## D4D 리뷰 루브릭 (Codex 가 봐야 할 관점)

- **CLAUDE.md CRITICAL**: 레이어 격리(다른 레이어 내부 모듈 import 금지), 결정론-AI 분리, `RAC_MATRIX`/`PHASE_THREAT_MULTIPLIER`/`SIGNAL_TO_THREAT` 하드코딩 불변(함수 인자 오버라이드 금지).
- **MIL-STD-882E SCC-1**: AI 강화판이 결정론적 안전 판정을 오버라이드하지 않는가.
- **스키마 정합**: `RawSensorEnvelope`/`MissionBrief`/각 레이어 OutputSchema 가 D4D 문서·`shared/schemas.py` 와 일치하는가. 레이어 간 JSON-직렬화 dict 계약.
- **fixture 정확성**: 시나리오 값이 실제로 04 `SIGNAL_TO_THREAT` 임계값을 통과하는가(조용히 탈락 없는가). 골든 결정론(`raw_tN.json == build_scenario_envelope(...)`).
- **TDD**: 테스트가 존재하고 의미 있는가(동어반복 아님).
- **Conventional Commits** 형식. 순수 스타일은 의미를 바꾸지 않으면 지적하지 않음.

## 출력 형식 (Codex 결과 매핑)

| 항목 | 결과 | 비고(파일:라인, Codex 지적) |
|------|------|------|
| 아키텍처/레이어 격리 | ✅/❌ | |
| 결정론-AI 분리(SCC-1) | ✅/❌ | |
| 스키마/계약 정합 | ✅/❌ | |
| fixture/임계값 정확성 | ✅/❌ | |
| 테스트(TDD) | ✅/❌ | |

Codex 가 clean 이라고 하면 그대로 clean 보고. 위반은 Codex 지적 원문 + 파일:라인 유지.
