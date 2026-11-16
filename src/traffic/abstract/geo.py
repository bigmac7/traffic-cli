"""
Get all of the geometric info, such as postcode  -> lat/long, etc
"""

import json
import os
import re
import time
from pathlib import Path

from geopy.exc import GeocoderQuotaExceeded, GeocoderRateLimited
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.location import Location
from traffic.config import Config
from traffic.providers import avoid_kwargs, resolve_provider


class TrafficError(ValueError):
    """An error whose machine-readable ``kind`` is known where it is raised."""

    def __init__(self, message, kind):
        super().__init__(message)
        self.kind = kind


# Nominatim's usage policy requires a descriptive user agent (app + contact)
# and limits anonymous use to ~1 request/second. We honour both below.
geocoder = Nominatim(user_agent="traffic-cli (+https://github.com/bigmac7/traffic-cli)")

# Rate-limit outbound geocode calls to stay within Nominatim's ~1 req/sec policy.
_rate_limited_geocode = RateLimiter(geocoder.geocode, min_delay_seconds=1.0)

# Cache results for the lifetime of a single CLI invocation so the heuristic
# route-splitting in the CLI and the endpoint lookups in Router don't re-query
# the same string. Keyed by (normalised query, country_codes).
_geocode_cache: dict = {}

# Hits are also persisted across invocations (misses are not), so periodic
# callers like a Waybar module don't repeat the same Nominatim lookups.
CACHE_FILE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "traffic-cli" / "geocode.json"
CACHE_TTL_SECONDS = 30 * 86400
use_disk_cache = True  # turned off by `--no-cache`
_disk_cache = None


def _load_disk_cache():
    global _disk_cache
    if _disk_cache is None:
        try:
            _disk_cache = json.loads(CACHE_FILE.read_text())
        except (OSError, ValueError):
            _disk_cache = {}
    return _disk_cache


def _save_disk_cache(cache):
    now = time.time()
    fresh = {k: v for k, v in cache.items() if now - v["ts"] < CACHE_TTL_SECONDS}
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(fresh))
        os.replace(tmp, CACHE_FILE)  # atomic, so a concurrent reader never sees half a file
    except OSError:
        pass  # a cache that can't be written is just a slower run


def geocode(query, country_codes=None):
    """Geocode a query with caching and Nominatim rate limiting.

    Returns the geopy ``Location`` (or ``None`` if not found). Results are
    cached per invocation (including misses) and, unless ``use_disk_cache``
    is off, hits are cached on disk for ``CACHE_TTL_SECONDS``.
    """
    if not query:
        return None
    key = (query.strip().lower(), country_codes)
    if key in _geocode_cache:
        return _geocode_cache[key]

    disk_key = f"{country_codes or ''}|{key[0]}"
    if use_disk_cache:
        hit = _load_disk_cache().get(disk_key)
        if hit and time.time() - hit["ts"] < CACHE_TTL_SECONDS:
            location = Location(hit["address"], (hit["lat"], hit["lon"]), {"importance": hit["importance"]})
            _geocode_cache[key] = location
            return location

    if country_codes:
        location = _rate_limited_geocode(query, country_codes=country_codes)
    else:
        location = _rate_limited_geocode(query)
    _geocode_cache[key] = location

    if location and use_disk_cache:
        cache = _load_disk_cache()
        cache[disk_key] = {
            "address": location.address,
            "lat": location.latitude,
            "lon": location.longitude,
            "importance": (location.raw or {}).get("importance", 0.5),
            "ts": time.time(),
        }
        _save_disk_cache(cache)
    return location


_COORDS_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_coords(value):
    """Return ``(lat, lon)`` if ``value`` is a ``lat,lon`` pair in decimal degrees, else ``None``."""
    m = _COORDS_RE.match(value or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


# Informal names / abbreviations that we resolve to an ISO 3166-1 alpha-2 code
# directly, so common cases (and the UK's constituent countries, which share
# the "gb" code) don't need a network lookup.
_COUNTRY_ALIASES = {
    "uk": "gb", "u.k.": "gb", "gb": "gb", "britain": "gb",
    "great britain": "gb", "united kingdom": "gb",
    "england": "gb", "scotland": "gb", "wales": "gb",
    "northern ireland": "gb", "n ireland": "gb",
    "usa": "us", "u.s.": "us", "u.s.a.": "us", "america": "us",
    "united states": "us", "united states of america": "us",
}

_country_code_cache: dict = {}


def normalize_country(value):
    """Resolve a user-supplied country to an ISO 3166-1 alpha-2 code.

    Accepts an ISO code (``gb``), a common alias (``uk``, ``england``), or a
    full country name (``france``), which is resolved via Nominatim. Returns
    the lowercase 2-letter code, or ``None`` if it can't be interpreted (so the
    caller can warn rather than silently search the whole planet).
    """
    if not value:
        return None
    key = value.strip().lower()
    if not key:
        return None
    if key in _country_code_cache:
        return _country_code_cache[key]

    disk_key = f"country|{key}"
    hit = _load_disk_cache().get(disk_key) if use_disk_cache else None
    if key in _COUNTRY_ALIASES:
        code = _COUNTRY_ALIASES[key]
    elif len(key) == 2 and key.isalpha():
        code = key
    elif hit and time.time() - hit["ts"] < CACHE_TTL_SECONDS:
        code = hit["code"]
    else:
        # Full country name: ask Nominatim for its country code.
        code = None
        try:
            location = _rate_limited_geocode(value, addressdetails=True)
            if location:
                code = (location.raw.get("address", {}) or {}).get("country_code")
        except Exception:
            code = None
        if code and use_disk_cache:
            cache = _load_disk_cache()
            cache[disk_key] = {"code": code, "ts": time.time()}
            _save_disk_cache(cache)

    _country_code_cache[key] = code
    return code


# GraphHopper instruction signs marking the end of a leg.
_GH_VIA_REACHED = 5
_GH_FINISH = 4


def extract_leg_durations(raw, leg_count):
    """Pulls per-leg durations (seconds) out of a provider's raw directions response.

    Handles ORS (geojson and json), Mapbox/OSRM, Google and GraphHopper shapes.
    Returns ``None`` if the response doesn't carry a breakdown with exactly
    ``leg_count`` legs.
    """
    if not isinstance(raw, dict):
        return None
    legs = None
    try:
        if raw.get("features"):  # ORS geojson
            legs = [seg["duration"] for seg in raw["features"][0]["properties"]["segments"]]
        elif raw.get("paths"):  # GraphHopper
            legs, current = [], 0.0
            for instruction in raw["paths"][0]["instructions"]:
                current += instruction["time"] / 1000
                if instruction["sign"] in (_GH_VIA_REACHED, _GH_FINISH):
                    legs.append(current)
                    current = 0.0
        elif raw.get("routes"):
            route = raw["routes"][0]
            if "segments" in route:  # ORS json
                legs = [seg["duration"] for seg in route["segments"]]
            elif "legs" in route:  # Mapbox/OSRM, Google
                legs = [
                    leg["duration"]["value"] if isinstance(leg["duration"], dict) else leg["duration"]
                    for leg in route["legs"]
                ]
    except (KeyError, IndexError, TypeError):
        return None
    if legs is None or len(legs) != leg_count:
        return None
    return [float(d) for d in legs]


class Router:
    def __init__(self, config: Config, traffic: bool = True, avoid_motorways: bool = False, avoid_tolls: bool = False):
        self.config = config
        provider_name = config.provider_name
        profile = config.profile
        if not provider_name:
            raise TrafficError("Provider name not set in config.", "config")

        self.provider, provider_info = resolve_provider(provider_name)
        if not provider_info:
            raise TrafficError(f"Provider '{provider_name}' is not supported.", "config")

        profiles = provider_info["profiles"]
        if profile not in profiles:
            valid = ", ".join(sorted(profiles))
            raise TrafficError(
                f"Profile '{profile}' is not supported for provider '{provider_name}'. "
                f"Valid profiles are: {valid}. Set one with `traffic set profile <profile>`.",
                "config",
            )
        self.profile = profiles[profile]
        # Live traffic only applies to driving.
        self.traffic = provider_info["traffic"] if traffic and profile == "car" else None
        # Motorways and tolls only matter when driving (ORS rejects them for other profiles).
        self.avoid = avoid_kwargs(self.provider, avoid_motorways, avoid_tolls) if profile == "car" else {}
        self.routing_client = config.router_class(api_key=config.api_key)

    def resolve_var(self, *vars):
        """Checks if inputs are stored in config, replaces them, and returns them all."""

        resolved = [self.config.config.get("vars", {}).get(var, self.config.config.get(var, var)) for var in vars]

        if not resolved:
            return None

        if len(resolved) == 1:
            return resolved[0]

        return tuple(resolved)

    def _geocode_location(self, query: str, country_code: str = None):
        """Geocodes a query string, applying country bias if configured.

        A ``lat,lon`` query is returned as-is without a geocoder call.
        """
        coords = parse_coords(query)
        if coords:
            return Location(query.strip(), coords, {})

        country = country_code or getattr(self.config, "country", None) or (self.config.config.get("country") if self.config.config else None)
        cc = normalize_country(country)
        if cc:
            try:
                location = geocode(query, country_codes=cc)
                if location:
                    return location
            except Exception:
                pass

        try:
            location = geocode(query)
        except Exception as e:
            kind = "rate_limit" if isinstance(e, (GeocoderRateLimited, GeocoderQuotaExceeded)) else "network"
            raise TrafficError(f"Geocoding service error while searching for '{query}': {e}", kind) from e

        if not location:
            raise TrafficError(f"Coordinates for '{query}' could not be found.", "geocode")
        return location

    def get_travel_time(self, home: str, destination: str, country_code: str = None):
        return self.get_route_time([home, destination], country_code=country_code)

    def get_route_time(self, stops, country_code: str = None):
        """Return the total travel time in seconds, visiting ``stops`` in order.

        Also sets ``last_leg_durations`` (empty if the response had no
        per-leg breakdown), ``traffic_aware`` and
        ``free_flow_duration`` (``None`` unless the provider reported a
        duration without traffic alongside it).
        """
        if len(stops) < 2:
            raise TrafficError("A route needs at least an origin and a destination.", "usage")
        resolved = [self.resolve_var(stop) for stop in stops]
        locations = [self._geocode_location(q, country_code=country_code) for q in resolved]

        self.last_locations = locations
        self.last_home_location = locations[0]
        self.last_destination_location = locations[-1]

        coords = [[loc.longitude, loc.latitude] for loc in locations]
        kwargs = {"profile": self.profile, **self.avoid}
        traffic = self.traffic or {}
        if "profile" in traffic:
            kwargs["profile"] = traffic["profile"]
        if traffic.get("departure_time"):
            kwargs["departure_time"] = int(time.time())

        route = self.routing_client.directions(locations=coords, **kwargs)
        self.traffic_aware = "profile" in traffic
        self.free_flow_duration = None
        duration = route.duration
        legs = extract_leg_durations(getattr(route, "raw", None), len(coords) - 1)

        if traffic.get("departure_time"):
            # routingpy sums leg["duration"] (no traffic); Google puts the
            # traffic-aware figure in leg["duration_in_traffic"], and omits it
            # when the route has intermediate stops.
            raw_legs = route.raw["routes"][0]["legs"]
            if raw_legs and all("duration_in_traffic" in leg for leg in raw_legs):
                self.traffic_aware = True
                self.free_flow_duration = duration
                legs = [float(leg["duration_in_traffic"]["value"]) for leg in raw_legs]
                duration = sum(legs)

        if len(coords) == 2:
            legs = [float(duration)]
        # Every provider returns legs; re-routing each leg would multiply the cost.
        self.last_leg_durations = legs or []
        return duration
