"""Which ride-share services to poll, and how.

``GOPOLL_PROVIDERS`` is a comma-separated list of preset names (see ``PRESETS``) and/or
custom GBFS feeds written as ``name=https://.../gbfs.json``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GO_SHARING = "go_sharing"

_NAME = re.compile(r"^[a-z0-9_]{1,32}$")


@dataclass(frozen=True)
class ProviderSpec:
    name: str  # stored in the `provider` column
    kind: str  # "gourban" (GO Sharing's own API) or "gbfs"
    url: str = ""  # GBFS auto-discovery URL; unused for gourban (GOPOLL_API_URL applies)
    label: str = ""

    @property
    def is_gbfs(self) -> bool:
        return self.kind == "gbfs"


def _gbfs(name: str, label: str, url: str) -> ProviderSpec:
    return ProviderSpec(name, "gbfs", url, label)


_FELYX_CITIES = {
    "amsterdam": "Amsterdam",
    "arnhem": "Arnhem",
    "breda": "Breda",
    "delft": "Delft",
    "den_bosch": "Den Bosch",
    "eindhoven": "Eindhoven",
    "enschede": "Enschede",
    "groningen": "Groningen",
    "haarlem": "Haarlem",
    "nijmegen": "Nijmegen",
    "rotterdam": "Rotterdam",
    "the_hague": "The Hague",
    "tilburg": "Tilburg",
    "zwolle": "Zwolle",
}
_DOTT_CITIES = {"eindhoven": "Eindhoven", "groningen": "Groningen", "utrecht": "Utrecht", "veldhoven": "Veldhoven"}

# Feed URLs from the MobilityData GBFS systems catalogue
# (https://github.com/MobilityData/gbfs/blob/master/systems.csv), September 2026.
PRESETS: dict[str, ProviderSpec] = {
    GO_SHARING: ProviderSpec(GO_SHARING, "gourban", label="GO Sharing (goUrban API, has license plates)"),
    "check_almere": _gbfs("check_almere", "Check, Almere", "https://api.ridecheck.app/gbfs/v3/almere/gbfs.json"),
    **{
        f"felyx_{city}": _gbfs(
            f"felyx_{city}", f"Felyx, {label}", f"https://maas.zeus.cooltra.com/gbfs/{city}/3.0/en/gbfs.json"
        )
        for city, label in _FELYX_CITIES.items()
    },
    **{
        f"dott_{city}": _gbfs(
            f"dott_{city}", f"Dott, {label}", f"https://gbfs.api.ridedott.com/public/v2/{city}/gbfs.json"
        )
        for city, label in _DOTT_CITIES.items()
    },
}


def parse_providers(value: str) -> tuple[ProviderSpec, ...]:
    """Parse a GOPOLL_PROVIDERS value. Raises ValueError with a readable message."""
    specs: list[ProviderSpec] = []
    for raw in (part.strip() for part in value.split(",")):
        if not raw:
            continue
        if "=" in raw:
            name, url = (s.strip() for s in raw.split("=", 1))
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"custom provider {name!r}: URL must start with http(s)://")
            if name in PRESETS:
                raise ValueError(f"custom provider name {name!r} clashes with a preset")
            spec = _gbfs(name, f"Custom GBFS ({url})", url)
        else:
            name = raw
            if name not in PRESETS:
                raise ValueError(f"unknown provider {name!r} (see `gotracker providers`, or use name=URL)")
            spec = PRESETS[name]
        if not _NAME.match(name):
            raise ValueError(f"provider name {name!r} must be 1-32 chars of a-z, 0-9, _")
        if any(s.name == name for s in specs):
            raise ValueError(f"provider {name!r} listed twice")
        specs.append(spec)
    if not specs:
        raise ValueError("no providers configured")
    return tuple(specs)
