"""Configuration from environment variables (optionally loaded from a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_API_URL = "https://greenmo.core.gourban-mobility.com/front/vehicles"


class ConfigError(ValueError):
    pass


def _get(env: dict, name: str, default: str) -> str:
    value = env.get(name)
    return default if value is None or value == "" else value


def _float(env: dict, name: str, default: float) -> float:
    raw = _get(env, name, str(default))
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None


def _int(env: dict, name: str, default: int) -> int:
    raw = _get(env, name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None


def _bool(env: dict, name: str, default: bool) -> bool:
    raw = _get(env, name, "true" if default else "false").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true/false, got {raw!r}")


@dataclass(frozen=True)
class Config:
    # Database
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "user"
    db_password: str = "password"
    db_name: str = "db"
    # Upstream API
    api_url: str = DEFAULT_API_URL
    lat: float = 52.364431  # Almere Centrum
    lng: float = 5.222011
    radius: int = 500  # unit unknown, value kept from the original script
    http_timeout: float = 20.0
    # Movement detection
    min_distance_m: float = 200.0
    require_range_change: bool = True
    # Extras
    store_snapshots: bool = False
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict | None = None, dotenv_path: str | Path | None = ".env") -> Config:
        """Build a Config from ``env`` (defaults to os.environ, after loading .env if present)."""
        if env is None:
            if dotenv_path and Path(dotenv_path).is_file():
                from dotenv import load_dotenv

                load_dotenv(dotenv_path, override=False)
            env = dict(os.environ)
        d = cls()
        return cls(
            db_host=_get(env, "GOPOLL_DB_HOST", d.db_host),
            db_port=_int(env, "GOPOLL_DB_PORT", d.db_port),
            db_user=_get(env, "GOPOLL_DB_USER", d.db_user),
            db_password=_get(env, "GOPOLL_DB_PASSWORD", d.db_password),
            db_name=_get(env, "GOPOLL_DB_NAME", d.db_name),
            api_url=_get(env, "GOPOLL_API_URL", d.api_url),
            lat=_float(env, "GOPOLL_LAT", d.lat),
            lng=_float(env, "GOPOLL_LNG", d.lng),
            radius=_int(env, "GOPOLL_RADIUS", d.radius),
            http_timeout=_float(env, "GOPOLL_HTTP_TIMEOUT", d.http_timeout),
            min_distance_m=_float(env, "GOPOLL_MIN_DISTANCE_M", d.min_distance_m),
            require_range_change=_bool(env, "GOPOLL_REQUIRE_RANGE_CHANGE", d.require_range_change),
            store_snapshots=_bool(env, "GOPOLL_STORE_SNAPSHOTS", d.store_snapshots),
            log_level=_get(env, "GOPOLL_LOG_LEVEL", d.log_level).upper(),
        )
