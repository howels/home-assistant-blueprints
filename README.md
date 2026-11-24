# home-assistant-blueprints

Home Assistant blueprints by howels.

| Path | Contents |
|----|----|
| `blueprints/room_occupancy.yaml` | Restores a room's lighting on entry and saves it, then turns the lights off, when the room is clear. |
| `examples/occupancy_scene_store.yaml` | Template sensor that keeps the saved snapshots across restarts. |
| `tests/` | pytest suite that runs the blueprint in a real Home Assistant core. |

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
