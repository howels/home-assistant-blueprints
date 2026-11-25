"""Tests for blueprints/panda_esl_weather.yaml.

The tests register fake weather.get_forecasts and panda_esl.write services, run the blueprint in a
real Home Assistant core and inspect the payload that the blueprint sends. Set PANDA_PAYLOAD_DIR to
write each payload as JSON, for rendering with the ha-panda renderer.
"""
import asyncio
import json
import os
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.core import SupportsResponse
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

BP = Path(__file__).resolve().parents[1] / "blueprints/panda_esl_weather.yaml"
WEATHER = "weather.home"

@pytest.fixture(autouse=True)
def midday(freezer):
    """Local midday, so that events two hours ahead stay on the same day."""
    freezer.move_to("2026-11-25 20:00:00+00:00")



async def pump(n=300):
    for _ in range(n):
        await asyncio.sleep(0)


def forecast_days():
    today = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    rows = [
        ("sunny", 14, 6, 0),
        ("rainy", 11, 7, 80),
        ("partlycloudy", 12, 5, 10),
        ("clear-night", 9, -2, 0),
        ("snowy", 1, -3, 60),
    ]
    return [
        {
            "datetime": (today + timedelta(days=i)).isoformat(),
            "condition": c,
            "temperature": hi,
            "templow": lo,
            "precipitation_probability": p,
        }
        for i, (c, hi, lo, p) in enumerate(rows)
    ]


async def setup(hass, inputs=None, forecast=True, state="partlycloudy", action="write_guarded", rows=None, attrs=None):
    d = Path(hass.config.path("blueprints/automation/howels"))
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(BP, d)
    calls = []

    async def write(call):
        calls.append((call.service, dict(call.data)))

    for s in ("write", "write_guarded"):
        hass.services.async_register("panda_esl", s, write)

    forecast_calls = []

    async def get_forecasts(call):
        forecast_calls.append(dict(call.data))
        if not forecast:
            raise ValueError("daily forecast not supported")
        return {WEATHER: {"forecast": rows if rows is not None else forecast_days()}}

    hass.services.async_register(
        "weather", "get_forecasts", get_forecasts, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set(
        WEATHER,
        state,
        {
            "temperature": 12.4,
            "temperature_unit": "°C",
            "humidity": 71,
            "wind_speed": 14.2,
            "wind_speed_unit": "km/h",
            **(attrs or {}),
        },
    )
    use = {
        "path": "howels/panda_esl_weather.yaml",
        "input": {"display": "dev1", "weather_entity": WEATHER, "write_action": f"panda_esl.{action}"},
    }
    use["input"].update(inputs or {})
    assert await async_setup_component(
        hass, "automation", {"automation": [{"id": "w", "alias": "weather label", "use_blueprint": use}]}
    )
    await hass.async_block_till_done()
    return calls, forecast_calls


async def run(hass, calls):
    await hass.services.async_call("automation", "trigger", {"entity_id": "automation.weather_label"}, blocking=False)
    await pump()
    assert calls, "no write"
    service, data = calls[-1]
    out = os.environ.get("PANDA_PAYLOAD_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        name = os.environ.get("PYTEST_CURRENT_TEST", "payload").split("::")[-1].split(" ")[0]
        (Path(out) / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return service, data


def visible(data):
    return [e for e in data["payload"] if e.get("visible", True) is not False]


def texts(data):
    return [e["value"] for e in visible(data) if e["type"] == "text"]


def icons(data):
    return [e["value"] for e in visible(data) if e["type"] == "icon"]


async def test_defaults(hass):
    calls, fc = await setup(hass)
    service, data = await run(hass, calls)
    assert service == "write_guarded"
    assert fc == [{"entity_id": [WEATHER], "type": "daily"}]
    assert data["background"] == "white"
    assert data["dry_run"] is False
    assert data["device_id"] == ["dev1"]
    t = texts(data)
    assert "12°C" in t
    assert "↑14°  ↓6°" in t
    assert "Partly Cloudy" in t
    assert "80%" not in t  # tomorrow's rain chance is not today's
    assert "10%" not in t
    assert "71%" in t
    assert "14 km/h" in t
    assert "--" not in t
    # Today is excluded from the strip. Three further days.
    assert icons(data).count("weather-rainy") == 1
    assert "weather-partly-cloudy" in icons(data)
    assert "weather-night" in icons(data)
    assert "weather-snowy" not in icons(data)  # fourth day beyond the strip
    assert "↑9°  ↓-2°" in t
    assert "↑11°  ↓7°" in t and "↑12°  ↓5°" in t
    reds = [e["value"] for e in visible(data) if e.get("color") == "red"]
    assert "weather-rainy" in reds
    assert all(e["y"] is not True for e in data["payload"] if "y" in e)


async def test_every_coordinate_inside_canvas(hass):
    calls, _ = await setup(hass)
    _, data = await run(hass, calls)
    for e in visible(data):
        for key in ("x", "y", "x_start", "x_end", "y_start", "y_end"):
            if key in e:
                assert isinstance(e[key], int), (key, e)
                assert 0 <= e[key] < (360 if key.startswith("x") else 240), (key, e)
        if "size" in e:
            assert isinstance(e["size"], int) and e["size"] > 0, e


@pytest.mark.parametrize("size,w,h", [("256x128", 256, 128), ("296x152", 296, 152), ("400x300", 400, 300)])
async def test_sizes(hass, size, w, h):
    calls, _ = await setup(hass, {"display_size": size})
    _, data = await run(hass, calls)
    for e in visible(data):
        for key in ("x", "x_start", "x_end"):
            if key in e:
                assert 0 <= e[key] < w, (key, e)
        for key in ("y", "y_start", "y_end"):
            if key in e:
                assert 0 <= e[key] < h, (key, e)
    strip = "weather-rainy" in icons(data)
    assert strip == (h >= 240)


async def test_emoji_style(hass):
    calls, _ = await setup(hass, {"icon_style": "emoji", "emoji_font": "NotoEmoji-Regular.ttf"})
    _, data = await run(hass, calls)
    assert icons(data) == []
    t = texts(data)
    assert "\u26C5" in t  # partly cloudy
    assert "\U0001F327" in t  # tomorrow, rainy
    assert "\u2614" in t and "\U0001F4A7" in t and "\U0001F4A8" in t
    emoji = [e for e in visible(data) if e.get("font") == "NotoEmoji-Regular.ttf"]
    assert len(emoji) == 7


async def test_no_forecast_support(hass):
    calls, _ = await setup(hass, forecast=False)
    _, data = await run(hass, calls)
    t = texts(data)
    assert "12°C" in t
    assert "--" in t  # rain chance unknown
    assert not any("↑" in x for x in t)
    assert "weather-rainy" not in icons(data)
    assert len(visible(data)) < len(data["payload"])


async def test_forecast_switch_off(hass):
    calls, _ = await setup(hass, {"show_forecast": False})
    _, data = await run(hass, calls)
    assert "weather-rainy" not in icons(data)
    assert "↑11°  ↓7°" not in texts(data)


async def test_write_and_dry_run(hass):
    calls, _ = await setup(hass, {"dry_run": True}, action="write")
    service, data = await run(hass, calls)
    assert service == "write"
    assert data["dry_run"] is True


async def test_wet_condition_is_red(hass):
    calls, _ = await setup(hass, state="pouring")
    _, data = await run(hass, calls)
    assert "weather-pouring" in [e["value"] for e in visible(data) if e.get("color") == "red"]


async def test_skipped_when_unavailable(hass):
    calls, _ = await setup(hass, state="unavailable")
    await hass.services.async_call(
        "automation",
        "trigger",
        {"entity_id": "automation.weather_label", "skip_condition": False},
        blocking=False,
    )
    await pump()
    assert calls == []
    hass.states.async_set(WEATHER, "unknown")
    await pump()
    assert calls == []


async def test_state_change_triggers(hass):
    calls, _ = await setup(hass)
    hass.states.async_set(WEATHER, "rainy", {"temperature": 9})
    await pump()
    assert len(calls) == 1


def met_no_rows(rain):
    """Met.no style daily forecast: precipitation in mm and no precipitation_probability."""
    today = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    return [
        {"datetime": (today + timedelta(days=i)).isoformat(), "condition": "cloudy", "temperature": 6 - i,
         "templow": 1, "precipitation": rain, "wind_speed": 19.1, "humidity": 72}
        for i in range(5)
    ]


async def test_rain_amount_when_no_probability(hass):
    calls, _ = await setup(hass, rows=met_no_rows(0.6), attrs={"precipitation_unit": "mm"})
    _, data = await run(hass, calls)
    assert "0.6 mm" in texts(data)
    assert "--" not in texts(data)
    umbrella = [e for e in visible(data) if e.get("value") == "umbrella"][0]
    assert umbrella["color"] == "red"


async def test_dry_day_has_black_umbrella(hass):
    calls, _ = await setup(hass, rows=met_no_rows(0.0), attrs={"precipitation_unit": "mm"})
    _, data = await run(hass, calls)
    assert "0 mm" in texts(data)
    umbrella = [e for e in visible(data) if e.get("value") == "umbrella"][0]
    assert umbrella["color"] == "black"
