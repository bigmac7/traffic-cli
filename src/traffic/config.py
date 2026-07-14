import json
from pathlib import Path
import logging
import routingpy

logger = logging.getLogger(__name__)
CONFIG_DIR = Path.home() / ".traffic"


class Config:
    def __init__(self) -> None:
        self.config_file = CONFIG_DIR / "config.json"
        self.config = self._load_config()

        if self.config:
            self.provider_name = self.config.get("provider_name")
            self.api_key = self.config.get("api_key")
            self.profile = self.config.get("profile", "car")

            try:
                self.router_class = self._get_router_class(self.provider_name)
            except AttributeError:
                raise ValueError(
                    f"Provider {self.provider_name} is not part of the supported list."
                )
        else:
            logger.warning("Config has not been initialised - init script must be ran")
            self.provider_name = None
            self.api_key = None
            self.profile = None
            self.router_class = None

    def _get_router_class(self, provider_name):
        if not provider_name:
            return None
        name_lower = provider_name.lower()
        if name_lower == "mapbox":
            target = "mapboxosrm"
        elif name_lower == "google_maps":
            target = "google"
        else:
            target = name_lower
        class_name = next(
            (attr for attr in dir(routingpy) if attr.lower() == target),
            provider_name
        )
        return getattr(routingpy, class_name)

    def _load_config(self):
        """Safely loads the config file if it exists."""
        if self.config_file.exists():
            with open(self.config_file, "r") as f:
                return json.load(f)
        return {}

    def initialise(self, provider_name, api_key, profile):
        """Creates the initial config.json from CLI arguments."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.config = {
            "provider_name": provider_name,
            "api_key": api_key,
            "profile": profile,
            "vars": {},
        }

        self.provider_name = provider_name
        self.api_key = api_key
        self.profile = profile
        self.router_class = self._get_router_class(self.provider_name)

        self.save()
        logger.info("Config created successfully")

    def save(self):
        """Writes the current state back to the disk."""
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=4)

    def add_var_to_config(self, key: str, value: str):
        if not self.config:
            raise ValueError("Config not initialized. Run `init` first.")

        self.config["vars"][key] = value
        self.save()
        logger.info("Added variable %s to config with value %s", key, value)

    def set_default_profile(self, profile: str):
        if not self.config:
            raise ValueError("Config not initialized. Run `init` first.")

        self.config["profile"] = profile
        self.save()
        logger.info("Changed default profile to %s", profile)
