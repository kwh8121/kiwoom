from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from kiwoom_worker.kiwoom.parse import (
    InvalidCode,
    Member,
    normalize_code,
    parse_change_rate,
    parse_member,
    parse_signed_int,
)

FIXTURE = Path(__file__).with_name("fixtures") / "phase0_cnsrreq_seq1.json"


def test_normalize_alnum_code() -> None:
    assert normalize_code("A0010F0") == ("0010F0", "stock")


def test_normalize_prefixes() -> None:
    assert [normalize_code(code)[1] for code in ("A005930", "J123456", "Q500001")] == ["stock", "elw", "etn"]


def test_normalize_rejects_bad() -> None:
    with pytest.raises(InvalidCode):
        normalize_code("A00593")


def test_parse_signed_int_none() -> None:
    assert parse_signed_int(None) is None


def test_change_rate_8_digit() -> None:
    assert parse_change_rate("00000686") == Decimal("6.86")


def test_change_rate_negative() -> None:
    assert parse_change_rate("-0000252") == Decimal("-2.52")


def test_change_rate_9_digit_spec() -> None:
    assert parse_change_rate("000001500") == Decimal("15.00")


def test_phase0_fixture_parses() -> None:
    msg = json.loads(FIXTURE.read_text(encoding="utf-8"))
    members = [parse_member(row) for row in msg["data"]]

    assert len(members) == 28
    assert members[0] == Member("0010F0", "A0010F0", "stock", "보원케미칼", 3195, Decimal("6.86"))


def test_parse_member_uses_absolute_price() -> None:
    member = parse_member({"9001": "A005930", "302": "삼성전자", "10": "-000080500", "12": "-0000252"})

    assert member == Member("005930", "A005930", "stock", "삼성전자", 80500, Decimal("-2.52"))
