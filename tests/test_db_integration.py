"""Runs against a real MySQL/MariaDB when GOPOLL_TEST_DB_* is set; skipped otherwise.

WARNING: drops and recreates `go` and `go_snapshot` in the test database.
"""

import os
import time

import pytest

from gotracker import db
from gotracker.api import Vehicle
from gotracker.config import Config
from gotracker.poll import poll_once
from gotracker.rides import detect_rides

pytestmark = pytest.mark.skipif(not os.environ.get("GOPOLL_TEST_DB_NAME"), reason="GOPOLL_TEST_DB_NAME not set")


@pytest.fixture
def repo():
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
    r = db.Repository(conn)
    r.init_schema()
    r.init_schema()  # idempotent
    yield r
    conn.close()


def v(plate, lat, km):
    return Vehicle(id=f"id-{plate}", license_plate=plate, lat=lat, lng=5.222011, state_of_charge=70.0, remaining_km=km)


def test_full_cycle(repo):
    cfg = Config(store_snapshots=True)
    # run 1: empty table, everything is a first sighting (was the bootstrap bug)
    r1 = poll_once(cfg, repo, fetch=lambda c: [v("A", 52.36, 40), v("B", 52.36, 30)])
    assert r1.recorded == 2
    time.sleep(1.1)  # `date` has 1-second resolution
    # run 2: A rode ~1.1 km, B jittered
    r2 = poll_once(cfg, repo, fetch=lambda c: [v("A", 52.37, 38), v("B", 52.3601, 30)])
    assert r2.recorded == 1

    latest = repo.latest_positions(["A", "B", "UNKNOWN"])
    assert set(latest) == {"A", "B"}
    assert latest["A"].lat == pytest.approx(52.37) and latest["A"].remaining_km == 38

    moves = repo.load_observations("movements")
    assert [o.plate for o in moves] == ["A", "A", "B"]
    snaps = repo.load_observations("snapshots")
    assert len(snaps) == 4
    rides = detect_rides(snaps, 200)
    assert [r.plate for r in rides] == ["A"] and rides[0].range_used_km == 2
