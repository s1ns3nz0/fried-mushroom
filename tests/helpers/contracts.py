"""레이어 간 계약 테스트 헬퍼 (test-only, ADR-004: src 런타임 검증 없음).

TypedDict 스키마 대비 레이어 출력 dict 을 검증한다.
- assert_matches_schema: 필수 키 / 타입 / Literal 값 / 중첩 재귀, extra 키 reject.
- assert_json_serializable: JSON 라운드트립 가능 여부.
"""

from __future__ import annotations

import json
import types
import typing


def assert_matches_schema(obj: object, schema: type, _path: str = "<root>") -> None:
    """obj 가 TypedDict `schema` 에 적합한지 검증. 위반 시 AssertionError."""
    if not isinstance(obj, dict):
        raise AssertionError(f"{_path}: dict 기대, {type(obj).__name__} 받음")

    required = getattr(schema, "__required_keys__", frozenset())
    optional = getattr(schema, "__optional_keys__", frozenset())
    known = required | optional

    missing = required - obj.keys()
    if missing:
        raise AssertionError(f"{_path}: 필수 키 누락 {sorted(missing)}")

    extra = obj.keys() - known
    if extra:
        raise AssertionError(f"{_path}: 스키마에 없는 키 {sorted(extra)}")

    hints = typing.get_type_hints(schema)
    for key, ann in hints.items():
        if key in obj:
            _check_type(obj[key], ann, f"{_path}.{key}")


def assert_json_serializable(obj: object) -> None:
    """레이어 출력이 JSON 직렬화 가능한지 검증 (레이어 간 dict 계약, 아키텍처 규칙)."""
    try:
        json.dumps(obj, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"JSON 직렬화 불가: {exc}") from exc


def _check_type(value: object, ann: object, path: str) -> None:
    """value 가 annotation `ann` 에 적합한지 검증."""
    origin = typing.get_origin(ann)
    if origin is typing.Union or origin is types.UnionType:
        members = typing.get_args(ann)
        for member in members:
            if member is type(None):
                if value is None:
                    return
                continue
            try:
                _check_type(value, member, path)
                return
            except AssertionError:
                continue
        raise AssertionError(f"{path}: union 불일치 — {value!r} 은 {members} 중 어느 것도 아님")
    if origin is typing.Literal:
        allowed = typing.get_args(ann)
        if value not in allowed:
            raise AssertionError(f"{path}: Literal 밖 값 {value!r} (허용 {list(allowed)})")
        return
    if origin in (list, tuple):
        if not isinstance(value, list):
            raise AssertionError(f"{path}: list 기대, {type(value).__name__} 받음")
        args = typing.get_args(ann)
        if args:
            for i, elem in enumerate(value):
                _check_type(elem, args[0], f"{path}[{i}]")
        return
    if origin is None and typing.is_typeddict(ann):
        # 중첩 TypedDict → 재귀
        assert_matches_schema(value, ann, path)
        return
    if origin is None and isinstance(ann, type):
        # 평범한 타입 (str/int/float/dict/list).
        # JSON은 float/int를 구분하지 않으므로 float 필드에 int(단 bool 제외) 허용.
        if ann is float and isinstance(value, int) and not isinstance(value, bool):
            return
        if not isinstance(value, ann):
            raise AssertionError(
                f"{path}: 타입 불일치 — {ann.__name__} 기대, {type(value).__name__} 받음"
            )
