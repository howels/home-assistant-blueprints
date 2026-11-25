# Mosquitto broker

The Mosquitto broker add-on is the service watched by `blueprints/pause_automations_on_service_restart.yaml` in this installation. The add-on is the running sensor. The blueprint pauses the MIDI automations across a broker restart so they do not act on the messages published when clients reconnect.

## Purpose

The Supervisor creates `binary_sensor.mosquitto_broker_running` for the Mosquitto broker add-on. The sensor is `on` while the add-on is running. It leaves `on` when the add-on stops or becomes unavailable.

When the broker returns, clients connect again and publish their current state. Automations that trigger on those topics see a burst of messages and run. The blueprint turns the selected automations off when the sensor leaves `on`, and turns them back on only after the broker has been up for the settle time and the restart actions have had the resume delay.

In this installation the restart action is the ha-midi bridge restart, documented in `examples/ha_midi_restart.md`. The bridge is restarted after the broker is back, while the MIDI automations are still off.

## Blueprint inputs

| Input | Value |
|----|----|
| Running sensor | `binary_sensor.mosquitto_broker_running` |
| Settle time | 5 seconds |
| Resume delay | 30 seconds |
| Action timeout | 120 seconds |
| Confirm time | 60 seconds |

The settle time is how long the sensor must stay `on` before the restart actions run. Five seconds avoids acting on a sensor that returns for a moment and drops again.

## Requirements

- The Mosquitto broker add-on is installed and supervised by Home Assistant. The blueprint reads the add-on's running sensor. It does not start or stop the add-on.
- `binary_sensor.mosquitto_broker_running` exists and is `on` while the add-on is running. Another broker install, or a renamed add-on, has a different entity id. Point the running sensor at that entity.
- Home Assistant MQTT is connected to this broker. The automations being paused are ones that trigger on topics from this broker.
- The memory `input_text` from `blueprints/pause_automations_on_service_restart.md` exists before this automation runs.
