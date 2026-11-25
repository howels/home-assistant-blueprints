"""Tests for blueprints/wled-matrix-album-art.yaml.

A primary player supplies the picture. Fallback players are used in order when
the primary is not playing. Each panel gets its own host and image settings.
An absolute picture URL is sent unchanged. A path is prefixed.
"""
import asyncio
import shutil
from datetime import timedelta
from pathlib import Path

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

BP = Path(__file__).resolve().parents[1] / "blueprints/wled-matrix-album-art.yaml"
PRIMARY = "media_player.primary"
FALLBACK_A = "media_player.fallback_a"
FALLBACK_B = "media_player.fallback_b"


async def pump(hass, n=3000):
    for _ in range(n):
        await asyncio.sleep(0)


def panel(name, host, **extra):
    item = {
        "name": name,
        "host": host,
        "width": 64,
        "height": 64,
        "segment": 0,
        "saturation": 1.2,
        "contrast": 0.9,
        "sharpen": 0.5,
        "gamma": 0.5,
    }
    item.update(extra)
    return item


async def setup(hass, panels, fallbacks=None, prefix="https://ha.example", extra=None, replace_light_services=True):
    folder = Path(hass.config.path("blueprints/automation/howels"))
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(BP, folder)
    calls = []

    async def record(call):
        calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("ha_ddp2wled", "send_to_wled_ddp", record)
    hass.services.async_register("ha_ddp2wled", "stop_ddp_stream", record)
    if replace_light_services:
        hass.services.async_register("light", "turn_on", record)
        hass.services.async_register("light", "turn_off", record)
    for entity in (PRIMARY, FALLBACK_A, FALLBACK_B):
        hass.states.async_set(entity, "idle")
    inputs = {
        "primary_player": PRIMARY,
        "fallback_players": fallbacks or [],
        "picture_url_prefix": prefix,
        "panels": panels,
    }
    inputs.update(extra or {})
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "id": "album",
                    "alias": "Art BP test",
                    "use_blueprint": {
                        "path": "howels/wled-matrix-album-art.yaml",
                        "input": inputs,
                    },
                }
            ]
        },
    )
    await hass.async_block_till_done()
    return calls


def sends(calls):
    return [data for domain, service, data in calls if service == "send_to_wled_ddp"]


async def test_primary_is_sent_to_every_panel_and_paths_are_prefixed(hass):
    calls = await setup(
        hass,
        [
            panel("hub75", "panel-a.example"),
            panel("portal", "http://panel-b.example/info", width=128, height=128, contrast=1.1, gamma=0.6),
        ],
        fallbacks=[FALLBACK_A],
    )
    hass.states.async_set(FALLBACK_A, "playing", {"entity_picture": "https://cdn.example/other.jpg"})
    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/api/media_player_proxy/primary"})
    await pump(hass)

    sent = sends(calls)[-2:]
    assert [item["wled_host"] for item in sent] == ["panel-a.example", "panel-b.example"]
    assert {item["image_url"] for item in sent} == {"https://ha.example/api/media_player_proxy/primary"}
    wide = next(item for item in sent if item["wled_host"] == "panel-b.example")
    assert wide["width"] == 128
    assert wide["height"] == 128
    assert wide["contrast"] == 1.1
    assert wide["gamma"] == 0.6
    assert wide["saturation"] == 1.2


async def test_absolute_picture_is_not_prefixed_and_fallback_order_is_kept(hass):
    calls = await setup(
        hass,
        [panel("hub75", "panel-a.example")],
        fallbacks=[FALLBACK_A, FALLBACK_B],
    )
    hass.states.async_set(FALLBACK_B, "playing", {"entity_picture": "https://cdn.example/b.jpg"})
    await pump(hass)
    assert sends(calls)[-1]["image_url"] == "https://cdn.example/b.jpg"

    hass.states.async_set(FALLBACK_A, "playing", {"entity_picture": "/art/a"})
    await pump(hass)
    assert sends(calls)[-1]["image_url"] == "https://ha.example/art/a"

    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "http://images.example/primary.png"})
    await pump(hass)
    assert sends(calls)[-1]["image_url"] == "http://images.example/primary.png"


async def test_device_configuration_url_overrides_the_host(hass):
    entry = MockConfigEntry(domain="wled", data={"host": "ignored.example"})
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("wled", "aabbccddeeff")},
        name="Hub75",
        configuration_url="http://device-host.example",
    )
    calls = await setup(
        hass,
        [panel("hub75", "ignored.example", device=device.id)],
    )
    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/cover"})
    await pump(hass)
    assert sends(calls)[-1]["wled_host"] == "device-host.example"


def wled_device(hass, ident, url):
    entry = MockConfigEntry(domain="wled", data={"host": ident})
    entry.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("wled", ident)},
        name=ident,
        configuration_url=url,
    )


async def test_stopping_clears_every_panel_and_turns_off_the_device_light(hass, freezer):
    device = wled_device(hass, "hub75", "http://panel-a.example")
    er.async_get(hass).async_get_or_create(
        "light",
        "wled",
        "hub75-main",
        suggested_object_id="panel_a_main",
        device_id=device.id,
    )
    calls = await setup(
        hass,
        [
            panel("hub75", "ignored.example", device=device.id, turn_on=False, turn_off=True),
            panel("portal", "portal.example", turn_on=False, turn_off=True),
        ],
    )
    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/cover"})
    await pump(hass)
    hass.states.async_set(PRIMARY, "idle")
    await pump(hass)
    freezer.tick(timedelta(seconds=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    hosts = [data["wled_host"] for domain, service, data in calls if service == "stop_ddp_stream"]
    assert hosts[-2:] == ["panel-a.example", "portal.example"]
    offs = [data["entity_id"] for domain, service, data in calls if service == "turn_off"]
    assert offs == [["light.panel_a_main"]]


def stops(calls):
    return [data["wled_host"] for domain, service, data in calls if service == "stop_ddp_stream"]


async def test_position_updates_do_not_restart_the_run(hass):
    calls = await setup(hass, [panel("hub75", "panel-a.example", turn_on=False, turn_off=False)])
    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/cover", "media_position": 1})
    await pump(hass)
    sent_before = len(sends(calls))
    stops_before = len(stops(calls))
    assert sent_before == 1

    for position in range(2, 8):
        hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/cover", "media_position": position})
        await pump(hass)
    assert len(sends(calls)) == sent_before
    assert len(stops(calls)) == stops_before


async def test_new_picture_is_sent_without_clearing(hass):
    calls = await setup(hass, [panel("hub75", "panel-a.example", turn_on=False, turn_off=False)])
    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/one"})
    await pump(hass)
    assert stops(calls) == ["panel-a.example"]
    assert sends(calls)[-1]["image_url"] == "https://ha.example/one"

    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/two"})
    await pump(hass)
    assert sends(calls)[-1]["image_url"] == "https://ha.example/two"
    assert stops(calls) == ["panel-a.example"]

    hass.states.async_set(PRIMARY, "paused", {"entity_picture": "/two"})
    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/two"})
    await pump(hass)
    assert len(stops(calls)) == 2


async def test_picture_is_sent_once_per_run_not_every_second(hass, freezer):
    calls = await setup(hass, [panel("hub75", "panel-a.example", turn_on=False, turn_off=False)])
    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/one"})
    await pump(hass)
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await pump(hass)
    assert len(sends(calls)) == 1


async def test_send_timeout_and_image_ranges_are_applied(hass):
    calls = await setup(
        hass,
        [panel("hub75", "panel-a.example", turn_on=False, turn_off=False, sharpen=1, gamma=2)],
        extra={"send_timeout": 3},
    )
    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/one"})
    await pump(hass)
    sent = sends(calls)[-1]
    assert sent["timeout"] == 3
    assert sent["sharpen"] == 1
    assert sent["gamma"] == 2


async def test_keepalive_is_taken_from_the_panel(hass):
    calls = await setup(hass, [panel("pixoo", "pixoo.example", keepalive=0, turn_on=False, turn_off=False)])
    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/cover"})
    await pump(hass)
    assert sends(calls)[-1]["keepalive_seconds"] == 0
    assert [service for domain, service, data in calls if domain == "light"] == []


async def test_session_restores_only_lights_that_were_off(hass, freezer):
    from homeassistant.components import light
    from homeassistant.components.light import ColorMode, LightEntity

    assert await async_setup_component(hass, "light", {})
    assert await async_setup_component(hass, "scene", {})
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"matrices": None}})

    class Lamp(LightEntity):
        _attr_should_poll = False

        def __init__(self, name, on):
            self._attr_name = name
            self._attr_unique_id = name
            self._attr_is_on = on
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF if on else None

        async def async_turn_on(self, **kw):
            self._attr_is_on = True
            self._attr_color_mode = ColorMode.ONOFF
            self.async_write_ha_state()

        async def async_turn_off(self, **kw):
            self._attr_is_on = False
            self._attr_color_mode = None
            self.async_write_ha_state()

    owned, kept = Lamp("owned", False), Lamp("kept", True)
    await hass.data[light.DATA_COMPONENT].async_add_entities([owned, kept])
    await hass.async_block_till_done()
    device = wled_device(hass, "hub", "http://wled.example")
    registry = er.async_get(hass)
    registry.async_update_entity("light.owned", device_id=device.id)
    registry.async_update_entity("light.kept", device_id=device.id)

    await setup(
        hass,
        [panel("hub", "ignored.example", device=device.id, turn_on=True, turn_off=True)],
        extra={"light_session": "input_boolean.matrices", "session_name": "matrices"},
        replace_light_services=False,
    )
    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/cover"})
    await pump(hass)
    assert hass.states.get("light.owned").state == "on"
    assert hass.states.get("light.kept").state == "on"
    assert hass.states.get("input_boolean.matrices").state == "on"

    hass.states.async_set(PRIMARY, "playing", {"entity_picture": "/next"})
    await pump(hass)
    assert hass.states.get("light.owned").state == "on"

    hass.states.async_set(PRIMARY, "idle")
    await pump(hass)
    freezer.tick(timedelta(seconds=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("light.owned").state == "off"
    assert hass.states.get("light.kept").state == "on"
    assert hass.states.get("input_boolean.matrices").state == "off"
