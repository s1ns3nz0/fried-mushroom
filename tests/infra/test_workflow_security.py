"""배포 워크플로 보안 회귀 가드 (#225 #238).

.github/workflows/*.yml 에 AWS 식별자(계정 ID / ARN / EC2 인스턴스 ID /
CloudFront 배포 ID / S3 버킷) 리터럴 하드코딩 금지 + deploy-*.yml 배포 job 의
DEPLOY_ENABLED 게이트 존재를 assert.

#221(배포 안전화) 상태를 고정 — 재발 방지.
#238: 배포 게이트 OR-우회 탐지 강화 — if 조건이 정확히 DEPLOY_ENABLED == 'true' 여야 함.
      `... == 'true' || github.event_name == 'workflow_dispatch'` 같은 OR 확장 시 실패.

검증 전략:
- 리터럴 탐지: string literal 이 없는 ${{ ... }} 표현식만 제거(known-safe 참조).
  string literal 포함 표현식(예: ${{ 'arn:...' }})은 제거하지 않고 스캔.
- 게이트 탐지: jobs: 섹션을 파싱해 각 job 이 개별적으로 DEPLOY_ENABLED 게이트를 가짐 assert.
- 게이트 엄격 검증: 전체 조건이 정확히 DEPLOY_ENABLED == 'true' 여야 함(OR 확장 불허).
- (선택) secrets.X || 'literal' 폴백 패턴 금지.

src/onboard, src/gcs, infra/sim 무접촉.
"""

import pathlib
import re

import pytest

_WORKFLOWS_DIR = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _all_workflow_files() -> list[pathlib.Path]:
    return sorted(_WORKFLOWS_DIR.glob("*.yml"))


def _deploy_workflow_files() -> list[pathlib.Path]:
    return sorted(_WORKFLOWS_DIR.glob("deploy-*.yml"))


def _strip_safe_expressions(text: str) -> str:
    """string literal(따옴표)이 없는 ${{ ... }} 표현식만 제거.

    secrets.X, vars.X, github.X 같은 known-safe 참조는 따옴표를 포함하지 않으므로
    제거된다. 반면 ${{ 'arn:aws:...' }} 처럼 string literal 이 있는 표현식은
    제거하지 않아 패턴 스캔에 걸린다.
    """
    return re.sub(r"\$\{\{[^'\"{}]*\}\}", "", text)


def _parse_jobs(text: str) -> dict[str, str | None]:
    """workflow YAML 텍스트에서 {job_name: if_condition_or_None} 추출.

    PyYAML 없이 indent 기반으로 파싱:
    - 0-space 의 'jobs:' 이후를 jobs 섹션으로 간주.
    - 2-space 들여쓰기 + 값 없는 키('  name:')를 job 이름으로 인식.
    - 4-space 의 'if: ...' 줄을 해당 job 의 조건으로 기록.
    """
    jobs: dict[str, str | None] = {}
    current_job: str | None = None
    in_jobs: bool = False

    for line in text.splitlines():
        # top-level key(0-space) 감지
        if re.match(r"^[a-zA-Z]", line):
            in_jobs = re.match(r"^jobs:\s*$", line) is not None
            current_job = None
            continue

        if not in_jobs:
            continue

        # job 이름: 2-space indent, 값 없는 키
        m = re.match(r"^  ([a-zA-Z][a-zA-Z0-9_-]*):\s*$", line)
        if m:
            current_job = m.group(1)
            jobs[current_job] = None
            continue

        # job-level if: 4-space indent (step-level 은 8-space)
        if current_job:
            m = re.match(r"^    if:\s+(.+)$", line)
            if m:
                jobs[current_job] = m.group(1).strip()

    return jobs


# ---------------------------------------------------------------------------
# 금지 패턴 정의
# ---------------------------------------------------------------------------

_FORBIDDEN: dict[str, tuple[str, str]] = {
    "aws_account_id": (
        r"\b\d{12}\b",
        "AWS 계정 ID (12자리 숫자) 리터럴 금지 — secrets/vars 참조 사용",
    ),
    "arn_literal": (
        r"arn:aws:",
        "AWS ARN 리터럴 금지 — secrets.AWS_ROLE_ARN 등으로 참조",
    ),
    "ec2_instance_id": (
        r"\bi-[0-9a-f]{8,17}\b",
        "EC2 인스턴스 ID 리터럴 금지 — vars.GROUND_INSTANCE_ID 등으로 참조",
    ),
    "cloudfront_dist_id": (
        r"\bE[A-Z0-9]{10,}\b",
        "CloudFront 배포 ID 리터럴 금지 — vars.CLOUDFRONT_DISTRIBUTION_ID 로 참조",
    ),
    "s3_bucket_literal": (
        r"s3://[a-z0-9][a-z0-9\-\.]{2,62}(?=[/\s\"'\n]|$)",
        "S3 버킷 리터럴 금지 — vars.DASHBOARD_BUCKET 등으로 참조",
    ),
}

# ── 1. 하드코딩 AWS 식별자 금지 ──────────────────────────────────────────────

_wf_pattern_cases = [
    (wf, name) for wf in _all_workflow_files() for name in _FORBIDDEN
]
_wf_pattern_ids = [f"{wf.name}::{name}" for wf, name in _wf_pattern_cases]


@pytest.mark.parametrize("wf_path,pattern_name", _wf_pattern_cases, ids=_wf_pattern_ids)
def test_no_hardcoded_aws_identifier(wf_path: pathlib.Path, pattern_name: str) -> None:
    """워크플로에 AWS 식별자 리터럴이 없어야 한다.

    string literal 없는 known-safe 표현식(${{ secrets.X }}, ${{ vars.X }} 등)만
    제거 후 패턴 검색. ${{ 'arn:aws:...' }} 같은 in-expression 리터럴도 탐지.
    """
    regex, msg = _FORBIDDEN[pattern_name]
    text = wf_path.read_text(encoding="utf-8")
    stripped = _strip_safe_expressions(text)
    matches = re.findall(regex, stripped)
    assert not matches, (
        f"{wf_path.name}: {msg}\n"
        f"  발견된 리터럴: {matches[:5]}"
    )


# ── 2. deploy job 각각 DEPLOY_ENABLED 게이트 (엄격 검증, #238) ───────────────

# 허용 게이트 패턴: ${{ }} 벗긴 후 전체 표현식이 정확히 이 형식이어야 함.
_STRICT_GATE_RE = re.compile(r"^vars\.DEPLOY_ENABLED\s*==\s*['\"]true['\"]$")


def _is_strict_deploy_gate(if_cond: str) -> bool:
    """if 조건이 정확히 `vars.DEPLOY_ENABLED == 'true'` 인지 검증 (#238).

    ${{ }} 래퍼는 허용하되, OR / AND 확장 등 부가 조건은 불허.
    예시:
        통과: "${{ vars.DEPLOY_ENABLED == 'true' }}"
        통과: "vars.DEPLOY_ENABLED == 'true'"
        실패: "${{ vars.DEPLOY_ENABLED == 'true' || github.event_name == 'workflow_dispatch' }}"
        실패: "vars.DEPLOY_ENABLED == 'true' && always()"
    """
    stripped = re.sub(r"^\$\{\{\s*|\s*\}\}$", "", if_cond).strip()
    return bool(_STRICT_GATE_RE.match(stripped))


# ── TDD: _is_strict_deploy_gate 단위 케이스 (#238) ───────────────────────────

@pytest.mark.parametrize("cond,expected", [
    ("${{ vars.DEPLOY_ENABLED == 'true' }}", True),
    ("vars.DEPLOY_ENABLED == 'true'", True),
    ('${{ vars.DEPLOY_ENABLED == "true" }}', True),
    ("${{ vars.DEPLOY_ENABLED == 'true' || github.event_name == 'workflow_dispatch' }}", False),
    ("vars.DEPLOY_ENABLED == 'true' && always()", False),
    ("${{ vars.DEPLOY_ENABLED != 'true' }}", False),
    ("vars.DEPLOY_ENABLED == 'true' || true", False),
], ids=[
    "ok-wrapped", "ok-bare", "ok-double-quote",
    "fail-or-dispatch", "fail-and-always", "fail-neq", "fail-or-true",
])
def test_is_strict_deploy_gate_unit(cond: str, expected: bool) -> None:
    """_is_strict_deploy_gate 가 OR-우회·부가 조건을 올바르게 거부해야 한다 (#238).

    구 가드(re.search)는 fail-or-dispatch 케이스를 통과 — 이 유닛 테스트로 맹점 검증.
    """
    assert _is_strict_deploy_gate(cond) is expected, (
        f"조건 {cond!r} → expected {expected}, got {not expected}"
    )


_deploy_ids = [wf.name for wf in _deploy_workflow_files()]


@pytest.mark.parametrize("wf_path", _deploy_workflow_files(), ids=_deploy_ids)
def test_every_deploy_job_has_deploy_enabled_gate(wf_path: pathlib.Path) -> None:
    """deploy-*.yml 의 각 job 이 개별적으로 DEPLOY_ENABLED 게이트를 가져야 한다.

    #238: OR 확장 등 우회 조건이 있는 경우도 실패하도록 _is_strict_deploy_gate 로 검증.
    """
    text = wf_path.read_text(encoding="utf-8")
    jobs = _parse_jobs(text)
    assert jobs, f"{wf_path.name}: jobs: 섹션에서 job 을 찾지 못함"

    for job_name, if_cond in jobs.items():
        assert if_cond is not None, (
            f"{wf_path.name}: job '{job_name}' 에 if: 조건 없음 — DEPLOY_ENABLED 게이트 필수"
        )
        assert _is_strict_deploy_gate(if_cond), (
            f"{wf_path.name}: job '{job_name}' if 조건이 엄격 게이트 형식이 아님: {if_cond!r}\n"
            "  → 정확히 `vars.DEPLOY_ENABLED == 'true'` 만 허용 (OR/AND 확장 불허, #238)"
        )


# ── 3. secrets fallback 리터럴 폴백 금지 ──────────────────────────────────────

_all_ids = [wf.name for wf in _all_workflow_files()]


@pytest.mark.parametrize("wf_path", _all_workflow_files(), ids=_all_ids)
def test_no_secrets_literal_fallback(wf_path: pathlib.Path) -> None:
    """secrets.X || 'literal' 폴백 패턴 금지 — 실패 시 하드코딩 대체값 노출."""
    text = wf_path.read_text(encoding="utf-8")
    matches = re.findall(
        r"\$\{\{[^}]*secrets\.[A-Z_]+\s*\|\|\s*['\"][^'\"]{1,}['\"][^}]*\}\}",
        text,
    )
    assert not matches, (
        f"{wf_path.name}: secrets fallback 리터럴 발견: {matches[:3]}"
    )
