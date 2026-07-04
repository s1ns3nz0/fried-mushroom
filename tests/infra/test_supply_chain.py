"""공급망 재현성 회귀 가드 (#242 #247).

#242: infra/log·infra/dashboard requirements.txt 모든 패키지 == 버전 핀,
      infra/log/Dockerfile base image SHA-256 다이제스트 고정.
#247: transitive 의존성 lock 파일(requirements.lock) 존재 + 전체 해시 포함,
      Dockerfile pip install --require-hashes 사용.

DevSecOps 감사 F-06/F-07 — 빌드 재현성 보장.
src/onboard, src/gcs, infra/sim 무접촉.
"""

import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
_LOG_REQ = _REPO / "infra" / "log" / "requirements.txt"
_DASH_REQ = _REPO / "infra" / "dashboard" / "requirements.txt"
_LOG_LOCK = _REPO / "infra" / "log" / "requirements.lock"
_DASH_LOCK = _REPO / "infra" / "dashboard" / "requirements.lock"
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


# ── 2. lock 파일 존재 + 전체 해시 포함 (#247) ────────────────────────────────

@pytest.mark.parametrize("lock_path", [_LOG_LOCK, _DASH_LOCK], ids=["log", "dashboard"])
def test_lock_file_exists(lock_path: pathlib.Path) -> None:
    """requirements.lock 파일이 존재해야 한다 (transitive 의존성 lock, F-07 확장)."""
    assert lock_path.exists(), (
        f"{lock_path.relative_to(_REPO)}: lock 파일 없음\n"
        "  → pip-compile --generate-hashes 로 생성 필요"
    )


@pytest.mark.parametrize("lock_path", [_LOG_LOCK, _DASH_LOCK], ids=["log", "dashboard"])
def test_lock_file_all_hashed(lock_path: pathlib.Path) -> None:
    """requirements.lock 의 모든 패키지 라인이 --hash=sha256: 를 가져야 한다."""
    if not lock_path.exists():
        pytest.skip("lock 파일 없음 — test_lock_file_exists 가 먼저 실패")

    text = lock_path.read_text(encoding="utf-8")
    # 패키지 라인: 공백 없이 시작하고 == 포함하거나 \로 끝나는 라인
    # pip-compile 출력: "package==X.Y.Z \\\n    --hash=sha256:..."
    # 패키지 헤더 줄: 공백 없이 시작, ==, \\ 로 끝남
    pkg_lines = [
        l.rstrip()
        for l in text.splitlines()
        if l and not l.startswith(" ") and not l.startswith("#") and "==" in l
    ]
    assert pkg_lines, f"{lock_path.name}: 패키지 라인 없음"

    unhashed = [l for l in pkg_lines if not l.endswith("\\")]
    assert not unhashed, (
        f"{lock_path.name}: --hash 없는 패키지 (단독 줄, \\로 끝나지 않음): {unhashed[:5]}\n"
        "  → pip-compile --generate-hashes 로 재생성 필요"
    )


# ── 3. Dockerfile base image digest 고정 ─────────────────────────────────────

def test_log_dockerfile_uses_require_hashes() -> None:
    """infra/log/Dockerfile 의 pip install 커맨드가 --require-hashes 를 사용해야 한다."""
    text = _LOG_DOCKERFILE.read_text(encoding="utf-8")
    pip_lines = [l.strip() for l in text.splitlines()
                 if "pip install" in l and not l.strip().startswith("#")]
    assert pip_lines, f"{_LOG_DOCKERFILE.name}: pip install 커맨드 없음"

    for line in pip_lines:
        assert "--require-hashes" in line, (
            f"{_LOG_DOCKERFILE.name}: pip install 에 --require-hashes 없음: {line!r}\n"
            "  → requirements.lock + --require-hashes 로 설치해 hash 검증 강제 (F-07)"
        )


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
