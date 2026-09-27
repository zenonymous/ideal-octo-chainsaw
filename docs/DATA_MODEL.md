# Data model

## Upstream API

`GET https://greenmo.core.gourban-mobility.com/front/vehicles?lat=<lat>&lng=<lng>&rad=<radius>`

This is an unofficial, undocumented endpoint of the goUrban platform that GO Sharing
runs on. It returns a JSON **array** of vehicle objects. The fields `gopoll.py` relies on:

| Field | Type (observed / assumed) | Notes |
|-------|---------------------------|-------|
| `id` | string or int | Vehicle id from the API |
| `licensePlate` | string | Used as the vehicle identity when looking up history |
| `stateOfCharge` | number | Battery %, stored as is |
| `remainingKilometers` | number | **Not always present.** Items without it are skipped |
| `position.coordinates` | `[lng, lat]` | GeoJSON order: index 0 = longitude, 1 = latitude |

Unknowns: the unit of `rad` (it was 5, then 500), rate limits, and whether the
endpoint still exists in this form.

## Database: table `go`

The schema was never committed. This is what the SQL in `gopoll.py` implies:

```sql
CREATE TABLE `go` (
  `id`                  VARCHAR(64)   NOT NULL,   -- vehicle id from the API (type unknown)
  `licensePlate`        VARCHAR(16)   NOT NULL,
  `stateOfCharge`       INT,
  `lat`                 DECIMAL(9,6)  NOT NULL,
  `lng`                 DECIMAL(9,6)  NOT NULL,
  `remainingKilometers` DECIMAL(6,1),
  `date`                TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- not set by the script, so it must default
  KEY `idx_plate_date` (`licensePlate`, `date`)
);
```

Open questions about the real schema:

- **Is there a PRIMARY/UNIQUE key on `id`?** The script uses `INSERT IGNORE`. If
  `id` (the vehicle id) is unique, then only **one row per vehicle** can ever exist
  and every later insert is silently dropped. Presumably that is not the case
  (maybe there is an auto-increment PK, or a unique key on `(id, date)`), but it is
  unverified.
- Column types are guesses. `lat`/`lng` are read back with `float(...)`, which
  suggests DECIMAL or string storage.

Each row means "at `date` this vehicle was observed at (`lat`, `lng`) with this
charge, and it had moved and lost range since its previous row".
