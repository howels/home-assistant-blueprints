"""Tests for blueprints/panda_esl_alerts.yaml."""
from datetime import timedelta

import pytest

from panda_helpers import add_automation, icons, images, in_canvas, install, pump, register_write, run, texts, visible


@pytest.fixture(autouse=True)
def midday(freezer):
    freezer.move_to("2026-11-25 20:00:00+00:00")


WATCH = [
    "binary_sensor.front_door",
    "binary_sensor.garage_door",
    "lock.back_door",
    "binary_sensor.hall_battery",
    "binary_sensor.shed",
]


async def setup(hass, inputs=None, states=None, freezer=None):
    install(hass, "panda_esl_alerts.yaml")
    calls = register_write(hass)
    base = {
        "binary_sensor.front_door": ("on", "Front door"),
        "binary_sensor.garage_door": ("off", "Garage door"),
        "lock.back_door": ("unlocked", "Back door lock"),
        "binary_sensor.hall_battery": ("on", "Hall sensor battery low"),
        "binary_sensor.shed": ("off", "Shed"),
    }
    for eid, (st, name) in (states or base).items():
        hass.states.async_set(eid, st, {"friendly_name": name})
    await add_automation(hass, "panda_esl_alerts.yaml", {"entities": WATCH, **(inputs or {})})
    return calls


async def test_lists_active_entities_newest_first(hass, freezer):
    calls = await setup(hass)
    freezer.tick(timedelta(hours=2))
    hass.states.async_set("binary_sensor.front_door", "off", {"friendly_name": "Front door"})
    freezer.tick(timedelta(minutes=5))
    hass.states.async_set("binary_sensor.front_door", "on", {"friendly_name": "Front door"})
    freezer.tick(timedelta(minutes=25))
    _, data = await run(hass, calls)
    t = texts(data)
    assert t[:2] == ["Alerts", "3 active"]
    assert t[2:4] == ["Front door", "25m"]
    assert t.count("2h") == 2
    assert {"Back door lock", "Hall sensor battery low"} <= set(t)
    assert "Garage door" not in t and "Shed" not in t
    assert icons(data).count("alert") == 3
    assert icons(data)[0] == "alert-outline"
    assert data["payload"][0]["fill"] == "red"
    in_canvas(data, 360, 240)


async def test_all_clear(hass):
    calls = await setup(hass, states={e: ("off", e) for e in WATCH})
    _, data = await run(hass, calls)
    assert "All clear" in texts(data)
    assert "0 active" in texts(data)
    assert data["payload"][0]["fill"] == "black"
    assert "check-circle-outline" in icons(data)


async def test_custom_active_states(hass):
    calls = await setup(hass, {"active_states": ["off"]})
    _, data = await run(hass, calls)
    t = texts(data)
    assert "Garage door" in t and "Shed" in t and "Front door" not in t


async def test_overflow(hass):
    many = {f"binary_sensor.s{i}": ("on", f"Sensor {i}") for i in range(12)}
    install(hass, "panda_esl_alerts.yaml")
    calls = register_write(hass)
    for eid, (st, name) in many.items():
        hass.states.async_set(eid, st, {"friendly_name": name})
    await add_automation(hass, "panda_esl_alerts.yaml", {"entities": list(many), "max_items": 4})
    _, data = await run(hass, calls)
    assert texts(data)[-1] == "+9 more"
    assert icons(data).count("alert") == 3


@pytest.mark.parametrize("size,w,h", [("256x128", 256, 128), ("296x152", 296, 152), ("400x300", 400, 300)])
async def test_sizes(hass, size, w, h):
    calls = await setup(hass, {"display_size": size})
    _, data = await run(hass, calls)
    in_canvas(data, w, h)


async def test_emoji(hass):
    calls = await setup(hass, {"icon_style": "emoji"})
    _, data = await run(hass, calls)
    assert icons(data) == []
    assert images(data).count("26A0") == 4  # header glyph and three markers


async def test_state_change_writes(hass):
    calls = await setup(hass, {"settle_seconds": 0})
    hass.states.async_set("binary_sensor.shed", "on", {"friendly_name": "Shed"})
    await pump()
    assert len(calls) == 1


async def test_emoji_in_names_is_drawn_as_image(hass):
    calls = await setup(hass, states={"binary_sensor.front_door": ("on", "Front \U0001F6AA door"), **{e: ("off", e) for e in WATCH[1:]}})
    _, data = await run(hass, calls)
    assert "Front door" in texts(data)
    assert images(data) == ["1F6AA"]
    url = [e["url"] for e in visible(data) if e["type"] == "dlimg"][0]
    assert url == "https://cdn.jsdelivr.net/gh/hfg-gmuend/openmoji@15.1.0/color/72x72/1F6AA.png"
    in_canvas(data, 360, 240)


async def test_emoji_in_names_is_stripped_in_strip_mode(hass):
    calls = await setup(hass, {"emoji_mode": "strip"}, states={"binary_sensor.front_door": ("on", "Front \U0001F6AA door"), **{e: ("off", e) for e in WATCH[1:]}})
    _, data = await run(hass, calls)
    assert "Front door" in texts(data)
    assert images(data) == []
