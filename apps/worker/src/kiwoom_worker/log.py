from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from traceback import format_exception


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = self._sanitize(record.getMessage())
        except Exception:  # noqa: BLE001 -- a broken log argument must never leak through unformatted.
            record.msg = "[log message redacted]"
        record.args = ()
        if record.exc_info is not None:
            record.exc_text = self._sanitize("".join(format_exception(*record.exc_info)))
        elif record.exc_text is not None:
            record.exc_text = self._sanitize(record.exc_text)
        return True

    def _sanitize(self, value: object) -> object:
        if isinstance(value, str):
            sanitized = value
            for secret in self._secrets:
                sanitized = sanitized.replace(secret, "***")
            return sanitized
        if isinstance(value, tuple):
            return tuple(self._sanitize(item) for item in value)
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, Mapping):
            return {self._sanitize(key): self._sanitize(item) for key, item in value.items()}
        return self._sanitize(str(value))
