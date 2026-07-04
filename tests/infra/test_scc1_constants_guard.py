"""SCC-1 정적 가드: infra/log advisory 계열은 결정론 상수를 읽지·쓰지 않는다 (#184).

계약(MIL-STD-882E SCC-1, CLAUDE.md CRITICAL): RAG 코퍼스/weight_advisor advisory 코드는
`CHANNEL_WEIGHTS`/`RAC_MATRIX`/`SIGNAL_TO_THREAT`/`PHASE_THREAT_MULTIPLIER` 등 결정론 상수를
절대 import 하거나 참조하지 않는다. 지금까지는 docstring + weight_advisor 자체 테스트로만 보장했다 —
이 테스트는 그 계약을 `infra/log/` 전체에 AST 로 정적 강제해 우발적/악의적 결합을 회귀로 잡는다.

패턴: tests/test_layer_boundaries.py(정적 cross-layer import 금지) 동형.
"""

import ast
import pathlib

import pytest

_INFRA_LOG = pathlib.Path(__file__).resolve().parents[2] / "infra" / "log"
_FORBIDDEN_CONSTANTS = {
    "CHANNEL_WEIGHTS",
    "RAC_MATRIX",
    "SIGNAL_TO_THREAT",
    "PHASE_THREAT_MULTIPLIER",
    "DEFAULT_CHANNEL_WEIGHT",
}


def _iter_infra_log_py():
    return sorted(_INFRA_LOG.glob("*.py"))


def _imported_modules_and_names(tree: ast.AST):
    """(모듈경로, 심볼) 쌍 — from X import Y 는 (X, Y), import X 는 (X, None)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                yield node.module, alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, None


@pytest.mark.parametrize("py", _iter_infra_log_py(), ids=lambda p: p.name)
def test_no_constants_import(py: pathlib.Path):
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    for module, symbol in _imported_modules_and_names(tree):
        assert "constants" not in module, (
            f"{py.name}: 결정론 상수 모듈 import 금지 ({module})")
        if symbol is not None:
            assert symbol not in _FORBIDDEN_CONSTANTS, (
                f"{py.name}: 결정론 상수 {symbol!r} import 금지 (SCC-1)")
            # `from onboard import shared` / `from X import constants` 패키지-레벨 우회 차단.
            assert symbol not in ("shared", "constants"), (
                f"{py.name}: shared/constants 패키지 import 금지 ({module} → {symbol})")
        assert "shared" not in module.split("."), (
            f"{py.name}: onboard shared 모듈 import 금지 ({module})")


@pytest.mark.parametrize("py", _iter_infra_log_py(), ids=lambda p: p.name)
def test_no_eval_or_exec(py: pathlib.Path):
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("eval", "exec"), (
                f"{py.name}: {node.func.id}() 사용 금지 (RAG-corpus §7)")


def test_guard_covers_advisory_modules():
    # 화이트리스트: advisory 핵심 모듈이 실제로 스캔 대상에 포함됨을 고정(파일 이동 회귀 방지).
    names = {p.name for p in _iter_infra_log_py()}
    for core in ("weight_advisor.py", "corpus.py", "aggregate.py"):
        assert core in names, f"{core} 가 SCC-1 가드 스캔 대상에서 누락"
