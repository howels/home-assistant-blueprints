"""Tests for blueprints/panda_esl_agenda.yaml."""
from datetime import timedelta

import pytest
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from panda_helpers import add_automation, icons, images, in_canvas, install, pump, register_write, run, texts, visible

CAL = ["calendar.family", "calendar.work"]
TODO = ["todo.shopping", "todo.jobs"]


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
            ]
        },
        "calendar.work": {
            "events": [
                {"start": (now + timedelta(hours=2)).isoformat(), "end": (now + timedelta(hours=3)).isoformat(), "summary": "Team stand-up"},
                {"start": (now - timedelta(minutes=10)).isoformat(), "end": (now + timedelta(minutes=20)).isoformat(), "summary": "Review"},
            ]
        },
    }


def tasks():
    today = dt_util.now().date()
    return {
        "todo.shopping": {"items": [
            {"summary": "Milk", "uid": "1", "status": "needs_action"},
            {"summary": "Book dentist", "uid": "2", "status": "needs_action", "due": today.isoformat()},
        ]},
        "todo.jobs": {"items": [
            {"summary": "Pay tax", "uid": "3", "status": "needs_action", "due": (today - timedelta(days=3)).isoformat()},
        ]},
    }


async def setup(hass, inputs=None, ev=None, td=None, fail_events=False, fail_todo=False):
    install(hass, "panda_esl_agenda.yaml")
    calls = register_write(hass)
    gets = {"events": [], "items": []}

    async def get_events(call):
        gets["events"].append(dict(call.data))
        if fail_events:
            raise HomeAssistantError("calendar unavailable")
        return ev if ev is not None else events()

    async def get_items(call):
        gets["items"].append(dict(call.data))
        if fail_todo:
            raise HomeAssistantError("todo unavailable")
        return td if td is not None else tasks()

    hass.services.async_register("calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY)
    hass.services.async_register("todo", "get_items", get_items, supports_response=SupportsResponse.ONLY)
    for c in CAL:
        hass.states.async_set(c, "off")
    for t in TODO:
        hass.states.async_set(t, "2")
    await add_automation(
        hass, "panda_esl_agenda.yaml", {"calendars": CAL, "todo_entities": TODO, **(inputs or {})}
    )
    return calls, gets


def summaries(data, names):
    return [x for x in texts(data) if x in names]


async def test_events_then_divider_then_tasks(hass):
    calls, gets = await setup(hass)
    service, data = await run(hass, calls)
    assert service == "write_guarded"
    assert gets["events"][0]["entity_id"] == CAL
    assert gets["items"][0]["entity_id"] == TODO
    assert gets["items"][0]["status"] == "needs_action"
    t = texts(data)
    assert t[:2] == ["Agenda", "Wed 25 Nov"]
    assert summaries(data, {"Review", "Team stand-up", "Bin day", "Pay tax", "Book dentist", "Milk"}) == [
        "Review", "Team stand-up", "Bin day", "Pay tax", "Book dentist", "Milk",
    ]
    # Time today, short day name for later days, no day for an item due today.
    assert {"Now", "14:00", "Thu", "Sun 22"} <= set(t)
    assert not {"Tom", "Tomorrow", "Today"} & set(t)
    lines = [e for e in visible(data) if e["type"] == "line"]
    assert len(lines) == 1
    boxes = [e for e in visible(data) if e["type"] == "rectangle" and e.get("width") == 2]
    assert len(boxes) == 3
    assert lines[0]["y_start"] < min(b["y_start"] for b in boxes)
    assert icons(data) == ["calendar-check"]
    in_canvas(data, 360, 240)


async def test_red_marks_today_events_and_overdue_tasks(hass):
    calls, _ = await setup(hass)
    _, data = await run(hass, calls)
    red = [e["value"] for e in data["payload"] if e.get("color") == "red"]
    # Now and 14:00 start today. The dentist is due today and has no label. The tax is overdue.
    assert red == ["Now", "14:00", "Sun 22"]


async def test_day_name_is_at_the_start_of_a_later_event(hass):
    now = dt_util.now()
    ev = {"calendar.work": {"events": [
        {"start": (now + timedelta(days=1, hours=-3)).isoformat(), "end": (now + timedelta(days=1)).isoformat(), "summary": "Dentist"},
        {"start": (now + timedelta(days=9)).date().isoformat(), "end": (now + timedelta(days=10)).date().isoformat(), "summary": "Far"},
    ]}}
    calls, _ = await setup(hass, ev=ev, td={t: {"items": []} for t in TODO}, inputs={"days_ahead": 14})
    _, data = await run(hass, calls)
    assert "Thu 09:00" in texts(data)
    assert "Fri 04" in texts(data)  # more than a week ahead: day name and date


async def test_event_and_task_text_each_align_in_their_own_column(hass):
    calls, _ = await setup(hass)
    _, data = await run(hass, calls)
    xs = {e["value"]: e["x"] for e in visible(data) if e["type"] == "text" and e.get("anchor") == "lm"}
    assert xs["Review"] == xs["Team stand-up"] == xs["Bin day"]
    assert xs["Pay tax"] == xs["Book dentist"] == xs["Milk"]
    box = [e for e in visible(data) if e["type"] == "rectangle" and e.get("width") == 2][0]
    assert xs["Sun 22"] == box["x_end"] + 4  # the day name follows the checkbox


async def test_checkbox_is_close_to_the_text_when_no_item_has_a_day(hass):
    td = {"todo.shopping": {"items": [{"summary": "Milk", "uid": "1", "status": "needs_action"}]}}
    calls, _ = await setup(hass, td=td)
    _, data = await run(hass, calls)
    box = [e for e in visible(data) if e["type"] == "rectangle" and e.get("width") == 2][0]
    milk = [e for e in visible(data) if e["type"] == "text" and e["value"] == "Milk"][0]
    assert milk["x"] - box["x_end"] <= 8


async def test_events_only_has_no_divider(hass):
    calls, _ = await setup(hass, td={t: {"items": []} for t in TODO})
    _, data = await run(hass, calls)
    assert [e for e in visible(data) if e["type"] == "line"] == []
    assert "Review" in texts(data)


async def test_tasks_only_has_no_divider(hass):
    calls, _ = await setup(hass, ev={c: {"events": []} for c in CAL})
    _, data = await run(hass, calls)
    assert [e for e in visible(data) if e["type"] == "line"] == []
    assert "Milk" in texts(data)


async def test_empty(hass):
    calls, _ = await setup(hass, ev={c: {"events": []} for c in CAL}, td={t: {"items": []} for t in TODO})
    _, data = await run(hass, calls)
    assert "Nothing planned" in texts(data)
    assert icons(data) == ["calendar-check", "check-circle-outline"]


async def test_long_lists_share_the_rows(hass):
    now = dt_util.now()
    many_events = {"calendar.work": {"events": [
        {"start": (now + timedelta(hours=1 + i)).isoformat(), "end": (now + timedelta(hours=2 + i)).isoformat(), "summary": f"Event {i}"}
        for i in range(6)
    ]}}
    many_tasks = {"todo.shopping": {"items": [
        {"summary": f"Task {i}", "uid": str(i), "status": "needs_action"} for i in range(6)
    ]}}
    calls, _ = await setup(hass, ev=many_events, td=many_tasks)
    _, data = await run(hass, calls)
    t = texts(data)
    assert [x for x in t if x.startswith("Event")] == ["Event 0", "Event 1", "Event 2"]
    assert [x for x in t if x.startswith("Task")] == ["Task 0", "Task 1", "Task 2"]
    assert "+6 more" in t
    in_canvas(data, 360, 240)


async def test_short_list_leaves_its_rows_to_the_other(hass):
    now = dt_util.now()
    one_event = {"calendar.work": {"events": [
        {"start": (now + timedelta(hours=1)).isoformat(), "end": (now + timedelta(hours=2)).isoformat(), "summary": "Only event"}
    ]}}
    many_tasks = {"todo.shopping": {"items": [
        {"summary": f"Task {i}", "uid": str(i), "status": "needs_action"} for i in range(9)
    ]}}
    calls, _ = await setup(hass, ev=one_event, td=many_tasks)
    _, data = await run(hass, calls)
    t = texts(data)
    assert "Only event" in t
    assert len([x for x in t if x.startswith("Task")]) == 5
    assert "+4 more" in t


@pytest.mark.parametrize("size,w,h", [("256x128", 256, 128), ("296x152", 296, 152), ("360x240", 360, 240), ("400x300", 400, 300)])
async def test_sizes(hass, size, w, h):
    calls, _ = await setup(hass, {"display_size": size})
    _, data = await run(hass, calls)
    in_canvas(data, w, h)


async def test_emoji_style_and_brown_dither(hass):
    td = {"todo.shopping": {"items": [
        {"summary": "Black \u26ab bin day", "uid": "1", "status": "needs_action"},
        {"summary": "Brown \U0001F7E4 bin day", "uid": "2", "status": "needs_action"},
    ]}}
    calls, _ = await setup(hass, {"icon_style": "emoji"}, td=td)
    _, data = await run(hass, calls)
    assert icons(data) == []
    names = images(data)
    assert names[0] == "1F4C5"  # header glyph
    assert names[1:] == ["26AB", "dither:disc:20"]
    assert {"Black bin day", "Brown bin day"} <= set(texts(data))
    in_canvas(data, 360, 240)


async def test_emoji_in_events_is_drawn_before_the_text(hass):
    now = dt_util.now()
    ev = {"calendar.work": {"events": [
        {"start": (now + timedelta(hours=1)).isoformat(), "end": (now + timedelta(hours=2)).isoformat(), "summary": "Bin \U0001F6AE day"}
    ]}}
    calls, _ = await setup(hass, ev=ev, td={t: {"items": []} for t in TODO})
    _, data = await run(hass, calls)
    assert images(data) == ["1F6AE"]
    pic = [e for e in visible(data) if e["type"] == "dlimg"][0]
    text = [e for e in visible(data) if e["type"] == "text" and e["value"] == "Bin day"][0]
    assert pic["x"] + pic["xsize"] <= text["x"]


async def test_strip_mode(hass):
    td = {"todo.shopping": {"items": [{"summary": "Brown \U0001F7E4 bin day", "uid": "1", "status": "needs_action"}]}}
    calls, _ = await setup(hass, {"emoji_mode": "strip"}, td=td, ev={c: {"events": []} for c in CAL})
    _, data = await run(hass, calls)
    assert images(data) == []
    assert "Brown bin day" in texts(data)


async def test_one_failing_service_still_writes(hass):
    calls, _ = await setup(hass, fail_events=True)
    _, data = await run(hass, calls)
    t = texts(data)
    assert "Milk" in t and "Review" not in t


async def test_both_services_failing_does_not_write(hass):
    calls, _ = await setup(hass, fail_events=True, fail_todo=True)
    await hass.services.async_call(
        "automation", "trigger", {"entity_id": "automation.label", "skip_condition": False}, blocking=False
    )
    await pump()
    assert calls == []


@pytest.mark.parametrize("entity,state", [("calendar.work", "on"), ("todo.shopping", "3")])
async def test_state_change_writes(hass, entity, state):
    calls, _ = await setup(hass, {"settle_seconds": 0})
    hass.states.async_set(entity, state)
    await pump()
    assert len(calls) == 1


async def test_long_summary_wraps_when_rows_are_spare(hass):
    now = dt_util.now()
    long = "El in the office (book keeping and more)"
    ev = {"calendar.work": {"events": [
        {"start": (now + timedelta(hours=1)).isoformat(), "end": (now + timedelta(hours=2)).isoformat(), "summary": long},
        {"start": (now + timedelta(hours=3)).isoformat(), "end": (now + timedelta(hours=4)).isoformat(), "summary": "Second"},
    ]}}
    td = {"todo.shopping": {"items": [{"summary": "Milk", "uid": "1", "status": "needs_action"}]}}
    calls, _ = await setup(hass, ev=ev, td=td)
    _, data = await run(hass, calls)
    first = [e for e in visible(data) if e["type"] == "text" and e["value"] == "El in the office (book"][0]
    rest = [e for e in visible(data) if e["type"] == "text" and e["value"] == "keeping and more)"][0]
    assert rest["x"] == first["x"]
    assert rest["y"] > first["y"]
    second = [e for e in visible(data) if e["type"] == "text" and e["value"] == "Second"][0]
    assert second["y"] > rest["y"]  # the next row moves down
    milk = [e for e in visible(data) if e["type"] == "text" and e["value"] == "Milk"][0]
    assert milk["y"] > second["y"]
    in_canvas(data, 360, 240)


async def test_long_summary_is_cut_when_no_row_is_spare(hass):
    now = dt_util.now()
    long = "El in the office (book keeping and the rest of the day)"
    ev = {"calendar.work": {"events": [
        {"start": (now + timedelta(hours=1 + i)).isoformat(), "end": (now + timedelta(hours=2 + i)).isoformat(), "summary": long if i == 0 else f"Event {i}"}
        for i in range(9)
    ]}}
    calls, _ = await setup(hass, ev=ev, td={t: {"items": []} for t in TODO})
    _, data = await run(hass, calls)
    cut = [x for x in texts(data) if x.startswith("El in")]
    assert len(cut) == 1 and cut[0].endswith("…")


async def test_emoji_do_not_overlap_and_sit_before_the_text(hass):
    now = dt_util.now()
    ev = {"calendar.work": {"events": [
        {"start": (now + timedelta(hours=1)).isoformat(), "end": (now + timedelta(hours=2)).isoformat(), "summary": "Bob \U0001F43E\U0001F496 and Donna"}
    ]}}
    calls, _ = await setup(hass, ev=ev, td={t: {"items": []} for t in TODO})
    _, data = await run(hass, calls)
    pics = [e for e in visible(data) if e["type"] == "dlimg"]
    text = [e for e in visible(data) if e["type"] == "text" and e["value"] == "Bob and Donna"][0]
    assert pics[0]["x"] + pics[0]["xsize"] == pics[1]["x"]  # no gap between emoji
    assert text["x"] - (pics[1]["x"] + pics[1]["xsize"]) == 3
    assert pics[0]["xsize"] == 20
