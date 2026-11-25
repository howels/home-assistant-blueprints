# PANDA ESL blueprints

Five blueprints draw a dashboard on a PANDA / ETAG Bluetooth e-paper label through the PANDA ESL integration (`https://github.com/moryoav/ha-panda`). Each blueprint builds a payload and calls `panda_esl.write_guarded` or `panda_esl.write`.

| Blueprint | Draws |
|----|----|
| `panda_esl_weather.yaml` | Current weather and a three day forecast. |
| `panda_esl_todo.yaml` | Open items of one to-do entity, with due dates. |
| `panda_esl_calendar.yaml` | Events of one or more calendars. |
| `panda_esl_agenda.yaml` | Events and open to-do items together, with a divider between the two lists. |
| `panda_esl_alerts.yaml` | Watched entities that are in a problem state. |

## Prerequisites

1. Install the PANDA ESL integration and add the label as a device.
2. Set the blueprint resolution to the label model: 256 x 128 (ETAG-525), 296 x 152 (ETAG-526), 360 x 240 (ETAG-530), or 400 x 300 (ETAG-534).
3. For the agenda, calendar, and to-do blueprints, add the calendar and to-do integrations. Google Calendar creates one calendar entity per Google calendar. Google Tasks creates one to-do entity per task list.

## Import

In Home Assistant, open Settings > Automations & scenes > Blueprints > Import blueprint. Enter the URL for one blueprint:

```
https://github.com/howels/home-assistant-blueprints/blob/main/blueprints/panda_esl_agenda.yaml
```

Replace `panda_esl_agenda.yaml` with the file name of another blueprint from the table. Import again after each repository update, then reload automations.

## Agenda layout

`panda_esl_agenda.yaml` calls `calendar.get_events` once for all selected calendars and `todo.get_items` once for all selected to-do entities.

| Part | Content |
|----|----|
| Header | Title and the date. |
| Events | Time column and summary, sorted by start time. Events that start today are red. |
| Divider | One black line, drawn only when both lists have rows. |
| Tasks | Checkbox, summary, and due date. An overdue date is red. Items with no due date follow the dated items. |
| Last row | `+N more` in red when more entries exist than rows fit. |

The rows are shared. When both lists are long, each keeps at least half of the rows. A short list leaves its unused rows to the other.

The automation writes at Home Assistant start, when a calendar or to-do entity changes state, and on the update interval. It skips the write when both services fail.

## Colours

The label shows black, white, and red. The renderer reduces every image to those three colours:

| Source pixel | Result |
|----|----|
| Red component above 128 and blue component below 128 | Red. Yellow and orange become red. |
| Luminance below 128 | Black. |
| Anything else | White. |

The label has no yellow layer. The blueprints use red for today's events, overdue dates, the alert header, the umbrella when rain is forecast, and the `+N more` row.

## Emoji

The text font has no emoji glyphs. With icon style emoji, the blueprints draw each emoji as an OpenMoji PNG through the `dlimg` element, up to three before each row. The image URL input holds one URL with `{code}` in place of the upper-case hexadecimal code point:

```
https://cdn.jsdelivr.net/gh/hfg-gmuend/openmoji@15.1.0/color/72x72/{code}.png
```

- The integration downloads each PNG at every write. A failed download aborts the write. Set Emoji in text to Strip to draw the text without emoji.
- Copy the OpenMoji `color/72x72` folder to the Home Assistant host, or to `config/www`, and enter a file path to avoid the download.
- Replace `color` with `black` in the URL for an all-black set.
- Emoji with no single code point file, such as flags and skin-tone sequences, are removed from the text.
- OpenMoji is licensed CC BY-SA 4.0.

### Brown emoji

The brown circle (`1F7E4`) and the brown square (`1F7EB`) have no colour on the panel. With Dither brown emoji on, the blueprint draws a checkerboard of red and black pixels with a black outline, which reads as dark red. The black circle (`26AB`) stays solid black.

The renderer resamples any image that is not drawn at its own size. Each dither image is therefore a PNG data URL at the exact emoji size. Emoji sizes are even numbers from 10 to 36 pixels:

| Resolution | Emoji size |
|----|----|
| 256 x 128 | 12 |
| 296 x 152 | 14 |
| 360 x 240 | 22 |
| 400 x 300 | 28 |

`tools/panda_dither_png.py` prints the images as a YAML block, for a different size or shape.

## Tests

`tests/test_panda_esl_*.py` run each blueprint in a real Home Assistant core with fake `get_items`, `get_events`, and write services. `tests/test_panda_esl_real_entities.py` uses the real to-do and calendar components. Setting `PANDA_PAYLOAD_DIR` writes each payload as JSON, which the ha-panda renderer can draw to a PNG.
