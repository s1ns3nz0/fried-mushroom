"use strict";

// D4D 대시보드 — 실시간 로그 스트림 클라이언트 + Canvas/HTML mock 시나리오 렌더.
// 대시보드는 판단하지 않는다 — 로그수집기의 로그와 mock 결정 로그를 수신해 표시만 한다.
//
// 로그수집기 WS /logs 메시지 포맷:
//   { correlation_id, layer, log, level: "info"|"warn"|"error", ts: <epoch ms> }
// 접속 시 최근 backlog 가 먼저 도착한다. 실 수신 로그는 layer 를 SRC 태그로
// 매핑해 시스템 로그 패널(C)에 같은 형식으로 표시한다.
//
// AI 결정 로그(B 패널)는 현재 mock 시나리오 이벤트로만 구동된다
// (handleDecisionLog 참고 — 향후 대시보드 /ws decision_log 타입 연동 스텁).

// ── 설정 ──────────────────────────────────────────────────────

const DEFAULT_LOG_WS_URL = "ws://localhost:8500/logs";
const MAX_LOG_ITEMS = 400; // 오래된 항목은 잘라 메모리 방어.

// level → CSS 클래스.
const LEVEL_CLASS = { info: "lvl-info", warn: "lvl-warn", error: "lvl-error" };

// ── 상태 ──────────────────────────────────────────────────────

const state = {
  ws: null,
  connected: false,
  reconnectDelay: 1000, // backoff (ms), 최대 15s.
  logWsUrl: DEFAULT_LOG_WS_URL, // /config 로 갱신되는 자동연결 대상.
};

// Canvas 2D 핸들 (지도/고도 mock 렌더 대상). 신호는 HTML 리스트(#signals-list)로 렌더.
const canvases = {
  map: document.getElementById("map-canvas"),
  profile: document.getElementById("profile-canvas"),
};

// ── 순수 로직 (브라우저 없이도 검증 가능) ──────────────────────

/** epoch ms → HH:MM:SS.mmm */
function formatTs(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n)) return String(ts != null ? ts : "");
  const d = new Date(n);
  const p2 = (v) => String(v).padStart(2, "0");
  const p3 = (v) => String(v).padStart(3, "0");
  return (
    p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":" +
    p2(d.getSeconds()) + "." + p3(d.getMilliseconds())
  );
}

/** 수신 payload 를 정규화(누락 필드 방어). layer → SRC 태그로 매핑. */
function normalizeEntry(raw) {
  return {
    src: raw && raw.layer != null ? String(raw.layer) : "SYS",
    log: raw && raw.log != null ? String(raw.log) : "",
    level: raw && LEVEL_CLASS[raw.level] ? raw.level : "info",
    ts: raw && raw.ts != null ? raw.ts : Date.now(),
  };
}

// ── DOM 렌더 ──────────────────────────────────────────────────

const el = {
  status: document.getElementById("conn-status"),
  list: document.getElementById("log-list"),
  count: document.getElementById("log-count"),
  logStatus: document.getElementById("log-status"),
  signalsList: document.getElementById("signals-list"),
  decisionList: document.getElementById("decision-list"),
  deviceStrip: document.getElementById("device-strip"),
  phaseChip: document.getElementById("phase-chip"),
};

function setStatus(text, ok) {
  if (el.status) {
    el.status.textContent = text;
    el.status.classList.toggle("status-on", !!ok);
    el.status.classList.toggle("status-off", !ok);
  }
  // Panel C header mini status dot mirrors the same connection state.
  if (el.logStatus) {
    el.logStatus.classList.toggle("status-on", !!ok);
    el.logStatus.classList.toggle("status-off", !ok);
    el.logStatus.title = text;
  }
}

/** 리스트가 바닥 근처인지(자동 스크롤 여부 판단). */
function isNearBottom(node) {
  return node.scrollHeight - node.scrollTop - node.clientHeight < 40;
}

/**
 * 시스템 로그 한 줄을 리스트에 append (최신이 아래로, 자동스크롤).
 * 형식: [HH:MM:SS.mmm] [SRC] message — SRC 는 muted 태그 칩, level 별 색 유지.
 */
function appendLog(raw) {
  const entry = normalizeEntry(raw);
  const li = document.createElement("li");
  li.className = "log-item " + (LEVEL_CLASS[entry.level] || "lvl-info");

  const ts = document.createElement("span");
  ts.className = "log-ts";
  ts.textContent = "[" + formatTs(entry.ts) + "]";

  const src = document.createElement("span");
  // Per-SRC muted tag chip; unknown sources fall back to the base chip style.
  src.className = "log-src src-" + entry.src.toLowerCase().replace(/[^a-z0-9_-]/g, "");
  src.textContent = entry.src;

  const msg = document.createElement("span");
  msg.className = "log-msg";
  msg.textContent = " " + entry.log;

  li.append(ts, src, msg);

  const stick = isNearBottom(el.list);
  el.list.appendChild(li);

  // 오래된 항목 제거.
  while (el.list.childElementCount > MAX_LOG_ITEMS) {
    el.list.removeChild(el.list.firstElementChild);
  }
  if (stick) el.list.scrollTop = el.list.scrollHeight;
  updateCount();
}

function updateCount() {
  if (el.count) el.count.textContent = String(el.list.childElementCount);
}

// ── WS 클라이언트 ─────────────────────────────────────────────
// Headless auto-connect: no manual toggle — /config resolves the URL,
// then connect() runs with backoff reconnect until the collector is up.

/** 로그수집기 WS /logs 에 연결. backlog → 실시간 순으로 수신. */
function connect() {
  let ws;
  try {
    ws = new WebSocket(state.logWsUrl);
  } catch (e) {
    setStatus("bad url", false);
    return;
  }
  state.ws = ws;
  setStatus("connecting…", false);

  ws.onopen = () => {
    state.connected = true;
    state.reconnectDelay = 1000;
    setStatus("connected", true);
  };
  ws.onclose = () => {
    state.connected = false;
    setStatus("disconnected", false);
    scheduleReconnect();
  };
  ws.onerror = () => {
    // onclose 가 뒤따르므로 상태 갱신만.
    setStatus("error", false);
  };
  ws.onmessage = (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (e) {
      return; // 파싱 실패 로그는 드롭(관측 전용, 재판단 없음).
    }
    // backlog 가 배열로 오는 경우도 허용.
    if (Array.isArray(msg)) {
      msg.forEach(appendLog);
    } else {
      appendLog(msg);
    }
  };
}

function scheduleReconnect() {
  const delay = state.reconnectDelay;
  state.reconnectDelay = Math.min(delay * 2, 15000);
  setStatus("reconnect " + Math.round(delay / 1000) + "s…", false);
  setTimeout(() => {
    if (!state.connected) connect();
  }, delay);
}

// ── UAV 시스템 로그 생성기(mock) ──────────────────────────────
// Panel C content: system logs that actuate the UAV (CAN/FC/GPS/IMU/LINK/
// BATT/GIMBAL/NAV). Values are derived from the same mock state variables
// the device tiles / channel mocks read (mock.battery/gps/comms/speedMps),
// so numbers stay consistent across panels. Real collector WS entries
// append into the same list via appendLog (layer mapped to SRC).

const SYS_LOG_INTERVAL_MS = 600; // rotation tick → ~1.7 lines/s mixed.
// Periodic source rotation — CAN (ESC command bus) most frequent.
const SYS_ROTATION = ["CAN", "FC", "GPS", "CAN", "LINK", "BATT", "CAN", "FC", "IMU", "GPS"];
let sysSeq = 0;

function emitSys(src, msg, level) {
  appendLog({ layer: src, log: msg, level: level || "info", ts: Date.now() });
}

/** mock.phase → FC flight mode string. */
function fcMode() {
  return mock.phase === "ENCOUNTER" ? "GUIDED" : mock.phase === "RTL" ? "RTL" : "AUTO";
}

/** Current target waypoint (1-based) over total path nodes, e.g. "4/7". */
function wpLabel() {
  let acc = 0, i = 0;
  for (; i < _seg.length; i++) {
    acc += _seg[i];
    if (mock.s < acc) break;
  }
  return Math.min(i + 1, PATH.length - 1) + "/" + PATH.length;
}

/** Emit one periodic system log line from the rotation. */
function emitPeriodicSysLog() {
  const src = SYS_ROTATION[sysSeq % SYS_ROTATION.length];
  sysSeq++;
  const jitter = Math.sin(mock.odo * 6);
  const jam = commsJam();
  switch (src) {
    case "CAN": {
      // Same rpm/temp/vib formulas as the device rows (computeDeviceStats).
      const base = escRpm(jitter);
      if (sysSeq % 2) {
        emitSys("CAN", "[0x1A0] ESC cmd rpm=" +
          [base + 5, base - 25, base + 15, base].join(","));
      } else {
        emitSys("CAN", "[0x1A5] ESC telem rpm=" + base + " temp=" +
          escTempC(jitter).toFixed(0) + "°C vib=" + frameVib(jitter).toFixed(2) + "g");
      }
      break;
    }
    case "FC":
      emitSys("FC", "heartbeat mode=" + fcMode() + " wp=" + wpLabel());
      break;
    case "GPS":
      emitSys("GPS", "fix 3D sats=" + gpsSats() + " hdop=" + gpsHdop().toFixed(1));
      break;
    case "LINK": {
      const latency = linkLatency(jam);
      emitSys("LINK", "rssi=" + linkRssi(jam) + "dBm latency=" + latency + "ms",
        latency > 200 ? "warn" : "info");
      break;
    }
    case "BATT": {
      const voltage = battVoltage();
      emitSys("BATT", voltage.toFixed(1) + "V " + Math.round(mock.battery) +
        "% cell_min=" + (voltage / 6 - 0.02).toFixed(2) + "V",
        mock.battery < 20 ? "warn" : "info");
      break;
    }
    case "IMU":
      emitSys("IMU", "att r=" + fmtSigned(mock.att.roll, 1) + " p=" +
        fmtSigned(mock.att.pitch, 1) + " y=" + fmtHeading(mock.att.yaw) +
        " gyro p/q/r=" + fmtSigned(mock.gyro.p, 1) + "/" + fmtSigned(mock.gyro.q, 1) +
        "/" + fmtSigned(mock.gyro.r, 1) + "°/s");
      break;
  }
}

// ── AI 결정 로그(B 패널) ──────────────────────────────────────
// mock 시나리오 이벤트에서만 구동된다(관측 전용, 재판단 없음).

const MAX_DECISION_EVENTS = 30;

const DECISION_TYPES = {
  detect: { label: "탐지", cls: "badge-detect" },
  assess: { label: "평가", cls: "badge-assess" },
  respond: { label: "대응", cls: "badge-respond" },
  replan: { label: "재계획", cls: "badge-replan" },
  resume: { label: "재개", cls: "badge-resume" },
};

// 열린 이벤트 박스 — 탐지에서 시작해 평가/대응/재계획/재개가 같은 박스에 쌓인다.
const decisionEvt = { seq: 0, openStages: null };

/** 새 조우 이벤트 박스를 #decision-list 에 append 하고 stage 컨테이너를 연다. */
function beginDecisionEvent() {
  decisionEvt.seq++;
  // Amber left-edge indicator follows the latest open event box.
  const prevActive = el.decisionList.querySelector(".decision-event.evt-active");
  if (prevActive) prevActive.classList.remove("evt-active");
  const li = document.createElement("li");
  li.className = "decision-event evt-active";

  const head = document.createElement("div");
  head.className = "decision-event-head";

  const id = document.createElement("span");
  id.className = "evt-id";
  id.textContent = "EVT-" + String(decisionEvt.seq).padStart(3, "0");

  const ts = document.createElement("span");
  ts.className = "evt-ts";
  ts.textContent = formatTs(Date.now());

  head.append(id, ts);

  const stages = document.createElement("div");
  stages.className = "decision-stages";

  li.append(head, stages);

  const stick = isNearBottom(el.decisionList);
  el.decisionList.appendChild(li);
  while (el.decisionList.childElementCount > MAX_DECISION_EVENTS) {
    el.decisionList.removeChild(el.decisionList.firstElementChild);
  }
  if (stick) el.decisionList.scrollTop = el.decisionList.scrollHeight;

  decisionEvt.openStages = stages;
  return stages;
}

/** AI 결정 stage 1건 — 탐지는 새 이벤트 박스를 열고, 나머지는 열린 박스에 append. */
function pushDecision(type, message) {
  if (!el.decisionList) return;
  const meta = DECISION_TYPES[type] || { label: type, cls: "badge-respond" };
  const stages = (type === "detect" || !decisionEvt.openStages)
    ? beginDecisionEvent()
    : decisionEvt.openStages;

  const row = document.createElement("div");
  row.className = "decision-stage";

  const badge = document.createElement("span");
  badge.className = "decision-badge " + meta.cls;
  badge.textContent = meta.label;

  const msg = document.createElement("span");
  msg.className = "log-msg";
  msg.textContent = message;

  const ts = document.createElement("span");
  ts.className = "stage-ts";
  ts.textContent = formatTs(Date.now());

  row.append(badge, msg, ts);

  const stick = isNearBottom(el.decisionList);
  stages.appendChild(row);
  if (stick) el.decisionList.scrollTop = el.decisionList.scrollHeight;
}

/**
 * 향후 대시보드 /ws 의 decision_log 타입 메시지 핸들러(스텁).
 * TODO(연동): 실제 온보드 파이프라인이 decision_log 이벤트를 WS로 보내면
 * 여기서 msg.type/msg.message 를 pushDecision 에 그대로 연결한다.
 * 현재는 WS 연결을 구현하지 않고 mock 시나리오 이벤트만 pushDecision 을 직접 호출한다.
 */
function handleDecisionLog(msg) {
  if (!msg) return;
  pushDecision(msg.type, msg.message);
}

// ── mock 시나리오 시뮬레이터 (uav tick WS 연동 시 교체) ─────────
// 로그 패널 mock 과 별개로, 지도/고도/신호 3칸을 구동하는 내부 mock.
// 시나리오: 출발지 → 목표 정상 비행 → T3 조우 → RTL(복귀) 루프.
// uav tick WS 연동 시 아래 mock 상태를 실제 platform_state/signal 로 교체한다.

const SCENARIO = { start: "출발지", goal: "목표", threat: "T3" };

// 지도 스케일 — 지도 폭(가로)의 실거리 환산 기준(m). 도심 두 지점 간
// 직선거리 ~2.5km 급 스케일. PATH 길이(정규 단위) × 이 값 = 경로 실거리(m).
const MAP_EXTENT_M = 3000;

// UAV 속도(m/s) — 소형 정찰 멀티로터 기준.
const UAV_CRUISE_MPS = 17;    // 순항(정상 비행) ~61km/h
const UAV_RTL_MPS = 20;       // 복귀 시 증속
const UAV_ENCOUNTER_MPS = 6;  // 조우 중 회피 저속 비행(evasive crawl)

// 경로 웨이포인트(정규 좌표 0..1). node=(x, y). 봉우리를 피해 저지대로.
const PATH = [
  { x: 0.08, y: 0.86 },
  { x: 0.20, y: 0.72 },
  { x: 0.36, y: 0.74 },
  { x: 0.50, y: 0.60 },
  { x: 0.60, y: 0.46 },
  { x: 0.72, y: 0.38 },
  { x: 0.88, y: 0.20 },
];

// 지형 봉우리(정규 좌표) — heightAt 로 표고장 생성.
const PEAKS = [
  { x: 0.28, y: 0.30, h: 0.95, r: 0.17 },
  { x: 0.66, y: 0.58, h: 0.80, r: 0.15 },
  { x: 0.48, y: 0.14, h: 0.62, r: 0.13 },
  { x: 0.82, y: 0.74, h: 0.58, r: 0.13 },
  { x: 0.14, y: 0.62, h: 0.45, r: 0.12 },
];

// 적 T3(정규 좌표 + 탐지 반경). 경로 인접에 배치해 조우 트리거.
const ENEMY = { x: 0.635, y: 0.40, r: 0.12 };

// 표고장: 봉우리 가우시안 합. 반환 0..1.
function heightAt(x, y) {
  let h = 0.10;
  for (let i = 0; i < PEAKS.length; i++) {
    const p = PEAKS[i];
    const dx = x - p.x, dy = y - p.y;
    h += p.h * Math.exp(-(dx * dx + dy * dy) / (2 * p.r * p.r));
  }
  return h > 1 ? 1 : h;
}

// 경로 누적 길이(정규 단위).
const _seg = [];
let _total = 0;
(function initPath() {
  for (let i = 0; i < PATH.length - 1; i++) {
    const dx = PATH[i + 1].x - PATH[i].x, dy = PATH[i + 1].y - PATH[i].y;
    const L = Math.hypot(dx, dy);
    _seg.push(L);
    _total += L;
  }
})();

// 경로 총 길이(m) — 웨이포인트 기하(정규 단위) × 지도 스케일(MAP_EXTENT_M).
const PATH_LENGTH_M = _total * MAP_EXTENT_M;

/** 경로 시작에서 거리 d 지점의 {x, y, head}. */
function pointAtDist(d) {
  if (d <= 0) {
    const a = PATH[0], b = PATH[1];
    return { x: a.x, y: a.y, head: Math.atan2(b.y - a.y, b.x - a.x) };
  }
  if (d >= _total) {
    const a = PATH[PATH.length - 2], b = PATH[PATH.length - 1];
    return { x: b.x, y: b.y, head: Math.atan2(b.y - a.y, b.x - a.x) };
  }
  let acc = 0;
  for (let i = 0; i < _seg.length; i++) {
    if (acc + _seg[i] >= d) {
      const t = (d - acc) / _seg[i];
      const a = PATH[i], b = PATH[i + 1];
      return {
        x: a.x + (b.x - a.x) * t,
        y: a.y + (b.y - a.y) * t,
        head: Math.atan2(b.y - a.y, b.x - a.x),
      };
    }
    acc += _seg[i];
  }
  const a = PATH[PATH.length - 2], b = PATH[PATH.length - 1];
  return { x: b.x, y: b.y, head: Math.atan2(b.y - a.y, b.x - a.x) };
}

/** RTL 중 복귀경로(출발점 → 현재 드론 위치까지 이미 지나온 경로) 포인트 목록. */
function returnPathPoints() {
  const pts = [PATH[0]];
  let acc = 0;
  for (let i = 0; i < PATH.length - 1; i++) {
    acc += _seg[i];
    if (acc <= mock.s) pts.push(PATH[i + 1]);
    else break;
  }
  pts.push({ x: mock.pos.x, y: mock.pos.y });
  return pts;
}

// mock 상태(NORMAL → ENCOUNTER → RTL 루프).
const mock = {
  s: 0, dir: 1, phase: "NORMAL", phaseT: 0,
  battery: 97, gps: 0.98, comms: 3, rac: 0,
  odo: 0, trailProfile: [], pos: { x: PATH[0].x, y: PATH[0].y }, head: 0,
  enemyActive: false, alt: 0, terr: 0, dEnemy: 1,
  _assessed: false, _responded: false, _failsafed: false,
  chanQ: {}, // 채널별 이전 quality(quality_delta = quality(t) - quality(t-1) 계산용).
  speedMps: UAV_CRUISE_MPS, // 현재 프레임 UAV 대지속도(m/s) — updateMock에서 phase별로 갱신.
  att: { roll: 0, pitch: 0, yaw: 0 }, // FC 자세(deg) — 운동상태에서 유도(updateMock, 저역통과).
  gyro: { p: 0, q: 0, r: 0 }, // 기체 각속도(deg/s) — roll/pitch/yaw 미분(저역통과).
  vs: 0, // 수직속도(m/s) — mock.alt 미분(저역통과).
  _prevHead: null, _prevAlt: null, _altTarget: null,
  timeScale: 1, // 배속(×1/×2/×4/×8) — 시뮬레이션 시간에만 적용(WS 재연결/실제 timestamp/rAF 제외).
};

const CLEAR_M = 120;  // 지형추종 여유고도(m)
// Altitude chase model — mock.alt follows a target altitude inside a realistic
// climb/descent envelope (small multirotor class) instead of teleporting.
const EVADE_CLIMB_M = 40;       // evasive climb target above terrain-following altitude (m)
const ALT_CLIMB_MAX_MPS = 5;    // max climb rate (m/s)
const ALT_SINK_MAX_MPS = 4;     // max descent rate (m/s)
const ALT_APPROACH_GAIN = 0.8;  // proportional approach rate near target (1/s)
const ALT_TARGET_TAU_S = 2;     // low-pass time constant of the altitude target (s)
const ALT_PLAN_VS_MPS = 2.2;    // planned cruise climb/descent budget (m/s at cruise speed)
const ALT_PLAN_N = 512;         // precomputed altitude-plan samples along the path
function elevM(h) { return 190 + h * 650; }

// Terrain-following altitude plan — precomputed slope-limited envelope over
// terrain+CLEAR_M along the static path. The two max-passes guarantee
// plan >= terrain+CLEAR_M everywhere while bounding |d(alt)/dt| at cruise
// speed to ALT_PLAN_VS_MPS, so climbs start early instead of hugging slopes.
const ALT_PLAN = (function () {
  const n = ALT_PLAN_N;
  const plan = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const pt = pointAtDist(_total * i / (n - 1));
    plan[i] = elevM(heightAt(pt.x, pt.y)) + CLEAR_M;
  }
  // Max altitude change per sample step for the VS budget at cruise speed.
  const stepM = ALT_PLAN_VS_MPS * (PATH_LENGTH_M / UAV_CRUISE_MPS) / (n - 1);
  for (let i = n - 2; i >= 0; i--) plan[i] = Math.max(plan[i], plan[i + 1] - stepM);
  for (let i = 1; i < n; i++) plan[i] = Math.max(plan[i], plan[i - 1] - stepM);
  return plan;
})();

/** Planned terrain-following altitude at path position s (0.._total), lerped. */
function altPlanAt(s) {
  const f = Math.max(0, Math.min(1, s / _total)) * (ALT_PLAN.length - 1);
  const i = Math.floor(f);
  if (i >= ALT_PLAN.length - 1) return ALT_PLAN[ALT_PLAN.length - 1];
  return ALT_PLAN[i] + (ALT_PLAN[i + 1] - ALT_PLAN[i]) * (f - i);
}

// ── 지형 격자(u16) — heightAt 목업을 1회 샘플링해 render.js 레이어 빌더에 공급 ──
// 실제 DEM 도입 시 이 샘플링부만 교체하면 된다(u16 인터페이스는 그대로 유지된다).

const GRID = 200; // u16 격자 크기(W=H=200) — 뷰셰드/footprint 도 같은 격자를 공유한다.

// 정규 좌표(0..1, y=0 상단)를 격자 좌표로 변환. gridY는 u16 배열의 "행 0 = 하단"
// 관례(render.js의 buildTerrainLayer 참조)에 맞춰 y를 반전한다.
function gridX(nx) { return nx * (GRID - 1); }
function gridY(ny) { return (1 - ny) * (GRID - 1); }

/** heightAt(정규 0..1 가우시안 목업)을 GRIDxGRID u16 격자로 1회 샘플링한다.
 * 실제 표고(m)는 elevM으로 변환해 hmin/hmax(관측된 실제 범위)도 함께 계산한다. */
function buildTerrainGrid() {
  const W = GRID, H = GRID;
  const elevations = new Float32Array(W * H);
  let hmin = Infinity, hmax = -Infinity;
  for (let ry = 0; ry < H; ry++) {
    const ny = 1 - ry / (H - 1);
    for (let gx = 0; gx < W; gx++) {
      const nx = gx / (W - 1);
      const hm = elevM(heightAt(nx, ny));
      elevations[ry * W + gx] = hm;
      if (hm < hmin) hmin = hm;
      if (hm > hmax) hmax = hm;
    }
  }
  const range = (hmax - hmin) || 1;
  const u16 = new Uint16Array(W * H);
  for (let i = 0; i < W * H; i++) {
    u16[i] = Math.round(((elevations[i] - hmin) / range) * 65535);
  }
  return { u16, W, H, hmin, hmax };
}

const terrainGrid = buildTerrainGrid();
// buildTerrainLayer는 시각화용 — u16이 이미 0..65535로 정규화돼 있으므로
// hmin/hmax는 0/65535 그대로 넘긴다(test-board 관례와 동일, 실제 물리 hmin/hmax는
// terrainGrid.hmin/hmax에 별도 보관해 뷰셰드/footprint 고각 계산에 사용한다).
const terrainLayer = D4DRender.buildTerrainLayer(terrainGrid.u16, terrainGrid.H, terrainGrid.W, 0, 65535);

// 적 탐지 footprint — 적이 정적이므로 1회만 계산해 캐시한다.
const FOOTPRINT_COLOR = [240, 85, 93, Math.round(0.32 * 255)]; // 반투명 빨강(적)
const enemyFootprintLayer = (function () {
  const enemyGrid = {
    center: [gridX(ENEMY.x), gridY(ENEMY.y)],
    detect_range: ENEMY.r * (GRID - 1),
  };
  const mask = D4DRender.computeEnemyFootprint(
    terrainGrid.u16, terrainGrid.H, terrainGrid.W, terrainGrid.hmin, terrainGrid.hmax, enemyGrid
  );
  return D4DRender.buildFootprintLayer(mask, terrainGrid.H, terrainGrid.W, FOOTPRINT_COLOR);
})();

// UAV 뷰셰드 — 매 프레임 재계산하지 않고, 드론이 ≥2 격자셀 이동했거나 250ms 지났을 때만 갱신.
const VIEWSHED_COLOR = [102, 194, 255, Math.round(0.22 * 255)]; // 반투명 쿨블루(UAV — friendly 계열)
const VIEWSHED_RECOMPUTE_MS = 250;
const VIEWSHED_MOVE_CELLS = 2;
let viewshedLayer = null;
let lastViewshedGrid = null; // {gx, gy} — 마지막으로 뷰셰드를 계산한 격자 좌표
let lastViewshedTime = 0;

/** 드론 이동/경과시간 기준으로 뷰셰드 레이어 캐시를 필요할 때만 갱신한다.
 * 드론 alt(mock.alt)는 elevM과 동일한 미터 스케일(지형고도+clearance+회피고도)이므로,
 * 저지대/고지대 통과 시 고각 계산이 실제로 달라져 뷰셰드 범위가 지형에 반응한다. */
function updateViewshedLayer(now) {
  const gx = gridX(mock.pos.x), gy = gridY(mock.pos.y);
  const moved = !lastViewshedGrid ||
    Math.hypot(gx - lastViewshedGrid.gx, gy - lastViewshedGrid.gy) >= VIEWSHED_MOVE_CELLS;
  const timedOut = now - lastViewshedTime >= VIEWSHED_RECOMPUTE_MS;
  if (viewshedLayer && !moved && !timedOut) return;
  const drone = { x: gx, y: gy, alt: mock.alt };
  const mask = D4DRender.computeViewshed(
    terrainGrid.u16, terrainGrid.H, terrainGrid.W, terrainGrid.hmin, terrainGrid.hmax, drone
  );
  viewshedLayer = D4DRender.buildViewshedLayer(mask, terrainGrid.H, terrainGrid.W, VIEWSHED_COLOR);
  lastViewshedGrid = { gx, gy };
  lastViewshedTime = now;
}

/** 배터리/품질 대비 색. */
function lvlColor(f) { return f > 0.5 ? "#4CC38A" : (f > 0.2 ? "#E5A93D" : "#F0555D"); }

// ── 공유 텔레메트리 산식 — 기체 신호 패널/11채널 패널/시스템 로그가 같은 값을 쓴다 ──

/** comms(0..3) → 재밍 정도(0..1). */
function commsJam() { return Math.max(0, Math.min(1, (3 - mock.comms) / 3)); }
function linkRssi(jam) { return Math.round(-62 - jam * 30); }
function linkLatency(jam) { return Math.round(45 + jam * 300); }
function linkLoss(jam) { return Math.min(0.4, jam * 0.35 + 0.01); }
/** 6S 리포 근사 전압(% 선형 매핑). */
function battVoltage() { return 19.8 + (mock.battery / 100) * 5.4; }
/** 소비전류(A) — 호버 기저 ~12A + 속도/상승(클램프)/회피 기동 가산. */
function battCurrentA() {
  return 12 + Math.max(0, mock.speedMps - 6) * 0.6 +
    Math.min(6, Math.max(0, mock.vs)) * 2 +
    (mock.phase === "ENCOUNTER" ? 5 : 0);
}
function gpsSats() { return Math.round(6 + mock.gps * 10); }
function gpsHdop() { return 0.9 + (1 - mock.gps) * 4; }
function gpsResidualM() { return (1 - mock.gps) * 8; }
function escRpm(jitter) { return Math.round(7600 + mock.speedMps * 35 + jitter * 60); }
function escTempC(jitter) { return 42.0 + jitter * 1.5; }
function frameVib(jitter) { return 0.12 + Math.abs(jitter) * 0.03; }

/** 부호 표기 고정 소수(deg 등): +12.3 / -2.1 */
function fmtSigned(v, digits) { return (v >= 0 ? "+" : "") + v.toFixed(digits); }
/** 컴퍼스 방위 3자리 zero-pad: 087 */
function fmtHeading(deg) { return String(Math.round(((deg % 360) + 360) % 360) % 360).padStart(3, "0"); }

/** mock 시나리오 상태 전이 + 신호/고도 갱신. dt는 실제 프레임 간격(s) —
 * 상단에서 timeScale을 1회 곱해 시뮬레이션 시간(simDt)으로 변환한 뒤 전 구간에서 사용한다. */
function updateMock(dt) {
  dt = dt * mock.timeScale; // simDt — 이하 모든 mock 시간 소비가 배속을 따른다.
  mock.phaseT += dt;
  // 실제 UAV 속도(m/s) — phase별 순항/조우저속/RTL증속을 실거리 기준 progress로 환산.
  const speedMps = mock.phase === "ENCOUNTER" ? UAV_ENCOUNTER_MPS
    : mock.phase === "RTL" ? UAV_RTL_MPS
    : UAV_CRUISE_MPS;
  mock.speedMps = speedMps;
  const dsNorm = mock.dir * (speedMps / PATH_LENGTH_M) * dt;
  mock.s += dsNorm;
  if (mock.s < 0) mock.s = 0;
  if (mock.s > _total) mock.s = _total;

  const p = pointAtDist(mock.s);
  mock.pos = p;
  mock.head = p.head;
  mock.odo += Math.abs(dsNorm);

  const dEnemy = Math.hypot(p.x - ENEMY.x, p.y - ENEMY.y);
  mock.dEnemy = dEnemy;
  mock.enemyActive = dEnemy < ENEMY.r * 1.6;

  // 상태기계 — 전이 시점마다 AI 결정 로그(B 패널) + 시스템 로그(C 패널)를 함께 emit.
  if (mock.phase === "NORMAL") {
    if (mock.dir > 0 && dEnemy < ENEMY.r) {
      mock.phase = "ENCOUNTER"; mock.phaseT = 0;
      pushDecision("detect", "위협 감지 — T3 근접 위협 탐지 (proximity_object anomaly)");
      const brg = Math.round(((Math.atan2(ENEMY.y - p.y, ENEMY.x - p.x) * 180) / Math.PI + 360) % 360);
      emitSys("FC", "mode AUTO→GUIDED (evasive)", "warn");
      emitSys("CAN", "[0x1A0] ESC cmd rpm↑ " +
        Math.round(escRpm(0) * 1.15) + " (throttle 78%)");
      emitSys("GIMBAL", "slew brg=" + brg + "° (track target)");
    }
  } else if (mock.phase === "ENCOUNTER") {
    if (!mock._assessed && mock.phaseT > 0.5) {
      mock._assessed = true;
      pushDecision("assess", "위험 평가 — RAC=Serious (L=B, S=Critical) priority 1");
    }
    if (!mock._responded && mock.phaseT > 0.9) {
      mock._responded = true;
      pushDecision("respond", "대응 결정 — flight_action=RTL, comms_level=SILENT");
    }
    // One-shot failsafe check when the C2 link degrades during the encounter.
    if (!mock._failsafed && mock.comms < 1.5) {
      mock._failsafed = true;
      const rssi = Math.round(-62 - ((3 - mock.comms) / 3) * 30);
      emitSys("FC", "failsafe check: C2 link degraded (rssi=" + rssi + "dBm) — GUIDED hold", "error");
    }
    if (mock.phaseT > 1.4) {
      mock.phase = "RTL"; mock.dir = -1; mock.phaseT = 0;
      pushDecision("replan", "재계획 — 복귀 경로 재계획 (reroute)");
      emitSys("FC", "mode GUIDED→RTL", "warn");
      emitSys("NAV", "reroute home dist=" + Math.round(mock.s * MAP_EXTENT_M) + "m");
    }
  } else if (mock.phase === "RTL") {
    if (mock.s <= 0.0005) {
      // 복귀 완료 → 신규 임무 재시작. 고도 프로파일 trail 도 새 사이클로 리셋.
      mock.phase = "NORMAL"; mock.dir = 1; mock.phaseT = 0;
      mock.battery = 96;
      mock._assessed = false; mock._responded = false; mock._failsafed = false;
      mock.trailProfile = [];
      pushDecision("resume", "임무 재개 — 경로 복행");
      emitSys("FC", "mode RTL→AUTO resume wp=" + wpLabel(), "warn");
    }
  }

  // 신호 목표값(phase별) — 부드럽게 approach.
  let gpsTarget = 0.95 + 0.03 * Math.sin(mock.odo * 6);
  let commsTarget = 3, racTarget = 0;
  if (mock.phase === "ENCOUNTER") { gpsTarget = 0.72; commsTarget = 1; racTarget = 3; }
  else if (mock.phase === "RTL") { gpsTarget = 0.85; commsTarget = 2; racTarget = 2; }
  mock.gps += (gpsTarget - mock.gps) * Math.min(1, dt * 3);
  mock.comms += (commsTarget - mock.comms) * Math.min(1, dt * 2);
  mock.rac += (racTarget - mock.rac) * Math.min(1, dt * 2.5);

  // 배터리: 상시 소모 + RTL 등판 시 가속. 실속도 기반 실거리 비행(leg당 수분)에 맞춰
  // 소모율을 낮춰 한 leg 안에서 바닥나지 않도록 스케일(leg당 총 소모 ~13%대).
  mock.battery -= (mock.phase === "RTL" ? 0.07 : 0.03) * dt;
  if (mock.battery < 6) mock.battery = 96;

  // 고도: 지형추종(slope-limited plan) + 회피 등판(조우/RTL 시) — target 고도를
  // 산출한 뒤 상승 +5 / 하강 -4 m/s 엔벨로프로 추종(즉시 점프 금지, VS/pitch 물리화).
  const h = heightAt(p.x, p.y);
  mock.terr = elevM(h);
  let avoid = 0;
  if (mock.phase === "ENCOUNTER" || mock.phase === "RTL") avoid = EVADE_CLIMB_M;
  const rawTarget = altPlanAt(mock.s) + avoid;
  if (mock._altTarget === null) { mock._altTarget = rawTarget; mock.alt = rawTarget; }
  mock._altTarget += (rawTarget - mock._altTarget) * Math.min(1, dt / ALT_TARGET_TAU_S);
  // Proportional approach near the target avoids bang-bang; clamped to the envelope.
  const vsCmd = Math.max(-ALT_SINK_MAX_MPS,
    Math.min(ALT_CLIMB_MAX_MPS, (mock._altTarget - mock.alt) * ALT_APPROACH_GAIN));
  mock.alt += vsCmd * dt;

  // FC 자세/각속도 유도(mock) — 운동상태의 per-tick 미분에서 계산, 저역통과로 안정화.
  //   yaw  = mock.head(경로 진행방위, 컴퍼스 deg) + ENCOUNTER 회피 요잉 진동
  //   roll = 협조선회 근사 atan(v·ω/g), ω=요잉각속도(rad/s), ±35° 클램프
  //   pitch= 상승률 근사 atan2(VS, GS), ±20° 클램프
  //   p/q/r= roll/pitch/yaw 미분(deg/s, 저역통과) — ENCOUNTER 회피 기동 시 스파이크.
  if (dt > 0) {
    const wrapPi = (a) => {
      while (a > Math.PI) a -= 2 * Math.PI;
      while (a < -Math.PI) a += 2 * Math.PI;
      return a;
    };
    const clampAbs = (v, lim) => Math.max(-lim, Math.min(lim, v));

    const prevHead = mock._prevHead === null ? mock.head : mock._prevHead;
    let omega = clampAbs(wrapPi(mock.head - prevHead) / dt, 2.5); // rad/s
    let yawRad = mock.head;
    if (mock.phase === "ENCOUNTER") {
      // 회피 요잉 기동: yaw 진동은 ω 항의 적분이라 r(요레이트)과 정합.
      omega += 1.1 * Math.sin(mock.phaseT * 6);
      yawRad += -(1.1 / 6) * Math.cos(mock.phaseT * 6);
    }
    mock._prevHead = mock.head;

    const prevAlt = mock._prevAlt === null ? mock.alt : mock._prevAlt;
    mock._prevAlt = mock.alt;
    const lp = Math.min(1, dt * 4); // 저역통과 계수(~0.25s 시정수).
    mock.vs += ((mock.alt - prevAlt) / dt - mock.vs) * lp;

    const rollT = clampAbs(Math.atan((mock.speedMps * omega) / 9.81) * 180 / Math.PI, 35);
    const pitchT = clampAbs(Math.atan2(mock.vs, mock.speedMps) * 180 / Math.PI, 20);
    const yaw = ((yawRad * 180 / Math.PI) + 360) % 360;

    const a = mock.att, g = mock.gyro;
    const prevRoll = a.roll, prevPitch = a.pitch;
    a.roll += (rollT - a.roll) * lp;
    a.pitch += (pitchT - a.pitch) * lp;
    a.yaw = yaw;
    g.p += ((a.roll - prevRoll) / dt - g.p) * lp;
    g.q += ((a.pitch - prevPitch) / dt - g.q) * lp;
    g.r += (omega * 180 / Math.PI - g.r) * lp;
  }

  // 고도 프로파일 trail: 경로를 따라 누적한 실거리(m, mock.s(정규 0.._total) × MAP_EXTENT_M)
  // 기준으로 시간순 (dist, alt) 샘플을 쌓는다. RTL 중에는 dist가 줄어들며 복귀를 그린다.
  // 루프(resume) 시 updateMock의 resume 분기에서 배열을 리셋한다.
  mock.trailProfile.push([mock.s * MAP_EXTENT_M, mock.alt]);
}

// ── 3칸 실제 렌더 ─────────────────────────────────────────────

/** 캔버스 내부 해상도(width/height 속성)를 렌더링 박스(clientWidth/clientHeight)에 맞춘다.
 * CSS 로 컨테이너 비율이 바뀌어도(예: 가로로 긴 짧은 strip) 그리기 좌표계가 그대로 따라가게 한다. */
function syncCanvasSize(cv) {
  if (!cv) return;
  const w = Math.round(cv.clientWidth);
  const h = Math.round(cv.clientHeight);
  if (w > 0 && h > 0 && (cv.width !== w || cv.height !== h)) {
    cv.width = w;
    cv.height = h;
  }
}

const PHASE_LABEL = { NORMAL: "정상 비행", ENCOUNTER: "T3 조우", RTL: "RTL 복귀" };
const PHASE_COLOR = { NORMAL: "#4CC38A", ENCOUNTER: "#F0555D", RTL: "#E5A93D" };
function droneColor() {
  return mock.phase === "NORMAL" ? "#4CC38A" : (mock.phase === "RTL" ? "#E5A93D" : "#F0555D");
}

/**
 * 지도/경로 — 레이어 순서: terrain(u16 격자) → UAV 가시영역(뷰셰드) → 적 탐지범위(footprint)
 * → 경로 → 복귀경로(RTL 시) → 마커(적 다이아몬드, 목표 크로스헤어, 시작 라벨, 드론).
 * terrain/뷰셰드/footprint는 GRIDxGRID 오프스크린 레이어를 캔버스 전체 크기로 늘려 그리므로,
 * 경로/마커도 패딩 없이 동일한 전체-캔버스 좌표계(px=nx*W, py=ny*H)를 사용해 정렬을 맞춘다.
 */
function drawMap() {
  const cv = canvases.map;
  if (!cv || !cv.getContext) return;
  if (cv.clientWidth === 0) return; // 탭 숨김 상태 — 프레임 스킵(제로 사이즈 방어).
  syncCanvasSize(cv);
  const ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height;

  const px = (nx) => nx * W;
  const py = (ny) => ny * H;

  ctx.clearRect(0, 0, W, H);

  // 1) terrain + 좌표 그리드 오버레이(1/8 간격, 미터 라벨).
  if (terrainLayer) ctx.drawImage(terrainLayer, 0, 0, W, H);
  D4DRender.drawMapGrid(ctx, W, H, MAP_EXTENT_M);

  // 2) UAV 가시영역(뷰셰드) — 지형 위, 나머지 오버레이/마커 아래.
  if (viewshedLayer) ctx.drawImage(viewshedLayer, 0, 0, W, H);

  // 3) 적 탐지범위(footprint, 지형 반영 · 원 아님) — 뷰셰드 위, 경로/마커 아래.
  if (enemyFootprintLayer) ctx.drawImage(enemyFootprintLayer, 0, 0, W, H);

  // 4) 경로(글로우 → 본선, 액티브 앰버).
  ctx.save();
  ctx.lineJoin = "round";
  const strokePath = () => {
    ctx.beginPath();
    for (let i = 0; i < PATH.length; i++) {
      const X = px(PATH[i].x), Y = py(PATH[i].y);
      if (i) ctx.lineTo(X, Y); else ctx.moveTo(X, Y);
    }
  };
  strokePath(); ctx.strokeStyle = "rgba(240,160,60,0.25)"; ctx.lineWidth = 6; ctx.stroke();
  strokePath(); ctx.strokeStyle = "rgba(240,160,60,0.9)"; ctx.lineWidth = 2.5; ctx.stroke();
  ctx.restore();

  // 5) 복귀경로(RTL 구간에서만) — 점선 앰버.
  if (mock.phase === "RTL") {
    const rp = returnPathPoints();
    ctx.save();
    ctx.beginPath();
    for (let i = 0; i < rp.length; i++) {
      const X = px(rp[i].x), Y = py(rp[i].y);
      if (i) ctx.lineTo(X, Y); else ctx.moveTo(X, Y);
    }
    ctx.setLineDash([7, 5]);
    ctx.strokeStyle = "#E5A93D"; ctx.lineWidth = 2.2;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  // 6) 마커들 — 적 다이아몬드, 목표 크로스헤어, 시작 라벨, 드론.
  const ex = px(ENEMY.x), ey = py(ENEMY.y);
  // MIL-STD-2525 hostile ground frame (render.js pure helper).
  D4DRender.drawHostileGround(ctx, ex, ey, 8);
  if (mock.phase === "ENCOUNTER") {
    // 탐지 콜아웃 — ENCOUNTER 동안만 앰버 라벨 칩(Maven detection callout).
    const callout = "T3 소화기 · 근접";
    ctx.save();
    ctx.font = "600 10px ui-monospace, Menlo, monospace";
    const tw = ctx.measureText(callout).width;
    const bx = ex + 12, by = ey - 21, bw = tw + 12, bh = 16;
    ctx.beginPath();
    ctx.roundRect(bx, by, bw, bh, 3);
    ctx.fillStyle = "rgba(13,13,15,0.85)";
    ctx.fill();
    ctx.strokeStyle = "#F0A03C"; ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = "#FFB95A"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
    ctx.fillText(callout, bx + 6, by + bh / 2);
    ctx.restore();
  } else {
    ctx.fillStyle = "#ff9a93"; ctx.font = "bold 11px system-ui"; ctx.textAlign = "left";
    ctx.fillText("T3", ex + 10, ey - 6);
  }

  const sN = PATH[0], gN = PATH[PATH.length - 1];
  const gx = px(gN.x), gy = py(gN.y);
  ctx.strokeStyle = "#4CC38A"; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.arc(gx, gy, 7, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.arc(gx, gy, 3.5, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(gx - 10, gy); ctx.lineTo(gx - 4, gy);
  ctx.moveTo(gx + 4, gy); ctx.lineTo(gx + 10, gy);
  ctx.moveTo(gx, gy - 10); ctx.lineTo(gx, gy - 4);
  ctx.moveTo(gx, gy + 4); ctx.lineTo(gx, gy + 10);
  ctx.stroke();

  ctx.beginPath(); ctx.arc(px(sN.x), py(sN.y), 5, 0, Math.PI * 2); ctx.fillStyle = "#4CC38A"; ctx.fill();
  ctx.strokeStyle = "#0D0D0F"; ctx.lineWidth = 1; ctx.stroke();
  ctx.fillStyle = "#E8E7E2"; ctx.font = "10px system-ui"; ctx.textAlign = "left";
  ctx.fillText(SCENARIO.start, px(sN.x) + 7, py(sN.y) + 3);
  ctx.textAlign = "right";
  ctx.fillText(SCENARIO.goal, gx - 7, gy + 3);
  ctx.textAlign = "left";

  const dx = px(mock.pos.x), dy = py(mock.pos.y);
  const dc = droneColor();
  const pulse = 8 + 3 * (0.5 + 0.5 * Math.sin(mock.odo * 10));
  ctx.beginPath(); ctx.arc(dx, dy, pulse, 0, Math.PI * 2);
  ctx.globalAlpha = 0.35; ctx.strokeStyle = dc; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.globalAlpha = 1;
  // MIL-STD-2525 friendly AIR frame (render.js pure helper) — affiliation
  // blue beats the phase color; the pulse ring above keeps phase feedback.
  D4DRender.drawFriendlyAir(ctx, dx, dy, 9, mock.head);
}

/** 상단 앱바 모드/phase 칩 — mock.phase를 라벨+상태색으로 표시(관측 전용). */
function updatePhaseChip() {
  if (!el.phaseChip) return;
  el.phaseChip.textContent = PHASE_LABEL[mock.phase] || mock.phase;
  el.phaseChip.style.color = PHASE_COLOR[mock.phase] || "";
}

/**
 * 고도 프로파일 정적 데이터(지형 표고 폴리곤) — 고정 경로(PATH)를 따라 1회 샘플링해 캐시한다.
 * dist 단위는 mock.trailProfile과 동일한 실거리 스케일(m, × MAP_EXTENT_M)로 맞춰 두 배열이 같은 x축을 쓴다.
 */
function buildFlightProfile() {
  const SAMPLES = 80;
  const dist = new Array(SAMPLES);
  const terrainH = new Array(SAMPLES);
  let maxH = -Infinity;
  for (let i = 0; i < SAMPLES; i++) {
    const d = (_total * i) / (SAMPLES - 1);
    const p = pointAtDist(d);
    const h = elevM(heightAt(p.x, p.y));
    dist[i] = d * MAP_EXTENT_M;
    terrainH[i] = h;
    if (h > maxH) maxH = h;
  }
  return {
    dist,
    terrainH,
    totalDist: dist[dist.length - 1],
    yMax: maxH + CLEAR_M * 1.5,
    distOffset: 0,
  };
}

const FLIGHT_PROFILE = buildFlightProfile();

/** 고도 프로파일 — D4DRender.drawProfile에 위임(지형 폴리곤 + trailProfile 고도선). */
function drawProfile() {
  const cv = canvases.profile;
  if (!cv || !cv.getContext) return;
  if (cv.clientWidth === 0) return; // 탭 숨김 상태 — 프레임 스킵(제로 사이즈 방어).
  syncCanvasSize(cv);
  const ctx = cv.getContext("2d");
  D4DRender.drawProfile(ctx, FLIGHT_PROFILE, { trailProfile: mock.trailProfile });
}

// ── 신호 패널(HTML 리스트) — 03(Sensor Abstraction) 실 계약 11채널 mock ──
// 채널/payload 필드는 docs/contracts/03-abstraction-output.md(AbstractionOutput) 골든 예시를 따른다.

const CHANNEL_DEFS = [
  { key: "position_consistency", label: "위치 정합성" },
  { key: "link_status", label: "링크 상태" },
  { key: "rf_spectrum", label: "RF 스펙트럼" },
  { key: "link_integrity", label: "링크 무결성" },
  { key: "encryption_status", label: "암호화 상태" },
  { key: "mission_phase", label: "임무 단계" },
  { key: "terrain_class", label: "지형 분류" },
  { key: "proximity_object", label: "근접 물체" },
  { key: "acoustic_event", label: "음향 이벤트" },
  { key: "obstacle_proximity", label: "장애물 근접" },
  { key: "operational_margin", label: "운용 여유도" },
];

/** quality(0..1) → state 라벨 공통 임계값. */
function stateFromQuality(q) {
  return q > 0.7 ? "normal" : q > 0.4 ? "degraded" : "anomaly";
}

/** 전 사이클 quality 대비 delta = quality(t) - quality(t-1)(첫 사이클은 0.0). */
function chanDelta(key, q) {
  const prev = mock.chanQ[key];
  const d = prev === undefined ? 0 : q - prev;
  mock.chanQ[key] = q;
  return d;
}

/** mock 시나리오 상태로부터 11채널(계약 payload 필드 포함) 스냅샷 계산(표시 전용, 재판단 없음). */
function computeChannels() {
  const commsN = mock.comms;
  const encounter = mock.phase === "ENCOUNTER";
  const rtl = mock.phase === "RTL";
  const jitter = Math.sin(mock.odo * 6);

  // ── position_consistency ── gps_imu_residual_m 등 잔차 계열(공유 산식).
  const gpsImuResidual = gpsResidualM();
  const baroResidual = 0.3 + Math.abs(jitter) * 0.15;
  const airspeedResidual = 0.4 + Math.abs(jitter) * 0.1;
  const hdop = gpsHdop();
  const vdop = hdop * 1.3;
  const satelliteCount = gpsSats();
  const cn0 = 42.5 - (1 - mock.gps) * 12;
  const pcQuality = mock.gps;

  // ── link_status / link_integrity / rf_spectrum ── comms 레벨 기반(공유 산식).
  const jam = commsJam();
  const rssi = linkRssi(jam);
  const packetLoss = linkLoss(jam);
  const latency = linkLatency(jam);
  const lsQuality = commsN / 3;
  const checksumFailRate = Math.min(0.5, jam * 0.4);
  const seqGapCount = Math.round(jam * 20);

  // ── mission_phase ── RTL 진입 시 declared=RTL.
  const declared = rtl ? "RTL" : "TRANSIT";
  const behavioral = rtl ? "return_path" : encounter ? "evasive_loiter" : "cruise";
  const phaseMatch = !encounter;
  const phaseConf = 0.9 - (encounter ? 0.15 : 0);

  // ── proximity_object / acoustic_event ── T3 조우 시 anomaly.
  const bearingToEnemy = ((Math.atan2(ENEMY.y - mock.pos.y, ENEMY.x - mock.pos.x) * 180) / Math.PI + 360) % 360;
  // 실제 UAV 속도(mock.speedMps, phase별로 갱신됨) 기준 접근속도.
  const closureRate = mock.speedMps + jitter * 0.3;

  // ── operational_margin ── 배터리는 루프 내내 서서히 소모(mock.battery).
  const batteryState = mock.battery > 40 ? "sufficient" : mock.battery > 15 ? "limited" : "critical";
  const weatherState = "limited"; // 시나리오 고정 기상 열화(골든 예시와 동일).
  const overall = batteryState === "sufficient" ? "limited" : batteryState;
  const worstFactor = batteryState === "sufficient" ? "weather" : "battery";
  const motorTempC = escTempC(jitter);
  const vibration = frameVib(jitter);

  const raw = {
    position_consistency: {
      quality: pcQuality,
      state: gpsImuResidual < 2 ? "normal" : gpsImuResidual < 5 ? "degraded" : "anomaly",
      summary: "잔차 " + gpsImuResidual.toFixed(1) + "m(baro " + baroResidual.toFixed(2) +
        "/ias " + airspeedResidual.toFixed(2) + ")·위성 " + satelliteCount + "·HDOP " + hdop.toFixed(1) +
        "/VDOP " + vdop.toFixed(1) + "·CN0 " + cn0.toFixed(1) + "dB",
    },
    link_status: {
      quality: lsQuality,
      state: commsN >= 2.5 ? "normal" : commsN >= 1.5 ? "degraded" : "anomaly",
      summary: rssi + "dBm·loss " + Math.round(packetLoss * 100) + "%·" + latency + "ms",
    },
    rf_spectrum: {
      quality: 1 - jam,
      state: jam < 0.3 ? "normal" : jam < 0.6 ? "degraded" : "anomaly",
      summary: "광대역이상 " + (jam >= 0.6 ? "O" : "X") +
        (jam >= 0.6 ? "·방위 " + bearingToEnemy.toFixed(0) + "°" : ""),
    },
    link_integrity: {
      quality: 1 - checksumFailRate,
      state: checksumFailRate < 0.05 ? "normal" : checksumFailRate < 0.2 ? "degraded" : "anomaly",
      summary: "체크섬실패 " + (checksumFailRate * 100).toFixed(1) + "%·시퀀스갭 " + seqGapCount,
    },
    encryption_status: {
      quality: 0.99,
      state: "normal",
      summary: "AES256·정상",
    },
    mission_phase: {
      quality: phaseConf,
      state: phaseMatch ? "normal" : "degraded",
      summary: declared + "/" + behavioral + (phaseMatch ? " 일치" : " 불일치"),
    },
    terrain_class: {
      // stub(고정값) — 03 계층 AI 보조채널은 MVP 에서 고정값 반환(CLAUDE.md 정책).
      quality: 0.55,
      state: "degraded",
      summary: "open_field·camera_verified·미스매치",
    },
    proximity_object: {
      // 시나리오 핵심 반응 채널 — T3 조우 시 anomaly 로 전환.
      quality: mock.enemyActive ? 0.55 : 0.95,
      state: mock.enemyActive ? "anomaly" : "normal",
      summary: mock.enemyActive
        ? "person(무기형상) 방위" + bearingToEnemy.toFixed(0) + "° 접근중 " + closureRate.toFixed(1) + "m/s"
        : "감지없음",
    },
    acoustic_event: {
      quality: encounter ? 0.92 : 0.91,
      state: encounter ? "anomaly" : "normal",
      summary: encounter
        ? "gunshot " + Math.round(118 + jitter * 2) + "dB 방위" + bearingToEnemy.toFixed(0) + "°"
        : "ambient " + Math.round(45 + jitter * 3) + "dB",
    },
    obstacle_proximity: {
      quality: 0.85 + jitter * 0.02,
      state: "normal",
      summary: "감지없음",
    },
    operational_margin: {
      quality: 1.0,
      state: overall === "limited" ? "degraded" : "anomaly",
      summary: "배터리 " + Math.round(mock.battery) + "%·전반 " + overall + "(" +
        (worstFactor === "weather" ? "날씨" : "배터리") + ":" + weatherState + ")·모터 " +
        motorTempC.toFixed(1) + "°C·진동 " + vibration.toFixed(2) + "g",
    },
  };

  const out = {};
  CHANNEL_DEFS.forEach((def) => {
    const c = raw[def.key];
    out[def.key] = { quality: c.quality, state: c.state, delta: chanDelta(def.key, c.quality), summary: c.summary };
  });
  return out;
}

let _signalRowsBuilt = false;
const _sigRowRefs = {};

/** 신호 패널 행(채널당 1행)을 최초 1회 생성 — 이후엔 제자리 갱신만(append-scroll 아님). */
function ensureSignalRows() {
  if (_signalRowsBuilt || !el.signalsList) return;
  CHANNEL_DEFS.forEach((def) => {
    const row = document.createElement("div");
    row.className = "sig-row";

    const name = document.createElement("span");
    name.className = "sig-name";
    name.textContent = def.label;

    const dot = document.createElement("span");
    dot.className = "sig-dot";

    const bar = document.createElement("span");
    bar.className = "sig-bar";
    const fill = document.createElement("span");
    fill.className = "sig-bar-fill";
    bar.appendChild(fill);

    const qnum = document.createElement("span");
    qnum.className = "sig-qnum";

    const delta = document.createElement("span");
    delta.className = "sig-delta";

    const payload = document.createElement("span");
    payload.className = "sig-payload";

    row.append(name, dot, bar, qnum, delta, payload);
    el.signalsList.appendChild(row);
    _sigRowRefs[def.key] = { dot, fill, qnum, delta, payload };
  });
  _signalRowsBuilt = true;
}

/** 매 tick 채널 스냅샷으로 기존 행을 제자리 갱신. */
function renderSignals() {
  ensureSignalRows();
  if (!el.signalsList) return;
  const channels = computeChannels();
  CHANNEL_DEFS.forEach((def) => {
    const refs = _sigRowRefs[def.key];
    const c = channels[def.key];
    if (!refs || !c) return;
    refs.dot.className = "sig-dot dot-" + c.state;
    refs.fill.className = "sig-bar-fill fill-" + c.state;
    refs.fill.style.width = Math.max(2, Math.round(c.quality * 100)) + "%";
    refs.qnum.textContent = "q=" + c.quality.toFixed(2);
    const deltaText = "Δ" + (c.delta >= 0 ? "+" : "") + c.delta.toFixed(2);
    refs.delta.textContent = deltaText;
    refs.delta.className = "sig-delta" + (c.delta < -0.3 ? " delta-alert" : "");
    refs.payload.textContent = c.summary;
    refs.payload.title = c.summary;
  });
}

// ── UAV 기체 신호 패널(하단 행 리스트) — FC(ArduPilot/PX4급) 텔레메트리 mock ──
// 03 의미 채널과 구분되는 기체 자체 상태. computeChannels/시스템 로그와 동일한
// mock 원천값·공유 산식(mock.battery/gps/comms/speedMps/alt/att/gyro/vs)에서
// 파생해 수치 모순이 없게 유지한다.

const DEVICE_ROW_DEFS = [
  { key: "att", label: "자세 ATT" },
  { key: "gyro", label: "각속도 GYRO" },
  { key: "battery", label: "배터리 BATT" },
  { key: "gpsins", label: "GPS/INS" },
  { key: "baro", label: "기압고도 BARO" },
  { key: "speed", label: "속도 SPD" },
  { key: "motor", label: "모터 ESC" },
  { key: "c2link", label: "C2 링크 LINK" },
  { key: "nav", label: "컴퍼스/홈 NAV" },
];

/** mock 원천값 → FC 텔레메트리 9행 스냅샷(표시 전용, 재판단 없음). */
function computeDeviceStats() {
  const jitter = Math.sin(mock.odo * 6);
  const att = mock.att, gyro = mock.gyro;

  const voltage = battVoltage();
  const batteryState = mock.battery >= 40 ? "normal" : mock.battery >= 20 ? "degraded" : "anomaly";

  const gpsImuResidual = gpsResidualM();
  const gpsState = gpsImuResidual < 2 ? "normal" : gpsImuResidual < 5 ? "degraded" : "anomaly";

  const rpmAvg = escRpm(jitter);
  const motorTempC = escTempC(jitter);
  const vibration = frameVib(jitter);

  const jam = commsJam();
  const linkState = mock.comms >= 2.5 ? "normal" : mock.comms >= 1.5 ? "degraded" : "anomaly";

  // 대기속도 = 대지속도 ± 바람(wind) 오프셋 mock.
  const airspeed = Math.max(0, mock.speedMps - 0.6 + jitter * 0.3);
  // 홈(출발지) 직선거리(m).
  const homeDistM = Math.round(
    Math.hypot(mock.pos.x - PATH[0].x, mock.pos.y - PATH[0].y) * MAP_EXTENT_M);
  const maxRate = Math.max(Math.abs(gyro.p), Math.abs(gyro.q), Math.abs(gyro.r));

  return {
    att: {
      value: "R " + fmtSigned(att.roll, 1) + "° P " + fmtSigned(att.pitch, 1) +
        "° Y " + fmtHeading(att.yaw) + "°",
      state: Math.abs(att.roll) < 25 ? "normal" : "degraded",
    },
    gyro: {
      value: "p " + fmtSigned(gyro.p, 1) + " q " + fmtSigned(gyro.q, 1) +
        " r " + fmtSigned(gyro.r, 1) + "°/s",
      state: maxRate < 40 ? "normal" : "degraded",
    },
    battery: {
      value: Math.round(mock.battery) + "% · " + voltage.toFixed(1) + "V · " +
        battCurrentA().toFixed(1) + "A",
      state: batteryState,
    },
    gpsins: {
      value: "3D " + (gpsImuResidual < 2 ? "FUSED" : "DEGRADED") + " · " +
        gpsSats() + "위성 · HDOP " + gpsHdop().toFixed(1),
      state: gpsState,
    },
    baro: {
      value: "ALT " + Math.round(mock.alt) + "m · VS " + fmtSigned(mock.vs, 1) + "m/s",
      state: "normal",
    },
    speed: {
      value: "GS " + mock.speedMps.toFixed(1) + "m/s · AS " + airspeed.toFixed(1) + "m/s",
      state: "normal",
    },
    motor: {
      value: rpmAvg + "rpm · " + motorTempC.toFixed(0) + "°C · 진동 " + vibration.toFixed(2) + "g",
      state: motorTempC >= 80 ? "anomaly"
        : (motorTempC >= 60 || vibration >= 0.2) ? "degraded" : "normal",
    },
    c2link: {
      value: linkRssi(jam) + "dBm · " + linkLatency(jam) + "ms · loss " +
        Math.round(linkLoss(jam) * 100) + "%",
      state: linkState,
    },
    nav: {
      value: "HDG " + fmtHeading(att.yaw) + "° · HOME " + homeDistM + "m",
      state: "normal",
    },
  };
}

let _deviceRowsBuilt = false;
const _devRowRefs = {};

/** 기체 신호 행(9개, [dot] LABEL value)을 최초 1회 생성 — 이후엔 제자리 갱신만. */
function ensureDeviceRows() {
  if (_deviceRowsBuilt || !el.deviceStrip) return;
  DEVICE_ROW_DEFS.forEach((def) => {
    const row = document.createElement("div");
    row.className = "dev-row";

    const dot = document.createElement("span");
    dot.className = "sig-dot";

    const label = document.createElement("span");
    label.className = "dev-label";
    label.textContent = def.label;

    const value = document.createElement("span");
    value.className = "dev-value";

    row.append(dot, label, value);
    el.deviceStrip.appendChild(row);
    _devRowRefs[def.key] = { dot, value };
  });
  _deviceRowsBuilt = true;
}

/** 매 tick 기체 텔레메트리 스냅샷으로 기존 행을 제자리 갱신. */
function renderDeviceStats() {
  ensureDeviceRows();
  if (!el.deviceStrip) return;
  const stats = computeDeviceStats();
  DEVICE_ROW_DEFS.forEach((def) => {
    const refs = _devRowRefs[def.key];
    const s = stats[def.key];
    if (!refs || !s) return;
    refs.dot.className = "sig-dot dot-" + s.state;
    refs.value.textContent = s.value;
    refs.value.title = s.value;
  });
}

// ── 애니메이션 루프 (requestAnimationFrame) ────────────────────

let _lastTs = 0;
function frame(ts) {
  const dt = _lastTs ? Math.min((ts - _lastTs) / 1000, 0.05) : 0.016;
  _lastTs = ts;
  updateMock(dt);
  updateViewshedLayer(ts);
  drawMap();
  updatePhaseChip();
  drawProfile();
  renderSignals();
  renderDeviceStats();
  requestAnimationFrame(frame);
}

/** mock 시뮬 구동 시작. rAF 없으면 1회 렌더로 폴백. */
function startMockSim() {
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(frame);
  } else {
    updateMock(0.016);
    updateViewshedLayer(performance.now());
    drawMap();
    updatePhaseChip();
    drawProfile();
    renderSignals();
    renderDeviceStats();
  }
}

// ── 진입점 ────────────────────────────────────────────────────

/** 서버 /config 에서 로그수집기 WS URL 기본값을 best-effort 로 가져온다. */
function loadConfig() {
  if (typeof fetch !== "function") return Promise.resolve();
  return fetch("/config")
    .then((r) => (r.ok ? r.json() : null))
    .then((cfg) => {
      if (cfg && cfg.log_ws_url) state.logWsUrl = cfg.log_ws_url;
    })
    .catch(() => { /* 설정 조회 실패 시 기본값 유지 */ });
}

/** 시스템 로그 회전 tick — 간격이 timeScale로 나뉘어 배속 시 로그 밀도도 함께 스케일된다. */
function scheduleSysLog() {
  setTimeout(() => {
    emitPeriodicSysLog();
    scheduleSysLog();
  }, SYS_LOG_INTERVAL_MS / mock.timeScale);
}

/** 탭 전환(관측 / 관측소) — 뷰 hidden 토글 + 탭 버튼 active 갱신.
 * 전역 함수 — gcs.js 가 파이프라인 실행 후 관측 탭으로 복귀할 때도 호출한다.
 * rAF 루프는 계속 돌고, 숨김 캔버스는 drawMap/drawProfile 의 clientWidth 가드가 스킵한다. */
function switchTab(view) {
  document.querySelectorAll("#tab-nav .tab-btn").forEach((btn) => {
    const active = btn.dataset.view === view;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  const obs = document.getElementById("view-observation");
  const gcsView = document.getElementById("view-gcs");
  if (obs) obs.hidden = view !== "observation";
  if (gcsView) gcsView.hidden = view !== "gcs";
}

/** 탭 버튼 클릭 바인딩. */
function initTabs() {
  const nav = document.getElementById("tab-nav");
  if (!nav) return;
  nav.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab-btn");
    if (btn && btn.dataset.view) switchTab(btn.dataset.view);
  });
}

/** 배속 세그먼트 컨트롤(×1/×2/×4/×8) — 클릭 시 mock.timeScale 갱신 + active 토글. */
function initSpeedControl() {
  const ctl = document.getElementById("speed-control");
  if (!ctl) return;
  ctl.addEventListener("click", (e) => {
    const btn = e.target.closest(".speed-btn");
    if (!btn) return;
    mock.timeScale = Number(btn.dataset.scale) || 1;
    ctl.querySelectorAll(".speed-btn").forEach((b) => {
      b.classList.toggle("active", b === btn);
    });
  });
}

function init() {
  startMockSim();
  initTabs();
  initSpeedControl();

  // UAV system log mock generator (panel C) — continuous, scenario-linked.
  scheduleSysLog();

  // /config 로 기본 URL 확정 후 자동 연결(수집기 미기동이면 backoff 재연결).
  loadConfig().then(connect);
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}
