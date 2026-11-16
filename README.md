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
(OpenRouteService, GraphHopper, Mapbox, or Google Maps).

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

Configuration is stored at `~/.traffic/config.json`, readable only by you
(it holds your API key).

### Supported providers

| Provider           | `init` name    | Live traffic | Get a key                              |
| ------------------ | -------------- | ------------ | -------------------------------------- |
| OpenRouteService   | `ors`          | No           | https://openrouteservice.org/          |
| GraphHopper        | `graphhopper`  | No           | https://www.graphhopper.com/           |
| Mapbox             | `mapbox`       | Yes          | https://www.mapbox.com/                |
| Google Maps        | `google_maps`  | Yes          | https://developers.google.com/maps     |

With the `car` profile, Mapbox (`driving-traffic`) and Google Maps (departure
time *now*) return durations that include current traffic. OpenRouteService
and GraphHopper return a free-flow estimate, and the default output says so.
Pass `--no-traffic` to get the free-flow duration from any provider.

Google bills a request that returns traffic data (`duration_in_traffic`) as
*Directions Advanced*: $10 per 1,000 requests after 5,000 free a month,
against $5 per 1,000 after 10,000 free without traffic. `--no-traffic` keeps
you on the cheaper rate. traffic-cli uses Google's legacy Directions API,
which can no longer be enabled on new Google Cloud projects (since October
2026); existing projects still work.

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
traffic <origin> to <stop> to <stop> to <destination>
```

Examples:

```bash
traffic california nevada
traffic "las vegas" california
traffic las vegas to california
traffic home work                  # using saved variables (see below)
traffic home to school to work     # multiple stops
traffic --country gb b46 cv7       # bias geocoding to a country
traffic --home London --destination Paris
```

### Multiple stops

Chain as many stops as you like with `to` (or a quoted `"->"`). They are visited in
order, and you get a per-leg breakdown plus the total for the whole trip:

```console
$ traffic home to school to work
From: home (...)
Via:  school (...)
To:   work (...)

  home -> school: 12 mins
  school -> work: 25 mins

Travel time: 37 mins
```

You can also add intermediate stops with the repeatable `--via` / `-v` option:

```bash
traffic home work --via school --via gym
```

#### Per-leg output for scripts

Add `--legs` / `-l` to get one line per leg instead of the total:

```console
$ traffic --raw --legs home to school to work
720
1500
$ traffic --compact --legs home to school to work
12m
25m
```

With `--json`, the output always includes a `stops` list (each stop's name,
resolved address and `[lat, lon]` coords) and a `legs` list:

```json
"legs": [
  {"from": "home", "to": "school", "duration_seconds": 720, "formatted": "12 mins", "compact": "12m"},
  {"from": "school", "to": "work", "duration_seconds": 1500, "formatted": "25 mins", "compact": "25m"}
]
```

The leg breakdown also goes in the tooltip. `--json --legs` replaces the
total in `text` with the leg times, e.g. `12m → 25m`.

Leg times come from the same single routing request. If a response has no
per-leg breakdown, `legs` is empty and only the total is shown.

Google returns no live traffic for routes with intermediate stops, so a
multi-stop Google route is a free-flow estimate (`traffic_aware: false`).
Mapbox includes traffic for up to 25 stops.

### Saved variables

Save frequently used locations as named shortcuts:

```bash
traffic set home "10 Downing Street, London"
traffic set work "Buckingham Palace, London"
traffic home work
```

### Coordinates

A `lat,lon` pair in decimal degrees is used as-is, with no geocoding. It works
as an origin, a destination, or a saved variable:

```bash
traffic 52.4862,-1.8904 51.5072,-0.1276
traffic set home 52.4862,-1.8904
```

Negative coordinates work as-is: `traffic -33.8688,151.2093 "sydney airport"`.

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
| `--legs` / `-l`       | One line per leg (with `--raw`/`--compact`/`--headless`); leg times as the `--json` text |

Other options:

| Flag           | Effect                                                         |
| -------------- | -------------------------------------------------------------- |
| `--no-traffic`   | Free-flow duration, even if the provider has live traffic    |
| `--no-motorways` | Avoid motorways (`car` profile only)                         |
| `--no-tolls`     | Avoid toll roads (`car` profile only)                        |
| `--no-cache`     | Don't read or write the on-disk geocode cache                |

### JSON output

```json
{
  "text": "2h 22m", "alt": "traffic", "tooltip": "...", "class": "traffic",
  "duration_seconds": 8553, "formatted": "2 hours, 22 mins, 33 seconds", "compact": "2h 22m",
  "origin": "home", "origin_address": "...", "origin_coords": [52.4862, -1.8904],
  "destination": "work", "destination_address": "...", "destination_coords": [51.5072, -0.1276],
  "provider": "google_maps", "traffic_aware": true, "duration_free_flow_seconds": 7900
}
```

`duration_seconds` includes traffic when `traffic_aware` is true.
`duration_free_flow_seconds` is present only when the provider reports it
(currently Google Maps; Mapbox's traffic profile has no free-flow figure).

On failure the exit code is 1 and the object has `"class": "error"`, a
human-readable `error`, and an `error_kind`: one of `config`, `usage`,
`geocode` (location not found), `no_route`, `auth`, `rate_limit`, `network`,
or `unknown`. `rate_limit` and `network` are worth retrying later; the others
will fail the same way until something changes.

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

For a multi-stop commute, `"exec": "traffic --json --legs home to school to work"`
shows each leg in the bar (`12m → 25m`), with the full breakdown and total in
the tooltip.

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
  rate-limited to ~1/second, and found locations (and country names given to
  `--country`) are cached for 30 days in
  `$XDG_CACHE_HOME/traffic-cli/geocode.json` (default `~/.cache/...`), to
  respect its [usage policy](https://operations.osmfoundation.org/policies/nominatim/).
  Delete that file to clear the cache.
- API usage (and any billing) is governed by whichever routing provider you
  configure.
