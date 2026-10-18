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
from kiwoom_worker.db import PostgresWorkerDb, WorkerDb
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
        await db.fail(claimed.run_id, settings.worker_id, RunFailure("PROFILE_CONFIG", False, "profile alias not configured", []))
        return True
    if creds.mode != claimed.mode:
        await db.fail(
            claimed.run_id,
            settings.worker_id,
            RunFailure("PROFILE_CONFIG", False, "profile mode does not match claimed run", []),
        )
        return True

    keepalive_task = asyncio.create_task(_keep_lease_alive(db, settings, claimed.run_id, clock))
    session_opener = lambda force_refresh: open_session_for(creds, force_refresh)

    try:
        try:
            await asyncio.sleep(0)
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
                    sync_items = None
                else:
                    payload = None
                    sync_items = await execute_sync(session_opener)
        except TimeoutError:
            await db.fail(claimed.run_id, settings.worker_id, RunFailure("RUN_TIMEOUT", False, "run exceeded timeout", []))
            return True
        except asyncio.CancelledError:
            raise
        except RunFailure as failure:
            await db.fail(claimed.run_id, settings.worker_id, failure)
            return True
        except Exception as exc:  # noqa: BLE001 -- classify arbitrary execution failures; DB settlement stays outside this handler.
            await db.fail(claimed.run_id, settings.worker_id, to_run_failure(exc, []))
            return True

        if payload is not None:
            if not await db.complete_search(claimed.run_id, settings.worker_id, payload):
                LOGGER.warning("lease lost before search completion for run %s", claimed.run_id)
        elif not await db.complete_sync(claimed.run_id, settings.worker_id, sync_items or []):
            LOGGER.warning("lease lost before sync completion for run %s", claimed.run_id)
        return True
    finally:
        keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keepalive_task


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
        await db.heartbeat(settings.worker_id, aliases, APP_VERSION)
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


async def _keep_lease_alive(db: WorkerDb, settings: WorkerSettings, run_id: str, clock: Clock) -> None:
    interval = max(settings.lease_seconds / 3, 0.1)
    while True:
        await clock.sleep(interval)
        if not await db.extend_lease(run_id, settings.worker_id, settings.lease_seconds):
            LOGGER.warning("lease extension rejected for run %s", run_id)
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
