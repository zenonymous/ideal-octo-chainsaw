"""Runs against a real MySQL/MariaDB when GOPOLL_TEST_DB_* is set; skipped otherwise.

WARNING: drops and recreates `go` and `go_snapshot` in the test database.
"""

import os
import time
from datetime import datetime

import pytest

from gotracker import db
from gotracker.api import Vehicle
from gotracker.config import Config
from gotracker.poll import poll_once
from gotracker.rides import detect_rides

pytestmark = pytest.mark.skipif(not os.environ.get("GOPOLL_TEST_DB_NAME"), reason="GOPOLL_TEST_DB_NAME not set")

UUID = "a7f3c2d0-1111-4e5b-9c1a-000000000001"  # 36 chars, like real GBFS ids


@pytest.fixture
def conn():
    config = Config(
        db_host=os.environ.get("GOPOLL_TEST_DB_HOST", "127.0.0.1"),
        db_port=int(os.environ.get("GOPOLL_TEST_DB_PORT", "3306")),
        db_user=os.environ.get("GOPOLL_TEST_DB_USER", "root"),
        db_password=os.environ.get("GOPOLL_TEST_DB_PASSWORD", ""),
        db_name=os.environ["GOPOLL_TEST_DB_NAME"],
    )
    conn = db.connect(config)
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS `go`, `go_snapshot`")
    yield conn
    conn.close()


@pytest.fixture
def repo(conn):
    r = db.Repository(conn)
    r.migrate(r.plan_migration())
    assert r.plan_migration().statements == []  # idempotent
    return r


def v(plate, lat, km):
    return Vehicle(id=f"id-{plate}", license_plate=plate, lat=lat, lng=5.222011, state_of_charge=70.0, remaining_km=km)


def test_full_cycle(repo):
    cfg = Config.from_env({"GOPOLL_PROVIDERS": "go_sharing,check_almere", "GOPOLL_STORE_SNAPSHOTS": "all"})
    feeds = {
        "go_sharing": [[v("A", 52.36, 40), v("B", 52.36, 30)], [v("A", 52.37, 38), v("B", 52.3601, 30)]],
        # GBFS: a parked vehicle, and one whose id rotated after a trip
        "check_almere": [[v(UUID, 52.36, 20), v("old-id", 52.35, 10)], [v(UUID, 52.36, 20), v("new-id", 52.34, 9)]],
    }
    for run in range(2):
        if run:
            time.sleep(1.1)  # `date` has 1-second resolution
        results = poll_once(cfg, repo, fetch=lambda c, p, run=run: feeds[p.name][run])
        assert not any(r.failed or r.errors for r in results)
    # run 1: 4 first sightings; run 2: A rode ~1.1 km, B jittered, new-id is a first sighting
    latest = repo.latest_positions("go_sharing", ["A", "B", UUID])
    assert set(latest) == {"A", "B"}
    assert latest["A"].lat == pytest.approx(52.37) and latest["A"].remaining_km == 38
    assert set(repo.latest_positions("check_almere", [UUID, "new-id", "A"])) == {UUID, "new-id"}

    moves = repo.load_observations("movements")
    assert [(o.provider, o.plate) for o in moves] == [
        ("check_almere", UUID),
        ("check_almere", "new-id"),
        ("check_almere", "old-id"),
        ("go_sharing", "A"),
        ("go_sharing", "A"),
        ("go_sharing", "B"),
    ]
    assert len(repo.load_observations("movements", providers=["check_almere"])) == 3

    snaps = repo.load_observations("snapshots")
    assert len(snaps) == 8
    rides = detect_rides(snaps, 200)
    assert [(r.provider, r.plate) for r in rides] == [("go_sharing", "A")] and rides[0].range_used_km == 2

    avail = repo.availability()
    assert sorted(n for p, _, n in avail if p == "check_almere") == [2, 2]
    assert len({t for _, t, _ in avail}) == 2  # one timestamp per poll


def test_migrate_legacy_table(conn):
    """A hand-made 2022-style table: narrow VARCHARs, INT id, no keys, existing rows."""
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE `go` (`id` INT NOT NULL, `licensePlate` VARCHAR(16), `stateOfCharge` INT, "
            "`lat` VARCHAR(20), `lng` VARCHAR(20), `remainingKilometers` FLOAT, "
            "`date` TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        cur.execute("INSERT INTO `go` VALUES (123, 'GO-OLD', 55, '52.35', '5.20', 25, '2022-04-23 10:00:00')")
    conn.commit()
    repo = db.Repository(conn)
    assert repo.schema_problems(need_snapshots=False) == ["table `go` has no `provider` column"]

    plan = repo.plan_migration()
    alter = next(s for s in plan.statements if s.startswith("ALTER TABLE `go`"))
    assert "ADD COLUMN `provider`" in alter and "MODIFY COLUMN `id` VARCHAR(64) NOT NULL" in alter
    assert "MODIFY COLUMN `licensePlate` VARCHAR(64) NULL" in alter
    assert any(s.startswith("CREATE TABLE IF NOT EXISTS `go_snapshot`") for s in plan.statements)
    repo.migrate(plan)
    assert repo.plan_migration().statements == []
    assert repo.schema_problems(need_snapshots=True) == []

    # old data kept and attributed to GO Sharing
    [old] = repo.load_observations("movements")
    assert (old.provider, old.plate, old.time) == ("go_sharing", "GO-OLD", datetime(2022, 4, 23, 10, 0))
    # long GBFS ids now fit
    repo.insert_movement("check_almere", Vehicle(UUID, UUID, 52.3, 5.2, 50.0, 10.0))
    repo.commit()
    assert UUID in repo.latest_positions("check_almere", [UUID])
