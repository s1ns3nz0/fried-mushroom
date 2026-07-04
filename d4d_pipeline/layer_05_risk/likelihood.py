"""05. Risk Assessment — likelihood 유틸리티.

THREAT_CATEGORY: 위협 → 3분류(PHYSICAL/REMOTE/NAVIGATION). 06이 import해 재사용.
"""

THREAT_CATEGORY: dict[str, str] = {
    "T1": "REMOTE",
    "T2": "REMOTE",
    "T5": "REMOTE",
    "T3": "PHYSICAL",
    "T4": "PHYSICAL",
    "T7": "NAVIGATION",
}
