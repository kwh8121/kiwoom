from __future__ import annotations

import json

import pytest

from kiwoom_worker.kiwoom.fixture import FixtureTransport


@pytest.mark.asyncio
async def test_fixture_transport_sends_bare_before_second_response() -> None:
    transport = FixtureTransport(
        {
            "conditions": [["0", "기본종목"]],
            "results": {
                "0": [
                    {"9001": "A005930", "302": "삼성전자", "10": "+070500", "12": "+000123"},
                    {"9001": "A035720", "302": "카카오, 테스트", "10": "+055000", "12": "+000045"},
                ]
            },
        }
    )

    await transport.send(json.dumps({"trnm": "LOGIN", "token": "fixture-token"}))
    assert json.loads(await transport.recv(1.0)) == {"trnm": "LOGIN", "return_code": 0}

    await transport.send(json.dumps({"trnm": "CNSRLST"}))
    assert json.loads(await transport.recv(1.0)) == {
        "trnm": "CNSRLST",
        "return_code": 0,
        "data": [["0", "기본종목"]],
    }

    await transport.send(json.dumps({"trnm": "CNSRREQ", "seq": "0", "search_type": "0", "stex_tp": "K"}))
    first_page = json.loads(await transport.recv(1.0))
    assert first_page["trnm"] == "CNSRREQ"
    assert first_page["seq"] == "0"
    assert first_page["cont_yn"] == "Y"
    assert first_page["next_key"] == "1"

    await transport.send(
        json.dumps(
            {
                "trnm": "CNSRREQ",
                "seq": "0",
                "search_type": "0",
                "stex_tp": "K",
                "cont_yn": "Y",
                "next_key": "1",
            }
        )
    )
    assert json.loads(await transport.recv(1.0)) == {"trnm": "CNSRREQ"}
    second_page = json.loads(await transport.recv(1.0))
    assert second_page["trnm"] == "CNSRREQ"
    assert second_page["seq"] == "0"
    assert second_page["cont_yn"] == "N"
    assert [row["302"] for row in second_page["data"]] == ["카카오, 테스트"]

