# GCS Layer 01 — 아키텍처 재검토 (grill-me 세션 기록)

날짜: 2026-07-04 · 범위: `src/gcs/layer_01_info_center/` 전체 파이프라인 + `infra/dashboard`/`infra/log` 연동 지점
방법: `01. 지상 정보 센터 AI.md` / `B-1. 지상통제센터 AI 세부.md` / 2026-07-04 설계 스펙 2건 + 실제 코드(run.py, nlp_extract.py, cross_check.py, mettc_assemble.py, project_brief.py, c4i_schema.py, log_server.py, gcs.js)를 대조하며 6단계 파이프라인을 순회. 각 분기마다 질문 → 권장안 → 결정을 기록한다.

## 요약

문서·단위테스트 수준에서는 설계가 탄탄하다(결정론/AI stub 분리, 승인 게이트, override 감사기록 등). 하지만 **실제 배선(dashboard→log_server→layer01)을 코드로 추적한 결과 P0급 간극 2건**을 발견했다 — 둘 다 "문서가 약속한 안전장치가 런타임에는 존재하지 않는다"는 동일한 패턴이다.

## P0 — 우선 수정 대상

### 1. `finalize()` 승인 게이트가 실제 대시보드 경로에서 사용되지 않음

- `run.py`의 `finalize()`는 override 타입검증·병합·감사기록(`applied_overrides`)·`mettc_state` 오염 방지까지 갖춘, 문서가 강조하는 "AI는 후보만, 최종 결정은 사람" 원칙의 구현체다.
- 그러나 `infra/log/log_server.py`에는 `/gcs/finalize` 엔드포인트가 없다. `/gcs/assemble`(draft 생성)과 `/gcs/run`(온보드 실행)만 존재.
- `infra/dashboard/static/gcs.js`: `loadFromLayer01()`이 `draft_brief`로 폼을 채우고(`fillForm`), 운용자가 폼을 편집한 뒤 `runPipeline()`을 누르면 `collectBrief()`가 폼 값을 모아 자체 JS 검증(`validateBrief`, 범위 체크 수준)만 거쳐 `/gcs/run`으로 직행한다.
- 결과: 문서상 승인 게이트의 실제 구현체는 테스트된 `finalize()`가 아니라 느슨한 클라이언트 JS 검증 경로다. 운용자가 폼에서 뭘 바꿨는지에 대한 감사기록도 없다(applied_overrides 상당물 부재).
- **결정: P0 결함으로 기록, 우선 수정.** 후속 조치: `/gcs/finalize` 엔드포인트 추가 + `gcs.js`가 `/gcs/run` 전에 이를 거치도록 변경. 폼 편집분은 `overrides` dict로 매핑해 `finalize`의 타입검증/감사기록을 그대로 태운다.

### 2. `no_fly_zones`가 온보드로 전달되지 않음

- `mettc_assemble.py`는 `C.no_fly_zones`를 채우지만, `project_brief.py`의 MissionBrief 6필드(`sortie_id, mission_context, posture, drone_profile, corridor, weights`)에는 no_fly_zones 자리가 없다.
- `grep -r no_fly_zone src/onboard` → 매치 없음. 07 Flight Planning을 포함해 온보드 어디에도 참조가 없다.
- 즉 운용자가 금지구역을 등록해도 비행 경로 계획이 이를 실제로 회피하지 않는다. `higher_intent`/`unit_mission`처럼 "의도적으로 온보드에 안 내려가는 참고용 필드"와는 성격이 다르다 — 안전 관련 데이터 유실.
- **결정: P0 결함으로 기록, 우선 수정.** 후속 조치: MissionBrief에 no_fly_zones 필드 추가(corridor와 동급 취급), 07 `route.py`가 회랑 생성/검증 시 참조하도록 확장. CLAUDE.md 하드 제약 목록에 corridor 이탈과 동급으로 명시. TDD로 골든케이스 추가.

## 브랜치별 결정 사항 (경합 없음 — 현행 유지)

| # | 단계 | 쟁점 | 결정 | 후속 조치 |
|---|---|---|---|---|
| ① | 수집 | 승인 대기 중 C4I 스냅샷이 stale해질 수 있음 | 현행 유지(MVP) | stale window 상한(예: 60초) 경고만 추가 |
| ② | NLP | stub→실 모델 전환 시 confidence 추적성 상실 위험 | SCC-1류 불변 제약 명시 | B-1/CLAUDE.md에 "실 NLP confidence 도입 후에도 cross_check 판정 로직은 결정론 고정" CRITICAL 규칙 추가 |
| ③ | 대조 | `_boost()`가 상향 전용, 반박 증거 무시 | 의도된 보수적 설계로 유지 | "하향 조정은 의도적으로 미구현(안전측 편향)"임을 B-1에 명문화 |
| ④ | 대조 매칭 | `_track_evidence()`의 label 부분문자열 매칭 오탐지 가능 | MVP로는 충분 | 실 C4I 연동 시점에 track_id/kind 기반 구조화 매칭으로 재검토 — 백로그 등재 |
| ⑤ | 조립 | `civil_sensitivity_estimate` 단일값이 지역 국소 변화를 과소평가할 수 있음 | 현 단일값 유지(05가 임무 단위 계산이므로 구조적 정합) | known-limitations에 "구간 이동 시나리오는 과소평가 위험" 명시 |
| ⑥ | 승인 | override 시 `mettc_state` 전체가 결과에서 빠짐(stale state 노출 방지 우선) | 현행 유지 | 대시보드는 mission_brief 기준 렌더링 + applied_overrides 별도 배지로 표시 |
| ⑦ | 승인 | `higher_intent`/`unit_mission`/`uav_mission`은 override 불가(재입력만 가능) | 의도된 설계로 유지 | 해당 없음 |
| ⑧ | 감사 | `finalize()` 반환값에 승인자 식별자(operator_id) 없음 | MVP 이후로 미룸 | 인증 체계 도입과 함께 후속 과제로 묶음 |
| ⑨ | 보안 | `/gcs/*` CORS가 임의 origin 허용(주석 확인) | 이번 재검토 범위 밖, 별도 트랙 | 별도 보안 감사(devsecops-redteam 등) 트랙으로 이관 |

## 다음 단계 제안

1. P0 두 건(finalize 배선, no_fly_zones 누락)부터 TDD로 수정 — 둘 다 "문서/테스트는 맞는데 배선이 안 됨" 패턴이라 회귀 테스트 우선순위가 높다.
2. B-1/CLAUDE.md에 이번에 명문화하기로 한 4개 항목(②③⑤⑦ 관련 주석) 반영.
3. stale window 경고(①), operator_id(⑧), CORS(⑨)는 다음 라운드 백로그로 이관.
