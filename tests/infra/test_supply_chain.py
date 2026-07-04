"""공급망 재현성 회귀 가드 (#242 #247 #261).

#242: infra/log·infra/dashboard requirements.txt 모든 패키지 == 버전 핀,
      infra/log/Dockerfile base image SHA-256 다이제스트 고정.
#247: infra/log transitive 의존성 lock 파일(requirements.lock) 존재 + 전체 해시 포함,
      Dockerfile pip install --require-hashes 사용.
      (infra/dashboard 는 컨테이너 없는 정적자산/S3 → lock 불필요, requirements.txt 핀만 유지)
#261: lock hash 가드 강화 — continuation(\\) 없는 standalone `package==X.Y.Z` 엔트리도 탐지.

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


# ── 2. log lock 파일 존재 + 각 패키지 블록에 실제 hash 포함 (#247 #261) ──────


def _packages_without_hash(lock_text: str) -> list[str]:
    """lock 파일 텍스트에서 --hash=sha256: 없는 top-level 패키지 이름 반환.

    continuation(\\로 끝남) 유무와 무관하게 모든 top-level 패키지 라인을 검사 (#261).
    - 패키지 헤더: 공백 없이 시작, == 포함, # 로 시작하지 않음.
    - 헤더 직후 들여쓰기 continuation 블록에서 --hash=sha256: 탐색.
    """
    no_hash: list[str] = []
    lines = lock_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # top-level 패키지 헤더: 첫 글자가 영문, == 포함, 주석 아님
        if re.match(r"^[a-zA-Z]", line) and "==" in line and not line.lstrip().startswith("#"):
            pkg_name = line.split("==")[0].strip()
            found_hash = False
            j = i + 1
            # 헤더 다음 들여쓰기 블록 탐색 (continuation 유무 무관)
            while j < len(lines) and (lines[j].startswith("    ") or lines[j].startswith("\t")):
                if "--hash=sha256:" in lines[j]:
                    found_hash = True
                    break
                j += 1
            if not found_hash:
                no_hash.append(pkg_name)
        i += 1
    return no_hash


def test_lock_parser_catches_standalone_unhashed_entry() -> None:
    """_packages_without_hash 가 continuation 없는 un-hashed 엔트리를 탐지해야 한다 (#261).

    TDD 검증: 구 가드(\\로 끝남 조건)는 이 케이스를 skip했으나, 신 가드는 탐지해야 함.
    """
    synthetic = "\n".join([
        "# Generated lock",
        "good-pkg==1.0.0 \\",
        "    --hash=sha256:aabbcc",
        "    # via something",
        "bad-pkg==2.0.0",          # continuation 없고 hash도 없음 — 구 가드는 놓침
        "    # via other",
    ])
    result = _packages_without_hash(synthetic)
    assert result == ["bad-pkg"], (
        f"standalone un-hashed 패키지 탐지 실패: {result!r} (expected ['bad-pkg'])"
    )


def test_log_lock_file_exists() -> None:
    """infra/log/requirements.lock 파일이 존재해야 한다 (transitive 의존성 lock, F-07 확장).

    infra/dashboard 는 컨테이너 없는 정적자산(S3) → lock 불필요, requirements.txt 핀만 유지.
    """
    assert _LOG_LOCK.exists(), (
        f"infra/log/requirements.lock: lock 파일 없음\n"
        "  → pip-compile --generate-hashes infra/log/requirements.txt 로 생성 필요"
    )


def test_log_lock_each_package_has_hash() -> None:
    """infra/log/requirements.lock 의 모든 top-level 패키지에 --hash=sha256: 가 있어야 한다.

    continuation(\\) 유무 무관하게 모든 패키지 헤더를 검사 (#261 강화).
    _packages_without_hash 헬퍼를 통해 검증.
    """
    if not _LOG_LOCK.exists():
        pytest.skip("lock 파일 없음 — test_log_lock_file_exists 가 먼저 실패")

    no_hash = _packages_without_hash(_LOG_LOCK.read_text(encoding="utf-8"))
    assert not no_hash, (
        f"infra/log/requirements.lock: --hash=sha256: 없는 패키지: {no_hash[:5]}\n"
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
