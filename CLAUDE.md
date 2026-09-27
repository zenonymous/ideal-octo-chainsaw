# CLAUDE.md: guide for agents working on this repo

## What this project is

A small data collector. It polls the public goUrban "front" API used by **GO Sharing**
(green shared e-mopeds in the Netherlands) around Almere Centrum
(`52.364431, 5.222011`) and records vehicle movements in a MySQL/MariaDB table named `go`.
It can also derive rides and render a CSV or HTML report from the stored data.

It started in April 2022 as a 30-line hobby script. It was restructured into the
`gotracker` package in September 2026 (v2, see CHANGELOG.md). The README calls the
vehicles "scooters". In practice they are e-mopeds.

## Layout

```
gopoll.py                 backwards-compatible entry point (existing cron jobs call it); forwards to gotracker.cli
gotracker/
  cli.py                  argparse commands: poll (default), init-db, rides, report
  config.py               Config dataclass; all settings from GOPOLL_* env vars / .env
  api.py                  fetch + parse the vehicles endpoint -> Vehicle; skips malformed items
  geo.py                  haversine_m()
  movement.py             should_record(): the "did it move?" rule. Pure function, heavily tested
  poll.py                 poll_once() orchestration (Store protocol, so tests use a fake); run() loop
  db.py                   Repository: all SQL lives here
  rides.py                Observation -> Ride detection, summarize() stats
  report.py               CSV writer and standalone HTML report (Leaflet map from cdnjs, CSS charts)
  schema.sql              CREATE TABLE IF NOT EXISTS for go + go_snapshot
tests/test_core.py        unit tests (no network, no DB)
tests/test_db_integration.py  real MySQL test; runs only when GOPOLL_TEST_DB_NAME is set; DROPS go/go_snapshot there
deploy/systemd/           oneshot service + 5-minute timer
Dockerfile, docker-compose.yml   container image; compose bundles MariaDB
.github/workflows/ci.yml  ruff + pytest (with a MariaDB service) on 3.9 and 3.12
```

## Key rules and invariants

- **Existing `go` table compatibility is a hard requirement.** The owner has data from
  2022 in a table whose exact DDL is unknown. Only use the columns
  `id, licensePlate, stateOfCharge, lat, lng, remainingKilometers, date`. Don't rely
  on `row_id` (it exists only in tables created by `init-db`). Never `ALTER` in
  `init-db`. `date` is filled by the column default, not by the script.
- API coordinates are GeoJSON `[lng, lat]`. `api.parse_vehicle` swaps them into
  `Vehicle.lat`/`.lng`. Everything after that uses named fields.
- Movement rule (`movement.should_record`): record if first sighting, or if moved at
  least `min_distance_m` **and** (`remainingKilometers` changed, or either value is
  unknown, or `require_range_change` is off).
- Per-vehicle insert errors are logged and skipped. The rest of the poll is still
  committed. An API failure writes nothing and exits with 1. DB connection or query
  failure exits with 2.
- Python ≥ 3.9. Every module has `from __future__ import annotations`, so `X | None`
  is fine in annotations but not in runtime expressions.
- Dependencies: `requests`, `PyMySQL`, `python-dotenv`. Keep the runtime footprint small.

## Commands

```sh
pip install -r requirements-dev.txt
ruff check . && ruff format --check .     # line length 120, E501 ignored for long SQL/HTML strings
pytest                                    # unit tests
GOPOLL_TEST_DB_NAME=gotest GOPOLL_TEST_DB_USER=... GOPOLL_TEST_DB_PASSWORD=... pytest   # + integration
./gopoll.py -v                            # one poll with debug output (needs .env + network)
```

Offline end-to-end testing: serve a JSON file with `python -m http.server` and set
`GOPOLL_API_URL=http://127.0.0.1:8000/vehicles.json`.

## Environment notes (Claude Code cloud sandbox)

- The real API host `greenmo.core.gourban-mobility.com` and the cdnjs and OpenStreetMap
  hosts were blocked by the sandbox network policy (proxy 403). The live API
  response has not been re-verified since 2022.
- MariaDB can be installed with apt and started with
  `mysqld_safe --user=mysql &` (create `/run/mysqld` first).
- The system Python's `cryptography` package was broken there, so use a venv.

## Open questions (ask the owner before changing related behaviour)

- The real DDL of the production `go` table. In particular, whether `id` is unique:
  if it is, inserts fail with IntegrityError, which is now logged loudly.
- The unit of the API's `rad` parameter (the default 500 is kept from 2022).
- The production polling interval. Docs assume 5 minutes.
