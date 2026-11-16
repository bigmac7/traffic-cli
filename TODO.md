# TODO

## 1. Move the Google provider to the Routes API

**Problem.** `google_maps` uses Google's legacy Directions API through
`routingpy.Google`. Since October 2026 that API can no longer be enabled on
new Google Cloud projects, so new users cannot set up the provider. Existing
projects still work.

**Proposal.** Call the Routes API (`POST
https://routes.googleapis.com/directions/v2:computeRoutes`) for Google.
`routingpy` 1.3.0 has no Routes client, so either use a newer `routingpy` if
it adds one, or write a small client. If writing one, raise `routingpy`
exceptions from it so `format_error_message` and `error_kind` keep working.

- Traffic: `routingPreference: TRAFFIC_AWARE` gives `duration` with traffic
  and `staticDuration` without, which fill `duration_seconds` and
  `duration_free_flow_seconds`. `--no-traffic` sends `TRAFFIC_UNAWARE`.
- Avoid: `routeModifiers.avoidHighways` / `avoidTolls`.
- Profiles: `DRIVE`, `BICYCLE`, `WALK`.
- Durations come back as strings like `"1234s"`, and a field mask
  (`X-Goog-FieldMask`) is required.

**Watch out: existing users cannot be switched silently.** Not yet verified,
but expected: the Routes API has to be enabled in each Cloud project
separately, and API keys restricted to "Directions API" need "Routes API"
added. Switching `google_maps` underneath them would turn working setups into
`auth` errors. Options:

- Add a new provider (for example `google_routes`), recommend it for new
  setups, and leave `google_maps` on the legacy API until Google retires it.
- Or switch `google_maps` and fall back to the legacy API when Routes answers
  "service disabled", with a one-line hint to enable it.

**Verify before relying on it.**

- Which Routes options move a request from Essentials to Pro billing. Traffic
  aware routing does. Check whether `avoidTolls` and `avoidHighways` do too.
- That enabling and key restrictions work as described above.

**Done when.** Tests show the Routes request body for traffic, `--no-traffic`
and avoid flags, durations are parsed from the `"Ns"` form, and an existing
`google_maps` config keeps working without any user action.
