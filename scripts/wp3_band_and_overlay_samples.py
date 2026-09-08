"""WP3 樣張產生器（2026-09-08）：底色框定版（第 3 位置＋上緣羽化）藍／紅，以及 PNG 壓標原型。

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
MAIN_TITLE = "週五變天北、東轉雨"
SUB_TITLE = "明早晚涼「中午仍破30度」"
# (檔名, kwargs)。四組是 lead 指定的；第五組多出來，是為了把「副標欄改深紅」跟
# 截圖的全藍版擺在一起比——兩張參考截圖裡都沒有紅欄，這件事得讓使用者自己看。
VSTRIP_COMBOS = (
    ("一般_左緣_Logo右上", dict(variant="normal", title_side="left", logo_corner="tr")),
    ("原音呈現_左緣_Logo右上_來源跟LIVE",
     dict(variant="original_audio", title_side="left", logo_corner="tr")),
    ("原音呈現_左緣_Logo右下_來源跟Logo",
     dict(variant="original_audio", title_side="left", logo_corner="br",
          source_follow_logo=True)),
    ("一般_右緣_Logo左上", dict(variant="normal", title_side="right", logo_corner="tl")),
    ("一般_左緣_Logo右上_副標深紅",
     dict(variant="normal", title_side="left", logo_corner="tr", sub_fill=(120, 18, 28))),
)
BACKDROP = OUT / "20260908_直標參考_一般國內直播.png"


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
    """定版底色框（不傳覆寫參數＝線上實際行為）。"""
    background = _png(neutral_backdrop())
    written = []
    blue = compose.compose_yt_cover(background, line1=LINE1, line2=LINE2, date_text=DATE, bottom_band=True)
    red = compose.compose_yt_hot_cover(background, line1=LINE1, line2=LINE2, bottom_band=True)
    for colour, data in (("藍", blue), ("紅", red)):
        path = OUT / f"20260908_底色框_定版_{colour}.png"
        path.write_bytes(data)
        written.append(path)
    return written


def live_backdrop() -> Image.Image:
    """把參考截圖放大到 1920×1080 當預覽底：要看的是疊起來像不像，蓋掉原本的直標沒關係。"""
    if not BACKDROP.exists():
        return neutral_backdrop()
    with Image.open(BACKDROP) as ref:
        return ref.convert("RGB").resize(compose.YT_CANVAS, Image.LANCZOS)


def vertical_samples() -> list[pathlib.Path]:
    written = []
    backdrop = live_backdrop()
    for label, kwargs in VSTRIP_COMBOS:
        data = compose.compose_yt_overlay(
            main_title=MAIN_TITLE, sub_title=SUB_TITLE, source_text=SOURCE, **kwargs,
        )
        transparent = OUT / f"20260908_YT直標_{label}_透明.png"
        transparent.write_bytes(data)
        written.append(transparent)

        preview = backdrop.copy().convert("RGBA")
        preview.alpha_composite(Image.open(io.BytesIO(data)).convert("RGBA"))
        path = OUT / f"20260908_YT直標_{label}_預覽.png"
        path.write_bytes(_png(preview.convert("RGB")))
        written.append(path)
    return written


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("20260908_YT壓標_*.png"):
        stale.unlink()          # 第一版的橫向壓標樣張，規格作廢
        print("removed", stale)
    for path in band_samples() + vertical_samples():
        print(path)
    print()
    print(f"底色框: top={compose.YT_BAND_TOP_RATIO} fade={compose.YT_BAND_FADE_RATIO} 羽化結尾={compose.YT_BAND_TOP_RATIO + compose.YT_BAND_FADE_RATIO:.4f}")
    print(f"第一行墨水上緣={compose._yt_title_ink_top_ratio(compose.YT_LINE1_BASELINE_RATIO):.4f}")
    print(f"第二行墨水上緣={compose._yt_title_ink_top_ratio(compose.YT_LINE2_BASELINE_RATIO):.4f}")
    print()
    layout = compose.yt_vertical_layout(main_title=MAIN_TITLE, sub_title=SUB_TITLE)
    print(f"主標 {len(layout['main_cells'])} 格：{' '.join(layout['main_cells'])}")
    print(f"副標 {len(layout['sub_cells'])} 格：{' '.join(layout['sub_cells'])}")
    print(f"欄高 {layout['column_height']}px  主標 {layout['main']}  副標 {layout['sub']}")


if __name__ == "__main__":
    main()
