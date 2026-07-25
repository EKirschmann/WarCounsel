#!/usr/bin/env python3
"""Draw docs/warcounsel.ico — the executable and tray icon.

Drawn with Pillow rather than rasterised from the SVG so the build needs no
SVG toolchain, and so each size can be tuned: at 16px the scroll is dropped
entirely, because a sword-through-parchment reduced to 16 pixels is a smudge
and the blade alone still reads.

Mirrors docs/warcounsel-mark.svg: dark blade where it crosses the parchment,
gold where it clears it, meter ticks down the fuller.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "warcounsel.ico"

BG_TOP = (27, 32, 48)
BG_BOT = (13, 17, 23)
PARCH = (216, 171, 92)
PARCH_HI = (242, 217, 160)
PARCH_LO = (169, 112, 47)
STEEL = (230, 207, 149)
STEEL_LO = (157, 117, 52)
DARK = (27, 34, 51)


def draw(size: int) -> Image.Image:
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    for y in range(S):  # vertical background wash
        t = y / S
        d.line([(0, y), (S, y)],
               fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)))

    show_scroll = size >= 24
    if show_scroll:
        d.rectangle([52, 96, 204, 200], fill=PARCH)
        d.rectangle([52, 96, 204, 100], fill=PARCH_HI)
        for x in (52, 190):                      # rolled ends
            d.ellipse([x - 8, 96, x + 22, 128], fill=PARCH_LO)
            d.ellipse([x - 8, 168, x + 22, 200], fill=PARCH_LO)
        if size >= 48:                           # runes only when legible
            for yy in (118, 144, 170):
                d.line([(74, yy), (84, yy)], fill=(138, 90, 34), width=3)
                d.line([(79, yy), (79, yy + 11)], fill=(138, 90, 34), width=3)
                d.line([(172, yy), (182, yy + 11)], fill=(138, 90, 34), width=3)
                d.line([(182, yy), (172, yy + 11)], fill=(138, 90, 34), width=3)

    # sword
    d.ellipse([117, 23, 139, 45], fill=STEEL)                 # pommel
    d.rectangle([122, 44, 134, 70], fill=STEEL)               # grip
    d.polygon([(92, 72), (164, 72), (156, 85), (100, 85)], fill=STEEL)  # guard
    blade_dark = DARK if show_scroll else STEEL
    d.polygon([(116, 85), (140, 85), (140, 213), (128, 235), (116, 213)],
              fill=blade_dark)
    d.rectangle([116, 85, 140, 91], fill=STEEL)
    d.polygon([(116, 200), (140, 200), (140, 213), (128, 235), (116, 213)],
              fill=STEEL)
    d.rectangle([116, 85, 119, 203], fill=STEEL)              # lit edge
    d.rectangle([137, 85, 140, 203], fill=STEEL_LO)           # shadow edge
    if size >= 32:
        for yy, w in ((104, 14), (122, 10), (140, 14), (158, 8), (176, 12)):
            d.rectangle([121, yy, 121 + w, yy + 4], fill=STEEL)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = (16, 24, 32, 48, 64, 128, 256)
    frames = [draw(s) for s in sizes]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(OUT, format="ICO",
                    sizes=[(s, s) for s in sizes],
                    append_images=frames[:-1])
    print(f"{OUT}  ({OUT.stat().st_size / 1024:.1f} KB, sizes {sizes})")
    png = OUT.with_suffix(".png")
    draw(256).save(png)
    print(f"{png}  (256px preview)")


if __name__ == "__main__":
    main()
