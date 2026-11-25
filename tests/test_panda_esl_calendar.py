"""Tests for blueprints/panda_esl_calendar.yaml."""
from datetime import timedelta

import pytest
from homeassistant.core import SupportsResponse
from homeassistant.util import dt as dt_util

from panda_helpers import add_automation, icons, in_canvas, install, pump, register_write, run, texts, visible

CAL = ["calendar.family", "calendar.work"]

@pytest.fixture(autouse=True)
def midday(freezer):
    """Local midday, so that events two hours ahead stay on the same day."""
    freezer.move_to("2026-11-25 20:00:00+00:00")



def events():
    now = dt_util.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "calendar.family": {
            "events": [
                {"start": (today + timedelta(days=1)).date().isoformat(), "end": (today + timedelta(days=2)).date().isoformat(), "summary": "Bin day"},
                {"start": (today + timedelta(days=2, hours=9, minutes=30)).isoformat(), "end": (today + timedelta(days=2, hours=10)).isoformat(), "summary": "Dentist"},
            ]
        },
        "calendar.work": {
            "events": [
                {"start": (now + timedelta(hours=2)).isoformat(), "end": (now + timedelta(hours=3)).isoformat(), "summary": "Team stand-up"},
                {"start": (now - timedelta(minutes=10)).isoformat(), "end": (now + timedelta(minutes=20)).isoformat(), "summary": "Review"},
                {"start": today.date().isoformat(), "end": (today + timedelta(days=1)).date().isoformat(), "summary": "Holiday"},
            ]
        },
    }


async def setup(hass, inputs=None, data=None):
    install(hass, "panda_esl_calendar.yaml")
    calls = register_write(hass)
    gets = []

    async def get_events(call):
        gets.append(dict(call.data))
        return data if data is not None else events()

    hass.services.async_register("calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY)
    for c in CAL:
        hass.states.async_set(c, "off")
    await add_automation(hass, "panda_esl_calendar.yaml", {"calendars": CAL, **(inputs or {})})
    return calls, gets


async def test_agenda(hass):
    calls, gets = await setup(hass)
    _, data = await run(hass, calls)
    assert gets[0]["entity_id"] == CAL
    assert dt_util.parse_datetime(gets[0]["end_date_time"]) > dt_util.now() + timedelta(days=3)
    t = texts(data)
    summaries = [x for x in t if x in {"Holiday", "Review", "Team stand-up", "Bin day", "Dentist"}]
    assert summaries == ["Holiday", "Review", "Team stand-up", "Bin day", "Dentist"]
    assert "Today" in t and "Now" in t and "Tomorrow" in t
    assert (dt_util.now() + timedelta(days=2)).strftime("%a") + " 09:30" in t
    assert (dt_util.now() + timedelta(hours=2)).strftime("%H:%M") in t
    red = [e["value"] for e in visible(data) if e.get("color") == "red"]
    assert red == ["Today", "Now", (dt_util.now() + timedelta(hours=2)).strftime("%H:%M")]
    assert icons(data) == ["calendar-month"]
    in_canvas(data, 360, 240)


async def test_days_ahead_limits_request(hass):
    calls, gets = await setup(hass, {"days_ahead": 0})
    await run(hass, calls)
    end = dt_util.parse_datetime(gets[0]["end_date_time"])
    assert end.date() == (dt_util.now() + timedelta(days=1)).date()
    assert end.hour == 0


async def test_empty(hass):
    calls, _ = await setup(hass, data={c: {"events": []} for c in CAL})
    _, data = await run(hass, calls)
    assert "No events" in texts(data)
    assert "calendar-check" in icons(data)


async def test_overflow(hass):
    now = dt_util.now()
    many = {CAL[0]: {"events": [
        {"start": (now + timedelta(hours=i + 1)).isoformat(), "end": (now + timedelta(hours=i + 2)).isoformat(),
         "summary": f"Event {i} with a long and wordy summary that will not fit on the line"}
        for i in range(12)
    ]}}
    calls, _ = await setup(hass, data=many)
    _, data = await run(hass, calls)
    t = texts(data)
    assert t[-1] == "+6 more"
    assert any(x.endswith("\u2026") for x in t)
    in_canvas(data, 360, 240)


@pytest.mark.parametrize("size,w,h", [("256x128", 256, 128), ("296x152", 296, 152), ("400x300", 400, 300)])
async def test_sizes(hass, size, w, h):
    calls, _ = await setup(hass, {"display_size": size})
    _, data = await run(hass, calls)
    in_canvas(data, w, h)


async def test_emoji(hass):
    calls, _ = await setup(hass, {"icon_style": "emoji"})
    _, data = await run(hass, calls)
    assert icons(data) == []
    assert "\U0001F4C5" in texts(data)


async def test_calendar_state_change_writes(hass):
    calls, _ = await setup(hass, {"settle_seconds": 0})
    hass.states.async_set("calendar.work", "on")
    await pump()
    assert len(calls) == 1


async def test_emoji_is_stripped(hass):
    now = dt_util.now()
    data_in = {CAL[0]: {"events": [
        {"start": (now + timedelta(hours=1)).isoformat(), "end": (now + timedelta(hours=2)).isoformat(),
         "summary": "Bob with auntie Donna \U0001F43E\U0001F496", "status": "confirmed"},
    ]}}
    calls, _ = await setup(hass, data=data_in)
    _, data = await run(hass, calls)
    assert "Bob with auntie Donna" in texts(data)
