"""Tests for the unchanged-image check shared by the PANDA ESL blueprints."""
import pytest

import test_panda_esl_agenda as agenda
import test_panda_esl_alerts as alerts
import test_panda_esl_calendar as calendar
import test_panda_esl_todo as todo
import test_panda_esl_weather as weather
from panda_helpers import pump

HELPER = "input_text.label_last_sent"
FORCE = "button.force_label"


@pytest.fixture(autouse=True)
def midday(freezer):
    freezer.move_to("2026-11-25 20:00:00+00:00")


async def _setup(name, hass, inputs):
    module = {"agenda": agenda, "alerts": alerts, "calendar": calendar, "todo": todo, "weather": weather}[name]
    result = await module.setup(hass, inputs=inputs)
    calls = result[0] if isinstance(result, tuple) else result
    return calls, "automation.weather_label" if name == "weather" else "automation.label"


@pytest.fixture
def helper(hass):
    """An input_text stand-in that records set_value calls."""
    sets = []

    async def set_value(call):
        sets.append(call.data["value"])
        hass.states.async_set(HELPER, call.data["value"])

    hass.services.async_register("input_text", "set_value", set_value)
    hass.states.async_set(HELPER, "")
    return sets


async def trigger(hass, entity):
    await hass.services.async_call(
        "automation", "trigger", {"entity_id": entity, "skip_condition": True}, blocking=False
    )
    await pump()
    await hass.async_block_till_done()


NAMES = ["agenda", "alerts", "calendar", "todo", "weather"]


@pytest.mark.parametrize("name", NAMES)
async def test_identical_payload_is_written_once(hass, helper, name):
    calls, entity = await _setup(name, hass, {"sent_helper": HELPER, "show_time": False} if name == "weather" else {"sent_helper": HELPER})
    await trigger(hass, entity)
    assert len(calls) == 1
    assert len(helper) == 1 and len(helper[0]) == 32
    await trigger(hass, entity)
    await trigger(hass, entity)
    assert len(calls) == 1
    assert len(helper) == 1


@pytest.mark.parametrize("name", NAMES)
async def test_changed_hash_is_written_again(hass, helper, name):
    calls, entity = await _setup(name, hass, {"sent_helper": HELPER})
    await trigger(hass, entity)
    hass.states.async_set(HELPER, "0" * 32)
    await trigger(hass, entity)
    assert len(calls) == 2
    assert helper[0] == helper[1]


@pytest.mark.parametrize("name", NAMES)
async def test_force_push_input_writes_every_run(hass, helper, name):
    calls, entity = await _setup(name, hass, {"sent_helper": HELPER, "force_push": True})
    await trigger(hass, entity)
    await trigger(hass, entity)
    assert len(calls) == 2


@pytest.mark.parametrize("name", NAMES)
async def test_force_entity_writes_once_when_pressed(hass, helper, name):
    calls, entity = await _setup(name, hass, {"sent_helper": HELPER, "force_entities": [FORCE]})
    hass.states.async_set(FORCE, "unknown")
    await trigger(hass, entity)
    assert len(calls) == 1
    hass.states.async_set(FORCE, "2026-11-25T20:00:00+00:00")
    await hass.async_block_till_done()
    await pump()
    await hass.async_block_till_done()
    assert len(calls) == 2
    await trigger(hass, entity)
    assert len(calls) == 2


@pytest.mark.parametrize("name", NAMES)
async def test_dry_run_never_skips_or_stores(hass, helper, name):
    calls, entity = await _setup(name, hass, {"sent_helper": HELPER, "dry_run": True})
    await trigger(hass, entity)
    await trigger(hass, entity)
    assert len(calls) == 2
    assert helper == []


@pytest.mark.parametrize("name", NAMES)
async def test_without_a_helper_every_run_writes(hass, helper, name):
    calls, entity = await _setup(name, hass, {})
    await trigger(hass, entity)
    await trigger(hass, entity)
    assert len(calls) == 2
    assert helper == []


async def test_helper_failure_does_not_stop_the_run(hass):
    calls, entity = await _setup("todo", hass, {"sent_helper": "input_text.missing"})
    await trigger(hass, entity)
    await trigger(hass, entity)
    assert len(calls) == 2


async def test_weather_time_defeats_the_check_until_hidden(hass, helper, freezer):
    calls, entity = await _setup("weather", hass, {"sent_helper": HELPER})
    await trigger(hass, entity)
    freezer.tick(60)
    await trigger(hass, entity)
    assert len(calls) == 2
    clocks = [e["value"] for _, d in calls for e in d["payload"] if e.get("anchor") == "rm" and e.get("value", "")[:1].isdigit() and ":" in e["value"]]
    assert len(set(clocks)) == 2


async def test_weather_without_time_is_stable(hass, helper, freezer):
    calls, entity = await _setup("weather", hass, {"sent_helper": HELPER, "show_time": False})
    await trigger(hass, entity)
    freezer.tick(600)
    await trigger(hass, entity)
    assert len(calls) == 1
