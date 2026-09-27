"""One polling run: fetch vehicles, decide what moved, store it."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Callable, Protocol

import pymysql

from . import db
from .api import ApiError, Vehicle, fetch_vehicles
from .config import Config
from .movement import LastPosition, should_record

log = logging.getLogger(__name__)


class Store(Protocol):
    def latest_positions(self, plates: Iterable[str]) -> dict[str, LastPosition]: ...
    def insert_movement(self, v: Vehicle) -> None: ...
    def insert_snapshots(self, vehicles: Sequence[Vehicle]) -> None: ...
    def commit(self) -> None: ...


@dataclass
class PollResult:
    seen: int = 0
    recorded: int = 0
    first_sightings: int = 0
    errors: int = 0


Fetcher = Callable[[Config], list[Vehicle]]


def fetch_from_api(config: Config) -> list[Vehicle]:
    return fetch_vehicles(config.api_url, config.lat, config.lng, config.radius, config.http_timeout)


def poll_once(config: Config, store: Store, fetch: Fetcher = fetch_from_api) -> PollResult:
    """Run one poll. Per-vehicle DB errors are logged and skipped; the rest is committed.

    Raises ApiError if the API can't be read (nothing is written in that case).
    """
    vehicles = _dedupe(fetch(config))
    result = PollResult(seen=len(vehicles))
    last = store.latest_positions(v.license_plate for v in vehicles)

    for v in vehicles:
        previous = last.get(v.license_plate)
        record, reason = should_record(v, previous, config.min_distance_m, config.require_range_change)
        if not record:
            log.debug("%s: skip (%s)", v.license_plate, reason)
            continue
        try:
            store.insert_movement(v)
        except pymysql.IntegrityError as e:
            result.errors += 1
            log.warning(
                "%s: insert rejected by a unique key (%s). Check the `go` table's keys, see docs/DATA_MODEL.md",
                v.license_plate,
                e,
            )
            continue
        except pymysql.MySQLError as e:
            result.errors += 1
            log.warning("%s: insert failed: %s", v.license_plate, e)
            continue
        result.recorded += 1
        if previous is None:
            result.first_sightings += 1
        log.debug("%s: recorded (%s)", v.license_plate, reason)

    if config.store_snapshots:
        try:
            store.insert_snapshots(vehicles)
        except pymysql.MySQLError as e:
            result.errors += 1
            log.error("storing snapshot failed (did you run `init-db`?): %s", e)

    store.commit()
    log.info(
        "poll done: %d vehicles seen, %d recorded (%d first sightings), %d errors",
        result.seen,
        result.recorded,
        result.first_sightings,
        result.errors,
    )
    return result


def run(config: Config, every: float | None = None, fetch: Fetcher = fetch_from_api) -> int:
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
    try:
        conn = db.connect(config)
    except pymysql.MySQLError as e:
        log.error("cannot connect to the database: %s", e)
        return 2
    try:
        poll_once(config, db.Repository(conn), fetch)
        return 0
    except ApiError as e:
        log.error("%s", e)
        return 1
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
