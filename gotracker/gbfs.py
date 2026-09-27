"""Client for GBFS feeds (General Bikeshare Feed Specification, v1.x-3.x).

Only free-floating vehicles with a position are read: ``free_bike_status`` (v1/v2) or
``vehicle_status`` (v3). Note that since GBFS 2.0, operators must give a vehicle a new
random id after every trip, so ids cannot be followed across rides.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .api import ApiError, Vehicle

log = logging.getLogger(__name__)

VEHICLE_FEEDS = ("vehicle_status", "free_bike_status")


def fetch_gbfs_vehicles(url: str, timeout: float = 20.0, session: requests.Session | None = None) -> list[Vehicle]:
    """Fetch vehicles from a GBFS auto-discovery URL (gbfs.json) or a vehicle feed URL."""
    http = session or requests
    doc = _get_json(http, url, timeout)
    if _vehicle_list(doc) is None:
        feed_url = discover_vehicle_feed(doc)
        doc = _get_json(http, feed_url, timeout)
    items = _vehicle_list(doc)
    if items is None:
        raise ApiError(f"{url}: no vehicles/bikes list in the vehicle feed")
    vehicles = []
    for item in items:
        try:
            v = parse_gbfs_vehicle(item)
        except ValueError as e:
            log.warning("skipping malformed GBFS vehicle: %s", e)
            continue
        if v is not None:
            vehicles.append(v)
    return vehicles


def discover_vehicle_feed(doc: Any) -> str:
    """Find the vehicle feed URL in a gbfs.json document (v1/v2 per-language, or v3)."""
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        raise ApiError("not a GBFS discovery document (no data object)")
    if isinstance(data.get("feeds"), list):  # v3
        feed_lists = [data["feeds"]]
    else:  # v1/v2: {"en": {"feeds": [...]}, "nl": {...}}; prefer English
        langs = sorted(data, key=lambda lang: (lang != "en", lang))
        feed_lists = [data[lang].get("feeds", []) for lang in langs if isinstance(data[lang], dict)]
    for wanted in VEHICLE_FEEDS:
        for feeds in feed_lists:
            for feed in feeds:
                if isinstance(feed, dict) and feed.get("name") == wanted and feed.get("url"):
                    return feed["url"]
    raise ApiError("GBFS discovery document lists no vehicle_status/free_bike_status feed")


def parse_gbfs_vehicle(item: Any) -> Vehicle | None:
    """Map one GBFS vehicle to a Vehicle. Returns None for vehicles without a position
    (docked at a station). Raises ValueError for malformed items.

    The GBFS vehicle id is used as the tracking key (``license_plate``), because GBFS
    feeds have no license plates.
    """
    if not isinstance(item, dict):
        raise ValueError(f"expected an object, got {type(item).__name__}")
    vid = item.get("vehicle_id", item.get("bike_id"))
    if not vid:
        raise ValueError("missing vehicle_id/bike_id")
    if item.get("lat") is None or item.get("lon") is None:
        return None
    try:
        lat, lng = float(item["lat"]), float(item["lon"])
    except (TypeError, ValueError):
        raise ValueError(f"{vid}: invalid lat/lon") from None
    fuel = item.get("current_fuel_percent")  # 0.0-1.0
    range_m = item.get("current_range_meters")
    return Vehicle(
        id=str(vid),
        license_plate=str(vid),
        lat=lat,
        lng=lng,
        state_of_charge=None if fuel is None else round(float(fuel) * 100, 2),
        remaining_km=None if range_m is None else round(float(range_m) / 1000, 2),
    )


def _vehicle_list(doc: Any) -> list | None:
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        return None
    for key in ("vehicles", "bikes"):
        if isinstance(data.get(key), list):
            return data[key]
    return None


def _get_json(http, url: str, timeout: float) -> Any:
    try:
        resp = http.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        raise ApiError(f"fetching {url} failed: {e}") from e
