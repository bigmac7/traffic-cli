"""
Get all of the geometric info, such as postcode  -> lat/long, etc
"""

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from traffic.config import Config
from traffic.providers import resolve_provider

# Nominatim's usage policy requires a descriptive user agent (app + contact)
# and limits anonymous use to ~1 request/second. We honour both below.
geocoder = Nominatim(user_agent="traffic-cli (+https://github.com/bigmac7/traffic-cli)")

# Rate-limit outbound geocode calls to stay within Nominatim's ~1 req/sec policy.
_rate_limited_geocode = RateLimiter(geocoder.geocode, min_delay_seconds=1.0)

# Cache results for the lifetime of a single CLI invocation so the heuristic
# route-splitting in the CLI and the endpoint lookups in Router don't re-query
# the same string. Keyed by (normalised query, country_codes).
_geocode_cache: dict = {}


def geocode(query, country_codes=None):
    """Geocode a query with in-process caching and Nominatim rate limiting.

    Returns the geopy ``Location`` (or ``None`` if not found). Results,
    including misses, are cached per invocation to avoid redundant requests.
    """
    if not query:
        return None
    key = (query.strip().lower(), country_codes)
    if key in _geocode_cache:
        return _geocode_cache[key]
    if country_codes:
        location = _rate_limited_geocode(query, country_codes=country_codes)
    else:
        location = _rate_limited_geocode(query)
    _geocode_cache[key] = location
    return location


class Router:
    def __init__(self, config: Config):
        self.config = config
        provider_name = config.provider_name
        profile = config.profile
        if not provider_name:
            raise ValueError("Provider name not set in config.")
        
        _, provider_info = resolve_provider(provider_name)
        if not provider_info:
            raise ValueError(f"Provider '{provider_name}' is not supported.")

        profiles = provider_info["profiles"]
        if profile not in profiles:
            valid = ", ".join(sorted(profiles))
            raise ValueError(
                f"Profile '{profile}' is not supported for provider '{provider_name}'. "
                f"Valid profiles are: {valid}. Set one with `traffic set profile <profile>`."
            )
        self.profile = profiles[profile]
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
        """Geocodes a query string, applying country bias if configured."""
        country = country_code or getattr(self.config, "country", None) or (self.config.config.get("country") if self.config.config else None)
        if country:
            cc = country.lower().strip()
            if cc == "uk":
                cc = "gb"
            try:
                location = geocode(query, country_codes=cc)
                if location:
                    return location
            except Exception:
                pass

        try:
            location = geocode(query)
        except Exception as e:
            raise ValueError(f"Geocoding service error while searching for '{query}': {e}")

        if not location:
            raise ValueError(f"Coordinates for '{query}' could not be found.")
        return location

    def get_travel_time(self, home: str, destination: str, country_code: str = None):
        home, destination = self.resolve_var(home, destination)
        home_loc = self._geocode_location(home, country_code=country_code)
        destination_loc = self._geocode_location(destination, country_code=country_code)

        self.last_home_location = home_loc
        self.last_destination_location = destination_loc

        home_coords = [home_loc.longitude, home_loc.latitude]
        destination_coords = [destination_loc.longitude, destination_loc.latitude]
        route = self.routing_client.directions(
            locations=[home_coords, destination_coords], profile=self.profile
        )
        return route.duration
