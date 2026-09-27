"""One polling run: fetch vehicles from every provider, decide what moved, store it."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

import pymysql

from . import db
from .api import ApiError, Vehicle, fetch_vehicles
from .config import Config
from .gbfs import fetch_gbfs_vehicles
from .movement import LastPosition, should_record
from .providers import ProviderSpec

log = logging.getLogger(__name__)


class Store(Protocol):
    def latest_positions(self, provider: str, plates: Iterable[str]) -> dict[str, LastPosition]: ...
    def insert_movement(self, provider: str, v: Vehicle) -> None: ...
    def insert_snapshots(self, provider: str, vehicles: Sequence[Vehicle], observed_at: datetime) -> None: ...
    def now(self) -> datetime: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass
class PollResult:
    provider: str
    seen: int = 0
    recorded: int = 0
    first_sightings: int = 0
    snapshots: int = 0
    errors: int = 0
    failed: bool = False  # the provider could not be fetched


Fetcher = Callable[[Config, ProviderSpec], list[Vehicle]]


def fetch_from_provider(config: Config, provider: ProviderSpec) -> list[Vehicle]:
    if provider.is_gbfs:
        return fetch_gbfs_vehicles(provider.url, config.http_timeout)
    return fetch_vehicles(config.api_url, config.lat, config.lng, config.radius, config.http_timeout)


def poll_once(config: Config, store: Store, fetch: Fetcher = fetch_from_provider) -> list[PollResult]:
    """Poll every configured provider. Each provider is committed separately, so one
    failing provider (API down, DB error) doesn't affect the others."""
    return [poll_provider(config, store, provider, fetch) for provider in config.providers]


def poll_provider(config: Config, store: Store, provider: ProviderSpec, fetch: Fetcher) -> PollResult:
    result = PollResult(provider=provider.name)
    try:
        vehicles = _dedupe(fetch(config, provider))
    except ApiError as e:
        result.failed = True
        log.error("%s: %s", provider.name, e)
        return result
    result.seen = len(vehicles)
    try:
        observed_at = store.now()
        last = store.latest_positions(provider.name, (v.license_plate for v in vehicles))
        _record_movements(config, store, provider, vehicles, last, result)
        if config.stores_snapshots(provider):
            try:
                store.insert_snapshots(provider.name, vehicles, observed_at)
                result.snapshots = len(vehicles)
            except pymysql.MySQLError as e:
                result.errors += 1
                log.error("%s: storing snapshot failed: %s", provider.name, e)
        store.commit()
    except pymysql.MySQLError as e:
        result.failed = True
        log.error("%s: database error: %s", provider.name, e)
        store.rollback()
        return result
    log.info(
        "%s: %d vehicles seen, %d recorded (%d first sightings), %d snapshot rows, %d errors",
        provider.name,
        result.seen,
        result.recorded,
        result.first_sightings,
        result.snapshots,
        result.errors,
    )
    return result


def _record_movements(config, store, provider, vehicles, last, result) -> None:
    for v in vehicles:
        previous = last.get(v.license_plate)
        record, reason = should_record(v, previous, config.min_distance_m, config.require_range_change)
        if not record:
            log.debug("%s %s: skip (%s)", provider.name, v.license_plate, reason)
            continue
        try:
            store.insert_movement(provider.name, v)
        except pymysql.IntegrityError as e:
            result.errors += 1
            log.warning(
                "%s %s: insert rejected by a unique key (%s). Check the `go` table's keys, see docs/DATA_MODEL.md",
                provider.name,
                v.license_plate,
                e,
            )
            continue
        except pymysql.DataError as e:
            result.errors += 1
            log.warning("%s %s: value rejected (%s); did you run `migrate`?", provider.name, v.license_plate, e)
            continue
        except pymysql.MySQLError as e:
            result.errors += 1
            log.warning("%s %s: insert failed: %s", provider.name, v.license_plate, e)
            continue
        result.recorded += 1
        if previous is None:
            result.first_sightings += 1
        log.debug("%s %s: recorded (%s)", provider.name, v.license_plate, reason)


def run(config: Config, every: float | None = None, fetch: Fetcher = fetch_from_provider) -> int:
    """Poll once (``every`` is None) or forever every ``every`` seconds. Returns an exit code."""
    while True:
        started = time.monotonic()
        if every is None:
            return _run_one(config, fetch)
        try:
            _run_one(config, fetch)
        except Exception:  # keep a long-running poller alive; the next run may succeed
            log.exception("poll failed unexpectedly")
        time.sleep(max(0.0, every - (time.monotonic() - started)))


def _run_one(config: Config, fetch: Fetcher) -> int:
    """Exit codes: 0 ok, 1 at least one provider could not be fetched/stored, 2 database/schema problem."""
    try:
        conn = db.connect(config)
    except pymysql.MySQLError as e:
        log.error("cannot connect to the database: %s", e)
        return 2
    try:
        repo = db.Repository(conn)
        problems = repo.schema_problems(need_snapshots=any(config.stores_snapshots(p) for p in config.providers))
        if problems:
            log.error("database schema is not up to date (%s); run `./gopoll.py migrate`", "; ".join(problems))
            return 2
        results = poll_once(config, repo, fetch)
        return 1 if any(r.failed for r in results) else 0
    except pymysql.MySQLError as e:
        log.error("database error: %s", e)
        return 2
    finally:
        conn.close()


def _dedupe(vehicles: list[Vehicle]) -> list[Vehicle]:
    seen: set[str] = set()
    out = []
    for v in vehicles:
        if v.license_plate not in seen:
            seen.add(v.license_plate)
            out.append(v)
    return out
