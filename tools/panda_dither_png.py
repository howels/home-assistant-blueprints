"""Print the dithered red and black emoji substitutes used by the PANDA ESL blueprints.

The label shows black, white, and red only. A brown emoji has no colour on that palette, so the
blueprints draw a checkerboard of red and black pixels instead, with a black outline. Each image
is a PNG data URL sized exactly to the emoji size, because the renderer resamples any other size
and would blur the checkerboard.

Usage: python3 tools/panda_dither_png.py  (needs Pillow)
"""
import base64
import io
import sys

from PIL import Image

SIZES = range(10, 37, 2)
TRANSPARENT, BLACK, RED = 0, 1, 2


def shape_mask(shape, n):
    c = (n - 1) / 2
    r = n / 2 - 0.25
    if shape == "square":
        return [[True] * n for _ in range(n)]
    return [[(x - c) ** 2 + (y - c) ** 2 <= r * r for x in range(n)] for y in range(n)]


def make(shape, n):
    inside = shape_mask(shape, n)
    img = Image.new("P", (n, n), TRANSPARENT)
    img.putpalette([255, 255, 255, 0, 0, 0, 255, 0, 0])
    px = img.load()
    for y in range(n):
        for x in range(n):
            if not inside[y][x]:
                continue
            edge = any(
                not (0 <= xx < n and 0 <= yy < n and inside[yy][xx])
                for xx, yy in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            )
            px[x, y] = BLACK if edge or (x + y) % 2 else RED
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True, transparency=TRANSPARENT)
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def yaml_block(indent="  "):
    lines = [f"{indent}dither_png:"]
    for shape in ("disc", "square"):
        lines.append(f"{indent}  {shape}:")
        for n in SIZES:
            lines.append(f'{indent}    "{n}": "{make(shape, n)}"')
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.write(yaml_block())
