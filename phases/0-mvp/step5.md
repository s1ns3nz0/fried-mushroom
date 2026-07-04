# Step 5: layer-04-threat-modeling

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/ADR.md` (ADR-003 결정론+AI 분리)
- `/d4d_pipeline/schemas.py` (Step 1 — `ThreatCandidate`, `ThreatModelingOutput`)
- `/d4d_pipeline/constants.py` (Step 1 — `THREAT_CATALOG`, `POTENTIAL_OUTCOME_MAP`, `SIGNAL_TO_THREAT`, `T4_MULTI_CHANNEL_CONDITIONS`, `PHASE_THREAT_MULTIPLIER`, `CHANNEL_WEIGHTS`, `CONFIDENCE_BY_MATCH_COUNT`, `W_MIN`, `Q_MIN`, `CROSS_CHECK_TOLERANCE`, `QUALITY_DELTA_DROP_THRESHOLD`)
- `/d4d_pipeline/layer_03_abstraction/run.py` (Step 3, 4) 및 11개 채널 payload 구조
- `/examples/raw_t3.json`, `raw_t4.json`, `raw_t7.json` 및 03을 통과시켰을 때 나오는 골든 dict

D4D 원문 문서 (레포 내 `/docs/D4D/`):

- `/docs/D4D/04. Threat Modeling.md` — Step A (임무 국면), B (신호→위협, T4 다중조건, T6 배경노출), C (결정론 confidence + AI 로그오즈 강화판 + 교차검증 + 국면 배수), D (potential_outcome). "최종 출력 스키마" 표. quality_delta로 T5(레이저) 감지.
- `/docs/D4D/C-1. Threat Modeling Spec.md` — 손계산 검증 사례 (골든 케이스로 활용)

## 작업

03의 11채널 출력을 받아 위협 후보를 산출하는 4단계 파이프라인. 결정론적 confidence와 AI 강화판(로그오즈)을 병렬로 계산하고 교차검증. RAC 산출은 여기 없음 (05의 몫).

### 1) 파일 구성

`d4d_pipeline/layer_04_threat/`:

- `run.py`
- `step_a_phase.py`
- `step_b_mapping.py`
- `step_c_confidence.py`
- `step_d_outcome.py`

`SIGNAL_TO_THREAT`의 `condition` 문자열을 실제 판정 함수로 컴파일하는 로직은 `step_b_mapping.py` 내부에 상수 테이블 형태로 하드코딩한다. 이유: `eval` 금지 (보안), 그리고 조건이 채널 payload key에 의존하는 단순 조회라 코드로 표현하는 편이 명확.

예시 (하드코딩):

```python
# step_b_mapping.py 내부
_SINGLE_CHANNEL_RULES: list[tuple[str, Callable[[dict], bool], str]] = [
    ("proximity_object",
     lambda ch: ch["state"] == "anomaly" and ch["payload"].get("weapon_shape") is True,
     "T3"),
    ("acoustic_event",
     lambda ch: ch["payload"].get("event_type") == "gunshot",
     "T3"),
    ("position_consistency",
     lambda ch: ch["payload"].get("gps_imu_residual_m", 0) > 5.0,
     "T1"),
    ("rf_spectrum",
     lambda ch: ch["payload"].get("wideband_anomaly") is True,
     "T1"),
    ("link_integrity",
     lambda ch: ch["payload"].get("checksum_fail_rate", 0) > 0.05
                or ch["payload"].get("seq_gap_count", 0) > 0,
     "T2"),
    ("encryption_status",
     lambda ch: ch["payload"].get("downgrade_detected") is True,
     "T2"),
    ("obstacle_proximity",
     lambda ch: (ch["payload"].get("distance_m", 1e9)
                 / max(ch["payload"].get("closure_rate_mps", 1e-6), 1e-6)) < 3.0,
     "T7"),
    ("proximity_object",
     lambda ch: ch["payload"].get("quality_delta", 0) < QUALITY_DELTA_DROP_THRESHOLD,
     "T5"),
    ("terrain_class",
     lambda ch: ch["payload"].get("quality_delta", 0) < QUALITY_DELTA_DROP_THRESHOLD,
     "T5"),
]
```

quality_delta는 채널 최상위 필드지만, T5 규칙에서만 참조하니 위처럼 payload 대신 최상위에서 읽는 별도 helper가 필요할 수 있다 (구현자 재량 — 결과가 문서와 일치하면 됨).

### 2) Step A: `step_a_phase.py`

```python
def run(abstraction: AbstractionOutput) -> tuple[str, float]:
    """
    mission_phase 채널의 payload.declared, mission_phase_confidence를 그대로 반환.
    이 step은 재계산하지 않는다 (04 문서 Step A 원칙).
    """
```

### 3) Step B: `step_b_mapping.py`

```python
def run(abstraction: AbstractionOutput) -> tuple[list[dict], float]:
    """
    반환:
      matched: [
        {"threat_event": "T3", "matched_channels": [{name, base_weight, quality, state}]},
        ...
      ]
      background_exposure_score: terrain_class.payload.exposure_score를 그대로 반환. 없으면 0.0.
    """
```

`_SINGLE_CHANNEL_RULES`를 순회하고, T4는 별도 `_check_t4_multi_channel(abstraction)` 함수로 세 조건(proximity_object closing/class, mission_phase match=False, link_status != normal)이 동시 참일 때만 매칭.

같은 threat_event에 여러 채널이 매칭되면 하나로 병합 (matched_channels 리스트에 누적).

### 4) Step C: `step_c_confidence.py`

```python
def run(matched: list[dict], declared_phase: str) -> list[dict]:
    """
    각 threat별로:
      1) W_min(=0.20) 미만인 base_weight 채널은 제외
      2) quality < Q_min(=0.65)인 채널도 이번 사이클 제외
      3) 매칭 채널이 전부 제외되면 이 threat은 candidates에서 제외
      4) match_count 산출 → deterministic_confidence (1→0.7, 2→0.9, 3+→0.95)
      5) avg_weight로 kill_chain_stage 산출:
            avg_weight >= 0.35 and match_count >= 2 → "후기"
            match_count >= 1 → "중기"
            else → "초기"
      6) AI 강화판:
            log_odds = sum(weight * logit(quality))
            ai_confidence = sigmoid(log_odds)
      7) 교차검증: |ai - det| <= CROSS_CHECK_TOLERANCE(0.15)이면 confidence=ai, source="ai".
         아니면 confidence=det, source="deterministic".
      8) 국면 배수: confidence *= PHASE_THREAT_MULTIPLIER.get((declared_phase, threat_event), 1.0), min 0.95
    반환: [{threat_event, match_count, confidence, confidence_source, kill_chain_stage}, ...]
    """
```

`logit(q) = ln(q / (1 - q))`. q=1이면 오버플로우 → q를 [0.001, 0.999]로 clamp. `sigmoid`, `log`, `exp`는 `math` 모듈로 구현. numpy 도입 불필요.

### 5) Step D: `step_d_outcome.py`

```python
def run(scored: list[dict]) -> list[ThreatCandidate]:
    """
    각 후보에 potential_outcome을 붙인다. POTENTIAL_OUTCOME_MAP[threat_event] 조회.
    """
```

### 6) 오케스트레이터 `run.py`

```python
def run(abstraction: AbstractionOutput,
        cycle_context: dict | None = None) -> ThreatModelingOutput:
    declared_phase, phase_conf = step_a_phase.run(abstraction)
    matched, exposure = step_b_mapping.run(abstraction)
    scored = step_c_confidence.run(matched, declared_phase)
    candidates = step_d_outcome.run(scored)
    primary = _pick_primary(candidates)  # match_count 최다, 동률이면 avg_weight 높은 쪽
    return {
        "declared_phase": declared_phase,
        "mission_phase_confidence": phase_conf,
        "candidates": candidates,
        "primary": primary,
        "background_exposure_score": exposure,
        "cycle_context": cycle_context or {},
    }
```

`cycle_context`는 후속 레이어(06/07)가 소비할 지형 정보(`optimal_terrain_bearing_deg` 등)를 담는 자리. 이 step에서는 밖에서 받은 값을 그대로 pass-through. MVP에서는 orchestrator(step 9)가 dummy 값(0.0)을 넘기면 된다.

### 7) 테스트

`tests/layer_04_threat/test_step_b_mapping.py`:
- t3 abstraction → matched에 T3, T5 아닌 결과. matched_channels에 proximity_object, acoustic_event 포함
- t4 abstraction → matched에 T4 포함 (다중조건 만족). T2도 함께 (link_integrity anomaly면)
- t7 abstraction → matched에 T7 포함
- 정상 envelope → matched=[]

`tests/layer_04_threat/test_step_c_confidence.py`:
- 매칭 채널 quality 0.9 하나 → deterministic_confidence=0.7. LOITER_ROI/T3 국면배수 1.1 적용 후 0.77
- 매칭 채널 두 개(quality 0.9, 0.8) → deterministic=0.9, AI 계산 검증, |ai-det| < 0.15면 source="ai"
- 채널 quality 0.5 (Q_min=0.65 미만) → 그 채널만 이번 사이클 제외
- 매칭 채널이 link_status(weight=0.15, W_min=0.20 미만) 하나뿐 → threat 자체 candidates에서 빠짐

`tests/layer_04_threat/test_step_d_outcome.py`:
- 각 T1~T7 후보에 대해 `potential_outcome`이 `POTENTIAL_OUTCOME_MAP`과 일치

`tests/layer_04_threat/test_run_golden.py`:
- t3 종단: `primary.threat_event == "T3"`, `primary.match_count >= 2`, `primary.confidence >= 0.9`, `primary.potential_outcome == "attrition_kill"`, `declared_phase == "LOITER_ROI"`
- t4: `primary.threat_event == "T4"`, `potential_outcome == "hull_loss"`
- t7: `primary.threat_event == "T7"`, `potential_outcome == "attrition_kill"`
- 정상: candidates 빈 리스트, `primary is None`

## Acceptance Criteria

```bash
python3 -m pytest tests/layer_04_threat/ -v
```

- 모든 테스트 PASSED

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - `eval` / `exec`을 쓰지 않았는가?
   - Step A가 mission_phase를 재계산하지 않고 03 결과를 그대로 읽는가?
   - AI 강화판이 결정론 confidence를 덮어쓰지 않고 교차검증 실패 시 결정론으로 폴백하는가?
   - `numpy` 등 추가 의존성이 없는가?
3. 결과에 따라 `phases/0-mvp/index.json`의 step 5를 업데이트한다.

## 금지사항

- Step A에서 `mission_phase.behavioral`을 재계산하지 마라. 이유: 03 소관 (04.md 원칙).
- AI가 매트릭스나 매핑을 바꾸도록 하지 마라. 이유: ADR-003 (SCC-1). AI는 confidence 값만 병렬 계산.
- 03의 채널 이름 규약을 어기지 마라 (`proximity_object`, `acoustic_event` 등 exact). 이유: cross-layer 계약.
- `candidates` 정렬을 여기서 하지 마라 (`primary` 선택은 여기서 하지만 정렬은 05). 이유: 04는 후보 산출, 05는 우선순위화.
