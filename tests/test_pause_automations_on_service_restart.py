"""Tests for blueprints/pause_automations_on_service_restart.yaml."""
import asyncio
import shutil
from datetime import timedelta
from pathlib import Path

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

BP = Path(__file__).resolve().parents[1] / "blueprints/pause_automations_on_service_restart.yaml"
SENSOR = "binary_sensor.service_running"
MEMORY = "input_text.paused"
KEEP = "automation.midi_keep"
ALSO = "automation.midi_also"
LEAVE = "automation.midi_leave"
CONTROLLER = "automation.pause_during_restart"


async def pump(hass, n=400):
    for _ in range(n):
        await asyncio.sleep(0)


async def tick(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await pump(hass)


def plain():
    async def handler(call):
        handler.calls.append(call)

    handler.calls = []
    return handler


async def setup(hass, freezer, restart, *, extra=None, leave_off=True):
    dest = Path(hass.config.path("blueprints/automation/howels"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(BP, dest)
    hass.services.async_register("test", "restart_bridge", restart)
    assert await async_setup_component(
        hass,
        "input_text",
        {"input_text": {"paused": {"name": "Paused", "max": 255, "initial": ""}}},
    )
    hass.states.async_set(SENSOR, "on")
    inputs = {
        "running_sensor": SENSOR,
        "memory": MEMORY,
        "automations": [KEEP, ALSO, LEAVE],
        "settle_seconds": 1,
        "resume_seconds": 2,
        "action_timeout_seconds": 30,
        "confirm_seconds": 0,
        "restart_actions": [{"action": "test.restart_bridge"}],
    }
    inputs.update(extra or {})
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "id": "pause",
                    "alias": "Pause during restart",
                    "use_blueprint": {
                        "path": "howels/pause_automations_on_service_restart.yaml",
                        "input": inputs,
                    },
                },
                {
                    "id": "keep",
                    "alias": "Midi keep",
                    "triggers": [{"trigger": "state", "entity_id": "input_boolean.unused"}],
                    "actions": [],
                },
                {
                    "id": "also",
                    "alias": "Midi also",
                    "triggers": [{"trigger": "state", "entity_id": "input_boolean.unused"}],
                    "actions": [],
                },
                {
                    "id": "leave",
                    "alias": "Midi leave",
                    "triggers": [{"trigger": "state", "entity_id": "input_boolean.unused"}],
                    "actions": [],
                },
            ]
        },
    )
    await hass.async_block_till_done()
    if leave_off:
        await hass.services.async_call(
            "automation", "turn_off", {"entity_id": LEAVE}, blocking=True
        )
        await hass.async_block_till_done()
    return inputs


async def test_down_keeps_them_off_and_up_restores_only_those_that_were_on(hass, freezer):
    restart = plain()
    await setup(hass, freezer, restart)

    hass.states.async_set(SENSOR, "off")
    await pump(hass)

    assert hass.states.get(KEEP).state == "off"
    assert hass.states.get(ALSO).state == "off"
    assert hass.states.get(LEAVE).state == "off"
    assert hass.states.get(MEMORY).state.startswith("110|d|")
    assert restart.calls == []

    await tick(hass, freezer, 120)
    assert hass.states.get(KEEP).state == "off"
    assert hass.states.get(MEMORY).state.startswith("110|d|")

    hass.states.async_set(SENSOR, "on")
    await pump(hass)
    await tick(hass, freezer, 1)
    assert len(restart.calls) == 1
    assert hass.states.get(KEEP).state == "off"
    assert "|r|" in hass.states.get(MEMORY).state

    await tick(hass, freezer, 2)
    assert hass.states.get(KEEP).state == "on"
    assert hass.states.get(ALSO).state == "on"
    assert hass.states.get(LEAVE).state == "off"
    assert hass.states.get(MEMORY).state == ""


async def test_restart_action_error_still_restores(hass, freezer):
    async def restart(_call):
        restart.calls += 1
        raise HomeAssistantError("ssh failed")

    restart.calls = 0
    await setup(hass, freezer, restart)
    hass.states.async_set(SENSOR, "unavailable")
    await pump(hass)
    assert hass.states.get(KEEP).state == "off"

    hass.states.async_set(SENSOR, "on")
    await tick(hass, freezer, 1)
    assert restart.calls == 1
    await tick(hass, freezer, 2)
    assert hass.states.get(KEEP).state == "on"
    assert hass.states.get(ALSO).state == "on"
    assert hass.states.get(LEAVE).state == "off"
    assert hass.states.get(MEMORY).state == ""


async def test_aborted_resume_is_restored_by_the_minute_check(hass, freezer):
    restart = plain()
    await setup(hass, freezer, restart)
    hass.states.async_set(SENSOR, "off")
    await pump(hass)
    hass.states.async_set(SENSOR, "on")
    await tick(hass, freezer, 1)
    assert "|r|" in hass.states.get(MEMORY).state
    assert hass.states.get(KEEP).state == "off"

    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": CONTROLLER}, blocking=True
    )
    await hass.services.async_call(
        "automation", "turn_on", {"entity_id": CONTROLLER}, blocking=True
    )
    await pump(hass)
    assert hass.states.get(KEEP).state == "off"
    assert len(restart.calls) == 1

    await tick(hass, freezer, 90)
    assert hass.states.get(KEEP).state == "on"
    assert hass.states.get(ALSO).state == "on"
    assert hass.states.get(LEAVE).state == "off"
    assert len(restart.calls) == 1


async def test_abandoned_restart_action_runs_again(hass, freezer):
    restart = plain()
    await setup(
        hass,
        freezer,
        restart,
        extra={"settle_seconds": 3600, "resume_seconds": 0, "action_timeout_seconds": 5},
    )
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": [KEEP, ALSO]}, blocking=True
    )
    await hass.services.async_call(
        "input_text",
        "set_value",
        {"entity_id": MEMORY, "value": "110|w|0"},
        blocking=True,
    )
    await tick(hass, freezer, 90)
    assert len(restart.calls) == 1
    assert hass.states.get(KEEP).state == "on"
    assert hass.states.get(ALSO).state == "on"
    assert hass.states.get(LEAVE).state == "off"
    assert hass.states.get(MEMORY).state == ""


async def test_home_assistant_start_restores_a_stored_mask(hass: HomeAssistant, freezer):
    restart = plain()
    await setup(
        hass,
        freezer,
        restart,
        extra={"settle_seconds": 3600, "resume_seconds": 30},
    )
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": [KEEP, ALSO]}, blocking=True
    )
    await hass.services.async_call(
        "input_text",
        "set_value",
        {"entity_id": MEMORY, "value": "110|r|0"},
        blocking=True,
    )
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await pump(hass)
    assert restart.calls == []
    assert hass.states.get(KEEP).state == "on"
    assert hass.states.get(ALSO).state == "on"
    assert hass.states.get(LEAVE).state == "off"
    assert hass.states.get(MEMORY).state == ""
