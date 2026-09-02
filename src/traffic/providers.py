"""
Authoritative registry of supported routing providers.

This is the single source of truth for which providers `traffic` supports.
Both `config.py` (for resolving the `routingpy` client class) and `geo.py`
(for resolving the travel profile) read from here, so a provider accepted by
`traffic init` is guaranteed to be usable by `Router`.

Each entry maps a canonical key to:
  - ``class_name``: the ``routingpy`` client class to instantiate.
  - ``aliases``: alternative names accepted from the user (case-insensitive).
  - ``profiles``: generic profile name -> provider-specific profile string.
"""

PROVIDERS: dict = {
    "ors": {
        "class_name": "ORS",
        "aliases": ("openrouteservice",),
        "profiles": {"bike": "cycling-regular", "car": "driving-car", "walk": "foot-walking"},
    },
    "graphhopper": {
        "class_name": "Graphhopper",
        "aliases": (),
        "profiles": {"bike": "bike", "car": "car", "walk": "foot"},
    },
    "mapbox": {
        "class_name": "MapboxOSRM",
        "aliases": ("mapboxosrm",),
        "profiles": {"bike": "cycling", "car": "driving", "walk": "walking"},
    },
    "google_maps": {
        "class_name": "Google",
        "aliases": ("google", "googlemaps"),
        "profiles": {"bike": "bicycling", "car": "driving", "walk": "walking"},
    },
}


def resolve_provider(name):
    """Resolve a user-supplied provider name to its ``(key, info)`` entry.

    Matches against the canonical key, the ``routingpy`` class name, and any
    registered aliases (all case-insensitive). Returns ``(None, None)`` if the
    name is unknown.
    """
    if not name:
        return None, None
    n = name.lower().strip()
    for key, info in PROVIDERS.items():
        if n == key or n == info["class_name"].lower() or n in info["aliases"]:
            return key, info
    return None, None


def supported_providers():
    """Return the sorted list of canonical provider names, for error messages."""
    return sorted(PROVIDERS)
