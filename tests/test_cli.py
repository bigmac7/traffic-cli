"""CLI tests. The geocoder and routing clients are faked; nothing touches the network."""

import json
import stat
from types import SimpleNamespace

import pytest
import routingpy
from click.testing import CliRunner
from geopy.exc import GeocoderTimedOut
from geopy.location import Location
from routingpy.exceptions import OverQueryLimit, RouterApiError, Timeout

import traffic.config
from traffic.abstract import geo
from traffic.cli import traffic as cli
from traffic.providers import PROVIDERS

PLACES = {
    "birmingham": Location("Birmingham, UK", (52.4862, -1.8904), {"importance": 0.8}),
    "london": Location("London, UK", (51.5072, -0.1276), {"importance": 0.9}),
}


class FakeClient:
    calls: list = []
    result = None

    def __init__(self, api_key):
        pass

    def directions(self, **kwargs):
        FakeClient.calls.append(kwargs)
        if isinstance(FakeClient.result, Exception):
            raise FakeClient.result
        return FakeClient.result


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(traffic.config, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(geo, "CACHE_FILE", tmp_path / "cache" / "geocode.json")
    monkeypatch.setattr(geo, "_geocode_cache", {})
    monkeypatch.setattr(geo, "_disk_cache", None)
    for info in PROVIDERS.values():
        monkeypatch.setattr(routingpy, info["class_name"], FakeClient)
    monkeypatch.setattr(FakeClient, "calls", [])
    monkeypatch.setattr(FakeClient, "result", SimpleNamespace(duration=3600, raw={}))

    geocoded = []

    def fake_geocode(query, **kwargs):
        geocoded.append(query)
        result = PLACES.get(query.lower())
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(geo, "_rate_limited_geocode", fake_geocode)

    def configure(provider="ors", profile="car", vars=None):
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / "config.json").write_text(
            json.dumps({"provider_name": provider, "api_key": "k", "profile": profile, "vars": vars or {}})
        )

    def run(*args):
        return CliRunner().invoke(cli, list(args))

    def new_process():
        geo._geocode_cache.clear()
        geo._disk_cache = None

    return SimpleNamespace(configure=configure, run=run, geocoded=geocoded, new_process=new_process)


def run_json(env, *args):
    result = env.run("--json", *args)
    return result.exit_code, json.loads(result.stdout)


GOOGLE_RAW = {
    "routes": [
        {
            "legs": [
                {"duration": {"value": 1000}, "duration_in_traffic": {"value": 1500}},
                {"duration": {"value": 2000}, "duration_in_traffic": {"value": 2500}},
            ]
        }
    ]
}


# --- 1. traffic-aware durations ---------------------------------------------


def test_google_uses_departure_time_and_duration_in_traffic(env):
    env.configure("google_maps")
    FakeClient.result = SimpleNamespace(duration=3000, raw=GOOGLE_RAW)
    code, out = run_json(env, "birmingham", "london")
    assert code == 0
    assert isinstance(FakeClient.calls[0]["departure_time"], int)
    assert FakeClient.calls[0]["profile"] == "driving"
    assert out["duration_seconds"] == 4000
    assert out["duration_free_flow_seconds"] == 3000
    assert out["traffic_aware"] is True
    assert out["provider"] == "google_maps"


def test_google_without_duration_in_traffic_is_not_traffic_aware(env):
    env.configure("google")
    FakeClient.result = SimpleNamespace(duration=3000, raw={"routes": [{"legs": [{"duration": {"value": 3000}}]}]})
    code, out = run_json(env, "birmingham", "london")
    assert (out["duration_seconds"], out["traffic_aware"]) == (3000, False)
    assert "duration_free_flow_seconds" not in out


def test_mapbox_uses_driving_traffic(env):
    env.configure("mapbox")
    code, out = run_json(env, "birmingham", "london")
    assert FakeClient.calls[0]["profile"] == "driving-traffic"
    assert out["traffic_aware"] is True
    assert out["provider"] == "mapbox"


@pytest.mark.parametrize("provider", ["ors", "graphhopper"])
def test_providers_without_traffic(env, provider):
    env.configure(provider)
    code, out = run_json(env, "birmingham", "london")
    assert out["traffic_aware"] is False
    assert FakeClient.calls[0]["profile"] == PROVIDERS[provider]["profiles"]["car"]
    assert "departure_time" not in FakeClient.calls[0]


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_no_traffic_restores_free_flow(env, provider):
    env.configure(provider)
    FakeClient.result = SimpleNamespace(duration=3000, raw=GOOGLE_RAW)
    code, out = run_json(env, "--no-traffic", "birmingham", "london")
    assert FakeClient.calls[0] == {
        "locations": [[-1.8904, 52.4862], [-0.1276, 51.5072]],
        "profile": PROVIDERS[provider]["profiles"]["car"],
    }
    assert (out["duration_seconds"], out["traffic_aware"]) == (3000, False)


def test_traffic_only_applies_to_car(env):
    env.configure("mapbox", profile="bike")
    code, out = run_json(env, "birmingham", "london")
    assert FakeClient.calls[0]["profile"] == "cycling"
    assert out["traffic_aware"] is False


def test_human_output_notes_missing_traffic(env):
    env.configure("ors")
    assert "no live traffic data from ors" in env.run("birmingham", "london").stderr
    assert env.run("--compact", "birmingham", "london").stderr == ""
    env.configure("mapbox")
    assert "no live traffic" not in env.run("birmingham", "london").stderr


def test_existing_json_keys_kept(env):
    env.configure()
    code, out = run_json(env, "birmingham", "london")
    for key in ("text", "alt", "tooltip", "class", "duration_seconds", "formatted", "compact",
                "origin", "origin_address", "destination", "destination_address"):
        assert key in out


# --- 2. coordinates -----------------------------------------------------------


def test_coordinates_skip_geocoding(env):
    env.configure()
    code, out = run_json(env, "52.4862,-1.8904", "51.5072,-0.1276")
    assert code == 0
    assert env.geocoded == []
    assert out["origin_coords"] == [52.4862, -1.8904]
    assert out["destination_coords"] == [51.5072, -0.1276]
    assert FakeClient.calls[0]["locations"] == [[-1.8904, 52.4862], [-0.1276, 51.5072]]


def test_saved_variable_with_coordinates(env):
    env.configure(vars={"home": "52.4862,-1.8904"})
    code, out = run_json(env, "home", "london")
    assert env.geocoded == ["london"]
    assert out["origin_coords"] == [52.4862, -1.8904]


def test_coordinates_in_single_argument(env):
    env.configure()
    code, out = run_json(env, "52.48,-1.89 to london")
    assert env.geocoded == ["london"]
    assert out["origin_coords"] == [52.48, -1.89]
    # A lone pair is one location, not "52.48" -> "-1.89".
    code, out = run_json(env, "52.48,-1.89")
    assert out["error_kind"] == "usage"


@pytest.mark.parametrize("args", [
    ("-33.8688,151.2093", "london"),
    ("--", "-33.8688,151.2093", "london"),
    ("--home", "-33.8688,151.2093", "london"),
])
def test_negative_latitude(env, args):
    env.configure()
    code, out = run_json(env, *args)
    assert code == 0
    assert out["origin"] == "-33.8688,151.2093"
    assert out["origin_coords"] == [-33.8688, 151.2093]


def test_out_of_range_coordinates_are_geocoded(env):
    assert geo.parse_coords("91,0") is None
    assert geo.parse_coords("0,181") is None
    assert geo.parse_coords(" 1.5 , -2 ") == (1.5, -2.0)


# --- 3. error kinds -----------------------------------------------------------


def test_error_kind_config(env):
    code, out = run_json(env, "birmingham", "london")
    assert (code, out["error_kind"]) == (1, "config")


def test_error_kind_usage(env):
    env.configure()
    code, out = run_json(env)
    assert (code, out["error_kind"]) == (1, "usage")


def test_error_kind_geocode(env):
    env.configure()
    code, out = run_json(env, "atlantis", "london")
    assert (code, out["error_kind"]) == (1, "geocode")


def test_error_kind_geocoder_down(env, monkeypatch):
    env.configure()
    monkeypatch.setitem(PLACES, "birmingham", GeocoderTimedOut("slow"))
    code, out = run_json(env, "birmingham", "london")
    assert (code, out["error_kind"]) == (1, "network")


@pytest.mark.parametrize(
    "exc, kind",
    [
        (RouterApiError(404, '{"error": {"message": "Route could not be found"}}'), "no_route"),
        (RouterApiError(401, '{"message": "Not Authorized - Invalid Token"}'), "auth"),
        (OverQueryLimit(429, "Too Many Requests"), "rate_limit"),
        (Timeout(), "network"),
        (RuntimeError("boom"), "unknown"),
    ],
)
def test_error_kind_from_router(env, exc, kind):
    env.configure()
    FakeClient.result = exc
    code, out = run_json(env, "birmingham", "london")
    assert (code, out["error_kind"]) == (1, kind)
    assert {"text", "alt", "tooltip", "class", "error"} <= out.keys()


# --- 4. persistent geocode cache ----------------------------------------------


def test_geocode_cache_persists_across_invocations(env):
    env.configure()
    run_json(env, "birmingham", "london")
    assert len(env.geocoded) == 2
    env.new_process()
    code, out = run_json(env, "birmingham", "london")
    assert len(env.geocoded) == 2
    assert out["origin_address"] == "Birmingham, UK"
    assert out["origin_coords"] == [52.4862, -1.8904]


def test_no_cache_geocodes_every_time(env):
    env.configure()
    run_json(env, "--no-cache", "birmingham", "london")
    env.new_process()
    run_json(env, "--no-cache", "birmingham", "london")
    assert len(env.geocoded) == 4
    assert not geo.CACHE_FILE.exists()


def test_geocode_cache_skips_misses_and_expired(env, monkeypatch):
    env.configure()
    run_json(env, "london", "atlantis")
    assert set(json.loads(geo.CACHE_FILE.read_text())) == {"|london"}
    env.new_process()
    monkeypatch.setattr(geo, "CACHE_TTL_SECONDS", 0)
    run_json(env, "birmingham", "london")
    assert env.geocoded.count("london") == 2


def test_country_name_lookup_is_cached_on_disk(env):
    env.configure()
    PLACES["france"] = Location("France", (46.6, 1.9), {"address": {"country_code": "fr"}})
    try:
        assert geo.normalize_country("France") == "fr"
        geo._country_code_cache.clear()
        env.new_process()
        assert geo.normalize_country("france") == "fr"
        assert env.geocoded == ["France"]
    finally:
        del PLACES["france"]
        geo._country_code_cache.clear()


# --- 5. config file permissions -----------------------------------------------


def test_config_is_private(env):
    config = traffic.config.Config()
    config.initialise("ors", "secret", "car")
    assert stat.S_IMODE(config.config_file.stat().st_mode) == 0o600
    config.config_file.chmod(0o644)
    config.save()
    assert stat.S_IMODE(config.config_file.stat().st_mode) == 0o600


# --- avoid motorways / tolls ----------------------------------------------------


@pytest.mark.parametrize(
    "provider, expected",
    [
        ("ors", {"options": {"avoid_features": ["highways", "tollways"]}}),
        ("google_maps", {"avoid": ["highways", "tolls"]}),
        ("mapbox", {"exclude": "motorway,toll"}),
        ("graphhopper", {
            "custom_model": {"priority": [
                {"if": "road_class == MOTORWAY", "multiply_by": "0"},
                {"if": "toll != NO", "multiply_by": "0"},
            ]},
            "ch_disable": True,
        }),
    ],
)
def test_avoid_motorways_and_tolls(env, provider, expected):
    env.configure(provider)
    FakeClient.result = SimpleNamespace(duration=3000, raw=GOOGLE_RAW)
    run_json(env, "--no-motorways", "--no-tolls", "birmingham", "london")
    assert {k: FakeClient.calls[0][k] for k in expected} == expected


def test_avoid_only_one(env):
    env.configure("mapbox")
    run_json(env, "--no-tolls", "birmingham", "london")
    assert FakeClient.calls[0]["exclude"] == "toll"


def test_avoid_ignored_off_car_and_include_tolls_is_noop(env):
    env.configure("ors", profile="bike")
    run_json(env, "--no-motorways", "birmingham", "london")
    assert "options" not in FakeClient.calls[0]
    env.configure("ors")
    code, out = run_json(env, "--include-tolls", "birmingham", "london")
    assert code == 0
    assert "options" not in FakeClient.calls[1]


# --- multi-stop routes ------------------------------------------------------------

COVENTRY = Location("Coventry, UK", (52.4068, -1.5197), {"importance": 0.7})


@pytest.mark.parametrize(
    "raw",
    [
        {"features": [{"properties": {"segments": [{"duration": 600}, {"duration": 900}]}}]},  # ORS geojson
        {"routes": [{"segments": [{"duration": 600}, {"duration": 900}]}]},  # ORS json
        {"routes": [{"legs": [{"duration": 600}, {"duration": 900}]}]},  # Mapbox
        {"routes": [{"legs": [{"duration": {"value": 600}}, {"duration": {"value": 900}}]}]},  # Google
        {"paths": [{"instructions": [  # GraphHopper: sign 5 = via reached, 4 = finish
            {"time": 200000, "sign": 0}, {"time": 400000, "sign": 5}, {"time": 900000, "sign": 4},
        ]}]},
    ],
)
def test_extract_leg_durations(raw):
    assert geo.extract_leg_durations(raw, 2) == [600.0, 900.0]
    assert geo.extract_leg_durations(raw, 3) is None


@pytest.mark.parametrize(
    "args",
    [
        ("birmingham to coventry to london",),
        ("birmingham", "to", "coventry", "->", "london"),
        ("birmingham", "london", "--via", "coventry"),
    ],
)
def test_multi_stop_single_request(env, monkeypatch, args):
    monkeypatch.setitem(PLACES, "coventry", COVENTRY)
    env.configure("mapbox")
    FakeClient.result = SimpleNamespace(duration=1500, raw={"routes": [{"legs": [{"duration": 600}, {"duration": 900}]}]})
    code, out = run_json(env, "--no-motorways", *args)
    assert code == 0
    assert len(FakeClient.calls) == 1
    call = FakeClient.calls[0]
    assert call["locations"] == [[-1.8904, 52.4862], [-1.5197, 52.4068], [-0.1276, 51.5072]]
    assert (call["profile"], call["exclude"]) == ("driving-traffic", "motorway")
    assert [s["name"] for s in out["stops"]] == ["birmingham", "coventry", "london"]
    assert out["stops"][1]["coords"] == [52.4068, -1.5197]
    assert [leg["duration_seconds"] for leg in out["legs"]] == [600, 900]
    assert out["duration_seconds"] == 1500
    assert out["traffic_aware"] is True


def test_legs_flag_outputs(env, monkeypatch):
    monkeypatch.setitem(PLACES, "coventry", COVENTRY)
    env.configure("mapbox")
    FakeClient.result = SimpleNamespace(duration=1500, raw={"routes": [{"legs": [{"duration": 600}, {"duration": 900}]}]})
    assert env.run("--raw", "--legs", "birmingham to coventry to london").stdout == "600\n900\n"
    code, out = run_json(env, "--legs", "birmingham to coventry to london")
    assert out["text"] == "10m → 15m"
    assert "Via:" in env.run("birmingham to coventry to london").stdout


def test_google_single_leg_uses_traffic_duration(env):
    env.configure("google_maps")
    FakeClient.result = SimpleNamespace(duration=3000, raw=GOOGLE_RAW)
    code, out = run_json(env, "birmingham", "london")
    assert [leg["duration_seconds"] for leg in out["legs"]] == [4000]


def test_google_multi_stop_has_no_live_traffic(env, monkeypatch):
    monkeypatch.setitem(PLACES, "coventry", COVENTRY)
    env.configure("google_maps")
    raw = {"routes": [{"legs": [{"duration": {"value": 600}}, {"duration": {"value": 900}}]}]}
    FakeClient.result = SimpleNamespace(duration=1500, raw=raw)
    code, out = run_json(env, "birmingham to coventry to london")
    assert out["traffic_aware"] is False
    assert [leg["duration_seconds"] for leg in out["legs"]] == [600, 900]


def test_missing_breakdown_makes_no_extra_requests(env, monkeypatch):
    monkeypatch.setitem(PLACES, "coventry", COVENTRY)
    env.configure("ors")
    code, out = run_json(env, "birmingham to coventry to london")
    assert len(FakeClient.calls) == 1
    assert out["legs"] == []
    assert out["duration_seconds"] == 3600
