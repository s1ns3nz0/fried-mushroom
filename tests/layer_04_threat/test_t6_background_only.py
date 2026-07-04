"""T6(환경노출도, 배경) 는 위협 후보가 아니라 배경정보 통과 지표임을 잠그는 locking 테스트.

## 결정 (issue #53, Task 1): (b) background-info-only — HIGH 노출도라도 T6 후보를 만들지 않는다.

D4D 문서가 세 곳에서 명시적으로 T6를 threat_event 후보에서 배제하고 노출도를 "가공 없이"
통과시키라고 규정한다:

- `docs/D4D/04. Threat Modeling.md:52` — 위협 표: "T6 | 환경노출도(배경) | threat_event 아님 — 별도 트랙(아래)".
- `docs/D4D/04. Threat Modeling.md:85` — "T6는 '이상 신호가 튀는 사건'이 아니라 ... 배경 위험도라,
  threat_event 후보에 넣지 않습니다. terrain_class ... exposure_score ... 를 가공 없이
  background_exposure_score로 Step D 출력에 항상 포함시키고, confidence·kill_chain_stage
  계산에는 넣지 않습니다."
- `docs/D4D/C-1. Threat Modeling Spec.md:91` — "T6 — 별도 트랙 (threat_event 아님)".
- `docs/contracts/04-threat-modeling-output.md:28` — "background_exposure_score ... T6(환경노출도,
  배경) 값. terrain_class.exposure_score(03)를 가공 없이 전달".
- `docs/D4D/05. Risk Assessment.md:22` — 노출도는 "exposure 기반 Medium 승격 없이 참고 지표로
  출력에 유지" (issue #24 Lead 결정, exposure≥0.7→Medium 승격 규칙 폐기).

상수 설계도 T6 후보화를 원천 차단한다 (후보가 생성되면 05 에서 경로 자체가 없어 크래시/스키마위반):
- `shared/constants.py` POTENTIAL_OUTCOME_MAP 에 T6 없음 → 04 Step D 가 "unknown" 을 붙여
  스키마 부적합 후보가 된다.
- `shared/constants.py` THREAT_CATEGORY 에 T6 없음 → 05 likelihood.base_rate("T6", ...) 가
  KeyError 로 즉시 크래시 (아래에서 실증).
- THREAT_CATALOG 에는 T6 가 표시용 라벨로만 존재(위협 처리 경로 아님).

따라서 shared/constants.py·docs 변경 없이, "고노출(0.8) 단독 + 활성위협 신호 없음 → candidates==[]
· primary==None, background_exposure_score 통과" 를 잠근다. 기존 동작을 확정하는 테스트라
작성 즉시 green 이다 (신규 구현 없음).
"""

from __future__ import annotations

import pytest

from onboard.layer_04_threat import run
from onboard.layer_05_risk import likelihood
from onboard.shared import constants as C

# terrain_class.exposure_score=0.8 은 배경노출 임계값(AMBIENT_EXPOSURE_THRESHOLD=0.7) 을 초과.
_HIGH_EXPOSURE = 0.8


class TestT6HighExposureYieldsNoCandidate:
    def test_high_exposure_alone_produces_no_candidate(self, abstraction_t6) -> None:
        """노출도 0.8(>0.7) 이 깔려 있어도 활성위협 신호가 없으면 후보/primary 를 만들지 않는다."""
        out = run.run(abstraction_t6)

        # 사전조건: 이 시나리오의 노출도가 실제로 HIGH(임계값 초과) 여야 검증이 유효.
        assert out["background_exposure_score"] == _HIGH_EXPOSURE
        assert out["background_exposure_score"] > C.AMBIENT_EXPOSURE_THRESHOLD

        # 핵심 잠금: T6 후보화 없음.
        assert out["candidates"] == []
        assert out["primary"] is None

    def test_background_exposure_passes_through_unprocessed(self, abstraction_t6) -> None:
        """노출도는 '가공 없이' Step D 출력에 통과된다 (04.md:85 / 04 contract:28)."""
        out = run.run(abstraction_t6)
        terrain = next(
            ch
            for ch in abstraction_t6["channels"]
            if ch["channel"] == "terrain_class"
        )
        # 입력 terrain_class.exposure_score 와 출력 background_exposure_score 가 동일(무가공).
        assert out["background_exposure_score"] == terrain["payload"]["exposure_score"]


class TestT6HasNoThreatProcessingPath:
    """T6 후보를 만들면 안 되는 근거를 상수 설계로 못박는다 (후보 생성 시 05 경로 부재)."""

    def test_t6_absent_from_potential_outcome_map(self) -> None:
        # Step D 가 T6 에 붙일 potential_outcome 이 없음 → "unknown"(스키마 부적합) 이 됨.
        assert "T6" not in C.POTENTIAL_OUTCOME_MAP

    def test_t6_absent_from_threat_category(self) -> None:
        # 05 의 base_rate 3분류(PHYSICAL/REMOTE/NAVIGATION) 에 T6 없음.
        assert "T6" not in C.THREAT_CATEGORY

    def test_t6_base_rate_lookup_would_crash(self) -> None:
        # 만약 T6 후보가 05 로 넘어가면 base_rate 조회가 KeyError 로 즉시 크래시한다.
        # (likelihood.base_rate 첫 줄 THREAT_CATEGORY[threat_event] 직접 인덱싱.)
        with pytest.raises(KeyError):
            likelihood.base_rate("T6", "정찰")

    def test_t6_is_catalog_display_label_only(self) -> None:
        # THREAT_CATALOG 에는 표시용 라벨로만 존재 — 위협 처리 경로(outcome/category) 는 없음.
        assert C.THREAT_CATALOG["T6"] == "환경노출도(배경)"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
