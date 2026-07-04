"""아키텍처 경계 불변식: 온보드 레이어는 다른 레이어의 내부 모듈을 import 하지 않는다.

CLAUDE.md CRITICAL: "레이어 간 통신은 오직 JSON-직렬화 가능한 dict로만. 레이어가
다른 레이어의 내부 모듈을 직접 import 금지." 오케스트레이터(run.py)만 레이어 run() 을
엮는다. 이 테스트는 그 경계를 정적(AST)으로 강제해 우발적 결합을 회귀로 잡는다.

허용 import (레이어 코드가 의존해도 되는 것):
- onboard.shared.*          — 공유 계약/상수 (SSOT)
- onboard.ai_stubs.*        — AI 스텁 (ADR-002)
- 자기 자신 레이어 패키지
- onboard.layer_02_sensor.schema — 원시 센서 계약(RawSensorEnvelope). layer 02 의
  '출력 계약' 이며 layer 03 이 입력 타입으로 소비한다(#14 정본). 로직이 아닌
  인터페이스 타입이므로 명시적 예외로 허용한다.

그 외 `onboard.layer_XX_*` 를 다른 레이어에서 import 하면 실패한다.
"""

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "onboard"
_LAYER_DIRS = sorted(p for p in _SRC.glob("layer_*") if p.is_dir())

# 명시적으로 허용된 교차-레이어 계약 import (모듈 전체 경로).
_ALLOWED_CROSS = {"onboard.layer_02_sensor.schema"}


def _own_layer_prefix(path: pathlib.Path) -> str:
    """파일이 속한 레이어 패키지명 (예: 'layer_03_abstraction')."""
    for part in path.relative_to(_SRC).parts:
        if part.startswith("layer_"):
            return part
    return ""


def _imported_modules(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


def _iter_layer_py():
    for d in _LAYER_DIRS:
        for py in d.rglob("*.py"):
            yield py


def _cross_layer_violations(py: pathlib.Path):
    own = _own_layer_prefix(py)
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    bad = []
    for mod in _imported_modules(tree):
        if not mod.startswith("onboard.layer_"):
            continue
        if mod in _ALLOWED_CROSS:
            continue
        # onboard.layer_<own>... 는 자기 레이어 → 허용.
        tail = mod[len("onboard.") :]
        if tail.split(".")[0] == own:
            continue
        bad.append(mod)
    return bad


def test_layer_dirs_discovered():
    # 경계 스캔이 실제로 레이어를 훑는지 (빈 glob 로 자명하게 통과하는 것 방지).
    assert len(_LAYER_DIRS) >= 6


@pytest.mark.parametrize("py", list(_iter_layer_py()), ids=lambda p: p.name)
def test_no_cross_layer_internal_imports(py):
    violations = _cross_layer_violations(py)
    assert not violations, (
        f"{py.relative_to(_SRC.parent)} 가 다른 레이어 내부 모듈을 import 함: {violations}. "
        f"레이어 간은 orchestrator 경유 dict 로만. 계약 타입이면 onboard.shared 로 이동."
    )


def test_layers_do_not_import_orchestrator():
    # 레이어는 run.py(오케스트레이터)/__main__(CLI) 를 import 하지 않는다 (역참조 금지).
    offenders = []
    for py in _iter_layer_py():
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for mod in _imported_modules(tree):
            if mod in ("onboard.run", "onboard.__main__"):
                offenders.append((py.name, mod))
    assert not offenders, f"레이어가 오케스트레이터를 역참조함: {offenders}"
