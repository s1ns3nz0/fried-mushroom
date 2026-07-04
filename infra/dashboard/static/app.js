"use strict";

// D4D 대시보드 — 수집기 WS /stream 라이브 클라이언트 + Canvas/HTML mock 시나리오 렌더.
// 대시보드는 판단하지 않는다 — 라이브 텔레메트리와 mock 결정 로그를 수신해 표시만 한다.
//
// AI 결정 모델(우측 패널 — 현재 결정 플로우 + 이력)은 현재 mock 시나리오 이벤트로만
// 구동된다 (handleDecisionLog 참고 — 향후 대시보드 /ws decision_log 타입 연동 스텁).

// ── 설정 ──────────────────────────────────────────────────────

const DEFAULT_LOG_WS_URL = "ws://localhost:8500/logs";
const DEFAULT_COLLECTOR_HTTP_URL = "http://localhost:8500";

// ── 공유 설정 로더 ────────────────────────────────────────────
// /config.json(정적 — S3 배포에서도 동작) → /config(로컬 dev 백엔드) → 내장 기본값.
// 결과 Promise 를 window.D4D_CONFIG 로 노출해 gcs.js 도 같은 설정을 쓴다.

function fetchConfigJson(url) {
  return fetch(url)
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
}

function loadSharedConfig() {
  const defaults = {
    logWsUrl: DEFAULT_LOG_WS_URL,
    collectorHttpUrl: DEFAULT_COLLECTOR_HTTP_URL,
  };
  if (typeof fetch !== "function") return Promise.resolve(defaults);
  return fetchConfigJson("/config.json")
    .then((cfg) => (cfg && cfg.log_ws_url ? cfg : fetchConfigJson("/config")))
    .then((cfg) => ({
      logWsUrl: (cfg && cfg.log_ws_url) || defaults.logWsUrl,
      collectorHttpUrl: (cfg && cfg.collector_http_url) || defaults.collectorHttpUrl,
    }));
}

if (typeof window !== "undefined") {
  window.D4D_CONFIG = loadSharedConfig();
}

// ── 상태 ──────────────────────────────────────────────────────

const state = {
  logWsUrl: DEFAULT_LOG_WS_URL, // /config 로 갱신되는 URL 원천(streamUrl 유도용).
  streamWs: null,
  streamConnected: false,
  streamReconnectDelay: 1000, // backoff (ms), 최대 15s.
  streamUrl: null, // logWsUrl에서 /logs → /stream 치환으로 유도(loadConfig 이후 확정).
};

// 수집기 WS /stream(라이브 텔레메트리) 수신 상태. active=true면 지도/고도 프로파일이
// mock 대신 이 상태를 그린다(신호 패널은 계속 mock — updateMock 참고).
// init 은 재연결/백로그로 2회 도착할 수 있어 idempotent 하게 처리한다(동일 격자면 재빌드 스킵).
const live = {
  active: false,
  route: null,
  terrain: null, // {u16, W, H, hmin, hmax} — 뷰셰드/프로파일 계산용 원본 격자.
  terrainLayer: null, // 렌더용 오프스크린 canvas(D4DRender.buildTerrainLayer).
  profile: null, // 고도 프로파일 정적 데이터(live.route 기준, buildLiveProfile).
  drone: null,
  trail: [],
  enemies: [], // init의 사전 브리핑 적 + tick의 discovered_enemies 병합(정적, 이동 없음).
  briefing: null, // init의 GCS 사전 첩보 {directive, threats:[{threat,confidence,source_phrase}]}.
  _terrainKey: null, // 동일 격자 재수신 시 rebuild 스킵용.
  _enemyFootprints: null, // 적별 탐지 footprint 레이어 캐시(정적 적 — init 시 1회 계산).
  _enemyFootprintsKey: null, // terrain+enemies 시그니처 — 동일하면 rebuild 스킵.
  channels: null, // tick.channels(실 파이프라인 11채널 스냅샷) — 신호 패널 소스(없으면 mock 폴백).
  threatEvent: null, // 현재 라이브 조우의 threat_event — 변경 감지로 새 조우를 연다.
  debug: null, // tick.debug(최신 사이클의 레이어별 input/output) — 디버그 로그 패널 소스.
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

// ── DOM 렌더 ──────────────────────────────────────────────────

const el = {
  status: document.getElementById("conn-status"),
  signalsList: document.getElementById("signals-list"),
  phaseChip: document.getElementById("phase-chip"),
  simModeChip: document.getElementById("sim-mode-chip"),
};

/** topbar #conn-status — /stream 라이브 연결 상태 표시. */
function setStatus(text, ok) {
  if (el.status) {
    el.status.textContent = text;
    el.status.classList.toggle("status-on", !!ok);
    el.status.classList.toggle("status-off", !ok);
  }
}

// ── 수집기 WS /stream 클라이언트(라이브 텔레메트리) ──────────────
// backoff 재연결 패턴 — /config 로 URL 확정 후 자동 연결.

/** 수집기 WS /stream 에 연결. init(지형/경로) → tick(드론 상태) 순으로 수신. */
function connectStream() {
  if (!state.streamUrl) return;
  let ws;
  try {
    ws = new WebSocket(state.streamUrl);
  } catch (e) {
    return;
  }
  state.streamWs = ws;

  ws.onopen = () => {
    state.streamConnected = true;
    state.streamReconnectDelay = 1000;
    setStatus("라이브 연결됨", true);
  };
  ws.onclose = () => {
    state.streamConnected = false;
    live.active = false; // 연결 끊김 → mock 재개(updateMock 프리즈 해제).
    live.channels = null; // 신호 패널도 mock(computeChannels)으로 복귀.
    live.threatEvent = null;
    setStatus("라이브 끊김", false);
    scheduleStreamReconnect();
  };
  ws.onerror = () => {
    // onclose 가 뒤따르므로 상태 갱신 없음.
  };
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleStreamMessage(msg);
    } catch (e) {
      // 파싱/처리 실패 로그는 드롭(관측 전용, 콘솔 에러 없음).
    }
  };
}

function scheduleStreamReconnect() {
  const delay = state.streamReconnectDelay;
  state.streamReconnectDelay = Math.min(delay * 2, 15000);
  setTimeout(() => {
    if (!state.streamConnected) connectStream();
  }, delay);
}

/** type=init/tick 라우팅(그 외 타입은 무시). */
function handleStreamMessage(msg) {
  if (!msg || typeof msg !== "object") return;
  if (msg.type === "init") applyStreamInit(msg);
  else if (msg.type === "tick") applyStreamTick(msg);
}

/**
 * type=init 처리 — 재연결/백로그로 2회 도착해도 idempotent(동일 격자 크기/범위면
 * 지형 레이어 rebuild 스킵, route/active/trail은 매번 갱신·리셋해도 무해하다 —
 * init은 연결 초입에서만 오므로 진행 중이던 trail을 지우는 부작용이 없다).
 */
function applyStreamInit(msg) {
  const t = msg.terrain, route = msg.route;
  if (!t || !route) return;
  const key = t.w + "x" + t.h + ":" + t.hmin + ":" + t.hmax;
  if (live._terrainKey !== key) {
    const u16 = new Uint16Array(t.u16);
    live.terrain = { u16, W: t.w, H: t.h, hmin: t.hmin, hmax: t.hmax };
    // buildTerrainLayer는 시각화용 — u16이 이미 0..65535로 정규화돼 있으므로
    // hmin/hmax는 0/65535 그대로 넘긴다(mock terrainLayer와 동일 관례, 위 주석 참고).
    // 실제 물리 hmin/hmax(m)는 live.terrain에 별도 보관해 뷰셰드/프로파일 계산에 쓴다.
    live.terrainLayer = D4DRender.buildTerrainLayer(u16, t.h, t.w, 0, 65535);
    live._terrainKey = key;
  }
  live.route = route;
  live.profile = buildLiveProfile(route, live.terrain);
  live.active = true;
  live.trail = [];
  live.enemies = msg.enemies || [];
  live.briefing = msg.briefing || null;
  rebuildLiveEnemyFootprints();
}

/** type=tick 처리 — 드론 스냅샷 갱신 + 고도 프로파일 trail 누적 + 실 채널/결정 반영. */
function applyStreamTick(msg) {
  live.drone = {
    x: msg.x, y: msg.y, alt_m: msg.alt_m, terrain_m: msg.terrain_m,
    heading_deg: msg.heading_deg, speed_mps: msg.speed_mps,
    battery_pct: msg.battery_pct, s: msg.s,
  };
  live.trail.push([msg.s * MAP_EXTENT_M, msg.alt_m]);
  if (msg.discovered_enemies) mergeDiscoveredEnemies(msg.discovered_enemies);
  if (msg.channels) live.channels = toChannelMap(msg.channels);
  if (msg.decision) applyLiveDecision(msg.decision, msg.channels);
  if (msg.debug) {
    live.debug = msg.debug;
    if (debugState.open) renderDebugLog(); // 패널이 열려 있으면 최신 tick으로 라이브 갱신.
  }
}

/** 적 dedup 키 — kind + 좌표(반올림). discovered_enemies 는 누적 리스트라 매 tick 재도착한다. */
function enemyMergeKey(en) {
  return (en.kind || en.type || "") + ":" +
    Number(en.x).toFixed(4) + ":" + Number(en.y).toFixed(4);
}

/** tick.discovered_enemies(누적) → live.enemies 병합. 임무 중 "식별"된 popup 적은
 * init 에 없으므로 여기서 처음 지도에 나타나고, 이후 tick 에서도 유지된다(제거 없음).
 * 신규 병합 시에만 footprint 레이어를 재구축한다(키 변화로 캐시 무효화). */
function mergeDiscoveredEnemies(list) {
  if (!Array.isArray(list) || !list.length || !Array.isArray(live.enemies)) return;
  const known = new Set(live.enemies.map(enemyMergeKey));
  let added = false;
  for (const en of list) {
    if (!en || typeof en.x !== "number" || typeof en.y !== "number") continue;
    const key = enemyMergeKey(en);
    if (known.has(key)) continue;
    known.add(key);
    live.enemies.push(Object.assign({}, en, { discovered: true }));
    added = true;
  }
  if (added) rebuildLiveEnemyFootprints();
}

/** payload의 스칼라 필드 최대 4개를 "k=v"로 잇는 범용 포맷터(채널별 문장 없음, 표시 전용). */
function fmtChannelPayload(payload) {
  if (!payload || typeof payload !== "object") return "";
  const parts = [];
  for (const k of Object.keys(payload)) {
    const v = payload[k];
    const t = typeof v;
    if (t !== "string" && t !== "number" && t !== "boolean") continue;
    parts.push(k + "=" + (t === "number" && !Number.isInteger(v) ? v.toFixed(2) : String(v)));
    if (parts.length >= 4) break;
  }
  return parts.join(" · ");
}

/** tick.channels 배열 → renderSignals/renderDecisionChips가 쓰는
 * {channel key → {quality, state, delta, summary}} 맵으로 변환. */
function toChannelMap(arr) {
  const out = {};
  arr.forEach((c) => {
    if (!c || !c.channel) return;
    out[c.channel] = {
      quality: typeof c.quality === "number" ? c.quality : 0,
      state: c.state,
      delta: typeof c.quality_delta === "number" ? c.quality_delta : 0,
      summary: fmtChannelPayload(c.payload),
    };
  });
  return out;
}

/** tick.decision(실 파이프라인 산출)을 기존 5블록 결정 플로우 상태에 매핑(표시 전용, 재판단 없음).
 * primary 위협 등장/변경 시 새 조우를 열고, primary 소멸 시 조우를 이력으로 내린다. */
function applyLiveDecision(dec, channels) {
  if (!dec || typeof dec !== "object") return;
  const primary = dec.threat && dec.threat.primary ? dec.threat.primary : null;
  if (!primary) {
    if (decision.current) {
      finalizeDecision();
      live.threatEvent = null;
    }
    renderDecisionFlow();
    return;
  }
  if (!decision.current || live.threatEvent !== primary.threat_event) {
    finalizeDecision();
    decision.seq++;
    decision.current = { seq: decision.seq, stages: {} };
    live.threatEvent = primary.threat_event;
  }
  const stages = decision.current.stages;

  // 1 탐지 — state != normal 채널명 나열.
  const fired = (channels || [])
    .filter((c) => c && c.state !== "normal")
    .map((c) => c.channel);
  stages.detect = {
    msg: fired.length ? fired.join(" · ") : "-",
    sub: fired.length + "개 채널 이상",
  };

  // 2 위협 판정 — threat_event + confidence + kill_chain_stage 뱃지.
  stages.threat = {
    msg: primary.threat_event,
    badge: primary.kill_chain_stage,
    short: primary.threat_event,
    conf: typeof primary.confidence === "number" ? primary.confidence : undefined,
    sub: "",
  };

  // 3 위험 평가 — RAC 뱃지 + 복합 긴급도.
  if (dec.risk) {
    const urg = dec.risk.compound_urgency_score;
    stages.assess = {
      msg: "RAC",
      rac: dec.risk.rac,
      sub: "긴급도 " + (typeof urg === "number" ? urg.toFixed(2) : String(urg)),
    };
  }

  // 4 대응 결정 — flight_action + (comms_level, target_bearing_deg, replan_scope).
  if (dec.response) {
    const fp = dec.flight_plan;
    const subParts = [];
    if (dec.response.comms_level != null) subParts.push("comms " + dec.response.comms_level);
    if (fp && typeof fp.target_bearing_deg === "number") {
      subParts.push("방위 " + Math.round(fp.target_bearing_deg) + "°");
    }
    if (fp && fp.replan_scope != null) subParts.push(String(fp.replan_scope));
    stages.respond = { msg: dec.response.flight_action, sub: subParts.join(" · ") };
  }

  renderDecisionFlow();
}

// ── AI 결정 모델(우측 패널) — 현재 결정 플로우 + 결정 이력 ──────
// mock 시나리오 이벤트에서만 구동된다(관측 전용, 재판단 없음).
// 상태 모델: 진행 중 조우 1건(decision.current)의 스테이지(detect/threat/assess/respond)가
// pushDecision 으로 채워져 5블록 플로우에 반영되고, 조우 완료(resume 또는 새 detect) 시
// 이력 1행(decision.history, 최신순 최대 6건)으로 내려간다. 조우가 없으면 평시(정상 순항) 표시.

const MAX_DECISION_HISTORY = 6;

const decision = {
  seq: 0,
  current: null, // { seq, stages: { detect|threat|assess|respond: {msg, sub, badge, short, conf, rac} } }
  history: [],   // 최신순 [{ ts, label, miss, summary }]
};

const dcEl = {
  meta: document.getElementById("decision-meta"),
  chips: document.getElementById("dc-chips"),
  combineLbl: document.getElementById("dc-combine-lbl"),
  detect: document.getElementById("dc-detect"),
  detectLine: document.getElementById("dc-detect-line"),
  detectSub: document.getElementById("dc-detect-sub"),
  threat: document.getElementById("dc-threat"),
  threatLine: document.getElementById("dc-threat-line"),
  threatBadge: document.getElementById("dc-threat-badge"),
  threatSub: document.getElementById("dc-threat-sub"),
  threatConf: document.getElementById("dc-threat-conf"),
  threatPct: document.getElementById("dc-threat-pct"),
  threatFill: document.getElementById("dc-threat-fill"),
  assess: document.getElementById("dc-assess"),
  assessLine: document.getElementById("dc-assess-line"),
  assessBadge: document.getElementById("dc-assess-badge"),
  assessSub: document.getElementById("dc-assess-sub"),
  respond: document.getElementById("dc-respond"),
  respondTxt: document.getElementById("dc-respond-txt"),
  respondSub: document.getElementById("dc-respond-sub"),
  history: document.getElementById("decision-history"),
};

/** 현재 조우를 결정 이력 1행(최신순)으로 내리고 플로우를 평시 상태로 비운다. */
function finalizeDecision() {
  const cur = decision.current;
  if (!cur) return;
  const th = cur.stages.threat;
  const as = cur.stages.assess;
  const re = cur.stages.respond;
  const summary = (as && as.rac ? "RAC " + as.rac + " → " : "") +
    (re ? re.msg : "정상 순항 유지");
  decision.history.unshift({
    ts: Date.now(),
    label: th ? (th.short || th.msg) : "위협 없음",
    miss: !th,
    summary,
  });
  if (decision.history.length > MAX_DECISION_HISTORY) {
    decision.history.length = MAX_DECISION_HISTORY;
  }
  decision.current = null;
  renderDecisionHistory();
}

/** AI 결정 stage 1건 — detect 는 새 조우를 열고(직전 미완 조우는 이력으로),
 * threat/assess/respond 는 현재 조우 스테이지를 채우고, replan 은 respond sub 에 덧붙이고,
 * resume 은 조우를 완료해 이력으로 내린다. detail 은 mock 이 넘기는 구조화 필드(옵션). */
function pushDecision(type, message, detail) {
  const d = detail || {};
  if (type === "resume") {
    finalizeDecision();
    renderDecisionFlow();
    return;
  }
  if (type === "detect" || !decision.current) {
    finalizeDecision();
    decision.seq++;
    decision.current = { seq: decision.seq, stages: {} };
  }
  const stages = decision.current.stages;
  if (type === "replan") {
    const re = stages.respond;
    if (re) re.sub = (re.sub ? re.sub + " · " : "") + message;
    else stages.respond = { msg: message, sub: "" };
  } else {
    stages[type] = {
      msg: message, sub: d.sub || "",
      badge: d.badge, short: d.short, conf: d.conf, rac: d.rac,
    };
  }
  renderDecisionFlow();
}

/** 현재 결정 플로우(블록 1~4) 렌더 — 미발화 스테이지는 muted 대기, 조우 없으면 평시. */
function renderDecisionFlow() {
  if (!dcEl.detect) return;
  const cur = decision.current;
  const st = cur ? cur.stages : {};
  const calm = !cur;

  // 1 탐지 — 조우 없으면 "정상 순항 · 위협 없음" 평시 상태.
  const de = st.detect;
  dcEl.detect.classList.toggle("wait", !de && !calm);
  dcEl.detect.classList.toggle("calm", calm && !de);
  dcEl.detectLine.textContent = de ? de.msg : (calm ? "정상 순항 · 위협 없음" : "대기");
  dcEl.detectSub.textContent = de ? de.sub : (calm ? "이상 신호 없음 · 감시 지속" : "");

  // 2 위협 판정 — HOSTILE 뱃지 + 신뢰도 바.
  const th = st.threat;
  dcEl.threat.classList.toggle("wait", !th);
  dcEl.threatLine.textContent = th ? th.msg : "대기";
  dcEl.threatBadge.hidden = !(th && th.badge);
  if (th && th.badge) dcEl.threatBadge.textContent = th.badge;
  dcEl.threatSub.textContent = th ? th.sub : "";
  const conf = th && typeof th.conf === "number" ? th.conf : null;
  dcEl.threatConf.hidden = conf === null;
  if (conf !== null) {
    dcEl.threatPct.textContent = "신뢰도 " + Math.round(conf * 100) + "%";
    dcEl.threatFill.style.width = Math.round(conf * 100) + "%";
  }

  // 3 위험 평가 — RAC 뱃지.
  const as = st.assess;
  dcEl.assess.classList.toggle("wait", !as);
  dcEl.assessLine.textContent = as ? as.msg : "대기";
  dcEl.assessBadge.hidden = !(as && as.rac);
  if (as && as.rac) dcEl.assessBadge.textContent = as.rac;
  dcEl.assessSub.textContent = as ? as.sub : "";

  // 4 대응 결정 — 발화 시 앰버 활성 강조.
  const re = st.respond;
  dcEl.respond.classList.toggle("wait", !re);
  dcEl.respond.classList.toggle("active", !!re);
  dcEl.respond.classList.toggle("decision", !!re);
  dcEl.respondTxt.textContent = re ? re.msg : "대기";
  dcEl.respondSub.textContent = re ? re.sub : "";
}

/** 결정 이력(완료 조우 최신순 최대 6건) 렌더 — 위협 없음 케이스는 green 뱃지(miss). */
function renderDecisionHistory() {
  if (!dcEl.history) return;
  dcEl.history.textContent = "";
  if (!decision.history.length) {
    const empty = document.createElement("div");
    empty.className = "dc-hempty";
    empty.textContent = "완료된 결정 없음";
    dcEl.history.appendChild(empty);
    return;
  }
  decision.history.forEach((h) => {
    const row = document.createElement("div");
    row.className = "dc-hrow" + (h.miss ? " miss" : "");
    const ht = document.createElement("span");
    ht.className = "dc-ht";
    ht.textContent = formatTs(h.ts).slice(0, 8); // HH:MM:SS
    const hb = document.createElement("span");
    hb.className = "dc-hb";
    hb.textContent = h.label;
    const sum = document.createElement("span");
    sum.className = "dc-hsum";
    sum.textContent = h.summary;
    sum.title = h.summary;
    row.append(ht, hb, sum);
    dcEl.history.appendChild(row);
  });
}

// 입력 신호 chip(블록 0) — 11채널을 1회 생성해 제자리 갱신.
let _dcChipsBuilt = false;
const _dcChipRefs = {};

function ensureDecisionChips() {
  if (_dcChipsBuilt || !dcEl.chips) return;
  CHANNEL_DEFS.forEach((def) => {
    const chip = document.createElement("span");
    chip.className = "dc-chip";
    const dot = document.createElement("span");
    dot.className = "dc-dot";
    const txt = document.createElement("span");
    chip.append(dot, txt);
    dcEl.chips.appendChild(chip);
    _dcChipRefs[def.key] = { chip, txt };
  });
  _dcChipsBuilt = true;
}

/** 블록 0 신호 chip + "N개 신호 결합" 라벨 + 헤더 메타 — 매 프레임 채널 스냅샷으로 갱신.
 * state != normal 채널만 점등(anomaly=red, degraded=amber). */
function renderDecisionChips(channels) {
  ensureDecisionChips();
  if (!dcEl.chips || !channels) return;
  let fired = 0;
  CHANNEL_DEFS.forEach((def) => {
    const refs = _dcChipRefs[def.key];
    const c = channels[def.key];
    if (!refs || !c) return;
    const on = c.state !== "normal";
    if (on) fired++;
    refs.chip.className = "dc-chip" + (on ? (c.state === "degraded" ? " warn on" : " on") : "");
    refs.txt.textContent = def.label + " · " + c.state;
  });
  if (dcEl.combineLbl) dcEl.combineLbl.textContent = fired + "개 신호 결합";
  if (dcEl.meta) {
    dcEl.meta.textContent = decision.current
      ? "EVT-" + String(decision.current.seq).padStart(3, "0") + " · 실시간"
      : "감시 중 · 실시간";
  }
}

/**
 * 향후 대시보드 /ws 의 decision_log 타입 메시지 핸들러(스텁).
 * TODO(연동): 실제 온보드 파이프라인이 decision_log 이벤트를 WS로 보내면
 * 여기서 msg.type/msg.message 를 pushDecision 에 그대로 연결한다.
 * type ∈ detect(탐지)/threat(위협)/assess(평가)/respond(대응)/replan(재계획)/resume(재개).
 * 현재는 WS 연결을 구현하지 않고 mock 시나리오 이벤트만 pushDecision 을 직접 호출한다.
 */
function handleDecisionLog(msg) {
  if (!msg) return;
  pushDecision(msg.type, msg.message);
}

// ── 디버그 모드 — 레이어별 input/output 로그 (관측 전용, 표시만) ──
// DEBUG 토글(topbar) ON → 🐛 버튼(AI 결정 모델 우상단, fixed) 표시 →
// 클릭 시 #debug-log 오버레이 토글. 열려 있는 동안 매 tick 최신 사이클의
// live.debug.layers(5개 레이어 IN/OUT JSON)로 라이브 갱신된다.

const debugState = { mode: false, open: false };

const dbgEl = {
  toggle: document.getElementById("debug-toggle"),
  bugBtn: document.getElementById("debug-bug-btn"),
  panel: document.getElementById("debug-log"),
  body: document.getElementById("debug-log-body"),
};

// 레이어 블록(접이식 details)은 레이어 구성이 같으면 재사용하고 JSON 본문(<pre>)만
// 제자리 갱신한다 — 접힘 상태/스크롤 위치가 tick마다 리셋되지 않게 한다.
let _dbgLayersKey = null;
const _dbgPreRefs = []; // 레이어 인덱스 순 [{ inPre, outPre }]

/** #debug-log 본문 렌더 — live.debug.layers를 레이어별 IN/OUT JSON 블록으로 표시. */
function renderDebugLog() {
  if (!dbgEl.body || !debugState.open) return;
  const layers = live.debug && Array.isArray(live.debug.layers) ? live.debug.layers : [];
  if (!layers.length) {
    _dbgLayersKey = null;
    _dbgPreRefs.length = 0;
    dbgEl.body.textContent = "디버그 데이터 없음 — 러너 tick 수신 대기 중";
    return;
  }
  const key = layers.map((l) => l.layer).join("|");
  if (_dbgLayersKey !== key) {
    dbgEl.body.textContent = "";
    _dbgPreRefs.length = 0;
    layers.forEach((l, i) => {
      const det = document.createElement("details");
      det.className = "dbg-layer";
      det.open = i === 0;
      const sum = document.createElement("summary");
      sum.textContent = l.layer;
      det.appendChild(sum);
      const refs = {};
      ["IN", "OUT"].forEach((label) => {
        const sec = document.createElement("div");
        sec.className = "dbg-io";
        const h = document.createElement("div");
        h.className = "dbg-io-label" + (label === "OUT" ? " out" : "");
        h.textContent = label;
        const pre = document.createElement("pre");
        pre.className = "dbg-json";
        sec.append(h, pre);
        det.appendChild(sec);
        refs[label] = pre;
      });
      dbgEl.body.appendChild(det);
      _dbgPreRefs.push({ inPre: refs.IN, outPre: refs.OUT });
    });
    _dbgLayersKey = key;
  }
  layers.forEach((l, i) => {
    const refs = _dbgPreRefs[i];
    if (!refs) return;
    refs.inPre.textContent = JSON.stringify(l.input, null, 2);
    refs.outPre.textContent = JSON.stringify(l.output, null, 2);
  });
}

/** DEBUG 토글/🐛 버튼 바인딩 — 토글 OFF 시 버튼과 로그 패널을 함께 숨긴다. */
function initDebugMode() {
  if (!dbgEl.toggle || !dbgEl.bugBtn || !dbgEl.panel) return;
  dbgEl.toggle.addEventListener("click", () => {
    debugState.mode = !debugState.mode;
    dbgEl.toggle.classList.toggle("active", debugState.mode);
    dbgEl.toggle.setAttribute("aria-pressed", debugState.mode ? "true" : "false");
    dbgEl.bugBtn.hidden = !debugState.mode;
    if (!debugState.mode) {
      debugState.open = false;
      dbgEl.panel.hidden = true;
    }
  });
  dbgEl.bugBtn.addEventListener("click", () => {
    debugState.open = !debugState.open;
    dbgEl.panel.hidden = !debugState.open;
    if (debugState.open) renderDebugLog();
  });
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

/** mock 드론 현재 위치 기준 적(ENEMY) 방위(deg, 0..360) — 신호/결정 표시 공용. */
function enemyBearingDeg() {
  return ((Math.atan2(ENEMY.y - mock.pos.y, ENEMY.x - mock.pos.x) * 180) / Math.PI + 360) % 360;
}

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
  _threatened: false, _assessed: false, _responded: false,
  chanQ: {}, // 채널별 이전 quality(quality_delta = quality(t) - quality(t-1) 계산용).
  speedMps: UAV_CRUISE_MPS, // 현재 프레임 UAV 대지속도(m/s) — updateMock에서 phase별로 갱신.
  att: { roll: 0, pitch: 0, yaw: 0 }, // FC 자세(deg) — 운동상태에서 유도(updateMock, 저역통과).
  gyro: { p: 0, q: 0, r: 0 }, // 기체 각속도(deg/s) — roll/pitch/yaw 미분(저역통과).
  vs: 0, // 수직속도(m/s) — mock.alt 미분(저역통과).
  _prevHead: null, _prevAlt: null, _altTarget: null,
  timeScale: 1, // 배속(−/+ 스테퍼, SPEED_STEPS 중 하나) — 시뮬레이션 시간에만 적용(WS 재연결/실제 timestamp/rAF 제외).
  paused: false, // 일시중지 — true 면 updateMock(상태 전진)·주기 시스템 로그를 스킵(rAF 렌더는 유지).
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

// gridX/gridY의 일반화판 — live.terrain은 GRID 상수가 아닌 수신 격자 크기(grid.W/H)를 쓴다.
function liveGridX(grid, nx) { return nx * (grid.W - 1); }
function liveGridY(grid, ny) { return (1 - ny) * (grid.H - 1); }

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

// 위협 유형별 마커 dispatch — kind→category→symbol 매핑:
//   T3/T4 (물리 적: 소화기/포획)                → physical → drawHostileGround (적색 다이아몬드)
//   T1/T2/T5 (원격 전자전: GPS스푸핑/사이버/레이저) → ew      → drawEwThreat (보라 육각형+번개)
//   T7 (항법 지형위험: 지형충돌/CFIT)            → terrain  → drawTerrainHazard (앰버 경고 삼각형)
//   미상 kind → physical 폴백. footprint 색도 같은 카테고리를 따른다.
const THREAT_CATEGORY = { T1: "ew", T2: "ew", T5: "ew", T3: "physical", T4: "physical", T7: "terrain" };
const FOOTPRINT_RGB = {
  physical: [240, 85, 93],  // 적색(적 지상부대)
  ew: [201, 123, 240],      // 보라(#C97BF0, 전자전)
  terrain: [229, 169, 61],  // 앰버(#E5A93D, 지형위험)
};

/** kind("T3", "T3 소화기" 등)에서 Tn 토큰을 뽑아 카테고리로 변환(미상은 physical). */
function threatCategory(kind) {
  const m = String(kind || "").toUpperCase().match(/T\d+/);
  return (m && THREAT_CATEGORY[m[0]]) || "physical";
}

/** 카테고리별 심볼 디스패치 — render.js 순수 헬퍼 호출. */
function drawThreatMarker(ctx, kind, x, y, size) {
  const cat = threatCategory(kind);
  if (cat === "ew") D4DRender.drawEwThreat(ctx, x, y, size);
  else if (cat === "terrain") D4DRender.drawTerrainHazard(ctx, x, y, size);
  else D4DRender.drawHostileGround(ctx, x, y, size);
}

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

// Min footprint range (cells) so the enemy viewshed reaches ridgelines and terrain occlusion is visible.
const ENEMY_FOOTPRINT_MIN_RANGE_CELLS = 45;

/** 라이브 사전 브리핑 적의 탐지 footprint 레이어를 재구축한다.
 * 적은 정적이고 지형은 init마다 고정이므로 terrain+enemies 시그니처가 같으면 스킵
 * (매 프레임 재계산 금지 — computeEnemyFootprint 는 적당 O(rays×range)). */
function rebuildLiveEnemyFootprints() {
  if (!live.terrain || !live.enemies || !live.enemies.length) {
    live._enemyFootprints = null;
    live._enemyFootprintsKey = null;
    return;
  }
  const key = live._terrainKey + "|" + live.enemies
    .map((en) => [en.x, en.y, en.radius, en.briefed ? 1 : 0, en.kind || en.type || ""].join(","))
    .join(";");
  if (live._enemyFootprintsKey === key && live._enemyFootprints) return;
  const g = live.terrain;
  live._enemyFootprints = live.enemies.map((en) => {
    // T7 (terrain hazard, e.g. CFIT) is not an observer — no detection FOV footprint.
    if (threatCategory(en.kind || en.type) === "terrain") return null;
    const enemyGrid = {
      center: [liveGridX(g, en.x), liveGridY(g, en.y)],
      detect_range: Math.max((en.radius || 0.05) * (g.W - 1), ENEMY_FOOTPRINT_MIN_RANGE_CELLS),
    };
    const mask = D4DRender.computeEnemyFootprint(g.u16, g.H, g.W, g.hmin, g.hmax, enemyGrid);
    const rgb = FOOTPRINT_RGB[threatCategory(en.kind || en.type)];
    const color = rgb.concat(Math.round((en.briefed ? 0.34 : 0.24) * 255));
    return D4DRender.buildFootprintLayer(mask, g.H, g.W, color);
  });
  live._enemyFootprintsKey = key;
}

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
  // 라이브 활성 + 드론 tick 수신 시 live.terrain/live.drone 기준으로 계산, 그 외엔 mock.
  const useLive = !!(live.active && live.drone && live.terrain);
  const grid = useLive ? live.terrain : terrainGrid;
  const gx = useLive ? liveGridX(grid, live.drone.x) : gridX(mock.pos.x);
  const gy = useLive ? liveGridY(grid, live.drone.y) : gridY(mock.pos.y);
  const alt = useLive ? live.drone.alt_m : mock.alt;
  const moved = !lastViewshedGrid ||
    lastViewshedGrid.live !== useLive ||
    Math.hypot(gx - lastViewshedGrid.gx, gy - lastViewshedGrid.gy) >= VIEWSHED_MOVE_CELLS;
  const timedOut = now - lastViewshedTime >= VIEWSHED_RECOMPUTE_MS;
  if (viewshedLayer && !moved && !timedOut) return;
  const drone = { x: gx, y: gy, alt };
  const mask = D4DRender.computeViewshed(
    grid.u16, grid.H, grid.W, grid.hmin, grid.hmax, drone
  );
  viewshedLayer = D4DRender.buildViewshedLayer(mask, grid.H, grid.W, VIEWSHED_COLOR);
  lastViewshedGrid = { gx, gy, live: useLive };
  lastViewshedTime = now;
}

/** 배터리/품질 대비 색. */
function lvlColor(f) { return f > 0.5 ? "#4CC38A" : (f > 0.2 ? "#E5A93D" : "#F0555D"); }

// ── 공유 텔레메트리 산식 — 신호 11채널 패널(computeChannels)이 사용한다 ──

/** comms(0..3) → 재밍 정도(0..1). */
function commsJam() { return Math.max(0, Math.min(1, (3 - mock.comms) / 3)); }
function linkRssi(jam) { return Math.round(-62 - jam * 30); }
function linkLatency(jam) { return Math.round(45 + jam * 300); }
function linkLoss(jam) { return Math.min(0.4, jam * 0.35 + 0.01); }
function gpsSats() { return Math.round(6 + mock.gps * 10); }
function gpsHdop() { return 0.9 + (1 - mock.gps) * 4; }
function gpsResidualM() { return (1 - mock.gps) * 8; }
function escTempC(jitter) { return 42.0 + jitter * 1.5; }
function frameVib(jitter) { return 0.12 + Math.abs(jitter) * 0.03; }

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
  // 라이브 활성 시 지도상 mock 위치 전진을 스킵(드론 프리즈) — 신호/텔레메트리는
  // mock.pos(마지막 위치) 기준으로 계속 산출되어 패널은 정상 구동된다.
  if (!live.active) {
    const dsNorm = mock.dir * (speedMps / PATH_LENGTH_M) * dt;
    mock.s += dsNorm;
    if (mock.s < 0) mock.s = 0;
    if (mock.s > _total) mock.s = _total;

    const p = pointAtDist(mock.s);
    mock.pos = p;
    mock.head = p.head;
    mock.odo += Math.abs(dsNorm);
  }

  const p = mock.pos;
  const dEnemy = Math.hypot(p.x - ENEMY.x, p.y - ENEMY.y);
  mock.dEnemy = dEnemy;
  mock.enemyActive = dEnemy < ENEMY.r * 1.6;

  // 상태기계 — 전이 시점마다 AI 결정 모델(우측 패널) 스테이지를 emit.
  // 라이브 활성 중엔 스킵 — mock pushDecision이 실 결정 플로우(applyLiveDecision)를 덮지 않게 한다.
  if (live.active) {
    // live: decision flow is driven by applyLiveDecision only.
  } else if (mock.phase === "NORMAL") {
    if (mock.dir > 0 && dEnemy < ENEMY.r) {
      mock.phase = "ENCOUNTER"; mock.phaseT = 0;
      pushDecision("detect", "근접 물체 + 총성 동시 포착", {
        sub: "weapon_shape=true · closing=true · 방위 " + enemyBearingDeg().toFixed(0) + "°",
      });
    }
  } else if (mock.phase === "ENCOUNTER") {
    // 4단계 결정 스테이지 — 조우 창(~1.6s, simDt 기준)에 탐지→위협→평가→대응 순서로 발화.
    if (!mock._threatened && mock.phaseT > 0.4) {
      mock._threatened = true;
      pushDecision("threat", "T3 · 근접 소화기", {
        badge: "HOSTILE", short: "T3 소화기", conf: 0.92,
        sub: "킬체인: 후기 · potential_outcome: attrition_kill",
      });
    }
    if (!mock._assessed && mock.phaseT > 0.8) {
      mock._assessed = true;
      pushDecision("assess", "RAC =", {
        rac: "SERIOUS",
        sub: "가능성 L=B · 심각도 S=Critical · 긴급도 0.85 · priority 1",
      });
    }
    if (!mock._responded && mock.phaseT > 1.2) {
      mock._responded = true;
      pushDecision("respond", "RTL 복귀 · 통신 SILENT", {
        sub: "회피 방위 " + ((enemyBearingDeg() + 180) % 360).toFixed(0) +
          "° (적 방위 +180°) · 고도 +" + EVADE_CLIMB_M + "m",
      });
    }
    if (mock.phaseT > 1.6) {
      mock.phase = "RTL"; mock.dir = -1; mock.phaseT = 0;
      pushDecision("replan", "재계획 LOCAL(reroute)");
    }
  } else if (mock.phase === "RTL") {
    if (mock.s <= 0.0005) {
      // 복귀 완료 → 신규 임무 재시작. 고도 프로파일 trail 도 새 사이클로 리셋.
      mock.phase = "NORMAL"; mock.dir = 1; mock.phaseT = 0;
      mock.battery = 96;
      mock._threatened = false; mock._assessed = false; mock._responded = false;
      mock.trailProfile = [];
      pushDecision("resume", "임무 재개 — 경로 복행");
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
 * → 경로 → 복귀경로(RTL 시) → 마커(적 다이아몬드, 목표 OBJ, 출발지 SP, 드론).
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

  // 라이브 활성 시 지형/경로 데이터 소스를 mock → live로 교체(레이어 순서는 그대로).
  const activeTerrainLayer = (live.active && live.terrainLayer) ? live.terrainLayer : terrainLayer;
  const routeWps = (live.active && live.route && live.route.waypoints && live.route.waypoints.length > 1)
    ? live.route.waypoints : PATH;

  // 1) terrain + 좌표 그리드 오버레이(1/8 간격, 미터 라벨).
  if (activeTerrainLayer) ctx.drawImage(activeTerrainLayer, 0, 0, W, H);
  D4DRender.drawMapGrid(ctx, W, H, MAP_EXTENT_M);

  // 2) UAV 가시영역(뷰셰드) — 지형 위, 나머지 오버레이/마커 아래.
  if (viewshedLayer) ctx.drawImage(viewshedLayer, 0, 0, W, H);

  // 3) 적 탐지범위(footprint, 지형 반영 · 원 아님) — mock 시나리오 전용(라이브엔 적 데이터 없음).
  if (!live.active && enemyFootprintLayer) ctx.drawImage(enemyFootprintLayer, 0, 0, W, H);

  // 3.5) 라이브 사전 브리핑 적 탐지범위(footprint, 지형 반영 · 원 아님) — init 시 캐시된 레이어.
  if (live.active && live._enemyFootprints) {
    for (const fp of live._enemyFootprints) if (fp) ctx.drawImage(fp, 0, 0, W, H);
  }

  // 4) 경로(글로우 → 본선, 액티브 앰버).
  ctx.save();
  ctx.lineJoin = "round";
  const strokePath = () => {
    ctx.beginPath();
    for (let i = 0; i < routeWps.length; i++) {
      const X = px(routeWps[i].x), Y = py(routeWps[i].y);
      if (i) ctx.lineTo(X, Y); else ctx.moveTo(X, Y);
    }
  };
  strokePath(); ctx.strokeStyle = "rgba(240,160,60,0.25)"; ctx.lineWidth = 6; ctx.stroke();
  strokePath(); ctx.strokeStyle = "rgba(240,160,60,0.9)"; ctx.lineWidth = 2.5; ctx.stroke();
  ctx.restore();

  // 4.5) 경로 waypoint 마커 — 중간 waypoint(1..len-2)만 그린다(0=출발 SP, 마지막=목표 OBJ
  // 전용 심볼이 담당). 경로선 위, 적/드론 마커 아래. 다크 채움 + 경로 앰버 테두리 + 번호.
  ctx.save();
  ctx.font = "8px ui-monospace, Menlo, monospace";
  ctx.textAlign = "left";
  ctx.textBaseline = "bottom";
  for (let i = 1; i < routeWps.length - 1; i++) {
    const X = px(routeWps[i].x), Y = py(routeWps[i].y);
    ctx.beginPath();
    ctx.arc(X, Y, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#0D0D0F";
    ctx.fill();
    ctx.strokeStyle = "rgba(240,160,60,0.9)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = "rgba(240,160,60,0.75)";
    ctx.fillText(String(i), X + 6, Y - 5);
  }
  ctx.restore();

  // 5) 복귀경로(RTL 구간에서만) — mock 시나리오 전용(점선 앰버).
  if (!live.active && mock.phase === "RTL") {
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

  // 5.5) 사전 브리핑 적 마커(라이브 전용, 정적) — 경로 위, 목표/드론 마커 아래.
  if (live.active && live.enemies && live.enemies.length) {
    ctx.save();
    ctx.font = "600 10px ui-monospace, Menlo, monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    for (const en of live.enemies) {
      const ex = px(en.x), ey = py(en.y);
      // 탐지범위는 3.5)의 지형 반영 footprint 레이어가 담당(평면 원 제거).
      // 위협 유형별 MIL-STD-2525 계열 심볼 — kind→category 디스패치(drawThreatMarker).
      drawThreatMarker(ctx, en.kind || en.type, ex, ey, 8);
      // 사전 첩보(briefed) 적은 라벨을 밝게 + GCS 확신도 병기(예: "T3·95%").
      // 임무 중 식별(discovered)된 popup 적은 앰버 라벨 + "신규 식별" 표기.
      const label = (en.kind || en.type) +
        (en.briefed && typeof en.confidence === "number"
          ? "·" + Math.round(en.confidence * 100) + "%" : "") +
        (en.discovered ? " · 신규 식별" : "");
      ctx.fillStyle = en.briefed ? "rgba(255,154,147,0.95)"
        : (en.discovered ? "rgba(255,185,90,0.95)" : "rgba(240,85,93,0.55)");
      ctx.fillText(label, ex + 11, ey - 8);
    }
    ctx.restore();
  }

  // 6) 마커들 — 적 다이아몬드(mock 전용), 목표 OBJ, 출발지 SP, 드론.
  if (!live.active) {
    const ex = px(ENEMY.x), ey = py(ENEMY.y);
    // 위협 유형별 심볼 — mock 적은 SCENARIO.threat(T3) → physical 다이아몬드.
    drawThreatMarker(ctx, SCENARIO.threat, ex, ey, 8);
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
  }

  // MIL-STD-2525 objective/start tactical graphics (render.js pure helpers) —
  // 라이브/mock 공통. 라벨(OBJ/SP)은 헬퍼가 자체 렌더한다.
  const sN = routeWps[0], gN = routeWps[routeWps.length - 1];
  D4DRender.drawObjective(ctx, px(gN.x), py(gN.y), 9);
  D4DRender.drawStartPoint(ctx, px(sN.x), py(sN.y), 9);

  // 드론 마커 — 라이브 tick 수신 중이면 live.drone, 아니면 mock(라이브 대기 중엔 프리즈된 마지막 위치).
  const liveDrone = live.active && live.drone;
  const dronePos = liveDrone ? live.drone : mock.pos;
  const droneHeadRad = liveDrone ? (live.drone.heading_deg - 90) * (Math.PI / 180) : mock.head;
  const dc = liveDrone ? "#66C2FF" : droneColor();
  const odoLike = liveDrone ? live.drone.s : mock.odo;
  const dx = px(dronePos.x), dy = py(dronePos.y);
  const pulse = 8 + 3 * (0.5 + 0.5 * Math.sin(odoLike * 10));
  ctx.beginPath(); ctx.arc(dx, dy, pulse, 0, Math.PI * 2);
  ctx.globalAlpha = 0.35; ctx.strokeStyle = dc; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.globalAlpha = 1;
  // MIL-STD-2525 friendly AIR frame (render.js pure helper) — affiliation
  // blue beats the phase color; the pulse ring above keeps phase feedback.
  D4DRender.drawFriendlyAir(ctx, dx, dy, 9, droneHeadRad);

  // 7) 사전 첩보 칩(라이브 전용) — GCS briefing.threats를 우상단에 요약 표시.
  drawBriefingChip(ctx, W);
}

/** 지도 우상단 "사전 첩보" 코너 칩 — live.briefing.threats가 있을 때만 그린다.
 * 예: "첩보: T3 저격조 95%". 신호 오버레이(좌상단)와 겹치지 않게 우상단 고정. */
function drawBriefingChip(ctx, W) {
  const b = live.active ? live.briefing : null;
  if (!b || !b.threats || !b.threats.length) return;
  ctx.save();
  ctx.font = "600 10px ui-monospace, Menlo, monospace";
  const lines = b.threats.map((t) =>
    "첩보: " + t.threat + " " + (t.source_phrase || "") + " " +
    Math.round((t.confidence || 0) * 100) + "%");
  let maxW = ctx.measureText("사전 첩보").width;
  lines.forEach((ln) => { maxW = Math.max(maxW, ctx.measureText(ln).width); });
  const pad = 8, lh = 14;
  const bw = maxW + pad * 2;
  const bh = (lines.length + 1) * lh + pad * 2 - 4;
  const bx = W - bw - 10, by = 10;
  ctx.beginPath();
  ctx.roundRect(bx, by, bw, bh, 4);
  ctx.fillStyle = "rgba(13,13,15,0.78)";
  ctx.fill();
  ctx.strokeStyle = "rgba(240,85,93,0.45)";
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.fillStyle = "#98979F";
  ctx.fillText("사전 첩보", bx + pad, by + pad - 2);
  ctx.fillStyle = "#FF9A93";
  lines.forEach((ln, i) => {
    ctx.fillText(ln, bx + pad, by + pad - 2 + (i + 1) * lh);
  });
  ctx.restore();
}

/** 상단 앱바 모드/phase 칩 — mock.phase를 라벨+상태색으로 표시(관측 전용). */
function updatePhaseChip() {
  if (!el.phaseChip) return;
  el.phaseChip.textContent = PHASE_LABEL[mock.phase] || mock.phase;
  el.phaseChip.style.color = PHASE_COLOR[mock.phase] || "";
}

/** 지도 패널 헤더의 라이브/시뮬 모드 칩 — live.active를 라벨+accent 색으로 표시(관측 전용). */
function updateSimModeChip() {
  if (!el.simModeChip) return;
  el.simModeChip.textContent = live.active ? "라이브" : "시뮬";
  el.simModeChip.style.color = live.active ? "var(--accent)" : "";
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

/** 임의 waypoint 배열(x,y 정규화)의 누적 길이(정규 단위) — buildLiveProfile 용. */
function routeTotalLength(waypoints) {
  let total = 0;
  for (let i = 0; i < waypoints.length - 1; i++) {
    total += Math.hypot(waypoints[i + 1].x - waypoints[i].x, waypoints[i + 1].y - waypoints[i].y);
  }
  return total;
}

/** pointAtDist의 일반화판(heading 불필요) — live.route.waypoints 위 임의 거리 d의 {x,y}. */
function pointAtDistGeneric(waypoints, total, d) {
  if (d <= 0) return { x: waypoints[0].x, y: waypoints[0].y };
  const last = waypoints[waypoints.length - 1];
  if (d >= total) return { x: last.x, y: last.y };
  let acc = 0;
  for (let i = 0; i < waypoints.length - 1; i++) {
    const a = waypoints[i], b = waypoints[i + 1];
    const L = Math.hypot(b.x - a.x, b.y - a.y);
    if (acc + L >= d) {
      const t = L ? (d - acc) / L : 0;
      return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
    }
    acc += L;
  }
  return { x: last.x, y: last.y };
}

/** live.terrain(u16 격자)에서 정규 좌표(nx,ny)의 물리 표고(m)를 최근접 셀로 조회. */
function liveTerrainHeightAt(grid, nx, ny) {
  const gx = Math.min(grid.W - 1, Math.max(0, Math.round(liveGridX(grid, nx))));
  const gy = Math.min(grid.H - 1, Math.max(0, Math.round(liveGridY(grid, ny))));
  const range = (grid.hmax - grid.hmin) || 1;
  return grid.hmin + (grid.u16[gy * grid.W + gx] / 65535) * range;
}

/** buildFlightProfile의 라이브판 — live.route.waypoints를 따라 live.terrain 표고를 샘플링. */
function buildLiveProfile(route, grid) {
  const wps = route.waypoints;
  if (!wps || wps.length < 2 || !grid) return null;
  const total = routeTotalLength(wps);
  const SAMPLES = 80;
  const dist = new Array(SAMPLES);
  const terrainH = new Array(SAMPLES);
  let maxH = -Infinity;
  for (let i = 0; i < SAMPLES; i++) {
    const d = (total * i) / (SAMPLES - 1);
    const p = pointAtDistGeneric(wps, total, d);
    const h = liveTerrainHeightAt(grid, p.x, p.y);
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

/** 고도 프로파일 — D4DRender.drawProfile에 위임(지형 폴리곤 + trailProfile 고도선).
 * 라이브 활성 시 live.profile/live.trail을, 아니면 mock 정적 프로파일/trailProfile을 쓴다. */
function drawProfile() {
  const cv = canvases.profile;
  if (!cv || !cv.getContext) return;
  if (cv.clientWidth === 0) return; // 탭 숨김 상태 — 프레임 스킵(제로 사이즈 방어).
  syncCanvasSize(cv);
  const ctx = cv.getContext("2d");
  const prof = (live.active && live.profile) ? live.profile : FLIGHT_PROFILE;
  const trail = live.active ? live.trail : mock.trailProfile;
  D4DRender.drawProfile(ctx, prof, { trailProfile: trail });
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
  const bearingToEnemy = enemyBearingDeg();
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

/** 매 tick 채널 스냅샷으로 기존 행을 제자리 갱신(channels 미전달 시 직접 계산). */
function renderSignals(channels) {
  ensureSignalRows();
  if (!el.signalsList) return;
  channels = channels || computeChannels();
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

// ── 애니메이션 루프 (requestAnimationFrame) ────────────────────

let _lastTs = 0;
function frame(ts) {
  // _lastTs는 매 프레임(일시중지 중 포함) 갱신되므로 resume 첫 프레임의 dt는
  // 직전 rAF 프레임 간격(~16ms)뿐이다 — 일시중지 시간이 dt로 누적되지 않는다.
  const dt = _lastTs ? Math.min((ts - _lastTs) / 1000, 0.05) : 0.016;
  _lastTs = ts;
  if (!mock.paused) updateMock(dt);
  updateViewshedLayer(ts);
  drawMap();
  updatePhaseChip();
  updateSimModeChip();
  drawProfile();
  // 채널 스냅샷은 프레임당 1회만 계산(quality_delta 산식 보존) — 신호 패널·결정 chip 공용.
  // 라이브 활성 + tick.channels 수신 시 실 파이프라인 채널을, 아니면 mock 폴백을 쓴다.
  const channels = (live.active && live.channels) ? live.channels : computeChannels();
  renderSignals(channels);
  renderDecisionChips(channels);
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
    updateSimModeChip();
    drawProfile();
    const channels = (live.active && live.channels) ? live.channels : computeChannels();
    renderSignals(channels);
    renderDecisionChips(channels);
  }
}

// ── 진입점 ────────────────────────────────────────────────────

/** 공유 설정 로더(window.D4D_CONFIG)에서 로그수집기 WS URL 을 가져온다. */
function loadConfig() {
  const cfgPromise = typeof window !== "undefined" && window.D4D_CONFIG
    ? window.D4D_CONFIG
    : loadSharedConfig();
  return cfgPromise
    .then((cfg) => {
      if (cfg && cfg.logWsUrl) state.logWsUrl = cfg.logWsUrl;
      // /stream 은 /logs 와 같은 수집기의 다른 엔드포인트 — logWsUrl에서 유도한다.
      state.streamUrl = state.logWsUrl.replace("/logs", "/stream");
    })
    .catch(() => { /* 설정 조회 실패 시 기본값 유지 */ });
}

/** 신호 11채널 오버레이(지도 좌상단) 접기/펼치기 — 헤더 버튼 클릭 토글. */
function initSignalsOverlay() {
  const overlay = document.getElementById("signals-overlay");
  const toggle = document.getElementById("signals-toggle");
  if (!overlay || !toggle) return;
  const caret = toggle.querySelector(".signals-caret");
  toggle.addEventListener("click", () => {
    const collapsed = overlay.classList.toggle("collapsed");
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    if (caret) caret.textContent = collapsed ? "▸" : "▾";
  });
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

// 배속 프리셋 시퀀스 — −/+ 스테퍼가 이 배열의 이전/다음 항목으로 이동한다.
const SPEED_STEPS = [1, 2, 4, 8, 16, 32, 64];

// Monotonic reset nonce — each ↺ click increments and POSTs {reset: nonce};
// the LIVE runner rebuilds its world when the nonce changes (no sticky state).
let resetNonce = 0;

/** 시뮬 컨트롤(#panel-map 헤더) — 재생/일시중지 토글 + −/+ 배속 스테퍼.
 * 일시중지는 mock.paused만 토글(렌더 루프는 유지), 배속은 일시중지와 무관하게 변경 가능. */
function initSimControls() {
  const playBtn = document.getElementById("playpause-btn");
  const dec = document.getElementById("speed-dec");
  const inc = document.getElementById("speed-inc");
  const val = document.getElementById("speed-val");
  const resetBtn = document.getElementById("reset-btn");
  if (!playBtn || !dec || !inc || !val) return;

  function syncPlay() {
    playBtn.textContent = mock.paused ? "▶" : "⏸";
    playBtn.title = mock.paused ? "재생" : "일시중지";
    playBtn.setAttribute("aria-pressed", mock.paused ? "false" : "true");
  }
  function syncSpeed() {
    const i = SPEED_STEPS.indexOf(mock.timeScale);
    val.textContent = String(mock.timeScale) + "×";
    dec.disabled = i <= 0;
    inc.disabled = i >= SPEED_STEPS.length - 1;
  }
  function step(d) {
    const cur = SPEED_STEPS.indexOf(mock.timeScale);
    const i = cur < 0 ? SPEED_STEPS.indexOf(1) : cur;
    const next = Math.min(SPEED_STEPS.length - 1, Math.max(0, i + d));
    mock.timeScale = SPEED_STEPS[next];
    // Best-effort: also push the new speed to the collector's control channel
    // so the LIVE runner (which polls GET /control) follows the stepper too.
    if (typeof window !== "undefined" && window.D4D_CONFIG) {
      window.D4D_CONFIG.then((cfg) => {
        if (!cfg || !cfg.collectorHttpUrl) return;
        return fetch(cfg.collectorHttpUrl + "/control", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ speed: SPEED_STEPS[next] }),
        });
      }).catch(() => {});
    }
    syncSpeed();
  }
  playBtn.addEventListener("click", () => {
    mock.paused = !mock.paused;
    const paused = mock.paused;
    // Best-effort: also push the paused state to the collector's control
    // channel so the LIVE runner (which polls GET /control) pauses too.
    if (typeof window !== "undefined" && window.D4D_CONFIG) {
      window.D4D_CONFIG.then((cfg) => {
        if (!cfg || !cfg.collectorHttpUrl) return;
        return fetch(cfg.collectorHttpUrl + "/control", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paused: paused }),
        });
      }).catch(() => {});
    }
    syncPlay();
  });
  dec.addEventListener("click", () => step(-1));
  inc.addEventListener("click", () => step(1));
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      resetNonce += 1;
      // Reset the local live view immediately (trail/drone) — active/route/
      // terrainLayer stay; the runner's re-POST /init refreshes them.
      live.trail = [];
      live.drone = null;
      // Reset the mock fallback scenario to its start.
      mock.s = 0; mock.dir = 1; mock.phase = "NORMAL"; mock.phaseT = 0;
      mock.odo = 0; mock.trailProfile = [];
      mock.pos = { x: PATH[0].x, y: PATH[0].y };
      mock._threatened = false; mock._assessed = false; mock._responded = false;
      // Best-effort: push the reset nonce to the collector's control channel
      // so the LIVE runner (which polls GET /control) replays from the start.
      if (typeof window !== "undefined" && window.D4D_CONFIG) {
        window.D4D_CONFIG.then((cfg) => {
          if (!cfg || !cfg.collectorHttpUrl) return;
          return fetch(cfg.collectorHttpUrl + "/control", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reset: resetNonce }),
          });
        }).catch(() => {});
      }
    });
  }
  syncPlay();
  syncSpeed();
}

function init() {
  renderDecisionFlow();
  renderDecisionHistory();
  startMockSim();
  initTabs();
  initSimControls();
  initSignalsOverlay();
  initDebugMode();

  // /config 로 기본 URL 확정 후 자동 연결(수집기 미기동이면 backoff 재연결).
  loadConfig().then(() => {
    connectStream();
  });
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}
