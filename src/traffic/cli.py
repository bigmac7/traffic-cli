import json
import re
import click
from traffic.abstract.geo import Router, geocode
from traffic.config import Config


def get_initialized_config(headless: bool = False):
    """Gets the configuration, automatically prompting for initialization if missing (unless headless)."""
    config = Config()
    if not config.provider_name:
        if headless:
            click.echo(
                "Error: Configuration not found or not initialized. Run `traffic init` first.",
                err=True,
            )
            raise SystemExit(1)
        click.echo("Configuration not found or not initialized.")
        provider_name = click.prompt(
            "Please enter provider name (e.g. ORS, Graphhopper)"
        )
        api_key = click.prompt("Please enter API key")
        profile = click.prompt("Please enter default profile", default="car")
        try:
            config.initialise(provider_name, api_key, profile)
        except ValueError as e:
            raise click.ClickException(str(e))
        click.echo(f"Configuration initialised with provider: {provider_name}\n")
    return config


def format_duration(seconds: float) -> str:
    """Formats a duration in seconds into a readable string of days, hours, mins, seconds."""

    sec = int(seconds)
    days, sec = divmod(sec, 86400)
    hours, sec = divmod(sec, 3600)
    mins, sec = divmod(sec, 60)

    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if mins > 0:
        parts.append(f"{mins} min{'s' if mins != 1 else ''}")
    if sec > 0 or not parts:
        parts.append(f"{sec} second{'s' if sec != 1 else ''}")

    return ", ".join(parts)


def format_duration_compact(seconds: float) -> str:
    """Formats a duration in seconds into a compact string like '1d 2h 15m' or '45m'."""
    sec = int(seconds)
    days, sec = divmod(sec, 86400)
    hours, sec = divmod(sec, 3600)
    mins, sec = divmod(sec, 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if mins > 0:
        parts.append(f"{mins}m")
    if not parts or (days == 0 and hours == 0 and mins == 0):
        parts.append(f"{sec}s")

    return " ".join(parts)


def format_error_message(exc: Exception) -> str:
    """
    Extracts a clean, human-readable error message from exceptions,
    parsing JSON payloads from routing APIs and filtering out raw JSON/metadata.
    """
    status = getattr(exc, "status", None)
    raw_msg = getattr(exc, "message", str(exc))

    parsed_json = None

    if isinstance(raw_msg, str):
        json_match = re.search(r"(\{.*\})", raw_msg, re.DOTALL)
        if json_match:
            candidate = json_match.group(1)
            try:
                parsed_json = json.loads(candidate)
            except Exception:
                try:
                    import ast
                    parsed_json = ast.literal_eval(candidate)
                except Exception:
                    pass
    elif isinstance(raw_msg, dict):
        parsed_json = raw_msg

    extracted_msg = None
    if isinstance(parsed_json, dict):
        # 1. ORS / OpenRouteService or generic error object
        err_field = parsed_json.get("error")
        if isinstance(err_field, dict):
            extracted_msg = (
                err_field.get("message")
                or err_field.get("detail")
                or err_field.get("description")
            )
        elif isinstance(err_field, str):
            extracted_msg = err_field

        # 2. GraphHopper / Mapbox standard 'message'
        if not extracted_msg and "message" in parsed_json:
            extracted_msg = str(parsed_json["message"])

        # 3. Google Maps 'error_message'
        if not extracted_msg and "error_message" in parsed_json:
            extracted_msg = str(parsed_json["error_message"])

        # 4. TomTom 'detailedError'
        if not extracted_msg and isinstance(parsed_json.get("detailedError"), dict):
            extracted_msg = parsed_json["detailedError"].get("message")

        # 5. TomTom 'errorText'
        if not extracted_msg and "errorText" in parsed_json:
            extracted_msg = str(parsed_json["errorText"])

        # 6. GraphHopper 'hints'
        if not extracted_msg and isinstance(parsed_json.get("hints"), list) and parsed_json["hints"]:
            first_hint = parsed_json["hints"][0]
            if isinstance(first_hint, dict):
                extracted_msg = first_hint.get("message")
            elif isinstance(first_hint, str):
                extracted_msg = first_hint

    # Fallback to string representation if no JSON field extracted
    if not extracted_msg:
        extracted_msg = str(exc)
        clean_match = re.match(r"^\d{3}\s*\((.*)\)$", extracted_msg, re.DOTALL)
        if clean_match:
            extracted_msg = clean_match.group(1).strip()

    user_msg = extracted_msg.strip()

    # Provide actionable context for common failure modes
    lower_msg = user_msg.lower()
    if (
        status in (401, 403)
        or "unauthorized" in lower_msg
        or "invalid token" in lower_msg
        or "invalid api key" in lower_msg
        or "not authorized" in lower_msg
    ):
        return f"{user_msg} (Check your API key using `traffic set api_key <key>`)"

    if (
        status == 404
        or "could not find point" in lower_msg
        or "cannot find point" in lower_msg
        or "within a radius" in lower_msg
        or "noroute" in lower_msg
        or "no route" in lower_msg
    ):
        return f"{user_msg} (No drivable route found between these locations for the selected travel profile)."

    if (
        status == 429
        or "rate limit" in lower_msg
        or "quota" in lower_msg
        or "over query limit" in lower_msg
    ):
        return f"{user_msg} (Rate limit exceeded. Please wait a moment before trying again)."

    return user_msg


def resolve_locations(locations, home_opt=None, dest_opt=None, config=None, country_code=None):
    """
    Resolves the origin (home) and destination from CLI options and positional arguments.
    Supports delimiters ('to', '->'), config variables, country biasing, and heuristic multi-word splitting.
    Returns a tuple: (origin, destination, info_message, error_message).
    """
    vars_dict = config.config.get("vars", {}) if config and config.config else {}
    cc = country_code or getattr(config, "country", None) or (config.config.get("country") if config and config.config else None)
    if cc:
        cc = cc.lower().strip()
        if cc == "uk":
            cc = "gb"

    # Case 1: Both options provided explicitly
    if home_opt and dest_opt:
        return home_opt, dest_opt, None, None

    # Case 2: One option provided explicitly, positional args provide the other
    if home_opt and locations:
        return home_opt, " ".join(locations), None, None
    if dest_opt and locations:
        return " ".join(locations), dest_opt, None, None

    # Case 3: No positional locations provided
    if not locations:
        err = (
            "Error: Missing origin and destination.\n\n"
            "Usage:\n"
            "  traffic <origin> <destination>\n"
            "  traffic <origin> to <destination>\n\n"
            "Examples:\n"
            "  traffic california nevada\n"
            '  traffic "las vegas" california\n'
            "  traffic las vegas to california\n"
            "  traffic home work"
        )
        return None, None, None, err

    # Case 4: Single positional string passed (e.g. 'las vegas to california')
    if len(locations) == 1:
        text = locations[0].strip()
        to_split = re.split(r"\s+to\s+", text, maxsplit=1, flags=re.IGNORECASE)
        if len(to_split) == 2 and to_split[0].strip() and to_split[1].strip():
            return to_split[0].strip(), to_split[1].strip(), None, None

        if "->" in text:
            parts = text.split("->", 1)
            if parts[0].strip() and parts[1].strip():
                return parts[0].strip(), parts[1].strip(), None, None

        if "," in text:
            parts = text.split(",", 1)
            if parts[0].strip() and parts[1].strip():
                return parts[0].strip(), parts[1].strip(), None, None

        err = (
            f"Error: Could not determine both origin and destination from '{text}'.\n\n"
            "Tip: Separate locations with spaces or use 'to', for example:\n"
            f'  traffic "{text}" <destination>\n'
            f"  traffic {text} to <destination>"
        )
        return None, None, None, err

    # Case 5: Exactly 2 positional arguments
    if len(locations) == 2:
        return locations[0], locations[1], None, None

    # Case 6: 3 or more positional arguments
    # Check for keyword delimiter 'to' or '->'
    lower_tokens = [t.lower() for t in locations]
    if "to" in lower_tokens:
        idx = lower_tokens.index("to")
        if 0 < idx < len(locations) - 1:
            h = " ".join(locations[:idx])
            d = " ".join(locations[idx + 1:])
            return h, d, None, None

    if "->" in locations:
        idx = locations.index("->")
        if 0 < idx < len(locations) - 1:
            h = " ".join(locations[:idx])
            d = " ".join(locations[idx + 1:])
            return h, d, None, None

    # Check for saved variable boundaries in config (e.g. 'home las vegas')
    if locations[0] in vars_dict:
        return locations[0], " ".join(locations[1:]), None, None
    if locations[-1] in vars_dict:
        return " ".join(locations[:-1]), locations[-1], None, None

    # Heuristic split testing using geocoding
    best_split = None
    best_score = -1.0

    for i in range(1, len(locations)):
        cand_h = " ".join(locations[:i])
        cand_d = " ".join(locations[i:])
        try:
            loc_h = None
            loc_d = None
            if cc:
                try:
                    loc_h = geocode(cand_h, country_codes=cc)
                    loc_d = geocode(cand_d, country_codes=cc)
                except Exception:
                    pass
            if not loc_h:
                loc_h = geocode(cand_h)
            if not loc_d:
                loc_d = geocode(cand_d)

            if loc_h and loc_d:
                imp_h = getattr(loc_h, "raw", {}).get("importance", 0.5)
                imp_d = getattr(loc_d, "raw", {}).get("importance", 0.5)
                score = imp_h + imp_d
                if score > best_score:
                    best_score = score
                    best_split = (cand_h, cand_d)
        except Exception:
            pass

    if best_split:
        h, d = best_split
        info = (
            f"Interpreting route as: '{h}' -> '{d}'\n"
            f"Tip: You can wrap multi-word locations in quotes (e.g. traffic \"{h}\" \"{d}\") or use 'to' (e.g. traffic {h} to {d}).\n"
        )
        return h, d, info, None

    raw_query = " ".join(locations)
    err = (
        f"Error: Could not determine origin and destination from '{raw_query}'.\n\n"
        "Tip: Wrap locations containing spaces in quotes, e.g.:\n"
        f'  traffic "{locations[0]} {locations[1]}" "{" ".join(locations[2:])}"\n'
        "Or use 'to' as a separator:\n"
        f"  traffic {' '.join(locations[:2])} to {' '.join(locations[2:])}"
    )
    return None, None, None, err


class DefaultCommandGroup(click.Group):
    """A Click Group that routes non-subcommand invocations to a default command."""

    def __init__(self, *args, **kwargs):
        self.default_cmd_name = kwargs.pop("default_cmd", "route")
        super().__init__(*args, **kwargs)

    def parse_args(self, ctx, args):
        if not args:
            return super().parse_args(ctx, args)
        first_arg = args[0]
        if first_arg in self.commands:
            return super().parse_args(ctx, args)
        if first_arg in ("--help", "--version"):
            return super().parse_args(ctx, args)
        args = [self.default_cmd_name] + list(args)
        return super().parse_args(ctx, args)

    def format_usage(self, ctx, formatter):
        formatter.write_usage(
            ctx.command_path,
            "[OPTIONS] [ORIGIN] [DESTINATION] | COMMAND [ARGS]...",
        )


@click.group(cls=DefaultCommandGroup, default_cmd="route", invoke_without_command=True)
@click.version_option(package_name="traffic-cli")
@click.pass_context
def traffic(ctx):
    """Calculates route and travel time between locations.

\b
Examples:
  traffic california nevada
  traffic "las vegas" california
  traffic las vegas to california
  traffic home work
  traffic --country gb b46 cv7
  traffic --json home work
  traffic --headless --compact home work
  traffic --home London --destination Paris
"""
    if ctx.invoked_subcommand is None and not ctx.params:
        click.echo(ctx.get_help())


@traffic.command("route", hidden=True)
@click.argument("locations", nargs=-1)
@click.option("--home", "-h", help="Starting postcode or address")
@click.option("--destination", "-d", help="Ending postcode or address")
@click.option("--country", "--cc", help="Country code bias for geocoding (e.g. 'gb', 'us', 'fr')")
@click.option("--no-motorways", is_flag=True, help="Avoid motorways")
@click.option("--include-tolls", is_flag=True, help="Include toll roads")
@click.option("--headless", "-q", "--quiet", is_flag=True, help="Headless mode: suppress tips and output clean duration")
@click.option("--json", "json_output", is_flag=True, help="Output result in JSON format (Waybar compatible)")
@click.option("--compact", "-c", is_flag=True, help="Output compact duration (e.g. '1h 15m')")
@click.option("--raw", "--seconds", is_flag=True, help="Output raw duration in seconds")
@click.pass_context
def route_cmd(
    ctx,
    locations,
    home,
    destination,
    country,
    no_motorways,
    include_tolls,
    headless,
    json_output,
    compact,
    raw,
):
    """Calculates route and travel time between locations."""
    is_headless = headless or json_output or compact or raw
    config = get_initialized_config(headless=is_headless)

    origin, dest, info, err = resolve_locations(
        locations=locations,
        home_opt=home,
        dest_opt=destination,
        config=config,
        country_code=country,
    )

    if err:
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "text": "error",
                        "alt": "traffic-error",
                        "tooltip": err.splitlines()[0],
                        "class": "error",
                        "error": err,
                    }
                )
            )
        else:
            click.echo(err, err=True)
        ctx.exit(1)

    if info and not is_headless:
        click.echo(info)

    try:
        router = Router(config)
        duration = router.get_travel_time(origin, dest, country_code=country)
        home_addr = getattr(getattr(router, "last_home_location", None), "address", origin)
        dest_addr = getattr(getattr(router, "last_destination_location", None), "address", dest)
        resolved_h, resolved_d = router.resolve_var(origin, dest)

        if json_output:
            formatted = format_duration(duration)
            compact_fmt = format_duration_compact(duration)
            output_data = {
                "text": compact_fmt,
                "alt": "traffic",
                "tooltip": f"From: {resolved_h} ({home_addr})\nTo: {resolved_d} ({dest_addr})\nTravel time: {formatted}",
                "class": "traffic",
                "duration_seconds": int(duration),
                "formatted": formatted,
                "compact": compact_fmt,
                "origin": resolved_h,
                "origin_address": home_addr,
                "destination": resolved_d,
                "destination_address": dest_addr,
            }
            click.echo(json.dumps(output_data))
        elif raw:
            click.echo(int(duration))
        elif compact:
            click.echo(format_duration_compact(duration))
        elif headless:
            click.echo(format_duration(duration))
        else:
            click.echo(f"From: {resolved_h} ({home_addr})")
            click.echo(f"To:   {resolved_d} ({dest_addr})")
            click.echo(f"Travel time: {format_duration(duration)}")
    except Exception as e:
        error_msg = format_error_message(e)
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "text": "error",
                        "alt": "traffic-error",
                        "tooltip": f"Traffic error: {error_msg}",
                        "class": "error",
                        "error": error_msg,
                    }
                )
            )
        else:
            click.echo(f"Error calculating travel time: {error_msg}", err=True)
        ctx.exit(1)


@traffic.command()
@click.argument("provider_name")
@click.argument("api_key")
@click.argument("profile", default="car")
def init(provider_name, api_key, profile):
    """Creates the initial config"""
    config = Config()
    try:
        config.initialise(provider_name, api_key, profile)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"Initialised with {provider_name}")


@traffic.command()
@click.argument("key")
@click.argument("value")
def set(key, value):
    """Sets a configuration variable or setting (e.g. country, profile, api_key, home)."""
    config = get_initialized_config()
    try:
        config.set_config_value(key, value)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"Set {key} to {value}")


if __name__ == "__main__":
    traffic()
