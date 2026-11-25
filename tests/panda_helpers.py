"""Shared helpers for the PANDA ESL blueprint tests."""
import asyncio
import json
import os
import shutil
from pathlib import Path

from homeassistant.setup import async_setup_component

BLUEPRINTS = Path(__file__).resolve().parents[1] / "blueprints"


async def pump(n=300):
    for _ in range(n):
        await asyncio.sleep(0)


def install(hass, name):
    d = Path(hass.config.path("blueprints/automation/howels"))
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINTS / name, d)


def register_write(hass):
    calls = []

    async def write(call):
        calls.append((call.service, dict(call.data)))

    for s in ("write", "write_guarded"):
        hass.services.async_register("panda_esl", s, write)
    return calls


async def add_automation(hass, blueprint, inputs):
    use = {"path": f"howels/{blueprint}", "input": {"display": "dev1", "write_action": "panda_esl.write_guarded"}}
    use["input"].update(inputs)
    assert await async_setup_component(
        hass, "automation", {"automation": [{"id": "x", "alias": "label", "use_blueprint": use}]}
    )
    await hass.async_block_till_done()


async def run(hass, calls, skip_condition=True):
    await hass.services.async_call(
        "automation", "trigger", {"entity_id": "automation.label", "skip_condition": skip_condition}, blocking=False
    )
    await pump()
    if not calls:
        await hass.async_block_till_done()
    assert calls, "no write"
    service, data = calls[-1]
    out = os.environ.get("PANDA_PAYLOAD_DIR")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        name = os.environ.get("PYTEST_CURRENT_TEST", "payload").split("::")[-1].split(" ")[0]
        (Path(out) / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return service, data


def visible(data):
    return [e for e in data["payload"] if e.get("visible", True) is not False]


def texts(data):
    return [e["value"] for e in visible(data) if e["type"] == "text"]


def icons(data):
    return [e["value"] for e in visible(data) if e["type"] == "icon"]


def _dither_names():
    import sys

    sys.path.insert(0, str(BLUEPRINTS.parent / "tools"))
    import panda_dither_png

    return {
        panda_dither_png.make(shape, n): f"dither:{shape}:{n}"
        for shape in ("disc", "square")
        for n in panda_dither_png.SIZES
    }


def image_name(url):
    if url.startswith("data:"):
        return _dither_names().get(url, "data:unknown")
    return url.rsplit("/", 1)[-1].removesuffix(".png")


def images(data):
    """Codes (file stem) of the visible dlimg elements, in payload order.

    A dithered brown substitute is named dither:<shape>:<size>.
    """
    return [image_name(e["url"]) for e in visible(data) if e["type"] == "dlimg"]


def in_canvas(data, w, h):
    for e in visible(data):
        if e["type"] == "dlimg":
            for a, b in (("x", "xsize"), ("y", "ysize")):
                assert isinstance(e[a], int) and isinstance(e[b], int), e
                assert 0 <= e[a] and e[a] + e[b] <= (w if a == "x" else h), e
        for key in ("x", "x_start", "x_end"):
            if key in e:
                assert isinstance(e[key], int) and 0 <= e[key] < w, (key, e)
        for key in ("y", "y_start", "y_end"):
            if key in e:
                assert isinstance(e[key], int) and 0 <= e[key] < h, (key, e)
        if "size" in e:
            assert isinstance(e["size"], int) and e["size"] > 0, e
