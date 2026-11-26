"""Tests for blueprints/ha_midi_smc_mixer.yaml.

The blueprint runs in a real Home Assistant core with the MQTT integration mocked. A bridge device is
registered with the identifier that ha-midi publishes, and the fader entities are attached to it.
Services of lights and media players are replaced by recorders. Time is frozen and advanced with tick().
"""
import asyncio
import itertools
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    async_fire_mqtt_message,
    async_fire_time_changed,
    async_fire_time_changed_exact,
)

BP = Path(__file__).resolve().parents[1] / "blueprints/ha_midi_smc_mixer.yaml"
IDENT = "ha-midi-bridge_sincosinco_smc_mixer_master_161"
PREFIX = "ha-midi/ha-midi-bridge/sincosinco_smc_mixer_master_161"
PRIVATE = "ha-midi/ha-midi-bridge/sincosinco_smc_mixer_private_160"
FADER = "number.ha_midi_bridge_sinco_smc_mixer_master_pitch_bend_channel_{}"

LIGHT_SERVICES = ("turn_on", "turn_off", "toggle")
PLAYER_SERVICES = (
    "volume_set", "media_play", "media_pause", "media_play_pause", "media_next_track",
    "media_previous_track", "volume_mute", "media_seek", "select_source",
)


class Env:
    def __init__(self, hass, freezer, mqtt_mock, device_id):
        self.hass, self.freezer, self.mqtt, self.device_id = hass, freezer, mqtt_mock, device_id
        self.calls = []
        self.logs = []
        self.exact = False

    async def pump(self, n=300):
        for _ in range(n):
            await asyncio.sleep(0)

    async def tick(self, seconds):
        self.freezer.tick(timedelta(seconds=seconds))
        # async_fire_time_changed treats the clock as 0.5 s later. Sampling tests need the exact time.
        (async_fire_time_changed_exact if self.exact else async_fire_time_changed)(self.hass)
        await self.pump()

    async def fire(self, leaf, payload, prefix=PREFIX, fader=True):
        """Publish a state topic. A fader message also updates the fader number entity."""
        if fader and leaf.startswith("pb_"):
            self.hass.states.async_set(FADER.format(leaf[3:]), payload)
        async_fire_mqtt_message(self.hass, f"{prefix}/{leaf}/state", payload)
        await self.pump()

    async def press(self, note, prefix=PREFIX):
        await self.fire(f"button_state_{note:03d}_00", "ON", prefix)
        await self.fire(f"button_state_{note:03d}_00", "OFF", prefix)

    def calls_of(self, name):
        return [c for c in self.calls if c[0] == name]

    def led(self, notes=None):
        """Key light publishes as (note, payload), in order. notes limits the result to a range."""
        out = []
        for call in self.mqtt.async_publish.call_args_list:
            topic, payload = call.args[0], call.args[1]
            if topic.startswith(PREFIX + "/button_light_") and topic.endswith("_00/set"):
                out.append((int(topic.split("button_light_")[1][:3]), payload))
        return [o for o in out if notes is None or o[0] in notes]


_COPIES = itertools.count()


@pytest.fixture(autouse=True)
def remove_mixer_copies(hass):
    """Each setup copies the blueprint into its own folder. conftest.py removes only the shared howels folder."""
    yield
    for d in Path(hass.config.path("blueprints/automation")).glob("midi_smc_*"):
        shutil.rmtree(d, ignore_errors=True)


async def setup(hass, freezer, mqtt_mock, inputs=None, light_state=None, players=None):
    # A folder per setup. The shared howels folder is removed by conftest.py after every test, and a
    # blueprint removed while an automation loads it produces "Unable to find" and a failed test.
    folder = f"midi_smc_{next(_COPIES)}"
    d = Path(hass.config.path(f"blueprints/automation/{folder}"))
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(BP, d)

    entry = hass.config_entries.async_entries("mqtt")[0]
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("mqtt", IDENT)}, name="HA-MIDI Bridge SINCO SMC-Mixer-Master"
    )
    ents = er.async_get(hass)
    for n in range(8):
        ents.async_get_or_create(
            "number", "mqtt", f"{IDENT}_pb_{n}", suggested_object_id=FADER.format(n).split(".")[1],
            config_entry=entry, device_id=device.id,
        )
        hass.states.async_set(FADER.format(n), "unknown")

    env = Env(hass, freezer, mqtt_mock, device.id)

    async def record(call):
        env.calls.append((f"{call.domain}.{call.service}", dict(call.data)))

    for s in LIGHT_SERVICES:
        hass.services.async_register("light", s, record)
    for s in PLAYER_SERVICES:
        hass.services.async_register("media_player", s, record)
    hass.services.async_register("system_log", "write", record)

    hass.states.async_set("light.lamp", "on", {"min_color_temp_kelvin": 2000, "max_color_temp_kelvin": 6500,
                                                  "color_temp_kelvin": 4000, "hs_color": [120.0, 50.0]})
    hass.states.async_set("light.strip", "off")
    hass.states.async_set("media_player.amp", "paused", {
        "volume_level": 0.5, "is_volume_muted": False, "source": "PC",
        "source_list": ["PC", "TV", "Radio"], "media_position": 100, "media_duration": 3000,
    })
    hass.states.async_set("media_player.cast", "idle", {"volume_level": 0.2})
    for entity_id, (state, attrs) in (players or {}).items():
        hass.states.async_set(entity_id, state, attrs)
    if light_state:
        for entity_id, (state, attrs) in light_state.items():
            hass.states.async_set(entity_id, state, attrs)

    base = {
        "device": device.id,
        "media_players": ["media_player.amp"],
        "strip_1_targets": ["light.lamp"],
        "strip_2_targets": ["media_player.amp", "light.strip"],
        "strip_3_targets": ["media_player.cast"],
    }
    base.update(inputs or {})
    cfg = {"automation": [{"id": "mixer", "alias": "mixer", "use_blueprint": {"path": f"{folder}/ha_midi_smc_mixer.yaml", "input": base}}]}
    assert await async_setup_component(hass, "automation", cfg)
    await env.pump()
    assert hass.states.get("automation.mixer").state == "on"
    return env


@pytest.fixture
async def env(hass, freezer, mqtt_mock):
    return await setup(hass, freezer, mqtt_mock)


async def test_loads_with_all_defaults(hass, env):
    state = hass.states.get("automation.mixer")
    assert state.state == "on"
    assert state.attributes.get("last_triggered") is None


# ---- faders ---------------------------------------------------------------------------------------------------

async def test_fader_sets_light_brightness(env):
    await env.fire("pb_0", "40")
    await env.tick(0.2)
    assert env.calls_of("light.turn_on")[-1][1]["brightness_pct"] == 40
    await env.fire("pb_0", "0")
    await env.tick(0.2)
    assert env.calls_of("light.turn_off")


async def test_fader_function_hue_colour_temp_and_saturation(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_fader": "hue"})
    await env.fire("pb_0", "50")
    await env.tick(0.2)
    assert env.calls[-1][1]["hs_color"] == [180.0, 50.0]


async def test_fader_colour_temp_uses_light_range(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_fader": "colour_temp"})
    await env.fire("pb_0", "50")
    await env.tick(0.2)
    assert env.calls[-1][1]["color_temp_kelvin"] == 4250


async def test_fader_colour_temp_via_rgb(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_fader": "colour_temp_rgb"})
    await env.fire("pb_0", "0")
    await env.tick(0.2)
    assert env.calls[-1][1]["rgb_color"] == [255, 137, 14]
    assert "color_temp_kelvin" not in env.calls[-1][1]
    await env.fire("pb_0", "50")
    await env.tick(0.2)
    assert env.calls[-1][1]["rgb_color"] == [255, 212, 177]
    await env.fire("pb_0", "100")
    await env.tick(0.2)
    assert env.calls[-1][1]["rgb_color"] == [255, 254, 250]


async def test_fader_saturation_keeps_hue(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_fader": "saturation"})
    await env.fire("pb_0", "75")
    await env.tick(0.2)
    assert env.calls[-1][1]["hs_color"] == [120.0, 75.0]


async def test_stale_fader_event_is_ignored(hass, env):
    hass.states.async_set(FADER.format(0), "70")
    async_fire_mqtt_message(hass, f"{PREFIX}/pb_0/state", "40")
    await env.tick(0.2)
    assert not env.calls_of("light.turn_on")


async def test_unused_fader_and_none_function_do_nothing(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_fader": "none"})
    await env.fire("pb_0", "40")
    await env.fire("pb_5", "40")
    await env.tick(0.2)
    assert env.calls == []


async def test_fader_raises_volume_slowly(hass, env):
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.2})
    await env.fire("pb_2", "80")
    await env.tick(0.2)
    levels = [c[1]["volume_level"] for c in env.calls_of("media_player.volume_set")]
    assert levels == [0.22]
    for _ in range(3):
        await env.tick(0.5)
    levels = [c[1]["volume_level"] for c in env.calls_of("media_player.volume_set")]
    assert levels == [0.22, 0.24, 0.26, 0.28]


async def test_fader_lowers_volume_quickly(hass, env):
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.8})
    await env.fire("pb_2", "20")
    await env.tick(0.2)
    for _ in range(5):
        await env.tick(0.5)
    levels = [c[1]["volume_level"] for c in env.calls_of("media_player.volume_set")]
    assert levels == [0.6, 0.4, 0.2]


async def test_ramp_stops_at_target(hass, env):
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.2})
    await env.fire("pb_2", "25")
    await env.tick(0.2)
    for _ in range(5):
        await env.tick(0.5)
    levels = [c[1]["volume_level"] for c in env.calls_of("media_player.volume_set")]
    assert levels == [0.22, 0.24, 0.25]


async def test_new_fader_position_replaces_ramp(hass, env):
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.2})
    await env.fire("pb_2", "90")
    await env.tick(0.2)
    await env.tick(0.5)
    assert len(env.calls_of("media_player.volume_set")) == 2
    await env.fire("pb_2", "10")
    for _ in range(4):
        await env.tick(0.5)
    levels = [c[1]["volume_level"] for c in env.calls_of("media_player.volume_set")]
    assert levels[:2] == [0.22, 0.24]
    # The old ramp stops. The new ramp lowers from the player's reported 0.2 to 0.1.
    assert levels[-1] == 0.1
    assert max(levels[2:]) < 0.2


async def test_fader_burst_runs_one_ramp(hass, env):
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.2})
    for v in range(50, 91, 2):
        await env.fire("pb_2", str(v))
    await env.tick(0.2)
    levels = [c[1]["volume_level"] for c in env.calls_of("media_player.volume_set")]
    assert levels == [0.22]


async def test_max_volume_caps_fader(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"max_volume": 50})
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.45})
    await env.fire("pb_2", "100")
    await env.tick(0.2)
    for _ in range(4):
        await env.tick(0.5)
    levels = [c[1]["volume_level"] for c in env.calls_of("media_player.volume_set")]
    assert levels == [0.47, 0.49, 0.5]


async def test_players_that_are_off_are_skipped(hass, env):
    hass.states.async_set("media_player.cast", "off", {})
    await env.fire("pb_2", "80")
    await env.tick(0.2)
    await env.tick(0.5)
    assert not env.calls_of("media_player.volume_set")



# ---- fader sampling -------------------------------------------------------------------------------------------

def align(env):
    """Start on a whole second so that every sampling interval that divides 1000 ms has a known boundary."""
    env.freezer.move_to("2026-11-25 12:00:00+00:00")
    env.exact = True


async def test_fader_burst_sends_only_the_latest_light_position(env):
    align(env)
    for v in range(10, 100, 10):
        await env.fire("pb_0", str(v))
    await env.tick(0.2)
    assert [c[1]["brightness_pct"] for c in env.calls_of("light.turn_on")] == [90]


async def test_moving_fader_updates_lights_once_per_interval(env):
    align(env)
    for v in range(1, 51):                        # a message every 20 ms for one second
        await env.fire("pb_0", str(v * 2))
        await env.tick(0.02)
    await env.tick(0.2)
    levels = [c[1]["brightness_pct"] for c in env.calls_of("light.turn_on")]
    assert 8 <= len(levels) <= 12                 # about one command per 100 ms, not fifty
    assert levels == sorted(levels)
    assert levels[-1] == 100


async def test_fader_that_stops_gets_its_final_position(env):
    align(env)
    for v in (20, 40, 60):
        await env.fire("pb_0", str(v))
        await env.tick(0.03)
    await env.tick(0.3)
    assert env.calls_of("light.turn_on")[-1][1]["brightness_pct"] == 60


async def test_sampling_interval_input_is_honoured(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"fader_debounce": 500})
    align(env)
    await env.fire("pb_0", "40")
    await env.tick(0.3)
    assert not env.calls_of("light.turn_on")
    await env.tick(0.3)
    assert env.calls_of("light.turn_on")[-1][1]["brightness_pct"] == 40


async def test_volume_ramp_waits_for_the_fader_to_be_still(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"fader_debounce": 400})
    align(env)
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.2})
    await env.fire("pb_2", "80")
    await env.tick(0.2)
    await env.fire("pb_2", "85")
    await env.tick(0.3)
    assert not env.calls_of("media_player.volume_set")     # the second message restarted the wait
    await env.tick(0.3)
    assert [c[1]["volume_level"] for c in env.calls_of("media_player.volume_set")] == [0.22]

# ---- dials ----------------------------------------------------------------------------------------------------

async def test_dial_steps_light_brightness(env):
    await env.fire("cc_016_00", "1")
    await env.tick(0.3)
    await env.fire("cc_016_00", "65")
    await env.tick(0.3)
    await env.fire("cc_016_00", "3")
    await env.tick(0.3)
    steps = [c[1]["brightness_step_pct"] for c in env.calls_of("light.turn_on")]
    assert steps == [5, -5, 15]


async def test_dial_steps_volume_up_less_than_down(hass, env):
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.5})
    await env.fire("cc_018_00", "1")
    await env.fire("cc_018_00", "65")
    await env.fire("cc_018_00", "66")
    levels = [c[1]["volume_level"] for c in env.calls_of("media_player.volume_set")]
    assert levels == [0.51, 0.48, 0.46]


async def test_dial_volume_respects_maximum_and_floor(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"max_volume": 40})
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.395})
    await env.fire("cc_018_00", "5")
    assert env.calls_of("media_player.volume_set")[-1][1]["volume_level"] == 0.4
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.5})
    await env.fire("cc_018_00", "1")
    assert len(env.calls_of("media_player.volume_set")) == 1   # above the cap, not raised
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.01})
    await env.fire("cc_018_00", "65")
    assert env.calls_of("media_player.volume_set")[-1][1]["volume_level"] == 0


async def test_dial_colour_temperature(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_dial": "colour_temp"})
    await env.fire("cc_016_00", "1")
    await env.tick(0.3)
    assert env.calls[-1][1]["color_temp_kelvin"] == 4225


async def test_dial_colour_temperature_on_rgb_only_light(hass, freezer, mqtt_mock):
    """WLED RGB lights report no color_temp_kelvin. The dial reads the temperature back from rgb_color."""
    from homeassistant.util import color as color_util

    def rgb_for(kelvin):
        return [round(c) for c in color_util.color_temperature_to_rgb(kelvin)]

    states = {
        "light.lamp": ("on", {"supported_color_modes": ["rgb"], "color_mode": "rgb", "color_temp_kelvin": None,
                              "min_color_temp_kelvin": None, "max_color_temp_kelvin": None,
                              "rgb_color": rgb_for(3000)}),
    }
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_dial": "colour_temp"}, light_state=states)
    await env.fire("cc_016_00", "1")                      # clockwise: colder
    await env.tick(0.3)
    assert 3200 <= env.calls[-1][1]["color_temp_kelvin"] <= 3260
    await env.fire("cc_016_00", "65")                     # anticlockwise: warmer
    await env.tick(0.3)
    assert 2740 <= env.calls[-1][1]["color_temp_kelvin"] <= 2800

    for start in (5000, 6000):                            # the cold side is read from the red channel
        hass.states.async_set("light.lamp", "on", {**states["light.lamp"][1], "rgb_color": rgb_for(start)})
        await env.fire("cc_016_00", "65")
        await env.tick(0.3)
        assert start - 225 - 60 <= env.calls[-1][1]["color_temp_kelvin"] <= start - 225 + 60


async def test_dial_colour_temperature_without_any_reading_starts_warm(hass, freezer, mqtt_mock):
    states = {"light.lamp": ("on", {"supported_color_modes": ["rgb"], "color_mode": "rgb"})}
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_dial": "colour_temp"}, light_state=states)
    await env.fire("cc_016_00", "1")
    await env.tick(0.3)
    assert env.calls[-1][1]["color_temp_kelvin"] == 2225


async def test_dial_colour_temperature_via_rgb(hass, freezer, mqtt_mock):
    """colour_temp_rgb sends rgb_color even when the light supports color_temp."""
    from homeassistant.util import color as color_util

    rgb_3000 = [round(c) for c in color_util.color_temperature_to_rgb(3000)]
    states = {
        "light.lamp": ("on", {"supported_color_modes": ["color_temp", "rgb"], "color_mode": "rgb",
                              "min_color_temp_kelvin": 2000, "max_color_temp_kelvin": 6500,
                              "rgb_color": rgb_3000}),
    }
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_dial": "colour_temp_rgb"}, light_state=states)
    await env.fire("cc_016_00", "1")                      # clockwise: colder (more blue)
    await env.tick(0.3)
    call = env.calls[-1][1]
    assert "color_temp_kelvin" not in call
    assert call["rgb_color"][2] > rgb_3000[2]
    await env.fire("cc_016_00", "65")                     # anticlockwise: warmer (less blue)
    await env.tick(0.3)
    call = env.calls[-1][1]
    assert "color_temp_kelvin" not in call
    assert call["rgb_color"][2] < rgb_3000[2]


async def test_dial_hue_and_saturation(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_dial": "hue"})
    await env.fire("cc_016_00", "65")
    await env.tick(0.3)
    assert env.calls[-1][1]["hs_color"] == [102.0, 50.0]


async def test_dial_saturation(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_dial": "saturation"})
    await env.fire("cc_016_00", "65")
    await env.tick(0.3)
    assert env.calls[-1][1]["hs_color"] == [120.0, 45.0]


async def test_dial_burst_sends_one_command_in_the_latest_direction(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_dial": "colour_temp"})
    align(env)
    for payload in ("1", "1", "1", "65"):
        await env.fire("cc_016_00", payload)
        await env.tick(0.03)
    await env.tick(0.3)
    calls = env.calls_of("light.turn_on")
    assert len(calls) == 1
    assert calls[0][1]["color_temp_kelvin"] == 3775


async def test_spinning_dial_updates_lights_once_per_interval(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_dial": "colour_temp"})
    align(env)
    for _ in range(25):                                   # 25 clicks over 1 second (40 ms apart)
        await env.fire("cc_016_00", "1")
        await env.tick(0.04)
    await env.tick(0.3)
    calls = env.calls_of("light.turn_on")
    assert 3 <= len(calls) <= 5                           # about one command per 250 ms, not 25


async def test_dial_sampling_interval_input_is_honoured(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"strip_1_dial": "colour_temp", "dial_debounce": 500})
    align(env)
    await env.fire("cc_016_00", "1")
    await env.tick(0.3)
    assert not env.calls_of("light.turn_on")
    await env.tick(0.3)
    assert env.calls_of("light.turn_on")[-1][1]["color_temp_kelvin"] == 4225


async def test_dial_zero_and_unknown_controllers_are_ignored(env):
    await env.fire("cc_016_00", "0")
    await env.fire("cc_016_00", "64")
    await env.fire("cc_030_00", "1")
    await env.fire("chord_0", "C")
    await env.tick(0.3)
    assert env.calls == []


# ---- strip keys -----------------------------------------------------------------------------------------------

async def test_strip_keys_on_lights(env):
    await env.press(24)
    assert env.calls[-1][0] == "light.toggle"
    await env.press(8)
    assert env.calls[-1][1]["brightness_pct"] == 100
    await env.press(16)
    assert env.calls[-1][0] == "light.turn_off"
    await env.press(0)
    assert env.calls[-1][1]["brightness_pct"] == 5


async def test_strip_keys_on_media_players_and_lights_together(env):
    await env.press(25)
    names = [c[0] for c in env.calls]
    assert names == ["light.toggle", "media_player.media_play_pause"]
    env.calls.clear()
    await env.press(9)
    assert [c[0] for c in env.calls] == ["light.turn_on", "media_player.media_next_track"]
    env.calls.clear()
    await env.press(1)
    assert [c[0] for c in env.calls] == ["light.turn_on", "media_player.media_previous_track"]


async def test_strip_mute_toggles_player_mute(hass, env):
    await env.press(18)
    assert env.calls_of("media_player.volume_mute")[-1][1]["is_volume_muted"] is True
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.2, "is_volume_muted": True})
    await env.press(18)
    assert env.calls_of("media_player.volume_mute")[-1][1]["is_volume_muted"] is False


async def test_key_release_and_unused_strips_do_nothing(env):
    await env.fire("button_state_024_00", "OFF")
    await env.press(27)   # strip 4 is unused
    assert env.calls == []


# ---- transport keys -------------------------------------------------------------------------------------------

async def test_transport_keys(env):
    for note, service in ((94, "media_play"), (93, "media_pause"), (95, "media_play_pause"),
                          (98, "media_previous_track"), (99, "media_next_track")):
        env.calls.clear()
        await env.press(note)
        assert [c[0] for c in env.calls] == [f"media_player.{service}"], note
        assert env.calls[0][1]["entity_id"] == ["media_player.amp"]


async def test_record_key_uses_record_players(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"record_media_players": ["media_player.cast"]})
    await env.press(95)
    assert env.calls[-1][1]["entity_id"] == ["media_player.cast"]
    env.calls.clear()
    await env.press(94)
    assert env.calls[-1][1]["entity_id"] == ["media_player.amp"]


async def test_up_and_down_keys_step_volume(hass, env):
    await env.press(96)
    await env.press(97)
    levels = [c[1]["volume_level"] for c in env.calls_of("media_player.volume_set")]
    assert levels == [0.51, 0.48]
    assert all(c[1]["entity_id"] == ["media_player.amp"] for c in env.calls_of("media_player.volume_set"))


async def test_rewind_and_fast_forward_seek(hass, env):
    hass.states.async_set("media_player.amp", "paused", {"media_position": 100, "media_duration": 105, "volume_level": 0.5})
    await env.press(92)
    assert env.calls[-1][1]["seek_position"] == 105
    await env.press(91)
    assert env.calls[-1][1]["seek_position"] == 90
    hass.states.async_set("media_player.amp", "paused", {"media_position": 4, "volume_level": 0.5})
    await env.press(91)
    assert env.calls[-1][1]["seek_position"] == 0


async def test_seek_skips_players_without_position(hass, env):
    hass.states.async_set("media_player.amp", "playing", {"volume_level": 0.5})
    await env.press(92)
    assert not env.calls_of("media_player.media_seek")


async def test_playing_seek_adds_elapsed_time(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock)
    from homeassistant.util import dt as dt_util
    started = dt_util.utcnow()
    hass.states.async_set("media_player.amp", "playing", {"media_position": 100, "media_position_updated_at": started})
    await env.tick(20)
    await env.press(92)
    assert env.calls_of("media_player.media_seek")[-1][1]["seek_position"] == 130


async def test_bank_keys_cycle_sources(hass, env):
    await env.press(47)
    assert env.calls[-1][1]["source"] == "TV"
    await env.press(46)
    assert env.calls[-1][1]["source"] == "Radio"      # wraps from PC
    await env.press(49)
    assert env.calls[-1][1]["source"] == "TV"
    hass.states.async_set("media_player.amp", "on", {"source": "Radio", "source_list": ["PC", "TV", "Radio"]})
    await env.press(47)
    assert env.calls[-1][1]["source"] == "PC"


async def test_bank_keys_skip_players_without_sources(hass, env):
    hass.states.async_set("media_player.amp", "on", {})
    await env.press(47)
    assert env.calls == []


# ---- device selection -----------------------------------------------------------------------------------------

async def test_events_from_the_private_port_are_ignored(env):
    await env.press(94, PRIVATE)
    await env.fire("pb_0", "40", PRIVATE, fader=False)
    assert env.calls == []


async def test_topic_prefix_override(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"topic_prefix": PRIVATE + "/"})
    await env.press(94, PRIVATE)
    assert [c[0] for c in env.calls] == ["media_player.media_play"]
    env.calls.clear()
    await env.press(94)
    assert env.calls == []


async def test_log_events_names_the_controls(hass, freezer, mqtt_mock):
    env = await setup(hass, freezer, mqtt_mock, {"log_events": True})
    await env.fire("pb_0", "40")
    await env.fire("cc_017_00", "65")
    await env.press(27)
    await env.press(95)
    await env.press(46)
    msgs = [c[1]["message"] for c in env.calls_of("system_log.write")]
    assert msgs == ["Fader 1: 40", "Dial 2: 65", "Strip 4 Select: ON", "Strip 4 Select: OFF",
                    "Record: ON", "Record: OFF", "Previous 8 tracks: ON", "Previous 8 tracks: OFF"]


# ---- state triggers --------------------------------------------------------------------------------------------

async def test_light_attribute_changes_do_not_start_a_run(hass, env):
    """A dial changes brightness and colour many times a second. Each change must not start a run, or the runs
    fill the stored traces and the parallel run limit."""
    before = hass.states.get("automation.mixer").attributes["last_triggered"]
    hass.states.async_set("light.lamp", "on", {"brightness": 10, "color_temp_kelvin": 3000})
    await env.pump()
    hass.states.async_set("light.lamp", "on", {"brightness": 200, "color_temp_kelvin": 5000})
    await env.pump()
    assert hass.states.get("automation.mixer").attributes["last_triggered"] == before


async def test_light_state_change_starts_a_run(hass, env):
    before = hass.states.get("automation.mixer").attributes["last_triggered"]
    hass.states.async_set("light.lamp", "off")
    await env.pump()
    assert hass.states.get("automation.mixer").attributes["last_triggered"] != before


async def test_player_mute_change_starts_a_run(hass, env):
    before = hass.states.get("automation.mixer").attributes["last_triggered"]
    hass.states.async_set("media_player.amp", "paused", {"volume_level": 0.5, "is_volume_muted": True})
    await env.pump()
    assert hass.states.get("automation.mixer").attributes["last_triggered"] != before


# ---- key lights -----------------------------------------------------------------------------------------------

async def test_transport_lights_follow_media_players(hass, env):
    hass.states.async_set("media_player.amp", "playing", {"volume_level": 0.5, "is_volume_muted": False})
    await env.pump()
    transport = range(93, 96)
    assert env.led(transport) == [(94, "ON"), (93, "OFF"), (95, "ON")]
    hass.states.async_set("media_player.amp", "paused", {"volume_level": 0.5, "is_volume_muted": False})
    await env.pump()
    assert env.led(transport)[3:] == [(94, "OFF"), (93, "ON"), (95, "OFF")]


async def test_position_updates_do_not_republish_lights(hass, env):
    hass.states.async_set("media_player.amp", "playing", {"volume_level": 0.5, "media_position": 1})
    await env.pump()
    n = len(env.led())
    hass.states.async_set("media_player.amp", "playing", {"volume_level": 0.5, "media_position": 2})
    await env.pump()
    assert len(env.led()) == n


async def test_strip_lights_follow_targets(hass, env):
    hass.states.async_set("light.lamp", "off", {})
    await env.pump()
    assert env.led() == [(24, "OFF"), (16, "ON")]
    hass.states.async_set("light.lamp", "on", {})
    await env.pump()
    assert env.led()[2:] == [(24, "ON"), (16, "OFF")]


async def test_strip_lights_follow_mute(hass, env):
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.2, "is_volume_muted": False})
    await env.pump()
    assert (26, "ON") in env.led() and (18, "OFF") in env.led()
    hass.states.async_set("media_player.cast", "playing", {"volume_level": 0.2, "is_volume_muted": True})
    await env.pump()
    assert env.led()[-1] == (18, "ON")


async def test_every_light_is_synchronised_when_the_bridge_comes_online(hass, env):
    hass.states.async_set("media_player.amp", "playing", {"volume_level": 0.5})
    await env.pump()
    hass.states.async_set("light.lamp", "on", {})
    await env.pump()
    env.mqtt.async_publish.reset_mock()
    async_fire_mqtt_message(hass, f"{PREFIX}/availability", "online")
    await env.pump()
    notes = sorted({n for n, _ in env.led()})
    assert notes == [16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 93, 94, 95]
    assert dict(env.led())[94] == "ON" and dict(env.led())[24] == "ON"
    env.mqtt.async_publish.reset_mock()
    async_fire_mqtt_message(hass, f"{PRIVATE}/availability", "online")
    await env.pump()
    assert env.led() == []
    async_fire_mqtt_message(hass, f"{PREFIX}/availability", "offline")
    await env.pump()
    assert env.led() == []


async def test_key_light_topics_use_the_bridge_set_topic(hass, env):
    hass.states.async_set("media_player.amp", "playing", {"volume_level": 0.5})
    await env.pump()
    topics = [c.args[0] for c in env.mqtt.async_publish.call_args_list]
    assert f"{PREFIX}/button_light_094_00/set" in topics
