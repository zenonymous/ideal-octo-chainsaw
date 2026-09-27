from datetime import datetime, timedelta

import pymysql
import pytest

from gotracker.api import Vehicle, parse_vehicle, parse_vehicles
from gotracker.config import Config, ConfigError
from gotracker.geo import haversine_m
from gotracker.movement import LastPosition, should_record
from gotracker.poll import poll_once
from gotracker.report import render_html
from gotracker.rides import Observation, detect_rides, summarize

ALMERE = (52.364431, 5.222011)


def vehicle(plate="GO-001", lat=ALMERE[0], lng=ALMERE[1], km=40.0, soc=80.0):
    return Vehicle(id=f"id-{plate}", license_plate=plate, lat=lat, lng=lng, state_of_charge=soc, remaining_km=km)


def north_of(lat, metres):
    return lat + metres / 111_195


# --- geo ---------------------------------------------------------------------


def test_haversine_known_distance():
    # Almere Centrum -> Amsterdam Centraal is roughly 23 km
    assert haversine_m(*ALMERE, 52.3791, 4.9003) == pytest.approx(21_900, rel=0.05)


def test_haversine_zero():
    assert haversine_m(*ALMERE, *ALMERE) == 0


# --- api parsing -------------------------------------------------------------


def test_parse_vehicle_geojson_order():
    v = parse_vehicle(
        {
            "id": 7,
            "licensePlate": "AB-12",
            "stateOfCharge": 55,
            "remainingKilometers": 30,
            "position": {"coordinates": [5.2, 52.3]},
        }
    )
    assert (v.lat, v.lng) == (52.3, 5.2)
    assert v.id == "7" and v.remaining_km == 30.0 and v.state_of_charge == 55.0


def test_parse_vehicle_optional_fields():
    v = parse_vehicle({"id": 1, "licensePlate": "X", "position": {"coordinates": [5, 52]}})
    assert v.remaining_km is None and v.state_of_charge is None


def test_parse_vehicles_skips_malformed(caplog):
    good = {"id": 1, "licensePlate": "X", "position": {"coordinates": [5, 52]}}
    out = parse_vehicles([good, {"id": 2}, "junk", {"id": 3, "licensePlate": "", "position": {"coordinates": [5, 52]}}])
    assert [v.license_plate for v in out] == ["X"]
    assert caplog.text.count("skipping malformed") == 3


# --- movement decision -------------------------------------------------------


def test_first_sighting_is_recorded():
    # This was the bootstrap bug: brand-new plates were never inserted.
    assert should_record(vehicle(), None, 200)[0]


def test_gps_jitter_is_ignored():
    last = LastPosition(north_of(ALMERE[0], 50), ALMERE[1], 45.0)
    assert not should_record(vehicle(km=40.0), last, 200)[0]


def test_short_ride_is_recorded():
    # 500 m is far below the old "1% of a coordinate" threshold (3.5-58 km).
    last = LastPosition(north_of(ALMERE[0], 500), ALMERE[1], 45.0)
    assert should_record(vehicle(km=40.0), last, 200)[0]


def test_moved_without_range_change_is_skipped_by_default():
    last = LastPosition(north_of(ALMERE[0], 500), ALMERE[1], 40.0)
    assert not should_record(vehicle(km=40.0), last, 200)[0]
    assert should_record(vehicle(km=40.0), last, 200, require_range_change=False)[0]


def test_unknown_range_falls_back_to_distance():
    last = LastPosition(north_of(ALMERE[0], 500), ALMERE[1], None)
    assert should_record(vehicle(km=None), last, 200)[0]


# --- poll_once with a fake store -------------------------------------------


class FakeStore:
    def __init__(self, last=None, fail_plates=()):
        self.last = last or {}
        self.fail_plates = set(fail_plates)
        self.inserted, self.snapshots, self.commits = [], [], 0

    def latest_positions(self, plates):
        return {p: self.last[p] for p in plates if p in self.last}

    def insert_movement(self, v):
        if v.license_plate in self.fail_plates:
            raise pymysql.IntegrityError(1062, "Duplicate entry")
        self.inserted.append(v)

    def insert_snapshots(self, vehicles):
        self.snapshots.extend(vehicles)

    def commit(self):
        self.commits += 1


def test_poll_once_records_new_and_moved_and_commits():
    moved_from = LastPosition(north_of(ALMERE[0], 1000), ALMERE[1], 50.0)
    parked = LastPosition(ALMERE[0], ALMERE[1], 40.0)
    store = FakeStore(last={"MOVED": moved_from, "PARKED": parked})
    vehicles = [vehicle("NEW"), vehicle("MOVED"), vehicle("PARKED"), vehicle("NEW")]  # NEW twice: deduped
    result = poll_once(Config(), store, fetch=lambda c: vehicles)
    assert sorted(v.license_plate for v in store.inserted) == ["MOVED", "NEW"]
    assert (result.seen, result.recorded, result.first_sightings, result.errors) == (3, 2, 1, 0)
    assert store.commits == 1 and store.snapshots == []


def test_poll_once_one_bad_row_does_not_lose_the_rest():
    store = FakeStore(fail_plates={"BAD"})
    result = poll_once(Config(), store, fetch=lambda c: [vehicle("BAD"), vehicle("GOOD")])
    assert [v.license_plate for v in store.inserted] == ["GOOD"]
    assert result.errors == 1 and store.commits == 1


def test_poll_once_snapshots():
    store = FakeStore()
    poll_once(Config(store_snapshots=True), store, fetch=lambda c: [vehicle("A"), vehicle("B")])
    assert len(store.snapshots) == 2


# --- rides -------------------------------------------------------------------


def test_detect_rides():
    t0 = datetime(2026, 9, 1, 8, 0)
    a, b = ALMERE, (north_of(ALMERE[0], 1500), ALMERE[1])
    obs = [
        Observation("P1", t0, *a, 40, 80),
        Observation("P1", t0 + timedelta(minutes=5), a[0] + 0.0001, a[1], 40, 80),  # jitter
        Observation("P1", t0 + timedelta(minutes=30), *b, 36, 72),  # ride
        Observation("P2", t0, *b, 20, 50),  # other plate, no ride
    ]
    rides = detect_rides(obs, 200)
    assert len(rides) == 1
    r = rides[0]
    assert r.plate == "P1" and r.start_time == t0 + timedelta(minutes=5)
    assert r.distance_m == pytest.approx(1500 - 11, abs=15)
    assert r.range_used_km == 4 and r.charge_used_pct == 8
    assert r.window_minutes == 25


def test_summarize_and_render():
    t = datetime(2026, 9, 1, 8, 0)
    obs = [
        Observation("P1", t, *ALMERE),
        Observation("P1", t + timedelta(hours=1), north_of(ALMERE[0], 1000), ALMERE[1]),
    ]
    rides = detect_rides(obs)
    stats = summarize(rides)
    assert stats.rides == 1 and stats.rides_per_hour[9] == 1 and stats.top_vehicles == [("P1", 1)]
    page = render_html(rides, stats, "Test </script>", ALMERE)
    assert "Test &lt;/script&gt;" in page and '"P1"' in page


def test_summarize_empty():
    assert summarize([]).median_distance_m == 0
    render_html([], summarize([]), "x", ALMERE)


# --- config ------------------------------------------------------------------


def test_config_from_env():
    c = Config.from_env(
        {
            "GOPOLL_DB_PASSWORD": "s3cret",
            "GOPOLL_MIN_DISTANCE_M": "150",
            "GOPOLL_STORE_SNAPSHOTS": "yes",
            "GOPOLL_LOG_LEVEL": "debug",
        }
    )
    assert c.db_password == "s3cret" and c.min_distance_m == 150
    assert c.store_snapshots is True and c.log_level == "DEBUG"
    assert c.radius == 500  # default kept


def test_config_rejects_bad_values():
    with pytest.raises(ConfigError):
        Config.from_env({"GOPOLL_RADIUS": "far"})
    with pytest.raises(ConfigError):
        Config.from_env({"GOPOLL_STORE_SNAPSHOTS": "maybe"})
