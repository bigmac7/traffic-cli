---
name: security-scan
description: Security scan for traffic-cli, covering the dependency audit and this repo's API-key, error-output and cache paths. Use before opening a PR, after changing dependencies or uv.lock, or when asked for a security check.
---

# Security scan

## Steps

1. **Audit dependencies and workflows.** Run the `Audit locked dependencies`
   and `Audit workflows` steps from
   `.github/workflows/security.yml`, setting `RUNNER_TEMP` to your scratch
   directory. That workflow defines the CI gate, so run it exactly as written.
   For each vulnerable package, run `uv lock --upgrade-package <name>`. If the
   package is a direct dependency in `pyproject.toml`, also raise its floor to
   the fixed version. Fix each workflow finding as zizmor advises. Then run
   `uv run pytest -q`. Done when both audits exit 0 and the tests pass.
2. **Review the diff.** Read `git diff main...HEAD`, plus uncommitted changes,
   against every rule in the reference below. Done when each rule is either
   confirmed to hold or reported with `file:line`.
3. **Report.** List upgraded packages with their advisory IDs, and list each
   rule violation with a proposed fix.

## Reference: what must stay true

- **The API key stays in `~/.traffic/config.json`.** `Config.save` writes that
  file with mode `0600`. The key appears in no output: human, `--json`,
  `tooltip`, error messages or logs. Tests point `CONFIG_DIR` at a temporary
  directory.
- **Errors carry no request URLs.** Google and ORS send the key in the query
  string. Text in `format_error_message` comes only from response bodies and
  exception messages.
- **Untrusted input is treated as data.** CLI arguments, Nominatim results and
  provider responses never reach a shell, `eval`, `exec` or `pickle`. The
  `ast.literal_eval` fallback in `format_error_message` is the one parser
  allowed on response text.
- **The geocode cache holds only public data.** `geo.CACHE_FILE` stores
  addresses, coordinates and country codes, never keys. It is written through
  a temporary file and `os.replace`.
- **Nominatim is called politely.** Every call goes through
  `_rate_limited_geocode` with the descriptive user agent, as its usage policy
  requires.
- **Workflows run with least privilege.** Each workflow sets `permissions:`
  explicitly, checks out with `persist-credentials: false` when it doesn't
  push, and pins third-party actions to a full commit SHA with a version
  comment.
