# ideal-octo-chainsaw

Read ride-share vehicle feeds and store a record in a database when a scooter has moved.

`gotracker` polls shared e-moped, e-scooter and e-bike services in the Netherlands and
stores what it sees in MySQL/MariaDB. You can then turn the data into rides, a CSV
export or an HTML report with a map and charts. Sources:

- **GO Sharing**, through the goUrban app API around Almere. It has license plates, so
  individual rides can be followed.
- Any service with a public **GBFS** feed. Presets are built in for **Check** (Almere),
  **Felyx** (14 cities) and **Dott** (4 cities), and any other feed can be added by URL.

## Quick start

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set the DB credentials and GOPOLL_PROVIDERS
./gopoll.py migrate           # create/upgrade tables (use --dry-run to see the SQL first)
./gopoll.py                   # one poll of every configured provider
```

Run it on a schedule. Any of these works:

- **cron**: `*/5 * * * * /path/to/ideal-octo-chainsaw/.venv/bin/python /path/to/ideal-octo-chainsaw/gopoll.py`
- **systemd timer**: see [deploy/systemd/README.md](deploy/systemd/README.md)
- **Docker Compose** (includes MariaDB): `cp .env.example .env && docker compose up -d`
- **built-in loop**: `./gopoll.py poll --every 300`

## Choosing services

```sh
./gopoll.py providers         # list presets and what is configured
```

```ini
# .env
GOPOLL_PROVIDERS=go_sharing,check_almere,felyx_amsterdam,mycity=https://example.com/gbfs.json
```

Each provider is fetched and committed separately, so one service being down doesn't
affect the others. More GBFS feeds are listed in the
[MobilityData catalogue](https://github.com/MobilityData/gbfs/blob/master/systems.csv).

**GBFS vs. GO Sharing.** The GBFS standard requires operators to give a vehicle a new
random id after every trip, and rented vehicles are hidden from the feed. For GBFS
services you therefore can't follow a vehicle from ride to ride. By default every
vehicle on every poll is stored for them (`go_snapshot`), and the report shows their
**availability over time**. GO Sharing exposes stable plates, so its rides are tracked.

## Commands

`./gopoll.py <command>` or `python -m gotracker <command>` (after `pip install .` you can
also use `gotracker <command>`).

| Command | What it does |
|---------|--------------|
| `poll` (default) | Fetch every provider once and store what moved, plus snapshots. `--every SECONDS` loops. |
| `migrate` | Create missing tables and upgrade existing ones. `--dry-run` prints the SQL. `init-db` is an alias. |
| `providers` | List built-in presets and the configured providers. |
| `rides` | Print detected rides as CSV (`-o rides.csv` to write a file). |
| `report` | Write `report.html`: map of rides per provider, rides per hour and per day, busiest vehicles, availability. |

`rides` and `report` accept `--provider NAME` (repeatable), `--since 2026-09-01`,
`--until ...`, `--source movements|snapshots`, `--min-distance M` and
`--max-window-hours H`. Add `-v` for debug logging, which shows why each vehicle was
recorded or skipped.

## What gets stored

- **`go`, movements:** a vehicle is recorded when it has **never been seen before**
  for that provider, or when it is at least `GOPOLL_MIN_DISTANCE_M` (default
  **200 m**) from its last stored position **and** its remaining range changed.
  The range check can be turned off with `GOPOLL_REQUIRE_RANGE_CHANGE=false`.
- **`go_snapshot`, every observation:** controlled by `GOPOLL_STORE_SNAPSHOTS`:
  `gbfs` (default), `all` or `none`. Snapshots grow quickly: 1,000 vehicles every
  5 minutes is about 290k rows a day.

Details: [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

## Configuration

All settings are environment variables, optionally set in `.env`. See
[.env.example](.env.example) for the full list with defaults.

## Development

```sh
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
pytest                      # DB integration tests are skipped unless GOPOLL_TEST_DB_NAME is set
```

## Documentation

| File | Contents |
|------|----------|
| [CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md) | Guide for AI coding agents and new contributors |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Feeds, database schema, migrations, rides |
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | Limitations and fixed bugs |
| [CHANGELOG.md](CHANGELOG.md) | Release notes and upgrade steps |
