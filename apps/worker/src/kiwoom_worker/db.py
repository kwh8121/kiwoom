from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from psycopg import AsyncConnection, DataError, IntegrityError
from psycopg.errors import RaiseException
from psycopg.types.json import Jsonb

from kiwoom_worker.runner import ConditionRefSnapshot, RunFailure


class SettlementRejected(Exception):
    """The database refused a settlement payload.

    The worker RPCs raise PAYLOAD_INVALID (SQLSTATE P0001) for a payload that
    violates the stored contract, and convert data and constraint errors into
    the same code. Re-sending the identical payload can never succeed, so this
    is reported separately from a transient database failure.
    """

    def __init__(self, operation: str, cause: Exception) -> None:
        self.operation = operation
        super().__init__(f"{operation} rejected the payload: {cause}")


@dataclass(frozen=True)
class ClaimedRun:
    # Issued by the claim and distinct per claim. Two processes can share a
    # configured worker id, so only this value identifies the lease holder.
    lease_owner: str
    run_id: str
    kind: str
    attempt: int
    profile_id: str
    alias: str
    mode: str
    definition: dict[str, Any] | None
    condition_refs: list[ConditionRefSnapshot]


class WorkerDb(Protocol):
    async def heartbeat(self, worker_id: str, aliases: list[str], version: str) -> None: ...

    async def claim(self, worker_id: str, aliases: list[str], lease_seconds: int) -> ClaimedRun | None: ...

    async def extend_lease(self, run_id: str, lease_owner: str, lease_seconds: int) -> bool: ...

    async def complete_search(self, run_id: str, lease_owner: str, payload: dict[str, object]) -> bool: ...

    async def complete_sync(self, run_id: str, lease_owner: str, items: list[dict[str, str]]) -> dict[str, object] | None: ...

    async def fail(self, run_id: str, lease_owner: str, failure: RunFailure) -> str | None: ...


class PostgresWorkerDb:
    def __init__(self, connection: AsyncConnection[Any]) -> None:
        self._connection = connection

    @classmethod
    async def connect(cls, url: str) -> PostgresWorkerDb:
        connection = await AsyncConnection.connect(url, autocommit=True)
        return cls(connection)

    async def close(self) -> None:
        await self._connection.close()

    async def heartbeat(self, worker_id: str, aliases: list[str], version: str) -> None:
        await self._fetch_one(
            "select worker.heartbeat(%s, %s, %s)",
            (worker_id, aliases, version),
        )

    async def claim(self, worker_id: str, aliases: list[str], lease_seconds: int) -> ClaimedRun | None:
        payload = await self._fetch_scalar(
            "select worker.claim_next_run(%s, %s, %s)",
            (worker_id, aliases, lease_seconds),
        )
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise TypeError("worker.claim_next_run returned non-object payload")

        profile = payload.get("profile")
        if not isinstance(profile, dict):
            raise TypeError("worker.claim_next_run profile payload missing")

        raw_refs = payload.get("condition_refs") or []
        if not isinstance(raw_refs, list):
            raise TypeError("worker.claim_next_run condition_refs payload must be a list")
        condition_refs = [
            ConditionRefSnapshot(
                condition_id=item["conditionId"],
                seq=item["seq"],
                name=item["name"],
            )
            for item in raw_refs
        ]

        definition = payload.get("definition")
        if definition is not None and not isinstance(definition, dict):
            raise TypeError("worker.claim_next_run definition payload must be an object")

        return ClaimedRun(
            lease_owner=str(payload["lease_owner"]),
            run_id=str(payload["run_id"]),
            kind=str(payload["kind"]),
            attempt=int(payload["attempt"]),
            profile_id=str(profile["id"]),
            alias=str(profile["alias"]),
            mode=str(profile["mode"]),
            definition=definition,
            condition_refs=condition_refs,
        )

    async def extend_lease(self, run_id: str, lease_owner: str, lease_seconds: int) -> bool:
        result = await self._fetch_scalar(
            "select worker.extend_lease(%s::uuid, %s, %s)",
            (run_id, lease_owner, lease_seconds),
        )
        return bool(result)

    async def complete_search(self, run_id: str, lease_owner: str, payload: dict[str, object]) -> bool:
        result = await self._settle(
            "complete_search_run",
            "select worker.complete_search_run(%s::uuid, %s, %s)",
            (run_id, lease_owner, Jsonb(payload)),
        )
        return bool(result)

    async def complete_sync(self, run_id: str, lease_owner: str, items: list[dict[str, str]]) -> dict[str, object] | None:
        result = await self._settle(
            "complete_sync_run",
            "select worker.complete_sync_run(%s::uuid, %s, %s)",
            (run_id, lease_owner, Jsonb(items)),
        )
        if result in (None, False):
            return None
        if not isinstance(result, dict):
            raise TypeError("worker.complete_sync_run returned non-object payload")
        return result

    async def fail(self, run_id: str, lease_owner: str, failure: RunFailure) -> str | None:
        result = await self._settle(
            "fail_run",
            "select worker.fail_run(%s::uuid, %s, %s, %s, %s, %s)",
            (
                run_id,
                lease_owner,
                failure.code,
                failure.message,
                failure.retryable,
                Jsonb(failure.partial),
            ),
        )
        if result is None:
            return None
        if not isinstance(result, str):
            raise TypeError("worker.fail_run returned non-string payload")
        return result

    async def _settle(self, operation: str, query: str, params: tuple[object, ...]) -> Any:
        try:
            return await self._fetch_scalar(query, params)
        except (RaiseException, DataError, IntegrityError) as exc:
            raise SettlementRejected(operation, exc) from exc

    async def _fetch_one(self, query: str, params: tuple[object, ...]) -> tuple[object, ...] | None:
        async with self._connection.cursor() as cursor:
            await cursor.execute(query, params)
            return await cursor.fetchone()

    async def _fetch_scalar(self, query: str, params: tuple[object, ...]) -> Any:
        row = await self._fetch_one(query, params)
        if row is None:
            return None
        return row[0]
