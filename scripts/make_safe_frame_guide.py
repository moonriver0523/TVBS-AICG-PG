"""產生「安全框引導圖」，供 B 階段參考圖引導實驗當作模型的輸入圖。

背景：像素版／百分比版／純文字版三輪 prompt 實驗都證實，安全框寫成文字（尤其是數字）
無法讓模型精準遵守；數字甚至會被當成文字畫進圖裡。本階段改走「圖片通道」——
不在 prompt 裡講任何數字，改用一張圖告訴模型內容該落在哪裡。

引導圖本身**絕對不含任何文字或數字**（歷史教訓：圖上有字，模型會照抄）。

三種變體：
- twotone：中央亮、四周暗。最直觀的「亮處作畫」暗示。
- chroma：四周改成純綠。專門用來偵測「引導圖顏色滲進輸出」這個失敗型態。
- wireframe：黑底＋安全區內灰色版位方塊。用構圖範例引導，比抽象色塊更符合
  影像模型的能力（模型很擅長模仿參考圖的構圖）。

另外產生 GPT native `images.edit` 用的底圖＋遮罩對：遮罩透明處＝允許作畫，
不透明處＝維持底圖不變，因此留白由 API 硬性保證，不靠模型自律。

用法：
    uv run python scripts/make_safe_frame_guide.py
    uv run python scripts/make_safe_frame_guide.py --variant wireframe --width 1920
"""

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import safe_area_spec  # noqa: E402  （需先加入專案根目錄到 sys.path）

DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "assets"

# 中央亮區／四周暗區的顏色。刻意用中性灰，避免模型把它當成配色參考。
CENTRE_LIGHT = (221, 221, 221)
MARGIN_DARK = (51, 51, 51)
MARGIN_CHROMA = (0, 177, 64)  # 純綠，滲色一眼可見
WIREFRAME_BG = (10, 10, 10)
WIREFRAME_BLOCK = (150, 150, 150)


def make_twotone(width: int, height: int, margin_color: tuple[int, int, int]) -> Image.Image:
    """中央安全區亮、四周留白暗。"""
    img = Image.new("RGB", (width, height), margin_color)
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = safe_area_spec.safe_rect(width, height)
    draw.rectangle([x0, y0, x1 - 1, y1 - 1], fill=CENTRE_LIGHT)
    return img


def make_wireframe(width: int, height: int) -> Image.Image:
    """安全區內放灰色版位方塊，用構圖範例引導；四周純黑留空。"""
    img = Image.new("RGB", (width, height), WIREFRAME_BG)
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = safe_area_spec.safe_rect(width, height)
    zone_w = x1 - x0
    zone_h = y1 - y0
    gap = round(zone_w * 0.03)

    # 標題橫塊：安全區頂端，寬度留一點餘裕，不貼安全區左右界
    title_h = round(zone_h * 0.18)
    draw.rectangle(
        [x0 + gap, y0 + gap, x0 + round(zone_w * 0.72), y0 + gap + title_h],
        fill=WIREFRAME_BLOCK,
    )

    # 三張並排資訊卡：安全區中段
    cards_top = y0 + gap * 2 + title_h
    cards_h = round(zone_h * 0.42)
    card_w = (zone_w - gap * 2 - gap * 2) // 3
    for i in range(3):
        left = x0 + gap + i * (card_w + gap)
        draw.rectangle(
            [left, cards_top, left + card_w, cards_top + cards_h],
            fill=WIREFRAME_BLOCK,
        )

    # 結論／來源細長條：安全區最低一列，仍在安全區內側
    strip_h = round(zone_h * 0.09)
    strip_bottom = y1 - gap
    draw.rectangle(
        [x0 + gap, strip_bottom - strip_h, x0 + round(zone_w * 0.55), strip_bottom],
        fill=WIREFRAME_BLOCK,
    )
    return img


def make_edit_base(width: int, height: int) -> Image.Image:
    """GPT images.edit 的底圖：整張單色深底。遮罩保護的留白會原封不動留下這個顏色。"""
    return Image.new("RGB", (width, height), (12, 18, 32))


def make_edit_mask(width: int, height: int) -> Image.Image:
    """GPT images.edit 的遮罩：安全區透明（允許作畫），四周不透明（保護留白）。"""
    mask = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    draw = ImageDraw.Draw(mask)
    x0, y0, x1, y1 = safe_area_spec.safe_rect(width, height)
    draw.rectangle([x0, y0, x1 - 1, y1 - 1], fill=(0, 0, 0, 0))
    return mask


def build(variant: str, width: int, height: int) -> Image.Image:
    if variant == "twotone":
        return make_twotone(width, height, MARGIN_DARK)
    if variant == "chroma":
        return make_twotone(width, height, MARGIN_CHROMA)
    if variant == "wireframe":
        return make_wireframe(width, height)
    if variant == "edit-base":
        return make_edit_base(width, height)
    if variant == "edit-mask":
        return make_edit_mask(width, height)
    raise ValueError(f"未知變體：{variant}")


VARIANTS = ("twotone", "chroma", "wireframe", "edit-base", "edit-mask")


def main() -> None:
    parser = argparse.ArgumentParser(description="產生安全框引導圖")
    parser.add_argument(
        "--variant",
        choices=(*VARIANTS, "all"),
        default="all",
        help="要產生的變體，預設全部",
    )
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    targets = VARIANTS if args.variant == "all" else (args.variant,)

    x0, y0, x1, y1 = safe_area_spec.safe_rect(args.width, args.height)
    print(f"畫布 {args.width}×{args.height}，安全區 x {x0}–{x1} / y {y0}–{y1}")
    print(f"四邊留白像素：{safe_area_spec.required_margins_px(args.width, args.height)}")

    for variant in targets:
        img = build(variant, args.width, args.height)
        path = args.out_dir / f"safe-guide-{variant}-{args.width}x{args.height}.png"
        img.save(path)
        print(f"已產生 {path}")


if __name__ == "__main__":
    main()
