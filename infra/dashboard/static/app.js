"use strict";

// D4D 대시보드 — 실시간 로그 스트림 클라이언트 + Canvas mock 시나리오 렌더.
// 대시보드는 판단하지 않는다 — 로그수집기의 로그를 수신해 표시만 한다.
//
// 로그수집기 WS /logs 메시지 포맷:
//   { correlation_id, layer, log, level: "info"|"warn"|"error", ts: <epoch ms> }
// 접속 시 최근 backlog 가 먼저 도착한다.

// ── 설정 ──────────────────────────────────────────────────────

const DEFAULT_LOG_WS_URL = "ws://localhost:8500/logs";
const MAX_LOG_ITEMS = 500; // 오래된 항목은 잘라 메모리 방어.

// correlation_id 그룹 색 팔레트(들여쓰기 대신 색으로 그룹핑).
const CID_COLORS = [
  "#58a6ff", "#3fb950", "#d29922", "#f778ba", "#a371f7",
  "#39c5cf", "#e3b341", "#ff7b72", "#7ee787", "#79c0ff",
];

// level → CSS 클래스.
const LEVEL_CLASS = { info: "lvl-info", warn: "lvl-warn", error: "lvl-error" };

// ── 상태 ──────────────────────────────────────────────────────

const state = {
  ws: null,
  connected: false,
  reconnectDelay: 1000, // backoff (ms), 최대 15s.
  manualClose: false,
  cidColorMap: new Map(), // correlation_id → 색
  filters: { level: "", layer: "", cid: "" },
  mockTimer: null,
};

// Canvas 2D 핸들 (지도/고도/신호 mock 렌더 대상).
const canvases = {
  map: document.getElementById("map-canvas"),
  profile: document.getElementById("profile-canvas"),
  signals: document.getElementById("signals-canvas"),
};

// ── 순수 로직 (브라우저 없이도 검증 가능) ──────────────────────

/** correlation_id 에 안정적으로 색을 배정한다. */
function colorForCid(cid) {
  if (!cid) return "#484f58";
  if (state.cidColorMap.has(cid)) return state.cidColorMap.get(cid);
  let hash = 0;
  for (let i = 0; i < cid.length; i++) {
    hash = (hash * 31 + cid.charCodeAt(i)) >>> 0;
  }
  const color = CID_COLORS[hash % CID_COLORS.length];
  state.cidColorMap.set(cid, color);
  return color;
}

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

/** correlation_id 축약(앞 8자). */
function shortCid(cid) {
  if (!cid) return "--------";
  return String(cid).slice(0, 8);
}

/**
 * 현재 필터 기준으로 로그를 통과시킬지 판단.
 * @param {{correlation_id?:string, layer?:string, level?:string}} entry
 * @param {{level:string, layer:string, cid:string}} filters
 */
function passesFilter(entry, filters) {
  if (filters.level && entry.level !== filters.level) return false;
  if (filters.layer) {
    const l = String(entry.layer || "").toLowerCase();
    if (!l.includes(filters.layer.toLowerCase())) return false;
  }
  if (filters.cid) {
    const c = String(entry.correlation_id || "").toLowerCase();
    if (!c.includes(filters.cid.toLowerCase())) return false;
  }
  return true;
}

/** 수신 payload 를 정규화(누락 필드 방어). */
function normalizeEntry(raw) {
  return {
    correlation_id: raw && raw.correlation_id != null ? String(raw.correlation_id) : "",
    layer: raw && raw.layer != null ? String(raw.layer) : "unknown",
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
  wsUrl: document.getElementById("log-ws-url"),
  connectBtn: document.getElementById("log-connect-btn"),
  filterLevel: document.getElementById("filter-level"),
  filterLayer: document.getElementById("filter-layer"),
  filterCid: document.getElementById("filter-cid"),
  mockBtn: document.getElementById("mock-inject-btn"),
  mockAuto: document.getElementById("mock-auto"),
  clearBtn: document.getElementById("log-clear-btn"),
};

function setStatus(text, ok) {
  if (!el.status) return;
  el.status.textContent = text;
  el.status.classList.toggle("status-on", !!ok);
  el.status.classList.toggle("status-off", !ok);
}

/** 리스트가 바닥 근처인지(자동 스크롤 여부 판단). */
function isNearBottom(node) {
  return node.scrollHeight - node.scrollTop - node.clientHeight < 40;
}

/**
 * 로그 한 줄을 리스트에 append (최신이 아래로, 자동스크롤).
 * 형식: [ts] [layer] correlation_id — log, level별 색 + correlation_id 색 그룹.
 */
function appendLog(raw) {
  const entry = normalizeEntry(raw);
  const li = document.createElement("li");
  li.className = "log-item " + (LEVEL_CLASS[entry.level] || "lvl-info");
  li.style.borderLeftColor = colorForCid(entry.correlation_id);
  // 필터 재적용을 위해 원본 필드 보관.
  li.dataset.level = entry.level;
  li.dataset.layer = entry.layer;
  li.dataset.cid = entry.correlation_id;
  li.hidden = !passesFilter(entry, state.filters);

  const ts = document.createElement("span");
  ts.className = "log-ts";
  ts.textContent = "[" + formatTs(entry.ts) + "]";

  const layer = document.createElement("span");
  layer.className = "log-layer";
  layer.textContent = "[" + entry.layer + "]";

  const cid = document.createElement("span");
  cid.className = "log-cid";
  cid.style.color = colorForCid(entry.correlation_id);
  cid.textContent = shortCid(entry.correlation_id);
  cid.title = entry.correlation_id;

  const msg = document.createElement("span");
  msg.className = "log-msg";
  msg.textContent = " — " + entry.log;

  li.append(ts, layer, cid, msg);

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

/** 필터 변경 시 기존 항목 표시/숨김 재적용. */
function applyFilters() {
  state.filters = {
    level: el.filterLevel ? el.filterLevel.value : "",
    layer: el.filterLayer ? el.filterLayer.value.trim() : "",
    cid: el.filterCid ? el.filterCid.value.trim() : "",
  };
  const items = el.list.children;
  for (let i = 0; i < items.length; i++) {
    const li = items[i];
    li.hidden = !passesFilter(
      { level: li.dataset.level, layer: li.dataset.layer, correlation_id: li.dataset.cid },
      state.filters,
    );
  }
}

// ── WS 클라이언트 ─────────────────────────────────────────────

function currentUrl() {
  const v = el.wsUrl && el.wsUrl.value.trim();
  return v || DEFAULT_LOG_WS_URL;
}

/** 로그수집기 WS /logs 에 연결. backlog → 실시간 순으로 수신. */
function connect() {
  state.manualClose = false;
  const url = currentUrl();
  let ws;
  try {
    ws = new WebSocket(url);
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
    if (el.connectBtn) el.connectBtn.textContent = "끊기";
  };
  ws.onclose = () => {
    state.connected = false;
    setStatus("disconnected", false);
    if (el.connectBtn) el.connectBtn.textContent = "연결";
    if (!state.manualClose) scheduleReconnect();
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

function disconnect() {
  state.manualClose = true;
  if (state.ws) {
    try { state.ws.close(); } catch (e) { /* noop */ }
  }
}

function scheduleReconnect() {
  const delay = state.reconnectDelay;
  state.reconnectDelay = Math.min(delay * 2, 15000);
  setStatus("reconnect " + Math.round(delay / 1000) + "s…", false);
  setTimeout(() => {
    if (!state.manualClose && !state.connected) connect();
  }, delay);
}

function toggleConnect() {
  if (state.connected || (state.ws && state.ws.readyState === WebSocket.CONNECTING)) {
    disconnect();
  } else {
    connect();
  }
}

// ── mock 로그(개발용) ─────────────────────────────────────────

const MOCK_LAYERS = ["sensor", "abstraction", "risk_assessment", "response", "state_store"];
const MOCK_LEVELS = ["info", "info", "info", "warn", "error"];
const MOCK_MSGS = [
  "tick ingested",
  "signal envelope decoded",
  "risk score computed",
  "corridor nominal",
  "gps quality degraded",
  "comms link jitter high",
  "threat candidate flagged",
  "replan evaluated",
];

let mockCidPool = [];
let mockSeq = 0;

/** 개발용 mock 로그 1건을 로컬 append(수집기 없이 UI 확인). */
function injectMock() {
  mockSeq++;
  // 3건마다 새 correlation_id 로 그룹 다양성 확보.
  if (mockCidPool.length === 0 || mockSeq % 3 === 0) {
    const id = "mock-" + mockSeq.toString(16).padStart(4, "0") +
      "-" + ((mockSeq * 2654435761) >>> 0).toString(16);
    mockCidPool.push(id);
    if (mockCidPool.length > 4) mockCidPool.shift();
  }
  const pick = (arr) => arr[mockSeq % arr.length];
  appendLog({
    correlation_id: pick(mockCidPool),
    layer: pick(MOCK_LAYERS),
    log: pick(MOCK_MSGS) + " #" + mockSeq,
    level: pick(MOCK_LEVELS),
    ts: Date.now(),
  });
}

function toggleMockAuto() {
  if (el.mockAuto && el.mockAuto.checked) {
    if (!state.mockTimer) state.mockTimer = setInterval(injectMock, 700);
  } else if (state.mockTimer) {
    clearInterval(state.mockTimer);
    state.mockTimer = null;
  }
}

// ── mock 시나리오 시뮬레이터 (uav tick WS 연동 시 교체) ─────────
// 로그 패널 mock 과 별개로, 지도/고도/신호 3칸을 구동하는 내부 mock.
// 시나리오: 양재역 → 고터역 정상 비행 → T3 조우 → RTL(복귀) 루프.
// uav tick WS 연동 시 아래 mock 상태를 실제 platform_state/signal 로 교체한다.

const SCENARIO = { start: "양재역", goal: "고터역", threat: "T3" };

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

// 표고 → 색(저지대 녹색 → 고지대 갈색 → 설선).
const RAMP = [
  [0.00, [10, 40, 24]],
  [0.30, [26, 74, 40]],
  [0.50, [58, 92, 44]],
  [0.66, [104, 96, 52]],
  [0.80, [140, 116, 66]],
  [0.92, [190, 176, 130]],
  [1.00, [232, 238, 240]],
];
function terrainColor(h) {
  let a = RAMP[0], b = RAMP[RAMP.length - 1];
  for (let i = 0; i < RAMP.length - 1; i++) {
    if (h >= RAMP[i][0] && h <= RAMP[i + 1][0]) { a = RAMP[i]; b = RAMP[i + 1]; break; }
  }
  const t = (h - a[0]) / ((b[0] - a[0]) || 1);
  const c0 = Math.round(a[1][0] + (b[1][0] - a[1][0]) * t);
  const c1 = Math.round(a[1][1] + (b[1][1] - a[1][1]) * t);
  const c2 = Math.round(a[1][2] + (b[1][2] - a[1][2]) * t);
  return "rgb(" + c0 + "," + c1 + "," + c2 + ")";
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

// mock 상태(NORMAL → ENCOUNTER → RTL 루프).
const mock = {
  s: 0, dir: 1, phase: "NORMAL", phaseT: 0,
  battery: 97, gps: 0.98, comms: 3, rac: 0,
  odo: 0, history: [], pos: { x: PATH[0].x, y: PATH[0].y }, head: 0,
  enemyActive: false, alt: 0, terr: 0,
};

const SPEED = 0.11;   // 정규거리/초
const CLEAR_M = 120;  // 지형추종 여유고도(m)
function elevM(h) { return 190 + h * 650; }

/** 배터리/품질 대비 색. */
function lvlColor(f) { return f > 0.5 ? "#3fb950" : (f > 0.2 ? "#d29922" : "#f85149"); }

/** mock 시나리오 상태 전이 + 신호/고도 갱신. */
function updateMock(dt) {
  mock.phaseT += dt;
  mock.s += mock.dir * SPEED * dt;
  if (mock.s < 0) mock.s = 0;
  if (mock.s > _total) mock.s = _total;

  const p = pointAtDist(mock.s);
  mock.pos = p;
  mock.head = p.head;
  mock.odo += SPEED * dt;

  const dEnemy = Math.hypot(p.x - ENEMY.x, p.y - ENEMY.y);
  mock.enemyActive = dEnemy < ENEMY.r * 1.6;

  // 상태기계.
  if (mock.phase === "NORMAL") {
    if (mock.dir > 0 && dEnemy < ENEMY.r) { mock.phase = "ENCOUNTER"; mock.phaseT = 0; }
  } else if (mock.phase === "ENCOUNTER") {
    if (mock.phaseT > 1.4) { mock.phase = "RTL"; mock.dir = -1; mock.phaseT = 0; }
  } else if (mock.phase === "RTL") {
    if (mock.s <= 0.0005) {
      // 복귀 완료 → 신규 임무 재시작.
      mock.phase = "NORMAL"; mock.dir = 1; mock.phaseT = 0;
      mock.battery = 96;
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

  // 배터리: 상시 소모 + RTL 등판 시 가속.
  mock.battery -= (mock.phase === "RTL" ? 0.9 : 0.45) * dt;
  if (mock.battery < 6) mock.battery = 96;

  // 고도: 지형추종 + 회피 등판(조우/RTL 시).
  const h = heightAt(p.x, p.y);
  mock.terr = elevM(h);
  let avoid = 0;
  if (mock.phase === "ENCOUNTER") avoid = 60 + 120 * Math.min(1, mock.phaseT / 1.4);
  else if (mock.phase === "RTL") avoid = 170;
  mock.alt = mock.terr + CLEAR_M + avoid;

  // 고도 프로파일 히스토리(롤링).
  mock.history.push({ terr: mock.terr, alt: mock.alt });
  if (mock.history.length > 150) mock.history.shift();
}

// ── 3칸 실제 렌더 ─────────────────────────────────────────────

let _terrainCache = null;

/** 표고장 + 격자 + 경로(정적)를 offscreen 캔버스에 캐시. */
function terrainCacheFor(cv) {
  if (_terrainCache && _terrainCache.w === cv.width && _terrainCache.h === cv.height) {
    return _terrainCache.canvas;
  }
  const W = cv.width, H = cv.height, pad = 8;
  const off = document.createElement("canvas");
  off.width = W; off.height = H;
  const c = off.getContext("2d");
  c.fillStyle = "#010409";
  c.fillRect(0, 0, W, H);

  // 표고장(셀 단위 heatmap).
  const step = 6;
  for (let yy = pad; yy < H - pad; yy += step) {
    for (let xx = pad; xx < W - pad; xx += step) {
      const nx = (xx - pad) / (W - 2 * pad), ny = (yy - pad) / (H - 2 * pad);
      c.fillStyle = terrainColor(heightAt(nx, ny));
      c.fillRect(xx, yy, step, step);
    }
  }

  // 격자.
  c.strokeStyle = "rgba(88,166,255,0.07)";
  c.lineWidth = 1;
  for (let gx = pad; gx <= W - pad; gx += 48) { c.beginPath(); c.moveTo(gx, pad); c.lineTo(gx, H - pad); c.stroke(); }
  for (let gy = pad; gy <= H - pad; gy += 48) { c.beginPath(); c.moveTo(pad, gy); c.lineTo(W - pad, gy); c.stroke(); }

  const px = (nx) => pad + nx * (W - 2 * pad);
  const py = (ny) => pad + ny * (H - 2 * pad);

  // 경로 폴리라인(글로우 → 본선).
  const strokePath = () => {
    c.beginPath();
    for (let i = 0; i < PATH.length; i++) {
      const X = px(PATH[i].x), Y = py(PATH[i].y);
      if (i) c.lineTo(X, Y); else c.moveTo(X, Y);
    }
  };
  c.lineJoin = "round";
  strokePath(); c.strokeStyle = "rgba(88,166,255,0.25)"; c.lineWidth = 6; c.stroke();
  strokePath(); c.strokeStyle = "rgba(88,166,255,0.9)"; c.lineWidth = 2.5; c.stroke();

  // 웨이포인트.
  for (let i = 0; i < PATH.length; i++) {
    c.beginPath(); c.arc(px(PATH[i].x), py(PATH[i].y), 2.5, 0, Math.PI * 2);
    c.fillStyle = "#79c0ff"; c.fill();
  }
  // 시작/목표 마커.
  const sN = PATH[0], gN = PATH[PATH.length - 1];
  c.beginPath(); c.arc(px(sN.x), py(sN.y), 5, 0, Math.PI * 2); c.fillStyle = "#3fb950"; c.fill();
  c.strokeStyle = "#0d1117"; c.lineWidth = 1; c.stroke();
  c.beginPath(); c.arc(px(gN.x), py(gN.y), 5, 0, Math.PI * 2); c.fillStyle = "#58a6ff"; c.fill();
  c.strokeStyle = "#0d1117"; c.lineWidth = 1; c.stroke();

  _terrainCache = { w: W, h: H, canvas: off };
  return off;
}

function drawDiamond(ctx, x, y, s, color) {
  ctx.beginPath();
  ctx.moveTo(x, y - s); ctx.lineTo(x + s, y); ctx.lineTo(x, y + s); ctx.lineTo(x - s, y);
  ctx.closePath();
  ctx.fillStyle = color; ctx.fill();
  ctx.strokeStyle = "#0d1117"; ctx.lineWidth = 1; ctx.stroke();
}

function drawDrone(ctx, x, y, head, color) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(head);
  ctx.beginPath();
  ctx.moveTo(9, 0); ctx.lineTo(-6, 5); ctx.lineTo(-3, 0); ctx.lineTo(-6, -5);
  ctx.closePath();
  ctx.fillStyle = color; ctx.fill();
  ctx.strokeStyle = "#0d1117"; ctx.lineWidth = 1; ctx.stroke();
  ctx.restore();
}

const PHASE_LABEL = { NORMAL: "정상 비행", ENCOUNTER: "T3 조우", RTL: "RTL 복귀" };
const PHASE_COLOR = { NORMAL: "#3fb950", ENCOUNTER: "#f85149", RTL: "#d29922" };
function droneColor() {
  return mock.phase === "NORMAL" ? "#3fb950" : (mock.phase === "RTL" ? "#d29922" : "#f85149");
}

/** 지도/경로 — 지형 + 경로 + 드론 + 적(T3) + 시나리오 라벨. */
function drawMap() {
  const cv = canvases.map;
  if (!cv || !cv.getContext) return;
  const ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height, pad = 8;
  ctx.drawImage(terrainCacheFor(cv), 0, 0);

  const px = (nx) => pad + nx * (W - 2 * pad);
  const py = (ny) => pad + ny * (H - 2 * pad);

  // 적 T3 + 탐지 링.
  const ex = px(ENEMY.x), ey = py(ENEMY.y);
  const rr = ENEMY.r * (W - 2 * pad);
  ctx.beginPath(); ctx.arc(ex, ey, rr, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(248,81,73,0.08)"; ctx.fill();
  ctx.setLineDash([5, 4]);
  ctx.strokeStyle = mock.enemyActive ? "rgba(248,81,73,0.9)" : "rgba(248,81,73,0.35)";
  ctx.lineWidth = mock.enemyActive ? 2 : 1;
  ctx.stroke();
  ctx.setLineDash([]);
  drawDiamond(ctx, ex, ey, 7, "#f85149");
  ctx.fillStyle = "#ff9a93"; ctx.font = "bold 11px system-ui"; ctx.textAlign = "left";
  ctx.fillText("T3", ex + 10, ey - 6);

  // 드론 + 펄스 링.
  const dx = px(mock.pos.x), dy = py(mock.pos.y);
  const dc = droneColor();
  const pulse = 8 + 3 * (0.5 + 0.5 * Math.sin(mock.odo * 10));
  ctx.beginPath(); ctx.arc(dx, dy, pulse, 0, Math.PI * 2);
  ctx.globalAlpha = 0.35; ctx.strokeStyle = dc; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.globalAlpha = 1;
  drawDrone(ctx, dx, dy, mock.head, dc);

  // 시나리오 + 페이즈 라벨.
  ctx.textAlign = "left";
  ctx.fillStyle = "#c9d1d9"; ctx.font = "bold 12px system-ui";
  ctx.fillText(SCENARIO.start + " → " + SCENARIO.goal, pad + 4, pad + 14);
  ctx.fillStyle = PHASE_COLOR[mock.phase]; ctx.font = "11px system-ui";
  ctx.fillText("● " + PHASE_LABEL[mock.phase], pad + 4, pad + 30);

  // 시작/목표 텍스트.
  ctx.fillStyle = "#c9d1d9"; ctx.font = "10px system-ui";
  ctx.fillText(SCENARIO.start, px(PATH[0].x) + 7, py(PATH[0].y) + 3);
  ctx.textAlign = "right";
  ctx.fillText(SCENARIO.goal, px(PATH[PATH.length - 1].x) - 7, py(PATH[PATH.length - 1].y) + 3);
  ctx.textAlign = "left";
}

/** 고도 프로파일 — 지형 표고선 + 드론 고도선(롤링 strip). */
function drawProfile() {
  const cv = canvases.profile;
  if (!cv || !cv.getContext) return;
  const ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height;
  ctx.fillStyle = "#010409"; ctx.fillRect(0, 0, W, H);

  const mL = 46, mR = 12, mT = 28, mB = 26;
  const plotW = W - mL - mR, plotH = H - mT - mB;
  const yMin = 120, yMax = 1200;
  const yPix = (m) => mT + plotH * (1 - (m - yMin) / (yMax - yMin));

  // y 격자 + 라벨.
  ctx.strokeStyle = "rgba(48,54,61,0.8)"; ctx.lineWidth = 1;
  ctx.fillStyle = "#8b949e"; ctx.font = "10px system-ui"; ctx.textAlign = "right";
  for (let m = yMin; m <= yMax; m += 270) {
    const y = yPix(m);
    ctx.beginPath(); ctx.moveTo(mL, y); ctx.lineTo(W - mR, y); ctx.stroke();
    ctx.fillText(Math.round(m) + "m", mL - 4, y + 3);
  }

  const hist = mock.history, n = hist.length;
  if (n > 1) {
    const xPix = (i) => mL + plotW * (i / (150 - 1));
    // 지형 면적.
    ctx.beginPath();
    ctx.moveTo(xPix(0), yPix(hist[0].terr));
    for (let i = 1; i < n; i++) ctx.lineTo(xPix(i), yPix(hist[i].terr));
    ctx.lineTo(xPix(n - 1), mT + plotH); ctx.lineTo(xPix(0), mT + plotH); ctx.closePath();
    ctx.fillStyle = "rgba(104,96,52,0.35)"; ctx.fill();
    // 지형 선.
    ctx.beginPath(); ctx.moveTo(xPix(0), yPix(hist[0].terr));
    for (let i = 1; i < n; i++) ctx.lineTo(xPix(i), yPix(hist[i].terr));
    ctx.strokeStyle = "#8a6f3a"; ctx.lineWidth = 1.5; ctx.stroke();
    // 드론 고도 선.
    const line = droneColor();
    ctx.beginPath(); ctx.moveTo(xPix(0), yPix(hist[0].alt));
    for (let i = 1; i < n; i++) ctx.lineTo(xPix(i), yPix(hist[i].alt));
    ctx.strokeStyle = line; ctx.lineWidth = 2; ctx.stroke();
    // 현재 점.
    ctx.beginPath(); ctx.arc(xPix(n - 1), yPix(hist[n - 1].alt), 3, 0, Math.PI * 2);
    ctx.fillStyle = line; ctx.fill();
  }

  // 축 프레임.
  ctx.strokeStyle = "#30363d"; ctx.lineWidth = 1;
  ctx.strokeRect(mL, mT, plotW, plotH);

  // 제목 + 범례.
  ctx.textAlign = "left"; ctx.font = "bold 11px system-ui"; ctx.fillStyle = "#c9d1d9";
  ctx.fillText("고도 프로파일 (거리→)", mL, 16);
  ctx.font = "10px system-ui";
  ctx.fillStyle = "#8a6f3a"; ctx.fillText("■ 지형 표고", mL + 150, 16);
  ctx.fillStyle = droneColor(); ctx.fillText("■ 드론 고도", mL + 232, 16);

  // 현재 값 readout.
  ctx.textAlign = "right"; ctx.fillStyle = "#c9d1d9"; ctx.font = "10px system-ui";
  ctx.fillText("고도 " + Math.round(mock.alt) + "m / 지형 " + Math.round(mock.terr) + "m", W - mR, H - 8);
  ctx.textAlign = "left"; ctx.fillStyle = "#8b949e";
  ctx.fillText("거리 " + mock.odo.toFixed(2), mL, H - 8);
}

/** 현재 신호 — 배터리·GPS·통신(L0~L3)·RAC 게이지/바. */
function drawSignals() {
  const cv = canvases.signals;
  if (!cv || !cv.getContext) return;
  const ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height;
  ctx.fillStyle = "#010409"; ctx.fillRect(0, 0, W, H);

  ctx.textAlign = "left"; ctx.font = "bold 11px system-ui"; ctx.fillStyle = "#c9d1d9";
  ctx.fillText("현재 신호 · C2 (mock)", 14, 20);

  const barX = 100, barW = W - barX - 74, barH = 13, rowH = 44;
  let y = 48;

  function row(label, drawBar, valueText, valueColor) {
    ctx.textAlign = "left"; ctx.font = "12px system-ui"; ctx.fillStyle = "#8b949e";
    ctx.fillText(label, 14, y + barH - 1);
    drawBar(y);
    ctx.textAlign = "right"; ctx.font = "bold 12px system-ui"; ctx.fillStyle = valueColor || "#c9d1d9";
    ctx.fillText(valueText, W - 14, y + barH - 1);
    y += rowH;
  }

  function meter(frac, color) {
    return (yy) => {
      ctx.fillStyle = "#161b22"; ctx.fillRect(barX, yy, barW, barH);
      ctx.fillStyle = color;
      ctx.fillRect(barX, yy, Math.max(2, barW * Math.max(0, Math.min(1, frac))), barH);
      ctx.strokeStyle = "#30363d"; ctx.lineWidth = 1; ctx.strokeRect(barX, yy, barW, barH);
    };
  }

  // 배터리.
  const bf = mock.battery / 100, bc = lvlColor(bf);
  row("배터리", meter(bf, bc), Math.round(mock.battery) + "%", bc);

  // GPS 품질.
  const gc = mock.gps > 0.85 ? "#3fb950" : (mock.gps > 0.6 ? "#d29922" : "#f85149");
  row("GPS 품질", meter(mock.gps, gc), Math.round(mock.gps * 100) + "%", gc);

  // 통신 (L0~L3, 3세그).
  const commsN = Math.max(0, Math.min(3, Math.round(mock.comms)));
  const commsColor = commsN >= 3 ? "#3fb950" : (commsN >= 2 ? "#d29922" : "#f85149");
  row("통신", (yy) => {
    const segW = (barW - 8) / 3;
    for (let i = 0; i < 3; i++) {
      ctx.fillStyle = i < commsN ? commsColor : "#161b22";
      ctx.fillRect(barX + i * (segW + 4), yy, segW, barH);
      ctx.strokeStyle = "#30363d"; ctx.strokeRect(barX + i * (segW + 4), yy, segW, barH);
    }
  }, "L" + commsN, commsColor);

  // RAC 등급 (4단계 스텝바).
  const racIdx = Math.max(0, Math.min(3, Math.round(mock.rac)));
  const RAC_LABELS = ["정상", "주의", "경계", "위험"];
  const RAC_COLORS = ["#3fb950", "#d29922", "#e08a2b", "#f85149"];
  row("RAC 등급", (yy) => {
    const segW = (barW - 12) / 4;
    for (let i = 0; i < 4; i++) {
      ctx.fillStyle = i <= racIdx ? RAC_COLORS[racIdx] : "#161b22";
      ctx.fillRect(barX + i * (segW + 4), yy, segW, barH);
      ctx.strokeStyle = "#30363d"; ctx.strokeRect(barX + i * (segW + 4), yy, segW, barH);
    }
  }, RAC_LABELS[racIdx], RAC_COLORS[racIdx]);

  // 페이즈/적 탐지 푸터.
  ctx.textAlign = "left"; ctx.font = "11px system-ui"; ctx.fillStyle = "#8b949e";
  ctx.fillText("상태:", 14, H - 14);
  ctx.fillStyle = PHASE_COLOR[mock.phase]; ctx.font = "bold 11px system-ui";
  ctx.fillText(PHASE_LABEL[mock.phase], 46, H - 14);
  ctx.textAlign = "right"; ctx.fillStyle = "#8b949e"; ctx.font = "11px system-ui";
  ctx.fillText("적: " + (mock.enemyActive ? "T3 탐지" : "—"), W - 14, H - 14);
}

// ── 애니메이션 루프 (requestAnimationFrame) ────────────────────

let _lastTs = 0;
function frame(ts) {
  const dt = _lastTs ? Math.min((ts - _lastTs) / 1000, 0.05) : 0.016;
  _lastTs = ts;
  updateMock(dt);
  drawMap();
  drawProfile();
  drawSignals();
  requestAnimationFrame(frame);
}

/** mock 시뮬 구동 시작. rAF 없으면 1회 렌더로 폴백. */
function startMockSim() {
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(frame);
  } else {
    updateMock(0.016);
    drawMap();
    drawProfile();
    drawSignals();
  }
}

// ── 진입점 ────────────────────────────────────────────────────

/** 서버 /config 에서 로그수집기 WS URL 기본값을 best-effort 로 가져온다. */
function loadConfig() {
  if (typeof fetch !== "function") return Promise.resolve();
  return fetch("/config")
    .then((r) => (r.ok ? r.json() : null))
    .then((cfg) => {
      if (cfg && cfg.log_ws_url && el.wsUrl) el.wsUrl.value = cfg.log_ws_url;
    })
    .catch(() => { /* 설정 조회 실패 시 기본값 유지 */ });
}

function init() {
  if (el.wsUrl) el.wsUrl.value = DEFAULT_LOG_WS_URL;
  startMockSim();

  if (el.connectBtn) el.connectBtn.addEventListener("click", toggleConnect);
  if (el.clearBtn) el.clearBtn.addEventListener("click", () => {
    el.list.innerHTML = "";
    updateCount();
  });
  if (el.mockBtn) el.mockBtn.addEventListener("click", injectMock);
  if (el.mockAuto) el.mockAuto.addEventListener("change", toggleMockAuto);
  [el.filterLevel, el.filterLayer, el.filterCid].forEach((node) => {
    if (node) node.addEventListener("input", applyFilters);
    if (node) node.addEventListener("change", applyFilters);
  });

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
