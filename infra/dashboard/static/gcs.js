"use strict";

// D4D 관측소(GCS) 탭 — METT+TC mission_brief 빌더 + 온보드 파이프라인 실행기.
// GCS layer 01(src/gcs) 이 구현·배선됨(#111): 운용자는 set_mission(지시서 등)을
// 넘겨 실 layer 01 로 브리핑을 조립(assembleFromSetMission)하거나, 폼으로 직접
// 브리핑을 만들어 POST /gcs/run 할 수 있다. 판단은 온보드 파이프라인이 수행한다.
//
// 계약 (로그수집기 :8500 이 서빙 — collectorHttpUrl 기준):
//   GET  /gcs/scenarios       → [{tag, sortie_id, mission_context}]
//   GET  /gcs/scenario/{tag}  → {raw, mission_brief}
//   GET  /gcs/set-missions    → [{tag, sortie_id, mission_context}]   (layer 01 입력)
//   GET  /gcs/set-mission/{tag}→ set_mission 번들
//   POST /gcs/assemble        → {draft_brief, signal_cards, warnings, correlation_id}
//   POST /gcs/run             → {result, log_published, correlation_id}
// 폼 ↔ JSON 라운드트립: 편집 → collectBrief() → 미리보기 = 전송 body.
// assemble→run 시 correlation_id 를 이어주면 조립·사이클 로그가 대시보드에서 연결된다.

(function () {
  const $ = (id) => document.getElementById(id);

  // 바인딩 상태 — raw 센서 입력 + 기지 id(브리핑 로드 시 원본 id 보존).
  const gcs = {
    raw: null,
    rawTag: null,
    baseIds: { emergency: "base_emergency", alternate: "base_alternate" },
    // #111: /gcs/assemble(실 layer 01)이 발급한 상관ID. run 에 이어주면
    // 조립·사이클 로그가 스트림에서 연결된다. 수동 프리셋 로드 시 해제.
    correlationId: null,
  };

  // ── 수집기 API 헬퍼 ─────────────────────────────────────────
  // /gcs/* 는 로그수집기(:8500)가 서빙 — app.js 의 공유 설정 로더(window.D4D_CONFIG)
  // 에서 collectorHttpUrl 을 해석해 브라우저가 수집기에 직접 요청한다(정적 배포 대응).

  const DEFAULT_COLLECTOR_HTTP_URL = "http://localhost:8500";

  function configReady() {
    return typeof window !== "undefined" && window.D4D_CONFIG
      ? window.D4D_CONFIG
      : Promise.resolve(null);
  }

  /** collectorHttpUrl + path 로 fetch — 설정 해석을 기다린 뒤 요청한다. */
  function collectorFetch(path, opts) {
    return configReady()
      .then((cfg) => (cfg && cfg.collectorHttpUrl) || DEFAULT_COLLECTOR_HTTP_URL)
      .then((base) => fetch(base + path, opts));
  }

  /**
   * #111: set_mission 태그 → 실 layer 01 조립.
   * GET /gcs/set-mission/{tag} → POST /gcs/assemble.
   * 반환 {draft_brief, signal_cards, warnings, correlation_id}.
   * draft_brief 는 6-필드 mission_brief 이므로 그대로 /gcs/run 에 투입 가능
   * (correlation_id 를 함께 넘기면 조립·사이클 로그가 연결됨).
   */
  function assembleFromSetMission(tag) {
    let enemyTracks = null;
    return collectorFetch("/gcs/set-mission/" + encodeURIComponent(tag))
      .then((r) => {
        if (!r.ok) throw new Error("set_mission 로드 실패: " + tag);
        return r.json();
      })
      .then((setMission) => {
        // 번들의 enemy_tracks(E 요소)를 조립 결과에 실어 폼 E 테이블 프리필에 쓴다.
        enemyTracks = Array.isArray(setMission.enemy_tracks) ? setMission.enemy_tracks : null;
        return collectorFetch("/gcs/assemble", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ set_mission: setMission }),
        });
      })
      .then((r) => {
        if (!r.ok) throw new Error("assemble 실패");
        return r.json();
      })
      .then((body) => ({ ...body, enemy_tracks: enemyTracks }));
  }
  // 외부(향후 리뷰 패널 UI)에서 참조 가능하도록 노출.
  if (typeof window !== "undefined") window.assembleFromSetMission = assembleFromSetMission;

  const DEFAULT_BRIEF = {
    sortie_id: "HWAJINPO-0705-01",
    mission_context: "정찰",
    posture: { watchcon: 4, defcon: 4, infocon: 5 },
    drone_profile: { armament: [], spare_asset_available: false, battery_pct: 100 },
    corridor: {
      waypoints: [
        { id: "lp", lat: 38.25675, lon: 128.42720, alt_m: 120 },
        { id: "wp1", lat: 38.26620, lon: 128.43304, alt_m: 120 },
        { id: "wp2", lat: 38.27344, lon: 128.44760, alt_m: 120 },
        { id: "obj", lat: 38.27990, lon: 128.45080, alt_m: 120 },
      ],
      bases: {
        emergency: { id: "base_emergency", lat: 38.25370, lon: 128.42600, alt_m: 50 },
        alternate: { id: "base_alternate", lat: 38.25440, lon: 128.42800, alt_m: 50 },
      },
    },
    weights: { stealth: 0.4, survival: 0.35, info_value: 0.2, timeliness: 0.05 },
  };

  // E · 적 트랙 예시(set_mission_recon.json 과 동일) — 프리셋 미로드 시 프리필.
  const EXAMPLE_ENEMY_TRACKS = [
    { id: "E1", kind: "T3", lat: 38.26426, lon: 128.45712, radius_m: 240, confidence: 0.9 },
    { id: "E2", kind: "T3", lat: 38.26732, lon: 128.43480, radius_m: 260, confidence: 0.85 },
  ];
  const ENEMY_KINDS = ["T1", "T2", "T3", "T4", "T5", "T6", "T7"];

  // 상황도 고정 위성 프레임(화진포, vizsim mission_brief_hwajinpo.json frame과 동일) —
  // 관측 탭 위성 지도와 좌표계를 1:1 정합시키기 위해 폼-유래 bbox 대신 이 고정 프레임을 쓴다.
  const SITU_FRAME = { latMin: 38.251, latMax: 38.285, lonMin: 128.398, lonMax: 128.478 };

  // ── 폼 유틸 ─────────────────────────────────────────────────

  function numVal(input, fallback) {
    const v = Number(input && input.value);
    return Number.isFinite(v) && input.value !== "" ? v : fallback;
  }

  function setNum(id, value, fallback) {
    const v = Number(value);
    $(id).value = Number.isFinite(v) ? v : fallback;
  }

  /** select 값 설정 — 목록에 없는 값이면 옵션을 추가해 손실 없이 라운드트립. */
  function setSelect(sel, value, fallback) {
    const want = value != null ? String(value) : fallback;
    sel.value = want;
    if (sel.value !== want) {
      const opt = document.createElement("option");
      opt.value = want;
      opt.textContent = want;
      sel.appendChild(opt);
      sel.value = want;
    }
  }

  function setStatus(msg, cls) {
    const node = $("gcs-run-status");
    if (!node) return;
    node.textContent = msg;
    node.className = "gcs-status" + (cls ? " " + cls : "");
    node.title = msg;
  }

  // ── 웨이포인트 테이블 ───────────────────────────────────────

  function addWpRow(wp) {
    const tbody = $("gcs-wp-body");
    const tr = document.createElement("tr");

    const mkCell = (cls, type, value) => {
      const td = document.createElement("td");
      const input = document.createElement("input");
      input.type = type;
      input.className = cls;
      if (type === "number") input.step = "any";
      input.value = value;
      td.appendChild(input);
      tr.appendChild(td);
    };

    mkCell("wp-id", "text", wp && wp.id != null ? wp.id : "wp" + (tbody.childElementCount + 1));
    mkCell("wp-lat", "number", wp && wp.lat != null ? wp.lat : 37.5);
    mkCell("wp-lon", "number", wp && wp.lon != null ? wp.lon : 127.0);
    mkCell("wp-alt", "number", wp && wp.alt_m != null ? wp.alt_m : 120);

    const td = document.createElement("td");
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "gcs-btn gcs-wp-remove";
    rm.textContent = "−";
    rm.title = "행 삭제";
    rm.addEventListener("click", () => {
      tr.remove();
      updatePreview();
    });
    td.appendChild(rm);
    tr.appendChild(td);

    tbody.appendChild(tr);
  }

  // ── E · 적 트랙 테이블 ──────────────────────────────────────

  function addEnemyRow(trk) {
    const tbody = $("gcs-enemy-body");
    const tr = document.createElement("tr");

    const mkCell = (cls, type, value) => {
      const td = document.createElement("td");
      const input = document.createElement("input");
      input.type = type;
      input.className = cls;
      if (type === "number") input.step = "any";
      input.value = value;
      td.appendChild(input);
      tr.appendChild(td);
    };

    mkCell("et-id", "text", trk && trk.id != null ? trk.id : "trk-" + (tbody.childElementCount + 1));

    const tdKind = document.createElement("td");
    const kindSel = document.createElement("select");
    kindSel.className = "et-kind";
    ENEMY_KINDS.forEach((k) => {
      const opt = document.createElement("option");
      opt.value = k;
      opt.textContent = k;
      kindSel.appendChild(opt);
    });
    setSelect(kindSel, trk && trk.kind != null ? trk.kind : null, "T3");
    tdKind.appendChild(kindSel);
    tr.appendChild(tdKind);

    mkCell("et-lat", "number", trk && trk.lat != null ? trk.lat : 37.5);
    mkCell("et-lon", "number", trk && trk.lon != null ? trk.lon : 127.0);
    mkCell("et-radius", "number", trk && trk.radius_m != null ? trk.radius_m : 200);
    mkCell("et-conf", "number", trk && trk.confidence != null ? trk.confidence : 0.8);

    const td = document.createElement("td");
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "gcs-btn gcs-wp-remove";
    rm.textContent = "−";
    rm.title = "행 삭제";
    rm.addEventListener("click", () => {
      tr.remove();
      updatePreview();
    });
    td.appendChild(rm);
    tr.appendChild(td);

    tbody.appendChild(tr);
  }

  function collectEnemyTracks() {
    return Array.from(document.querySelectorAll("#gcs-enemy-body tr")).map((tr, i) => ({
      id: tr.querySelector(".et-id").value.trim() || "trk-" + (i + 1),
      kind: tr.querySelector(".et-kind").value,
      lat: numVal(tr.querySelector(".et-lat"), 0),
      lon: numVal(tr.querySelector(".et-lon"), 0),
      radius_m: numVal(tr.querySelector(".et-radius"), 0),
      confidence: numVal(tr.querySelector(".et-conf"), 0),
    }));
  }

  /** E 테이블 채우기 — 트랙이 없으면 예시 2건으로 프리필(빈 상태 금지). */
  function fillEnemyTracks(tracks) {
    $("gcs-enemy-body").textContent = "";
    const list = Array.isArray(tracks) && tracks.length ? tracks : EXAMPLE_ENEMY_TRACKS;
    list.forEach(addEnemyRow);
  }

  // ── 폼 → mission_brief 조립 / mission_brief → 폼 채우기 ─────

  function collectBrief() {
    const waypoints = Array.from(document.querySelectorAll("#gcs-wp-body tr")).map((tr, i) => ({
      id: tr.querySelector(".wp-id").value.trim() || "wp" + (i + 1),
      lat: numVal(tr.querySelector(".wp-lat"), 0),
      lon: numVal(tr.querySelector(".wp-lon"), 0),
      alt_m: numVal(tr.querySelector(".wp-alt"), 0),
    }));
    const armament = $("gcs-armament").value
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    return {
      sortie_id: $("gcs-sortie-id").value.trim(),
      mission_context: $("gcs-mission-context").value,
      posture: {
        watchcon: numVal($("gcs-watchcon"), 4),
        defcon: numVal($("gcs-defcon"), 4),
        infocon: numVal($("gcs-infocon"), 5),
      },
      drone_profile: {
        armament,
        spare_asset_available: $("gcs-spare-asset").checked,
        battery_pct: numVal($("gcs-battery-pct"), 100),
      },
      corridor: {
        waypoints,
        bases: {
          emergency: {
            id: gcs.baseIds.emergency,
            lat: numVal($("gcs-base-em-lat"), 0),
            lon: numVal($("gcs-base-em-lon"), 0),
            alt_m: numVal($("gcs-base-em-alt"), 0),
          },
          alternate: {
            id: gcs.baseIds.alternate,
            lat: numVal($("gcs-base-al-lat"), 0),
            lon: numVal($("gcs-base-al-lon"), 0),
            alt_m: numVal($("gcs-base-al-alt"), 0),
          },
        },
      },
      weights: {
        stealth: numVal($("gcs-w-stealth"), 0),
        survival: numVal($("gcs-w-survival"), 0),
        info_value: numVal($("gcs-w-info"), 0),
        timeliness: numVal($("gcs-w-time"), 0),
      },
    };
  }

  function fillBase(prefix, base, fallback, key) {
    const b = base || fallback;
    gcs.baseIds[key] = b.id != null ? b.id : fallback.id;
    setNum("gcs-base-" + prefix + "-lat", b.lat, fallback.lat);
    setNum("gcs-base-" + prefix + "-lon", b.lon, fallback.lon);
    setNum("gcs-base-" + prefix + "-alt", b.alt_m, fallback.alt_m);
  }

  function fillForm(brief) {
    const b = brief || {};
    const posture = b.posture || {};
    const dp = b.drone_profile || {};
    const corridor = b.corridor || {};
    const bases = corridor.bases || {};
    const weights = b.weights || {};
    const D = DEFAULT_BRIEF;

    $("gcs-sortie-id").value = b.sortie_id || D.sortie_id;
    setSelect($("gcs-mission-context"), b.mission_context, D.mission_context);
    setNum("gcs-watchcon", posture.watchcon, D.posture.watchcon);
    setNum("gcs-defcon", posture.defcon, D.posture.defcon);
    setNum("gcs-infocon", posture.infocon, D.posture.infocon);
    setNum("gcs-battery-pct", dp.battery_pct, D.drone_profile.battery_pct);
    $("gcs-spare-asset").checked = !!dp.spare_asset_available;
    $("gcs-armament").value = Array.isArray(dp.armament) ? dp.armament.join(", ") : "";

    $("gcs-wp-body").textContent = "";
    const wps = Array.isArray(corridor.waypoints) && corridor.waypoints.length
      ? corridor.waypoints
      : D.corridor.waypoints;
    wps.forEach(addWpRow);
    fillBase("em", bases.emergency, D.corridor.bases.emergency, "emergency");
    fillBase("al", bases.alternate, D.corridor.bases.alternate, "alternate");

    setNum("gcs-w-stealth", weights.stealth, D.weights.stealth);
    setNum("gcs-w-survival", weights.survival, D.weights.survival);
    setNum("gcs-w-info", weights.info_value, D.weights.info_value);
    setNum("gcs-w-time", weights.timeliness, D.weights.timeliness);

    fillEnemyTracks(b.enemy_tracks);
  }

  /**
   * 미리보기 전용 JSON — mission_brief + enemy_tracks(E) + mettc(T_time/C 참고 필드).
   * /gcs/run 전송 body 는 collectBrief()(+raw) 그대로이며 이 확장 필드는 포함하지 않는다.
   */
  function collectPreview() {
    const preview = collectBrief();
    preview.enemy_tracks = collectEnemyTracks();
    preview.mettc = {
      T_time: {
        endurance_s: numVal($("gcs-endurance-s"), null),
        eta_goal_s: numVal($("gcs-eta-goal-s"), null),
      },
      C: {
        no_fly_zones: $("gcs-no-fly-zones").value
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        civil_sensitivity: $("gcs-civil-sensitivity").value,
      },
    };
    return preview;
  }

  function updatePreview() {
    $("gcs-json-preview").textContent = JSON.stringify(collectPreview(), null, 2);
    renderBriefSummary();
    drawSituMap();
  }

  // ── 우: UAV 임무 brief 요약(읽기 좋은 형태) ─────────────────
  // collectBrief() 결과(온보드 전송 body)를 사람이 읽기 좋은 요약으로 렌더.

  function renderBriefSummary() {
    const host = $("gcs-brief-summary");
    if (!host) return;
    const b = collectBrief();
    const p = b.posture || {};
    const dp = b.drone_profile || {};
    const co = b.corridor || {};
    const w = b.weights || {};
    const arms = Array.isArray(dp.armament) && dp.armament.length ? dp.armament.join(", ") : "없음";
    const nWp = Array.isArray(co.waypoints) ? co.waypoints.length : 0;
    const rows = [
      ["출격번호", b.sortie_id || "—"],
      ["임무 유형", b.mission_context || "—"],
      ["태세", "WATCHCON " + p.watchcon + " · DEFCON " + p.defcon + " · INFOCON " + p.infocon],
      ["기체 제원", "배터리 " + dp.battery_pct + "% · 무장 " + arms + " · 예비기 " + (dp.spare_asset_available ? "가용" : "없음")],
      ["회랑", "웨이포인트 " + nWp + "개 · 기지 emergency/alternate"],
      ["가중치", "S " + w.stealth + " · 생존 " + w.survival + " · 정보 " + w.info_value + " · 적시 " + w.timeliness],
    ];
    host.textContent = "";
    rows.forEach(([k, v]) => {
      const row = document.createElement("div");
      row.className = "gcs-sum-row";
      const key = document.createElement("span");
      key.className = "gcs-sum-key";
      key.textContent = k;
      const val = document.createElement("span");
      val.className = "gcs-sum-val";
      val.textContent = v;
      row.append(key, val);
      host.appendChild(row);
    });
  }

  // ── 좌: 피아 상황도 (상황도 이미지 배경 + 아군 경로/기지 + 적 트랙) ───
  // 폼의 waypoints/bases + collectEnemyTracks() 를 lat/lon 바운딩박스로
  // 정규화해 캔버스에 그린다(발표용 대략 정합). 폼 변경 시 갱신.

  let situMapImg = null;
  (function loadSituMapImg() {
    const im = new Image();
    im.onload = () => { situMapImg = im; drawSituMap(); };
    im.onerror = () => { situMapImg = null; };
    im.src = "/static/assets/situmap.jpg";
  })();

  function sizeCanvas(cv) {
    const w = cv.clientWidth, h = cv.clientHeight;
    if (w && h && (cv.width !== w || cv.height !== h)) {
      cv.width = w;
      cv.height = h;
    }
  }

  /** 적 트랙 lat/lon 추출 — pos.lat/lon 또는 flat lat/lon 모두 수용(관측 탭/vizsim과 동일). */
  function trackLatLon(e) {
    const pos = e && e.pos;
    if (pos && Number.isFinite(pos.lat) && Number.isFinite(pos.lon)) return [pos.lat, pos.lon];
    return [e ? e.lat : undefined, e ? e.lon : undefined];
  }

  function drawSituMap() {
    const cv = $("gcs-situ-canvas");
    if (!cv || !cv.getContext) return;
    if (cv.clientWidth === 0) return; // 탭 숨김/미표시 — 스킵.
    sizeCanvas(cv);
    const ctx = cv.getContext("2d");
    const W = cv.width, H = cv.height;
    ctx.clearRect(0, 0, W, H);

    // 배경: 상황도 이미지(있으면) + 어두운 스크림, 없으면 단색.
    if (situMapImg) {
      ctx.drawImage(situMapImg, 0, 0, W, H);
      ctx.fillStyle = "rgba(6,10,16,0.44)";
      ctx.fillRect(0, 0, W, H);
    } else {
      ctx.fillStyle = "#10131a";
      ctx.fillRect(0, 0, W, H);
    }

    const b = collectBrief();
    const co = b.corridor || {};
    const wps = Array.isArray(co.waypoints) ? co.waypoints : [];
    const bases = co.bases || {};
    const baseList = [bases.emergency, bases.alternate].filter(Boolean);
    const enemies = collectEnemyTracks();

    const isPt = (la, lo) => Number.isFinite(la) && Number.isFinite(lo) && (la !== 0 || lo !== 0);
    const all = [];
    wps.forEach((p) => { if (isPt(p.lat, p.lon)) all.push([p.lat, p.lon]); });
    baseList.forEach((p) => { if (isPt(p.lat, p.lon)) all.push([p.lat, p.lon]); });
    enemies.forEach((e) => { const [la, lo] = trackLatLon(e); if (isPt(la, lo)) all.push([la, lo]); });
    if (!all.length) return;

    // 관측 탭(위성 프레임) 과 동일한 고정 프레임으로 정규화 — 폼-유래 bbox 대신 SITU_FRAME 사용.
    const { latMin, latMax, lonMin, lonMax } = SITU_FRAME;
    const dLat = latMax - latMin, dLon = lonMax - lonMin;
    const proj = (la, lo) => [
      ((lo - lonMin) / dLon) * W,
      ((latMax - la) / dLat) * H, // 북쪽이 위.
    ];
    // 미터→px 근사(적 탐지반경 원). lon 방향 스케일 사용.
    const midLat = (latMin + latMax) / 2;
    const mPerDegLon = 111320 * Math.cos((midLat * Math.PI) / 180) || 111320;
    const pxPerM = W / dLon / mPerDegLon;

    // 아군 공격루트(waypoints, 출발지→목표) — 굵은 청색 화살표(글로우+본선).
    const routePts = wps.filter((p) => isPt(p.lat, p.lon)).map((p) => proj(p.lat, p.lon));
    if (routePts.length > 1) {
      ctx.save();
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.beginPath();
      routePts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.strokeStyle = "rgba(59,156,255,0.35)"; ctx.lineWidth = 9; ctx.stroke();
      ctx.beginPath();
      routePts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.strokeStyle = "#3B9CFF"; ctx.lineWidth = 3; ctx.stroke();
      ctx.restore();
      const [px, py] = routePts[routePts.length - 2];
      const [tx, ty] = routePts[routePts.length - 1];
      drawArrowHead(ctx, px, py, tx, ty, "#3B9CFF");
    }

    // 웨이포인트 점 + 출발지(첫 wp) 아군 심볼 + 목표(마지막 wp) 목표 심볼.
    routePts.forEach(([x, y], i) => {
      if (i === 0) {
        drawFriendlyMarker(ctx, x, y); // 아군 출발(LP) — 청색 원.
      } else if (i === routePts.length - 1) {
        drawTargetMarker(ctx, x, y); // 목표(마지막 wp) — 청색 조준 심볼.
      } else {
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fillStyle = "#0D0D0F"; ctx.fill();
        ctx.strokeStyle = "#3B9CFF"; ctx.lineWidth = 1.5; ctx.stroke();
      }
    });

    // 기지(청색 diamond, 소형) — 흰/검 외곽선으로 대비.
    baseList.forEach((p) => {
      if (!isPt(p.lat, p.lon)) return;
      const [x, y] = proj(p.lat, p.lon);
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = "#7FC7FF";
      ctx.fillRect(-4, -4, 8, 8);
      ctx.strokeStyle = "#FFFFFF"; ctx.lineWidth = 1.4; ctx.strokeRect(-4, -4, 8, 8);
      ctx.strokeStyle = "rgba(0,0,0,0.65)"; ctx.lineWidth = 0.8; ctx.strokeRect(-4, -4, 8, 8);
      ctx.restore();
    });

    // 적 트랙 — 탐지반경 원(붉은 점선) + 붉은 적대 마커(다이아몬드) + 짧은 라벨.
    ctx.save();
    ctx.font = "700 10px ui-monospace, Menlo, monospace";
    ctx.textAlign = "left";
    enemies.forEach((e) => {
      const [la, lo] = trackLatLon(e);
      if (!isPt(la, lo)) return;
      const [x, y] = proj(la, lo);
      const r = Number(e.radius_m) > 0 ? e.radius_m * pxPerM : 0;
      if (r > 2) {
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.setLineDash([5, 4]);
        ctx.strokeStyle = "rgba(240,85,93,0.7)"; ctx.lineWidth = 1.4; ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "rgba(240,85,93,0.1)"; ctx.fill();
      }
      drawEnemyMarker(ctx, x, y);
      const label = (e.kind || "E") + " " + (e.id || "");
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(0,0,0,0.85)";
      ctx.strokeText(label, x + 11, y + 3);
      ctx.fillStyle = "#FFD9DA";
      ctx.fillText(label, x + 11, y + 3);
    });
    ctx.restore();
  }

  /** 화살표 머리 — (x1,y1)→(x2,y2) 방향으로 끝점(x2,y2)에 그림. */
  function drawArrowHead(ctx, x1, y1, x2, y2, color) {
    const ang = Math.atan2(y2 - y1, x2 - x1);
    const s = 13;
    ctx.save();
    ctx.translate(x2, y2);
    ctx.rotate(ang);
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(-s, -s * 0.55);
    ctx.lineTo(-s, s * 0.55);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = "rgba(0,0,0,0.6)";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.restore();
  }

  /** 아군 출발(LP) 심볼 — 청색 원 + 글로우 + 흰/검 외곽선. */
  function drawFriendlyMarker(ctx, x, y) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, 12, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(59,156,255,0.25)"; ctx.fill();
    ctx.beginPath();
    ctx.arc(x, y, 8, 0, Math.PI * 2);
    ctx.fillStyle = "#3B9CFF"; ctx.fill();
    ctx.strokeStyle = "#FFFFFF"; ctx.lineWidth = 2; ctx.stroke();
    ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.lineWidth = 1; ctx.stroke();
    ctx.restore();
  }

  /** 목표(마지막 wp) 심볼 — 청색 조준(사각+십자) + 글로우. */
  function drawTargetMarker(ctx, x, y) {
    const s = 9;
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, 13, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(59,156,255,0.2)"; ctx.fill();
    ctx.strokeStyle = "#3B9CFF"; ctx.lineWidth = 2; ctx.strokeRect(x - s, y - s, s * 2, s * 2);
    ctx.beginPath();
    ctx.moveTo(x - s - 4, y); ctx.lineTo(x + s + 4, y);
    ctx.moveTo(x, y - s - 4); ctx.lineTo(x, y + s + 4);
    ctx.strokeStyle = "#FFFFFF"; ctx.lineWidth = 1; ctx.stroke();
    ctx.restore();
  }

  /** 적대 마커 — 붉은 다이아몬드 + 흰/검 이중 외곽선(위성 배경 대비). */
  function drawEnemyMarker(ctx, x, y) {
    const s = 9;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(Math.PI / 4);
    ctx.fillStyle = "#F0555D"; ctx.fillRect(-s, -s, s * 2, s * 2);
    ctx.strokeStyle = "#FFFFFF"; ctx.lineWidth = 2; ctx.strokeRect(-s, -s, s * 2, s * 2);
    ctx.strokeStyle = "rgba(0,0,0,0.65)"; ctx.lineWidth = 1; ctx.strokeRect(-s, -s, s * 2, s * 2);
    ctx.restore();
  }

  // ── 시나리오 프리셋 / raw 바인딩 ─────────────────────────────

  function markActivePreset(tag) {
    document.querySelectorAll(".gcs-preset").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tag === tag);
    });
  }

  function bindRaw(tag, raw) {
    gcs.raw = raw;
    gcs.rawTag = tag;
    const seq = raw && raw.seq != null ? " (seq=" + raw.seq + ")" : "";
    $("gcs-raw-bound").textContent = "raw: raw_" + tag + ".json" + seq;
    const sel = $("gcs-raw-select");
    if (sel && sel.value !== tag) sel.value = tag;
  }

  function fetchScenario(tag) {
    return collectorFetch("/gcs/scenario/" + encodeURIComponent(tag)).then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  /** 프리셋 선택 — 브리핑 폼 채우기 + raw 바인딩. (수동 브리핑 → 01 조립 상관ID 해제) */
  function loadScenario(tag) {
    return fetchScenario(tag)
      .then((data) => {
        fillForm(data.mission_brief || {});
        bindRaw(tag, data.raw || null);
        gcs.correlationId = null;
        markActivePreset(tag);
        updatePreview();
        setStatus("프리셋 " + tag + " 로드 완료", "");
      })
      .catch((e) => setStatus("프리셋 로드 실패(" + tag + "): " + e.message, "err"));
  }

  /** #111: 지시서(set_mission) 프리셋 → 실 layer 01 조립 → 폼 채움 + 상관ID 보관. */
  function loadFromLayer01(tag) {
    setStatus("layer 01 조립 중… (" + tag + ")", "");
    return assembleFromSetMission(tag)
      .then((body) => {
        fillForm(body.draft_brief || {});
        // set_mission 번들의 enemy_tracks 로 E 테이블 프리필(없으면 예시 유지).
        fillEnemyTracks(body.enemy_tracks);
        gcs.correlationId = body.correlation_id || null;
        markActivePreset("01:" + tag);
        updatePreview();
        const cards = (body.signal_cards || []).map((c) => c.source_phrase).join(", ");
        const nWarn = (body.warnings || []).length;
        let msg = "01 조립 완료 · 신호카드 [" + (cards || "없음") + "] · 경고 " + nWarn;
        if (!gcs.raw) msg += " — raw 미선택: raw 선택기에서 지정 후 실행";
        setStatus(msg, nWarn ? "err" : "ok");
      })
      .catch((e) => setStatus("layer 01 조립 실패(" + tag + "): " + e.message, "err"));
  }

  /** #111: set_mission 프리셋 목록을 시나리오 패널에 렌더 (실 layer 01 경로). */
  function loadSetMissions() {
    return collectorFetch("/gcs/set-missions")
      .then((r) => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then((items) => {
        if (!items || !items.length) return;
        const list = $("gcs-scenario-list");
        const head = document.createElement("div");
        head.className = "gcs-preset-head";
        head.textContent = "지시서 → layer 01 조립";
        list.appendChild(head);
        items.forEach((it) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "gcs-preset gcs-preset-01";
          btn.dataset.tag = "01:" + it.tag;
          const tagEl = document.createElement("span");
          tagEl.className = "gcs-preset-tag";
          tagEl.textContent = "01·" + String(it.tag).toUpperCase();
          const meta = document.createElement("span");
          meta.className = "gcs-preset-meta";
          meta.textContent = (it.sortie_id || "—") + " · " + (it.mission_context || "—");
          btn.append(tagEl, meta);
          btn.addEventListener("click", () => loadFromLayer01(it.tag));
          list.appendChild(btn);
        });
      })
      .catch((e) => setStatus("set_mission 목록 조회 실패: " + e.message, "err"));
  }

  /** raw 선택기 변경 — raw 만 교체(브리핑 폼은 유지). */
  function loadRawOnly(tag) {
    return fetchScenario(tag)
      .then((data) => {
        bindRaw(tag, data.raw || null);
        setStatus("raw 센서 입력 → raw_" + tag + ".json", "");
      })
      .catch((e) => setStatus("raw 로드 실패(" + tag + "): " + e.message, "err"));
  }

  function loadScenarios() {
    return collectorFetch("/gcs/scenarios")
      .then((r) => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then((items) => {
        const list = $("gcs-scenario-list");
        const sel = $("gcs-raw-select");
        list.textContent = "";
        sel.textContent = "";
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "— 선택 —";
        sel.appendChild(placeholder);
        (items || []).forEach((it) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "gcs-preset";
          btn.dataset.tag = it.tag;
          const tagEl = document.createElement("span");
          tagEl.className = "gcs-preset-tag";
          tagEl.textContent = String(it.tag).toUpperCase();
          const meta = document.createElement("span");
          meta.className = "gcs-preset-meta";
          meta.textContent = (it.sortie_id || "—") + " · " + (it.mission_context || "—");
          btn.append(tagEl, meta);
          btn.addEventListener("click", () => loadScenario(it.tag));
          list.appendChild(btn);

          const opt = document.createElement("option");
          opt.value = it.tag;
          opt.textContent = "raw_" + it.tag + ".json";
          sel.appendChild(opt);
        });
      })
      .catch((e) => setStatus("시나리오 목록 조회 실패: " + e.message, "err"));
  }

  // ── 검증 / 실행 ─────────────────────────────────────────────

  function validateBrief(brief) {
    const errs = [];
    if (!brief.sortie_id) errs.push("sortie_id 필수");
    ["watchcon", "defcon", "infocon"].forEach((k) => {
      const v = brief.posture[k];
      if (!(v >= 1 && v <= 5)) errs.push(k + " 1..5");
    });
    const bp = brief.drone_profile.battery_pct;
    if (!(bp >= 0 && bp <= 100)) errs.push("battery_pct 0..100");
    if (brief.corridor.waypoints.length < 1) errs.push("waypoint 1개 이상 필요");
    Object.keys(brief.weights).forEach((k) => {
      const v = brief.weights[k];
      if (!(v >= 0 && v <= 1)) errs.push("weights." + k + " 0..1");
    });
    return errs;
  }

  /** 임무 전달 — POST /gcs/run 후 요약 표시, 성공 시 관측 탭으로 자동 전환. */
  function runPipeline() {
    const brief = collectBrief();
    const errs = validateBrief(brief);
    if (errs.length) {
      setStatus("검증 실패: " + errs.join(" · "), "err");
      return;
    }
    setStatus("파이프라인 실행 중…", "");
    $("gcs-run").disabled = true;
    collectorFetch("/gcs/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        raw: gcs.raw,
        mission_brief: brief,
        // 01 조립을 거친 브리핑이면 상관ID 를 이어 조립·사이클 로그를 연결(#111).
        ...(gcs.correlationId ? { correlation_id: gcs.correlationId } : {}),
      }),
    })
      .then((r) => r.json().then((data) => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) throw new Error(data && data.detail ? String(data.detail) : "실행 실패");
        const res = data.result || {};
        const primary = res.threat && res.threat.primary
          ? res.threat.primary.threat_event
          : "없음";
        const cands = (res.risk && res.risk.candidates) || [];
        let rac = (res.risk && res.risk.ambient_rac) || "—";
        if (cands.length) {
          const top = cands.reduce((a, b) => {
            const ra = a && a.priority_rank != null ? a.priority_rank : Infinity;
            const rb = b && b.priority_rank != null ? b.priority_rank : Infinity;
            return ra <= rb ? a : b;
          });
          if (top && top.rac != null) rac = top.rac;
        }
        const action = (res.flight_plan && res.flight_plan.flight_action) ||
          (res.response && res.response.flight_action) || "—";
        setStatus(
          "[" + data.correlation_id + "] primary=" + primary + " · RAC=" + rac +
            " · flight_action=" + action +
            (data.log_published ? " · 로그 발행됨 → 관측 탭" : " · 로그 미발행(수집기 확인)"),
          "ok"
        );
        // 요약 확인 여유 후 관측 탭으로 전환(시스템 로그에 사이클 로그가 흐른다).
        setTimeout(() => {
          if (typeof switchTab === "function") switchTab("observation");
        }, 1200);
      })
      .catch((e) => setStatus("실행 실패: " + e.message, "err"))
      .finally(() => {
        $("gcs-run").disabled = false;
      });
  }

  // ── 확인 → mission_brief 세팅 완료 모달 ─────────────────────

  function openConfirmModal() {
    const modal = $("gcs-modal");
    if (!modal) return;
    $("gcs-modal-json").textContent = JSON.stringify(collectBrief(), null, 2);
    modal.hidden = false;
  }

  function closeConfirmModal() {
    const modal = $("gcs-modal");
    if (modal) modal.hidden = true;
  }

  function initConfirmModal() {
    const modal = $("gcs-modal");
    if (!modal) return;
    $("gcs-confirm").addEventListener("click", openConfirmModal);
    $("gcs-modal-close").addEventListener("click", closeConfirmModal);
    $("gcs-modal-backdrop").addEventListener("click", closeConfirmModal);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal.hidden) closeConfirmModal();
    });
  }

  // ── 발표 진행 마법사 — 좌(상황도)→중(폼)→우(brief)→확인 ──────
  // 켜면 클릭할 때마다 다음 섹션으로 진행하며 현재 섹션을 점선 강조·나머지 dim.
  // (관측 탭 결정모델 마법사 .wiz-active/.wiz-dim·전역 클릭 진행 패턴 참고.)

  const PRESENT_STEPS = ["gcs-situ", "gcs-editor", "gcs-brief"];
  const present = { on: false, step: 0 };

  function renderPresent() {
    PRESENT_STEPS.forEach((id, i) => {
      const el = $(id);
      if (!el) return;
      el.classList.toggle("gcs-wiz-active", i === present.step);
      el.classList.toggle("gcs-wiz-dim", i !== present.step);
    });
  }

  function clearPresent() {
    PRESENT_STEPS.forEach((id) => {
      const el = $(id);
      if (el) el.classList.remove("gcs-wiz-active", "gcs-wiz-dim");
    });
  }

  function startPresent() {
    present.on = true;
    present.step = 0;
    const t = $("gcs-present-toggle");
    t.classList.add("active");
    t.setAttribute("aria-pressed", "true");
    renderPresent();
    setStatus("발표 진행: 화면을 클릭하면 다음 섹션으로 →", "");
  }

  function endPresent() {
    present.on = false;
    const t = $("gcs-present-toggle");
    t.classList.remove("active");
    t.setAttribute("aria-pressed", "false");
    clearPresent();
  }

  function advancePresent() {
    present.step++;
    if (present.step > PRESENT_STEPS.length - 1) {
      openConfirmModal();
      setStatus("세팅 완료", "ok");
      endPresent();
    } else {
      renderPresent();
    }
  }

  function initPresent() {
    const toggle = $("gcs-present-toggle");
    if (!toggle) return;
    toggle.addEventListener("click", () => {
      if (present.on) endPresent();
      else startPresent();
    });
    // 전역 클릭 진행 — 진행 모드 ON + GCS 뷰 표시 중일 때만.
    document.addEventListener("click", (e) => {
      if (!present.on) return;
      if (e.target.closest("#gcs-present-toggle")) return; // 토글 클릭은 제외.
      if (e.target.closest("#gcs-modal")) return; // 모달 내부 클릭 제외.
      const view = document.getElementById("view-gcs");
      if (view && view.hidden) return;
      advancePresent();
    });
  }

  // ── 진입점 ──────────────────────────────────────────────────

  function init() {
    if (!$("gcs-form")) return;
    fillForm(DEFAULT_BRIEF);
    updatePreview();

    $("gcs-form").addEventListener("input", updatePreview);
    $("gcs-form").addEventListener("change", updatePreview);
    $("gcs-form").addEventListener("submit", (e) => e.preventDefault());
    $("gcs-wp-add").addEventListener("click", () => {
      addWpRow(null);
      updatePreview();
    });
    $("gcs-enemy-add").addEventListener("click", () => {
      addEnemyRow(null);
      updatePreview();
    });
    $("gcs-reset").addEventListener("click", () => {
      fillForm(DEFAULT_BRIEF);
      markActivePreset(null);
      updatePreview();
      setStatus("초기화됨", "");
    });
    $("gcs-validate").addEventListener("click", () => {
      const errs = validateBrief(collectBrief());
      setStatus(errs.length ? "검증 실패: " + errs.join(" · ") : "검증 통과", errs.length ? "err" : "ok");
    });
    $("gcs-run").addEventListener("click", runPipeline);
    $("gcs-raw-select").addEventListener("change", (e) => {
      if (e.target.value) loadRawOnly(e.target.value);
    });

    initConfirmModal();
    initPresent();
    window.addEventListener("resize", drawSituMap);

    loadScenarios().then(loadSetMissions);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
