"""
Get all of the geometric info, such as postcode  -> lat/long, etc
"""

from geopy.geocoders import Nominatim
import routingpy
from typing import Literal, List
from traffic.config import Config

geocoder = Nominatim(user_agent="traffic")


provider_map: dict = {
    "ors": {
        "class_name": "ORS",
        "profiles": {"bike": "cycling-regular", "car": "driving-car", "walk": "foot-walking"},
    },
    "graphhopper": {
        "class_name": "Graphhopper",
        "profiles": {"bike": "bike", "car": "car", "walk": "foot"},
    },
    "mapbox": {
        "class_name": "MapboxOSRM",
        "profiles": {"bike": "cycling", "car": "driving", "walk": "walking"},
    },
    "google_maps": {
        "class_name": "Google",
        "profiles": {"bike": "bicycling", "car": "driving", "walk": "walking"},
    },
    "tomtom": {
        "class_name": "TomTom",
        "profiles": {
            "bike": "bicycle",
            "car": "car",
            "walk": "pedestrian",
        },
    },
}


class Router:
    def __init__(self, config: Config):
        self.config = config
        provider_name = config.provider_name
        profile = config.profile
        if not provider_name:
            raise ValueError("Provider name not set in config.")
        
        provider_info = next(
            (v for k, v in provider_map.items() if k.lower() == provider_name.lower() or v.get("class_name", "").lower() == provider_name.lower()),
            None
        )
        if not provider_info:
            raise ValueError(f"Provider '{provider_name}' is not supported.")

        self.profile = provider_info["profiles"][profile]
        self.routing_client = config.router_class(api_key=config.api_key)

    def resolve_var(self, *vars):
        """Checks if inputs are stored in config, replaces them, and returns them all."""

        resolved = [self.config.config.get("vars", {}).get(var, self.config.config.get(var, var)) for var in vars]

        if not resolved:
            return None

        if len(resolved) == 1:
            return resolved[0]

        return tuple(resolved)

    def _get_coords_from_query(self, query: str):
        location = geocoder.geocode(query)  # see geopy examples
        if not location:
            raise ValueError(f"Co-ordinates for {query}")
        return [location.longitude, location.latitude]

    def get_travel_time(self, home: str, destination: str):
        home, destination = self.resolve_var(home, destination)
        home_coords = self._get_coords_from_query(home)
        destination_coords = self._get_coords_from_query(destination)
        route = self.routing_client.directions(
            locations=[home_coords, destination_coords], profile=self.profile
        )
        return route.duration
