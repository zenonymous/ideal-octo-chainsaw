# CLAUDE.md: guide for agents working on this repo

## What this project is

A single-script data collector (`gopoll.py`, about 30 lines, Python 3). It polls the
public goUrban "front" API used by **GO Sharing** (green shared e-mopeds in the
Netherlands) and logs vehicle movements into a MySQL/MariaDB table named `go`. The
hard-coded centre point `52.364431, 5.222011` is Almere Centrum, NL.

It is a personal hobby project from April 2022. There are no tests, no packaging
and no config files. The README calls the vehicles "scooters". In practice they are
e-mopeds.

## Repository layout

```
gopoll.py          the whole program; run directly (has a shebang, is executable)
requirements.txt   runtime deps (requests, PyMySQL)
README.md          user-facing overview
docs/DATA_MODEL.md API fields used + inferred `go` table schema
docs/KNOWN_ISSUES.md  bugs and limitations found in the current code; read before changing logic
```

## Control flow of gopoll.py

1. `pymysql.connect(host='localhost', user='user', password='password', db='db')`.
   These are placeholder credentials. The real ones were never committed.
2. `GET .../front/vehicles?lat=52.364431&lng=5.222011&rad=500` returns a JSON list
   of vehicles. The unit of `rad` is unknown (it was 5 before, then raised to 500).
3. For each vehicle:
   - `SELECT lng, lat, remainingKilometers FROM go WHERE licensePlate=%s ORDER BY date DESC LIMIT 1`
   - Skip the vehicle if the API item has no `remainingKilometers`.
   - Skip it if there is no previous row. **This means new vehicles are never recorded.**
   - Compute the *percentage* change of lng and lat relative to the new value.
   - Insert (`INSERT IGNORE`) only if |Δlng%| > 1 or |Δlat%| > 1, **and**
     `remainingKilometers` differs from the last row.
4. One `db.commit()` at the end.

## History of the filtering logic

This explains why the code looks the way it does:

| Commit | Change |
|--------|--------|
| 573606f | Insert every vehicle on every run (`remainingKilometers` defaulted to 0 when missing) |
| db38641 | "GPS is not accurate": only insert when `remainingKilometers` changed |
| 8f3c9bf | Compare `result[0]` (the tuple was being compared before) and require a previous row |
| 5f97880 | Also require a lat/lng change, to skip parked vehicles whose battery is just draining |
| c0cec44 | Threshold raised to 1% (with a sign bug) |
| 9e64d9a | Sign bug fixed: `< -1.0` |

The author's intent was to **record rides, not GPS jitter or idle battery drain**.

## Conventions and gotchas

- Code style is loose: mixed 2- and 4-space indentation and nested `with db.cursor()`
  that shadows the outer cursor. If you rewrite the script, move to 4 spaces and PEP 8.
- API coordinates are GeoJSON order `[lng, lat]`. The DB stores `lat` and `lng`
  as separate columns. Keep the order straight.
- `cursor.execute(sql, (item['licensePlate']))` passes a bare string, not a
  1-tuple. PyMySQL accepts this, but `(x,)` is the intended form.
- `datetime` and `json` are imported but unused.
- The upstream API is undocumented and unofficial. Its field names are known only
  from this code. Treat it as fragile.

## Running / testing

There is no test suite. To exercise the script you need network access to
`greenmo.core.gourban-mobility.com` and a reachable MySQL with the `go` table (DDL
in `docs/DATA_MODEL.md`). Note: from the Claude Code cloud sandbox this host was
blocked by the network policy (HTTP 403 at the proxy), so the API's current
availability and response shape could not be re-verified.

## Before changing behaviour

Read `docs/KNOWN_ISSUES.md`. Several "obvious" fixes, such as the 1% threshold or
bootstrap on an empty table, change which rows get stored. Confirm the intent with
the owner first.
