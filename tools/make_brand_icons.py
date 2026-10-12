#!/usr/bin/env python3
"""Generate the integration's brand icons: a "C" on a film strip (deliberately not Cineville's logo).

Writes custom_components/cineville/brand/{icon,icon@2x,dark_icon,dark_icon@2x}.png.
Home Assistant (2026+) serves these as the integration's icon; HACS validation requires icon.png.
Usage: .venv/bin/python tools/make_brand_icons.py   (needs Pillow, which Home Assistant's test env includes)
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "cineville" / "brand"
CANVAS = 2048  # drawn large, then scaled down for smooth edges

THEMES = {
    # name: (strip colour, "C" colour)
    "icon": ((38, 50, 56, 255), (255, 179, 0, 255)),  # dark strip, amber C: for light backgrounds
    "dark_icon": ((207, 216, 220, 255), (230, 81, 0, 255)),  # light strip, deep orange C: for dark backgrounds
}


def draw_icon(strip: tuple, letter: tuple) -> Image.Image:
    s = CANVAS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Film strip: a rounded rectangle filling the square
    margin = int(s * 0.06)
    d.rounded_rectangle([margin, margin, s - margin, s - margin], radius=int(s * 0.12), fill=strip)

    # Sprocket holes punched out along the left and right edges (transparent)
    holes = 6
    hole_w, hole_h = int(s * 0.075), int(s * 0.085)
    inset = margin + int(s * 0.045)
    top, bottom = margin + int(s * 0.07), s - margin - int(s * 0.07)
    step = (bottom - top - hole_h) / (holes - 1)
    for i in range(holes):
        y = int(top + i * step)
        for x in (inset, s - inset - hole_w):
            d.rounded_rectangle([x, y, x + hole_w, y + hole_h], radius=int(hole_w * 0.3), fill=(0, 0, 0, 0))

    # The "C": a thick ring, open to the right, with rounded ends
    cx = cy = s // 2
    radius, width = int(s * 0.27), int(s * 0.11)
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    gap = 50  # degrees on each side of the opening (0° = right)
    d.arc(box, start=gap, end=360 - gap, fill=letter, width=width)
    import math

    mid = radius - width / 2
    for angle in (gap, 360 - gap):
        ex = cx + mid * math.cos(math.radians(angle))
        ey = cy + mid * math.sin(math.radians(angle))
        r = width / 2
        d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=letter)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (strip, letter) in THEMES.items():
        big = draw_icon(strip, letter)
        for suffix, size in (("", 256), ("@2x", 512)):
            path = OUT / f"{name}{suffix}.png"
            big.resize((size, size), Image.LANCZOS).save(path, optimize=True)
            print("wrote", path.relative_to(OUT.parent.parent.parent))


if __name__ == "__main__":
    main()
