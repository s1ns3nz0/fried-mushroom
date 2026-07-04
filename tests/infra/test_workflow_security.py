"""배포 워크플로 보안 회귀 가드 (#225).

.github/workflows/*.yml 에 AWS 식별자(계정 ID / ARN / EC2 인스턴스 ID /
CloudFront 배포 ID / S3 버킷) 리터럴 하드코딩 금지 + deploy-*.yml 배포 job 의
DEPLOY_ENABLED 게이트 존재를 assert.

#221(배포 안전화) 상태를 고정 — 재발 방지.

검증 전략:
- 리터럴 탐지: ${{ ... }} 표현식(secrets/vars 참조)을 제거한 뒤 위험 패턴 검색.
  표현식 제거 후 남은 리터럴이 있으면 실패.
- 게이트 탐지: 4-space 들여쓰기 job-level if: 줄에 DEPLOY_ENABLED 포함 여부.
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


def _strip_expressions(text: str) -> str:
    """${{ ... }} 표현식 제거 — secrets/vars 참조는 리터럴이 아니므로 제거 후 검사."""
    return re.sub(r'\$\{\{[^}]*\}\}', '', text)


# ---------------------------------------------------------------------------
# 금지 패턴 정의
# ---------------------------------------------------------------------------

_FORBIDDEN: dict[str, tuple[str, str]] = {
    "aws_account_id": (
        r'\b\d{12}\b',
        "AWS 계정 ID (12자리 숫자) 리터럴 금지 — secrets/vars 참조 사용",
    ),
    "arn_literal": (
        r'arn:aws:',
        "AWS ARN 리터럴 금지 — secrets.AWS_ROLE_ARN 등으로 참조",
    ),
    "ec2_instance_id": (
        r'\bi-[0-9a-f]{8,17}\b',
        "EC2 인스턴스 ID 리터럴 금지 — vars.GROUND_INSTANCE_ID 등으로 참조",
    ),
    "cloudfront_dist_id": (
        r'\bE[A-Z0-9]{10,}\b',
        "CloudFront 배포 ID 리터럴 금지 — vars.CLOUDFRONT_DISTRIBUTION_ID 로 참조",
    ),
    "s3_bucket_literal": (
        r's3://[a-z0-9][a-z0-9\-\.]{2,62}/',
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
    """워크플로에 AWS 식별자 리터럴이 없어야 한다 — ${{ }} 표현식 제거 후 검사."""
    regex, msg = _FORBIDDEN[pattern_name]
    text = wf_path.read_text(encoding="utf-8")
    stripped = _strip_expressions(text)
    matches = re.findall(regex, stripped)
    assert not matches, (
        f"{wf_path.name}: {msg}\n"
        f"  발견된 리터럴: {matches[:5]}"
    )


# ── 2. deploy job DEPLOY_ENABLED 게이트 ──────────────────────────────────────

_deploy_ids = [wf.name for wf in _deploy_workflow_files()]


@pytest.mark.parametrize("wf_path", _deploy_workflow_files(), ids=_deploy_ids)
def test_deploy_job_has_deploy_enabled_gate(wf_path: pathlib.Path) -> None:
    """deploy-*.yml 의 모든 배포 job 이 DEPLOY_ENABLED 게이트를 가져야 한다."""
    text = wf_path.read_text(encoding="utf-8")
    # job-level if: 는 4-space 들여쓰기 (jobs: 블록의 직속 step 아닌 job 조건)
    job_if_lines = [
        line.strip()
        for line in text.splitlines()
        if re.match(r'^ {4}if:\s', line)
    ]
    assert job_if_lines, (
        f"{wf_path.name}: 배포 job 에 if: 조건 없음 — DEPLOY_ENABLED 게이트 필수"
    )
    for line in job_if_lines:
        assert "DEPLOY_ENABLED" in line, (
            f"{wf_path.name}: 배포 job if 조건에 DEPLOY_ENABLED 없음: {line!r}"
        )


# ── 3. secrets fallback 리터럴 폴백 금지 ──────────────────────────────────────

_all_ids = [wf.name for wf in _all_workflow_files()]


@pytest.mark.parametrize("wf_path", _all_workflow_files(), ids=_all_ids)
def test_no_secrets_literal_fallback(wf_path: pathlib.Path) -> None:
    """secrets.X || 'literal' 폴백 패턴 금지 — 실패 시 하드코딩 대체값 노출."""
    text = wf_path.read_text(encoding="utf-8")
    matches = re.findall(
        r'\$\{\{[^}]*secrets\.[A-Z_]+\s*\|\|\s*[\'"][^\'"]{1,}[\'"][^}]*\}\}',
        text,
    )
    assert not matches, (
        f"{wf_path.name}: secrets fallback 리터럴 발견: {matches[:3]}"
    )
