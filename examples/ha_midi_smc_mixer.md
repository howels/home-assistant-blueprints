# ha-midi SMC-Mixer

`blueprints/ha_midi_smc_mixer.yaml` replaces the separate ha-midi automations (one per fader, dial and key) with one automation. It controls lights and media players from an M-VAVE SMC-Mixer that reaches Home Assistant through the ha-midi bridge.

## How the bridge presents the mixer

The mixer runs in DAW mode and speaks the Mackie Control protocol. The bridge creates one MQTT device per MIDI port. Select the `HA-MIDI Bridge SINCO SMC-Mixer-Master` device. The `Private` port repeats the same controls and uses a different client number.

The bridge publishes under `ha-midi/ha-midi-bridge/<port>_<client>/`. The blueprint reads the `state` topics:

| Control | Topic leaf | Payload | Home Assistant entity |
|----|----|----|----|
| Fader 1 to 8 | `pb_0` to `pb_7` | 0 to 100 | `number` Pitch Bend Channel 0 to 7 |
| Dial 1 to 8 | `cc_016_00` to `cc_023_00` | `1` to `15` clockwise, `65` to `79` anticlockwise | `number` Control Change 016 to 023 |
| Key press | `button_state_NNN_00` | `ON`, then `OFF` on release | `binary_sensor` Note NNN State |
| Key light | `button_light_NNN_00` | `ON`, `OFF` | `light` Note NNN Light |

A dial sends the number of detents in the low six bits and the direction in bit six. A repeated direction leaves the `number` entity state unchanged, so a state trigger misses it. The blueprint triggers on the MQTT message instead.

Key and dial entities exist only after the control has been used once. The blueprint does not depend on them. It matches the topic, and it publishes key lights to the `set` topic of the `light` entity.

## Control names

| Name | Note or controller | Mackie Control function |
|----|----|----|
| Strip 1 to 8 Record | notes 0 to 7 | Rec/Rdy |
| Strip 1 to 8 Solo | notes 8 to 15 | Solo |
| Strip 1 to 8 Mute | notes 16 to 23 | Mute |
| Strip 1 to 8 Select | notes 24 to 31 | Select |
| Previous 8 tracks | notes 46 and 48 | Bank left, Channel left |
| Next 8 tracks | notes 47 and 49 | Bank right, Channel right |
| Rewind | note 91 | Rewind |
| Fast forward | note 92 | Fast forward |
| Stop | note 93 | Stop |
| Play | note 94 | Play |
| Record | note 95 | Record |
| Up, Down, Left, Right | notes 96 to 99 | Cursor |

The device has 43 keys: 32 strip keys and 11 transport keys. Set `log_events` on the blueprint to write each event to the system log as `Fader 1: 40` or `Strip 4 Select: ON`. The log shows which physical control sends which name.

Verified against the live bridge: notes 0, 8, 16, 24, 47, 93, 94, 95 and 98 exist, faders `pb_0` to `pb_7` exist, and dials `cc_016_00` to `cc_020_00` and `cc_023_00` exist. Inferred from the Mackie Control layout: the remaining strip notes, notes 46, 48, 49, 91, 92, 96, 97 and 99, and dials `cc_021_00` and `cc_022_00`. Controller `cc_030_00` has appeared and is not mapped.

## Safe volume

Faders and dials change volume at different speeds in each direction.

| Control | Rising | Falling |
|----|----|----|
| Fader | `volume_rise_rate`, default 4 %/s | `volume_fall_rate`, default 40 %/s |
| Dial detent or Up and Down keys | `volume_step_up`, default 1 % | `volume_step_down`, default 2 % |

A fader ramps in steps of half a second. The ramp starts when the fader has been still for `fader_debounce` (default 100 ms), so a drag produces one ramp from the final position. A new position stops the ramp in progress. The blueprint compares the fader position with the fader `number` entity of the device at every step. A ramp that finds a different position ends.

`max_volume` limits every control. A fader at the top sets the maximum. A player already above the maximum is not raised by a dial and can still be lowered.

A player that is off or reports no `volume_level` is skipped.

## Debouncing and sampling

Faders and dials emit 20 to 40 MQTT messages per second while moving. Slow lights such as WLED take roughly 140 ms per `light.turn_on` round-trip when idle. Without rate limiting, concurrent service calls queue on the light's web server, latency climbs past one second, and the automation hits its parallel run limit (`max: 60`, `max_exceeded: silent`), dropping further input. For relative dial steps, queued runs also read the same stale colour or brightness before the light updates, so reversing a dial causes queued runs in the old direction to fight the new direction for several seconds.

The blueprint coalesces incoming messages with two inputs in the advanced section: `fader_debounce` (default 100 ms) and `dial_debounce` (default 250 ms).

| Control | Target | Mechanism | Effect |
|----|----|----|----|
| Fader | Lights | Grid-sampled latest-wins: each message delays to the next `fader_debounce` clock boundary, then acts only if the fader `number` entity still matches its payload | At most one light command per interval while dragging; final position always lands within one interval |
| Fader | Media players | Trailing debounce: each message waits `fader_debounce`, then starts a ramp only if the fader `number` entity still matches its payload | A drag starts one ramp instead of overlapping ramps |
| Dial | Lights | Grid-sampled latest-wins: each message records `state_attr(this.entity_id, 'last_triggered')`, delays to the next `dial_debounce` clock boundary, and acts only if `last_triggered` has not advanced | At most one light command per 250 ms (4 per second), giving WLED time to report its new state before the next step reads it; direction reversals take effect on the next boundary |

If the device has no fader `number` entity, every fader message acts and nothing is skipped.

Key-light state triggers also filter to `to: null` (state changes only) plus a separate `attribute: is_volume_muted` trigger. Attribute-only updates from brightness or colour changes do not spawn parallel runs, keeping parallel slots free and preserving dial and fader traces.

## Strip functions

Each strip has one list of lights and media players. The fader and dial functions select what they change.

| Function | Lights | Media players |
|----|----|----|
| Automatic | Brightness | Volume |
| Brightness | Brightness, 0 turns the light off | None |
| Colour temperature | Kelvin across the light range (`color_temp_kelvin`) | None |
| Colour temperature via RGB | Warm-to-cool sweep sent as `rgb_color` | None |
| Hue | Hue, saturation kept | None |
| Saturation | Saturation, hue kept | None |
| Volume | None | Volume |
| Not used | None | None |

Set the fader to `brightness` and the dial to `volume` to drive a light and a media player from the same strip.

## Colour temperature via RGB

Some WLED RGB+CCT lights report `color_temp` support to Home Assistant while configured with auto-white mode set to Brighter (`rgbwm: 1`). When Home Assistant sends `color_temp_kelvin`, the WLED integration sends full white RGB (`[255, 255, 255]`) alongside `cct`, and WLED keeps RGB lit at full power alongside the white channel, washing out warm white. Selecting `colour_temp_rgb` sends `rgb_color` directly without reconfiguring WLED.

The curve does not use Home Assistant's Tanner Helland kelvin-to-RGB formula. Under WLED's default `2.8` colour gamma, Tanner Helland's low green values below 3000 K render as red rather than orange. Instead, both faders and dials share the `rgb_temp_stops` lookup table, steered through warm orange before dropping toward red at the bottom end:

| Position | RGB | Hue | Character |
|----|----|----|----|
| 0 % | `[255, 115, 0]` | 27° | Deep warm red-orange |
| 20 % | `[255, 158, 45]` | 32° | Rich orange |
| 40 % | `[255, 180, 95]` | 32° | Warm orange |
| 60 % | `[255, 196, 140]` | 29° | Soft warm orange-white |
| 85 % | `[255, 242, 238]` | — | Neutral warm white |
| 90 % | `[255, 250, 255]` | — | Pure white |
| 100 % | `[215, 242, 255]` | 200° | Cool daylight white |

Faders interpolate piecewise linearly across `rgb_temp_stops` from 0 to 100 %. Every stop has `max(rgb) == 255`, keeping brightness level across the sweep. Normalised blue rises strictly from `0` to `255` over 0 to 90 %, and normalised red falls strictly from `255` to `215` over 90 to 100 %. Dials invert the light's reported `rgb_color` back to a position on the same table (within 0.22 % round-trip error), add `dial_pct`, and interpolate the next RGB value.

## Key lights

The blueprint publishes key lights on three events: a state change of a transport media player or strip entity, Home Assistant start, and the bridge availability topic reporting `online`. A change of media position does not publish.

| Key light | On when |
|----|----|
| Play, Record | A transport player (a record player for Record) is `playing` |
| Stop | No transport player is `playing` |
| Select 1 to 8 | A strip light is on or a strip media player is `playing` |
| Mute 1 to 8 | A strip media player is muted, or the strip has lights and all are off |

## Replacing the existing automations

| Existing automation | Blueprint input |
|----|----|
| `Midi fader 0`, `1`, `2` | `strip_1_targets` to `strip_3_targets`, fader function `brightness` |
| `Midi fader 3` | `strip_4_targets` with `light.angle_lamp`, fader function `brightness` |
| `Midi fader 4` | `strip_5_targets` with `light.angle_lamp`, fader function `hue` |
| `Midi fader 5` | `strip_6_targets` with `light.angle_lamp`, fader function `saturation` |
| `Midi key play`, `Midi key pause` | `media_players` with Play and Stop |
| `Midi button record`, `Midi light record` | `record_media_players` |
| `study media play`, `study media paused` | Key lights of Play and Stop |
| `Midi knob 0 up`, `Midi knob 0 down` | `strip_1_targets` with a media player, dial function `volume` |
| `Midi fader channel 0 button square` | Not replaced. Select 1 toggles play and pause of the strip media players. It does not change the source |

Fader 6 sets saturation directly. `Midi fader 5` set saturation to 100 minus the fader position.

The `ha-midi restart when MQTT starts` automation holds the old automations off during a bridge restart. Replace its `automations` list with the single entity of the new automation.

## Example

```yaml
- id: ha_midi_smc_mixer
  alias: HA-MIDI SMC-Mixer
  use_blueprint:
    path: howels/ha_midi_smc_mixer.yaml
    input:
      device: MIXER_DEVICE_ID
      media_players:
        - media_player.study_amplifier
        - media_player.study_amplifier_4
      record_media_players:
        - media_player.ledfx_ledfx_lan_media_player
      strip_1_targets:
        - light.wled_ceiling_light
        - media_player.study_amplifier_2
      strip_1_fader: brightness
      strip_1_dial: volume
      strip_2_targets:
        - light.front_desk_wled
      strip_3_targets:
        - light.wled_gl_c_616wl
      strip_4_targets:
        - light.angle_lamp
      strip_5_targets:
        - light.angle_lamp
      strip_5_fader: hue
      strip_6_targets:
        - light.angle_lamp
      strip_6_fader: saturation
```

`MIXER_DEVICE_ID` is the device identifier of the Master device. The blueprint form selects it from a list.

## Requirements

- The ha-midi bridge publishes the mixer to MQTT with Home Assistant discovery. The MQTT device has the manufacturer `HA-MIDI`.
- The selected device has a `number` entity for each fader that is used. The blueprint finds it by the name suffix `_pitch_bend_channel_N`.
- The bridge accepts `ON` and `OFF` on `button_light_NNN_00/set`.
- The bridge restarts republish retained control state. Turn the automation off while the bridge restarts. The blueprint `pause_automations_on_service_restart.yaml` does this.
