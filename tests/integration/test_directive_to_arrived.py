"""종단 배선 골든: 지시서(set_mission) → GCS 승인 → sim 폐루프 → ARRIVED.

#151 폐루프 데모의 front-of-loop(이음새) 실증. 이 테스트는 '이음새 + 생존성'만 잠근다:
 (1) 지시서 → GCS 브리핑 == mission_brief_t3 골든 (이음새)
 (2) 그 브리핑으로 돈 폐루프가 ARRIVED 도달 + ≥1 EVADE + 회피 후 phase 복귀 (모킹 없는 실동작 생존성)
 (3) 같은 seed 2회 = 동일 궤적 (재현성)
세부 내부 전이(heading==target_bearing 정밀, mission_corridor_resume anchor)는 #158(sim 내부 E2E) 소관.
여기선 phase 수준 생존성만 — EVADE 가 임무 끝까지 래치되지 않고 풀려야 데모 패널이 정직하다.
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT / "infra" / "sim"), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from demo import directive_to_brief, run_from_directive  # noqa: E402

_SET_MISSION = _ROOT / "examples" / "set_mission_t3.json"
_GOLDEN_BRIEF = _ROOT / "examples" / "mission_brief_t3.json"
_SEED = 42
_TICKS = 300  # t3 corridor(~2.8km) + EVADE 우회 감안 — ARRIVED 는 ~tick 223.


def _directive() -> dict:
    return json.loads(_SET_MISSION.read_text(encoding="utf-8"))


def test_directive_produces_golden_brief() -> None:
    # 이음새: GCS 가 지시서에서 뽑은 브리핑이 온보드 골든과 완전 일치.
    brief = directive_to_brief(_directive())
    assert brief == json.loads(_GOLDEN_BRIEF.read_text(encoding="utf-8"))


def test_closed_loop_reaches_arrived_with_evasion() -> None:
    # 생존성: 지시서 한 방으로 폐루프가 ARRIVED 까지 가고, 도중 실제로 회피(EVADE)한다.
    frames = run_from_directive(_directive(), seed=_SEED, ticks=_TICKS)
    phases = [f["world"]["phase"] for f in frames]
    assert "ARRIVED" in phases, "폐루프가 임무 달성(ARRIVED)에 도달해야 함"
    assert "EVADE" in phases, "경로상 위협 조우 시 실제 회피(EVADE)가 발생해야 함"
    assert phases.index("EVADE") < phases.index("ARRIVED"), "회피는 달성 이전에 일어남"


def test_evasion_resolves_not_latched() -> None:
    # 생존성 핵심: 위협 해소 후 phase 가 EVADE 에서 풀려 정상 국면으로 복귀해야 한다
    # (EVADE 래치 회귀 가드). 래치되면 데모 패널이 임무 끝까지 EVADE 로 오도됨.
    frames = run_from_directive(_directive(), seed=_SEED, ticks=_TICKS)
    phases = [f["world"]["phase"] for f in frames]
    first_evade = phases.index("EVADE")
    after = phases[first_evade:]
    assert any(p in ("TRANSIT", "ARRIVED") for p in after), "EVADE 진입 후 phase 가 복귀해야 함(래치 금지)"


def test_closed_loop_is_deterministic() -> None:
    a = run_from_directive(_directive(), seed=_SEED, ticks=_TICKS)
    b = run_from_directive(_directive(), seed=_SEED, ticks=_TICKS)
    assert [f["world"] for f in a] == [f["world"] for f in b], "같은 seed = 동일 궤적"
