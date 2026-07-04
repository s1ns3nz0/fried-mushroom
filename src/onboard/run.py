"""온보드 파이프라인 오케스트레이터 (하니스).

한 사이클을 03→04→05→06→07 순서로 엮는다 (step9.md 계약).
각 레이어는 `src/onboard/layer_XX_*/run.py` 의 순수 함수:

    layer_03.run(raw, previous_qualities)
    layer_04.run(abstraction, cycle_context)
    layer_05.run(threat, mission_brief, link_quality=...)
    layer_06.run(risk, mission_brief)
    layer_07.run(response, primary_context, cycle_context)

아직 미구현인 레이어는 스키마 적합 passthrough(canned)로 대체한다 (try-import 배선).
dev 가 layer_XX/run.py 에 run() 을 추가하면 orchestrator 수정 없이 자동 배선된다.

파이프라인은 순수(IO 없음). 파일 read / stdout 은 __main__.py(CLI) 가 담당.
로깅(JSONL 등)은 유즈사이트 책임 — 오케스트레이터에 넣지 않는다 (ARCHITECTURE 상태 관리).
"""

from __future__ import annotations

import importlib
import math

from .shared.constants import RAC_ORDER
from .corridor import assess_corridor_deviation
from .endurance import assess_endurance
from .sensor_health import assess_sensor_health

_LAYER_MODULE = {
    "03": "onboard.layer_03_abstraction.run",
    "04": "onboard.layer_04_threat.run",
    "05": "onboard.layer_05_risk.run",
    "06": "onboard.layer_06_response.run",
    "07": "onboard.layer_07_planning.run",
}


def run_cycle(
    raw: dict,
    mission_brief: dict,
    previous_qualities: dict | None = None,
    cycle_context: dict | None = None,
    previous_flight_plan_state: dict | None = None,
) -> dict:
    """한 사이클 실행. 반환:

        {"abstraction": ..., "threat": ..., "risk": ..., "response": ...,
         "flight_plan": ..., "flight_plan_state": ...}

    flight_plan_state: 07의 RAC 완화 디바운스 상태(ADR-004 07 한정 예외).
    다음 사이클엔 extract_flight_plan_state(result)로 뽑아 previous_flight_plan_state
    로 넘긴다(03의 previous_qualities/extract_qualities 와 동일 패턴).
    """
    cycle_context = cycle_context or _compute_terrain_bearings(mission_brief)

    abstraction = _run_layer("03", lambda run: run(raw, previous_qualities))
    # 03 terrain_class 방위(non-None)가 있으면 코리더 heuristic 을 덮어써 통일한다.
    # 04 직전에 적용해 04/05/07 이 동일 cycle_context(방위)를 보도록 한다 (04-unify, #145).
    cycle_context = {**cycle_context, **_extract_terrain_bearings(abstraction)}

    threat = _run_layer("04", lambda run: run(abstraction, cycle_context))
    link_quality = _extract_link_quality(abstraction)
    risk = _run_layer("05", lambda run: run(threat, mission_brief, link_quality=link_quality))
    response = _run_layer("06", lambda run: run(risk, mission_brief))

    primary = threat.get("primary")
    primary_context = primary.get("context") if primary else None
    obstacle_ttc_s = _extract_obstacle_ttc(abstraction)
    cycle_context_07 = {
        **cycle_context,  # 방위 오버라이드는 03 직후 통일 적용됨(위) — 여기서 중복 제거
        **({"obstacle_ttc_s": obstacle_ttc_s} if obstacle_ttc_s is not None else {}),
        "corridor_waypoints": mission_brief.get("corridor", {}).get("waypoints", []),
        "corridor_bases": mission_brief.get("corridor", {}).get("bases", {}),
        "weights": mission_brief.get("weights", {}),
    }
    flight_plan, flight_plan_state = _run_layer_07(
        response, primary_context, cycle_context_07, previous_flight_plan_state
    )

    endurance = assess_endurance(raw, mission_brief)
    corridor = assess_corridor_deviation(raw, mission_brief)
    sensor_health = assess_sensor_health(abstraction)

    return {
        "abstraction": abstraction,
        "threat": threat,
        "risk": risk,
        "response": response,
        "flight_plan": flight_plan,
        "flight_plan_state": flight_plan_state,
        "endurance": endurance,
        "corridor": corridor,
        "sensor_health": sensor_health,
    }


def _run_layer_07(
    response: dict,
    primary_context: dict | None,
    cycle_context_07: dict,
    debounce_state: dict | None,
) -> tuple[dict, dict]:
    """07 전용 호출 래퍼 — run()이 (FlightPlanOutput, debounce_state) 튜플을 반환하므로
    다른 레이어처럼 단일 dict 를 가정하는 _run_layer 로 처리할 수 없다.
    """
    run = _import_layer_run("07")
    if run is not None:
        return run(response, primary_context, cycle_context_07, debounce_state)
    return _STUB_OUTPUT["07"](), _STUB_FLIGHT_PLAN_STATE()


def _compute_terrain_bearings(mission_brief: dict) -> dict:
    """코리더 waypoints에서 지형 방위 산출. GIS 실조회는 후순위 — heuristic stub.

    waypoints >= 2개: wp[0]→wp[-1] bearing. 위도별 경도 거리 보정(cos(mean_lat)) 적용.
    - optimal_terrain_bearing_deg: 코리더 헤딩 (장애물 통과 방향)
    - lowest_exposure_bearing_deg: 헤딩 + 90° (교차 방향 이탈)
    waypoints < 2개: (0.0, 0.0) fallback.
    """
    wps = mission_brief.get("corridor", {}).get("waypoints", [])
    if len(wps) >= 2:
        dlat = wps[-1]["lat"] - wps[0]["lat"]
        dlon = wps[-1]["lon"] - wps[0]["lon"]
        mean_lat = math.radians((wps[0]["lat"] + wps[-1]["lat"]) / 2)
        dlon_corr = dlon * math.cos(mean_lat)
        # atan2/cos 의 마지막 ULP 는 libm(파이썬/플랫폼)마다 달라 골든을 CI(3.11)와
        # 로컬(3.13)에서 어긋나게 한다. 6자리(≈0.1m)로 반올림해 이식성 확보.
        optimal = round(math.degrees(math.atan2(dlon_corr, dlat)) % 360, 6)
        lowest = round((optimal + 90) % 360, 6)
    else:
        optimal = 0.0
        lowest = 0.0
    return {"optimal_terrain_bearing_deg": optimal, "lowest_exposure_bearing_deg": lowest}


def _extract_link_quality(abstraction: dict) -> float | None:
    """abstraction 채널에서 link_status quality 추출 (없으면 None). 05 link_quality 인자용."""
    for channel in abstraction.get("channels", []):
        if channel.get("channel") == "link_status":
            return channel.get("quality")
    return None


def _extract_terrain_bearings(abstraction: dict) -> dict:
    """terrain_class 채널 payload에서 지형 방위(non-None만) 추출. 07 cycle_context 오버라이드용.

    실제 GIS/세그멘테이션이 방위를 산출하면 코리더 heuristic(_compute_terrain_bearings)보다
    우선한다. 스텁이 None 을 주면 빈 dict 를 반환해 코리더 값을 보존한다.
    """
    for channel in abstraction.get("channels", []):
        if channel.get("channel") == "terrain_class":
            p = channel.get("payload", {})
            return {
                k: p[k]
                for k in ("optimal_terrain_bearing_deg", "lowest_exposure_bearing_deg")
                if p.get(k) is not None
            }
    return {}


def _extract_obstacle_ttc(abstraction: dict) -> float | None:
    """obstacle_proximity 채널 payload에서 TTC(s) 계산. 07 CFIT override 판정용."""
    for channel in abstraction.get("channels", []):
        if channel.get("channel") == "obstacle_proximity":
            p = channel.get("payload", {})
            d = p.get("distance_m")
            v = p.get("closure_rate_mps")
            if d is not None and v is not None and v > 0:
                return d / v
    return None


def extract_qualities(result: dict) -> dict[str, float]:
    """run_cycle 결과에서 채널명→quality 맵 추출. 다음 사이클 previous_qualities 인자용."""
    return {ch["channel"]: ch["quality"] for ch in result["abstraction"]["channels"]}


def extract_flight_plan_state(result: dict) -> dict:
    """run_cycle 결과에서 07 디바운스 상태 추출. 다음 사이클 previous_flight_plan_state 인자용."""
    return result["flight_plan_state"]


def extract_link_window(results: list[dict]) -> list[dict]:
    """chain 결과 시퀀스에서 link_status 채널 출력 윈도우 추출. assess_link_loss 입력용."""
    window = []
    for r in results:
        for ch in r["abstraction"]["channels"]:
            if ch["channel"] == "link_status":
                window.append(ch)
                break
    return window


def extract_nav_window(results: list[dict]) -> list[dict]:
    """chain 결과 시퀀스에서 position_consistency 채널 출력 윈도우 추출. assess_nav_integrity 입력용."""
    window = []
    for r in results:
        for ch in r["abstraction"]["channels"]:
            if ch["channel"] == "position_consistency":
                window.append(ch)
                break
    return window


def _cycle_interval_s(ts_ms, prev_ts_ms) -> float:
    """연속 두 raw 의 ts_ms 델타(초). 산출 불가(결측/역행) 시 1.0 폴백.

    advisory 지속시간(outage/untrusted_seconds)·HOLD/RTL/LAND 임계는 실경과시간에 좌우되므로
    스트림 실제 cadence 를 ts_ms 로 도출한다(1Hz 하드코딩 금지, codex P2)."""
    if isinstance(ts_ms, (int, float)) and isinstance(prev_ts_ms, (int, float)) and ts_ms > prev_ts_ms:
        return (ts_ms - prev_ts_ms) / 1000.0
    return 1.0


def run_cycle_chain(
    pairs,
    previous_qualities: dict | None = None,
    previous_flight_plan_state: dict | None = None,
    previous_link_window: list[dict] | None = None,
    previous_nav_window: list[dict] | None = None,
    previous_ts_ms: int | float | None = None,
) -> list[dict]:
    """(raw, mission_brief) 시퀀스를 연속 실행하며 사이클 간 상태를 자동 스레딩한다 (#133).

    각 사이클 결과에서 `extract_qualities`/`extract_flight_plan_state` 를 뽑아 다음 사이클
    previous_qualities/previous_flight_plan_state 로 자동 연결한다 — CLI `--prev-qualities`
    수동 주입 없이도 quality_delta(T5 광학 교란 등)가 연속 스트림에서 자연 발화한다.

    각 사이클 결과에 cross-cycle advisory 를 추가한다:
    - link_loss (#389): 누적 link_status 윈도우 → C2 통신두절 failsafe 타임라인
    - nav_integrity (#389): 누적 position_consistency 윈도우 → GNSS 항법 failsafe 타임라인
    - failsafe (#399): endurance(energy)·link_loss(comms)·nav_integrity(nav) 3축을
      most-conservative-wins 로 융합한 통합 failsafe 권고
    CRITICAL: advisory_only — 결정론 판정(risk/threat/response/flight_plan) 불변(SCC-1).

    pairs: iterable of (raw, mission_brief). 반환: 사이클별 run_cycle 결과 리스트.
    체인 이어붙이기(분할 스트림): quality/flight_plan_state 뿐 아니라 **advisory 윈도우**
    (previous_link_window/previous_nav_window)와 직전 ts_ms(previous_ts_ms)도 주입해야
    지속 두절/신뢰상실 스트릭이 배치 경계에서 리셋되지 않는다(codex P2). 3+배치는 윈도우를
    **누적**해서 넘긴다(마지막 배치만 추출하면 히스토리 소실):
        win = win + extract_link_window(batch_results)

    cycle_interval_s 는 raw.ts_ms 델타에서 도출된다(1Hz 하드코딩 아님) — 등cadence 정확.
    가변 cadence 구간 스트릭의 실경과 합산 정밀화는 후속 #410.
    """
    from .link_loss import assess_link_loss
    from .nav_integrity import assess_nav_integrity
    from .failsafe_arbiter import assess_failsafe

    results: list[dict] = []
    prev_q = previous_qualities
    prev_fp = previous_flight_plan_state
    link_window: list[dict] = list(previous_link_window or [])
    nav_window: list[dict] = list(previous_nav_window or [])
    prev_ts = previous_ts_ms

    for raw, mission_brief in pairs:
        result = run_cycle(
            raw,
            mission_brief,
            previous_qualities=prev_q,
            previous_flight_plan_state=prev_fp,
        )
        # cross-cycle advisory 윈도우 갱신
        for ch in result["abstraction"]["channels"]:
            if ch["channel"] == "link_status":
                link_window.append(ch)
            elif ch["channel"] == "position_consistency":
                nav_window.append(ch)
        ts = raw.get("ts_ms")
        interval = _cycle_interval_s(ts, prev_ts)
        if isinstance(ts, (int, float)):
            prev_ts = ts
        result = dict(result)
        result["link_loss"] = assess_link_loss(link_window, cycle_interval_s=interval)
        result["nav_integrity"] = assess_nav_integrity(nav_window, cycle_interval_s=interval)
        result["failsafe"] = assess_failsafe({
            "energy": result["endurance"],
            "comms": result["link_loss"],
            "nav": result["nav_integrity"],
        })
        results.append(result)
        prev_q = extract_qualities(result)
        prev_fp = extract_flight_plan_state(result)
    return results


def _run_layer(num: str, invoke):
    """레이어 run() 이 있으면 invoke(run) 으로 호출, 없으면 canned passthrough."""
    run = _import_layer_run(num)
    if run is not None:
        return invoke(run)
    return _STUB_OUTPUT[num]()


def _import_layer_run(num: str):
    try:
        module = importlib.import_module(_LAYER_MODULE[num])
    except ModuleNotFoundError:
        return None
    run = getattr(module, "run", None)
    return run if callable(run) else None


# 미구현 레이어용 최소 스키마 적합 고정 출력 (각 OutputSchema 의 최소 인스턴스).
_STUB_OUTPUT = {
    "03": lambda: {
        "schema_version": "0.0-stub",
        "id": "stub",
        "ts": 0,
        "channels": [],
    },
    "04": lambda: {
        "declared_phase": "unknown",
        "mission_phase_confidence": 0.0,
        "candidates": [],
        "primary": None,
        "background_exposure_score": 0.0,
    },
    "05": lambda: {
        "candidates": [],
    },
    "06": lambda: {
        "primary_threat_event": None,
        "rac": "Low",
        "kill_chain_stage": None,
        "threat_category": None,
        "flight_action": "MAINTAIN",
        "comms_level": "L0",
        "payload_action": [],
        "nav_mode": None,
        "special_action": None,
        "secondary_threats": [],
        "ai_reliability": "normal",
    },
    "07": lambda: {
        "flight_action": "MAINTAIN",
        "target_bearing_deg": None,
        "altitude_delta_m": 0,
        "replan_scope": "NONE",
        "reroute_anchor": "mission_corridor_resume",
        "route": [],
        "speed_mode": "NORMAL",
    },
}


def _STUB_FLIGHT_PLAN_STATE() -> dict:
    """07 fallback(모듈 부재) 시 디바운스 상태 초기값 — _STUB_OUTPUT["07"]의 MAINTAIN/Low 모양과 일치."""
    return {
        "committed_rac_order": RAC_ORDER["Low"],
        "committed_flight_action": "MAINTAIN",
        "committed_primary_threat_event": None,
        "committed_kill_chain_stage": None,
        "candidate_rac_order": None,
        "candidate_streak": 0,
    }
