"""tests/infra/ 공통 fixture — infra/log sys.path 삽입.

이 conftest.py가 tests/infra/ 아래 모든 테스트에 infra/log 경로를 자동으로
sys.path에 추가한다. 각 테스트 파일의 개별 sys.path.insert는 불필요.
"""

import sys
from pathlib import Path

_INFRA_LOG = Path(__file__).resolve().parents[2] / "infra" / "log"
if str(_INFRA_LOG) not in sys.path:
    sys.path.insert(0, str(_INFRA_LOG))
