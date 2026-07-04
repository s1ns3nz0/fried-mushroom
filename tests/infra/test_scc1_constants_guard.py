"""SCC-1 정적 가드: infra/log advisory 계열은 결정론 상수를 읽지·쓰지 않는다 (#184, #193).

계약(MIL-STD-882E SCC-1, CLAUDE.md CRITICAL): RAG 코퍼스/weight_advisor advisory 코드는
`CHANNEL_WEIGHTS`/`RAC_MATRIX`/`SIGNAL_TO_THREAT`/`PHASE_THREAT_MULTIPLIER` 등 결정론 상수를
절대 import 하거나 참조하지 않는다. 지금까지는 docstring + weight_advisor 자체 테스트로만 보장했다 —
이 테스트는 그 계약을 `infra/log/` 전체에 AST 로 정적 강제해 우발적/악의적 결합을 회귀로 잡는다.

패턴: tests/test_layer_boundaries.py(정적 cross-layer import 금지) 동형.

#193 — post-merge P2: #189 가드는 (a) 모듈명에 'constants' 포함 (b) symbol 이 하드코딩된
_FORBIDDEN_CONSTANTS (c) 'shared' 경로만 검사했다. 그래서 `src/onboard/run.py` 처럼 상수를
비-constants 모듈에서 재-export 하는 경로(`from onboard.run import RAC_ORDER`)를 못 잡았다
(module=onboard.run → 'constants'/'shared' 미포함, symbol=RAC_ORDER → 원래 화이트리스트에 없음).
아래 규칙 1은 금지 심볼을 `shared/constants.py` AST 스캔으로 동적 파생해 재-export 경로 무관하게
차단한다. 규칙 2는 advisory 모듈(corpus/aggregate/weight_advisor)에 한해 onboard.*/gcs.*/src.*
import 자체를 금지하는 소스 화이트리스트를 추가한다 — 단, log_server/pipeline_feeder 등
파이프라인 드라이버 모듈은 `onboard.run.run_cycle` 같은 정당한 함수 import 를 하므로 규칙 2 에서
면제한다(전면 차단은 빌드를 깬다).
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

_INFRA_LOG = pathlib.Path(__file__).resolve().parents[2] / "infra" / "log"
_CONSTANTS_MODULE = (
    pathlib.Path(__file__).resolve().parents[2] / "src" / "onboard" / "shared" / "constants.py"
)

# 레거시 하드코딩 목록 — 아래 _collect_forbidden_constant_symbols() 로 파생되는 surface 에
# 흡수된다. 최소한 이 5개 + RAC_ORDER 는 파생 결과에 포함되어야 한다(테스트로 고정).
_LEGACY_FORBIDDEN_CONSTANTS = {
    "CHANNEL_WEIGHTS",
    "RAC_MATRIX",
    "SIGNAL_TO_THREAT",
    "PHASE_THREAT_MULTIPLIER",
    "DEFAULT_CHANNEL_WEIGHT",
}

# 규칙 2 — advisory 모듈: SCC-1 advisory 계약(RAG 코퍼스/weight_advisor)에 직결되고
# onboard/gcs 를 import 할 정당한 이유가 없는 핵심 모듈만 엄격 화이트리스트 적용.
_ADVISORY_MODULES = {"corpus.py", "aggregate.py", "weight_advisor.py"}

# 규칙 2 면제 — 파이프라인 드라이버 모듈: `onboard.run.run_cycle` 등 정당한 함수 import 필요.
# (log_server.py: from onboard.run import run_cycle / from gcs.layer_01_info_center.run import
#  assemble_draft. pipeline_feeder.py: from onboard.run import run_cycle, ... )
_PIPELINE_EXEMPT_MODULES = {
    "log_server.py",
    "pipeline_feeder.py",
    "collector.py",
    "main.py",
    "panel_feed.py",
    "store.py",
}

# 규칙 2 — advisory 모듈이 명시적으로 허용하는 서드파티 의존성.
# CLAUDE.md: "표준 라이브러리 우선. 외부 의존성은 pytest, numpy 정도로 최소화".
# sqlite_vec: corpus.py 가 narrative 하이브리드 재순위용 선택적 벡터 백엔드로 이미 사용 중
# (try/except 게이트, RAG-corpus §7) — onboard/gcs/SCC-1 상수와 무관한 순수 검색 의존성.
_ADVISORY_ALLOWED_THIRD_PARTY = {"numpy", "sqlite_vec"}


def _iter_infra_log_py():
    return sorted(_INFRA_LOG.glob("*.py"))


def _sibling_module_stems() -> set[str]:
    """infra/log 내 flat(패키지 아님) 모듈 stem — 서로 `import aggregate` 식으로 참조한다."""
    return {p.stem for p in _iter_infra_log_py()}


def _collect_forbidden_constant_symbols(constants_path: pathlib.Path = _CONSTANTS_MODULE) -> set[str]:
    """shared/constants.py 를 AST 파싱해 모듈 최상위 UPPER_SNAKE 심볼을 동적 수집.

    Assign/AnnAssign 의 target 이 ast.Name 이고 이름이 UPPER_SNAKE(대문자/숫자/언더스코어,
    최소 하나의 알파벳 포함)인 module-level 문만 대상 — 재-export 경로와 무관하게
    "이 심볼이 결정론 상수다"라는 surface 를 만든다(#193).
    """
    tree = ast.parse(constants_path.read_text(encoding="utf-8"), filename=str(constants_path))
    symbols: set[str] = set()
    for node in tree.body:  # module 최상위만 — 함수/클래스 내부 지역변수는 제외.
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper() and target.id.isidentifier():
                symbols.add(target.id)
    return symbols


_FORBIDDEN_CONSTANTS = _collect_forbidden_constant_symbols()


def _imported_modules_and_names(tree: ast.AST):
    """(모듈경로, 심볼, level) 3-tuple — from X import Y 는 (X, Y, level), import X 는 (X, None, 0)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                yield module, alias.name, node.level
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, None, 0


def _attribute_access_violations(tree: ast.AST, surface: set[str]) -> list[str]:
    """`x.RAC_MATRIX` 같은 속성 접근 흡수(#191) — surface 심볼에 속하는 .attr 접근을 위반으로 수집."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in surface:
            hits.append(node.attr)
    return hits


def _rule1_violations(source: str, filename: str = "<snippet>") -> list[str]:
    """규칙 1(금지 심볼 surface + attribute 접근) 위반 메시지 리스트. 비어있으면 통과."""
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []
    for module, symbol, _level in _imported_modules_and_names(tree):
        if "constants" in module:
            violations.append(f"{filename}: 결정론 상수 모듈 import 금지 ({module})")
        if symbol is not None:
            if symbol in _FORBIDDEN_CONSTANTS:
                violations.append(f"{filename}: 결정론 상수 {symbol!r} import 금지 (SCC-1, source={module})")
            if symbol in ("shared", "constants"):
                violations.append(f"{filename}: shared/constants 패키지 import 금지 ({module} → {symbol})")
        if "shared" in module.split("."):
            violations.append(f"{filename}: onboard shared 모듈 import 금지 ({module})")
    for attr in _attribute_access_violations(tree, _FORBIDDEN_CONSTANTS):
        violations.append(f"{filename}: 결정론 상수 {attr!r} 속성 접근 금지 (SCC-1)")
    return violations


def _rule2_violations(source: str, filename: str, sibling_stems: set[str]) -> list[str]:
    """규칙 2(advisory 모듈 엄격 소스 화이트리스트) 위반 메시지 리스트."""
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []
    for module, _symbol, level in _imported_modules_and_names(tree):
        if level > 0:
            continue  # 상대 import — 자기 패키지, 허용.
        root = module.split(".")[0] if module else ""
        if not root:
            continue
        if module.startswith("infra.log"):
            continue
        if root in sibling_stems:
            continue  # infra/log 형제 모듈 flat import (예: `from aggregate import ...`).
        if root in _ADVISORY_ALLOWED_THIRD_PARTY:
            continue
        if root in sys.stdlib_module_names or root in sys.builtin_module_names:
            continue
        violations.append(
            f"{filename}: advisory 모듈은 onboard/gcs/src import 금지 ({module}) — SCC-1 소스 화이트리스트 위반"
        )
    return violations


@pytest.mark.parametrize("py", _iter_infra_log_py(), ids=lambda p: p.name)
def test_no_constants_import(py: pathlib.Path):
    violations = _rule1_violations(py.read_text(encoding="utf-8"), filename=py.name)
    assert not violations, "; ".join(violations)


@pytest.mark.parametrize("py", _iter_infra_log_py(), ids=lambda p: p.name)
def test_no_eval_or_exec(py: pathlib.Path):
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("eval", "exec"), (
                f"{py.name}: {node.func.id}() 사용 금지 (RAG-corpus §7)")


@pytest.mark.parametrize(
    "py",
    [p for p in _iter_infra_log_py() if p.name in _ADVISORY_MODULES],
    ids=lambda p: p.name,
)
def test_advisory_module_source_whitelist(py: pathlib.Path):
    """규칙 2 — corpus/aggregate/weight_advisor 는 stdlib + 형제모듈 + numpy 만 import 가능."""
    violations = _rule2_violations(
        py.read_text(encoding="utf-8"), filename=py.name, sibling_stems=_sibling_module_stems()
    )
    assert not violations, "; ".join(violations)


@pytest.mark.parametrize(
    "py",
    [p for p in _iter_infra_log_py() if p.name in _PIPELINE_EXEMPT_MODULES],
    ids=lambda p: p.name,
)
def test_pipeline_modules_pass_rule1_but_exempt_from_rule2(py: pathlib.Path):
    """log_server/pipeline_feeder 등은 규칙 1은 지키되(상수 재-export 금지) 규칙 2(소스
    화이트리스트)는 면제 — `from onboard.run import run_cycle` 같은 정당한 함수 import 허용."""
    assert not _rule1_violations(py.read_text(encoding="utf-8"), filename=py.name)


def test_guard_covers_advisory_modules():
    # 화이트리스트: advisory 핵심 모듈이 실제로 스캔 대상에 포함됨을 고정(파일 이동 회귀 방지).
    names = {p.name for p in _iter_infra_log_py()}
    for core in ("weight_advisor.py", "corpus.py", "aggregate.py"):
        assert core in names, f"{core} 가 SCC-1 가드 스캔 대상에서 누락"


def test_forbidden_constants_surface_derived_dynamically():
    """규칙 1 surface — shared/constants.py AST 스캔 파생, 레거시 5개 + RAC_ORDER 포함 고정."""
    assert _LEGACY_FORBIDDEN_CONSTANTS <= _FORBIDDEN_CONSTANTS
    assert "RAC_ORDER" in _FORBIDDEN_CONSTANTS
    # 파생 surface 가 레거시 하드코딩보다 넓다는 것도 고정(향후 상수 자동 커버 확인).
    assert len(_FORBIDDEN_CONSTANTS) > len(_LEGACY_FORBIDDEN_CONSTANTS)


def test_reexport_bypass_is_now_detected_by_rule1():
    """#193 회귀(양성) — `from onboard.run import RAC_ORDER` 재-export 우회를 규칙 1이 검출.

    실제 파일을 수정하지 않고, 동일한 형태의 import 문을 문자열 소스로 파싱해 헬퍼에 통과시킨다.
    #189 가드(모듈명에 'constants' 포함 검사)는 module='onboard.run' 이라 통과시켰다 — 그게 버그.
    """
    snippet = "from onboard.run import RAC_ORDER\n"
    violations = _rule1_violations(snippet, filename="<bypass-snippet>")
    assert violations, "재-export 경로(onboard.run)를 통한 RAC_ORDER import 가 잡히지 않음 (#193 회귀)"


def test_legitimate_pipeline_function_import_is_not_flagged_by_rule1():
    """#193 회귀(음성 대조) — `from onboard.run import run_cycle` 은 정당한 함수 import 이므로
    규칙 1에 걸리지 않아야 한다(전면 차단 금지 제약)."""
    snippet = "from onboard.run import run_cycle\n"
    violations = _rule1_violations(snippet, filename="<legit-snippet>")
    assert not violations, "; ".join(violations)


def test_advisory_module_importing_pipeline_function_violates_rule2():
    """#193 회귀 — advisory 모듈(예: weight_advisor.py)이 `from onboard.run import run_cycle`
    을 (문자열 소스로) 넣으면 규칙 2(소스 화이트리스트) 위반이어야 한다. 상수가 아니어도
    onboard.* 자체를 advisory 모듈에서 import 할 이유가 없다."""
    snippet = "from onboard.run import run_cycle\n"
    violations = _rule2_violations(snippet, filename="weight_advisor.py", sibling_stems=_sibling_module_stems())
    assert violations, "advisory 모듈의 onboard.* import 가 규칙 2 위반으로 잡히지 않음 (#193 회귀)"


def test_attribute_access_to_forbidden_constant_is_detected():
    """#191 연장 — `x.RAC_MATRIX` 같은 속성 접근도 규칙 1이 잡는다(재-export 모듈을 별칭으로
    import한 뒤 속성으로 참조하는 우회)."""
    snippet = "import onboard.run as r\nvalue = r.RAC_MATRIX\n"
    violations = _rule1_violations(snippet, filename="<attr-snippet>")
    assert violations, "속성 접근을 통한 RAC_MATRIX 참조가 잡히지 않음"
