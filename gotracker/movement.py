"""Decide whether a vehicle observation is worth recording as a movement."""

from __future__ import annotations

from dataclasses import dataclass

from .api import Vehicle
from .geo import haversine_m


@dataclass(frozen=True)
class LastPosition:
    """The most recent row stored for a license plate."""

    lat: float
    lng: float
    remaining_km: float | None


def should_record(
    vehicle: Vehicle,
    last: LastPosition | None,
    min_distance_m: float,
    require_range_change: bool = True,
) -> tuple[bool, str]:
    """Return (record?, reason).

    - A plate never seen before is always recorded, so it has a baseline to compare against.
    - Otherwise it must have moved at least ``min_distance_m`` metres (filters GPS jitter),
      and, if ``require_range_change``, its remaining range must differ (filters parked
      vehicles whose position drifts but that were not ridden). When the range is unknown
      on either side, only the distance counts.
    """
    if last is None:
        return True, "first sighting"
    distance = haversine_m(last.lat, last.lng, vehicle.lat, vehicle.lng)
    if distance < min_distance_m:
        return False, f"moved {distance:.0f} m < {min_distance_m:.0f} m"
    if require_range_change and _same(last.remaining_km, vehicle.remaining_km):
        return False, f"moved {distance:.0f} m but remaining range unchanged"
    return True, f"moved {distance:.0f} m"


def _same(a: float | None, b: float | None) -> bool:
    # The API sometimes omits remainingKilometers; if either side is unknown we can't
    # tell, so fall back to the distance check alone.
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < 1e-6
