"use strict";

/*
 * D4D 대시보드 — 지형/시야각/고도 순수 렌더 모듈.
 * test-board(D4DRender)에서 이식. DOM 상태·WS 접근 없이 canvas 렌더 함수만 제공한다.
 * app.js가 상태(state)를 조립해 이 모듈의 함수를 호출한다.
 */
(function () {
  'use strict';

  const D4DRender = {};

  // 'terrain' colormap의 위성-다크 근사 — 5-stop 선형보간(~55-65% 명도, 저채도).
  const COLOR_STOPS = [
    { t: 0.00, c: [18, 42, 40] },    // 진청록(딥)
    { t: 0.25, c: [40, 84, 60] },    // 어두운 녹
    { t: 0.50, c: [96, 92, 58] },    // 어두운 황갈
    { t: 0.75, c: [72, 58, 42] },    // 어두운 갈
    { t: 1.00, c: [150, 150, 148] }, // 회백(정상부)
  ];

  function terrainColor(t) {
    if (t <= COLOR_STOPS[0].t) return COLOR_STOPS[0].c;
    for (let i = 1; i < COLOR_STOPS.length; i++) {
      const prev = COLOR_STOPS[i - 1];
      const cur = COLOR_STOPS[i];
      if (t <= cur.t) {
        const span = cur.t - prev.t || 1;
        const f = (t - prev.t) / span;
        return [
          prev.c[0] + (cur.c[0] - prev.c[0]) * f,
          prev.c[1] + (cur.c[1] - prev.c[1]) * f,
          prev.c[2] + (cur.c[2] - prev.c[2]) * f,
        ];
      }
    }
    return COLOR_STOPS[COLOR_STOPS.length - 1].c;
  }

  const CONTOUR_LEVELS = 12;

  // 뷰셰드(가시영역) 레이캐스팅 튜닝 상수.
  const VIEWSHED_RAYS = 720;
  const VIEWSHED_MAX_RANGE_DEFAULT = 70; // cell
  // 기본 뷰셰드 색(호출측이 color 를 넘기지 않을 때만 사용).
  const VIEWSHED_COLOR_DEFAULT = [60, 130, 255, Math.round(0.44 * 255)];

  // 적 탐지 footprint 튜닝 상수.
  const ENEMY_HEIGHT_OFFSET = 10; // m, 적 고도 가정치(지형고도 + 10m)
  const FOOTPRINT_COLOR_DEFAULT = [235, 45, 45, Math.round(0.34 * 255)];

  function terrainHeightAt(u16, W, hmin, hmax, x, y) {
    const range = (hmax - hmin) || 1;
    return hmin + (u16[y * W + x] / 65535) * range;
  }

  /**
   * 드론 위치·고도에서 지형에 가리지 않고 관측 가능한 지상 셀을 레이디얼
   * 레이캐스팅으로 계산한다. 각 레이(720방향)를 따라 셀 단위로 전진하며,
   * 드론→목표 셀 고각(elevation angle)이 그 레이에서 지금까지의 최대 고각
   * 이상이면 가시로 마킹하고 최대 고각을 갱신한다(표준 뷰셰드 알고리즘).
   * drone: {x, y, alt} — alt는 절대 고도(m). 지형 높이는 u16을 hmin/hmax로
   * 역양자화해 구한다. 반환: Uint8Array(H*W) (1=가시, 0=불가시).
   */
  D4DRender.computeViewshed = function (u16, H, W, hmin, hmax, drone, maxRange) {
    maxRange = maxRange || VIEWSHED_MAX_RANGE_DEFAULT;
    const mask = new Uint8Array(H * W);

    const cx0 = Math.round(drone.x);
    const cy0 = Math.round(drone.y);
    if (cx0 >= 0 && cx0 < W && cy0 >= 0 && cy0 < H) {
      mask[cy0 * W + cx0] = 1;
    }

    const steps = Math.floor(maxRange);
    for (let r = 0; r < VIEWSHED_RAYS; r++) {
      const theta = (r / VIEWSHED_RAYS) * Math.PI * 2;
      const dxStep = Math.cos(theta);
      const dyStep = Math.sin(theta);
      let maxElevAngle = -Infinity;
      let lastCx = cx0;
      let lastCy = cy0;
      for (let s = 1; s <= steps; s++) {
        const fx = drone.x + dxStep * s;
        const fy = drone.y + dyStep * s;
        const cx = Math.round(fx);
        const cy = Math.round(fy);
        if (cx < 0 || cx >= W || cy < 0 || cy >= H) break;
        if (cx === lastCx && cy === lastCy) continue;
        lastCx = cx;
        lastCy = cy;
        const h = terrainHeightAt(u16, W, hmin, hmax, cx, cy);
        const elevAngle = Math.atan2(h - drone.alt, s);
        if (elevAngle >= maxElevAngle) {
          mask[cy * W + cx] = 1;
          maxElevAngle = elevAngle;
        }
      }
    }

    return mask;
  };

  /**
   * computeViewshed이 만든 mask(H*W, 1=가시)를 오프스크린 canvas(W x H)에
   * 반투명 색으로 채색한다. y반전은 buildTerrainLayer와 동일하게 캔버스
   * 행 cy에 데이터 행 (H-1-cy)를 대응시킨다. color 생략 시 파란 기본색 사용.
   */
  D4DRender.buildViewshedLayer = function (mask, H, W, color) {
    const canvas = document.createElement('canvas');
    canvas.width = W;
    canvas.height = H;
    const ctx = canvas.getContext('2d');
    const imgData = ctx.createImageData(W, H);
    const data = imgData.data;
    const [cr, cg, cb, ca] = color || VIEWSHED_COLOR_DEFAULT;

    for (let cy = 0; cy < H; cy++) {
      const yData = H - 1 - cy;
      for (let x = 0; x < W; x++) {
        const srcIdx = yData * W + x;
        const di = (cy * W + x) * 4;
        if (mask[srcIdx]) {
          data[di] = cr;
          data[di + 1] = cg;
          data[di + 2] = cb;
          data[di + 3] = ca;
        } else {
          data[di + 3] = 0;
        }
      }
    }

    ctx.putImageData(imgData, 0, 0);
    return canvas;
  };

  /**
   * 적 시점 탐지 footprint(지형 반영, 원 아님)를 계산한다. enemy={center:[x,y],
   * detect_range}. 적 고도는 지형고도 + ENEMY_HEIGHT_OFFSET(가정치)로 두고,
   * computeViewshed를 그대로 재사용해 detect_range 범위 내에서 지형에 가리지
   * 않는 셀만 마킹한다(능선 뒤는 빠지는 불규칙 형태). 반환: Uint8Array(H*W).
   */
  D4DRender.computeEnemyFootprint = function (u16, H, W, hmin, hmax, enemy) {
    const mask = new Uint8Array(H * W);
    if (!enemy || !enemy.center) return mask;

    const ex = enemy.center[0];
    const ey = enemy.center[1];
    const cx = Math.min(W - 1, Math.max(0, Math.round(ex)));
    const cy = Math.min(H - 1, Math.max(0, Math.round(ey)));
    const groundH = terrainHeightAt(u16, W, hmin, hmax, cx, cy);
    const enemyPos = { x: ex, y: ey, alt: groundH + ENEMY_HEIGHT_OFFSET };
    const maxRange = enemy.detect_range || VIEWSHED_MAX_RANGE_DEFAULT;

    return D4DRender.computeViewshed(u16, H, W, hmin, hmax, enemyPos, maxRange);
  };

  /**
   * computeEnemyFootprint이 만든 mask(H*W, 1=가시)를 오프스크린 canvas(W x H)에
   * 반투명 색으로 채색한다. buildViewshedLayer와 동일하게 y반전 적용.
   * color 생략 시 FOOTPRINT_COLOR_DEFAULT(반투명 빨강) 사용.
   */
  D4DRender.buildFootprintLayer = function (mask, H, W, color) {
    const canvas = document.createElement('canvas');
    canvas.width = W;
    canvas.height = H;
    const ctx = canvas.getContext('2d');
    const imgData = ctx.createImageData(W, H);
    const data = imgData.data;
    const [cr, cg, cb, ca] = color || FOOTPRINT_COLOR_DEFAULT;

    for (let cy = 0; cy < H; cy++) {
      const yData = H - 1 - cy;
      for (let x = 0; x < W; x++) {
        const srcIdx = yData * W + x;
        const di = (cy * W + x) * 4;
        if (mask[srcIdx]) {
          data[di] = cr;
          data[di + 1] = cg;
          data[di + 2] = cb;
          data[di + 3] = ca;
        } else {
          data[di + 3] = 0;
        }
      }
    }

    ctx.putImageData(imgData, 0, 0);
    return canvas;
  };

  /**
   * Uint16Array(row-major, terrain[y*W+x])를 오프스크린 canvas(W x H)에
   * ImageData로 채색해 반환한다.
   * 데이터는 y=row origin lower(행 0이 하단), canvas는 origin upper이므로
   * 캔버스 행 cy에는 데이터 행 (H-1-cy)를 샘플링한다.
   */
  D4DRender.buildTerrainLayer = function (u16, H, W, hmin, hmax) {
    const canvas = document.createElement('canvas');
    canvas.width = W;
    canvas.height = H;
    const ctx = canvas.getContext('2d');
    const imgData = ctx.createImageData(W, H);
    const data = imgData.data;
    const range = (hmax - hmin) || 1;

    const ts = new Float32Array(W * H);
    const levels = new Uint8Array(W * H);

    for (let cy = 0; cy < H; cy++) {
      const yData = H - 1 - cy;
      for (let x = 0; x < W; x++) {
        const srcIdx = yData * W + x;
        let t = (u16[srcIdx] - hmin) / range;
        if (t < 0) t = 0;
        if (t > 1) t = 1;
        const ci = cy * W + x;
        ts[ci] = t;
        levels[ci] = Math.min(CONTOUR_LEVELS - 1, Math.floor(t * CONTOUR_LEVELS));
      }
    }

    for (let cy = 0; cy < H; cy++) {
      for (let x = 0; x < W; x++) {
        const ci = cy * W + x;
        const [r, g, b] = terrainColor(ts[ci]);
        const lvl = levels[ci];
        const leftLvl = x > 0 ? levels[ci - 1] : lvl;
        const topLvl = cy > 0 ? levels[ci - W] : lvl;
        const isEdge = lvl !== leftLvl || lvl !== topLvl;
        const shade = isEdge ? 0.7 : 1.0;
        const di = ci * 4;
        data[di] = r * shade;
        data[di + 1] = g * shade;
        data[di + 2] = b * shade;
        data[di + 3] = 255;
      }
    }

    ctx.putImageData(imgData, 0, 0);
    return canvas;
  };

  /**
   * 지도 좌표 그리드 오버레이 — extent(m)를 1/8 간격의 얇은 그리드선으로
   * 나누고 가장자리에 작은 mono 미터 라벨을 붙인다(계측 지도 느낌).
   * terrain 레이어 위, 뷰셰드/경로/마커 아래에서 호출된다.
   */
  D4DRender.drawMapGrid = function (ctx, W, H, extentM) {
    const DIV = 8;
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.lineWidth = 1;
    ctx.fillStyle = 'rgba(255,255,255,0.30)';
    ctx.font = '8px ui-monospace, Menlo, monospace';
    for (let i = 1; i < DIV; i++) {
      const fx = (i / DIV) * W;
      const fy = (i / DIV) * H;
      ctx.beginPath();
      ctx.moveTo(fx, 0);
      ctx.lineTo(fx, H);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, fy);
      ctx.lineTo(W, fy);
      ctx.stroke();
      const m = Math.round((i / DIV) * extentM);
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText(String(m), fx, H - 3);
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(m), 3, fy);
    }
    ctx.restore();
  };

  // x축 거리(m) 눈금 라벨 포맷 — 1000m 미만은 "Nm", 이상은 "N.Nkm".
  function formatDist(v) {
    if (v <= 0) return '0';
    if (v < 1000) return Math.round(v) + 'm';
    return (v / 1000).toFixed(1) + 'km';
  }

  /**
   * prof: {dist:[...], terrainH:[...], totalDist, yMax} — 정적 프로파일 데이터(app.js가 생성).
   * state: {trailProfile:[[dist, alt], ...]} — 현재까지 드론 고도 누적 배열(시간순, 시나리오
   * 루프마다 app.js가 리셋).
   * 좌측 y축(m) + 하단 x축(거리) 눈금/격자선/라벨을 그린 뒤 지형 채움 + 드론 고도선을 그린다.
   * 눈금 개수는 플롯 폭/높이에 맞춰 적응한다(가로로 긴 짧은 strip 대응).
   */
  D4DRender.drawProfile = function (ctx, prof, state) {
    const canvas = ctx.canvas;
    const cw = canvas.width;
    const ch = canvas.height;

    const margin = { left: 46, right: 12, top: 10, bottom: 34 };
    const plotW = cw - margin.left - margin.right;
    const plotH = ch - margin.top - margin.bottom;
    const distOff = prof.distOffset || 0;
    const xMax = (distOff + (prof.totalDist || 0)) || 1;
    const yMax = prof.yMax || 1;

    // 눈금 개수: 플롯 크기에 맞춰 적응(폭이 좁으면 줄이고 넓으면 늘림).
    const xTickCount = Math.max(3, Math.min(10, Math.round(plotW / 100)));
    const yTickCount = Math.max(3, Math.min(6, Math.round(plotH / 35)));

    function toXY(dist, alt) {
      return [
        margin.left + (dist / xMax) * plotW,
        margin.top + plotH - (alt / yMax) * plotH,
      ];
    }

    ctx.clearRect(0, 0, cw, ch);

    // y축 눈금 + 격자선 + 라벨 — muted(#98979F) 저알파.
    ctx.save();
    ctx.strokeStyle = 'rgba(152,151,159,0.15)';
    ctx.fillStyle = '#98979F';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= yTickCount; i++) {
      const v = (yMax / yTickCount) * i;
      const [, y] = toXY(0, v);
      ctx.beginPath();
      ctx.moveTo(margin.left, y);
      ctx.lineTo(margin.left + plotW, y);
      ctx.stroke();
      ctx.fillText(Math.round(v).toString(), margin.left - 6, y);
    }
    ctx.restore();

    // x축 눈금.
    ctx.save();
    ctx.fillStyle = '#98979F';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let i = 0; i <= xTickCount; i++) {
      const v = (xMax / xTickCount) * i;
      const [x] = toXY(v, 0);
      ctx.fillText(formatDist(v), x, margin.top + plotH + 6);
    }
    ctx.restore();

    // 지형: dist/terrainH 폴리곤 채움 + 윤곽선(경로를 따라 누적한 실거리 기준).
    if (prof.dist && prof.dist.length > 1) {
      ctx.save();
      ctx.beginPath();
      const [x0, y0] = toXY(prof.dist[0] + distOff, 0);
      ctx.moveTo(x0, y0);
      prof.dist.forEach(function (d, i) {
        const [x, y] = toXY(d + distOff, prof.terrainH[i]);
        ctx.lineTo(x, y);
      });
      const lastDist = prof.dist[prof.dist.length - 1];
      const [xLast] = toXY(lastDist + distOff, 0);
      ctx.lineTo(xLast, y0);
      ctx.closePath();
      ctx.fillStyle = 'rgba(141,115,90,0.55)';
      ctx.fill();
      ctx.restore();

      ctx.save();
      ctx.strokeStyle = '#5b4636';
      ctx.lineWidth = 1.0;
      ctx.beginPath();
      prof.dist.forEach(function (d, i) {
        const [x, y] = toXY(d + distOff, prof.terrainH[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.restore();
    }

    // 드론 고도선: 현재까지의 trailProfile 만 그린다(accent 앰버).
    if (state.trailProfile && state.trailProfile.length > 1) {
      ctx.save();
      ctx.strokeStyle = '#F0A03C';
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      state.trailProfile.forEach(function (p, i) {
        const [x, y] = toXY(p[0], p[1]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.restore();
    }

    // 현재 위치 마커: trailProfile 마지막 점에 밝은 앰버 점.
    if (state.trailProfile && state.trailProfile.length > 0) {
      const last = state.trailProfile[state.trailProfile.length - 1];
      const [x, y] = toXY(last[0], last[1]);
      ctx.save();
      ctx.fillStyle = '#FFB95A';
      ctx.strokeStyle = '#0D0D0F';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(x, y, 4.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    }

    // 축 라벨.
    ctx.save();
    ctx.fillStyle = '#E8E7E2';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText('경로 거리 (m/km)', margin.left + plotW / 2, ch - 6);
    ctx.save();
    ctx.translate(14, margin.top + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textBaseline = 'middle';
    ctx.fillText('고도 (m)', 0, 0);
    ctx.restore();
    ctx.restore();
  };

  // ── MIL-STD-2525/APP-6 map symbols (pure draw helpers) ──────────────
  // Affiliation colors follow military symbology convention and take
  // precedence over the dashboard's lavender brand accent here:
  // hostile = red (#F0555D), friendly = 2525 crystal-blue (#66C2FF).
  const SYM_HOSTILE_STROKE = '#F0555D';
  const SYM_HOSTILE_FILL = 'rgba(240,85,93,0.25)';
  const SYM_FRIENDLY_STROKE = '#66C2FF';
  const SYM_FRIENDLY_FILL = 'rgba(102,194,255,0.25)';

  /**
   * Hostile ground unit — 2525 hostile frame: red diamond OUTLINE
   * (not filled solid), very subtle fill, small solid center dot.
   */
  D4DRender.drawHostileGround = function (ctx, x, y, size) {
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(x, y - size);
    ctx.lineTo(x + size, y);
    ctx.lineTo(x, y + size);
    ctx.lineTo(x - size, y);
    ctx.closePath();
    ctx.fillStyle = SYM_HOSTILE_FILL;
    ctx.fill();
    ctx.strokeStyle = SYM_HOSTILE_STROKE;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, Math.max(1.5, size * 0.22), 0, Math.PI * 2);
    ctx.fillStyle = SYM_HOSTILE_STROKE;
    ctx.fill();
    ctx.restore();
  };

  /**
   * Friendly air track — 2525 friendly AIR frame: light-blue semicircle
   * open at the bottom (dome), with the fixed-wing UAV bowtie modifier
   * inside. Per 2525 convention the frame does NOT rotate with heading;
   * instead a short velocity leader tick points along headingRad.
   */
  D4DRender.drawFriendlyAir = function (ctx, x, y, size, headingRad) {
    const cy = y + size * 0.5; // dome chord sits below (x, y) so the symbol reads centered
    ctx.save();

    // Dome fill (chord-closed path used for fill only).
    ctx.beginPath();
    ctx.arc(x, cy, size, Math.PI, 0);
    ctx.closePath();
    ctx.fillStyle = SYM_FRIENDLY_FILL;
    ctx.fill();

    // Dome stroke — arc only, open at the bottom.
    ctx.beginPath();
    ctx.arc(x, cy, size, Math.PI, 0);
    ctx.strokeStyle = SYM_FRIENDLY_STROKE;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Fixed-wing UAV modifier: bowtie (two triangles meeting at center).
    const by = cy - size * 0.38;
    const w = size * 0.55;
    const h = size * 0.28;
    ctx.beginPath();
    ctx.moveTo(x, by);
    ctx.lineTo(x - w, by - h);
    ctx.lineTo(x - w, by + h);
    ctx.closePath();
    ctx.moveTo(x, by);
    ctx.lineTo(x + w, by - h);
    ctx.lineTo(x + w, by + h);
    ctx.closePath();
    ctx.fillStyle = SYM_FRIENDLY_STROKE;
    ctx.fill();

    // Heading tick (velocity leader) from dome edge along current heading.
    const hx = Math.cos(headingRad);
    const hy = Math.sin(headingRad);
    ctx.beginPath();
    ctx.moveTo(x + hx * size, cy + hy * size);
    ctx.lineTo(x + hx * size * 1.9, cy + hy * size * 1.9);
    ctx.strokeStyle = SYM_FRIENDLY_STROKE;
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.restore();
  };

  window.D4DRender = D4DRender;
})();
