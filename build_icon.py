#!/usr/bin/env python3.11
"""
SPY Auto Trader app icon generator.

Design:
- Squircle dark-navy background with subtle vertical gradient.
- Six ascending candlesticks (4 green up-days, 1 red pullback, 1 big green
  breakout on the right). Last candle has a soft glow.
- Thin diagonal trend line connecting the highs.
- No text — recognizable as a "trading app" icon at every size.

Outputs:
  /tmp/SpyAutoTrader.iconset/   — Apple-required PNG sizes
  /tmp/SpyAutoTrader.icns       — compiled icns
"""

import os
import shutil
import subprocess
from PIL import Image, ImageDraw, ImageFilter

ICONSET = "/tmp/SpyAutoTrader.iconset"
shutil.rmtree(ICONSET, ignore_errors=True)
os.makedirs(ICONSET, exist_ok=True)

# ── Colors (matches dashboard palette) ────────────────────────────────────────
BG_TOP    = (10, 24, 48)      # deep navy
BG_BOT    = (4, 7, 14)        # near-black
GREEN     = (0, 229, 160)     # bull green
GREEN_HI  = (74, 255, 196)    # highlight
RED       = (255, 61, 104)    # bear red
TREND     = (245, 158, 11)    # amber (VWAP-style)
GRID      = (122, 150, 184, 32)


def _gradient(size: int) -> Image.Image:
    """Vertical navy→black gradient."""
    img = Image.new("RGB", (size, size))
    for y in range(size):
        t = y / max(1, size - 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOT[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOT[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOT[2] * t)
        for x in range(size):
            img.putpixel((x, y), (r, g, b))
    return img


def _gradient_fast(size: int) -> Image.Image:
    """Faster: draw with horizontal lines."""
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOT[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOT[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOT[2] * t)
        draw.line([(0, y), (size - 1, y)], fill=(r, g, b))
    return img


def _squircle_mask(size: int, radius_frac: float = 0.225) -> Image.Image:
    """Rounded-rect mask. radius_frac picks corner curvature
    (~0.225 matches macOS Big Sur+ squircle look)."""
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    r = int(size * radius_frac)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    return mask


def _draw_grid(img: Image.Image, size: int) -> None:
    """Subtle horizontal grid lines, like a chart background."""
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # 4 horizontal grid lines in the middle 60% of the canvas
    for i in range(1, 5):
        y = int(size * (0.25 + 0.125 * i))
        d.line([(int(size * 0.10), y), (int(size * 0.90), y)],
               fill=GRID, width=max(1, size // 256))
    img.alpha_composite(overlay)


def _draw_candle(d: ImageDraw.ImageDraw, x: int, body_top: int, body_bot: int,
                 wick_top: int, wick_bot: int, w: int, color: tuple,
                 outline: tuple = None, line_w: int = 1) -> None:
    """One OHLC candle: wick + body."""
    cx = x + w // 2
    d.line([(cx, wick_top), (cx, wick_bot)], fill=color, width=max(1, line_w))
    # Body
    if outline:
        d.rectangle([x, body_top, x + w, body_bot], fill=color, outline=outline,
                    width=max(1, line_w))
    else:
        d.rectangle([x, body_top, x + w, body_bot], fill=color)


def _glow(img: Image.Image, bbox, color: tuple, blur: int) -> None:
    """Add a soft glow inside bbox by drawing a blurred shape."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle(bbox, fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer)


def render(size: int, fname: str) -> None:
    # Background gradient → squircle mask
    bg = _gradient_fast(size).convert("RGBA")
    mask = _squircle_mask(size)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(bg, (0, 0), mask)

    _draw_grid(canvas, size)

    d = ImageDraw.Draw(canvas)
    # ── Candlestick layout ──
    # 6 candles, slightly ascending (last one big green breakout)
    n = 6
    pad_x = int(size * 0.13)
    inner_w = size - 2 * pad_x
    cell_w = inner_w / n
    body_w = int(cell_w * 0.55)
    line_w = max(1, size // 96)
    # vertical band that candles occupy
    chart_top = int(size * 0.30)
    chart_bot = int(size * 0.80)
    chart_h = chart_bot - chart_top

    # OHLC values (open, high, low, close) as fractions of chart_h, where 0 = top
    candles = [
        # (open, high, low, close, color)
        (0.72, 0.62, 0.78, 0.66, GREEN),  # green
        (0.66, 0.55, 0.70, 0.58, GREEN),  # green
        (0.58, 0.52, 0.66, 0.62, RED),    # red pullback
        (0.62, 0.50, 0.66, 0.52, GREEN),  # green
        (0.52, 0.42, 0.56, 0.46, GREEN),  # green
        (0.46, 0.18, 0.48, 0.22, GREEN_HI),  # breakout
    ]

    # Soft amber trendline connecting the highs
    trend_pts = []
    for i, (o, h, low, c, col) in enumerate(candles):
        cx = pad_x + int(cell_w * i + cell_w / 2)
        wick_top = chart_top + int(chart_h * h)
        trend_pts.append((cx, wick_top))

    # Trend line first (so candles paint over it)
    if len(trend_pts) >= 2:
        # Slight glow under the line
        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.line(trend_pts, fill=(*TREND, 100), width=max(2, line_w * 2))
        glow = glow.filter(ImageFilter.GaussianBlur(max(1, size // 96)))
        canvas.alpha_composite(glow)
        d.line(trend_pts, fill=(*TREND, 230), width=max(1, line_w))

    # Last candle — add glow behind it
    last_i = len(candles) - 1
    o, h, low, c, col = candles[last_i]
    x = pad_x + int(cell_w * last_i + (cell_w - body_w) / 2)
    body_top = chart_top + int(chart_h * min(o, c))
    body_bot = chart_top + int(chart_h * max(o, c))
    _glow(canvas, (x - body_w // 2, body_top - body_w // 2,
                   x + body_w + body_w // 2, body_bot + body_w // 2),
          (*GREEN_HI, 70), blur=max(2, size // 64))

    # Draw all candles
    for i, (o, h, low, c, col) in enumerate(candles):
        x = pad_x + int(cell_w * i + (cell_w - body_w) / 2)
        wick_top = chart_top + int(chart_h * h)
        wick_bot = chart_top + int(chart_h * low)
        body_top = chart_top + int(chart_h * min(o, c))
        body_bot = chart_top + int(chart_h * max(o, c))
        _draw_candle(d, x, body_top, body_bot, wick_top, wick_bot, body_w,
                     col, line_w=line_w)

    # Subtle inner border to make it pop
    border = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(border)
    r = int(size * 0.225)
    bd.rounded_rectangle([0, 0, size - 1, size - 1], radius=r,
                         outline=(122, 150, 184, 40),
                         width=max(1, size // 256))
    canvas.alpha_composite(border)

    canvas.save(fname, "PNG")


# Apple-required sizes for an .iconset
sizes = [
    (16,   "16x16"),
    (32,   "16x16@2x"),
    (32,   "32x32"),
    (64,   "32x32@2x"),
    (128,  "128x128"),
    (256,  "128x128@2x"),
    (256,  "256x256"),
    (512,  "256x256@2x"),
    (512,  "512x512"),
    (1024, "512x512@2x"),
]
for px, name in sizes:
    render(px, f"{ICONSET}/icon_{name}.png")

subprocess.run(["iconutil", "-c", "icns", "-o", "/tmp/SpyAutoTrader.icns",
                ICONSET], check=True)
print("Icon built: /tmp/SpyAutoTrader.icns")
