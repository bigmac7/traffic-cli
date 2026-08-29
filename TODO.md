# TODO

Deferred items from the code review (2026-08-29). None are blockers for the
currently published `0.1.1`, but each is worth addressing before the next release.

## 1. Write a real README
`pyproject.toml` sets `readme = "README.md"`, but the file is empty, so the PyPI
project page is blank. Add usage, install instructions, supported providers, and
examples — this file is the package's landing page on PyPI.

## 2. Rate-limit / cache Nominatim geocoding
The heuristic split loop in `resolve_locations` (`src/traffic/cli.py`) can fire
up to `2 * (n - 1)` `geocoder.geocode()` calls in a tight burst, and `Router`
then geocodes both endpoints again. OSM's public Nominatim allows ~1 request/sec
and forbids bulk use, so heavy queries risk a `403`/IP ban.
- Cache geocode results within a single invocation (avoid re-geocoding the same
  string, and reuse the heuristic hits in `Router`).
- Set a descriptive `user_agent` (app name + contact) in `geo.py` instead of the
  generic `"traffic"`, which Nominatim's policy discourages.

## 3. Single source of truth for providers
`Config._get_router_class` (`config.py`) resolves any matching `routingpy` class,
while `provider_map` (`geo.py`) only supports 5 providers. `traffic init` can
accept a provider that `Router` later rejects. Consolidate to one authoritative
provider list and validate at init time.
