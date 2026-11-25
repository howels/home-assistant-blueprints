# home-assistant-blueprints

Home Assistant blueprints by howels.

| Path | Contents |
|----|----|
| `blueprints/pause_automations_on_service_restart.yaml` | Turns selected automations off while a service restarts, runs an action, and turns back on only the automations that were on. Restores them if that run is aborted. Usage with the Mosquitto broker and ha-midi is in the readmes below. |
| `examples/mosquitto_broker.md` | The Mosquitto broker add-on running sensor used as that blueprint's service sensor. |
| `examples/ha_midi_restart.md` | The `shell_command` that restarts the ha-midi bridge, and the SSH and systemd requirements. |
| `blueprints/room_occupancy.yaml` | Restores a room's lighting on entry and saves it, then turns the lights off, when the room is clear. |
| `blueprints/zha_aurora_dimmer_lights.yaml` | Controls up to two light groups from a ZHA Aurora dimmer or smart knob. Handles step events and absolute level events, with adjustable sensitivity. |
| `blueprints/wled-matrix-album-art.yaml` | Shows a media player's album art on a WLED matrix and clears the matrix when playback stops. |
| `blueprints/panda_esl_weather.yaml` | Draws current weather and a three day forecast on a PANDA / ETAG Bluetooth e-paper label through the PANDA ESL integration. Icon style is Material Design Icons or OpenMoji pictures. |
| `blueprints/panda_esl_todo.yaml` | Draws the open items of a to-do entity, with due dates, on a PANDA ESL label. |
| `blueprints/panda_esl_calendar.yaml` | Draws the coming events of one or more calendar entities, including Google Calendar, on a PANDA ESL label. |
| `blueprints/panda_esl_alerts.yaml` | Lists watched entities that are in a problem state, such as open doors and low batteries, on a PANDA ESL label. |
| `blueprints/panda_esl_*.yaml` emoji | Icon style emoji draws OpenMoji PNGs through the `dlimg` element. The panel shows black, white, and red, so red parts stay red, outlines turn black, and yellow is drawn as red. The default image URL points at jsDelivr; set the emoji image URL to a local folder to avoid the download. OpenMoji is licensed CC BY-SA 4.0. |
| `examples/occupancy_scene_store.yaml` | Template sensor that keeps the saved snapshots across restarts. |
| `tests/` | pytest suite that runs the blueprint in a real Home Assistant core. |

## Pause automations on service restart

`blueprints/pause_automations_on_service_restart.md` is the blueprint. `examples/mosquitto_broker.md` is the broker sensor this installation watches. `examples/ha_midi_restart.md` is the SSH command that restarts the bridge. The blueprint needs an `input_text` with maximum length 255 before the automation runs.

## Install room_occupancy

1. In Home Assistant, open Settings > Automations & scenes > Blueprints > Import blueprint. Enter `https://github.com/howels/home-assistant-blueprints/blob/main/blueprints/room_occupancy.yaml`.
2. Add the item in `examples/occupancy_scene_store.yaml` to the `template:` list in `configuration.yaml`. Check the configuration, then reload template entities.
3. Create one automation per room from the blueprint. The blueprint description explains each input and the sequence it runs.

Without the store sensor the blueprint still works, but it forgets the saved lighting at restart and every entry restores the lights.

## Tests

The suite needs Python 3.14 and the Home Assistant core package. From the repository root:

```
uv venv /tmp/hav --python 3.14
uv pip install --python /tmp/hav/bin/python homeassistant pytest-homeassistant-custom-component
cd tests && PYTHONDONTWRITEBYTECODE=1 /tmp/hav/bin/python -m pytest -q -p no:cacheprovider
```

`tests/harness.py` copies the blueprint and the store sensor into a test instance, with fake lights and frozen time.
