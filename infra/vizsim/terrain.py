"""Deterministic gaussian heightmap — Python port of the dashboard's
infra/dashboard/static/app.js (PEAKS / heightAt / elevM / buildTerrainGrid),
so the sim world and dashboard render agree on terrain. Stdlib only.
"""
import math

# Terrain peaks (normalized coords) — identical to app.js PEAKS.
PEAKS = [
    {"x": 0.28, "y": 0.30, "h": 0.95, "r": 0.17},
    {"x": 0.66, "y": 0.58, "h": 0.80, "r": 0.15},
    {"x": 0.48, "y": 0.14, "h": 0.62, "r": 0.13},
    {"x": 0.82, "y": 0.74, "h": 0.58, "r": 0.13},
    {"x": 0.14, "y": 0.62, "h": 0.45, "r": 0.12},
]

GRID = 200  # u16 grid size (W=H=200), matches app.js GRID.


def height_at(x: float, y: float) -> float:
    """Sum of gaussian peaks, clamped to <= 1.0. Matches app.js heightAt."""
    h = 0.10
    for p in PEAKS:
        dx = x - p["x"]
        dy = y - p["y"]
        h += p["h"] * math.exp(-(dx * dx + dy * dy) / (2 * p["r"] * p["r"]))
    return 1.0 if h > 1 else h


def elev_m(h: float) -> float:
    """Matches app.js elevM(h) = 190 + h * 650."""
    return 190 + h * 650


def build_terrain_grid() -> dict:
    """Sample height_at over a GRIDxGRID grid, matching app.js buildTerrainGrid's
    row convention: row 0 of the output corresponds to ny=1 (bottom in normalized
    space), i.e. row 0 = bottom (see app.js gridY comment)."""
    w = h = GRID
    elevations = [0.0] * (w * h)
    hmin = math.inf
    hmax = -math.inf
    for ry in range(h):
        ny = 1 - ry / (h - 1)
        for gx in range(w):
            nx = gx / (w - 1)
            hm = elev_m(height_at(nx, ny))
            elevations[ry * w + gx] = hm
            if hm < hmin:
                hmin = hm
            if hm > hmax:
                hmax = hm
    rng = (hmax - hmin) or 1
    u16 = [round(((e - hmin) / rng) * 65535) for e in elevations]
    return {"u16": u16, "w": w, "h": h, "hmin": hmin, "hmax": hmax}
