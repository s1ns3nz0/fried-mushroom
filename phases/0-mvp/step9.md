# Step 9: end-to-end-orchestrator

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/PRD.md` (성공 기준 — t3 시나리오 종단 골든)
- `/docs/ARCHITECTURE.md` (데이터 흐름, 상태 관리)
- `/docs/ADR.md`
- `/d4d_pipeline/schemas.py`
- 각 레이어 `run.py`:
  - `/d4d_pipeline/layer_03_abstraction/run.py`
  - `/d4d_pipeline/layer_04_threat/run.py`
  - `/d4d_pipeline/layer_05_risk/run.py`
  - `/d4d_pipeline/layer_06_response/run.py`
  - `/d4d_pipeline/layer_07_planning/run.py`
- `/examples/raw_t3.json`, `raw_t4.json`, `raw_t7.json`, `mission_brief_t3.json`, `_t4.json`, `_t7.json`

## 작업

전체 파이프라인을 하나의 CLI로 엮고, 세 시나리오의 종단 골든 JSON을 만든 뒤 통합 회귀 테스트를 붙인다.

### 1) `d4d_pipeline/run.py`

```python
def run_cycle(raw: RawSensorEnvelope,
              mission_brief: MissionBrief,
              previous_qualities: dict[str, float] | None = None,
              cycle_context: dict | None = None) -> dict:
    """
    한 사이클 실행. 반환:
      {
        "abstraction": AbstractionOutput,
        "threat": ThreatModelingOutput,
        "risk": RiskAssessmentOutput,
        "response": ResponseOutput,
        "flight_plan": FlightPlanOutput,
      }
    """
    cycle_context = cycle_context or _default_cycle_context()

    abstraction = layer_03.run(raw, previous_qualities)
    threat = layer_04.run(abstraction, cycle_context)
    link_q = _extract_link_quality(abstraction)
    risk = layer_05.run(threat, mission_brief, link_quality=link_q)
    response = layer_06.run(risk, mission_brief)

    primary_context = threat["primary"]["context"] if threat["primary"] else None
    flight_plan = layer_07.run(response, primary_context, cycle_context)

    return {
        "abstraction": abstraction,
        "threat": threat,
        "risk": risk,
        "response": response,
        "flight_plan": flight_plan,
    }
```

`_default_cycle_context`는 MVP에서 `{"optimal_terrain_bearing_deg": 0.0, "lowest_exposure_bearing_deg": 0.0}` 정도로. 실제 지형 조회는 후순위 (07의 골든 케이스 만족만 확인).

04의 `primary.context.bearing_deg`는 MVP에서 03의 proximity_object/acoustic_event/rf_spectrum 중 우선순위대로 골라 04가 primary에 심어 넘겨야 한다. 이 로직은 04의 오케스트레이터에 추가한다 (step 5에서 놓쳤다면 이 step에서 보완):

```python
# layer_04_threat/run.py 안 (보완 지시 — step 5에서 이미 반영됐다면 no-op)
def _extract_primary_context(abstraction: AbstractionOutput, primary_threat_event: str) -> dict:
    priority = ["proximity_object", "acoustic_event", "rf_spectrum"]
    for name in priority:
        for ch in abstraction["channels"]:
            if ch["channel"] == name and ch["payload"].get("bearing_deg") is not None:
                return {
                    "bearing_deg": ch["payload"]["bearing_deg"],
                    "bearing_source": name,
                    "class": ch["payload"].get("class"),
                }
    return {}
```

step 5에서 이 로직이 누락됐다면 여기서 추가한다. 추가만 하고 04의 다른 로직은 건드리지 않는다.

### 2) CLI 엔트리포인트

`d4d_pipeline/__main__.py`:

```python
import json, sys
from pathlib import Path
from .run import run_cycle

def main() -> int:
    if len(sys.argv) < 3:
        print("usage: python -m d4d_pipeline <raw.json> <mission_brief.json>", file=sys.stderr)
        return 2
    raw = json.loads(Path(sys.argv[1]).read_text())
    mb = json.loads(Path(sys.argv[2]).read_text())
    result = run_cycle(raw, mb)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### 3) 종단 골든 JSON

`examples/expected_t3.json`, `expected_t4.json`, `expected_t7.json` — `run_cycle` 실행 결과를 JSON dump 해서 저장한다. 각 파일에는 위 반환 dict의 5개 최상위 키가 다 들어간다.

파일은 처음 만들 때 `python -m d4d_pipeline examples/raw_t3.json examples/mission_brief_t3.json > examples/expected_t3.json` 로 생성한 뒤, 사람이 눈으로 확인해 문서와 어긋나지 않는 부분만 커밋한다.

### 4) 통합 테스트

`tests/integration/test_e2e_golden.py`:

```python
import json
from pathlib import Path
from d4d_pipeline.run import run_cycle

_ROOT = Path(__file__).parents[2]

def _load(name: str) -> dict:
    return json.loads((_ROOT / "examples" / name).read_text())

@pytest.mark.parametrize("scenario", ["t3", "t4", "t7"])
def test_scenario_matches_golden(scenario: str) -> None:
    raw = _load(f"raw_{scenario}.json")
    mb = _load(f"mission_brief_{scenario}.json")
    actual = run_cycle(raw, mb)
    expected = _load(f"expected_{scenario}.json")
    assert actual == expected
```

`tests/integration/test_e2e_semantics.py`:

- t3: `actual["response"]["primary_threat_event"] == "T3"`, `actual["response"]["payload_action"] == ["DATA_WIPE"]` (armament 없음), `actual["flight_plan"]["replan_scope"] in {"LOCAL", "FULL"}`
- t4: `actual["response"]["primary_threat_event"] == "T4"`, `actual["response"]["flight_action"] == "RTL"` (High/후기 가정), `actual["response"]["payload_action"] == ["DATA_WIPE"]`
- t7: `actual["response"]["threat_category"] == "NAVIGATION"`, `actual["flight_plan"]["altitude_delta_m"] > 0`
- 정상 raw envelope: `actual["response"]["primary_threat_event"] is None`, `actual["response"]["rac"] == "Low"`, `actual["flight_plan"]["replan_scope"] == "NONE"`

### 5) `.gitignore` 갱신

파이프라인 실행 로그 자리를 남긴다 (Step 0에서 만든 .gitignore에 추가):

```
.d4d_logs/
```

로그 자체 구현(JSONL append)은 오케스트레이터에 넣지 말고 유즈사이트(호출자)의 책임으로 남긴다 — ARCHITECTURE.md "상태 관리" 규칙. 이 step에서는 CLI가 stdout에 결과만 뱉는다.

## Acceptance Criteria

```bash
python3 -m pytest -v
python3 -m d4d_pipeline examples/raw_t3.json examples/mission_brief_t3.json > /tmp/actual_t3.json
diff /tmp/actual_t3.json examples/expected_t3.json
```

- 첫 커맨드: 모든 단위·통합 테스트 PASSED
- 두 번째 커맨드: exit 0 (CLI가 골든과 정확히 일치하는 결과 출력)
- 세 번째 커맨드: exit 0 (diff 없음)

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - `run.py`가 상태를 갖지 않는가? (모든 상태는 인자로 전달)
   - 각 레이어의 오케스트레이터만 호출하고 내부 모듈을 직접 import 하지 않는가?
   - CLI가 stdout/stderr에만 쓰고 파일을 만들지 않는가?
   - `expected_*.json`이 D4D 문서의 예시 JSON과 큰 갈등이 없는가? (특히 t3의 response.flight_action, payload_action)
3. 결과에 따라 `phases/0-mvp/index.json`의 step 9를 업데이트한다.

## 금지사항

- 사이클 간 상태(quality_delta 이전 quality 등)를 파이프라인 내부 전역 변수로 저장하지 마라. 이유: ARCHITECTURE.md 상태 관리 규칙 (stateless 유지). 호출자가 `previous_qualities`로 넘긴다.
- MAVLink 실제 송신 코드를 넣지 마라. 이유: PRD MVP 제외 사항.
- 로그 파일을 쓰거나 SQLite/데이터베이스를 도입하지 마라. 이유: MVP 스코프. stdout JSON으로 충분.
- t3/t4/t7 이외의 시나리오를 새로 만들지 마라. 이유: 스코프 유지. 추가 시나리오는 별도 phase.
- `expected_*.json`을 손으로 편집하지 마라. 이유: 골든은 CLI 실행 결과여야 재현성이 보장된다. 값이 이상하면 상위 step으로 돌아가 로직을 고쳐야 한다.
