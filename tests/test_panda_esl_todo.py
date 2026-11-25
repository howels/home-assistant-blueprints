"""Tests for blueprints/panda_esl_todo.yaml."""
import pytest
from homeassistant.core import SupportsResponse
from homeassistant.util import dt as dt_util

from panda_helpers import add_automation, in_canvas, icons, images, install, pump, register_write, run, texts, visible

TODO = "todo.shopping"

@pytest.fixture(autouse=True)
def midday(freezer):
    """Local midday, so that events two hours ahead stay on the same day."""
    freezer.move_to("2026-11-25 20:00:00+00:00")



def items(n, overdue=True):
    today = dt_util.now().date()
    rows = [
        {"summary": "Pay council tax", "uid": "1", "status": "needs_action", "due": (today.replace(day=1) if overdue and today.day > 1 else today).isoformat()},
        {"summary": "Book dentist", "uid": "2", "status": "needs_action", "due": today.isoformat()},
        {"summary": "Milk", "uid": "3", "status": "needs_action"},
    ]
    rows += [{"summary": f"Item number {i} with a rather long summary that cannot fit the row", "uid": str(i), "status": "needs_action"} for i in range(4, n + 1)]
    return rows[:n]


async def setup(hass, n=3, inputs=None):
    install(hass, "panda_esl_todo.yaml")
    calls = register_write(hass)
    gets = []

    async def get_items(call):
        gets.append(dict(call.data))
        return {TODO: {"items": items(n)}}

    hass.services.async_register("todo", "get_items", get_items, supports_response=SupportsResponse.ONLY)
    hass.states.async_set(TODO, str(n), {"friendly_name": "Shopping"})
    await add_automation(hass, "panda_esl_todo.yaml", {"todo_entity": TODO, **(inputs or {})})
    return calls, gets


async def test_rows(hass):
    calls, gets = await setup(hass)
    service, data = await run(hass, calls)
    assert gets == [{"entity_id": [TODO], "status": "needs_action"}]
    t = texts(data)
    assert t[:2] == ["Shopping", "3 left"]
    assert "Pay council tax" in t and "Book dentist" in t and "Milk" in t
    assert "Today" in t
    red = [e["value"] for e in visible(data) if e.get("color") == "red"]
    assert len(red) == (1 if dt_util.now().day > 1 else 0)
    assert icons(data) == ["format-list-checks"]
    in_canvas(data, 360, 240)


async def test_overflow_and_truncation(hass):
    calls, _ = await setup(hass, n=12)
    _, data = await run(hass, calls)
    t = texts(data)
    assert t[-1] == "+6 more"
    assert any(x.endswith("\u2026") for x in t)
    in_canvas(data, 360, 240)
    assert sum(1 for e in visible(data) if e["type"] == "rectangle") == 1 + 6


async def test_max_items(hass):
    calls, _ = await setup(hass, n=5, inputs={"max_items": 3})
    _, data = await run(hass, calls)
    assert texts(data)[-1] == "+3 more"


async def test_empty(hass):
    calls, _ = await setup(hass, n=0)
    _, data = await run(hass, calls)
    assert "Nothing to do" in texts(data)
    assert "0 left" in texts(data)
    assert "check-circle-outline" in icons(data)


@pytest.mark.parametrize("size,w,h", [("256x128", 256, 128), ("296x152", 296, 152), ("400x300", 400, 300)])
async def test_sizes(hass, size, w, h):
    calls, _ = await setup(hass, n=12, inputs={"display_size": size})
    _, data = await run(hass, calls)
    in_canvas(data, w, h)


async def test_emoji(hass):
    calls, _ = await setup(hass, inputs={"icon_style": "emoji"})
    _, data = await run(hass, calls)
    assert icons(data) == []
    assert images(data) == ["2705"]
    in_canvas(data, 360, 240)


async def test_state_change_waits_then_writes(hass):
    calls, _ = await setup(hass, inputs={"settle_seconds": 0})
    hass.states.async_set(TODO, "4", {"friendly_name": "Shopping"})
    await pump()
    assert len(calls) == 1


async def test_skipped_when_unavailable(hass):
    calls, _ = await setup(hass)
    hass.states.async_set(TODO, "unavailable")
    await pump()
    assert calls == []


async def test_emoji_is_drawn_as_images_and_text_trimmed(hass):
    install(hass, "panda_esl_todo.yaml")
    calls = register_write(hass)

    async def get_items(call):
        return {TODO: {"items": [
            {"summary": "Black \u26ab\U0001F6AE bin day", "uid": "1", "status": "needs_action", "due": "2026-11-26"},
            {"summary": "Brown \U0001F7E4\U0001F6AE bin day ", "uid": "2", "status": "needs_action", "due": "2026-11-26"},
        ]}}

    hass.services.async_register("todo", "get_items", get_items, supports_response=SupportsResponse.ONLY)
    hass.states.async_set(TODO, "2", {"friendly_name": "My tasks"})
    await add_automation(hass, "panda_esl_todo.yaml", {"todo_entity": TODO})
    _, data = await run(hass, calls)
    t = texts(data)
    assert "Black bin day" in t and "Brown bin day" in t
    assert t.count("Tomorrow") == 2
    assert images(data) == ["26AB", "1F6AE", "1F7E4", "1F6AE"]
    in_canvas(data, 360, 240)


async def test_emoji_is_stripped_in_strip_mode(hass):
    install(hass, "panda_esl_todo.yaml")
    calls = register_write(hass)

    async def get_items(call):
        return {TODO: {"items": [{"summary": "Bin \U0001F6AE day ", "uid": "1", "status": "needs_action"}]}}

    hass.services.async_register("todo", "get_items", get_items, supports_response=SupportsResponse.ONLY)
    hass.states.async_set(TODO, "1", {"friendly_name": "My tasks"})
    await add_automation(hass, "panda_esl_todo.yaml", {"todo_entity": TODO, "emoji_mode": "strip"})
    _, data = await run(hass, calls)
    assert "Bin day" in texts(data)
    assert images(data) == []


async def test_unsupported_emoji_is_dropped(hass):
    install(hass, "panda_esl_todo.yaml")
    calls = register_write(hass)

    async def get_items(call):
        # Regional indicators (a flag) and a skin-tone modifier have no single OpenMoji file.
        return {TODO: {"items": [{"summary": "Flag \U0001F1EC\U0001F1E7 \U0001F3FD day", "uid": "1", "status": "needs_action"}]}}

    hass.services.async_register("todo", "get_items", get_items, supports_response=SupportsResponse.ONLY)
    hass.states.async_set(TODO, "1", {"friendly_name": "My tasks"})
    await add_automation(hass, "panda_esl_todo.yaml", {"todo_entity": TODO})
    _, data = await run(hass, calls)
    assert "Flag day" in texts(data)
    assert images(data) == []


async def test_custom_emoji_url(hass):
    install(hass, "panda_esl_todo.yaml")
    calls = register_write(hass)

    async def get_items(call):
        return {TODO: {"items": [{"summary": "Bin \U0001F6AE day", "uid": "1", "status": "needs_action"}]}}

    hass.services.async_register("todo", "get_items", get_items, supports_response=SupportsResponse.ONLY)
    hass.states.async_set(TODO, "1", {"friendly_name": "My tasks"})
    await add_automation(hass, "panda_esl_todo.yaml", {"todo_entity": TODO, "emoji_image_url": "/config/emoji/{code}.png"})
    _, data = await run(hass, calls)
    assert [e["url"] for e in visible(data) if e["type"] == "dlimg"] == ["/config/emoji/1F6AE.png"]
