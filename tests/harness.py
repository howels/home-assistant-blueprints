"""Test harness for blueprints/room_occupancy.yaml.

Runs the blueprint and the store sensor from examples/occupancy_scene_store.yaml in a real Home
Assistant core with fake lights. Setup, from the repository root:

    uv venv /tmp/hav --python 3.14
    uv pip install --python /tmp/hav/bin/python homeassistant pytest-homeassistant-custom-component
    cd tests && /tmp/hav/bin/python -m pytest -q -p no:cacheprovider

Time is frozen. Tests advance it with Env.tick and yield to the event loop with
Env.pump. They avoid hass.async_block_till_done, which waits for delay actions.
"""
import asyncio
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

import yaml
from homeassistant.components import light
from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import CoreState, State
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

REPO = Path(__file__).resolve().parents[1]
RESTORE_FILE = Path(tempfile.gettempdir()) / "room_occupancy_restore.json"


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda l, s, n: None)


def store_config():
    return yaml.load((REPO / "examples/occupancy_scene_store.yaml").read_text(), _Loader)[0]


class FakeLight(LightEntity):
    _attr_should_poll = False
    _attr_min_color_temp_kelvin = 2000
    _attr_max_color_temp_kelvin = 6500

    def __init__(self, name, modes):
        self._attr_name = name
        self._attr_unique_id = name
        self._attr_supported_color_modes = set(modes)
        self._attr_is_on = False
        self._attr_brightness = None
        self._attr_color_mode = None
        self.log = []

    def set_available(self, value):
        self._attr_available = value
        self.async_write_ha_state()

    async def async_turn_on(self, **kw):
        self.log.append(("on", kw))
        self._attr_is_on = True
        self._attr_brightness = kw.get("brightness", self._attr_brightness or 255)
        if "color_temp_kelvin" in kw:
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_color_temp_kelvin = kw["color_temp_kelvin"]
        elif "hs_color" in kw:
            self._attr_color_mode = ColorMode.HS
            self._attr_hs_color = tuple(kw["hs_color"])
        elif self._attr_color_mode is None:
            self._attr_color_mode = sorted(self._attr_supported_color_modes)[0]
        self.async_write_ha_state()

    async def async_turn_off(self, **kw):
        self.log.append(("off", kw))
        self._attr_is_on = False
        self._attr_color_mode = None
        self._attr_brightness = None
        self.async_write_ha_state()


class Env:
    def __init__(self, hass, freezer):
        self.hass = hass
        self.freezer = freezer

    async def pump(self, n=300):
        for _ in range(n):
            await asyncio.sleep(0)

    async def tick(self, seconds):
        self.freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(self.hass)
        await self.pump()

    def s(self, e):
        return self.hass.states.get(e)

    async def setsensor(self, e, v):
        self.hass.states.async_set(e, v)
        await self.pump()

    @property
    def store(self):
        st = self.s("sensor.occupancy_scene_store")
        return (st.attributes.get("rooms") if st else None) or {}


async def build(hass, freezer, restore=None, inputs=None, auto_extra=None, starting=False, minimal=False):
    bp = Path(hass.config.path("blueprints/automation/howels"))
    bp.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "blueprints/room_occupancy.yaml", bp)

    if restore is not None:
        mock_restore_cache_with_extra_data(
            hass,
            [(State.from_dict(restore["state"]), restore["extra_data"])],
        )
    assert await async_setup_component(hass, "template", {"template": [store_config()]})
    assert await async_setup_component(hass, "light", {})
    comp = hass.data[light.DATA_COMPONENT]
    lights = [
        FakeLight("lamp ct", [ColorMode.COLOR_TEMP]),
        FakeLight("lamp hs", [ColorMode.HS]),
        FakeLight("lamp bri", [ColorMode.BRIGHTNESS]),
    ]
    await comp.async_add_entities(lights)
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"entered": None, "left": None}})
    assert await async_setup_component(hass, "input_select", {"input_select": {"preset": {"options": ["a", "b"], "initial": "a"}}})
    assert await async_setup_component(
        hass,
        "scene",
        {"scene": [{"platform": "homeassistant", "states": [{
            "name": "default_test",
            "entities": {
                "light.lamp_ct": {"state": "on", "brightness": 100, "color_mode": "color_temp", "color_temp_kelvin": 2700},
                "light.lamp_hs": {"state": "off"},
                "light.lamp_bri": {"state": "on", "brightness": 50},
            },
        }]}]},
    )
    for e in ("binary_sensor.motion", "binary_sensor.mmwave"):
        hass.states.async_set(e, "off")
    base = {
        "room_name": "Study",
        "sensors": ["binary_sensor.motion"],
        "hold_only_sensors": ["binary_sensor.mmwave"],
        "clear_delay": {"hours": 0, "minutes": 0, "seconds": 30},
        "snapshot_entities": ["light.lamp_ct", "light.lamp_hs", "light.lamp_bri", "input_select.preset"],
        "default_scene": "scene.default_test",
        "settle_time": 1,
    }
    if minimal:
        base = {k: base[k] for k in ("room_name", "sensors", "snapshot_entities")}
    base.update(inputs or {})
    cfg = {"id": "room1", "alias": "Study occupancy", "use_blueprint": {"path": "howels/room_occupancy.yaml", "input": base}}
    cfg.update(auto_extra or {})
    if starting:
        hass.set_state(CoreState.starting)
    assert await async_setup_component(hass, "automation", {"automation": [cfg]})
    hass.set_state(CoreState.running)
    await hass.async_block_till_done()
    env = Env(hass, freezer)
    env.lights = {l.entity_id: l for l in lights}
    return env
