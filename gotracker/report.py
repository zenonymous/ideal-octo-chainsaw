"""Render rides and statistics as a standalone HTML page (map + charts)."""

from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from typing import TextIO

from .rides import Ride, Stats

CSV_FIELDS = [
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


def write_csv(rides: list[Ride], out: TextIO) -> None:
    w = csv.writer(out)
    w.writerow(CSV_FIELDS)
    for r in rides:
        w.writerow(
            [
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


def render_html(rides: list[Ride], stats: Stats, title: str, center: tuple[float, float]) -> str:
    # Newest rides last so they draw on top; cap to keep the page light.
    shown = rides[-5000:]
    data = [
        [
            r.start_lat,
            r.start_lng,
            r.end_lat,
            r.end_lng,
            r.plate,
            r.end_time.strftime("%Y-%m-%d %H:%M"),
            round(r.distance_m),
        ]
        for r in shown
    ]
    # json.dumps output is safe inside <script> once "</" is escaped.
    rides_json = json.dumps(data).replace("</", "<\\/")
    max_hour = max(stats.rides_per_hour.values(), default=0) or 1
    max_day = max(stats.rides_per_day.values(), default=0) or 1
    hours = "".join(
        f'<div class="bar" title="{h:02d}:00 · {n} rides"><span style="height:{100 * n / max_hour:.0f}%"></span><i>{h}</i></div>'
        for h, n in stats.rides_per_hour.items()
    )
    days = "".join(
        f'<tr><td>{html.escape(d)}</td><td class="num">{n}</td>'
        f'<td class="spark"><span style="width:{100 * n / max_day:.0f}%"></span></td></tr>'
        for d, n in list(stats.rides_per_day.items())[-31:]
    )
    top = "".join(f'<tr><td>{html.escape(p)}</td><td class="num">{n}</td></tr>' for p, n in stats.top_vehicles)
    note = f" (map shows the latest {len(shown)})" if len(shown) < len(rides) else ""
    return _TEMPLATE.format(
        title=html.escape(title),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        rides=stats.rides,
        vehicles=stats.vehicles,
        total_km=f"{stats.total_distance_km:,.1f}",
        median_m=f"{stats.median_distance_m:,.0f}",
        note=html.escape(note),
        hours=hours,
        days=days or '<tr><td colspan="3">No rides</td></tr>',
        top=top or '<tr><td colspan="2">No rides</td></tr>',
        rides_json=rides_json,
        center_lat=center[0],
        center_lng=center[1],
    )


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
  :root {{ --bg:#f7f7f5; --fg:#1d1d1b; --muted:#6b6b66; --card:#fff; --line:#e3e3de; --accent:#1f9d55; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#161615; --fg:#ececea; --muted:#9a9a94; --card:#20201e; --line:#33332f; --accent:#3cc47c; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font:15px/1.45 system-ui, sans-serif; background:var(--bg); color:var(--fg); }}
  main {{ max-width:1100px; margin:0 auto; padding:24px 16px 48px; }}
  h1 {{ font-size:1.5rem; margin:0 0 4px; }}
  h2 {{ font-size:1rem; margin:0 0 12px; }}
  .muted {{ color:var(--muted); }}
  .tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:20px 0; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .tile b {{ display:block; font-size:1.6rem; font-variant-numeric:tabular-nums; }}
  #map {{ height:480px; border-radius:10px; border:1px solid var(--line); }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:12px; margin-top:12px; }}
  .hours {{ display:flex; align-items:flex-end; gap:3px; height:140px; }}
  .bar {{ flex:1; display:flex; flex-direction:column; justify-content:flex-end; height:100%; }}
  .bar span {{ background:var(--accent); border-radius:3px 3px 0 0; min-height:1px; }}
  .bar i {{ font-style:normal; font-size:10px; color:var(--muted); text-align:center; }}
  table {{ width:100%; border-collapse:collapse; }}
  td {{ padding:3px 4px; border-bottom:1px solid var(--line); }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; width:4em; }}
  .spark {{ width:40%; }} .spark span {{ display:block; height:8px; background:var(--accent); border-radius:4px; }}
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
  <div id="map"></div>
  <div class="grid">
    <div class="card"><h2>Rides by hour of day</h2><div class="hours">{hours}</div></div>
    <div class="card"><h2>Rides per day (last 31)</h2><table>{days}</table></div>
    <div class="card"><h2>Most-ridden vehicles</h2><table>{top}</table></div>
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
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  for (const [aLat, aLng, bLat, bLng, plate, when, dist] of rides) {{
    L.polyline([[aLat, aLng], [bLat, bLng]], {{ color: accent, weight: 2, opacity: 0.35 }})
      .bindTooltip(plate + " · " + when + " · " + dist + " m").addTo(map);
    L.circleMarker([bLat, bLng], {{ radius: 2, color: accent, opacity: 0.6 }}).addTo(map);
  }}
</script>
</body>
</html>
"""
