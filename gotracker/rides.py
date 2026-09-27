"""Turn stored observations into rides and summary statistics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby

from .geo import haversine_m


@dataclass(frozen=True)
class Observation:
    plate: str
    time: datetime
    lat: float
    lng: float
    remaining_km: float | None = None
    state_of_charge: float | None = None
    provider: str = "go_sharing"


@dataclass(frozen=True)
class Ride:
    """A vehicle seen at one place and later at another place.

    ``start_time``/``end_time`` bound the ride: it started at or after ``start_time``
    and ended at or before ``end_time``. With snapshot data the window is at most one
    poll interval wider than the real ride; with movement data it can be much wider.
    ``distance_m`` is the straight-line distance, not the route length.
    """

    plate: str
    start_time: datetime
    end_time: datetime
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    distance_m: float
    range_used_km: float | None
    charge_used_pct: float | None
    provider: str = "go_sharing"

    @property
    def window_minutes(self) -> float:
        return (self.end_time - self.start_time).total_seconds() / 60


def detect_rides(observations: Iterable[Observation], min_distance_m: float = 200.0) -> list[Ride]:
    """Find rides in observations sorted by (provider, plate, time).

    Consecutive observations of one plate that are at least ``min_distance_m`` apart
    count as a ride. Observations closer together than that are treated as the vehicle
    standing still, and the latest of them becomes the ride's start point.
    """
    rides: list[Ride] = []
    for (provider, plate), group in groupby(observations, key=lambda o: (o.provider, o.plate)):
        prev: Observation | None = None
        for obs in group:
            if prev is not None:
                distance = haversine_m(prev.lat, prev.lng, obs.lat, obs.lng)
                if distance >= min_distance_m:
                    rides.append(
                        Ride(
                            plate=plate,
                            start_time=prev.time,
                            end_time=obs.time,
                            start_lat=prev.lat,
                            start_lng=prev.lng,
                            end_lat=obs.lat,
                            end_lng=obs.lng,
                            distance_m=distance,
                            range_used_km=_diff(prev.remaining_km, obs.remaining_km),
                            charge_used_pct=_diff(prev.state_of_charge, obs.state_of_charge),
                            provider=provider,
                        )
                    )
            prev = obs
    return rides


def _diff(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return before - after


@dataclass(frozen=True)
class Stats:
    rides: int
    vehicles: int
    total_distance_km: float
    median_distance_m: float
    rides_per_day: dict[str, int]
    rides_per_hour: dict[int, int]
    top_vehicles: list[tuple[str, str, int]]  # (provider, plate, rides)
    rides_per_provider: dict[str, int]


def summarize(rides: list[Ride], top: int = 10) -> Stats:
    """Aggregate rides. Rides are bucketed by their end time (when they were observed)."""
    distances = sorted(r.distance_m for r in rides)
    per_day = Counter(r.end_time.strftime("%Y-%m-%d") for r in rides)
    per_hour = Counter(r.end_time.hour for r in rides)
    return Stats(
        rides=len(rides),
        vehicles=len({r.plate for r in rides}),
        total_distance_km=sum(distances) / 1000,
        median_distance_m=_median(distances),
        rides_per_day=dict(sorted(per_day.items())),
        rides_per_hour={h: per_hour.get(h, 0) for h in range(24)},
        top_vehicles=[
            (p, plate, n) for (p, plate), n in Counter((r.provider, r.plate) for r in rides).most_common(top)
        ],
        rides_per_provider=dict(Counter(r.provider for r in rides).most_common()),
    )


def _median(sorted_values: list[float]) -> float:
    n = len(sorted_values)
    if n == 0:
        return 0.0
    mid = n // 2
    return sorted_values[mid] if n % 2 else (sorted_values[mid - 1] + sorted_values[mid]) / 2
