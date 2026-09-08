"""出一張「YT 整點雙切」樣張給使用者看版面（WP2 第一階段）。

不打生圖 API：兩格底圖用中性色（灰藍／灰棕）加一點漸層在本機畫，重點是版面不是照片。

    python -X utf8 scripts/make_yt_hourly_split_sample.py
"""

from __future__ import annotations

import io
import pathlib
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import compose  # noqa: E402

OUT = pathlib.Path(r"D:\Downloads\20260908_YT整點雙切_sample.png")


def neutral_panel(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> bytes:
    """一格用的中性底圖：上淺下深的直向漸層，1000×1000。"""
    size = 1000
    image = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(image)
    for y in range(size):
        t = y / (size - 1)
        draw.line(
            ((0, y), (size, y)),
            fill=tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(3)),
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> None:
    png = compose.compose_yt_hourly_split_cover(
        neutral_panel((122, 140, 166), (48, 60, 78)),      # 灰藍
        neutral_panel((160, 140, 120), (78, 64, 52)),      # 灰棕
        left_line1="尼泊爾洪災逾1380死",
        left_line2="家屬赴總理府抗議",
        right_line1="直播帶貨美國爆紅",
        right_line2="砸數十億美元",
        date_text="2026/09/08",
        time_text="20:00",
        left_ai_note=True,
        right_ai_note=True,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(png)
    print(f"樣張：{OUT}（{len(png) / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
