from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._sanitize(record.msg)
        record.args = self._sanitize(record.args)
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
            return {key: self._sanitize(item) for key, item in value.items()}
        return value
