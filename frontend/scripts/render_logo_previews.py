#!/usr/bin/env python3
"""Preview Unicode WORDMARK with OpenCode-style cell fill (ink fg+bg on █).

App field background stays #000000. Brand inks unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow required: pip install Pillow") from exc

WORDMARK = [
    "███████  ██   ██  ██   ██   █████    █████   ██████    █████ ",
    "██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██  ██   ██",
    "██   ██   ██ ██   ██   ██  ██       ██   ██  ██   ██  ███████",
    "███████    ███     ██ ██   ██       ██   ██  ██   ██  ██   ██",
    "██   ██   ██ ██     ███    ██       ██   ██  ██   ██  ██     ",
    "██   ██  ██   ██    ███    ██   ██  ██   ██  ██   ██  ██   ██",
    "██   ██  ██   ██    ███     █████    █████   ██████    █████ ",
]

PINK_TOP = (255, 182, 193)  # #FFB6C1
PINK_HOT = (255, 105, 180)  # #FF69B4
BG = (0, 0, 0)  # #000000
LABEL = (170, 170, 170)
SUB = (255, 182, 193)

PROFILES = {
    "cmd-cellfill": "CMD / conhost — Unicode █ + matching ink bg",
    "ps-cellfill": "PowerShell — Unicode █ + matching ink bg",
    "wt-cellfill": "Windows Terminal — Unicode █ + matching ink bg",
    "macos-cellfill": "macOS — Unicode █ + matching ink bg",
}


def load_font(size: int) -> ImageFont.ImageFont:
    for path in (
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\lucon.ttf",
        "/System/Library/Fonts/Menlo.ttc",
    ):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_one(out: Path, title: str, cols: int = 100) -> None:
    label_font = load_font(14)
    cell_w, cell_h = 10, 18
    pad_x, pad_y = 24, 40
    subtitle = "✦ General-Purpose AI Agent ✦"
    content_w = cols * cell_w
    height = pad_y + 28 + len(WORDMARK) * cell_h + 36 + 24
    img = Image.new("RGB", (content_w + pad_x * 2, height), BG)
    draw = ImageDraw.Draw(img)
    draw.text((pad_x, 12), title, fill=LABEL, font=label_font)

    dw = max(len(line.rstrip()) for line in WORDMARK)
    leading = max(0, (cols - dw) // 2)

    for i, line in enumerate(WORDMARK):
        y = pad_y + 28 + i * cell_h
        ink = PINK_TOP if i == 0 else PINK_HOT
        text = (" " * leading) + line.rstrip()
        for j, ch in enumerate(text):
            if ch != "█":
                continue
            x = pad_x + j * cell_w
            # OpenCode-style: fill entire cell with ink (fg+bg same) — no black gutters
            draw.rectangle([x, y, x + cell_w, y + cell_h], fill=ink)

    sub_y = pad_y + 28 + len(WORDMARK) * cell_h + 16
    sub_lead = max(0, (cols - len(subtitle)) // 2)
    draw.text((pad_x + sub_lead * cell_w, sub_y), subtitle, fill=SUB, font=label_font)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parents[2] / "qa-artifacts" / "logo-profiles"),
    )
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    for key, title in PROFILES.items():
        render_one(out_dir / f"preview-{key}.png", f"{key}: {title}")


if __name__ == "__main__":
    main()
