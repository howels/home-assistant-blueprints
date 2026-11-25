# ha-midi restart

`shell_command.ha_midi_restart` restarts the ha-midi bridge after the Mosquitto broker is back. It is the restart action of `blueprints/pause_automations_on_service_restart.yaml`. The MIDI automations are off while it runs, so the state the bridge publishes on reconnect does not trigger them.

The command lives in Home Assistant `configuration.yaml`. It is not part of the blueprint file. The bridge address is set there and is not recorded in this repository.

Home Assistant runs SSH with the key `/config/.ssh/id_ed25519` and the known-hosts file `/config/.ssh/known_hosts`. The remote user is `ha-midi`. The remote command is exactly:

```text
sudo systemctl restart ha-midi
```

On the blueprint, the restart actions input is:

```yaml
restart_actions:
  - action: shell_command.ha_midi_restart
```

## What it does

The ha-midi unit is the bridge that publishes MIDI control state to the broker. `systemctl restart ha-midi` stops that process and starts it again, so it connects to the broker that just came up.

The blueprint runs this command only after the broker running sensor has been `on` for the settle time. It then waits the resume delay before turning the MIDI automations back on. The bridge needs that interval to reconnect and publish.

A failed SSH command does not stop the restore. Home Assistant ends a `shell_command` that runs for more than 60 seconds and reports an error. The blueprint ignores the error and still turns the automations on. If the automation run is stopped while the command is in progress, the stored mask turns them on after the action timeout. That timeout is 120 seconds, which is longer than the 60 second `shell_command` limit.

## What the account may do

The `ha-midi` user is not an administrator of the bridge host. `sudo` allows one command and refuses every other. The allowed command is `systemctl restart ha-midi`.

The sudoers rule names that whole command. `sudo` runs it with no password and no terminal, because the SSH session from Home Assistant is not interactive. A different command does not match the rule, so `sudo` rejects it. That includes:

- `systemctl restart` of any other unit
- `systemctl stop`, `start`, `disable`, or `edit` of `ha-midi` or of any other unit
- extra arguments on the restart command
- a root shell
- reboot, shutdown, or package changes

The account can still run programs as itself over SSH. It cannot use `sudo` to change any other service on the host.

## Automations held off

These are the automations passed to the blueprint. Each one acts on MIDI state from the bridge. An automation in this list that is already off is not turned on at the end.

- `automation.midi_light`
- `automation.midi_channel_1`
- `automation.midi_fader_2`
- `automation.midi_fader_3`
- `automation.midi_fader_4`
- `automation.midi_fader_5`
- `automation.midi_button_record`
- `automation.midi_key_pause`
- `automation.midi_key_play`
- `automation.midi_light_record`
- `automation.midi_knob_0_down`
- `automation.midi_knob_0_up`
- `automation.midi_fader_channel_0_button_square`

## Requirements

- The bridge host runs systemd unit `ha-midi` and accepts SSH as user `ha-midi`. Its address is kept in Home Assistant configuration, not in this repository.
- The private key is `/config/.ssh/id_ed25519` on the Home Assistant host. The command does not prompt for a passphrase.
- `/config/.ssh/known_hosts` on the Home Assistant host already contains the bridge host key. The command sets `UserKnownHostsFile` and does not accept a new key on its own. A missing host key makes the command fail.
- `sudo` for `ha-midi` permits `systemctl restart ha-midi` and no other command, with no password and no terminal.
- `shell_command` is configured in Home Assistant, with the key `ha_midi_restart`. Reload `shell_command` after editing `configuration.yaml`, or restart Home Assistant.
- The memory `input_text` and the Mosquitto running sensor from `examples/mosquitto_broker.md` are in place. The command does not pause the automations. The blueprint does.
