"""Command line entry point: ``python -m gotracker <command>``."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pymysql

from . import __doc__ as package_doc
from . import __version__, db
from .config import Config, ConfigError
from .poll import run
from .providers import PRESETS
from .report import render_html, summarize_availability, write_csv
from .rides import detect_rides, summarize

log = logging.getLogger("gotracker")


def _date(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date/time: {value!r}") from None


def _default_env_file() -> Path | None:
    # cron runs jobs from $HOME, so also look next to the project, not just in the cwd.
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if candidate.is_file():
            return candidate
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gotracker", description=package_doc)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--env-file", help="dotenv file to load (default: ./.env, else .env next to gopoll.py)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging (overrides GOPOLL_LOG_LEVEL)")
    sub = p.add_subparsers(dest="command")

    poll = sub.add_parser("poll", help="fetch vehicles once from every provider and record them (default)")
    poll.add_argument("--every", type=float, metavar="SECONDS", help="keep polling at this interval")

    for name in ("migrate", "init-db"):
        m = sub.add_parser(
            name,
            help="create missing tables and upgrade existing ones (adds `provider` to `go`)"
            + (" [alias of migrate]" if name == "init-db" else ""),
        )
        m.add_argument("--dry-run", action="store_true", help="only print the SQL that would run")

    sub.add_parser("providers", help="list built-in providers and the configured ones")

    for name, help_ in (("rides", "print detected rides as CSV"), ("report", "write an HTML map/stats report")):
        s = sub.add_parser(name, help=help_)
        s.add_argument(
            "--source",
            choices=sorted(db.SOURCES),
            default="movements",
            help="movements = `go` table (default); snapshots = `go_snapshot`",
        )
        s.add_argument("--provider", action="append", default=[], help="only this provider (repeatable)")
        s.add_argument("--since", type=_date, help="only rows at/after this time (ISO format)")
        s.add_argument("--until", type=_date, help="only rows before this time (ISO format)")
        s.add_argument(
            "--max-window-hours",
            type=float,
            metavar="H",
            help="drop rides whose observed start/end window is longer than this (e.g. after data gaps)",
        )
        s.add_argument(
            "--min-distance",
            type=float,
            metavar="M",
            help="metres between observations that count as a ride (default: GOPOLL_MIN_DISTANCE_M)",
        )
        s.add_argument(
            "-o", "--output", default="-" if name == "rides" else "report.html", help="output file ('-' for stdout)"
        )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = Config.from_env(dotenv_path=args.env_file or _default_env_file())
    except ConfigError as e:
        print(f"configuration error: {e}", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    command = args.command or "poll"

    if command == "poll":
        return run(config, every=getattr(args, "every", None))
    if command == "providers":
        return _list_providers(config)

    try:
        conn = db.connect(config)
    except pymysql.MySQLError as e:
        log.error("cannot connect to the database: %s", e)
        return 2
    repo = db.Repository(conn)
    try:
        if command in ("migrate", "init-db"):
            return _migrate(repo, args.dry_run)
        observations = repo.load_observations(args.source, args.since, args.until, args.provider)
        availability = repo.availability(args.since, args.until, args.provider) if command == "report" else []
    except pymysql.MySQLError as e:
        hint = " (run `migrate` to create or upgrade tables)" if e.args and e.args[0] in (1054, 1146) else ""
        log.error("database error: %s%s", e, hint)
        return 2
    finally:
        repo.close()

    min_distance = args.min_distance if args.min_distance is not None else config.min_distance_m
    rides = detect_rides(observations, min_distance)
    if args.max_window_hours is not None:
        rides = [r for r in rides if r.window_minutes <= args.max_window_hours * 60]
    rides.sort(key=lambda r: r.end_time)
    log.info("%d observations -> %d rides", len(observations), len(rides))

    if command == "rides":
        if args.output == "-":
            write_csv(rides, sys.stdout)
        else:
            with open(args.output, "w", newline="", encoding="utf-8") as f:
                write_csv(rides, f)
        return 0

    page = render_html(
        rides,
        summarize(rides),
        "Ride-share vehicles",
        (config.lat, config.lng),
        availability=summarize_availability(availability),
        provider_order=[p.name for p in config.providers],
    )
    if args.output == "-":
        sys.stdout.write(page)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(page)
        log.info("wrote %s", args.output)
    return 0


def _migrate(repo: db.Repository, dry_run: bool) -> int:
    plan = repo.plan_migration()
    for note in plan.notes:
        log.info("%s", note)
    if not plan.statements:
        log.info("schema is up to date")
        return 0
    for statement in plan.statements:
        print(statement + ";\n")
    if dry_run:
        log.info("dry run: nothing changed")
        return 0
    repo.migrate(plan)
    log.info("applied %d statement(s)", len(plan.statements))
    return 0


def _list_providers(config: Config) -> int:
    configured = {p.name for p in config.providers}
    print("Configured (GOPOLL_PROVIDERS):")
    for p in config.providers:
        snap = "snapshots" if config.stores_snapshots(p) else "movements only"
        print(f"  {p.name:<20} {p.label or p.url}  [{snap}]")
    print("\nBuilt-in presets:")
    for name, p in PRESETS.items():
        mark = "*" if name in configured else " "
        print(f" {mark}{name:<20} {p.label}")
    print("\nAny other GBFS feed: add name=https://.../gbfs.json to GOPOLL_PROVIDERS.")
    return 0
