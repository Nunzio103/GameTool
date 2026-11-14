"""Generates assets/icon.ico: white crosshair on a blue rounded square.

Usage: python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
S = 1024            # draw large and scale down: smooth edges
TOP = (0x1a, 0x80, 0xe6)
BOTTOM = (0x00, 0x4d, 0x99)
WHITE = (255, 255, 255, 255)
DOT = (0xff, 0xb5, 0x47, 255)   # orange center dot, stands out on the blue


def background():
    gradient = Image.new("RGBA", (S, S))
    px = gradient.load()
    for y in range(S):
        t = y / (S - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)) + (255,)
        for x in range(S):
            px[x, y] = color
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((32, 32, S - 33, S - 33), radius=230, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(gradient, mask=mask)
    return img


def draw(small):
    """small: thicker strokes and no inner ticks, for 16-32 px."""
    img = background()
    d = ImageDraw.Draw(img)
    c = S // 2
    ring_r, ring_w = (270, 110) if small else (255, 64)
    d.ellipse((c - ring_r, c - ring_r, c + ring_r, c + ring_r), outline=WHITE, width=ring_w)
    # ticks: from the ring toward the edge and (if there is room) toward the center
    tick_w = 110 if small else 64
    spans = [(ring_r - ring_w // 2, 420)] if small else [(150, 205), (ring_r - ring_w // 2, 410)]
    for r0, r1 in spans:
        h = tick_w // 2
        d.rectangle((c - h, c - r1, c + h, c - r0), fill=WHITE)
        d.rectangle((c - h, c + r0, c + h, c + r1), fill=WHITE)
        d.rectangle((c - r1, c - h, c - r0, c + h), fill=WHITE)
        d.rectangle((c + r0, c - h, c + r1, c + h), fill=WHITE)
    dot = 95 if small else 62
    d.ellipse((c - dot, c - dot, c + dot, c + dot), fill=DOT)
    return img


def main():
    big, small = draw(False), draw(True)
    frames = [(small if n <= 32 else big).resize((n, n), Image.LANCZOS) for n in SIZES]
    out = ROOT / "assets" / "icon.ico"
    out.parent.mkdir(exist_ok=True)
    frames[-1].save(out, sizes=[(n, n) for n in SIZES], append_images=frames[:-1])
    big.resize((256, 256), Image.LANCZOS).save(ROOT / "assets" / "icon.png")
    print("scritto", out)


if __name__ == "__main__":
    main()
