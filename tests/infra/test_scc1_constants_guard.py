"""SCC-1 정적 가드: infra/log advisory 모듈은 결정론 상수를 읽거나 쓰지 않는다.

CLAUDE.md CRITICAL: "결정론적 로직(임계값 비교, 매트릭스 조회, GIS 조회, 잔차 계산)과
AI 강화판 ... 은 반드시 분리 ... RAC 매트릭스는 AI가 절대 바꾸지 않는다
(MIL-STD-882E SCC-1 원칙)." docs/RAG-corpus.md §7 은 이를 infra/log advisory 계열
(코퍼스/weight_advisor)에 대해 재확인한다.

지금까지는 weight_advisor.py 자체 테스트(문자열 검사, tests/infra/test_weight_advisor.py)
로만 보장됐다. 이 테스트는 infra/log/ 전체를 AST 로 정적 스캔해, 어떤 모듈도 다음을 하지
않음을 강제한다:
  1. shared/constants(onboard.shared.constants 또는 shared.constants) 모듈 자체 또는
     그 안의 보호 상수(CHANNEL_WEIGHTS/RAC_MATRIX/SIGNAL_TO_THREAT/
     PHASE_THREAT_MULTIPLIER) import.
  2. 그 상수들에 대한 속성 접근(module.CONST 형태), import 경로가 무엇이든.
  3. eval()/exec() 호출 (docs/RAG-corpus.md §7 계약).
"""

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_INFRA_LOG = _ROOT / "infra" / "log"

_PROTECTED_CONSTANTS = frozenset({
    "CHANNEL_WEIGHTS",
    "RAC_MATRIX",
    "SIGNAL_TO_THREAT",
    "PHASE_THREAT_MULTIPLIER",
})


def _iter_infra_log_py():
    for py in sorted(_INFRA_LOG.glob("*.py")):
        yield py


def _parse(py: pathlib.Path) -> ast.AST:
    return ast.parse(py.read_text(encoding="utf-8"), filename=str(py))


def _constants_module_violations(tree: ast.AST):
    """shared/constants 모듈 자체 또는 보호 상수 이름의 import 를 수집.

    `from onboard.shared.constants import RAC_MATRIX`, `from shared import constants`,
    `import onboard.shared.constants` 등 어느 경로로 들어와도 걸린다 — 마지막
    구성요소가 'constants' 인 모듈, 혹은 import 되는 이름이 'constants'/보호 상수인
    경우 전부 위반으로 간주한다(advisory 는 상수 모듈 자체에 의존하면 안 됨).
    """
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            tail = node.module.split(".")[-1]
            if tail == "constants":
                bad.append(f"from {node.module} import ...")
            for alias in node.names:
                if alias.name == "constants" or alias.name in _PROTECTED_CONSTANTS:
                    bad.append(f"from {node.module} import {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == "constants":
                    bad.append(f"import {alias.name}")
    return bad


def _attribute_access_violations(tree: ast.AST):
    """`module.CHANNEL_WEIGHTS` 형태의 속성 접근 — import 경로와 무관하게 잡는다."""
    bad = [f".{node.attr} 속성 접근" for node in ast.walk(tree)
           if isinstance(node, ast.Attribute) and node.attr in _PROTECTED_CONSTANTS]
    return bad


def _eval_exec_violations(tree: ast.AST):
    bad = [node.func.id for node in ast.walk(tree)
           if isinstance(node, ast.Call)
           and isinstance(node.func, ast.Name)
           and node.func.id in ("eval", "exec")]
    return bad


def test_infra_log_dir_discovered():
    # 가드가 실제로 infra/log 를 훑는지 (빈 glob 로 자명하게 통과하는 것 방지).
    assert len(list(_iter_infra_log_py())) >= 8


@pytest.mark.parametrize("py", list(_iter_infra_log_py()), ids=lambda p: p.name)
def test_no_constants_import(py):
    violations = _constants_module_violations(_parse(py))
    assert not violations, (
        f"{py.name} 가 shared/constants 모듈(또는 보호 상수)을 import 함: {violations}. "
        f"advisory 코드는 결정론 상수를 절대 읽거나 쓰지 않는다 (SCC-1)."
    )


@pytest.mark.parametrize("py", list(_iter_infra_log_py()), ids=lambda p: p.name)
def test_no_protected_constant_attribute_access(py):
    violations = _attribute_access_violations(_parse(py))
    assert not violations, (
        f"{py.name} 가 보호 상수에 속성 접근함: {violations}. "
        f"CHANNEL_WEIGHTS/RAC_MATRIX/SIGNAL_TO_THREAT/PHASE_THREAT_MULTIPLIER 는 "
        f"AI/advisory 코드가 참조 불가 (MIL-STD-882E SCC-1)."
    )


@pytest.mark.parametrize("py", list(_iter_infra_log_py()), ids=lambda p: p.name)
def test_no_eval_exec(py):
    violations = _eval_exec_violations(_parse(py))
    assert not violations, f"{py.name} 가 eval/exec 를 호출함: {violations}. docs/RAG-corpus.md §7 위반."


@pytest.mark.parametrize("module_name", ["corpus.py", "aggregate.py", "weight_advisor.py"])
def test_advisory_core_modules_touch_no_constants(module_name):
    # 라운드 3 advisory 핵심 3개 모듈을 명시적으로 고정 — 회귀 시 원인을 즉시 특정한다.
    tree = _parse(_INFRA_LOG / module_name)
    assert not _constants_module_violations(tree)
    assert not _attribute_access_violations(tree)
    assert not _eval_exec_violations(tree)
