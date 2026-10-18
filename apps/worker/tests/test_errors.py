from __future__ import annotations

from kiwoom_worker.kiwoom.errors import (
    ErrorClass,
    KiwoomApiError,
    classify,
    resolve_return_code,
)


def test_classify_table() -> None:
    assert classify(105110) is ErrorClass.RATE_LIMIT
    assert classify(900004) is ErrorClass.CONDITION_MISSING
    assert classify(8010) is ErrorClass.IP_DEVICE


def test_classify_input_range() -> None:
    assert classify(1500) is ErrorClass.INPUT
    assert classify(1599) is ErrorClass.INPUT


def test_embedded_code() -> None:
    assert resolve_return_code(3, "[8005:Token이 유효하지 않습니다]") == 8005


def test_embedded_code_equals_syntax() -> None:
    assert resolve_return_code(None, "failed CODE=1700") == 1700


def test_unknown_top_level_code_without_embedded_match() -> None:
    assert resolve_return_code(42, "plain message") == 42


def test_numeric_string_top_level_does_not_count_as_return_code() -> None:
    assert resolve_return_code("8005", "plain message") is None


def test_bool_top_level_does_not_count_as_return_code() -> None:
    assert resolve_return_code(True, "plain message") is None


def test_float_top_level_does_not_count_as_return_code() -> None:
    assert resolve_return_code(8005.0, "plain message") is None


def test_recognized_top_level_int_beats_conflicting_embedded_code() -> None:
    assert resolve_return_code(900001, "[8005:Token이 유효하지 않습니다]") == 900001


def test_kiwoom_api_error_fields() -> None:
    error = KiwoomApiError(900001, "거래소 구분값을 확인해 주세요")

    assert error.return_code == 900001
    assert error.error_class is ErrorClass.CONFIG
    assert error.message == "거래소 구분값을 확인해 주세요"
    assert str(error) == "[CONFIG:900001] 거래소 구분값을 확인해 주세요"
