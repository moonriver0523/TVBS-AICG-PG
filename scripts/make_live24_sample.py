"""出一張 YT 24H LIVE 樣張檢查幾何（2026-09-13）。

不打生圖 API：底圖用中性漸層在本機畫，重點是角標／Logo／標題／日期的位置關係，
不是照片好不好看。真的要看成品再另外實拍。

    python -X utf8 scripts/make_live24_sample.py
"""

from __future__ import annotations

import io
import pathlib
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import compose  # noqa: E402

OUT = pathlib.Path(r"D:\Downloads\20260913_YT24HLIVE_樣張.png")


def gradient(size: tuple[int, int], top: tuple[int, int, int],
             bottom: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    w, h = size
    for y in range(h):
        t = y / (h - 1)
        draw.line(((0, y), (w, y)),
                  fill=tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> None:
    cases = [
        ("滿版_短標題", gradient((1920, 1080), (108, 126, 152), (34, 44, 62)),
         "東北季風剩1天 假日回溫"),
        ("滿版_長標題", gradient((1920, 1080), (150, 128, 104), (60, 48, 36)),
         "熱浪襲西班牙馬德里太陽門搭遮陽棚"),
        ("雙切漸層", compose.blend_backgrounds_lr(
            gradient((1000, 1000), (122, 140, 166), (48, 60, 78)),
            gradient((1000, 1000), (166, 142, 116), (82, 66, 50)),
        ), "颱風外圍環流 北部防大雨"),
    ]
    tiles = []
    for name, background, title in cases:
        png = compose.compose_yt_live24_cover(
            background, title=title, date_text="2026.09.13", ai_note=True,
        )
        path = OUT.with_name(f"{OUT.stem}_{name}.png")
        path.write_bytes(png)
        print(f"{name}：{path}（{len(png) / 1024:.0f} KB）")
        tiles.append((name, Image.open(io.BytesIO(png)).convert("RGB")))

    tw = 900
    parts = [(n, t.resize((tw, round(tw * t.height / t.width)), Image.LANCZOS)) for n, t in tiles]
    th = parts[0][1].height
    sheet = Image.new("RGB", (tw + 20, len(parts) * (th + 34) + 10), (20, 20, 24))
    draw = ImageDraw.Draw(sheet)
    y = 8
    for name, tile in parts:
        draw.text((12, y), name, fill=(255, 220, 120))
        sheet.paste(tile, (10, y + 22))
        y += th + 34
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT)
    print(f"對照表：{OUT}")


if __name__ == "__main__":
    main()
