"""Draw the ThzDAQ pixel icon and write it for Windows, macOS and the window.

Two hand-made grids: 32x32 (THz lettering over an oscilloscope screen with a
terahertz chirp and a recording light) and a simpler 16x16 for small sizes.
Every size is an integer nearest-neighbour scale of one of them, so pixels stay
sharp: 16, 48 from the small grid; 32, 64, 128, 256, 512, 1024 from the large.

    uv run python assets/make_icon.py

writes assets/thzdaq.ico, assets/thzdaq.icns, assets/thzdaq.png and the PNGs
the application loads (packages/thzdaq-gui/src/thzdaq_gui/resources/icon/).
"""

import io
import math
import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
RESOURCES = ROOT / "packages/thzdaq-gui/src/thzdaq_gui/resources/icon"

PALETTE = {
    "K": (14, 14, 14, 255),  # outline
    "B": (38, 38, 38, 255),  # body
    "b": (52, 52, 52, 255),  # body highlight (top edge)
    "S": (21, 21, 21, 255),  # screen
    "g": (44, 44, 44, 255),  # screen grid
    "O": (243, 156, 18, 255),  # accent orange (theme.ACCENT)
    "Y": (255, 214, 120, 255),  # hot highlight
    "W": (236, 236, 236, 255),  # lettering
    "R": (231, 76, 60, 255),  # recording light
    "r": (150, 40, 30, 255),
}

# 3x5 pixel font for the lettering
GLYPHS = {
    "T": ["WWW", ".W.", ".W.", ".W.", ".W."],
    "H": ["W.W", "W.W", "WWW", "W.W", "W.W"],
    "z": ["....", "WWWW", "..WW", "WW..", "WWWW"],
}


def blank(size):
    return [["." for _ in range(size)] for _ in range(size)]


def body(grid, inset, radius):
    """Rounded square with an outline and a lighter top edge."""
    size = len(grid)
    lo, hi = inset, size - 1 - inset

    def inside(x, y, shrink=0):
        a, b, r = lo + shrink, hi - shrink, max(radius - shrink, 0)
        if not (a <= x <= b and a <= y <= b):
            return False
        cx = min(max(x, a + r), b - r)
        cy = min(max(y, a + r), b - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r + r * 0.6

    for y in range(size):
        for x in range(size):
            if inside(x, y, 1):
                grid[y][x] = "b" if y == lo + 1 else "B"
            elif inside(x, y):
                grid[y][x] = "K"


def screen(grid, x0, y0, x1, y1, step):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            on_grid = (x - x0) % step == 0 and (y - y0) % step == 0
            grid[y][x] = "g" if on_grid and x > x0 and y > y0 else "S"
    mid = (y0 + y1) // 2
    for x in range(x0 + 1, x1, 2):
        grid[mid][x] = "g"


def chirp(grid, x0, x1, center, amplitude, cycles_start, cycles_end):
    """A wave whose frequency grows to the right (a terahertz sweep)."""
    points = []
    width = x1 - x0
    for i in range(width * 8 + 1):
        t = i / (width * 8)
        cycles = cycles_start * t + (cycles_end - cycles_start) * t * t / 2
        phase = 2 * math.pi * cycles
        envelope = 0.55 + 0.45 * t  # it grows as well
        x = x0 + t * width
        y = center - amplitude * envelope * math.sin(phase)
        points.append((round(x), round(y)))
    previous = None
    for x, y in points:
        if previous is not None:
            px, py = previous
            for yy in range(min(py, y), max(py, y) + 1):
                grid[yy][x] = "O"
        grid[y][x] = "O"
        previous = (x, y)
    # The crests and troughs light up
    for x in range(x0, x1 + 1):
        column = [y for y in range(len(grid)) if grid[y][x] == "O"]
        if len(column) == 1 and abs(column[0] - center) >= amplitude * 0.6:
            grid[column[0]][x] = "Y"


def text(grid, word, x, y):
    for glyph_name in word:
        glyph = GLYPHS[glyph_name]
        for dy, row in enumerate(glyph):
            for dx, cell in enumerate(row):
                if cell == "W":
                    grid[y + dy][x + dx] = "W"
        x += len(glyph[0]) + 1


def light(grid, x, y):
    grid[y][x] = "R"
    grid[y][x + 1] = "R"
    grid[y + 1][x] = "r"
    grid[y + 1][x + 1] = "R"


def large():
    grid = blank(32)
    body(grid, inset=1, radius=5)
    text(grid, "THz", 5, 4)
    light(grid, 24, 5)
    screen(grid, 4, 12, 27, 27, step=4)
    chirp(grid, 5, 26, center=20, amplitude=5.5, cycles_start=1.0, cycles_end=3.6)
    return grid


def small():
    grid = blank(16)
    body(grid, inset=0, radius=3)
    screen(grid, 2, 3, 13, 12, step=4)
    chirp(grid, 3, 12, center=8, amplitude=3.0, cycles_start=1.0, cycles_end=1.8)
    grid[1][11] = "R"
    grid[1][12] = "R"
    return grid


def image(grid, scale):
    size = len(grid)
    picture = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell != ".":
                picture.putpixel((x, y), PALETTE[cell])
    return picture.resize((size * scale, size * scale), Image.NEAREST)


def sizes():
    small_grid, large_grid = small(), large()
    return {
        16: image(small_grid, 1),
        "16@2x": image(small_grid, 2),
        32: image(large_grid, 1),
        48: image(small_grid, 3),
        64: image(large_grid, 2),
        128: image(large_grid, 4),
        256: image(large_grid, 8),
        512: image(large_grid, 16),
        1024: image(large_grid, 32),
    }


# macOS icon types: PNG of each point size at 1x and 2x
ICNS_TYPES = (
    (b"icp4", 16), (b"ic11", "16@2x"), (b"icp5", 32), (b"ic12", 64),
    (b"ic07", 128), (b"ic13", 256), (b"ic08", 256), (b"ic14", 512),
    (b"ic09", 512), (b"ic10", 1024),
)  # fmt: skip


def write_icns(path: Path, images) -> None:
    """Every entry written (Pillow leaves out 16 and 32 at 1x, so macOS would
    shrink a larger picture and blur the pixels)."""
    chunks = []
    for kind, size in ICNS_TYPES:
        buffer = io.BytesIO()
        images[size].save(buffer, format="PNG")
        data = buffer.getvalue()
        chunks.append(kind + struct.pack(">I", len(data) + 8) + data)
    body = b"".join(chunks)
    path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def main() -> None:
    images = sizes()
    RESOURCES.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 64, 128, 256):
        images[size].save(RESOURCES / f"thzdaq_{size}.png")
    images[256].save(ASSETS / "thzdaq.png")
    # Windows: every size in one .ico, each drawn for its size
    ico_sizes = (16, 32, 48, 64, 128, 256)
    images[256].save(
        ASSETS / "thzdaq.ico",
        sizes=[(s, s) for s in ico_sizes],
        append_images=[images[s] for s in ico_sizes if s != 256],
    )
    write_icns(ASSETS / "thzdaq.icns", images)
    print("written", ASSETS / "thzdaq.ico", ASSETS / "thzdaq.icns", RESOURCES)


if __name__ == "__main__":
    main()
