from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from kiwoom_worker.runner import ConditionRefSnapshot, RunFailure


@dataclass(frozen=True)
class ClaimedRun:
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

    async def extend_lease(self, run_id: str, worker_id: str, lease_seconds: int) -> bool: ...

    async def complete_search(self, run_id: str, worker_id: str, payload: dict[str, object]) -> bool: ...

    async def complete_sync(self, run_id: str, worker_id: str, items: list[dict[str, str]]) -> dict[str, object] | None: ...

    async def fail(self, run_id: str, worker_id: str, failure: RunFailure) -> str | None: ...


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
            run_id=str(payload["run_id"]),
            kind=str(payload["kind"]),
            attempt=int(payload["attempt"]),
            profile_id=str(profile["id"]),
            alias=str(profile["alias"]),
            mode=str(profile["mode"]),
            definition=definition,
            condition_refs=condition_refs,
        )

    async def extend_lease(self, run_id: str, worker_id: str, lease_seconds: int) -> bool:
        result = await self._fetch_scalar(
            "select worker.extend_lease(%s::uuid, %s, %s)",
            (run_id, worker_id, lease_seconds),
        )
        return bool(result)

    async def complete_search(self, run_id: str, worker_id: str, payload: dict[str, object]) -> bool:
        result = await self._fetch_scalar(
            "select worker.complete_search_run(%s::uuid, %s, %s)",
            (run_id, worker_id, Jsonb(payload)),
        )
        return bool(result)

    async def complete_sync(self, run_id: str, worker_id: str, items: list[dict[str, str]]) -> dict[str, object] | None:
        result = await self._fetch_scalar(
            "select worker.complete_sync_run(%s::uuid, %s, %s)",
            (run_id, worker_id, Jsonb(items)),
        )
        if result in (None, False):
            return None
        if not isinstance(result, dict):
            raise TypeError("worker.complete_sync_run returned non-object payload")
        return result

    async def fail(self, run_id: str, worker_id: str, failure: RunFailure) -> str | None:
        result = await self._fetch_scalar(
            "select worker.fail_run(%s::uuid, %s, %s, %s, %s, %s)",
            (
                run_id,
                worker_id,
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

    async def _fetch_one(self, query: str, params: tuple[object, ...]) -> tuple[object, ...] | None:
        async with self._connection.cursor() as cursor:
            await cursor.execute(query, params)
            return await cursor.fetchone()

    async def _fetch_scalar(self, query: str, params: tuple[object, ...]) -> Any:
        row = await self._fetch_one(query, params)
        if row is None:
            return None
        return row[0]
