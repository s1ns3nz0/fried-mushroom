"""로그 수집기 — uav raw_log 수신단 (스켈레톤).

uav(온보드)가 비행 후 일괄 전송하는 `raw_log`(무손실 원본 JSON)를 수신해
파일시스템에 임무당 1개로 저장한다. 이것이 ground/rag 학습 파이프의 입력 공급단이다.

2계층 중 1계층(raw_log) 담당:
- raw_log       : 파일시스템 JSON, 임무당 1개, 무손실 원본  ← 여기(collector)
- episode_index : SQLite + sqlite-vec, 검색 전용            ← aggregate.py + store.py

수신 방식 2안(택1 또는 병행):
- HTTP POST /raw_log : uav → 지상 직접 업로드
- 파일 watch        : 공유 디스크에 떨어진 raw_log 파일 감시

실시간 아님 — 착륙 후 일괄 수신(C2 링크 끊김 시 손상 방지).
→ 스키마: docs/architecture/ground/02-learning-rag.md (raw_log)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# raw_log 필수 최상위 키 (docs/architecture/ground/02-learning-rag.md).
RAW_LOG_KEYS = (
    "mission_id",
    "gps_track",             # [{ts, lat, lon, terrain_class}]
    "aircraft_state_series", # [{ts, battery_pct, attitude{roll,pitch,yaw}, speed_mps}]
    "threat_modeling_log",   # [{ts, threat_event, confidence, kill_chain_stage}]
    "risk_assessment_log",   # [{ts, l_class, severity, rac}]
)


class LogCollector:
    """uav raw_log 수신 → 파일시스템 저장.

    임무당 1개 파일(`raw/<mission_id>.json`)로 무손실 보관한다.
    저장 후 aggregate.py가 episode_index 구조화집계를 수행한다(별도 트리거).
    """

    def __init__(self, store_dir: str | Path = "raw") -> None:
        # TODO: store_dir 생성/보관. 저장 루트.
        self.store_dir = Path(store_dir)

    def validate(self, raw_log: dict[str, Any]) -> None:
        """raw_log 스키마 최소 검증(RAW_LOG_KEYS 존재 여부)."""
        # TODO: 필수 키 누락 시 예외. 값 타입 검증은 aggregate 단계와 분담.
        raise NotImplementedError

    def save(self, raw_log: dict[str, Any]) -> Path:
        """raw_log를 `<store_dir>/<mission_id>.json`으로 기록하고 경로 반환."""
        # TODO: validate 후 mission_id로 파일명 구성, json.dump. 반환 경로는 raw_log_ref.
        raise NotImplementedError

    def receive_post(self, body: bytes) -> Path:
        """HTTP POST /raw_log 바디(JSON) 수신 → save.

        업로드 방식 진입점. body를 파싱해 save로 위임.
        """
        # TODO: raw_log = json.loads(body); return self.save(raw_log)
        raise NotImplementedError

    def watch(self, watch_dir: str | Path) -> None:
        """공유 디스크(watch_dir)에 떨어진 raw_log 파일 감시 → save.

        파일 watch 방식 진입점(폴링 또는 inotify). 신규 파일 감지 시 save.
        """
        # TODO: watch_dir 폴링/감시 루프. 신규 *.json 감지 → load → save.
        raise NotImplementedError


# debt: 인증·재전송 중복 처리 없음. uav→지상 업로드 보안·멱등성 필요 시 업그레이드.
