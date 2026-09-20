"""出樣張給使用者用眼睛驗收 B80／B46（2026-09-20，官方底圖當固定層之後的直標）。

不接端點、不接 UI、不呼叫任何生圖 API——甲案本來就是「官方底圖＋Pillow 壓字」，
直接呼叫 compose.compose_yt_overlay 就是最終成品的畫法，不需要另外準備底圖或跑
模型。每組各存兩張：`_透明` 是端點實際回傳的那張 PNG（RGBA，本身沒有底圖）；
`_預覽` 是疊在中性深灰底上的版本，方便肉眼看貼到直播畫面上的樣子。

    python -X utf8 scripts/b80_vstrip_official_bg_samples.py
"""

from __future__ import annotations

import io
import pathlib
import sys

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import compose  # noqa: E402

OUT = pathlib.Path(r"D:\Downloads\20260920_B80直標_sample.png")
BACKDROP = (60, 70, 90)          # 中性深灰，只是給眼睛看，不是真的直播畫面

MAIN = "週五變天北、東轉雨"
SUB = "明早晚涼「中午仍破30度」"
# 12／14 格都頂到規格上限——B80 訂的字級下限（32px@1080）就是照這組算出來的，
# 這兩組是驗收「縮到下限還讀得出來」用的。
MAX_MAIN = "十二個格子滿滿滿滿的標題"
MAX_SUB = "十四個格子滿滿滿滿滿的標題喔"

SAMPLES = (
    ("一般_左緣", dict(main_title=MAIN, sub_title=SUB, title_side="left", logo_corner="tr")),
    ("一般_右緣鏡射", dict(main_title=MAIN, sub_title=SUB, title_side="right", logo_corner="tl")),
    ("原音呈現", dict(main_title=MAIN, sub_title=SUB, variant="original_audio", source_text="路透社")),
    ("AI即時翻譯", dict(main_title=MAIN, sub_title=SUB, variant="ai_translation")),
    ("LIVE章關閉", dict(main_title=MAIN, sub_title=SUB, live=False)),
    ("字級下限_12+14格", dict(main_title=MAX_MAIN, sub_title=MAX_SUB)),
    ("字級下限_有小標", dict(main_title=MAX_MAIN, sub_title=MAX_SUB, variant="original_audio")),
)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for name, kwargs in SAMPLES:
        png = compose.compose_yt_overlay(**kwargs)

        transparent = OUT.with_name(f"{OUT.stem}_{name}_透明.png")
        transparent.write_bytes(png)
        print(f"{name}（透明）：{transparent}（{len(png) / 1024:.0f} KB）")

        preview_canvas = Image.new("RGBA", compose.YT_CANVAS, BACKDROP + (255,))
        preview_canvas.alpha_composite(Image.open(io.BytesIO(png)).convert("RGBA"))
        preview_path = OUT.with_name(f"{OUT.stem}_{name}_預覽.png")
        preview_canvas.convert("RGB").save(preview_path)
        print(f"{name}（預覽）：{preview_path}")


if __name__ == "__main__":
    main()
