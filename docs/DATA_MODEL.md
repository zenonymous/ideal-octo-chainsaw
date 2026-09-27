# Data model

## Sources

### GO Sharing: goUrban API (`kind = gourban`)

`GET https://greenmo.core.gourban-mobility.com/front/vehicles?lat=<lat>&lng=<lng>&rad=<radius>`

This is an unofficial, undocumented endpoint. It returns a JSON **array** of vehicles.
Fields used (see `gotracker/api.py`):

| Field | Required | Notes |
|-------|----------|-------|
| `id` | yes | Vehicle id, stored as a string |
| `licensePlate` | yes | Stable vehicle identity |
| `position.coordinates` | yes | GeoJSON order: `[lng, lat]` |
| `stateOfCharge` | no | Battery % |
| `remainingKilometers` | no | Not always present |

Unknowns: the unit of `rad`, rate limits, and whether the endpoint still exists in this form.

### GBFS feeds (`kind = gbfs`)

[GBFS](https://gbfs.org) is the open standard for shared-mobility feeds. The
configured URL is normally the auto-discovery `gbfs.json`. The client finds the
vehicle feed in it: `vehicle_status` (v3) or `free_bike_status` (v1/v2, preferring the
English feed list). A vehicle feed URL also works directly. Fields used
(see `gotracker/gbfs.py`):

| GBFS field | Stored as |
|-----------|-----------|
| `vehicle_id` (v3) / `bike_id` (v1/v2) | both `id` and `licensePlate` |
| `lat`, `lon` | `lat`, `lng`. Vehicles without them (docked at a station) are skipped |
| `current_fuel_percent` (0–1) | `stateOfCharge` × 100 |
| `current_range_meters` | `remainingKilometers` ÷ 1000 |

**Privacy rule of GBFS ≥ 2.0:** vehicle ids are rotated to a new random value after
every trip, and vehicles in use are not listed. A ride therefore shows up as "id X
disappeared at A, and later a new id Y appeared at B". The two cannot be linked
reliably. `reserved`/`disabled` flags are not stored.

Built-in presets (`gotracker/providers.py`) come from the MobilityData
[systems catalogue](https://github.com/MobilityData/gbfs/blob/master/systems.csv),
as of September 2026.

## Database

`gotracker/schema.sql` defines fresh installs. `./gopoll.py migrate` creates missing
tables and upgrades existing ones. Use `--dry-run` to see the SQL first.

### `go`: movements

One row per first sighting of a `(provider, licensePlate)`, plus one per detected
movement.

| Column | Notes |
|--------|-------|
| `row_id` | Auto-increment PK. **Only in tables created from schema.sql.** Code must not depend on it |
| `provider` | e.g. `go_sharing`, `check_almere`, `felyx_amsterdam`, or a custom name |
| `id` | Vehicle id from the source |
| `licensePlate` | Plate (GO Sharing) or GBFS vehicle id. VARCHAR(64) |
| `stateOfCharge` | Battery % |
| `lat`, `lng` | |
| `remainingKilometers` | NULL if unknown |
| `date` | Filled by `DEFAULT CURRENT_TIMESTAMP` (database server time) |

Index `(provider, licensePlate, date)` is used for the "latest row per vehicle" lookup.

For GBFS providers, most rows in `go` are first sightings of freshly rotated ids,
which is effectively "a vehicle appeared here".

### `go_snapshot`: every observation

Written for providers selected by `GOPOLL_STORE_SNAPSHOTS` (`gbfs` by default, or
`all`/`none`). It has the same columns as `go`, with `observed_at` in place of `date`.
`observed_at` is identical for all rows of one provider poll, so
`COUNT(*) GROUP BY provider, observed_at` gives availability per poll.

Volume is roughly vehicles × polls per day. For example, 1,000 vehicles every
5 minutes is about 290k rows a day.

### Migrating the original 2022 table

The original `go` table was created by hand and its DDL was never committed.
`migrate` inspects it through `information_schema` and makes one `ALTER TABLE`:

- `ADD COLUMN provider VARCHAR(32) NOT NULL DEFAULT 'go_sharing'`: existing rows are
  attributed to GO Sharing.
- `MODIFY` `id` / `licensePlate` to VARCHAR(64) if they are narrower CHAR/VARCHAR or
  integers. Nullability is kept. Columns with a default or AUTO_INCREMENT are left
  alone, with a note.
- `ADD KEY (provider, licensePlate, date)`.

No data is dropped or rewritten. Running `migrate` again is a no-op. `poll` refuses
to run while `go` (or `go_snapshot`, when snapshots are on) is missing or has no
`provider` column, and prints the command to use.

## Rides (derived, not stored)

`gotracker/rides.py` walks observations per `(provider, plate)` in time order. Two
consecutive observations at least `min_distance_m` apart form a **ride**:

- `start_time` = the last time it was seen at the old spot and `end_time` = the first
  time it was seen at the new one. The ride happened within that window.
- `distance_m` is the straight-line distance, not the route.
- `range_used_km` / `charge_used_pct` are before minus after. They are negative after
  a battery swap.

This works for GO Sharing. For GBFS providers it only finds moves where the id did not
rotate, for example staff relocations or feeds that don't follow the rotation rule.
