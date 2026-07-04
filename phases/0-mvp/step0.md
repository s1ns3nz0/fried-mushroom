# Step 0: project-setup

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/PRD.md`
- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`

## 작업

D4D Python 파이프라인의 뼈대를 만든다. 이 step은 코드 로직 없이 빈 패키지·설정 파일만 생성한다.

### 1) `pyproject.toml`

프로젝트 메타·pytest 설정을 하나의 파일에 담는다.

```toml
[project]
name = "d4d-pipeline"
version = "0.0.1"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-ra --strict-markers"
```

외부 의존성은 지금 넣지 말 것 (다음 step들에서 필요할 때 추가).

### 2) 디렉토리 뼈대

`ARCHITECTURE.md`의 "디렉토리 구조" 그대로 만든다. 각 디렉토리마다 빈 `__init__.py`를 둔다. `run.py`·채널별 모듈 파일들은 이 step에서는 만들지 않는다 (다음 step에서 생성).

만들 디렉토리:

```
src/onboard/
src/onboard/layer_02_sensor/
src/onboard/layer_03_abstraction/
src/onboard/layer_04_threat/
src/onboard/layer_05_risk/
src/onboard/layer_06_response/
src/onboard/layer_07_planning/
src/onboard/ai_stubs/
examples/
tests/
tests/layer_03_abstraction/
tests/layer_04_threat/
tests/layer_05_risk/
tests/layer_06_response/
tests/layer_07_planning/
tests/integration/
```

`tests/` 하위에도 `__init__.py`가 필요하다 (같은 이름의 test 모듈이 충돌하지 않도록).

### 3) 최소 smoke test

이 step의 AC를 통과시키기 위한 dummy 테스트를 `tests/test_smoke.py`에 하나 둔다:

```python
def test_python_version() -> None:
    import sys
    assert sys.version_info >= (3, 11)
```

### 4) `.gitignore` 갱신

기존 `.gitignore`를 읽고 아래 항목이 없으면 추가:

```
__pycache__/
*.pyc
.pytest_cache/
.venv/
*.egg-info/
```

## Acceptance Criteria

```bash
python3 -m pytest -v
```

- exit code 0
- `test_smoke.py::test_python_version` PASSED

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - `ARCHITECTURE.md`의 디렉토리 구조를 그대로 반영했는가?
   - 빈 `__init__.py`가 모든 패키지 디렉토리에 있는가?
   - `pyproject.toml`에 외부 의존성(numpy, pydantic 등)이 없는가?
3. 결과에 따라 `phases/0-mvp/index.json`의 step 0을 업데이트한다.

## 금지사항

- 채널별 모듈 파일(`position_consistency.py` 등)을 이 step에서 생성하지 마라. 이유: 이 step은 "빈 뼈대"만 다룬다. 다음 step들이 각자의 파일을 생성한다.
- `numpy`, `pydantic`, `pyyaml` 등 외부 의존성을 추가하지 마라. 이유: 표준 라이브러리로 충분히 커버되는지 먼저 확인한다. 필요하면 해당 step에서 명시적으로 추가.
- `src/onboard/shared/schemas.py`, `src/onboard/shared/constants.py`, `src/onboard/run.py`를 만들지 마라. 이유: step 1과 step 9에서 각각 다룬다.
- 기존 `docs/`, `scripts/`, `CLAUDE.md`, `phases/` 를 수정하지 마라.
