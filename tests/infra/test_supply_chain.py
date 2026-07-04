"""공급망 재현성 회귀 가드 (#242).

infra/log·infra/dashboard requirements.txt 의 모든 패키지가 == 버전 핀을 가지는지,
infra/log/Dockerfile base image 가 SHA-256 다이제스트 고정을 사용하는지 assert.

DevSecOps 감사 F-06/F-07 — 빌드 재현성 보장.
src/onboard, src/gcs, infra/sim 무접촉.
"""

import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
_LOG_REQ = _REPO / "infra" / "log" / "requirements.txt"
_DASH_REQ = _REPO / "infra" / "dashboard" / "requirements.txt"
_LOG_DOCKERFILE = _REPO / "infra" / "log" / "Dockerfile"


def _requirement_lines(path: pathlib.Path) -> list[str]:
    """의미 있는 requirements 줄만 반환 (주석·공백 제외)."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return lines


# ── 1. requirements.txt 버전 핀 ───────────────────────────────────────────────

@pytest.mark.parametrize("req_path", [_LOG_REQ, _DASH_REQ], ids=["log", "dashboard"])
def test_requirements_all_pinned(req_path: pathlib.Path) -> None:
    """requirements.txt 의 모든 패키지가 == 버전 핀을 가져야 한다.

    extras (uvicorn[standard]) 허용, 단 버전은 == 로 명시 필수.
    """
    unpinned = []
    for line in _requirement_lines(req_path):
        # 패키지명만 있거나 >=, <=, ~=, != 핀인 경우 실패
        if "==" not in line:
            unpinned.append(line)

    assert not unpinned, (
        f"{req_path.relative_to(_REPO)}: == 버전 핀 없는 패키지: {unpinned}\n"
        "  → `package==X.Y.Z` 형식으로 핀해 빌드 재현성 보장 (F-07)"
    )


# ── 2. Dockerfile base image digest 고정 ─────────────────────────────────────

def test_log_dockerfile_base_image_digest_pinned() -> None:
    """infra/log/Dockerfile 의 FROM 지시어가 @sha256: 다이제스트를 포함해야 한다.

    태그 단독 사용(python:3.11-slim)은 태그 재할당 시 이미지가 바뀌어 재현성 깨짐(F-06).
    """
    text = _LOG_DOCKERFILE.read_text(encoding="utf-8")
    from_lines = [l.strip() for l in text.splitlines() if re.match(r"^FROM\b", l.strip(), re.IGNORECASE)]
    assert from_lines, f"{_LOG_DOCKERFILE.name}: FROM 지시어를 찾을 수 없음"

    for line in from_lines:
        assert "@sha256:" in line, (
            f"{_LOG_DOCKERFILE.name}: FROM 지시어에 SHA-256 다이제스트 없음: {line!r}\n"
            "  → `FROM image:tag@sha256:<digest>` 형식으로 고정 (F-06)"
        )
