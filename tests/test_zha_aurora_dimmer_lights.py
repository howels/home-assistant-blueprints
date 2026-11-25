"""Tests for blueprints/zha_aurora_dimmer_lights.yaml: step events and absolute level events."""
import asyncio, shutil
from pathlib import Path
import pytest
from homeassistant.core import callback
from homeassistant.setup import async_setup_component

BP = Path(__file__).resolve().parents[1] / "blueprints/zha_aurora_dimmer_lights.yaml"

async def pump(hass, n=200):
    for _ in range(n):
        await asyncio.sleep(0)

async def setup(hass, with2=True, extra=None):
    d = Path(hass.config.path("blueprints/automation/howels")); d.mkdir(parents=True, exist_ok=True)
    shutil.copy(BP, d)
    calls = []
    async def h(call):
        calls.append((call.service, dict(call.data), call.data.get("entity_id")))
    for s in ("turn_on", "toggle"):
        hass.services.async_register("light", s, h)
    hass.services.async_register("system_log", "write", h)
    hass.states.async_set("light.a", "on", {"color_mode": "color_temp", "color_temp_kelvin": 4000, "min_color_temp_kelvin": 2000, "max_color_temp_kelvin": 6500})
    hass.states.async_set("light.b", "on", {"color_mode": "hs", "hs_color": [350.0, 80.0]})
    use = {"path": "howels/zha_aurora_dimmer_lights.yaml", "input": {"remote": "dev1", "light1": {"entity_id": ["light.a"]}}}
    use["input"].update(extra or {})
    if with2: use["input"]["light2"] = {"entity_id": "light.b"}
    assert await async_setup_component(hass, "automation", {"automation": [{"id": "k", "alias": "knob", "use_blueprint": use}]})
    await hass.async_block_till_done()
    return calls

def ev(hass, command, endpoint=1, params=None, args=None):
    data = {"device_id": "dev1", "command": command, "endpoint_id": endpoint, "params": params or {}, "args": args if args is not None else []}
    hass.bus.async_fire("zha_event", data)

async def test_toggle_and_endpoint(hass):
    calls = await setup(hass)
    ev(hass, "on", 1); ev(hass, "off", 2); await pump(hass)
    assert [(c[0], c[2]) for c in calls] == [("toggle", ["light.a"]), ("toggle", ["light.b"])]

async def test_step_up_down(hass):
    calls = await setup(hass)
    ev(hass, "step", 1, {"step_mode": "StepMode.Up", "step_size": 20}); ev(hass, "step", 1, {"step_mode": "StepMode.Down", "step_size": 8}); await pump(hass)
    assert [c[1]["brightness_step_pct"] for c in calls] == [5.0, -2.0]

async def test_burst_runs_in_parallel(hass):
    calls = await setup(hass)
    block = asyncio.Event()
    async def slow(call):
        calls.append(("slow", dict(call.data), None)); await block.wait()
    hass.services.async_register("light", "turn_on", slow)
    for _ in range(8): ev(hass, "step", 1, {"step_mode": "StepMode.Up", "step_size": 20})
    await pump(hass)
    assert len(calls) == 8   # all issued while the first is still pending
    block.set(); await pump(hass)

async def test_color_temp(hass):
    calls = await setup(hass)
    ev(hass, "step_color_temp", 1, {"step_mode": "StepMode.Up", "step_size": 10}); await pump(hass)
    assert calls[-1][1]["color_temp_kelvin"] == int(1000000 / (250 - 10))
    ev(hass, "step_color_temp", 1, {"step_mode": "StepMode.Down", "step_size": 9999}); await pump(hass)
    span = 1000000 / 2000 - 1000000 / 6500
    assert calls[-1][1]["color_temp_kelvin"] == int(1000000 / (250 + span / 10))
    hass.states.async_set("light.a", "on", {"color_mode": "color_temp", "color_temp_kelvin": 2100, "min_color_temp_kelvin": 2000, "max_color_temp_kelvin": 6500})
    ev(hass, "step_color_temp", 1, {"step_mode": "StepMode.Down", "step_size": 9999}); await pump(hass)
    assert calls[-1][1]["color_temp_kelvin"] == 2000

async def test_hue_and_mode_switch(hass):
    calls = await setup(hass)
    ev(hass, "step_color_temp", 2, {"step_mode": "StepMode.Up", "step_size": 40}); await pump(hass)
    assert calls[-1][1]["hs_color"] == [10, 100] or calls[-1][1]["hs_color"] == [10.0, 100]
    ev(hass, "move_saturation", 2); await pump(hass)
    assert calls[-1][1]["color_temp_kelvin"] == 3333
    ev(hass, "move_saturation", 1); await pump(hass)
    assert calls[-1][1]["hs_color"] == [0, 100]

async def test_unused_endpoint_and_logs(hass):
    calls = await setup(hass, with2=False)
    ev(hass, "on", 2); ev(hass, "step", 2, {"step_mode": "StepMode.Up", "step_size": 20}); await pump(hass)
    assert calls == []
    ev(hass, "attribute_updated", 1, args={"attribute_id": 0, "value": 1}); ev(hass, "press_type", 1, {"press_type": 2}); await pump(hass)
    assert [c[1]["message"] for c in calls] == ["entered mode 1", "mode 1 long click"]


async def test_brightness_cap_floor_and_sensitivity(hass):
    calls = await setup(hass)
    up = {"step_mode": "StepMode.Up", "step_size": 200}
    ev(hass, "step", 1, up); ev(hass, "step", 1, {**up, "step_size": 1}); await pump(hass)
    assert [c[1]["brightness_step_pct"] for c in calls] == [10.0, 1.0]

async def test_custom_sensitivity(hass):
    calls = await setup(hass, extra={"brightness_sensitivity": 0.5, "min_step": 2, "max_step": 4})
    up = {"step_mode": "StepMode.Up", "step_size": 6}
    ev(hass, "step", 1, up); ev(hass, "step", 1, {**up, "step_size": 1}); ev(hass, "step", 1, {**up, "step_size": 50}); await pump(hass)
    assert [c[1]["brightness_step_pct"] for c in calls] == [3.0, 2.0, 4.0]

async def test_colour_sensitivity_and_hue_cap(hass):
    calls = await setup(hass, extra={"colour_sensitivity": 2})
    ev(hass, "step_color_temp", 1, {"step_mode": "StepMode.Up", "step_size": 10}); await pump(hass)
    assert calls[-1][1]["color_temp_kelvin"] == int(1000000 / (250 - 20))
    hass.states.async_set("light.a", "on", {"color_mode": "hs", "hs_color": [100.0, 50.0]})
    ev(hass, "step_color_temp", 1, {"step_mode": "StepMode.Up", "step_size": 500}); await pump(hass)
    assert calls[-1][1]["hs_color"][0] == 136


# Absolute level events (move_to_level_with_on_off), the behaviour of the former Lutron toggle blueprint.

async def setup_level(hass, sens=3, transition=None, with2=False):
    extra = {"level_sensitivity": sens}
    if transition is not None:
        extra["level_transition"] = transition
    return await setup(hass, with2=with2, extra=extra)


def lev(hass, level, press=2, command="move_to_level_with_on_off", endpoint=1):
    hass.bus.async_fire("zha_event", {"device_id": "dev1", "command": command, "endpoint_id": endpoint, "params": {}, "args": [level, press]})


async def sweep(hass, sens):
    calls = await setup_level(hass, sens)
    for lv in range(0, 255):
        lev(hass, lv)
        await pump(hass, 30)
    return {c[1]["brightness"] for c in calls if c[0] == "turn_on"}


async def test_level_resolution_s3(hass):
    levels = await sweep(hass, 3)
    assert len(levels) == 255 and max(levels) == 254


async def test_level_resolution_s2(hass):
    levels = await sweep(hass, 2)
    assert len(levels) == 52 and all(l % 5 == 0 and l <= 255 for l in levels), sorted(levels)


async def test_level_resolution_s1(hass):
    levels = await sweep(hass, 1)
    assert len(levels) == 18 and all(l % 15 == 0 for l in levels), sorted(levels)


async def test_level_transition_default_and_custom(hass):
    calls = await setup_level(hass)
    lev(hass, 100); await pump(hass)
    assert calls[-1][1]["transition"] == 0.2 and calls[-1][1]["brightness"] == 100


async def test_level_custom_transition(hass):
    calls = await setup_level(hass, transition=0)
    lev(hass, 100); await pump(hass)
    assert calls[-1][1]["transition"] == 0


async def test_level_press_toggles_and_unknown_press_ignored(hass):
    calls = await setup_level(hass)
    lev(hass, 0, 7); lev(hass, 100, 5); lev(hass, 100, 2, command="stop"); await pump(hass)
    assert [c[0] for c in calls] == ["toggle"]


async def test_level_endpoint_routing(hass):
    calls = await setup_level(hass, with2=True)
    lev(hass, 100, 2, endpoint=1); lev(hass, 100, 2, endpoint=2); lev(hass, 100, 2, endpoint=3); await pump(hass)
    assert [c[2] for c in calls] == [["light.a"], "light.b", ["light.a"]] or [c[2] for c in calls] == [["light.a"], ["light.b"], ["light.a"]]


async def test_level_endpoint_two_unused_falls_back_to_first(hass):
    calls = await setup_level(hass, with2=False)
    lev(hass, 100, 2, endpoint=2); await pump(hass)
    assert calls[-1][2] == ["light.a"]


async def test_level_events_sent_in_arrival_order(hass):
    calls = await setup_level(hass)
    for lv in (50, 60, 70, 80):
        lev(hass, lv)
    await pump(hass)
    assert [c[1]["brightness"] for c in calls] == [50, 60, 70, 80]
