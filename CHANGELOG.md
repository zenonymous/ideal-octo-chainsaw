# Changelog

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
3. Optional: `./gopoll.py init-db`. It adds `go_snapshot` and leaves `go` untouched.

## 1.x (April 2022)

The original `gopoll.py`: see the git history (commits 573606f to 9e64d9a).
