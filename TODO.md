# TODO

The five items proposed for 0.2.0 on 2026-11-16 (traffic-aware durations,
coordinate input/output, `error_kind`, persistent geocode cache, small fixes)
are implemented on `feat/0.2.0`, with tests in `tests/test_cli.py`.

Still open:

- **Google billing for traffic requests.** Setting `departure_time` is required
  for `duration_in_traffic` and is believed to bill at a higher SKU. Confirm on
  the Directions API usage and billing page and state the price in the README.
- **Mapbox free-flow duration.** `driving-traffic` reports no free-flow
  duration, so `duration_free_flow_seconds` is omitted for Mapbox. If you need
  it, make a second `driving` request, which costs an extra call.
- **Negative latitudes need `--`.** Click reads `-33.8,151.2` as an option, so
  `traffic -- -33.8,151.2 ...` or `--home=-33.8,151.2` is required. Documented
  in the README. Fixing it means parsing arguments by hand.
- **`--no-motorways` and `--include-tolls` are accepted but ignored.** Neither
  is passed to the router. Wire them up or remove them.
- **Full country names in `country` config are geocoded every run** (for
  example `france`). Their codes are not in the persistent cache. `traffic set
  country fr` avoids this.
