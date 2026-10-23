from __future__ import annotations

import re
from enum import StrEnum

_EMBEDDED_CODE_RE = re.compile(r"\[(\d+):|CODE=(\d+)")
_RATE_LIMIT_CODES = frozenset({105110, 1700, 1701, 1702})
_TOKEN_EXPIRED_CODES = frozenset({8005})
_IP_DEVICE_CODES = frozenset({8010, 8040, 8050, 8103})
_CONFIG_CODES = frozenset({8001, 8002, 8030, 8031, 8104, 900001})
_CONDITION_MISSING_CODES = frozenset({900004})
_TRANSIENT_CODES = frozenset({1999})


class ErrorClass(StrEnum):
    RATE_LIMIT = "RATE_LIMIT"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    IP_DEVICE = "IP_DEVICE"
    CONFIG = "CONFIG"
    CONDITION_MISSING = "CONDITION_MISSING"
    INPUT = "INPUT"
    TRANSIENT = "TRANSIENT"
    UNKNOWN = "UNKNOWN"


def resolve_return_code(return_code: object, return_msg: object) -> int | None:
    parsed_top_level = _coerce_int(return_code)
    if parsed_top_level is not None and classify(parsed_top_level) is not ErrorClass.UNKNOWN:
        return parsed_top_level

    embedded = _extract_embedded_code(return_msg)
    if embedded is not None:
        return embedded

    return parsed_top_level


def classify(code: int) -> ErrorClass:
    if code in _RATE_LIMIT_CODES:
        return ErrorClass.RATE_LIMIT
    if code in _TOKEN_EXPIRED_CODES:
        return ErrorClass.TOKEN_EXPIRED
    if code in _IP_DEVICE_CODES:
        return ErrorClass.IP_DEVICE
    if code in _CONFIG_CODES:
        return ErrorClass.CONFIG
    if code in _CONDITION_MISSING_CODES:
        return ErrorClass.CONDITION_MISSING
    if 1500 <= code <= 1599:
        return ErrorClass.INPUT
    if code in _TRANSIENT_CODES:
        return ErrorClass.TRANSIENT
    return ErrorClass.UNKNOWN


class KiwoomApiError(Exception):
    def __init__(self, return_code: int, message: str) -> None:
        self.return_code = return_code
        self.error_class = classify(return_code)
        self.message = message
        super().__init__(f"[{self.error_class}:{self.return_code}] {self.message}")


def _coerce_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _extract_embedded_code(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = _EMBEDDED_CODE_RE.search(value)
    if match is None:
        return None
    return int(match.group(1) or match.group(2))
