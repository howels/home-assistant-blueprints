import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from harness import RESTORE_FILE, build

M, W = "binary_sensor.motion", "binary_sensor.mmwave"


async def enter_default(env):
    await env.setsensor(M, "on")
    await env.tick(2)


async def customise(env):
    """Simulate the user changing the lights while in the room."""
    h = env.hass
    await h.services.async_call("light", "turn_on", {"entity_id": "light.lamp_ct", "brightness": 200, "color_temp_kelvin": 4000}, blocking=True)
    await h.services.async_call("light", "turn_on", {"entity_id": "light.lamp_hs", "brightness": 80, "hs_color": [120, 50]}, blocking=True)
    await h.services.async_call("input_select", "select_option", {"entity_id": "input_select.preset", "option": "b"}, blocking=True)


async def leave(env, secs=31):
    await env.setsensor(M, "off")
    await env.tick(secs)
    await env.pump()


async def test_full_cycle(hass, freezer):
    env = await build(hass, freezer)
    await enter_default(env)
    assert env.s("light.lamp_ct").attributes["brightness"] == 100
    assert env.s("light.lamp_hs").state == "off"
    assert env.s("scene.study_scene_tmp") is not None
    assert env.store["study"]["vacated"] is False
    assert env.store["study"]["snapshot"] == {}   # default is not persisted

    await customise(env)
    await leave(env)
    for e in ("light.lamp_ct", "light.lamp_hs", "light.lamp_bri"):
        assert env.s(e).state == "off", e
    rec = env.store["study"]
    assert rec["vacated"] is True
    snap = rec["snapshot"]
    assert snap["light.lamp_ct"]["brightness"] == 200
    assert snap["light.lamp_ct"]["color_temp_kelvin"] == 4000
    assert snap["light.lamp_ct"]["color_mode"] == "color_temp"
    assert "hs_color" not in snap["light.lamp_ct"] and "xy_color" not in snap["light.lamp_ct"]
    assert list(snap["light.lamp_hs"]["hs_color"]) == [120, 50]
    assert snap["input_select.preset"] == {"state": "b"}
    assert rec["saved_at"]

    # re-entry restores the saved state, not the default
    await env.setsensor(M, "on")
    await env.tick(1)
    assert env.s("light.lamp_ct").attributes["brightness"] == 200
    assert env.s("light.lamp_ct").attributes["color_temp_kelvin"] == 4000
    assert env.s("light.lamp_hs").state == "on"
    assert env.s("light.lamp_hs").attributes["brightness"] == 80
    assert env.s("light.lamp_bri").state == "on"
    assert env.s("input_select.preset").state == "b"
    assert env.store["study"]["vacated"] is False


async def test_flicker_keeps_manual_changes(hass, freezer):
    env = await build(hass, freezer)
    await enter_default(env)
    await customise(env)
    await leave(env)
    await env.setsensor(M, "on")
    await env.tick(1)
    # user dims a lamp, sensor flickers
    await hass.services.async_call("light", "turn_on", {"entity_id": "light.lamp_ct", "brightness": 10}, blocking=True)
    for _ in range(3):
        await env.setsensor(M, "off")
        await env.tick(5)
        await env.setsensor(M, "on")
        await env.tick(1)
    assert env.s("light.lamp_ct").attributes["brightness"] == 10


async def test_reentry_during_vacancy_run_is_serialised(hass, freezer):
    env = await build(hass, freezer, inputs={"on_vacant_actions": [{"delay": {"seconds": 10}}]})
    await enter_default(env)
    await customise(env)
    await env.setsensor(M, "off")
    await env.tick(31)          # vacancy run starts, snapshot saved, lights off, 10 s delay
    assert env.s("light.lamp_ct").state == "off"
    assert env.store["study"]["snapshot"]["light.lamp_ct"]["brightness"] == 200
    await env.setsensor(M, "on")  # re-entry while the vacancy run is still running
    await env.tick(1)
    assert env.s("light.lamp_ct").state == "off"   # entry is queued, not racing
    await env.tick(10)          # vacancy run ends, entry runs
    await env.tick(1)
    assert env.s("light.lamp_ct").state == "on"
    assert env.s("light.lamp_ct").attributes["brightness"] == 200
    assert env.s("light.lamp_hs").attributes["brightness"] == 80
    kinds = [k for k, _ in env.lights["light.lamp_ct"].log]
    assert kinds[-2:] == ["off", "on"], kinds


async def test_zz_dump_restore_state(hass, freezer, hass_storage):
    """Round trip through core.restore_state, as Home Assistant writes it on stop."""
    import json
    from homeassistant.helpers import restore_state as rs
    env = await build(hass, freezer)
    await enter_default(env)
    await customise(env)
    await leave(env)
    await rs.async_get(hass).async_dump_states()
    rec = [r for r in hass_storage["core.restore_state"]["data"]
           if r["state"]["entity_id"] == "sensor.occupancy_scene_store"][0]
    RESTORE_FILE.write_text(json.dumps(rec))


async def test_zzz_restart_restores_scene_and_snapshot(hass, freezer):
    import json
    rec = json.loads(RESTORE_FILE.read_text())
    saved = rec["state"]["attributes"]["rooms"]
    env = await build(hass, freezer, restore=rec, starting=True)
    assert env.store == saved                       # restored by the template sensor
    assert saved["study"]["snapshot"]["light.lamp_ct"]["brightness"] == 200
    assert env.s("scene.study_scene_tmp") is None   # runtime scenes do not survive a restart
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await env.pump()
    scene = env.s("scene.study_scene_tmp")
    assert scene is not None
    assert set(scene.attributes["entity_id"]) == {"light.lamp_ct", "light.lamp_hs", "light.lamp_bri", "input_select.preset"}
    await env.setsensor(M, "on")
    await env.tick(1)
    assert env.s("light.lamp_ct").attributes["brightness"] == 200      # not the default (100)
    assert env.s("light.lamp_ct").attributes["color_temp_kelvin"] == 4000
    assert env.s("light.lamp_hs").attributes["brightness"] == 80
    assert env.s("input_select.preset").state == "b"


async def test_hold_only_sensor(hass, freezer):
    env = await build(hass, freezer)
    await env.setsensor(W, "on")
    await env.tick(2)
    assert env.s("light.lamp_ct").state == "off"       # hold-only cannot start occupancy
    await enter_default(env)
    await customise(env)
    await env.setsensor(M, "off")
    await env.tick(60)
    assert env.s("light.lamp_ct").state == "on"        # mmwave still holds the room
    await env.setsensor(W, "off")
    await env.tick(31)
    assert env.s("light.lamp_ct").state == "off"


async def test_unavailable_sensors_do_not_vacate(hass, freezer):
    env = await build(hass, freezer)
    await enter_default(env)
    await env.setsensor(M, "unavailable")
    await env.setsensor(W, "unavailable")
    await env.tick(120)
    assert env.s("light.lamp_ct").state == "on"


async def test_snapshot_conditions_keep_old_snapshot(hass, freezer):
    env = await build(hass, freezer, inputs={"snapshot_conditions": [
        {"condition": "state", "entity_id": "input_select.preset", "state": "a"}]})
    await enter_default(env)
    await customise(env)       # preset -> b, so the condition fails
    await leave(env)
    assert env.s("light.lamp_ct").state == "off"
    assert env.store["study"]["snapshot"] == {}
    assert env.store["study"]["vacated"] is True


async def test_people_and_hours_gate_entry(hass, freezer):
    hass.states.async_set("person.a", "not_home")
    env = await build(hass, freezer, inputs={"people": ["person.a"]})
    await enter_default(env)
    assert env.s("light.lamp_ct").state == "off"
    assert env.store == {}
    await env.setsensor(M, "off")
    await env.tick(31)
    hass.states.async_set("person.a", "home")
    await env.setsensor(M, "on")
    await env.tick(2)
    assert env.s("light.lamp_ct").state == "on"


async def test_vacate_with_everything_already_off_keeps_snapshot(hass, freezer):
    env = await build(hass, freezer)
    await enter_default(env)
    await customise(env)
    await leave(env)
    snap = env.store["study"]["snapshot"]
    await env.setsensor(W, "on"); await env.setsensor(W, "off")   # hold-only blip while vacant
    await env.tick(31)
    assert env.store["study"]["snapshot"] == snap


async def test_missing_store_degrades_to_runtime_scene(hass, freezer):
    env = await build(hass, freezer, inputs={"store": "sensor.nonexistent"})
    await enter_default(env)
    await customise(env)
    await leave(env)
    assert env.s("light.lamp_ct").state == "off"
    await env.setsensor(M, "on")
    await env.tick(1)
    assert env.s("light.lamp_ct").attributes["brightness"] == 200    # via scene.study_scene_tmp


async def test_turn_off_target_and_actions(hass, freezer):
    env = await build(hass, freezer, inputs={
        "turn_off_target": {"entity_id": ["light.lamp_bri"]},
        "on_enter_actions": [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.entered"}}],
        "on_vacant_actions": [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.left"}}],
    }) if False else None


async def test_minimal_inputs_use_defaults(hass, freezer, caplog):
    env = await build(hass, freezer, minimal=True)
    await env.setsensor(M, "on")
    await env.tick(6)                                     # the entry waits 5 s for a light to come on
    assert env.s("light.lamp_ct").state == "off"          # no default scene, lights untouched
    assert env.store["study"]["vacated"] is True          # nothing was restored, so the next entry retries
    await hass.services.async_call("light", "turn_on", {"entity_id": "light.lamp_bri", "brightness": 90}, blocking=True)
    await env.setsensor(M, "off")
    await env.tick(119)
    assert env.s("light.lamp_bri").state == "on"          # default clear delay is 2 minutes
    await env.tick(2)
    assert env.s("light.lamp_bri").state == "off"
    await env.setsensor(M, "on")
    await env.tick(1)
    assert env.s("light.lamp_bri").attributes["brightness"] == 90
    errs = [r for r in caplog.records if r.levelname in ("ERROR", "WARNING") and r.name.startswith("homeassistant")]
    assert not errs, [r.getMessage() for r in errs]


async def test_scene_reload_recreates_runtime_scene(hass, freezer):
    env = await build(hass, freezer)
    await enter_default(env)
    await customise(env)
    await leave(env)
    assert env.s("scene.study_scene_tmp") is not None
    await hass.services.async_call("scene", "delete", {"entity_id": "scene.study_scene_tmp"}, blocking=True)
    assert env.s("scene.study_scene_tmp") is None
    hass.bus.async_fire("scene_reloaded")
    await env.pump()
    assert env.s("scene.study_scene_tmp") is not None
    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.study_scene_tmp"}, blocking=True)
    assert env.s("light.lamp_ct").attributes["brightness"] == 200


async def test_active_hours_across_midnight(hass, freezer):
    import datetime as dt
    from homeassistant.util import dt as dt_util
    tz = dt_util.get_default_time_zone()
    freezer.move_to(dt.datetime(2026, 11, 24, 3, 0, tzinfo=tz))
    env = await build(hass, freezer, inputs={"active_after": "08:00:00", "active_before": "01:00:00"})
    await enter_default(env)
    assert env.s("light.lamp_ct").state == "off"          # 03:00 is outside 08:00-01:00
    assert env.store == {}
    await env.setsensor(M, "off")
    await env.tick(31)
    freezer.move_to(dt.datetime(2026, 11, 24, 23, 30, tzinfo=tz))
    await env.setsensor(M, "on")
    await env.tick(2)
    assert env.s("light.lamp_ct").state == "on"           # 23:30 is inside


async def test_target_and_actions(hass, freezer):
    env = await build(hass, freezer, inputs={
        "turn_off_target": {"entity_id": ["light.lamp_bri"]},
        "on_enter_actions": [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.entered"}}],
        "on_vacant_actions": [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.left"}}],
    })
    await enter_default(env)
    assert env.s("input_boolean.entered").state == "on"
    await customise(env)
    await leave(env)
    assert env.s("light.lamp_bri").state == "off"        # in the target
    assert env.s("light.lamp_ct").state == "on"           # not in the target
    assert env.s("input_boolean.left").state == "on"
    assert env.store["study"]["snapshot"]["light.lamp_ct"]["brightness"] == 200


async def test_queued_duplicate_entries_apply_once(hass, freezer):
    env = await build(hass, freezer, inputs={"on_enter_actions": [{"delay": {"seconds": 5}}]})
    await enter_default(env)
    await env.setsensor(M, "off"); await env.tick(1)
    await env.setsensor(M, "on"); await env.tick(1)
    await env.setsensor(M, "off"); await env.tick(1)
    await env.setsensor(M, "on"); await env.tick(20)
    on_calls = [k for k, _ in env.lights["light.lamp_ct"].log if k == "on"]
    assert len(on_calls) == 1, env.lights["light.lamp_ct"].log


async def test_forget_event_clears_snapshot(hass, freezer):
    env = await build(hass, freezer)
    await enter_default(env)
    await customise(env)
    await leave(env)
    assert env.store["study"]["snapshot"]
    hass.bus.async_fire("occupancy_room_update", {"room": "study", "snapshot": {}, "vacated": True})
    await env.pump()
    assert env.store["study"]["snapshot"] == {}
    assert env.store["study"]["saved_at"] == ""
    await env.setsensor(M, "on")
    await env.tick(2)
    assert env.s("light.lamp_ct").attributes["brightness"] == 200   # runtime scene still exists, so it is used


async def test_entries_queued_behind_vacancy_apply_once(hass, freezer):
    """Variables are read when a run starts, not when it is queued."""
    env = await build(hass, freezer, inputs={"on_vacant_actions": [{"delay": {"seconds": 10}}]})
    await enter_default(env)
    await customise(env)
    await env.setsensor(M, "off")
    await env.tick(31)                       # vacancy run saves, turns off, then waits 10 s
    before = len([k for k, _ in env.lights["light.lamp_ct"].log if k == "on"])
    for state in ("on", "off", "on"):        # two entries queue while vacated is true
        await env.setsensor(M, state)
        await env.tick(1)
    await env.tick(15)
    after = [k for k, _ in env.lights["light.lamp_ct"].log if k == "on"]
    assert len(after) - before == 1
    # a manual change after the restore survives: the second queued entry saw vacated false
    assert env.s("light.lamp_ct").attributes["brightness"] == 200


async def test_entry_before_hours_restores_when_hours_open(hass, freezer):
    import datetime as dt
    from homeassistant.util import dt as dt_util
    tz = dt_util.get_default_time_zone()
    freezer.move_to(dt.datetime(2026, 11, 24, 7, 0, tzinfo=tz))
    env = await build(hass, freezer, inputs={"active_after": "08:00:00", "active_before": "23:00:00"})
    await enter_default(env)
    assert env.s("light.lamp_ct").state == "off"
    freezer.move_to(dt.datetime(2026, 11, 24, 8, 0, 0, 500000, tzinfo=tz))
    async_fire = __import__("pytest_homeassistant_custom_component.common", fromlist=["x"]).async_fire_time_changed
    async_fire(hass)
    await env.pump()
    assert env.s("light.lamp_ct").state == "on"
    await env.tick(2)
    assert env.store["study"]["vacated"] is False


async def test_gate_needs_someone_in_the_room(hass, freezer):
    import datetime as dt
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    tz = dt_util.get_default_time_zone()
    freezer.move_to(dt.datetime(2026, 11, 24, 7, 0, tzinfo=tz))
    env = await build(hass, freezer, inputs={"active_after": "08:00:00", "active_before": "23:00:00"})
    freezer.move_to(dt.datetime(2026, 11, 24, 8, 0, 0, 500000, tzinfo=tz))
    async_fire_time_changed(hass)
    await env.pump()
    assert env.s("light.lamp_ct").state == "off"          # empty room: the hours opening restores nothing


async def test_arrival_home_restores_when_already_in_room(hass, freezer):
    hass.states.async_set("person.a", "not_home")
    env = await build(hass, freezer, inputs={"people": ["person.a"]})
    await enter_default(env)
    assert env.s("light.lamp_ct").state == "off"
    hass.states.async_set("person.a", "home")
    await env.pump()
    assert env.s("light.lamp_ct").state == "on"


def raw_record(rooms):
    return {
        "state": {"entity_id": "sensor.occupancy_scene_store", "state": "2026-01-01T00:00:00+00:00",
                  "attributes": {"rooms": rooms}, "last_changed": "2026-01-01T00:00:00+00:00",
                  "last_updated": "2026-01-01T00:00:00+00:00", "context": {"id": "x", "parent_id": None, "user_id": None}},
        "extra_data": {"native_value": "2026-01-01T00:00:00+00:00", "native_unit_of_measurement": None},
    }


async def test_recheck_vacates_after_a_missed_edge(hass, freezer):
    """The vacate template is already true when the automation loads, so it never fires."""
    import datetime as dt
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    tz = dt_util.get_default_time_zone()
    freezer.move_to(dt.datetime(2026, 11, 24, 12, 0, 30, tzinfo=tz))
    env = await build(hass, freezer, restore=raw_record({"study": {"snapshot": {}, "saved_at": "", "vacated": False}}))
    await hass.services.async_call("light", "turn_on", {"entity_id": "light.lamp_ct", "brightness": 120}, blocking=True)
    await env.tick(300)                                    # 12:05:30, no recheck due
    assert env.s("light.lamp_ct").state == "on"
    freezer.move_to(dt.datetime(2026, 11, 24, 12, 10, 0, 500000, tzinfo=tz))
    async_fire_time_changed(hass)
    await env.pump()
    assert env.s("light.lamp_ct").state == "off"
    assert env.store["study"]["vacated"] is True
    assert env.store["study"]["snapshot"]["light.lamp_ct"]["brightness"] == 120


async def test_recheck_leaves_manual_lights_alone_once_vacated(hass, freezer):
    import datetime as dt
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    tz = dt_util.get_default_time_zone()
    freezer.move_to(dt.datetime(2026, 11, 24, 12, 0, 30, tzinfo=tz))
    env = await build(hass, freezer, restore=raw_record({"study": {"snapshot": {}, "saved_at": "", "vacated": True}}))
    await hass.services.async_call("light", "turn_on", {"entity_id": "light.lamp_ct", "brightness": 120}, blocking=True)
    await env.tick(300)
    freezer.move_to(dt.datetime(2026, 11, 24, 12, 10, 0, 500000, tzinfo=tz))
    async_fire_time_changed(hass)
    await env.pump()
    assert env.s("light.lamp_ct").state == "on"


async def test_unavailable_lights_at_entry_retry_on_next_entry(hass, freezer):
    env = await build(hass, freezer)
    await enter_default(env)
    await customise(env)
    await leave(env)
    for l in env.lights.values():
        l.set_available(False)
    await env.setsensor(M, "on")
    await env.tick(6)
    assert env.store["study"]["vacated"] is True          # nothing came on, so try again next time
    for l in env.lights.values():
        l.set_available(True)
    await env.setsensor(M, "off")
    await env.tick(1)
    await env.setsensor(M, "on")
    await env.tick(2)
    assert env.s("light.lamp_ct").attributes["brightness"] == 200
    assert env.store["study"]["vacated"] is False
    assert env.store["study"]["snapshot"]["light.lamp_ct"]["brightness"] == 200
