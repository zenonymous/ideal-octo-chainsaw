# CLAUDE.md: guide for agents working on this repo

## What this project is

A small data collector for Dutch ride-share vehicles. On each poll it fetches every
configured **provider** and writes to MySQL/MariaDB:

- `go`: movements, meaning first sightings plus moves of at least N metres.
- `go_snapshot`: optionally, every vehicle seen on every poll.

It can also derive rides and render a CSV or HTML report.

Providers come in two kinds:

- `gourban`: GO Sharing's unofficial app API around Almere (`52.364431, 5.222011`).
  It has stable license plates, so rides can be followed per vehicle.
- `gbfs`: any standard GBFS feed (Check, Felyx, Dott, or a custom URL). GBFS ≥2.0
  **rotates vehicle ids after every trip** and hides rented vehicles, so per-vehicle
  ride tracking mostly doesn't work. Snapshots and availability are the useful data.

History: a 30-line script from April 2022, restructured in v2.0 (September 2026) and
made multi-provider in v2.1. Both are merged into `main`
(zenonymous/ideal-octo-chainsaw#1 and #2). See CHANGELOG.md.

## Layout

```
gopoll.py                 backwards-compatible entry point (existing cron jobs call it); forwards to gotracker.cli
gotracker/
  cli.py                  commands: poll (default), migrate (alias init-db), providers, rides, report
  config.py               Config dataclass; all settings from GOPOLL_* env vars / .env
  providers.py            ProviderSpec, PRESETS (catalogue URLs), parse_providers(GOPOLL_PROVIDERS)
  api.py                  goUrban client -> Vehicle; also defines Vehicle and ApiError
  gbfs.py                 GBFS client: discovery (v1-v3), free_bike_status/vehicle_status -> Vehicle
  geo.py                  haversine_m()
  movement.py             should_record(): the "did it move?" rule. Pure, heavily tested
  poll.py                 poll_once() -> poll_provider() per provider (Store protocol; tests use a fake); run() loop
  db.py                   Repository: all SQL, including plan_migration()/migrate() and schema_problems()
  rides.py                Observation -> Ride detection per (provider, plate); summarize()
  report.py               CSV, availability summary, standalone HTML (Leaflet from cdnjs, CSS/SVG charts)
  schema.sql              CREATE TABLE IF NOT EXISTS for go + go_snapshot (fresh installs)
tests/test_core.py        unit tests (no network, no DB); GBFS via tests/fixtures/*.json
tests/test_db_integration.py  real MySQL; runs only when GOPOLL_TEST_DB_NAME is set; DROPS go/go_snapshot there
deploy/systemd/, Dockerfile, docker-compose.yml, .github/workflows/ci.yml
```

## Key rules and invariants

- **Every row carries `provider`.** Identity is `(provider, licensePlate)`. The same
  plate or id at two providers is two vehicles. Every query that looks up history
  must filter by provider.
- For GBFS, `licensePlate` and `id` both hold the GBFS vehicle id. It is often a
  36-character UUID, so those columns are VARCHAR(64).
- **The existing production `go` table** (from 2022, DDL unknown) is only changed by an
  explicit `migrate`. The migration adds `provider` (existing rows become
  `go_sharing`), widens `id`/`licensePlate` to VARCHAR(64) (INT becomes VARCHAR,
  nullability kept, skipped if the column has a default), and adds an index. It never
  drops or rewrites data and always has a `--dry-run`. `poll` refuses to run, with exit
  code 2, while `go` (or `go_snapshot`, when snapshots are on) is missing or has no
  `provider` column (`Repository.schema_problems`). It does not check column widths:
  an un-widened column shows up as a per-row DataError with a `migrate` hint. Don't
  rely on `row_id`, which exists only in tables created from `schema.sql`.
- `go.date` is filled by the column default. `go_snapshot.observed_at` is set
  explicitly from the DB's `CURRENT_TIMESTAMP` once per provider poll, so all rows of
  one poll share a timestamp. `availability()` groups on that.
- goUrban coordinates are GeoJSON `[lng, lat]`. GBFS uses `lat`/`lon` fields,
  `current_fuel_percent` in 0–1 (stored ×100) and `current_range_meters` (stored ÷1000
  as km).
- Movement rule (`movement.should_record`): record if first sighting, or if moved at
  least `min_distance_m` **and** (`remainingKilometers` changed, or either value is
  unknown, or `require_range_change` is off).
- Failure isolation: a per-vehicle insert error is logged and skipped. A provider's
  API or DB failure rolls back only that provider. Exit code 1 means some provider
  failed and 2 means a DB or schema problem.
- Report colours: categorical slots 1–3 are validated for all pairs in light and dark
  (see the comment in report.py). Providers past the third fold into "Other".
  Colours follow the configured provider order, never the ride count.
- Python ≥ 3.9 with `from __future__ import annotations` everywhere. Runtime
  dependencies are `requests`, `PyMySQL` and `python-dotenv`. Keep it small.

## Adding a provider

- **Another GBFS feed:** add a preset in `providers.PRESETS` (URL from the MobilityData
  `systems.csv`), or tell users to use `name=URL`. No other code is needed.
- **A non-GBFS API:** add a client returning `list[Vehicle]`, a new `kind`, and a
  branch in `poll.fetch_from_provider`. Add fixture-based tests like the GBFS ones.

## Keeping the docs current

Docs are part of every change. When you change behaviour, update in the same commit:

| You changed | Update |
|-------------|--------|
| A setting (`config.py`) | `.env.example`, README "Configuration"/"What gets stored" |
| A command or flag (`cli.py`) | README "Commands", the Commands block below |
| The schema or migration (`schema.sql`, `db.py`) | docs/DATA_MODEL.md, CHANGELOG upgrade steps |
| Presets or feed parsing (`providers.py`, `gbfs.py`, `api.py`) | README "Choosing services", docs/DATA_MODEL.md "Sources" |
| Movement or ride logic (`movement.py`, `rides.py`) | README "What gets stored", docs/DATA_MODEL.md "Rides" |
| Found or fixed a limitation | docs/KNOWN_ISSUES.md |
| Anything user-visible | CHANGELOG.md, and the version in `gotracker/__init__.py` when releasing |
| Layout, invariants, workflow | this file |

## Commands

```sh
pip install -r requirements-dev.txt
ruff check . && ruff format --check .     # line length 120, E501 ignored for long SQL/HTML strings
pytest                                    # unit tests
GOPOLL_TEST_DB_NAME=gotest GOPOLL_TEST_DB_USER=... GOPOLL_TEST_DB_PASSWORD=... pytest   # + integration
./gopoll.py -v                            # one poll with debug output (needs .env + network)
./gopoll.py migrate --dry-run             # show pending schema changes
```

Offline end-to-end testing: serve fixture JSON with `python -m http.server`, with URLs
inside the discovery file pointing at it, and configure
`GOPOLL_PROVIDERS=local=http://127.0.0.1:8000/gbfs.json`.

## Environment notes (Claude Code cloud sandbox)

- The sandbox network policy blocked every provider host (goUrban, ridecheck,
  cooltra, ridedott), plus cdnjs and OpenStreetMap. Live feeds have not been verified;
  the GBFS code follows the spec and the tests use spec-shaped fixtures.
- MariaDB can be installed with apt and started with `mysqld_safe --user=mysql &`
  (create `/run/mysqld` first). The system Python's `cryptography` was broken there,
  so use a venv.

## Open questions (ask the owner before changing related behaviour)

- The real DDL of the production `go` table (unique keys?). `migrate --dry-run` prints
  the plan against it.
- The unit of the goUrban `rad` parameter (500 is kept from 2022).
- The production polling interval. Docs assume 5 minutes.
