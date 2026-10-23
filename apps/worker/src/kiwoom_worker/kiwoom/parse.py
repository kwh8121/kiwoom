from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

_CODE_RE = re.compile(r"^(?P<prefix>[AJQ])(?P<code>[0-9A-Z]{6})$")
_INSTRUMENT_TYPES = {"A": "stock", "J": "elw", "Q": "etn"}


class InvalidCode(ValueError):
    pass


@dataclass(frozen=True)
class Member:
    code: str
    raw_code: str
    instrument_type: str
    name: str | None
    price: int | None
    change_rate: Decimal | None


def normalize_code(raw: str) -> tuple[str, str]:
    match = _CODE_RE.fullmatch(raw)
    if match is None:
        raise InvalidCode(f"invalid Kiwoom code: {raw!r}")
    prefix = match.group("prefix")
    return match.group("code"), _INSTRUMENT_TYPES[prefix]


def parse_signed_int(value: str | None) -> int | None:
    if value is None:
        return None
    return int(value)


def parse_change_rate(value: str | None) -> Decimal | None:
    parsed = parse_signed_int(value)
    if parsed is None:
        return None
    return (Decimal(parsed) / Decimal(100)).quantize(Decimal("0.00"))


def parse_member(row: Mapping[str, object]) -> Member:
    raw_code = _require_str(row, "9001")
    code, instrument_type = normalize_code(raw_code)
    price = parse_signed_int(_optional_str(row, "10"))
    return Member(
        code=code,
        raw_code=raw_code,
        instrument_type=instrument_type,
        name=_optional_str(row, "302"),
        price=abs(price) if price is not None else None,
        change_rate=parse_change_rate(_optional_str(row, "12")),
    )


def _require_str(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise TypeError(f"expected string field {key!r}")
    return value


def _optional_str(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"expected string field {key!r}")
    return value
