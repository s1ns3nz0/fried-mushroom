"""tests/infra 공용 — infra/log 모듈을 sys.path 로 임포트 가능하게 한다.

CI(`testpaths=["tests"]`)가 infra/log 테스트를 수집하도록 tests/ 아래 둔다.
infra/log 는 배포 앱 패키지가 아니라 sys.path 삽입으로 import (파이프라인 무변경).
onboard 는 pyproject `pythonpath=["src"]` 로 이미 해석된다.
"""

import sys
from pathlib import Path

_INFRA_LOG = Path(__file__).resolve().parents[2] / "infra" / "log"
if str(_INFRA_LOG) not in sys.path:
    sys.path.insert(0, str(_INFRA_LOG))
