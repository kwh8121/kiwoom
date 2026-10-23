from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from kiwoom_worker.clock import Clock, SystemClock
from kiwoom_worker.config import WorkerSettings, load_profiles, load_settings
from kiwoom_worker.db import PostgresWorkerDb, SettlementRejected, WorkerDb
from kiwoom_worker.kiwoom.fixture import FixtureTransport
from kiwoom_worker.kiwoom.session import ConditionSession
from kiwoom_worker.kiwoom.token import WS_URLS, Credentials, TokenProvider
from kiwoom_worker.kiwoom.transport import open_websocket
from kiwoom_worker.log import RedactingFilter
from kiwoom_worker.runner import (
    RunFailure,
    SearchJob,
    execute_search,
    execute_sync,
    to_run_failure,
)

LOGGER = logging.getLogger("kiwoom_worker.main")

OpenSessionFor = Callable[[Credentials, bool], AbstractAsyncContextManager[ConditionSession]]


async def process_one(
    db: WorkerDb,
    settings: WorkerSettings,
    profiles: dict[str, Credentials],
    open_session_for: OpenSessionFor,
    clock: Clock,
) -> bool:
    aliases = list(profiles)
    claimed = await db.claim(settings.worker_id, aliases, settings.lease_seconds)
    if claimed is None:
        return False

    creds = profiles.get(claimed.alias)
    if creds is None:
        await _fail_quietly(db, settings, claimed.run_id, RunFailure("PROFILE_CONFIG", False, "profile alias not configured", []))
        return True
    if creds.mode != claimed.mode:
        await _fail_quietly(
            db,
            settings,
            claimed.run_id,
            RunFailure("PROFILE_CONFIG", False, "profile mode does not match claimed run", []),
        )
        return True

    session_opener = lambda force_refresh: open_session_for(creds, force_refresh)
    # Losing the lease means the database may already have handed this run to
    # another worker. Carrying on would duplicate Kiwoom requests against a
    # shared rate limit, so the keepalive interrupts the work it can no longer
    # claim to own.
    lease_lost = asyncio.Event()
    execution: asyncio.Task[tuple[dict[str, Any] | None, list[dict[str, str]] | None]] | None = None

    def abandon_run() -> None:
        lease_lost.set()
        if execution is not None:
            execution.cancel()

    keepalive_task = asyncio.create_task(
        _keep_lease_alive(db, settings, claimed.run_id, clock, abandon_run)
    )

    try:
        try:
            await asyncio.sleep(0)
            execution = asyncio.create_task(
                _execute_claimed(claimed, settings, session_opener, clock)
            )
            if lease_lost.is_set():
                execution.cancel()
            payload, sync_items = await execution
        except asyncio.CancelledError:
            if lease_lost.is_set():
                LOGGER.warning(
                    "lease lost during run %s; abandoned the run without settling it",
                    claimed.run_id,
                )
                return True
            raise
        except TimeoutError:
            # Only the run budget reaches this branch. ResponseTimeout also
            # subclasses TimeoutError, so execute_search and execute_sync must
            # keep converting it into a retryable RunFailure first; otherwise a
            # single slow response is misreported as a run-wide timeout.
            await _fail_quietly(db, settings, claimed.run_id, RunFailure("RUN_TIMEOUT", False, "run exceeded timeout", []))
            return True
        except RunFailure as failure:
            await _fail_quietly(db, settings, claimed.run_id, failure)
            return True
        except Exception as exc:  # noqa: BLE001 -- classify arbitrary execution failures; DB settlement stays outside this handler.
            await _fail_quietly(db, settings, claimed.run_id, to_run_failure(exc, []))
            return True

        try:
            if payload is not None:
                if not await db.complete_search(claimed.run_id, settings.worker_id, payload):
                    LOGGER.warning("lease lost before search completion for run %s", claimed.run_id)
            elif not await db.complete_sync(claimed.run_id, settings.worker_id, sync_items or []):
                LOGGER.warning("lease lost before sync completion for run %s", claimed.run_id)
        except SettlementRejected as rejected:
            # Re-sending the same payload cannot succeed, so record the real
            # reason now instead of letting the lease expire and retry until the
            # run ends as a misleading LEASE_EXPIRED.
            LOGGER.error("settlement rejected for run %s: %s", claimed.run_id, rejected)
            await _fail_quietly(
                db,
                settings,
                claimed.run_id,
                RunFailure("SETTLE_REJECTED", False, str(rejected), []),
            )
        return True
    finally:
        keepalive_task.cancel()
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass
        except Exception:
            # A keepalive failure must not replace this run's own outcome.
            LOGGER.exception("lease keepalive failed for run %s", claimed.run_id)
        # On the shutdown path the await above was interrupted while the
        # execution task was still running, so it has to be stopped here too.
        if execution is not None and not execution.done():
            execution.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await execution


async def _execute_claimed(
    claimed: Any,
    settings: WorkerSettings,
    session_opener: Callable[[bool], AbstractAsyncContextManager[ConditionSession]],
    clock: Clock,
) -> tuple[dict[str, Any] | None, list[dict[str, str]] | None]:
    """Run the claimed job under its own run budget.

    This lives in a task of its own so the lease keepalive can cancel the
    broker work the moment the run stops being ours.
    """
    async with asyncio.timeout(settings.run_timeout_s):
        if claimed.kind == "search":
            payload = await execute_search(
                SearchJob(
                    run_id=claimed.run_id,
                    profile_id=claimed.profile_id,
                    definition=claimed.definition or {},
                    condition_refs=claimed.condition_refs,
                ),
                session_opener,
                clock,
            )
            return payload, None
        return None, await execute_sync(session_opener)


async def _fail_quietly(db: WorkerDb, settings: WorkerSettings, run_id: str, failure: RunFailure) -> None:
    """Record a terminal failure without letting the report itself end the worker.

    A rejected fail_run payload would otherwise crash the process, which leaves
    the run claimed until its lease expires and burns one of its attempts.
    """
    try:
        await db.fail(run_id, settings.worker_id, failure)
    except SettlementRejected:
        LOGGER.exception("could not record failure %s for run %s", failure.code, run_id)


async def run_worker(
    settings: WorkerSettings,
    db: WorkerDb,
    open_session_for: OpenSessionFor,
    clock: Clock,
    stop: asyncio.Event,
) -> None:
    profiles = load_profiles(settings.profiles_file)
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(_heartbeat_worker(db, settings, list(profiles), stop, clock))
        while not stop.is_set():
            handled = await process_one(db, settings, profiles, open_session_for, clock)
            if not handled:
                await _sleep_until_stop(stop, settings.poll_interval_s, clock)


async def _heartbeat_worker(
    db: WorkerDb,
    settings: WorkerSettings,
    aliases: list[str],
    stop: asyncio.Event,
    clock: Clock,
) -> None:
    while not stop.is_set():
        try:
            await db.heartbeat(settings.worker_id, aliases, APP_VERSION)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Liveness reporting is advisory. Aborting the task group here would
            # cancel an in-flight Kiwoom run over a transient database blip.
            LOGGER.exception("heartbeat failed for worker %s", settings.worker_id)
        await _sleep_until_stop(stop, settings.heartbeat_interval_s, clock)


def cli() -> None:
    settings = load_settings(os.environ)
    profiles = load_profiles(settings.profiles_file)
    _configure_logging(settings.database_url, profiles)
    asyncio.run(_run_cli(settings, profiles))


async def _run_cli(settings: WorkerSettings, profiles: dict[str, Credentials]) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            signal.signal(signum, lambda *_args: stop.set())

    db = await PostgresWorkerDb.connect(settings.database_url)
    clock = SystemClock()
    async with httpx.AsyncClient() as client:
        if settings.transport == "fixture":
            if settings.fixture_file is None:
                raise RuntimeError("fixture transport requires KIWOOM_WORKER_FIXTURE_FILE")
            market = json.loads(Path(settings.fixture_file).read_text(encoding="utf-8"))
            open_session_for = _fixture_session_opener(settings, market, clock)
        else:
            provider = TokenProvider(client, clock)
            open_session_for = _live_session_opener(settings, provider, clock)

        try:
            await run_worker(settings, db, open_session_for, clock, stop)
        finally:
            await db.close()


@asynccontextmanager
async def _open_session(
    settings: WorkerSettings,
    transport_factory: Callable[[], Any],
    token: str,
    clock: Clock,
):
    transport_result = transport_factory()
    transport = await transport_result if asyncio.iscoroutine(transport_result) else transport_result
    session = ConditionSession(
        transport,
        clock=clock,
        request_interval_s=settings.request_interval_s,
        response_timeout_s=settings.response_timeout_s,
        max_pages=settings.max_pages,
        rate_limit_retries=settings.rate_limit_retries,
    )
    try:
        await session.login(token)
        yield session
    finally:
        await transport.close()


def _live_session_opener(settings: WorkerSettings, provider: TokenProvider, clock: Clock) -> OpenSessionFor:
    def opener(creds: Credentials, force_token_refresh: bool):
        @asynccontextmanager
        async def _manager():
            token = await provider.get(creds, force_refresh=force_token_refresh)
            async with _open_session(
                settings,
                lambda: open_websocket(WS_URLS[creds.mode]),
                token,
                clock,
            ) as session:
                yield session

        return _manager()

    return opener


def _fixture_session_opener(settings: WorkerSettings, market: dict[str, Any], clock: Clock) -> OpenSessionFor:
    def opener(_creds: Credentials, _force_token_refresh: bool):
        @asynccontextmanager
        async def _manager():
            async with _open_session(
                settings,
                lambda: FixtureTransport(market),
                "fixture-token",
                clock,
            ) as session:
                yield session

        return _manager()

    return opener


async def _keep_lease_alive(
    db: WorkerDb,
    settings: WorkerSettings,
    run_id: str,
    clock: Clock,
    on_lease_lost: Callable[[], None],
) -> None:
    interval = max(settings.lease_seconds / 3, 0.1)
    while True:
        await clock.sleep(interval)
        if not await db.extend_lease(run_id, settings.worker_id, settings.lease_seconds):
            LOGGER.warning("lease extension rejected for run %s", run_id)
            on_lease_lost()
            return


async def _sleep_until_stop(stop: asyncio.Event, seconds: float, clock: Clock) -> None:
    sleeper = asyncio.create_task(clock.sleep(seconds))
    stopper = asyncio.create_task(stop.wait())
    done, pending = await asyncio.wait({sleeper, stopper}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    for task in done:
        if task is stopper:
            return


def _configure_logging(database_url: str, profiles: dict[str, Credentials]) -> None:
    logging.basicConfig(level=logging.INFO)
    secrets = [
        secret
        for creds in profiles.values()
        for secret in (creds.appkey, creds.secretkey)
        if secret
    ]
    password = urlsplit(database_url).password
    if password:
        secrets.append(password)
    redacting_filter = RedactingFilter(secrets)
    root_logger = logging.getLogger()
    root_logger.addFilter(redacting_filter)
    for handler in root_logger.handlers:
        handler.addFilter(redacting_filter)


def _detect_version() -> str:
    try:
        return version("kiwoom-worker")
    except PackageNotFoundError:
        return "0.1.0"


APP_VERSION = _detect_version()
