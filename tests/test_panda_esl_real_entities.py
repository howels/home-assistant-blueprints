"""Run the to-do and calendar blueprints against real Home Assistant todo and calendar entities.

The other tests register fake get_items and get_events services. These tests use the real services,
so the response shape and the date formats come from Home Assistant core.
"""
from datetime import timedelta

import pytest
from homeassistant.components import calendar, todo
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from panda_helpers import add_automation, icons, in_canvas, install, register_write, run, texts


@pytest.fixture(autouse=True)
def midday(freezer):
    freezer.move_to("2026-11-25 20:00:00+00:00")


class FakeTodo(TodoListEntity):
    _attr_has_entity_name = True
    _attr_name = "My Tasks"
    _attr_unique_id = "tasks"

    def __init__(self, items):
        self._attr_todo_items = items


class FakeCalendar(CalendarEntity):
    _attr_has_entity_name = True

    def __init__(self, name, events):
        self._attr_name = name
        self._attr_unique_id = name
        self._events = events

    @property
    def event(self):
        return None

    async def async_get_events(self, hass, start_date, end_date):
        return [e for e in self._events if e.end_datetime_local > start_date and e.start_datetime_local < end_date]


async def test_todo_with_real_entity(hass):
    today = dt_util.now().date()
    entity = FakeTodo(
        [
            TodoItem(summary="Pay bill", uid="1", status=TodoItemStatus.NEEDS_ACTION, due=today - timedelta(days=3)),
            TodoItem(summary="Call plumber", uid="2", status=TodoItemStatus.NEEDS_ACTION, due=dt_util.now() + timedelta(days=1)),
            TodoItem(summary="Milk", uid="3", status=TodoItemStatus.NEEDS_ACTION),
            TodoItem(summary="Done already", uid="4", status=TodoItemStatus.COMPLETED),
        ]
    )
    assert await async_setup_component(hass, "todo", {})
    await hass.data[todo.DATA_COMPONENT].async_add_entities([entity])
    install(hass, "panda_esl_todo.yaml")
    calls = register_write(hass)
    await add_automation(hass, "panda_esl_todo.yaml", {"todo_entity": entity.entity_id})
    _, data = await run(hass, calls)
    t = texts(data)
    assert t[:2] == ["My Tasks", "3 left"]
    assert [x for x in t if x in {"Pay bill", "Call plumber", "Milk", "Done already"}] == ["Pay bill", "Call plumber", "Milk"]
    assert "Tomorrow" in t
    assert "Sun 22 Nov" in t
    red = [e["value"] for e in data["payload"] if e.get("color") == "red"]
    assert red == ["Sun 22 Nov"]
    in_canvas(data, 360, 240)


async def test_calendar_with_real_entities(hass):
    now = dt_util.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    family = FakeCalendar(
        "Family",
        [
            CalendarEvent(start=(midnight + timedelta(days=1)).date(), end=(midnight + timedelta(days=2)).date(), summary="Bin day"),
            CalendarEvent(start=now + timedelta(days=2, hours=-3), end=now + timedelta(days=2, hours=-2), summary="Dentist"),
        ],
    )
    work = FakeCalendar(
        "Work",
        [
            CalendarEvent(start=now + timedelta(hours=2), end=now + timedelta(hours=3), summary="Stand-up"),
            CalendarEvent(start=now - timedelta(minutes=10), end=now + timedelta(minutes=20), summary="Review"),
            CalendarEvent(start=now + timedelta(days=9), end=now + timedelta(days=9, hours=1), summary="Beyond the window"),
        ],
    )
    assert await async_setup_component(hass, "calendar", {})
    await hass.data[calendar.DATA_COMPONENT].async_add_entities([family, work])
    install(hass, "panda_esl_calendar.yaml")
    calls = register_write(hass)
    await add_automation(hass, "panda_esl_calendar.yaml", {"calendars": [family.entity_id, work.entity_id]})
    _, data = await run(hass, calls)
    t = texts(data)
    assert [x for x in t if x in {"Bin day", "Dentist", "Stand-up", "Review", "Beyond the window"}] == [
        "Review", "Stand-up", "Bin day", "Dentist",
    ]
    assert {"Now", "Tomorrow"} <= set(t)
    assert icons(data) == ["calendar-month"]
    in_canvas(data, 360, 240)
