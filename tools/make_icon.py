"""Draws the app icon (the dial-and-blade mark in web/common.js) into aion2meter/web/app.ico and app.png.
Needs Pillow. The icon puts the mark on a dark rounded tile so it reads on light and dark taskbars."""
import math
import os

from PIL import Image, ImageDraw

S = 1024             # drawn large, then scaled down for clean edges
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aion2meter", "web")
STOPS = [(0.0, (0xFF, 0xD2, 0x7A)), (0.5, (0xF5, 0xA5, 0x24)), (1.0, (0xFF, 0x6B, 0x3D))]


def colour(t):
    for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return tuple(round(a + (b - a) * f) for a, b in zip(c0, c1))
    return STOPS[-1][1]


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = S * 0.04
    d.rounded_rectangle((pad, pad, S - pad, S - pad), radius=S * 0.22, fill=(23, 23, 28, 255),
                        outline=(58, 58, 68, 255), width=round(S * 0.012))

    # the mark, in its 32x32 design space, scaled to 78% of the tile
    k = S * 0.78 / 32
    ox = (S - 32 * k) / 2
    oy = (S - 32 * k) / 2 + S * 0.01

    def P(x, y):
        return ox + x * k, oy + y * k

    cx, cy, r, w = 16, 19, 11, 3.6
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    box = (*P(cx - r - w / 2, cy - r - w / 2), *P(cx + r + w / 2, cy + r + w / 2))
    md.arc(box, start=145, end=395, fill=255, width=round(w * k))
    for ang in (215, -35):  # round caps
        ex, ey = cx + r * math.cos(math.radians(ang)), cy - r * math.sin(math.radians(ang))
        x0, y0 = P(ex - w / 2, ey - w / 2)
        x1, y1 = P(ex + w / 2, ey + w / 2)
        md.ellipse((x0, y0, x1, y1), fill=255)
    x_lo, x_hi = P(cx - r - w / 2, 0)[0], P(cx + r + w / 2, 0)[0]
    lut = [colour(i / 255) for i in range(256)]
    grad = Image.new("RGB", (S, 1))
    grad.putdata([lut[max(0, min(255, int((x - x_lo) / (x_hi - x_lo) * 255)))] for x in range(S)])
    img.paste(grad.resize((S, S)), (0, 0), mask)

    d = ImageDraw.Draw(img)
    d.polygon([P(17.07, 19.9), P(21.14, 12.87), P(14.93, 18.1)], fill=(255, 255, 255, 255))
    for rad, fill in ((2.7, (255, 255, 255, 255)), (1.0, (23, 23, 28, 255))):
        d.ellipse((*P(cx - rad, cy - rad), *P(cx + rad, cy + rad)), fill=fill)

    big = img.resize((256, 256), Image.LANCZOS)
    big.save(os.path.join(OUT, "app.png"))
    big.save(os.path.join(OUT, "app.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ok", OUT)


if __name__ == "__main__":
    main()
