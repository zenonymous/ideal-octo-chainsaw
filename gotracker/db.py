"""MySQL/MariaDB access. All SQL lives here."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
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


class Repository:
    def __init__(self, conn):
        self.conn = conn

    def latest_positions(self, plates: Iterable[str]) -> dict[str, LastPosition]:
        """Most recent `go` row for each of ``plates``, in one query per chunk."""
        plates = sorted(set(plates))
        result: dict[str, LastPosition] = {}
        with self.conn.cursor() as cur:
            for i in range(0, len(plates), _CHUNK):
                chunk = plates[i : i + _CHUNK]
                marks = ", ".join(["%s"] * len(chunk))
                cur.execute(
                    "SELECT g.`licensePlate`, g.`lat`, g.`lng`, g.`remainingKilometers` "
                    "FROM `go` g JOIN ("
                    f"  SELECT `licensePlate`, MAX(`date`) AS d FROM `go` WHERE `licensePlate` IN ({marks}) "
                    "  GROUP BY `licensePlate`"
                    ") m ON g.`licensePlate` = m.`licensePlate` AND g.`date` = m.d",
                    chunk,
                )
                for plate, lat, lng, km in cur.fetchall():
                    result[plate] = LastPosition(
                        lat=float(lat), lng=float(lng), remaining_km=None if km is None else float(km)
                    )
        return result

    def insert_movement(self, v: Vehicle) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO `go` (`id`, `licensePlate`, `stateOfCharge`, `lat`, `lng`, `remainingKilometers`) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (v.id, v.license_plate, v.state_of_charge, v.lat, v.lng, v.remaining_km),
            )

    def insert_snapshots(self, vehicles: Sequence[Vehicle]) -> None:
        if not vehicles:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO `go_snapshot` (`id`, `licensePlate`, `stateOfCharge`, `lat`, `lng`, `remainingKilometers`) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [(v.id, v.license_plate, v.state_of_charge, v.lat, v.lng, v.remaining_km) for v in vehicles],
            )

    def load_observations(
        self, source: str = "movements", since: datetime | None = None, until: datetime | None = None
    ) -> list[Observation]:
        """Rows from ``go`` (movements) or ``go_snapshot`` (snapshots), ordered by plate and time."""
        table, time_col = SOURCES[source]
        where, params = [], []
        if since is not None:
            where.append(f"`{time_col}` >= %s")
            params.append(since)
        if until is not None:
            where.append(f"`{time_col}` < %s")
            params.append(until)
        sql = (
            f"SELECT `licensePlate`, `{time_col}`, `lat`, `lng`, `remainingKilometers`, `stateOfCharge` FROM `{table}`"
            + (" WHERE " + " AND ".join(where) if where else "")
            + f" ORDER BY `licensePlate`, `{time_col}`"
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
                )
                for plate, t, lat, lng, km, soc in cur.fetchall()
            ]

    def init_schema(self) -> None:
        sql = resources.files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")
        with self.conn.cursor() as cur:
            for statement in _split_sql(sql):
                cur.execute(statement)
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _split_sql(sql: str) -> list[str]:
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
