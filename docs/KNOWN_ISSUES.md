# Known issues

Found during a code review in September 2026. Line numbers refer to `gopoll.py` at
commit 9e64d9a.

## 1. New vehicles are never recorded (bootstrap bug)

`gopoll.py:22`: rows are inserted only `if result is not None`, meaning a previous
row must already exist for the plate. With an empty table the script inserts nothing,
ever. Any vehicle added to the fleet after the table was first filled (by the
pre-8f3c9bf version, which inserted everything) is invisible. Fix: insert when
`result is None`.

## 2. The "1% coordinate change" threshold is about 3.5 km or about 58 km

`gopoll.py:23-25` computes the *percentage* change of each coordinate. Near Almere
(lat 52.36, lng 5.22):

- 1% of longitude = 0.052° ≈ **3.5 km** east–west
- 1% of latitude = 0.52° ≈ **58 km** north–south

So a ride is recorded only if the moped ends up about 3.5 km or more further east or
west. Most short rides, and nearly every north–south ride, are dropped. A percentage
of a coordinate is also location-dependent: it behaves differently elsewhere and
divides by zero at lng 0. The right metric is the haversine distance in metres
against a threshold of, say, 100–300 m.

## 3. `INSERT IGNORE` may hide errors or drop rows

`INSERT IGNORE` hides duplicate-key errors and also downgrades some data errors to
warnings. If `id` is a unique key (see DATA_MODEL.md), rows are silently discarded.

## 4. No robustness

- No HTTP timeout, and no `raise_for_status()`. A hung or failed request hangs or
  crashes the cron job.
- `item['stateOfCharge']` and `item['position']` are accessed without checks, so one
  malformed item aborts the whole run. Nothing has been committed at that point,
  so the whole snapshot is lost.
- No logging.

## 5. Configuration is hard-coded

DB credentials (placeholders), the API URL, the centre point, the radius and the
thresholds are all literals in the script. Real credentials must be edited into the
file, which risks committing them.

## 6. Minor code quality

- Unused imports `datetime` and `json`.
- `(item['licensePlate'])` is not a tuple.
- Mixed indentation and a shadowed `cursor` variable.
- N+1 queries: one `SELECT` per vehicle per run.
- No `requirements.txt` existed before September 2026.
