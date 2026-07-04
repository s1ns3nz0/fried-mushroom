"use strict";

// D4D 관측소(GCS) 탭 — METT+TC mission_brief 빌더 + 온보드 파이프라인 실행기.
// GCS layer 01(src/gcs) 미구현 대체 UI: 운용자가 임무 브리핑을 조립해
// POST /gcs/run 으로 전달한다. 판단은 온보드 파이프라인이 수행하고,
// 이 탭은 조립·전달·결과 요약 표시만 담당한다(관측 전용).
//
// 계약:
//   GET  /gcs/scenarios      → [{tag, sortie_id, mission_context}]
//   GET  /gcs/scenario/{tag} → {raw, mission_brief}
//   POST /gcs/run            → {result, log_delivered, correlation_id}
// 폼 ↔ JSON 라운드트립: 편집 → collectBrief() → 미리보기 = 전송 body.

(function () {
  const $ = (id) => document.getElementById(id);

  // 바인딩 상태 — raw 센서 입력 + 기지 id(브리핑 로드 시 원본 id 보존).
  const gcs = {
    raw: null,
    rawTag: null,
    baseIds: { emergency: "base_emergency", alternate: "base_alternate" },
  };

  const DEFAULT_BRIEF = {
    sortie_id: "",
    mission_context: "정찰",
    posture: { watchcon: 4, defcon: 4, infocon: 5 },
    drone_profile: { armament: [], spare_asset_available: false, battery_pct: 100 },
    corridor: {
      waypoints: [{ id: "wp1", lat: 37.5, lon: 127.0, alt_m: 120 }],
      bases: {
        emergency: { id: "base_emergency", lat: 37.49, lon: 127.0, alt_m: 50 },
        alternate: { id: "base_alternate", lat: 37.48, lon: 127.005, alt_m: 50 },
      },
    },
    weights: { stealth: 0.4, survival: 0.35, info_value: 0.2, timeliness: 0.05 },
  };

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

    $("gcs-sortie-id").value = b.sortie_id || "";
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
  }

  function updatePreview() {
    $("gcs-json-preview").textContent = JSON.stringify(collectBrief(), null, 2);
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
    return fetch("/gcs/scenario/" + encodeURIComponent(tag)).then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  /** 프리셋 선택 — 브리핑 폼 채우기 + raw 바인딩. */
  function loadScenario(tag) {
    return fetchScenario(tag)
      .then((data) => {
        fillForm(data.mission_brief || {});
        bindRaw(tag, data.raw || null);
        markActivePreset(tag);
        updatePreview();
        setStatus("프리셋 " + tag + " 로드 완료", "");
      })
      .catch((e) => setStatus("프리셋 로드 실패(" + tag + "): " + e.message, "err"));
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
    return fetch("/gcs/scenarios")
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
    if (!gcs.raw) errs.push("raw 센서 입력 미바인딩(프리셋 또는 raw 선택)");
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
    fetch("/gcs/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw: gcs.raw, mission_brief: brief }),
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
            (data.log_delivered ? " · 로그 전송됨 → 관측 탭" : " · 로그 미전송(수집기 확인)"),
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

    loadScenarios();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
