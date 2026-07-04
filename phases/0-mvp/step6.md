# Step 6: layer-05-risk-assessment

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/ADR.md` (ADR-003)
- `/src/onboard/shared/schemas.py` (Step 1 — `RiskCandidate`, `RiskAssessmentOutput`, `MissionBrief`)
- `/src/onboard/shared/constants.py` (Step 1 — `BASE_RATE_PHYSICAL`, `BASE_RATE_REMOTE_NAV`, `L_VALUE_TO_CLASS_THRESHOLDS`, `RAC_MATRIX`, `RAC_ORDER`, `SEVERITY_ORDER`, `CONTINUOUS_S_BASE_SCORE`, `CONTINUOUS_S_TO_NUM_THRESHOLDS`, `AMBIENT_EXPOSURE_THRESHOLD`)
- `/src/onboard/layer_04_threat/run.py` 및 스텝들 (Step 5)
- `/examples/mission_brief_t3.json`, `_t4.json`, `_t7.json`

D4D 원문 문서 (레포 내 `/docs/D4D/`):

- `/docs/D4D/05. Risk Assessment.md` — threat_category 3분류, base_rate 표, posture_shift 로직(watchcon/defcon vs infocon), 예비기체 override, RAC 매트릭스, continuous_L/S, compound_urgency_score, priority_rank 정렬, ambient_rac
- `/docs/D4D/D-1. Risk Assessment Spec.md` — 손계산 검증

## 작업

04의 `ThreatModelingOutput`과 `MissionBrief`를 받아 각 candidate에 RAC/compound_urgency_score를 붙이고 우선순위로 정렬. RAC 매트릭스는 절대 오버라이드 불가.

### 1) 파일 구성

`src/onboard/layer_05_risk/`:

- `run.py`
- `likelihood.py` — base_rate 조회 + posture_shift
- `severity.py` — severity_label + spare_asset override
- `rac_matrix.py` — RAC 조회 wrapper (constants.RAC_MATRIX를 read-only로 노출)
- `compound.py` — continuous_L/S, cross-check, compound_urgency_score

### 2) `likelihood.py`

```python
THREAT_CATEGORY: dict[str, str] = {
    "T1": "REMOTE", "T2": "REMOTE", "T5": "REMOTE",
    "T3": "PHYSICAL", "T4": "PHYSICAL",
    "T7": "NAVIGATION",
}

def base_rate(threat_event: str, mission_context: str) -> float:
    """PHYSICAL은 (event, context) 조회, REMOTE/NAVIGATION은 event 단독 조회."""

def posture_shift_steps(posture: dict, threat_event: str) -> int:
    """
    T2 → posture['infocon'] 기준
    나머지 → min(posture['watchcon'], posture['defcon'])
    steps 결정 규칙(문서에 정확한 매핑 없으면 team 표를 그대로):
      level 1 (최고경계) → +3 (A쪽으로 3단계)
      level 2 → +2
      level 3 → +1
      level 4 → 0
      level 5 → -1
    구체 매핑은 D4D 문서를 그대로 따르되, 문서에 없으면 위 안을 함수 상수로 하고 주석으로 "team 임시 설정" 명시.
    """

def l_value_to_class(rate: float) -> str:
    """L_VALUE_TO_CLASS_THRESHOLDS 순회 → A~F."""

def shift_class(l_class: str, steps: int) -> str:
    """A쪽으로 steps만큼 이동. A를 넘어가면 A 고정, F 아래로는 F 고정."""
```

### 3) `severity.py`

```python
def severity_label(threat_event: str, spare_asset_available: bool,
                   forced_override: bool = False) -> tuple[str, int]:
    """
    label = OUTCOME_TO_SEVERITY[POTENTIAL_OUTCOME_MAP[threat_event]]
    num = SEVERITY_ORDER[label]
    if (not spare_asset_available) or forced_override:
        num_final = max(1, num - 1)
        label_final = _num_to_label(num_final)
    else:
        num_final, label_final = num, label
    return label_final, num_final
    """
```

### 4) `rac_matrix.py`

```python
from ..constants import RAC_MATRIX

def lookup(l_class: str, severity_num: int) -> str:
    return RAC_MATRIX[(l_class, severity_num)]
```

노출은 이 함수만. `RAC_MATRIX`를 직접 import 하는 외부 코드가 없도록.

### 5) `compound.py`

```python
def continuous_l(base: float, confidence: float) -> float:
    """
    04의 confidence(최저 앵커 0.7 기준)로 base_rate를 보정.
    continuous_L = min(base * (confidence / 0.7), min(base * 3, 0.95))
    """

def continuous_s(severity_label_final: str, mission_brief: MissionBrief,
                 link_quality: float) -> float:
    """
    base_score = CONTINUOUS_S_BASE_SCORE[severity_label_final]
    penalty = (+0.10 if battery_pct < 30) + (+0.05 if not spare_asset_available) + (+0.05 if link_quality < 0.5)
    return min(base_score + penalty, 0.95)
    """

def s_num_from_continuous(s: float) -> int:
    """CONTINUOUS_S_TO_NUM_THRESHOLDS 순회."""

def cross_check_reliability(rac: str, rac_ai: str) -> str:
    """|RAC_ORDER[rac] - RAC_ORDER[rac_ai]| >= 2 → 'low', else 'normal'."""

def urgency_score(cont_l: float, cont_s: float, kill_chain_stage: str) -> float:
    """L*S + 0.1 if kill_chain_stage == '후기' else L*S. min(x, 0.95)."""
```

### 6) `run.py`

```python
def run(threat: ThreatModelingOutput,
        mission_brief: MissionBrief) -> RiskAssessmentOutput:
    candidates_out: list[RiskCandidate] = []
    for c in threat["candidates"]:
        b = base_rate(c["threat_event"], mission_brief["mission_context"])
        steps = posture_shift_steps(mission_brief["posture"], c["threat_event"])
        l_class = shift_class(l_value_to_class(b), steps)

        forced = mission_brief["drone_profile"].get("forced_severity_override", False)
        sev_label, sev_num = severity_label(
            c["threat_event"],
            mission_brief["drone_profile"].get("spare_asset_available", True),
            forced,
        )
        rac = lookup(l_class, sev_num)

        # AI 강화판 병렬
        cl = continuous_l(b, c["confidence"])
        link_q = _link_quality_from(mission_brief)   # TODO: MVP에서 mission_brief에 없으면 0.9 기본
        cs = continuous_s(sev_label, mission_brief, link_q)
        l_class_ai = shift_class(l_value_to_class(cl), steps)
        rac_ai = lookup(l_class_ai, s_num_from_continuous(cs))
        reliability = cross_check_reliability(rac, rac_ai)

        urg = urgency_score(cl, cs, c["kill_chain_stage"])

        candidates_out.append({
            **c,
            "rac": rac,
            "l_class_final": l_class,
            "severity_label_final": sev_label,
            "compound_risk_assessment": {
                "continuous_L": cl,
                "continuous_S": cs,
                "rac_ai_equivalent": rac_ai,
                "ai_reliability": reliability,
            },
            "compound_urgency_score": urg,
            "priority_rank": 0,  # 정렬 후 채운다
        })

    # 정렬: compound_urgency_score 내림차순, 동률이면 severity_num_final 오름차순, 그래도 동률이면 match_count 내림차순
    candidates_out.sort(key=lambda x: (
        -x["compound_urgency_score"],
        SEVERITY_ORDER[x["severity_label_final"]],
        -x["match_count"],
    ))
    for i, c in enumerate(candidates_out, 1):
        c["priority_rank"] = i

    ambient = None
    if not candidates_out:
        ambient = "Medium" if threat["background_exposure_score"] >= AMBIENT_EXPOSURE_THRESHOLD else "Low"

    return {"candidates": candidates_out, "ambient_rac": ambient}
```

`link_quality`는 03의 link_status.quality를 04가 뭉치지 않고 05가 접근할 수 없다. MVP에서는 mission_brief 안에 넣지 말고, `run(threat, mission_brief, link_quality=None)`으로 인자 추가. 오케스트레이터가 abstraction 결과에서 뽑아 넘긴다.

### 7) 테스트

`tests/layer_05_risk/test_likelihood.py`:
- `base_rate("T3", "정찰") == 0.15`, `base_rate("T3", "타격") == 0.35`, `base_rate("T1", "정찰") == 0.12` (T1은 컨텍스트 무관)
- `l_value_to_class(0.6) == "A"`, `l_value_to_class(0.4) == "B"`, `l_value_to_class(0.005) == "F"`
- `shift_class("C", 2) == "A"`, `shift_class("A", 2) == "A"` (상한 고정), `shift_class("F", -1) == "F"` (하한 고정)

`tests/layer_05_risk/test_severity.py`:
- T2 outcome=hull_loss → Catastrophic=1. spare_asset_available=False여도 이미 1이라 override 무효
- T1 outcome=mission_abort → Marginal=3. spare_asset=False면 → Critical=2
- forced_override=True + spare_asset=True → 한 단계 격상

`tests/layer_05_risk/test_rac_matrix.py`:
- `lookup("A", 1) == "High"`, `lookup("F", 4) == "Low"`, 중앙 몇 개 스팟체크

`tests/layer_05_risk/test_run_golden.py`:
- t3 mission_brief + 04 t3 결과 → 유일 candidate T3의 `rac`가 D4D 문서 예시(Serious 또는 High — mission_context=정찰, posture watchcon/defcon=3 기준 손계산 확인)와 일치. `priority_rank == 1`. `compound_urgency_score > 0.2`.
- t4 → T4의 severity=Catastrophic(hull_loss), spare_asset=True라 격상 없음. rac는 매트릭스 조회 결과.
- t7 → T7의 rac 및 priority_rank
- 정상 envelope → candidates 빈 리스트, `ambient_rac == "Low"`

`tests/layer_05_risk/test_matrix_immutable.py`:
- `RAC_MATRIX["A", 1] = "Low"` 시도 시 `TypeError` (Step 1의 MappingProxyType 검증 재확인)

## Acceptance Criteria

```bash
python3 -m pytest tests/layer_05_risk/ -v
```

- 모든 테스트 PASSED

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - RAC_MATRIX가 코드 어디에서도 mutation 되지 않는가?
   - continuous_L/S가 결정론적 RAC를 덮어쓰지 않는가?
   - compound_risk_assessment의 `ai_reliability`가 통보용으로만 산출되는가?
3. 결과에 따라 `phases/0-mvp/index.json`의 step 6을 업데이트한다.

## 금지사항

- `RAC_MATRIX`를 함수 인자로 받아 오버라이드하는 시그니처를 만들지 마라. 이유: ADR-003 (SCC-1 원칙).
- AI 강화판이 실제 RAC를 결정하도록 하지 마라. 참고지표만.
- `numpy`를 도입하지 마라. 이유: 표준 `math`로 충분.
- 04를 다시 실행하거나 04의 로직(confidence 재산정)을 반복하지 마라. 이유: 계층 분리. 04의 출력을 신뢰하고 소비.
- `secondary_threats` 요약 리스트를 여기서 만들지 마라. 이유: 06의 몫 (RiskAssessmentOutput의 candidates 전체를 06이 받아서 1순위만 실행하고 나머지를 요약).
