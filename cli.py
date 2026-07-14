from abstract.geo import Router
from config import Config
import click


def get_initialized_config():
    """Gets the configuration, automatically prompting for initialization if missing."""
    config = Config()
    if not config.provider_name:
        click.echo("Configuration not found or not initialized.")
        provider_name = click.prompt(
            "Please enter provider name (e.g. ORS, Graphhopper)"
        )
        api_key = click.prompt("Please enter API key")
        profile = click.prompt("Please enter default profile", default="car")
        config.initialise(provider_name, api_key, profile)
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


@click.group()
def cli():
    pass


@cli.group(invoke_without_command=True)
@click.option("--home", help="Starting postcode or address")
@click.option("--destination", help="Ending postcode or address")
@click.option("--no-motorways", is_flag=True, help="Avoid motorways")
@click.option("--include-tolls", is_flag=True, help="Include toll roads")
@click.pass_context
def traffic(ctx, home, destination, no_motorways, include_tolls):
    """Calculates route and travel time between locations."""
    if ctx.invoked_subcommand is not None:
        return

    if not home or not destination:
        click.echo("Error: Please provide both --home and --destination options.")
        click.echo(ctx.get_help())
        ctx.exit(1)

    config = get_initialized_config()
    router = Router(config)

    try:
        duration = router.get_travel_time(home, destination)
        click.echo(f"Travel time: {format_duration(duration)}")
    except Exception as e:
        click.echo(f"Error calculating travel time: {e}", err=True)
        ctx.exit(1)


@traffic.command()
@click.argument("provider_name")
@click.argument("api_key")
@click.argument("profile", default="car")
def init(provider_name, api_key, profile):
    """Creates the initial config"""
    config = Config()
    config.initialise(provider_name, api_key, profile)
    click.echo(f"Initialised with {provider_name}")


@traffic.command()
@click.argument("key")
@click.argument("value")
def set(key, value):
    """Sets a configuration variable."""
    config = get_initialized_config()
    if key == "profile":
        config.set_default_profile(value)
    else:
        config.add_var_to_config(key, value)
    click.echo(f"Set {key} to {value}")


if __name__ == "__main__":
    cli()
