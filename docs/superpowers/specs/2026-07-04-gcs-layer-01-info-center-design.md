# GCS Layer 01 — Info Center: mission_brief 조립 (설계)

날짜: 2026-07-04 · 범위: `src/gcs/layer_01_info_center/` MVP 슬라이스

## 1. 목적

지상통제센터 AI(D4D `01`/`B-1`)의 6단계 중, 이 프로젝트(순수함수·CLI·모델 없음)에
맞는 **결정론적 mission_brief 조립 슬라이스**를 구현한다. 출력은 온보드 파이프라인이
이미 소비하는 `MissionBrief` 계약 그대로여서 `01 → run_cycle(02..07)` 종단이 성립한다.

**핵심 원칙(스펙 계승):** AI는 후보안만 제시, 최종 결정은 사람(승인 게이트). NLP는
지시서 원문만 읽는다(추적성). 확신도 < 0.7 은 운용자에게 숨긴다. drone_profile 은
상수라 임무정보와 분리(최상위). 결정론 로직과 stub 분리(ADR-002/003).

## 2. 출력 계약

온보드 `MissionBrief` (src/onboard/shared/schemas.py):
```
{sortie_id, mission_context: "정찰|타격|호송|수송", posture, drone_profile, corridor, weights}
```
`finalize` 는 이 6필드 브리핑 + 승인 타임스탬프를 반환한다.

## 3. 입력 (set_mission 번들)

```
{
  "sortie_id": str,
  "directive_text": str,          # 지시서 원문 — NLP 가 읽는 유일 입력
  "mission_context": str,         # 운용자 선택 임무유형
  "posture": {watchcon, defcon, infocon},
  "drone_profile": {spare_available, armament, ...},
  "corridor": {...},              # GCS 항로정보 (구조 통과, 온보드가 검증)
  "weights": {stealth, survival, info_value, timeliness},
  "c4i": {                        # 대조용 사실 데이터
     "enemy_situation": [str, ...],       # 적상황 (위협신호 확증)
     "asset_management": {"spare_available": bool},  # 예비기체 검증
     "known_mission": str                 # 임무목적 검증
  }
}
```

## 4. 모듈 분해 (한 파일 = 한 책임)

- **`nlp_extract.py`** — `extract_signals(directive_text) -> list[Signal]`. 결정론 키워드 룰.
  `KEYWORD_RULES`: [(phrase, signal dict, base_confidence)]. 확실성 수식어("확인됨"→상향,
  "가능성"→하향) 반영. `CONFIDENCE_FLOOR = 0.7` 미만 신호는 제외. C4I/GCS 안 봄.
  Signal = `{source_phrase, signal_type, threat?, effect?, confidence}`.
- **`cross_check.py`** — `cross_check(signals, drone_profile, mission_context, c4i) -> (adjusted_signals, warnings)`.
  · 확신도 조정: 위협신호가 `c4i.enemy_situation` 에 확증되면 confidence 상향 + reason.
  · 불일치 경고(확신도 무변): `drone_profile.spare_available` vs `c4i.asset_management.spare_available`;
    `mission_context`/목적 vs `c4i.known_mission`. Warning = `{field, registered, c4i, message}`.
- **`assemble.py`** — `assemble_brief(inputs) -> draft_brief`. 6 MissionBrief 필드를 출처
  태깅 없이(온보드 계약 그대로) 구성. drone_profile 은 그대로 최상위 통과.
- **`run.py`** — 오케스트레이터, 2단계:
  · `assemble_draft(inputs) -> {draft_brief, signal_cards, warnings}`
    signal_cards = confidence>=0.7 인 (adjusted) 신호 카드 (원문·해석·확신도·대조사유).
  · `finalize(draft, approved, ts_ms) -> {mission_brief, approved_ts_ms}` (approved=True)
    또는 `{status: "pending_approval", signal_cards, warnings}` (approved=False).
  순수 함수 — ts_ms 는 주입(Date.now 금지).

## 5. 데이터 흐름

```
set_mission inputs
  → nlp_extract.extract_signals(directive_text)         → signals[]
  → cross_check(signals, drone_profile, ctx, c4i)       → adjusted_signals[], warnings[]
  → assemble_brief(inputs)                              → draft_brief (6필드)
  → assemble_draft = {draft_brief, signal_cards, warnings}
  → (운용자 승인) finalize(draft, approved, ts_ms)      → {mission_brief, approved_ts_ms}
                                                            → run_cycle(raw, mission_brief) (온보드)
```

## 6. 에러 처리

- 필수 입력 필드 누락(sortie_id/mission_context/posture/drone_profile/corridor/weights)
  → 명시적 `KeyError`/`ValueError` (조용한 기본값 금지 — 임무 저작 시맨틱).
- `c4i` 누락 → 대조 건너뜀(경고 없음), 조립은 진행 (graceful, C4I 는 비동기 소스).
- `finalize(approved=False)` → 브리핑 미확정, pending 반환.

## 7. 테스트 (TDD)

- `nlp_extract`: 알려진 문구 → 신호+확신도; 확실성 수식어; <0.7 필터.
- `cross_check`: C4I 확증 → 확신도 상향; spare/mission 불일치 → 경고(확신도 무변); c4i 부재 → 무경고.
- `assemble`: 6 필드 draft; drone_profile 통과; 필수 누락 → 에러.
- `run`: assemble_draft 종단; finalize 승인 → 온보드 소비가능 MissionBrief; 미승인 → pending.
- **통합(킬러):** `finalize(...).mission_brief` → `run_cycle(raw_t3, mission_brief)` 01→07 완주.

## 8. 범위 밖 (MVP)

실제 NLP 모델, 승인 UI, RAG 코퍼스, 거부/재수집 흐름, B-1 전체 METT+TC 리치니스
(higher_intent/uav_mission/bases/assets/no_fly_zones/civil_sensitivity). 후속 서브프로젝트.

## 9. 패턴 준수

순수함수·JSON dict I/O·레이어 격리(다른 레이어 내부 import 금지, shared 만)·결정론
우선·상수 하드코딩(모듈 상수). onboard 아키텍처와 동형.
