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
    assert record.args == ("***", {"nested": "***"})
    assert record.getMessage() == "token=*** payload={'nested': '***'}"

