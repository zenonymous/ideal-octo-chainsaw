import json
from datetime import datetime, timedelta
from pathlib import Path

import pymysql
import pytest

from gotracker.api import ApiError, Vehicle, parse_vehicle, parse_vehicles
from gotracker.config import Config, ConfigError
from gotracker.gbfs import discover_vehicle_feed, fetch_gbfs_vehicles
from gotracker.geo import haversine_m
from gotracker.movement import LastPosition, should_record
from gotracker.poll import poll_once
from gotracker.providers import parse_providers
from gotracker.report import color_slots, render_html, summarize_availability
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

GOS = Config().providers[0]  # go_sharing


class FakeStore:
    def __init__(self, last=None, fail_plates=()):
        self.last = last or {}  # {(provider, plate): LastPosition}
        self.fail_plates = set(fail_plates)
        self.inserted, self.snapshots, self.commits, self.rollbacks = [], [], 0, 0

    def latest_positions(self, provider, plates):
        return {p: self.last[(provider, p)] for p in plates if (provider, p) in self.last}

    def insert_movement(self, provider, v):
        if v.license_plate in self.fail_plates:
            raise pymysql.IntegrityError(1062, "Duplicate entry")
        self.inserted.append((provider, v.license_plate))

    def insert_snapshots(self, provider, vehicles, observed_at):
        self.snapshots.extend((provider, v.license_plate) for v in vehicles)

    def now(self):
        return datetime(2026, 9, 27, 12, 0)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_poll_once_records_new_and_moved_and_commits():
    moved_from = LastPosition(north_of(ALMERE[0], 1000), ALMERE[1], 50.0)
    parked = LastPosition(ALMERE[0], ALMERE[1], 40.0)
    store = FakeStore(last={("go_sharing", "MOVED"): moved_from, ("go_sharing", "PARKED"): parked})
    vehicles = [vehicle("NEW"), vehicle("MOVED"), vehicle("PARKED"), vehicle("NEW")]  # NEW twice: deduped
    [result] = poll_once(Config(), store, fetch=lambda c, p: vehicles)
    assert sorted(plate for _, plate in store.inserted) == ["MOVED", "NEW"]
    assert (result.seen, result.recorded, result.first_sightings, result.errors) == (3, 2, 1, 0)
    assert store.commits == 1 and store.snapshots == []  # go_sharing: no snapshots by default


def test_poll_once_one_bad_row_does_not_lose_the_rest():
    store = FakeStore(fail_plates={"BAD"})
    [result] = poll_once(Config(), store, fetch=lambda c, p: [vehicle("BAD"), vehicle("GOOD")])
    assert store.inserted == [("go_sharing", "GOOD")]
    assert result.errors == 1 and store.commits == 1


def test_poll_once_snapshots_all():
    store = FakeStore()
    poll_once(Config(snapshots="all"), store, fetch=lambda c, p: [vehicle("A"), vehicle("B")])
    assert len(store.snapshots) == 2


def test_poll_multiple_providers_keeps_them_apart_and_isolates_failures():
    config = Config.from_env({"GOPOLL_PROVIDERS": "go_sharing,check_almere,broken=https://example.invalid/gbfs.json"})
    # The same plate/id at two providers is two different vehicles.
    store = FakeStore(last={("go_sharing", "X"): LastPosition(ALMERE[0], ALMERE[1], 40.0)})

    def fetch(cfg, provider):
        if provider.name == "broken":
            raise ApiError("down")
        return [vehicle("X")]

    results = poll_once(config, store, fetch)
    assert [(r.provider, r.recorded, r.failed) for r in results] == [
        ("go_sharing", 0, False),  # parked, known
        ("check_almere", 1, False),  # first sighting for this provider
        ("broken", 0, True),
    ]
    assert store.inserted == [("check_almere", "X")]
    assert store.snapshots == [("check_almere", "X")]  # default: snapshots for GBFS only
    assert store.commits == 2


# --- providers ---------------------------------------------------------------


def test_parse_providers():
    specs = parse_providers(" go_sharing , felyx_amsterdam, mine=https://x.test/gbfs.json ")
    assert [(s.name, s.kind) for s in specs] == [
        ("go_sharing", "gourban"),
        ("felyx_amsterdam", "gbfs"),
        ("mine", "gbfs"),
    ]
    assert specs[1].url == "https://maas.zeus.cooltra.com/gbfs/amsterdam/3.0/en/gbfs.json"
    assert specs[2].url == "https://x.test/gbfs.json"


@pytest.mark.parametrize(
    "value",
    ["", "nope", "go_sharing,go_sharing", "Bad Name=https://x.test", "x=ftp://x.test", "check_almere=https://x.test"],
)
def test_parse_providers_rejects(value):
    with pytest.raises(ValueError):
        parse_providers(value)


def test_default_is_go_sharing_only():
    assert [p.name for p in Config.from_env({}).providers] == ["go_sharing"]


# --- GBFS --------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"


class FakeHttp:
    """Serves fixture files by URL."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, timeout=None, **kw):
        self.calls.append(url)
        body = self.routes[url]
        resp = type("R", (), {})()
        resp.raise_for_status = lambda: None
        resp.json = lambda: json.loads((FIXTURES / body).read_text())
        return resp


def test_gbfs_v3_discovery_and_vehicles():
    http = FakeHttp(
        {
            "https://gbfs.test/v3/gbfs.json": "gbfs_v3_discovery.json",
            "https://gbfs.test/v3/vehicle_status.json": "gbfs_v3_vehicle_status.json",
        }
    )
    vehicles = fetch_gbfs_vehicles("https://gbfs.test/v3/gbfs.json", session=http)
    assert http.calls[-1] == "https://gbfs.test/v3/vehicle_status.json"
    # the docked vehicle without lat/lon is skipped, the malformed one logged
    assert [v.id for v in vehicles] == ["a7f3c2d0-1111-4e5b-9c1a-000000000001", "a7f3c2d0-1111-4e5b-9c1a-000000000002"]
    v = vehicles[0]
    assert (v.lat, v.lng) == (52.3712, 5.2181)
    assert v.license_plate == v.id
    assert v.state_of_charge == 83.0 and v.remaining_km == 41.5


def test_gbfs_v2_prefers_english_feed_and_reads_bikes():
    http = FakeHttp(
        {
            "https://gbfs.test/v2/gbfs.json": "gbfs_v2_discovery.json",
            "https://gbfs.test/v2/en/free_bike_status.json": "gbfs_v2_free_bike_status.json",
        }
    )
    vehicles = fetch_gbfs_vehicles("https://gbfs.test/v2/gbfs.json", session=http)
    assert [v.id for v in vehicles] == ["bike-1", "bike-2"]
    assert vehicles[1].state_of_charge is None and vehicles[1].remaining_km == 3.0


def test_gbfs_direct_vehicle_feed_url():
    http = FakeHttp({"https://gbfs.test/v2/en/free_bike_status.json": "gbfs_v2_free_bike_status.json"})
    assert len(fetch_gbfs_vehicles("https://gbfs.test/v2/en/free_bike_status.json", session=http)) == 2
    assert len(http.calls) == 1


def test_gbfs_discovery_without_vehicle_feed():
    with pytest.raises(ApiError):
        discover_vehicle_feed({"data": {"feeds": [{"name": "station_status", "url": "x"}]}})


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


def test_detect_rides_does_not_mix_providers():
    t = datetime(2026, 9, 1, 8, 0)
    far = (north_of(ALMERE[0], 2000), ALMERE[1])
    obs = [Observation("X", t, *ALMERE, provider="a"), Observation("X", t + timedelta(hours=1), *far, provider="b")]
    assert detect_rides(obs) == []


def test_summarize_and_render():
    t = datetime(2026, 9, 1, 8, 0)
    obs = [
        Observation("P1", t, *ALMERE),
        Observation("P1", t + timedelta(hours=1), north_of(ALMERE[0], 1000), ALMERE[1]),
    ]
    rides = detect_rides(obs)
    stats = summarize(rides)
    assert stats.rides == 1 and stats.rides_per_hour[9] == 1
    assert stats.top_vehicles == [("go_sharing", "P1", 1)] and stats.rides_per_provider == {"go_sharing": 1}
    page = render_html(rides, stats, "Test </script>", ALMERE)
    assert "Test &lt;/script&gt;" in page and '"P1"' in page
    assert 'class="legend"' not in page  # one provider: no legend


def test_render_multi_provider_colors_follow_config_order():
    t = datetime(2026, 9, 1, 8, 0)
    rides = []
    for p in ["p4", "p3", "p2", "p1"]:
        obs = [
            Observation("X", t, *ALMERE, provider=p),
            Observation("X", t, north_of(ALMERE[0], 900), ALMERE[1], provider=p),
        ]
        rides += detect_rides(obs)
    avail = summarize_availability([("p1", t, 10), ("p1", t + timedelta(minutes=5), 12), ("p2", t, 3)])
    page = render_html(rides, summarize(rides), "x", ALMERE, avail, provider_order=["p1", "p2", "p3", "p4"])
    assert color_slots(["p1", "p2", "p3", "p4"]) == {"p1": 1, "p2": 2, "p3": 3, "p4": 0}
    assert 'class="legend"' in page and "Other" in page and "GBFS providers" in page
    assert "Vehicles available" in page and "<polyline" in page
    assert avail[0].average == 11 and (avail[0].minimum, avail[0].maximum) == (10, 12)


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
    assert c.snapshots == "all" and c.log_level == "DEBUG"
    assert c.radius == 500  # default kept


def test_snapshot_modes():
    gos, check = parse_providers("go_sharing,check_almere")
    assert [Config(snapshots=m).stores_snapshots(gos) for m in ("all", "gbfs", "none")] == [True, False, False]
    assert [Config(snapshots=m).stores_snapshots(check) for m in ("all", "gbfs", "none")] == [True, True, False]
    assert Config.from_env({"GOPOLL_STORE_SNAPSHOTS": "false"}).snapshots == "none"


def test_config_rejects_bad_values():
    with pytest.raises(ConfigError):
        Config.from_env({"GOPOLL_RADIUS": "far"})
    with pytest.raises(ConfigError):
        Config.from_env({"GOPOLL_STORE_SNAPSHOTS": "maybe"})
    with pytest.raises(ConfigError):
        Config.from_env({"GOPOLL_PROVIDERS": "lime_amsterdam"})
