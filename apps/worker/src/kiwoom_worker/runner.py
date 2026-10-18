from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from kiwoom_worker.clock import Clock
from kiwoom_worker.core.expr import (
    ConditionInfo,
    evaluate,
    leaf_condition_ids,
    validate_definition,
)
from kiwoom_worker.kiwoom.errors import ErrorClass, KiwoomApiError
from kiwoom_worker.kiwoom.parse import Member
from kiwoom_worker.kiwoom.session import (
    ConditionItem,
    ConditionSession,
    IncompletePagination,
    ProtocolError,
    ResponseTimeout,
    SearchResult,
)

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class ConditionRefSnapshot:
    condition_id: str
    seq: str
    name: str


@dataclass(frozen=True)
class SearchJob:
    run_id: str
    profile_id: str
    definition: dict[str, Any]
    condition_refs: list[ConditionRefSnapshot]


SessionOpener = Callable[[bool], AbstractAsyncContextManager[ConditionSession]]


class RunFailure(Exception):
    def __init__(self, code: str, retryable: bool, message: str, partial: list[dict[str, object]]) -> None:
        self.code = code
        self.retryable = retryable
        self.message = message
        self.partial = partial
        super().__init__(message)


class _AttemptFailed(Exception):
    def __init__(self, cause: BaseException, partial: list[dict[str, object]]) -> None:
        self.cause = cause
        self.partial = partial
        super().__init__(str(cause))


def to_run_failure(exc: BaseException, partial: list[dict[str, object]]) -> RunFailure:
    if isinstance(exc, RunFailure):
        return exc

    if isinstance(exc, KiwoomApiError):
        code_map = {
            ErrorClass.RATE_LIMIT: ("RATE_LIMITED", True),
            ErrorClass.TOKEN_EXPIRED: ("TOKEN_INVALID", False),
            ErrorClass.IP_DEVICE: ("IP_DEVICE_AUTH", False),
            ErrorClass.CONFIG: ("PROFILE_CONFIG", False),
            ErrorClass.CONDITION_MISSING: ("CONDITION_CHANGED", False),
            ErrorClass.INPUT: ("KIWOOM_INPUT", False),
            ErrorClass.TRANSIENT: ("KIWOOM_TRANSIENT", True),
            ErrorClass.UNKNOWN: ("KIWOOM_UNKNOWN", False),
        }
        code, retryable = code_map[exc.error_class]
        return RunFailure(code, retryable, exc.message, partial)

    if isinstance(exc, ResponseTimeout):
        return RunFailure("RESPONSE_TIMEOUT", True, str(exc), partial)
    if isinstance(exc, IncompletePagination):
        return RunFailure("INCOMPLETE_PAGINATION", True, str(exc), partial)
    if isinstance(exc, ProtocolError):
        return RunFailure("KIWOOM_PROTOCOL", False, str(exc), partial)
    if isinstance(exc, OSError):
        return RunFailure("KIWOOM_TRANSIENT", True, str(exc), partial)
    return RunFailure("KIWOOM_UNKNOWN", False, str(exc), partial)


def market_phase(at: datetime) -> Literal["pre", "regular", "post", "weekend"]:
    local = at.astimezone(KST) if at.tzinfo is not None else at.replace(tzinfo=KST)
    if local.weekday() >= 5:
        return "weekend"
    if (local.hour, local.minute, local.second) < (9, 0, 0):
        return "pre"
    if (local.hour, local.minute, local.second) < (15, 30, 0):
        return "regular"
    return "post"


async def execute_search(job: SearchJob, open_session: SessionOpener, clock: Clock) -> dict[str, object]:
    issues = validate_definition(
        job.definition,
        {ref.condition_id: ConditionInfo(job.profile_id, True) for ref in job.condition_refs},
    )
    if issues:
        raise RunFailure("INVALID_DEFINITION", False, ", ".join(issues), [])

    refs_by_id = {ref.condition_id: ref for ref in job.condition_refs}
    ordered_refs = [refs_by_id[condition_id] for condition_id in leaf_condition_ids(job.definition["expr"])]

    for force_refresh in (False, True):
        try:
            return await _execute_search_once(job, ordered_refs, open_session, force_refresh, clock)
        except _AttemptFailed as exc:
            if not force_refresh and _is_token_expired(exc.cause):
                continue
            raise to_run_failure(exc.cause, exc.partial) from exc.cause
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not force_refresh and _is_token_expired(exc):
                continue
            if isinstance(exc, RunFailure):
                raise
            raise to_run_failure(exc, []) from exc

    raise AssertionError("unreachable")


async def execute_sync(open_session: SessionOpener) -> list[dict[str, str]]:
    async with open_session(False) as session:
        return [{"seq": item.seq, "name": item.name} for item in await session.list_conditions()]


async def _execute_search_once(
    job: SearchJob,
    ordered_refs: list[ConditionRefSnapshot],
    open_session: SessionOpener,
    force_refresh: bool,
    clock: Clock,
) -> dict[str, object]:
    partial: list[dict[str, object]] = []
    async with open_session(force_refresh) as session:
        listed_conditions = await session.list_conditions()
        _verify_condition_refs(ordered_refs, listed_conditions)

        sets: dict[str, frozenset[str]] = {}
        snapshots: list[dict[str, object]] = []

        for ref in ordered_refs:
            started_at = clock.now()
            try:
                result = await session.search(ref.seq)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                partial.append(
                    _partial_entry(
                        ref,
                        started_at=started_at,
                        completed_at=clock.now(),
                        page_count=None,
                        row_count=None,
                        error_code=_partial_error_code(exc),
                    )
                )
                raise _AttemptFailed(exc, partial) from exc

            sets[ref.condition_id] = frozenset(member.code for member in result.members)
            snapshots.append(_snapshot_entry(ref, result))
            partial.append(
                _partial_entry(
                    ref,
                    started_at=result.started_at,
                    completed_at=result.completed_at,
                    page_count=result.page_count,
                    row_count=len(result.members),
                    error_code=None,
                )
            )

        evaluated = evaluate(job.definition["expr"], sets)
        return {
            "window_start": snapshots[0]["started_at"],
            "window_end": snapshots[-1]["completed_at"],
            "market_phase": market_phase(datetime.fromisoformat(snapshots[0]["started_at"])),
            "snapshots": snapshots,
            "results": [
                {"code": code, "matched_condition_ids": evaluated.matches[code]}
                for code in evaluated.codes
            ],
            "excluded_codes": evaluated.excluded,
        }


def _verify_condition_refs(ordered_refs: list[ConditionRefSnapshot], items: list[ConditionItem]) -> None:
    names_by_seq = {item.seq: item.name for item in items}
    for ref in ordered_refs:
        actual_name = names_by_seq.get(ref.seq)
        if actual_name != ref.name:
            partial = [
                _partial_entry(
                    ref,
                    started_at=None,
                    completed_at=None,
                    page_count=None,
                    row_count=None,
                    error_code="CONDITION_CHANGED",
                )
            ]
            actual_label = actual_name if actual_name is not None else "<missing>"
            raise RunFailure(
                "CONDITION_CHANGED",
                False,
                f"condition changed for seq={ref.seq}: expected={ref.name!r}, actual={actual_label!r}",
                partial,
            )


def _snapshot_entry(ref: ConditionRefSnapshot, result: SearchResult) -> dict[str, object]:
    return {
        "condition_id": ref.condition_id,
        "seq": ref.seq,
        "name": ref.name,
        "started_at": result.started_at.isoformat(),
        "completed_at": result.completed_at.isoformat(),
        "page_count": result.page_count,
        "members": [_member_payload(member) for member in result.members],
    }


def _member_payload(member: Member) -> dict[str, object]:
    return {
        "code": member.code,
        "raw_code": member.raw_code,
        "instrument_type": member.instrument_type,
        "name": member.name,
        "price": member.price,
        "change_rate": _decimal_to_string(member.change_rate),
    }


def _decimal_to_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _partial_entry(
    ref: ConditionRefSnapshot,
    *,
    started_at: datetime | None,
    completed_at: datetime | None,
    page_count: int | None,
    row_count: int | None,
    error_code: str | None,
) -> dict[str, object]:
    return {
        "condition_id": ref.condition_id,
        "seq": ref.seq,
        "name": ref.name,
        "started_at": started_at.isoformat() if started_at is not None else None,
        "completed_at": completed_at.isoformat() if completed_at is not None else None,
        "page_count": page_count,
        "row_count": row_count,
        "error_code": error_code,
    }


def _partial_error_code(exc: BaseException) -> str:
    return to_run_failure(exc, []).code


def _is_token_expired(exc: BaseException) -> bool:
    return isinstance(exc, KiwoomApiError) and exc.error_class is ErrorClass.TOKEN_EXPIRED
