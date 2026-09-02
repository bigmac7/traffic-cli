# traffic-cli

A small command-line tool that calculates the driving (or cycling/walking)
travel time between two locations using a routing API of your choice.

```console
$ traffic "las vegas" "los angeles"
From: las vegas (Las Vegas, Clark County, Nevada, United States)
To:   los angeles (Los Angeles, Los Angeles County, California, United States)
Travel time: 3 hours, 58 mins
```

Locations can be place names, addresses, or postcodes. Geocoding is done via
OpenStreetMap's Nominatim; routing is delegated to a provider you configure
(OpenRouteService, GraphHopper, Mapbox, Google Maps, or TomTom).

## Installation

Requires Python 3.10+.

```bash
pipx install traffic-cli      # recommended (isolated install)
# or
pip install traffic-cli
# or, with uv
uv tool install traffic-cli
```

## Setup

You need a free/paid API key from one of the supported routing providers, then
run `init` once:

```bash
traffic init <provider> <api_key> [profile]
# e.g.
traffic init ors YOUR_API_KEY car
```

If you run `traffic` before initialising, it will prompt you interactively.

Configuration is stored at `~/.traffic/config.json`.

### Supported providers

| Provider           | `init` name    | Get a key                              |
| ------------------ | -------------- | -------------------------------------- |
| OpenRouteService   | `ors`          | https://openrouteservice.org/          |
| GraphHopper        | `graphhopper`  | https://www.graphhopper.com/           |
| Mapbox             | `mapbox`       | https://www.mapbox.com/                |
| Google Maps        | `google_maps`  | https://developers.google.com/maps     |

### Travel profiles

Each provider supports three generic profiles: `car` (default), `bike`, and
`walk`. Set your default with:

```bash
traffic set profile bike
```

## Usage

```bash
traffic <origin> <destination>
traffic <origin> to <destination>
```

Examples:

```bash
traffic california nevada
traffic "las vegas" california
traffic las vegas to california
traffic home work                  # using saved variables (see below)
traffic --country gb b46 cv7       # bias geocoding to a country
traffic --home London --destination Paris
```

### Saved variables

Save frequently used locations as named shortcuts:

```bash
traffic set home "10 Downing Street, London"
traffic set work "Buckingham Palace, London"
traffic home work
```

### Country bias

If a place name is ambiguous, bias geocoding to a country with `--country`
(alias `--cc`), or set a default. You can pass an ISO code (`gb`), a country
name (`france`), or a common alias (`uk`, `england`, `usa`):

```bash
traffic --country gb birmingham coventry
traffic --country england b46 b9
traffic set country gb
```

> **Tip:** short, bare UK outward codes like `b9` are ambiguous even within a
> country (they also match B-roads). Use a full postcode (`B9 4AA`) or add a
> town (`"B9, Birmingham"`) for a precise result.

### Output formats

| Flag                  | Output                                                        |
| --------------------- | ------------------------------------------------------------ |
| *(default)*           | Human-readable origin, destination, and travel time          |
| `--compact` / `-c`    | Compact duration, e.g. `3h 58m`                              |
| `--raw` / `--seconds` | Raw duration in seconds                                       |
| `--json`              | JSON object (Waybar-compatible)                              |
| `--headless` / `-q`   | Suppresses tips; prints a clean duration (good for scripts)  |

Routing options:

| Flag              | Effect              |
| ----------------- | ------------------- |
| `--no-motorways`  | Avoid motorways     |
| `--include-tolls` | Include toll roads  |

### Waybar

The `--json` output is designed to drop straight into a
[Waybar](https://github.com/Alexays/Waybar) custom module:

```jsonc
"custom/traffic": {
    "exec": "traffic --json home work",
    "return-type": "json",
    "interval": 300
}
```

## Commands

| Command                              | Description                                  |
| ------------------------------------ | -------------------------------------------- |
| `traffic <origin> <destination>`     | Calculate travel time (the default command)  |
| `traffic init <provider> <key> [profile]` | Create the initial configuration        |
| `traffic set <key> <value>`          | Set a setting (`profile`, `country`, `api_key`, `provider_name`) or a saved variable |
| `traffic --version`                  | Print the installed version                  |
| `traffic --help`                     | Show help                                    |

## Notes

- Geocoding uses OpenStreetMap's public Nominatim service. Requests are
  rate-limited to ~1/second and cached per invocation to respect its
  [usage policy](https://operations.osmfoundation.org/policies/nominatim/).
- API usage (and any billing) is governed by whichever routing provider you
  configure.
