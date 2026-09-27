# ideal-octo-chainsaw

Read the GO Sharing vehicle API and store a record in a database when a scooter has moved.

`gotracker` polls the public vehicle feed that GO Sharing (green shared e-mopeds, run
on the goUrban platform) uses for its app. It covers the area around Almere, NL, and
stores a row in MySQL/MariaDB every time a moped has been ridden. You can then turn
the data into rides, a CSV export or an HTML report with a map and charts.

## Quick start

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set the DB credentials
./gopoll.py init-db           # create missing tables (never alters existing ones)
./gopoll.py                   # one poll, same as the original script
```

Run it on a schedule. Any of these works:

- **cron**: `*/5 * * * * /path/to/ideal-octo-chainsaw/.venv/bin/python /path/to/ideal-octo-chainsaw/gopoll.py`
- **systemd timer**: see [deploy/systemd/README.md](deploy/systemd/README.md)
- **Docker Compose** (includes MariaDB): `cp .env.example .env && docker compose up -d`
- **built-in loop**: `./gopoll.py poll --every 300`

## Commands

`./gopoll.py <command>` or `python -m gotracker <command>` (after `pip install .` you can
also use `gotracker <command>`).

| Command | What it does |
|---------|--------------|
| `poll` (default) | Fetch vehicles once and record the ones that moved. `--every SECONDS` loops. |
| `init-db` | Create `go` / `go_snapshot` if missing. |
| `rides` | Print detected rides as CSV (`-o rides.csv` to write a file). |
| `report` | Write `report.html`: a map of rides, rides per hour and per day, and the busiest vehicles. |

`rides` and `report` accept `--since 2026-09-01`, `--until ...`,
`--source movements|snapshots`, `--min-distance M` and `--max-window-hours H`.
Add `-v` for debug logging, which shows why each vehicle was recorded or skipped.

## What counts as a movement

A vehicle is recorded when:

- it has **never been seen before** (this gives a baseline row), or
- it is at least `GOPOLL_MIN_DISTANCE_M` (default **200 m**) from its last stored
  position, **and** its `remainingKilometers` changed. The range check can be turned
  off with `GOPOLL_REQUIRE_RANGE_CHANGE=false`.

With `GOPOLL_STORE_SNAPSHOTS=true` every vehicle on every poll is also stored in
`go_snapshot`. This gives much tighter ride start and end times, at the cost of more rows.

## Configuration

All settings are environment variables, optionally set in `.env`. See
[.env.example](.env.example) for the full list with defaults.

## Development

```sh
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
pytest                      # DB integration test skipped unless GOPOLL_TEST_DB_NAME is set
```

## Documentation

| File | Contents |
|------|----------|
| [CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md) | Guide for AI coding agents and new contributors |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | API response shape and database schema |
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | Limitations, and the bugs fixed in v2 |
| [CHANGELOG.md](CHANGELOG.md) | What changed between the 2022 script and v2 |
