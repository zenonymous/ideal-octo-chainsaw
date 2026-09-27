# Data model

## Upstream API

`GET https://greenmo.core.gourban-mobility.com/front/vehicles?lat=<lat>&lng=<lng>&rad=<radius>`

This is an unofficial, undocumented endpoint of the goUrban platform that GO Sharing
runs on. It returns a JSON **array** of vehicle objects. Fields used (see `gotracker/api.py`):

| Field | Required | Notes |
|-------|----------|-------|
| `id` | yes | Vehicle id, stored as a string |
| `licensePlate` | yes | Vehicle identity when looking up history |
| `position.coordinates` | yes | GeoJSON order: `[lng, lat]` |
| `stateOfCharge` | no | Battery %, stored as NULL when missing |
| `remainingKilometers` | no | **Not always present.** When missing, only the distance rule applies |

Items missing a required field are logged and skipped.

Unknowns: the unit of `rad` (it was 5 in 2022, then 500), rate limits, and whether the
endpoint still exists in this form.

## Database

`gotracker/schema.sql` is the source of truth for new installs. `init-db` runs it with
`CREATE TABLE IF NOT EXISTS`, so it never touches existing tables.

### `go`: movements

One row per first sighting of a plate, plus one per detected movement.

| Column | Notes |
|--------|-------|
| `row_id` | Auto-increment PK. **Only in tables created by `init-db`.** Code must not depend on it |
| `id` | Vehicle id from the API |
| `licensePlate` | |
| `stateOfCharge` | Battery % |
| `lat`, `lng` | |
| `remainingKilometers` | NULL if the API omitted it |
| `date` | Filled by `DEFAULT CURRENT_TIMESTAMP` (database server time) |

Index `(licensePlate, date)`: used for the "latest row per plate" lookup.

**Legacy tables:** the original 2022 table was created by hand and its DDL was never
committed. The code only uses the columns above (without `row_id`), so it works with
any table that has them. It was tested against one with VARCHAR `lat`/`lng` and no
keys. If the legacy table has a UNIQUE key on `id`, each vehicle can only ever have
one row. Inserts now fail visibly (logged IntegrityError) instead of being silently
dropped by `INSERT IGNORE` as they were before.

### `go_snapshot`: every observation (optional)

Written only when `GOPOLL_STORE_SNAPSHOTS=true`. Each poll inserts every vehicle, with
the same columns as `go` and `observed_at` in place of `date`. Expect roughly
(number of vehicles × polls per day) rows per day, for example 300 × 288 ≈ 86k/day
at a 5-minute interval.

## Rides (derived, not stored)

`gotracker/rides.py` walks observations per plate in time order. Two consecutive
observations at least `min_distance_m` apart form a **ride**:

- `start_time` = the last time it was seen at the old spot and `end_time` = the first
  time it was seen at the new one. The ride happened somewhere inside that window.
- `distance_m` is the straight-line distance, not the route.
- `range_used_km` / `charge_used_pct` are before minus after. They are negative after
  a battery swap.

From `go` (movements) the window can be long, because a movement row is written only
after the move. From `go_snapshot` it is at most about one poll interval longer than
the real ride.
