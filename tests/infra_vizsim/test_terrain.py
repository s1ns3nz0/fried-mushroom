"""Tests for terrain.py — Python port of dashboard's deterministic gaussian
heightmap (infra/dashboard/static/app.js: PEAKS / heightAt / elevM /
buildTerrainGrid). These must agree bit-for-bit in formula with app.js so the
sim world and dashboard render show the same terrain.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))       # vizsim 패키지
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vizsim import terrain  # noqa: E402


def test_height_at_near_peak1_apex():
    # PEAKS[0] = {x: 0.28, y: 0.30, h: 0.95, r: 0.17} — apex of the tallest peak.
    assert terrain.height_at(0.28, 0.30) >= 0.95


def test_height_at_far_from_peaks_is_low():
    # (0,0) is far from every peak center; only the 0.10 base plus small
    # gaussian tails contribute.
    assert terrain.height_at(0.0, 0.0) < 0.3


def test_height_at_clamped_to_one():
    # Overlapping peak tails could sum above 1.0 without the clamp.
    assert terrain.height_at(0.28, 0.30) <= 1.0


def test_elev_m_matches_app_js_formula():
    # app.js: function elevM(h) { return 190 + h * 650; }
    assert terrain.elev_m(0.0) == 190
    assert terrain.elev_m(1.0) == 840
    assert terrain.elev_m(0.5) == 190 + 0.5 * 650


def test_build_terrain_grid_shape_and_range():
    grid = terrain.build_terrain_grid()
    assert grid["w"] == 200
    assert grid["h"] == 200
    assert len(grid["u16"]) == 40000
    assert min(grid["u16"]) == 0
    assert max(grid["u16"]) == 65535
    assert all(isinstance(v, int) for v in grid["u16"])


def test_build_terrain_grid_is_deterministic():
    grid1 = terrain.build_terrain_grid()
    grid2 = terrain.build_terrain_grid()
    assert grid1["u16"] == grid2["u16"]
    assert grid1["hmin"] == grid2["hmin"]
    assert grid1["hmax"] == grid2["hmax"]
