# Known issues

## Open

1. **Unverified API.** The endpoint is unofficial and its current response was not
   re-checked in 2026, because it was not reachable from the sandbox. If it changed,
   `api.parse_vehicle` is the only place that needs updating.
2. **Legacy table DDL unknown.** See [DATA_MODEL.md](DATA_MODEL.md). A UNIQUE key on
   `id` would make every insert after the first fail. This is now logged, not hidden.
3. **Same-second ties.** `date` has 1-second resolution. If two rows for one plate share
   a timestamp, "latest row" picks either one. This is harmless at normal poll intervals.
4. **Timezones.** `date`/`observed_at` use the DB server's time zone (`CURRENT_TIMESTAMP`).
   The report buckets by those values as stored.
5. **Straight-line distances** underestimate real ride length.
6. **Report needs internet.** The HTML report loads Leaflet from cdnjs and map tiles from
   OpenStreetMap. Offline it shows a notice where the map would be, and the stats
   still render.

## Fixed in v2 (September 2026)

These were found in the original `gopoll.py` (commit 9e64d9a):

| Issue | Was | Now |
|-------|-----|-----|
| Bootstrap bug | Rows were inserted only if the plate already had one, so an empty table stayed empty and new vehicles were never recorded | First sighting is always recorded |
| Distance threshold | "1% change of a coordinate", which near Almere means ≈3.5 km east–west or ≈58 km north–south, so almost every ride was dropped | Haversine distance ≥ `GOPOLL_MIN_DISTANCE_M` (200 m) |
| `INSERT IGNORE` | Silently dropped rows | Plain `INSERT`; errors logged per vehicle |
| No HTTP timeout / status check | Could hang or crash cron | 20 s timeout, `raise_for_status`, exit code 1 |
| One malformed item | Aborted the whole run, losing the snapshot | Item logged and skipped |
| Hard-coded credentials and settings | Edited into the source | `GOPOLL_*` env vars / `.env` |
| N+1 queries | One SELECT per vehicle | One SELECT per poll (chunked) |
| Items without `remainingKilometers` | Always skipped | Judged on distance alone |
| No tests, deps, CI | None | pytest, requirements, GitHub Actions |
