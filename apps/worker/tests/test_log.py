from __future__ import annotations

import logging

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

