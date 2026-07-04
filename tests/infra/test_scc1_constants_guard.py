"""SCC-1 정적 가드: infra/log advisory 계열은 결정론 상수를 읽지·쓰지 않는다 (#184, #193).

계약(MIL-STD-882E SCC-1, CLAUDE.md CRITICAL): RAG 코퍼스/weight_advisor advisory 코드는
`shared/constants` 의 결정론 상수를 절대 import 하거나 참조하지 않는다. 이 테스트는 그 계약을
`infra/log/` 전체에 AST 로 정적 강제한다.

#193 보완: 상수명 재-export 우회 차단. `onboard.run` 이 `RAC_ORDER` 를 재노출하므로
`from onboard.run import RAC_ORDER` 는 module='onboard.run'/symbol='RAC_ORDER' 로 구 가드(모듈명
`constants` 검사)를 통과했다. 이제 **shared/constants 전 심볼 surface** 를 AST 로 동적 추출해,
출처 모듈과 무관하게 상수명 import 를 잡는다. 정상 파이프라인 import(`from onboard.run import
run_cycle`)는 허용 — pipeline_feeder 가 실제로 쓴다.

패턴: tests/test_layer_boundaries.py(정적 cross-layer import 금지) 동형.
"""

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_INFRA_LOG = _ROOT / "infra" / "log"
_CONSTANTS_PY = _ROOT / "src" / "onboard" / "shared" / "constants.py"


def _constant_surface() -> frozenset[str]:
    """shared/constants.py 의 모듈-레벨 상수명 전체 (import 없이 AST 추출)."""
    tree = ast.parse(_CONSTANTS_PY.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        for tg in targets:
            if isinstance(tg, ast.Name) and tg.id.isupper():
                names.add(tg.id)
    return frozenset(names)


_FORBIDDEN = _constant_surface()


def _iter_infra_log_py():
    return sorted(_INFRA_LOG.glob("*.py"))


def _onboard_rooted_aliases(tree: ast.AST) -> set[str]:
    """onboard/gcs 패키지에 바인딩된 지역명 수집 — 재-export 모듈 attribute 접근 추적용(#193)."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split(".")[0]
                if root in ("onboard", "gcs"):
                    aliases.add(a.asname or root)  # `import onboard.run` → 'onboard'
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in ("onboard", "gcs"):
                for a in node.names:  # `from onboard import run` → 'run'
                    aliases.add(a.asname or a.name)
    return aliases


def _attr_root(node: ast.Attribute) -> str | None:
    """attribute 체인 최상위 Name id (`run.x.RAC_ORDER` → 'run'). 없으면 None."""
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    return cur.id if isinstance(cur, ast.Name) else None


def _import_violations(src: str, forbidden: frozenset[str] = _FORBIDDEN) -> list[str]:
    """상수 import/attribute 위반 목록. 상수명 import(재-export 포함) + constants 경로 +
    shared 심볼 + star import + 별칭 통한 상수 attribute 접근 + eval/exec."""
    tree = ast.parse(src)
    aliases = _onboard_rooted_aliases(tree)
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            if _attr_root(node) in aliases:  # run.RAC_ORDER 형 우회(codex P2)
                bad.append(f"attribute {node.attr} via aliased onboard/gcs module")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if "constants" in mod or "shared" in mod.split("."):
                bad.append(f"import from {mod}")
            for alias in node.names:
                if alias.name in forbidden:  # 상수명 재-export 우회 차단(#193)
                    bad.append(f"constant symbol {alias.name} from {mod}")
                if alias.name in ("shared", "constants"):
                    bad.append(f"package {alias.name} from {mod}")
                # star import 은 재노출 상수를 통째로 끌어올 수 있음 → onboard/gcs 출처 차단(#193 codex P2).
                if alias.name == "*" and mod.split(".")[0] in ("onboard", "gcs"):
                    bad.append(f"star import from {mod}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "constants" in alias.name or "shared" in alias.name.split("."):
                    bad.append(f"import {alias.name}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("eval", "exec"):
                bad.append(f"{node.func.id}() call")
    return bad


@pytest.mark.parametrize("py", _iter_infra_log_py(), ids=lambda p: p.name)
def test_infra_log_module_clean(py: pathlib.Path):
    violations = _import_violations(py.read_text(encoding="utf-8"))
    assert not violations, f"{py.name}: SCC-1 위반 {violations}"


def test_surface_extraction_sane():
    # 핵심 상수가 surface 에 실제로 포함(추출 회귀 방지) — 하나라도 빠지면 우회 구멍.
    for c in ("CHANNEL_WEIGHTS", "RAC_MATRIX", "RAC_ORDER", "SIGNAL_TO_THREAT", "PHASE_THREAT_MULTIPLIER"):
        assert c in _FORBIDDEN, f"{c} 가 상수 surface 추출에서 누락"


def test_catches_reexport_bypass():
    # #193 확인된 우회: onboard.run 이 재노출한 RAC_ORDER import → 잡혀야 함.
    assert _import_violations("from onboard.run import RAC_ORDER\n")
    assert _import_violations("from onboard.shared.constants import CHANNEL_WEIGHTS\n")
    assert _import_violations("import onboard.shared.constants\n")
    assert _import_violations("from onboard import shared\n")
    assert _import_violations("from onboard.run import *\n")  # star 재-export 우회(codex P2)
    assert _import_violations("import onboard.run as run\nx = run.RAC_ORDER\n")  # attr 우회(codex P2)
    assert _import_violations("from onboard import run\ny = run.RAC_ORDER\n")


def test_allows_legitimate_pipeline_import():
    # 정상 파이프라인 import 는 허용 — pipeline_feeder 의 실제 사용.
    assert not _import_violations("from onboard.run import run_cycle, extract_qualities\n")


def test_catches_eval_exec():
    assert _import_violations("x = eval('1')\n")
    assert _import_violations("exec('y=1')\n")


def test_guard_covers_advisory_modules():
    names = {p.name for p in _iter_infra_log_py()}
    for core in ("weight_advisor.py", "corpus.py", "aggregate.py"):
        assert core in names, f"{core} 가 SCC-1 가드 스캔 대상에서 누락"
