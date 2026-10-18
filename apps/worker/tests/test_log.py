from __future__ import annotations

import logging

import pytest

from kiwoom_worker.log import RedactingFilter


def test_redacting_filter_masks_secret() -> None:
    record = logging.LogRecord(
        name="kiwoom-worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="token=%s payload=%r",
        args=("top-secret", {"nested": "top-secret"}),
        exc_info=None,
    )

    allowed = RedactingFilter(["top-secret"]).filter(record)

    assert allowed is True
    assert record.args == ()
    assert record.getMessage() == "token=*** payload={'nested': '***'}"


def test_redacting_filter_masks_rendered_objects_keys_and_tracebacks() -> None:
    try:
        raise ValueError("maskme")
    except ValueError as error:
        record = logging.LogRecord(
            name="kiwoom-worker",
            level=logging.ERROR,
            pathname=__file__,
            lineno=30,
            msg="failure=%s payload=%r",
            args=(error, {"maskme": "value"}),
            exc_info=(type(error), error, error.__traceback__),
        )

    RedactingFilter(["maskme"]).filter(record)
    rendered = logging.Formatter().format(record)

    assert "maskme" not in rendered
    assert record.args == ()
    assert record.exc_text is not None
    assert "maskme" not in record.exc_text


@pytest.mark.parametrize("secret", ["line1\nline2", "quote'backslash\\value"])
def test_redacting_filter_masks_secrets_before_percent_r_escaping(secret: str) -> None:
    record = logging.LogRecord(
        name="kiwoom-worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=50,
        msg="payload=%r",
        args=({"sensitive-key": secret},),
        exc_info=None,
    )

    RedactingFilter([secret]).filter(record)
    rendered = logging.Formatter().format(record)

    assert secret not in rendered
    assert repr(secret)[1:-1] not in rendered


def test_redacting_filter_masks_escaped_custom_object_repr() -> None:
    secret = "line1\nline2"

    class SecretValue:
        def __str__(self) -> str:
            return secret

        def __repr__(self) -> str:
            return repr(secret)

    record = logging.LogRecord(
        name="kiwoom-worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=80,
        msg="payload=%r",
        args=({"value": SecretValue()},),
        exc_info=None,
    )

    RedactingFilter([secret]).filter(record)
    rendered = logging.Formatter().format(record)

    assert secret not in rendered
    assert repr(secret)[1:-1] not in rendered

