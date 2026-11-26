"""Tests for blueprints/ledfx_playback.yaml."""
import asyncio
import shutil
from datetime import timedelta
from pathlib import Path

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

BP = Path(__file__).resolve().parents[1] / "blueprints/ledfx_playback.yaml"
MUSIC = "media_player.room"
OTHER = "media_player.other"
LEDFX = "media_player.ledfx_room"
POWER = "switch.psu"
CABINET = "light.cabinet"
TILES = "light.tiles"
LEAF = "light.leaf"
BUTTON = "button.preset"
SCENE = "scene.room_tmp"
OCCUPY = "automation.room_occupy"
SESSION = "input_boolean.ledfx_session"
AUTO = "automation.ledfx_room"

calls = []


async def pump(hass, n=400):
    for _ in range(n):
        await asyncio.sleep(0)


async def tick(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await pump(hass)


def ents(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def saw(domain, service, entity=None, step=None):
    for item_domain, item_service, data in calls:
        if (item_domain, item_service) != (domain, service):
            continue
        if step is not None and data.get("step") != step:
            continue
        if entity is not None and entity not in ents(data.get("entity_id")):
            continue
        return True
    return False


def count(domain, service, entity=None, step=None):
    found = 0
    for item_domain, item_service, data in calls:
        if (item_domain, item_service) != (domain, service):
            continue
        if step is not None and data.get("step") != step:
            continue
        if entity is not None and entity not in ents(data.get("entity_id")):
            continue
        found += 1
    return found


def record(hass):
    async def handler(call):
        calls.append((call.domain, call.service, dict(call.data)))
        if call.domain == "media_player" and call.service == "media_play":
            hass.states.async_set(LEDFX, "playing")
        elif call.domain == "media_player" and call.service == "media_pause":
            hass.states.async_set(LEDFX, "paused")
        elif call.domain == "media_player" and call.service == "turn_on":
            hass.states.async_set(LEDFX, "idle")

    for domain, service in (
        ("media_player", "media_play"),
        ("media_player", "media_pause"),
        ("media_player", "turn_on"),
        ("switch", "turn_on"),
        ("switch", "turn_off"),
        ("light", "turn_on"),
        ("light", "turn_off"),
        ("button", "press"),
        ("scene", "turn_on"),
        ("test", "note"),
    ):
        hass.services.async_register(domain, service, handler)


async def setup(hass, *, extra=None, states=None, minimal=False, players=None):
    calls.clear()
    dest = Path(hass.config.path("blueprints/automation/howels"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(BP, dest)
    record(hass)
    initial = {
        MUSIC: "idle",
        OTHER: "idle",
        LEDFX: "paused",
    }
    initial.update(states or {})
    for entity, state in initial.items():
        hass.states.async_set(entity, state)
    assert await async_setup_component(
        hass,
        "input_boolean",
        {"input_boolean": {"ledfx_session": {"name": "LedFX session"}}},
    )
    inputs = {
        "music_players": players or [MUSIC],
        "ledfx_player": LEDFX,
    }
    if not minimal:
        inputs.update(
            {
                "session_helper": SESSION,
                "suspend_automations": [OCCUPY],
                "stop_delay_seconds": 5,
                "settle_seconds": 2,
                "ledfx_ready_seconds": 0,
                "sync_on_start": False,
                "watchdog": False,
                "power_entities": [POWER],
                "lights_on": [CABINET],
                "lights_off": [CABINET],
                "refresh_lights": [TILES],
                "session_lights": [LEAF],
                "preset_buttons": [BUTTON],
                "restore_scenes": [SCENE],
                "power_off_on_stop": False,
                "ledfx_start_actions": [{"action": "test.note", "data": {"step": "snapshot"}}],
                "playback_start_actions": [{"action": "test.note", "data": {"step": "playback_start"}}],
                "playback_stop_actions": [{"action": "test.note", "data": {"step": "playback_stop"}}],
            }
        )
    inputs.update(extra or {})
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "id": "ledfx_room",
                    "alias": "LedFX room",
                    "use_blueprint": {"path": "howels/ledfx_playback.yaml", "input": inputs},
                },
                {
                    "id": "occupy",
                    "alias": "Room occupy",
                    "triggers": [{"trigger": "state", "entity_id": "input_boolean.ledfx_session"}],
                    "actions": [],
                },
            ]
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "on", hass.states.get(AUTO)
    calls.clear()


async def play(hass):
    hass.states.async_set(MUSIC, "playing")
    await pump(hass)


async def test_defaults_load_and_play_starts_paused_ledfx(hass, freezer):
    await setup(hass, minimal=True)
    await play(hass)
    assert saw("media_player", "media_play", LEDFX)
    assert hass.states.get(LEDFX).state == "playing"


async def test_playing_opens_a_session(hass, freezer):
    await setup(hass)
    await play(hass)

    assert saw("switch", "turn_on", POWER)
    assert saw("light", "turn_on", CABINET)
    assert saw("light", "turn_on", LEAF)
    assert saw("light", "turn_off", TILES)
    assert saw("light", "turn_on", TILES)
    assert saw("button", "press", BUTTON)
    assert saw("media_player", "media_play", LEDFX)
    assert saw("test", "note", step="snapshot")
    assert saw("test", "note", step="playback_start")
    assert not saw("scene", "turn_on", SCENE)
    assert not saw("media_player", "turn_on", LEDFX)
    assert hass.states.get(SESSION).state == "on"
    assert hass.states.get(OCCUPY).state == "off"


async def test_idle_and_off_ledfx_are_started(hass, freezer):
    await setup(hass, states={LEDFX: "idle"})
    await play(hass)
    assert saw("media_player", "media_play", LEDFX)
    assert not saw("media_player", "turn_on", LEDFX)
    assert count("test", "note", step="snapshot") == 1

    hass.states.async_set(MUSIC, "idle")
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 2)
    assert hass.states.get(SESSION).state == "off"

    calls.clear()
    hass.states.async_set(LEDFX, "off")
    await play(hass)
    assert saw("media_player", "turn_on", LEDFX)
    assert saw("media_player", "media_play", LEDFX)
    assert count("test", "note", step="snapshot") == 1


async def test_already_playing_does_not_snapshot_or_replay(hass, freezer):
    await setup(hass, states={LEDFX: "playing"})
    await play(hass)

    assert saw("switch", "turn_on", POWER)
    assert saw("light", "turn_on", CABINET)
    assert saw("test", "note", step="playback_start")
    assert not saw("media_player", "media_play")
    assert not saw("test", "note", step="snapshot")
    assert not saw("button", "press")
    assert not saw("light", "turn_on", LEAF)
    assert not saw("light", "turn_off", TILES)
    assert hass.states.get(SESSION).state == "off"
    assert hass.states.get(OCCUPY).state == "on"


async def test_attribute_update_does_not_run_again(hass, freezer):
    await setup(hass)
    await play(hass)
    calls.clear()

    hass.states.async_set(MUSIC, "playing", {"media_title": "a", "media_position": 12})
    await pump(hass)
    assert calls == []


async def test_short_gap_does_not_stop(hass, freezer):
    await setup(hass)
    await play(hass)
    hass.states.async_set(MUSIC, "idle")
    await tick(hass, freezer, 4)
    assert not saw("media_player", "media_pause")

    hass.states.async_set(MUSIC, "playing")
    await tick(hass, freezer, 10)
    assert not saw("media_player", "media_pause")
    assert not saw("scene", "turn_on")
    assert hass.states.get(SESSION).state == "on"


async def test_stop_after_delay_restores_the_room(hass, freezer):
    await setup(hass)
    await play(hass)
    hass.states.async_set(MUSIC, "idle")
    await tick(hass, freezer, 5)

    assert saw("media_player", "media_pause", LEDFX)
    assert not saw("scene", "turn_on", SCENE)
    assert hass.states.get(SESSION).state == "on"

    await tick(hass, freezer, 2)
    assert saw("light", "turn_off", CABINET)
    assert saw("scene", "turn_on", SCENE)
    assert saw("test", "note", step="playback_stop")
    assert not saw("switch", "turn_off", POWER)
    assert hass.states.get(SESSION).state == "off"
    assert hass.states.get(OCCUPY).state == "on"


async def test_power_is_turned_off_only_when_asked(hass, freezer):
    await setup(hass, extra={"power_off_on_stop": True})
    await play(hass)
    hass.states.async_set(MUSIC, "idle")
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 2)
    assert saw("switch", "turn_off", POWER)


async def test_other_player_still_playing_blocks_stop(hass, freezer):
    await setup(hass, players=[MUSIC, OTHER], states={OTHER: "playing"})
    await play(hass)
    hass.states.async_set(MUSIC, "idle")
    await tick(hass, freezer, 5)
    assert not saw("media_player", "media_pause")

    hass.states.async_set(OTHER, "idle")
    await tick(hass, freezer, 5)
    assert saw("media_player", "media_pause", LEDFX)


async def test_unavailable_player_blocks_stop(hass, freezer):
    await setup(hass, players=[MUSIC, OTHER], states={OTHER: "unavailable"})
    await play(hass)
    hass.states.async_set(MUSIC, "idle")
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 2)
    assert not saw("media_player", "media_pause")
    assert not saw("scene", "turn_on")
    assert hass.states.get(SESSION).state == "on"


async def test_buffering_does_not_stop(hass, freezer):
    await setup(hass, extra={"watchdog": True})
    await play(hass)
    hass.states.async_set(MUSIC, "buffering")
    await tick(hass, freezer, 70)
    assert not saw("media_player", "media_pause")
    assert hass.states.get(SESSION).state == "on"


async def test_paused_and_off_count_as_stopped(hass, freezer):
    await setup(hass)
    await play(hass)
    hass.states.async_set(MUSIC, "paused")
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 2)
    assert saw("media_player", "media_pause", LEDFX)
    assert hass.states.get(SESSION).state == "off"

    calls.clear()
    await play(hass)
    hass.states.async_set(MUSIC, "off")
    await tick(hass, freezer, 5)
    await tick(hass, freezer, 2)
    assert saw("media_player", "media_pause", LEDFX)
    assert saw("scene", "turn_on", SCENE)


async def test_buffering_during_settle_does_not_restore(hass, freezer):
    await setup(hass)
    await play(hass)
    hass.states.async_set(MUSIC, "idle")
    await tick(hass, freezer, 5)
    assert saw("media_player", "media_pause", LEDFX)

    hass.states.async_set(MUSIC, "buffering")
    await tick(hass, freezer, 2)

    assert not saw("scene", "turn_on")
    assert not saw("test", "note", step="playback_stop")
    assert count("media_player", "media_play", LEDFX) == 2
    assert hass.states.get(SESSION).state == "on"
    assert hass.states.get(OCCUPY).state == "off"


async def test_resume_during_settle_keeps_the_session(hass, freezer):
    await setup(hass)
    await play(hass)
    hass.states.async_set(MUSIC, "idle")
    await tick(hass, freezer, 5)
    assert saw("media_player", "media_pause", LEDFX)
    assert count("test", "note", step="snapshot") == 1

    hass.states.async_set(MUSIC, "playing")
    await pump(hass)

    assert not saw("scene", "turn_on")
    assert count("test", "note", step="snapshot") == 1
    assert count("media_player", "media_play", LEDFX) == 2
    assert count("button", "press", BUTTON) == 1
    assert hass.states.get(SESSION).state == "on"
    assert hass.states.get(OCCUPY).state == "off"
    assert not saw("test", "note", step="playback_stop")


async def test_watchdog_stops_a_missed_idle(hass, freezer):
    await setup(hass, extra={"watchdog": True}, states={MUSIC: "idle", LEDFX: "playing"})
    await tick(hass, freezer, 70)
    assert saw("media_player", "media_pause", LEDFX)
    assert not saw("scene", "turn_on", SCENE)

    await tick(hass, freezer, 2)
    assert saw("scene", "turn_on", SCENE)
    assert saw("test", "note", step="playback_stop")
    assert not saw("test", "note", step="snapshot")


async def test_watchdog_does_not_start_ledfx(hass, freezer):
    await setup(
        hass,
        extra={"watchdog": True},
        states={MUSIC: "playing", LEDFX: "paused"},
    )
    await tick(hass, freezer, 70)
    assert not saw("media_player", "media_play")
    assert not saw("test", "note", step="snapshot")
    assert hass.states.get(SESSION).state == "off"


async def test_boot_starts_when_music_is_already_playing(hass, freezer):
    await setup(
        hass,
        extra={"sync_on_start": True},
        states={MUSIC: "playing", LEDFX: "paused"},
    )
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await pump(hass)

    assert saw("media_player", "media_play", LEDFX)
    assert saw("test", "note", step="snapshot")
    assert not saw("test", "note", step="playback_start")
    assert hass.states.get(SESSION).state == "on"


async def test_boot_restores_an_open_session_without_the_stop_delay(hass, freezer):
    await setup(hass, extra={"sync_on_start": True}, states={MUSIC: "idle", LEDFX: "paused"})
    await hass.services.async_call(
        "input_boolean", "turn_on", {"entity_id": SESSION}, blocking=True
    )
    calls.clear()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await pump(hass)

    assert not saw("media_player", "media_pause")
    assert saw("scene", "turn_on", SCENE)
    assert saw("test", "note", step="playback_stop")
    assert hass.states.get(SESSION).state == "off"
    assert hass.states.get(OCCUPY).state == "on"


async def test_boot_waits_the_stop_delay_when_the_session_is_off(hass, freezer):
    await setup(hass, extra={"sync_on_start": True})
    hass.states.async_set(MUSIC, "idle")
    hass.states.async_set(LEDFX, "playing")
    calls.clear()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await pump(hass)
    assert not saw("media_player", "media_pause")
    assert not saw("scene", "turn_on")


async def test_ready_wait_plays_when_ledfx_appears(hass, freezer):
    await setup(hass, extra={"ledfx_ready_seconds": 5}, states={LEDFX: "unavailable"})
    await play(hass)
    assert saw("switch", "turn_on", POWER)
    assert not saw("media_player", "media_play")
    assert not saw("test", "note", step="snapshot")

    hass.states.async_set(LEDFX, "paused")
    await pump(hass)
    assert saw("media_player", "media_play", LEDFX)
    assert saw("test", "note", step="snapshot")
    assert hass.states.get(SESSION).state == "on"


async def test_unavailable_ledfx_is_left_alone_when_the_ready_time_is_zero(hass, freezer):
    await setup(hass, states={LEDFX: "unavailable"})
    await play(hass)
    assert saw("switch", "turn_on", POWER)
    assert saw("light", "turn_on", CABINET)
    assert not saw("media_player", "media_play")
    assert not saw("test", "note", step="snapshot")
    assert hass.states.get(SESSION).state == "off"
    assert hass.states.get(OCCUPY).state == "on"
