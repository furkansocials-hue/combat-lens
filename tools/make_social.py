"""Draws docs/social.png (1280x640), the picture GitHub shows when a link to the repo is shared.
Needs Pillow. Uses the demo-mode screenshots in docs/ and the app icon."""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
W, H = 1280, 640
FONTS = r"C:\Windows\Fonts"


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def rounded(im, r):
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=r, fill=255)
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def shadowed(canvas, im, xy, r=16, blur=24, alpha=150):
    sh = Image.new("RGBA", (im.width + blur * 4, im.height + blur * 4), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((blur * 2, blur * 2, blur * 2 + im.width, blur * 2 + im.height), radius=r,
                                         fill=(0, 0, 0, alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(sh, (xy[0] - blur * 2, xy[1] - blur * 2 + 10))
    canvas.alpha_composite(rounded(im, r), xy)


def main():
    bg = Image.new("RGBA", (W, H), (14, 13, 20, 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((-260, -320, 640, 520), fill=(155, 107, 255, 90))
    g.ellipse((760, 260, 1500, 900), fill=(46, 230, 197, 46))
    bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))

    analysis = Image.open(os.path.join(DOCS, "analysis.png")).convert("RGBA")
    analysis = analysis.resize((int(analysis.width * 0.5), int(analysis.height * 0.5)), Image.LANCZOS)
    shadowed(bg, analysis, (W - analysis.width - 36, 64), r=14)
    overlay = Image.open(os.path.join(DOCS, "overlay.png")).convert("RGBA")
    overlay = overlay.resize((int(overlay.width * 0.84), int(overlay.height * 0.84)), Image.LANCZOS)
    shadowed(bg, overlay, (590, H - overlay.height - 40), r=12)

    d = ImageDraw.Draw(bg)
    icon = Image.open(os.path.join(ROOT, "aion2meter", "web", "app.png")).convert("RGBA").resize((96, 96), Image.LANCZOS)
    bg.alpha_composite(icon, (64, 92))
    d.text((64, 214), "Combat Lens", font=font("segoeuib.ttf", 76), fill=(244, 242, 252))
    d.text((68, 306), "AION 2 DPS Meter", font=font("seguisb.ttf", 36), fill=(205, 182, 255))
    lines = ["Party & skill damage over the game", "Fight analysis, DPS curve, history",
             "Field boss & Spacetime Rift timers", "Reads network traffic only"]
    y = 378
    for line in lines:
        d.ellipse((70, y + 13, 80, y + 23), fill=(46, 230, 197))
        d.text((94, y), line, font=font("segoeui.ttf", 26), fill=(200, 198, 214))
        y += 42
    d.text((64, H - 54), "Türkçe · English  ·  Free & open source (GPL-3.0)", font=font("segoeui.ttf", 20),
           fill=(130, 126, 150))
    out = os.path.join(DOCS, "social.png")
    bg.convert("RGB").save(out, optimize=True)
    print(out, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    main()
