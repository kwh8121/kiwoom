from __future__ import annotations

import pytest

from kiwoom_worker.kiwoom.allowlist import (
    ALLOWED_API_IDS,
    ALLOWED_TRNM,
    ForbiddenRequest,
    assert_api_id_allowed,
    assert_outgoing_allowed,
)


def test_allowlist_constants() -> None:
    assert ALLOWED_API_IDS == frozenset({"au10001", "au10002", "ka10171", "ka10172"})
    assert ALLOWED_TRNM == frozenset({"LOGIN", "PING", "CNSRLST", "CNSRREQ"})


def test_forbid_realtime() -> None:
    with pytest.raises(ForbiddenRequest):
        assert_outgoing_allowed({"trnm": "CNSRREQ", "seq": "1", "search_type": "1", "stex_tp": "K"})


def test_forbid_exchange_other_than_krx() -> None:
    with pytest.raises(ForbiddenRequest):
        assert_outgoing_allowed({"trnm": "CNSRREQ", "seq": "1", "search_type": "0", "stex_tp": "N"})


def test_forbid_clear() -> None:
    with pytest.raises(ForbiddenRequest):
        assert_outgoing_allowed({"trnm": "CNSRCLR", "seq": "1"})


def test_forbid_order_api() -> None:
    with pytest.raises(ForbiddenRequest):
        assert_api_id_allowed("kt10000")


def test_allow_login_and_search_request() -> None:
    assert_outgoing_allowed({"trnm": "LOGIN"})
    assert_outgoing_allowed({"trnm": "PING"})
    assert_outgoing_allowed({"trnm": "CNSRLST"})
    assert_outgoing_allowed({"trnm": "CNSRREQ", "seq": "1", "search_type": "0", "stex_tp": "K"})


def test_allow_known_api_id() -> None:
    assert_api_id_allowed("ka10172")
