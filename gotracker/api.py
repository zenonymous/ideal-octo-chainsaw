"""Client for the (unofficial) goUrban vehicles endpoint used by GO Sharing."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class Vehicle:
    id: str
    license_plate: str
    lat: float
    lng: float
    state_of_charge: float | None
    remaining_km: float | None


def parse_vehicle(item: Any) -> Vehicle:
    """Turn one API item into a Vehicle. Raises ValueError on malformed items.

    ``position.coordinates`` is GeoJSON order: ``[lng, lat]``.
    """
    if not isinstance(item, dict):
        raise ValueError(f"expected an object, got {type(item).__name__}")
    try:
        lng, lat = item["position"]["coordinates"][:2]
        plate = item["licensePlate"]
        vid = item["id"]
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"missing or invalid field: {e}") from None
    if not plate:
        raise ValueError("empty licensePlate")
    soc = item.get("stateOfCharge")
    km = item.get("remainingKilometers")
    return Vehicle(
        id=str(vid),
        license_plate=str(plate),
        lat=float(lat),
        lng=float(lng),
        state_of_charge=None if soc is None else float(soc),
        remaining_km=None if km is None else float(km),
    )


def parse_vehicles(items: Iterable[Any]) -> list[Vehicle]:
    """Parse all items, logging and skipping malformed ones."""
    vehicles = []
    for item in items:
        try:
            vehicles.append(parse_vehicle(item))
        except ValueError as e:
            log.warning("skipping malformed vehicle %r: %s", _short(item), e)
    return vehicles


def fetch_vehicles(
    url: str,
    lat: float,
    lng: float,
    radius: int,
    timeout: float = 20.0,
    session: requests.Session | None = None,
) -> list[Vehicle]:
    http = session or requests
    try:
        resp = http.get(url, params={"lat": lat, "lng": lng, "rad": radius}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise ApiError(f"fetching vehicles failed: {e}") from e
    if not isinstance(data, list):
        raise ApiError(f"expected a JSON list, got {type(data).__name__}")
    return parse_vehicles(data)


def _short(item: Any, limit: int = 200) -> str:
    text = repr(item)
    return text if len(text) <= limit else text[:limit] + "..."
