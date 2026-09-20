"""出一張「YT 整點雙則」樣張給使用者看版面（WP2，2026-09-08）。

雙則＝同一張底圖上下兩行標題（上白＝第一則、下黃＝第二則），底圖由左右兩張羽化拼成。
不打生圖 API：兩格底圖用中性色（灰藍／灰棕）在本機畫，重點是接縫與標題不是照片。

    python -X utf8 scripts/make_yt_hourly_dual_sample.py
"""

from __future__ import annotations

import io
import pathlib
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import compose  # noqa: E402

OUT = pathlib.Path(r"D:\Downloads\20260908_YT整點雙則_sample.png")


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
    background = compose.blend_backgrounds_lr(
        neutral_panel((122, 140, 166), (48, 60, 78)),      # 灰藍：第一則
        neutral_panel((166, 142, 116), (82, 66, 50)),      # 灰棕：第二則
    )
    png = compose.compose_yt_hourly_cover(
        background,
        line1="尼泊爾洪災逾1380死家屬抗議",
        line2="直播帶貨美國爆紅砸數十億",
        date_text="2026/09/08",
        time_text="20:00",
        ai_note=True,
        line_max_chars=compose.YT_HOURLY_LINE_MAX_CHARS,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(png)
    print(f"樣張：{OUT}（{len(png) / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
