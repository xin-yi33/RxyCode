"""Convert §B ASCII frames to PNG for multimodal review."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "section-b"


def render_frame(text: str, out_path: Path) -> None:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    font = ImageFont.load_default()
    # monospace-ish metrics for default bitmap font
    cell_w, cell_h = 7, 14
    pad = 12
    width = max((len(line) for line in lines), default=40) * cell_w + pad * 2
    height = max(len(lines), 1) * cell_h + pad * 2
    img = Image.new("RGB", (width, height), "#0d1117")
    draw = ImageDraw.Draw(img)
    y = pad
    for line in lines:
        draw.text((pad, y), line, fill="#c9d1d9", font=font)
        y += cell_h
    img.save(out_path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for txt in sorted(OUT.glob("*.txt")):
        png = txt.with_suffix(".png")
        render_frame(txt.read_text(encoding="utf-8"), png)
        print(f"wrote {png}")


if __name__ == "__main__":
    main()
