"""Render rides and statistics as a standalone HTML page (map + charts)."""

from __future__ import annotations

import csv
import html
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TextIO

from .rides import Ride, Stats

CSV_FIELDS = [
    "provider",
    "plate",
    "start_time",
    "end_time",
    "window_minutes",
    "start_lat",
    "start_lng",
    "end_lat",
    "end_lng",
    "distance_m",
    "range_used_km",
    "charge_used_pct",
]

# Map colours: validated categorical slots 1-3 (all pairs, light + dark); anything past
# three providers folds into a neutral "Other". Keep in sync with the CSS tokens below.
MAP_SLOTS = 3
OTHER = "Other"


def write_csv(rides: list[Ride], out: TextIO) -> None:
    w = csv.writer(out)
    w.writerow(CSV_FIELDS)
    for r in rides:
        w.writerow(
            [
                r.provider,
                r.plate,
                r.start_time.isoformat(sep=" "),
                r.end_time.isoformat(sep=" "),
                f"{r.window_minutes:.1f}",
                r.start_lat,
                r.start_lng,
                r.end_lat,
                r.end_lng,
                f"{r.distance_m:.0f}",
                "" if r.range_used_km is None else f"{r.range_used_km:g}",
                "" if r.charge_used_pct is None else f"{r.charge_used_pct:g}",
            ]
        )


@dataclass(frozen=True)
class Availability:
    """Vehicles seen per poll for one provider, averaged per hour."""

    provider: str
    hourly: list[tuple[datetime, float]]  # (hour start, average vehicles seen)
    average: float
    minimum: int
    maximum: int


def summarize_availability(rows: Sequence[tuple[str, datetime, int]]) -> list[Availability]:
    by_provider: dict[str, dict[datetime, list[int]]] = defaultdict(lambda: defaultdict(list))
    for provider, observed_at, count in rows:
        by_provider[provider][observed_at.replace(minute=0, second=0, microsecond=0)].append(count)
    result = []
    for provider in sorted(by_provider):
        hours = by_provider[provider]
        counts = [c for cs in hours.values() for c in cs]
        result.append(
            Availability(
                provider=provider,
                hourly=[(h, sum(cs) / len(cs)) for h, cs in sorted(hours.items())],
                average=sum(counts) / len(counts),
                minimum=min(counts),
                maximum=max(counts),
            )
        )
    return result


def color_slots(providers: Sequence[str]) -> dict[str, int]:
    """Slot 1..MAP_SLOTS per provider in the given (stable, configured) order; 0 = Other."""
    return {p: (i + 1 if i < MAP_SLOTS else 0) for i, p in enumerate(providers)}


def render_html(
    rides: list[Ride],
    stats: Stats,
    title: str,
    center: tuple[float, float],
    availability: Sequence[Availability] = (),
    provider_order: Sequence[str] = (),
) -> str:
    # Colour follows the provider, never its rank: configured order first, then any
    # other providers found in the data, alphabetically.
    seen = {r.provider for r in rides} | {a.provider for a in availability}
    order = [p for p in provider_order if p in seen] + sorted(seen - set(provider_order))
    slots = color_slots(order)
    availability = sorted(availability, key=lambda a: order.index(a.provider))

    # Newest rides last so they draw on top; cap to keep the page light.
    shown = rides[-5000:]
    data = [
        [
            r.start_lat,
            r.start_lng,
            r.end_lat,
            r.end_lng,
            r.provider,
            r.plate,
            r.end_time.strftime("%Y-%m-%d %H:%M"),
            round(r.distance_m),
            slots.get(r.provider, 0),
        ]
        for r in shown
    ]
    # json.dumps output is safe inside <script> once "</" is escaped.
    rides_json = json.dumps(data).replace("</", "<\\/")
    max_hour = max(stats.rides_per_hour.values(), default=0) or 1
    max_day = max(stats.rides_per_day.values(), default=0) or 1
    hours = "".join(
        f'<div class="bar" title="{h:02d}:00 · {n} rides"><span style="height:{100 * n / max_hour:.0f}%"></span>'
        f"<i>{h}</i></div>"
        for h, n in stats.rides_per_hour.items()
    )
    days = "".join(
        f'<tr><td>{html.escape(d)}</td><td class="num">{n}</td>'
        f'<td class="spark"><span style="width:{100 * n / max_day:.0f}%"></span></td></tr>'
        for d, n in list(stats.rides_per_day.items())[-31:]
    )
    top = "".join(
        f'<tr><td>{html.escape(plate)}</td><td class="muted">{html.escape(p)}</td><td class="num">{n}</td></tr>'
        for p, plate, n in stats.top_vehicles
    )
    note = f" (map shows the latest {len(shown)})" if len(shown) < len(rides) else ""
    return _TEMPLATE.format(
        title=html.escape(title),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        rides=stats.rides,
        vehicles=stats.vehicles,
        total_km=f"{stats.total_distance_km:,.1f}",
        median_m=f"{stats.median_distance_m:,.0f}",
        note=html.escape(note),
        legend=_legend(order, slots) if len(order) > 1 else "",
        providers=_provider_table(order, slots, stats, availability),
        gbfs_note=_GBFS_NOTE if any(p != "go_sharing" for p in order) else "",
        hours=hours,
        days=days or '<tr><td colspan="3">No rides</td></tr>',
        top=top or '<tr><td colspan="3">No rides</td></tr>',
        availability=_availability_section(availability),
        rides_json=rides_json,
        center_lat=center[0],
        center_lng=center[1],
    )


def _swatch(slot: int) -> str:
    return f'<span class="sw s{slot}"></span>'


def _legend(order: Sequence[str], slots: dict[str, int]) -> str:
    items = [f"{_swatch(slots[p])}{html.escape(p)}" for p in order if slots[p]]
    if any(slots[p] == 0 for p in order):
        items.append(f"{_swatch(0)}{OTHER}")
    return '<div class="legend">' + "".join(f"<span>{i}</span>" for i in items) + "</div>"


def _provider_table(order, slots, stats: Stats, availability) -> str:
    if not order:
        return ""
    avg = {a.provider: f"{a.average:,.0f}" for a in availability}
    rows = "".join(
        f"<tr><td>{_swatch(slots[p])}{html.escape(p)}</td>"
        f'<td class="num">{stats.rides_per_provider.get(p, 0)}</td>'
        f'<td class="num">{avg.get(p, "–")}</td></tr>'
        for p in order
    )
    return (
        '<div class="card"><h2>Providers</h2><table><tr class="muted"><td></td><td class="num">Rides</td>'
        f'<td class="num">Avg. available</td></tr>{rows}</table></div>'
    )


def _availability_section(availability: Sequence[Availability]) -> str:
    if not availability:
        return ""
    rows = "".join(
        f'<tr><td>{html.escape(a.provider)}</td><td class="num">{a.average:,.0f}</td>'
        f'<td class="num">{a.minimum}</td><td class="num">{a.maximum}</td><td class="sparkcell">{_sparkline(a)}</td></tr>'
        for a in availability
    )
    return (
        '<div class="card wide"><h2>Vehicles available (from snapshots, hourly average)</h2>'
        '<table><tr class="muted"><td>Provider</td><td class="num">Avg</td><td class="num">Min</td>'
        f'<td class="num">Max</td><td>Over time</td></tr>{rows}</table></div>'
    )


def _sparkline(a: Availability, width: int = 320, height: int = 40) -> str:
    """One series per provider (small multiples), each on its own 0-based scale."""
    points = a.hourly[-24 * 31 :]
    top = max((v for _, v in points), default=0) or 1
    n = len(points)

    def xy(i: int, v: float) -> tuple[float, float]:
        x = width / 2 if n == 1 else i * width / (n - 1)
        return round(x, 1), round(height - 2 - v / top * (height - 4), 1)

    coords = [xy(i, v) for i, (_, v) in enumerate(points)]
    line = " ".join(f"{x},{y}" for x, y in coords)
    step = width / max(n, 1)
    hits = "".join(
        f'<rect x="{max(0, x - step / 2):.1f}" y="0" width="{step:.1f}" height="{height}">'
        f"<title>{t:%Y-%m-%d %H}:00 · {v:,.0f} vehicles</title></rect>"
        for (x, _), (t, v) in zip(coords, points)
    )
    return (
        f'<svg class="sparkline" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" '
        f'aria-label="{html.escape(a.provider)}: {a.minimum} to {a.maximum} vehicles">'
        f'<polyline points="{line}"/><g class="hits">{hits}</g></svg>'
    )


_GBFS_NOTE = (
    '<p class="muted small">GBFS providers give a vehicle a new random id after every trip, so rides '
    "can rarely be followed there; their snapshots show availability instead.</p>"
)

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
  :root {{ --bg:#f7f7f5; --fg:#1d1d1b; --muted:#6b6b66; --card:#fff; --line:#e3e3de; --accent:#1f9d55;
          --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s0:#8a8983; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#161615; --fg:#ececea; --muted:#9a9a94; --card:#20201e; --line:#33332f; --accent:#3cc47c;
            --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s0:#7c7b75; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font:15px/1.45 system-ui, sans-serif; background:var(--bg); color:var(--fg); }}
  main {{ max-width:1100px; margin:0 auto; padding:24px 16px 48px; }}
  h1 {{ font-size:1.5rem; margin:0 0 4px; }}
  h2 {{ font-size:1rem; margin:0 0 12px; }}
  .muted {{ color:var(--muted); }}
  .small {{ font-size:13px; }}
  .tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:20px 0; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; min-width:0; }}
  .tile b {{ display:block; font-size:1.6rem; font-variant-numeric:tabular-nums; }}
  #map {{ height:480px; border-radius:10px; border:1px solid var(--line); }}
  .legend {{ display:flex; flex-wrap:wrap; gap:6px 16px; margin:0 0 8px; font-size:13px; }}
  .sw {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align:-1px; }}
  .s0 {{ background:var(--s0); }} .s1 {{ background:var(--s1); }} .s2 {{ background:var(--s2); }} .s3 {{ background:var(--s3); }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:12px; margin-top:12px; }}
  .wide {{ grid-column:1 / -1; overflow-x:auto; }}
  .hours {{ display:flex; align-items:flex-end; gap:3px; height:140px; }}
  .bar {{ flex:1; display:flex; flex-direction:column; justify-content:flex-end; height:100%; }}
  .bar span {{ background:var(--accent); border-radius:3px 3px 0 0; min-height:1px; }}
  .bar i {{ font-style:normal; font-size:10px; color:var(--muted); text-align:center; }}
  table {{ width:100%; border-collapse:collapse; }}
  td {{ padding:3px 4px; border-bottom:1px solid var(--line); }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; width:5em; }}
  .spark {{ width:40%; }} .spark span {{ display:block; height:8px; background:var(--accent); border-radius:4px; }}
  .sparkcell {{ width:45%; min-width:96px; }}
  .sparkline {{ width:100%; height:40px; display:block; }}
  .sparkline polyline {{ fill:none; stroke:var(--accent); stroke-width:2; vector-effect:non-scaling-stroke;
                        stroke-linejoin:round; }}
  .sparkline .hits rect {{ fill:transparent; }}
  .sparkline .hits rect:hover {{ fill:var(--line); }}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <div class="muted">Generated {generated}. Distances are straight lines between observed positions.</div>
  <div class="tiles">
    <div class="card tile"><span class="muted">Rides</span><b>{rides}</b></div>
    <div class="card tile"><span class="muted">Vehicles</span><b>{vehicles}</b></div>
    <div class="card tile"><span class="muted">Total distance</span><b>{total_km} km</b></div>
    <div class="card tile"><span class="muted">Median ride</span><b>{median_m} m</b></div>
  </div>
  <h2>Rides{note}</h2>
  {legend}
  <div id="map"></div>
  {gbfs_note}
  <div class="grid">
    {providers}
    <div class="card"><h2>Rides by hour of day</h2><div class="hours">{hours}</div></div>
    <div class="card"><h2>Rides per day (last 31)</h2><table>{days}</table></div>
    <div class="card"><h2>Most-ridden vehicles</h2><table>{top}</table></div>
    {availability}
  </div>
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
  const rides = {rides_json};
  if (typeof L === "undefined") {{
    document.getElementById("map").textContent = "Map unavailable: Leaflet could not be loaded (offline?).";
    throw new Error("Leaflet not loaded");
  }}
  const map = L.map("map").setView([{center_lat}, {center_lng}], 13);
  L.tileLayer("https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
    maxZoom: 19, attribution: "&copy; OpenStreetMap contributors"
  }}).addTo(map);
  const css = getComputedStyle(document.documentElement);
  const colors = [0, 1, 2, 3].map(i => css.getPropertyValue("--s" + i).trim());
  const bounds = [];
  for (const [aLat, aLng, bLat, bLng, provider, plate, when, dist, slot] of rides) {{
    const color = colors[slot];
    L.polyline([[aLat, aLng], [bLat, bLng]], {{ color, weight: 2, opacity: 0.45 }})
      .bindTooltip(provider + " · " + plate + " · " + when + " · " + dist + " m").addTo(map);
    L.circleMarker([bLat, bLng], {{ radius: 4, color: css.getPropertyValue("--card").trim(), weight: 2,
      fillColor: color, fillOpacity: 0.9 }}).addTo(map);
    bounds.push([aLat, aLng], [bLat, bLng]);
  }}
  if (bounds.length) map.fitBounds(bounds, {{ padding: [20, 20], maxZoom: 15 }});
</script>
</body>
</html>
"""
