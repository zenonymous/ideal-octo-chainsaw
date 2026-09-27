"""MySQL/MariaDB access. All SQL lives here."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from importlib import resources

import pymysql

from .api import Vehicle
from .config import Config
from .movement import LastPosition
from .rides import Observation

log = logging.getLogger(__name__)

# Keep IN (...) lists to a sane size.
_CHUNK = 500
# Wide enough for GBFS vehicle ids (usually UUIDs, 36 chars).
ID_WIDTH = 64

SOURCES = {"movements": ("go", "date"), "snapshots": ("go_snapshot", "observed_at")}


def connect(config: Config) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=config.db_host,
        port=config.db_port,
        user=config.db_user,
        password=config.db_password,
        database=config.db_name,
        charset="utf8mb4",
        autocommit=False,
    )


@dataclass
class MigrationPlan:
    statements: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Repository:
    def __init__(self, conn):
        self.conn = conn

    # --- polling -------------------------------------------------------------

    def latest_positions(self, provider: str, plates: Iterable[str]) -> dict[str, LastPosition]:
        """Most recent `go` row for each of ``plates`` of ``provider``, in one query per chunk."""
        plates = sorted(set(plates))
        result: dict[str, LastPosition] = {}
        with self.conn.cursor() as cur:
            for i in range(0, len(plates), _CHUNK):
                chunk = plates[i : i + _CHUNK]
                marks = ", ".join(["%s"] * len(chunk))
                cur.execute(
                    "SELECT g.`licensePlate`, g.`lat`, g.`lng`, g.`remainingKilometers` "
                    "FROM `go` g JOIN ("
                    "  SELECT `licensePlate`, MAX(`date`) AS d FROM `go` "
                    f"  WHERE `provider` = %s AND `licensePlate` IN ({marks}) GROUP BY `licensePlate`"
                    ") m ON g.`licensePlate` = m.`licensePlate` AND g.`date` = m.d "
                    "WHERE g.`provider` = %s",
                    [provider, *chunk, provider],
                )
                for plate, lat, lng, km in cur.fetchall():
                    result[plate] = LastPosition(
                        lat=float(lat), lng=float(lng), remaining_km=None if km is None else float(km)
                    )
        return result

    def insert_movement(self, provider: str, v: Vehicle) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO `go` (`provider`, `id`, `licensePlate`, `stateOfCharge`, `lat`, `lng`, "
                "`remainingKilometers`) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (provider, v.id, v.license_plate, v.state_of_charge, v.lat, v.lng, v.remaining_km),
            )

    def insert_snapshots(self, provider: str, vehicles: Sequence[Vehicle], observed_at: datetime) -> None:
        if not vehicles:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO `go_snapshot` (`provider`, `observed_at`, `id`, `licensePlate`, `stateOfCharge`, "
                "`lat`, `lng`, `remainingKilometers`) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (provider, observed_at, v.id, v.license_plate, v.state_of_charge, v.lat, v.lng, v.remaining_km)
                    for v in vehicles
                ],
            )

    def now(self) -> datetime:
        """The database's current time, so snapshot timestamps match `DEFAULT CURRENT_TIMESTAMP`."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT CURRENT_TIMESTAMP")
            return cur.fetchone()[0]

    def schema_problems(self, need_snapshots: bool) -> list[str]:
        """What stops polling from working; empty if the schema is fine."""
        problems = []
        tables = self._tables()
        needed = ["go"] + (["go_snapshot"] if need_snapshots else [])
        for table in needed:
            if table not in tables:
                problems.append(f"table `{table}` is missing")
            elif "provider" not in self._columns(table):
                problems.append(f"table `{table}` has no `provider` column")
        return problems

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()

    # --- reporting -----------------------------------------------------------

    def load_observations(
        self,
        source: str = "movements",
        since: datetime | None = None,
        until: datetime | None = None,
        providers: Sequence[str] = (),
    ) -> list[Observation]:
        """Rows from ``go`` (movements) or ``go_snapshot`` (snapshots), ordered by provider, plate, time."""
        table, time_col = SOURCES[source]
        where, params = _filters(time_col, since, until, providers)
        sql = (
            f"SELECT `provider`, `licensePlate`, `{time_col}`, `lat`, `lng`, `remainingKilometers`, `stateOfCharge` "
            f"FROM `{table}`{where} ORDER BY `provider`, `licensePlate`, `{time_col}`"
        )
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [
                Observation(
                    plate=plate,
                    time=t,
                    lat=float(lat),
                    lng=float(lng),
                    remaining_km=None if km is None else float(km),
                    state_of_charge=None if soc is None else float(soc),
                    provider=provider,
                )
                for provider, plate, t, lat, lng, km, soc in cur.fetchall()
            ]

    def availability(
        self, since: datetime | None = None, until: datetime | None = None, providers: Sequence[str] = ()
    ) -> list[tuple[str, datetime, int]]:
        """(provider, observed_at, vehicles seen) per snapshot poll. Empty if there are no snapshots."""
        if "go_snapshot" not in self._tables():
            return []
        where, params = _filters("observed_at", since, until, providers)
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT `provider`, `observed_at`, COUNT(*) FROM `go_snapshot`{where} "
                "GROUP BY `provider`, `observed_at` ORDER BY `observed_at`",
                params,
            )
            return [(p, t, int(n)) for p, t, n in cur.fetchall()]

    # --- schema --------------------------------------------------------------

    def plan_migration(self) -> MigrationPlan:
        """Statements that bring the schema up to date. Creates missing tables and, for
        existing ones, adds `provider`, widens the id columns and adds indexes. Never drops
        or rewrites data."""
        plan = MigrationPlan()
        creates = _create_statements()
        tables = self._tables()
        for table, time_col in SOURCES.values():
            if table not in tables:
                plan.statements.append(creates[table])
                continue
            columns = self._columns(table)
            changes = []
            if "provider" not in columns:
                changes.append("ADD COLUMN `provider` VARCHAR(32) NOT NULL DEFAULT 'go_sharing'")
                plan.notes.append(f"`{table}`: existing rows get provider = 'go_sharing'")
            for name in ("id", "licensePlate"):
                change = _widen(table, name, columns.get(name), plan.notes)
                if change:
                    changes.append(change)
            first_cols = {tuple(cols[:2]) for cols in self._indexes(table).values()}
            if ("provider", "licensePlate") not in first_cols:
                changes.append(f"ADD KEY `idx_{table}_provider_plate_time` (`provider`, `licensePlate`, `{time_col}`)")
            if changes:
                plan.statements.append(f"ALTER TABLE `{table}`\n  " + ",\n  ".join(changes))
        return plan

    def migrate(self, plan: MigrationPlan) -> None:
        with self.conn.cursor() as cur:
            for statement in plan.statements:
                cur.execute(statement)
        self.conn.commit()

    def _tables(self) -> set[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()")
            return {row[0] for row in cur.fetchall()}

    def _columns(self, table: str) -> dict[str, dict]:
        with self.conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT COLUMN_NAME AS name, DATA_TYPE AS type, CHARACTER_MAXIMUM_LENGTH AS length, "
                "IS_NULLABLE AS nullable, COLUMN_DEFAULT AS dflt, EXTRA AS extra "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                (table,),
            )
            return {row["name"]: row for row in cur.fetchall()}

    def _indexes(self, table: str) -> dict[str, list[str]]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT INDEX_NAME, COLUMN_NAME FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s ORDER BY INDEX_NAME, SEQ_IN_INDEX",
                (table,),
            )
            indexes: dict[str, list[str]] = {}
            for name, column in cur.fetchall():
                indexes.setdefault(name, []).append(column)
            return indexes


_INT_TYPES = {"tinyint", "smallint", "mediumint", "int", "bigint"}


def _widen(table: str, name: str, col: dict | None, notes: list[str]) -> str | None:
    """MODIFY clause making ``name`` a VARCHAR(ID_WIDTH), or None if not needed/possible."""
    if col is None:
        notes.append(f"`{table}`.`{name}` is missing; the poller needs it, add it by hand")
        return None
    ctype, length = col["type"].lower(), col["length"]
    if ctype in ("varchar", "char") and length is not None and length >= ID_WIDTH:
        return None
    if ctype not in ("varchar", "char") and ctype not in _INT_TYPES:
        notes.append(f"`{table}`.`{name}` is {ctype}; left as is (GBFS ids may not fit)")
        return None
    if "auto_increment" in (col["extra"] or "").lower():
        notes.append(f"`{table}`.`{name}` is AUTO_INCREMENT; left as is")
        return None
    if col["dflt"] not in (None, "NULL"):
        notes.append(f"`{table}`.`{name}` has a default; left as is, widen it by hand if GBFS inserts fail")
        return None
    null = "NULL" if col["nullable"] == "YES" else "NOT NULL"
    if ctype in _INT_TYPES:
        notes.append(f"`{table}`.`{name}`: {ctype} -> VARCHAR({ID_WIDTH}) (numbers are kept as text)")
    else:
        notes.append(f"`{table}`.`{name}`: {ctype}({length}) -> VARCHAR({ID_WIDTH})")
    return f"MODIFY COLUMN `{name}` VARCHAR({ID_WIDTH}) {null}"


def _filters(
    time_col: str, since: datetime | None, until: datetime | None, providers: Sequence[str]
) -> tuple[str, list]:
    where, params = [], []
    if since is not None:
        where.append(f"`{time_col}` >= %s")
        params.append(since)
    if until is not None:
        where.append(f"`{time_col}` < %s")
        params.append(until)
    if providers:
        where.append(f"`provider` IN ({', '.join(['%s'] * len(providers))})")
        params.extend(providers)
    return (" WHERE " + " AND ".join(where) if where else ""), params


def _create_statements() -> dict[str, str]:
    sql = resources.files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    statements = [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
    creates = {}
    for statement in statements:
        m = re.match(r"CREATE TABLE IF NOT EXISTS `(\w+)`", statement)
        if m:
            creates[m.group(1)] = statement
    return creates
