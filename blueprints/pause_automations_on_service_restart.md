# Pause automations while a service restarts

`blueprints/pause_automations_on_service_restart.yaml` is an automation blueprint. It turns a chosen set of automations off while a service restarts, runs an action, then turns on only the automations that were on. Automations that were already off stay off.

The blueprint is the generic mechanism. The Mosquitto broker sensor and the ha-midi restart command are one installation of it. Those two are described in `examples/mosquitto_broker.md` and `examples/ha_midi_restart.md`.

## What it does

The running sensor is a binary sensor that is on while the service is up.

1. When the sensor leaves `on`, the blueprint writes a mask of which selected automations are on and turns those off.
2. When the sensor has been `on` for the settle time, it turns those automations off again, runs the restart actions, waits the resume delay, and turns the stored automations back on.
3. For the confirm time afterwards it turns them on again if they are off, then clears the mask.

`automation.turn_off` is kept by Home Assistant. A restart action that fails, or an automation reload that stops the run, skips the later `automation.turn_on`. The mask is written before the automations are turned off, so a later run can still turn them on. That later run is the minute check, and Home Assistant start. Runs are queued. A second restart waits until the current run has finished. Errors from the restart actions are ignored.

## Mask

The mask is kept in the memory `input_text`. The value is `MASK|PHASE|UNIX`.

`MASK` has one character per selected automation, in the order configured on the blueprint. `1` was on and is restored. `0` was off and is left off. `UNIX` is the time that phase started, in seconds.

| Phase | Meaning | When the automations are turned back on |
|----|----|----|
| `d` | The service is down. | The sensor has been on for the settle time plus the action timeout. The start trigger is given that long to run the restart actions itself. |
| `w` | The restart actions are running. | The action timeout has passed. The actions had not finished. |
| `r` | The resume delay is running. | The resume delay has passed. |
| `c` | The automations have been turned on and the mask is still kept. | Immediately if any stored automation is off. The mask is cleared after the confirm time if they stay on. |

On Home Assistant start a stored mask is acted on immediately when the sensor is on. A state trigger does not fire for a sensor that is already on.

During phase `c`, a stored automation that is turned off is turned back on. That lasts for the confirm time. The default is 60 seconds.

## Requirements

- Home Assistant can import an automation blueprint.
- The running sensor is a `binary_sensor` whose state is `on` only while the service is up. `off` and `unavailable` both count as down.
- The memory helper is an `input_text`. Set its maximum length to 255. The stored value is one character per automation, plus `|`, the phase letter, `|`, and a ten-digit timestamp. 255 is the longest Home Assistant state.
- The selected automations are `automation` entities. This blueprint must not be one of them.
- The restart actions are optional. Leave them empty to pause and restore with no extra action.
- If a restart action is a `shell_command`, Home Assistant stops it after 60 seconds and reports an error. The blueprint ignores that error. Set the action timeout longer than the command can run. The default action timeout is 120 seconds.

## Import

In Home Assistant, open Settings > Automations & scenes > Blueprints > Import blueprint. Enter `https://github.com/howels/home-assistant-blueprints/blob/main/blueprints/pause_automations_on_service_restart.yaml`. Save the suggested path `howels/pause_automations_on_service_restart.yaml`.

Create the memory `input_text` before the automation runs. Create one automation from the blueprint per service.
