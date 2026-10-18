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
            record.msg = self._sanitize(record.msg)
            record.args = self._sanitize(record.args)
            rendered = record.getMessage()
        except Exception:  # noqa: BLE001 -- a broken log argument must never leak through unformatted.
            rendered = "[log message redacted]"
        record.msg = self._sanitize(rendered)
        record.args = ()
        if record.exc_info is not None:
            record.exc_text = self._replace_secrets("".join(format_exception(*record.exc_info)))
        elif record.exc_text is not None:
            record.exc_text = self._replace_secrets(record.exc_text)
        return True

    def _sanitize(self, value: object) -> object:
        if isinstance(value, str):
            return self._replace_secrets(value)
        if isinstance(value, tuple):
            return tuple(self._sanitize(item) for item in value)
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, Mapping):
            return {self._sanitize(key): self._sanitize(item) for key, item in value.items()}
        string_value = str(value)
        repr_value = repr(value)
        sanitized_string = self._replace_secrets(string_value)
        sanitized_repr = self._replace_secrets(repr_value)
        if sanitized_string == string_value and sanitized_repr == repr_value:
            return value
        return _SanitizedValue(sanitized_string, sanitized_repr)

    def _replace_secrets(self, value: str) -> str:
        sanitized = value
        for secret in self._secrets:
            sanitized = sanitized.replace(secret, "***")
        return sanitized


class _SanitizedValue:
    def __init__(self, string_value: str, repr_value: str) -> None:
        self._string_value = string_value
        self._repr_value = repr_value

    def __str__(self) -> str:
        return self._string_value

    def __repr__(self) -> str:
        return self._repr_value
