import json
from pathlib import Path
import logging
import routingpy

from traffic.providers import resolve_provider, supported_providers

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
            self.country = self.config.get("country") or self.config.get("country_code")

            self.router_class = self._get_router_class(self.provider_name)
        else:
            logger.warning("Config has not been initialised - init script must be ran")
            self.provider_name = None
            self.api_key = None
            self.profile = None
            self.country = None
            self.router_class = None

    def _get_router_class(self, provider_name):
        if not provider_name:
            return None
        _, info = resolve_provider(provider_name)
        if not info:
            supported = ", ".join(supported_providers())
            raise ValueError(
                f"Provider '{provider_name}' is not supported. "
                f"Supported providers: {supported}."
            )
        return getattr(routingpy, info["class_name"])

    def _load_config(self):
        """Safely loads the config file if it exists."""
        if self.config_file.exists():
            with open(self.config_file, "r") as f:
                return json.load(f)
        return {}

    def initialise(self, provider_name, api_key, profile):
        """Creates the initial config.json from CLI arguments.

        Validates the provider (and profile) up front so an unsupported choice
        fails at `traffic init` time rather than later when routing runs.
        """
        _, info = resolve_provider(provider_name)
        if not info:
            supported = ", ".join(supported_providers())
            raise ValueError(
                f"Provider '{provider_name}' is not supported. "
                f"Supported providers: {supported}."
            )
        if profile not in info["profiles"]:
            valid = ", ".join(sorted(info["profiles"]))
            raise ValueError(
                f"Profile '{profile}' is not supported for provider '{provider_name}'. "
                f"Valid profiles are: {valid}."
            )

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
        self.country = None
        self.router_class = self._get_router_class(self.provider_name)

        self.save()
        logger.info("Config created successfully")

    def save(self):
        """Writes the current state back to the disk."""
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=4)

    def set_config_value(self, key: str, value: str):
        """Sets a configuration variable or system setting."""
        if not self.config:
            raise ValueError("Config not initialized. Run `init` first.")

        norm_key = key.lower()
        if norm_key in ("profile", "default_profile"):
            self.config["profile"] = value
            self.profile = value
            logger.info("Changed default profile to %s", value)
        elif norm_key in ("country", "country_code", "cc"):
            val = value.lower().strip()
            if val == "uk":
                val = "gb"
            self.config["country"] = val
            self.country = val
            logger.info("Changed default country to %s", val)
        elif norm_key == "api_key":
            self.config["api_key"] = value
            self.api_key = value
        elif norm_key == "provider_name":
            self.config["provider_name"] = value
            self.provider_name = value
            self.router_class = self._get_router_class(value)
        else:
            if "vars" not in self.config:
                self.config["vars"] = {}
            self.config["vars"][key] = value
            logger.info("Added variable %s to config with value %s", key, value)

        self.save()

    def add_var_to_config(self, key: str, value: str):
        self.set_config_value(key, value)

    def set_default_profile(self, profile: str):
        self.set_config_value("profile", profile)
