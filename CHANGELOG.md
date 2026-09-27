# Changelog

## 2.1.0 (September 2026)

**Multiple ride-share services.**
- `GOPOLL_PROVIDERS` selects what to poll: `go_sharing` (the default, same as before),
  built-in GBFS presets (`check_almere`, `felyx_<city>` ×14, `dott_<city>` ×4), and
  custom GBFS feeds as `name=URL`. `./gopoll.py providers` lists them.
- New GBFS client (spec v1–v3, auto-discovery).
- Every row now has a `provider` column. Vehicle identity is `(provider, licensePlate)`.
- `GOPOLL_STORE_SNAPSHOTS` is now `gbfs` (default) / `all` / `none`. `true`/`false`
  still work and mean `all`/`none`.
- Each provider is fetched and committed separately. Exit code 1 if any provider failed.
- Report: rides coloured per provider with a legend, a providers table, an
  availability section (vehicles seen per poll, hourly averages) and `--provider`
  filters. CSV has a `provider` column.
- New `migrate` command with `--dry-run`. `init-db` is now an alias.

**Upgrading from 2.0 or from the 2022 script:**
1. `./gopoll.py migrate --dry-run` to review the SQL. It adds `provider` to `go`
   (existing rows become `go_sharing`), widens `id`/`licensePlate` to VARCHAR(64), adds
   an index, and creates `go_snapshot`.
2. `./gopoll.py migrate`. Until this has run, `poll` exits with code 2 and a message
   (it checks that the tables and the `provider` column exist).
3. Add providers to `GOPOLL_PROVIDERS` in `.env`.

## 2.0.0 (September 2026)

Restructured the single script into the `gotracker` package. `./gopoll.py` with no
arguments still does one poll, so existing cron jobs keep working. They do need a
`.env` (or `GOPOLL_*` variables) for credentials; see Upgrading.

**Behaviour changes. These change which rows get stored:**
- Plates never seen before are now recorded, as a baseline row.
- Movement means a haversine distance of at least 200 m (configurable), not a
  "1% coordinate change". Many more real rides will be recorded.
- Vehicles without `remainingKilometers` are no longer always skipped.
- `INSERT IGNORE` became `INSERT`: key conflicts are now logged instead of silently dropped.

**New:**
- Configuration through `GOPOLL_*` env vars / `.env` (`.env.example`).
- Commands: `init-db`, `rides` (CSV), `report` (HTML map and stats), `poll --every N`.
- Optional `go_snapshot` table storing every observation (`GOPOLL_STORE_SNAPSHOTS=true`).
- Robustness: HTTP timeout, per-item error handling, logging, exit codes.
- Tests (unit + MariaDB integration), ruff, GitHub Actions CI.
- Dockerfile, docker-compose (with MariaDB), systemd service and timer.

**Upgrading an existing install:**
1. `pip install -r requirements.txt` (adds `python-dotenv`).
2. `cp .env.example .env` and move your DB credentials from the old `gopoll.py` into it.
3. Optional: `./gopoll.py init-db`. In 2.0 it added `go_snapshot` and left `go` untouched.
   From 2.1 on, `init-db` is an alias of `migrate`, which also upgrades `go`; follow the
   2.1 steps above instead.

## 1.x (April 2022)

The original `gopoll.py`: see the git history (commits 573606f to 9e64d9a).
