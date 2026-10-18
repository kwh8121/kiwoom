from __future__ import annotations

from collections.abc import Mapping

ALLOWED_API_IDS = frozenset({"au10001", "au10002", "ka10171", "ka10172"})
ALLOWED_TRNM = frozenset({"LOGIN", "PING", "CNSRLST", "CNSRREQ"})


class ForbiddenRequest(ValueError):
    pass


def assert_outgoing_allowed(packet: Mapping[str, object]) -> None:
    trnm = packet.get("trnm")
    if trnm not in ALLOWED_TRNM:
        raise ForbiddenRequest(f"forbidden trnm: {trnm!r}")

    if trnm == "CNSRREQ":
        if packet.get("search_type") != "0":
            raise ForbiddenRequest("CNSRREQ search_type must be '0'")
        if packet.get("stex_tp") != "K":
            raise ForbiddenRequest("CNSRREQ stex_tp must be 'K'")


def assert_api_id_allowed(api_id: str) -> None:
    if api_id not in ALLOWED_API_IDS:
        raise ForbiddenRequest(f"forbidden api_id: {api_id!r}")
