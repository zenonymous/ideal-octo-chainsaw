# Known issues

## Open

1. **Unverified live feeds.** Neither the goUrban endpoint nor the GBFS feeds could be
   reached from the development sandbox. The GBFS client follows the spec (v1–v3) and
   is tested against spec-shaped fixtures. Feed URLs come from the MobilityData
   catalogue and can change. If a preset breaks, override it with `name=URL`.
2. **GBFS rides can't be followed.** Vehicle ids rotate after each trip (see
   [DATA_MODEL.md](DATA_MODEL.md)). Rides and "most-ridden vehicles" in the report are
   meaningful only for GO Sharing. Use availability for GBFS providers.
3. **Snapshot volume.** Whole-city GBFS feeds can have thousands of vehicles. There is
   no area filter or retention job yet. Prune `go_snapshot` by `observed_at` if needed.
4. **Legacy table DDL unknown.** Check `migrate --dry-run` before applying it to
   production. A UNIQUE key on `id` would make inserts fail, which is now logged.
5. **Same-second ties.** `date` has 1-second resolution. If two rows for one vehicle
   share a timestamp, "latest row" picks either one.
6. **Timezones.** Timestamps use the DB server's time zone (`CURRENT_TIMESTAMP`).
7. **Straight-line distances** underestimate real ride length.
8. **Report needs internet** for Leaflet (cdnjs) and map tiles (OpenStreetMap). Offline
   it shows a notice where the map would be.
9. **Map colours:** only three providers get their own colour. The rest share
   "Other", but the provider table and tooltips still name them.
10. **Schema check is shallow.** Before polling, only the tables and the `provider`
    column are checked. If `migrate` could not widen `id`/`licensePlate` (for example
    because the column has a default), long GBFS ids fail per row with a logged
    DataError that points to `migrate`.

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
