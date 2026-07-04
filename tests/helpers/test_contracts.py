"""tests/helpers/contracts.py 자체 검증 (TDD).

레이어 계약 헬퍼가 스키마 위반을 실제로 잡는지 확인한다.
"""

import json
import pathlib

import pytest

from onboard.shared.schemas import (
    AbstractionOutput,
    MissionBrief,
    ThreatCandidate,
    ThreatModelingOutput,
)

from tests.helpers.contracts import (
    assert_json_serializable,
    assert_matches_schema,
)

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _valid_abstraction() -> dict:
    return {
        "schema_version": "1.0",
        "id": "cycle-1",
        "ts": 1720000000,
        "channels": [
            {
                "channel": "gps",
                "state": "normal",
                "quality": 0.92,
                "quality_delta": 0.0,
                "payload": {"fix": "3d"},
            }
        ],
    }


def _valid_candidate() -> dict:
    return {
        "threat_event": "GPS_SPOOF",
        "match_count": 2,
        "confidence": 0.8,
        "confidence_source": "deterministic",
        "kill_chain_stage": "중기",
        "potential_outcome": "항법 드리프트",
    }


def _valid_threat_modeling() -> dict:
    return {
        "declared_phase": "ingress",
        "mission_phase_confidence": 0.7,
        "candidates": [_valid_candidate()],
        "primary": _valid_candidate(),
        "background_exposure_score": 0.3,
    }


class TestAssertMatchesSchema:
    def test_valid_mission_brief_passes(self) -> None:
        # golden fixture는 MissionBrief 스키마에 적합해야 한다 (raise 없음)
        assert_matches_schema(_load("mission_brief_t3.json"), MissionBrief)

    def test_missing_required_key_fails(self) -> None:
        obj = _load("mission_brief_t3.json")
        del obj["sortie_id"]
        with pytest.raises(AssertionError, match="sortie_id"):
            assert_matches_schema(obj, MissionBrief)

    def test_unknown_key_rejected(self) -> None:
        obj = _load("mission_brief_t3.json")
        obj["flght_context"] = "typo"  # 오타 필드
        with pytest.raises(AssertionError, match="flght_context"):
            assert_matches_schema(obj, MissionBrief)

    def test_wrong_scalar_type_fails(self) -> None:
        obj = _load("mission_brief_t3.json")
        obj["sortie_id"] = 123  # str이어야 함
        with pytest.raises(AssertionError, match="sortie_id"):
            assert_matches_schema(obj, MissionBrief)

    def test_literal_bad_value_fails(self) -> None:
        obj = _load("mission_brief_t3.json")
        obj["mission_context"] = "침투"  # Literal[정찰/타격/호송/수송] 밖
        with pytest.raises(AssertionError, match="mission_context"):
            assert_matches_schema(obj, MissionBrief)

    def test_literal_valid_value_passes(self) -> None:
        obj = _load("mission_brief_t3.json")
        obj["mission_context"] = "타격"  # Literal 안
        assert_matches_schema(obj, MissionBrief)

    def test_nested_list_typeddict_passes(self) -> None:
        assert_matches_schema(_valid_abstraction(), AbstractionOutput)

    def test_nested_list_typeddict_bad_elem_fails(self) -> None:
        obj = _valid_abstraction()
        obj["channels"][0]["state"] = "broken"  # ChannelState Literal 밖
        with pytest.raises(AssertionError, match=r"channels\[0\]\.state"):
            assert_matches_schema(obj, AbstractionOutput)

    def test_notrequired_absent_passes(self) -> None:
        assert_matches_schema(_valid_candidate(), ThreatCandidate)

    def test_notrequired_present_wrong_type_fails(self) -> None:
        obj = _valid_candidate()
        obj["context"] = 123  # NotRequired[dict] — dict이어야 함
        with pytest.raises(AssertionError, match="context"):
            assert_matches_schema(obj, ThreatCandidate)

    def test_union_none_member_passes(self) -> None:
        obj = _valid_threat_modeling()
        obj["primary"] = None  # ThreatCandidate | None
        assert_matches_schema(obj, ThreatModelingOutput)

    def test_union_typeddict_member_passes(self) -> None:
        assert_matches_schema(_valid_threat_modeling(), ThreatModelingOutput)

    def test_int_accepted_for_float_field(self) -> None:
        obj = _valid_candidate()
        obj["confidence"] = 1  # JSON은 float/int 구분 없음 — float 필드에 int 허용
        assert_matches_schema(obj, ThreatCandidate)

    def test_union_wrong_type_fails(self) -> None:
        obj = _valid_threat_modeling()
        obj["primary"] = 123  # ThreatCandidate 도 None 도 아님
        with pytest.raises(AssertionError, match="primary"):
            assert_matches_schema(obj, ThreatModelingOutput)

    def test_freeform_dict_accepts_anything(self) -> None:
        obj = _load("mission_brief_t3.json")
        # posture 는 free-form dict — 안쪽 구조는 재귀 검증하지 않는다
        obj["posture"] = {"임의키": [1, 2, {"nested": True}], "another": None}
        assert_matches_schema(obj, MissionBrief)


class TestShippedFixturesConform:
    """examples/ 에 커밋된 골든 fixture 가 스키마에 적합한지 회귀 잠금."""

    @pytest.mark.parametrize(
        "name",
        [
            "mission_brief_t3.json",
            "mission_brief_t4.json",
            "mission_brief_t7.json",
            "mission_brief_strike.json",
        ],
    )
    def test_mission_brief_fixture_matches_schema(self, name: str) -> None:
        obj = _load(name)
        assert_matches_schema(obj, MissionBrief)
        assert_json_serializable(obj)

    def test_strike_fixture_enables_weapon_drop(self) -> None:
        # 타격 시나리오: 소모성 무장 보유 → 06 payload_actions 가 WEAPON_DROP 부여 조건
        obj = _load("mission_brief_strike.json")
        assert obj["mission_context"] == "타격"
        assert any(a.get("expendable") is True for a in obj["drone_profile"]["armament"])


class TestAssertJsonSerializable:
    def test_plain_nested_dict_passes(self) -> None:
        assert_json_serializable(_load("mission_brief_t3.json"))

    def test_non_serializable_fails(self) -> None:
        obj = _load("mission_brief_t3.json")
        obj["posture"] = {"bad": {1, 2, 3}}  # set 은 JSON 직렬화 불가
        with pytest.raises(AssertionError):
            assert_json_serializable(obj)
