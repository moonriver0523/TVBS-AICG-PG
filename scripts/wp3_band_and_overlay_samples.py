"""WP3 樣張產生器（2026-09-08）：底色框三個位置 × 藍／紅，以及 PNG 壓標原型。

只出樣張給使用者挑，不接端點、不接 UI。跑法（在 worktree 根目錄）：

    E:/GitHub/TVBS-AICG-PG/.venv/Scripts/python.exe -X utf8 scripts/wp3_band_and_overlay_samples.py

底圖刻意用中性灰漸層加淡格線，不用已合成好的封面——那種檔案裡的標題是烤進去的，
底色框會壓在烤好的字上、程式再畫一次字，量位置會量到假的。
"""
import io
import pathlib
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import compose  # noqa: E402

OUT = pathlib.Path(r"D:\Downloads")
LINE1 = "澳洲擬立新法"
LINE2 = "民眾可關閉社群媒體演算法"
DATE = "2026/09/08"
SOURCE = "畫面來源：路透社"
VARIANT_LABELS = {"line1_top": "1上緣", "between": "2行間", "line2_top": "3第二行"}
COMBOS = (("tr", "left", "右上Logo_標題左"),
          ("br", "left", "右下Logo_標題左"),
          ("tl", "right", "左上Logo_標題右"))


def neutral_backdrop(size=compose.YT_CANVAS, grid=True) -> Image.Image:
    """中性灰漸層＋淡格線的示意畫面：半透明的東西壓上去看得出透了多少。"""
    width, height = size
    canvas = Image.new("RGB", size)
    draw = ImageDraw.Draw(canvas)
    for y in range(height):
        t = y / max(1, height - 1)
        v = round(150 - 40 * t)
        draw.line(((0, y), (width, y)), fill=(v, v, v + 6))
    if grid:
        for x in range(0, width, 120):
            draw.line(((x, 0), (x, height)), fill=(175, 175, 182))
        for y in range(0, height, 120):
            draw.line(((0, y), (width, y)), fill=(175, 175, 182))
    return canvas


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def band_samples() -> list[pathlib.Path]:
    background = _png(neutral_backdrop())
    written = []
    for name, (top, fade) in compose.YT_BAND_VARIANTS.items():
        label = VARIANT_LABELS[name]
        blue = compose.compose_yt_cover(
            background, line1=LINE1, line2=LINE2, date_text=DATE, bottom_band=True,
            band_top_ratio=top, band_fade_ratio=fade,
        )
        red = compose.compose_yt_hot_cover(
            background, line1=LINE1, line2=LINE2, bottom_band=True,
            band_top_ratio=top, band_fade_ratio=fade,
        )
        for colour, data in (("藍", blue), ("紅", red)):
            path = OUT / f"20260908_底色框_{colour}_{label}.png"
            path.write_bytes(data)
            written.append(path)
    return written


def overlay_samples() -> list[pathlib.Path]:
    written = []
    for corner, side, label in COMBOS:
        data = compose.compose_yt_overlay(
            line1=LINE1, line2=LINE2, source_text=SOURCE,
            logo_corner=corner, title_side=side,
        )
        transparent = OUT / f"20260908_YT壓標_{label}_透明.png"
        transparent.write_bytes(data)
        written.append(transparent)

        preview = neutral_backdrop().convert("RGBA")
        preview.alpha_composite(Image.open(io.BytesIO(data)).convert("RGBA"))
        path = OUT / f"20260908_YT壓標_{label}_預覽.png"
        path.write_bytes(_png(preview.convert("RGB")))
        written.append(path)
    return written


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in band_samples() + overlay_samples():
        print(path)
    print()
    for name, (top, fade) in compose.YT_BAND_VARIANTS.items():
        print(f"{name}: top={top} fade={fade} 漸入結尾={top + fade:.4f}")
    print(f"第一行墨水上緣={compose._yt_title_ink_top_ratio(compose.YT_LINE1_BASELINE_RATIO):.4f}")
    print(f"第二行墨水上緣={compose._yt_title_ink_top_ratio(compose.YT_LINE2_BASELINE_RATIO):.4f}")


if __name__ == "__main__":
    main()
