# Step 7: layer-06-response

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/CLAUDE.md`
- `/d4d_pipeline/schemas.py` (`ResponseOutput`, `MissionBrief`)
- `/d4d_pipeline/constants.py`
- `/d4d_pipeline/layer_05_risk/run.py` (Step 6)
- `/examples/mission_brief_t7.json` (armament에 expendable=True 있음)

D4D 원문 문서 (레포 내 `/docs/D4D/`):

- `/docs/D4D/06. Response.md` — threat_category 3분류(PHYSICAL/REMOTE/NAVIGATION, 05와 공유), RAC=High 테이블 (kill_chain_stage×threat_category), RAC=Serious/Medium/Low 테이블, payload_action(DATA_WIPE, WEAPON_DROP), nav_mode(INS_ONLY), special_action(GCS_CONSULT/INCREASE_ASSESSMENT_FREQUENCY), 자폭드론 override, secondary_threats 요약 규약.
- `/docs/D4D/E-1. Response Spec.md` — 손계산 검증

## 작업

05의 정렬된 candidates 중 1순위만 실행 대상. 나머지는 요약(secondary_threats)로 남겨 지상국 통보.

### 1) 파일 구성

`d4d_pipeline/layer_06_response/`:

- `run.py`
- `flight_comms.py` — (RAC, kill_chain_stage, threat_category) 조회 테이블
- `payload_nav.py` — threat_event별 overlay

`THREAT_CATEGORY` dict는 05의 `likelihood.py`에 이미 있다. 06은 그 값을 import 해서 재사용 (`from ..layer_05_risk.likelihood import THREAT_CATEGORY`).

### 2) `flight_comms.py`

```python
# RAC=High, kill_chain_stage=후기/중기
_HIGH_LATE: dict[str, tuple[str, str]] = {
    "PHYSICAL":   ("RTL",                      "L3"),
    "REMOTE":     ("REROUTE",                  "L2"),
    "NAVIGATION": ("ALTITUDE_CHANGE_REROUTE",  "L2"),
}

# RAC=High, kill_chain_stage=초기
_HIGH_EARLY: dict[str, tuple[str, str]] = {
    "PHYSICAL":   ("POSTURE_ELEVATE", "L1"),
    "REMOTE":     ("POSTURE_ELEVATE", "L1"),
    "NAVIGATION": ("POSTURE_ELEVATE", "L1"),
}

# RAC = Serious/Medium/Low (threat_category, kill_chain_stage 무관)
_LOWER_RAC: dict[str, tuple[str, str, str | None]] = {
    "Serious": ("ALTITUDE_CHANGE", "L1", "GCS_CONSULT"),
    "Medium":  ("MAINTAIN",        "L1", "INCREASE_ASSESSMENT_FREQUENCY"),
    "Low":     ("MAINTAIN",        "L0", None),
}

def resolve(rac: str, kill_chain_stage: str | None,
            threat_category: str | None) -> tuple[str, str, str | None]:
    """return (flight_action, comms_level, special_action)."""
```

RAC=High이고 stage=초기면 `special_action="INCREASE_ASSESSMENT_FREQUENCY"` (문서의 POSTURE_ELEVATE 자리에 이 지시가 붙는다). RAC=High/late는 special_action=None.

### 3) `payload_nav.py`

```python
def payload_actions(threat_event: str, kill_chain_stage: str, rac: str,
                    threat_category: str,
                    drone_profile: dict) -> list[str]:
    """
    조건: rac=='High' and kill_chain_stage in {'후기','중기'} 아니면 [].
    아니면:
      - PHYSICAL(T3, T4) → ['DATA_WIPE'] 시작
      - T3 && drone_profile['armament']에 expendable=True 항목 존재 → ['WEAPON_DROP'] 추가
      - T4는 WEAPON_DROP 추가 안 함 (문서: 무게감소 취지는 T3 전용)
      - REMOTE(T1/T2/T5), NAVIGATION(T7) → []
    """

def nav_mode(threat_event: str, rac: str, kill_chain_stage: str) -> str | None:
    """
    조건 동일: rac='High' and stage in {'후기','중기'}.
    - T1 → 'INS_ONLY'
    - 그 외 → None
    """
```

### 4) `run.py`

```python
def run(risk: RiskAssessmentOutput,
        mission_brief: MissionBrief) -> ResponseOutput:
    candidates = risk["candidates"]
    if not candidates:
        # 위협 미탐지 — ambient_rac로 폴백
        rac = risk.get("ambient_rac") or "Low"
        flight, comms, special = flight_comms.resolve(rac, None, None)
        return {
            "primary_threat_event": None,
            "rac": rac,
            "kill_chain_stage": None,
            "threat_category": None,
            "flight_action": flight,
            "comms_level": comms,
            "payload_action": [],
            "nav_mode": None,
            "special_action": special,
            "secondary_threats": [],
            "ai_reliability": "normal",
        }

    primary = candidates[0]
    tc = THREAT_CATEGORY[primary["threat_event"]]
    flight, comms, special = flight_comms.resolve(
        primary["rac"], primary["kill_chain_stage"], tc,
    )
    payload = payload_nav.payload_actions(
        primary["threat_event"], primary["kill_chain_stage"], primary["rac"],
        tc, mission_brief["drone_profile"],
    )
    nav = payload_nav.nav_mode(primary["threat_event"], primary["rac"], primary["kill_chain_stage"])

    return {
        "primary_threat_event": primary["threat_event"],
        "rac": primary["rac"],
        "kill_chain_stage": primary["kill_chain_stage"],
        "threat_category": tc,
        "flight_action": flight,
        "comms_level": comms,
        "payload_action": payload,
        "nav_mode": nav,
        "special_action": special,
        "secondary_threats": [
            {
                "threat_event": c["threat_event"],
                "rac": c["rac"],
                "compound_urgency_score": c["compound_urgency_score"],
                "priority_rank": c["priority_rank"],
            }
            for c in candidates[1:]
        ],
        "ai_reliability": primary["compound_risk_assessment"]["ai_reliability"],
    }
```

### 5) 테스트

`tests/layer_06_response/test_flight_comms.py`:
- `resolve("High", "후기", "PHYSICAL") == ("RTL", "L3", None)`
- `resolve("High", "초기", "PHYSICAL") == ("POSTURE_ELEVATE", "L1", "INCREASE_ASSESSMENT_FREQUENCY")`
- `resolve("Serious", None, None) == ("ALTITUDE_CHANGE", "L1", "GCS_CONSULT")`
- `resolve("Low", None, None) == ("MAINTAIN", "L0", None)`

`tests/layer_06_response/test_payload_nav.py`:
- T3 + High + 후기 + armament에 expendable=True → `["DATA_WIPE", "WEAPON_DROP"]`
- T3 + High + 후기 + armament=[] → `["DATA_WIPE"]`
- T4 + High + 후기 → `["DATA_WIPE"]` (WEAPON_DROP 없음)
- T3 + Serious + 후기 → `[]` (High 아니면 payload_action 안 나감)
- T1 + High + 후기 → `[]`, nav_mode="INS_ONLY"
- T7 + High + 후기 → `[]`, nav_mode=None

`tests/layer_06_response/test_run_golden.py`:
- t3 종단: `primary_threat_event="T3"`, `flight_action="RTL"` 또는 `"POSTURE_ELEVATE"`(kill_chain_stage에 따라), `comms_level`, `payload_action`이 문서 예시와 일치. `secondary_threats=[]`.
- t4: flight_action="RTL", comms_level="L3", payload_action=["DATA_WIPE"], nav_mode=None
- t7: flight_action이 T7 계열 (High면 ALTITUDE_CHANGE_REROUTE, Serious면 ALTITUDE_CHANGE), threat_category="NAVIGATION"
- 정상: primary_threat_event=None, rac="Low", flight_action="MAINTAIN"

## Acceptance Criteria

```bash
python3 -m pytest tests/layer_06_response/ -v
```

- 모든 테스트 PASSED

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - 1순위만 실행하고 나머지는 `secondary_threats` 요약으로만 나가는가?
   - `ai_reliability`가 05에서 넘어온 값을 그대로 통보에 붙였는가 (06이 자체 판정하지 않음)?
   - WEAPON_DROP이 armament expendable 조건 없이 나가지 않는가?
3. 결과에 따라 `phases/0-mvp/index.json`의 step 7을 업데이트한다.

## 금지사항

- 자체적으로 RAC를 재계산하지 마라. 이유: 05의 결과를 소비만 한다.
- WEAPON_DROP을 armament 조건 없이 넣지 마라. 이유: MVP 기체는 무장 없음. 조건부 실행 구조를 지키지 않으면 안전성 회귀.
- `special_action`을 여러 값 동시 반환하도록 리스트로 만들지 마라. 이유: 문서상 단일 지시.
- `flight_action`을 문자열 상수 대신 자유 문자열로 두지 마라. 이유: 07이 파싱하기 어렵다. 정확히 6종({RTL, REROUTE, ALTITUDE_CHANGE_REROUTE, ALTITUDE_CHANGE, MAINTAIN, POSTURE_ELEVATE}) 중 하나.
