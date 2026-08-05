"""畫一張 TVBS 安全框規格示意圖，給報告與簡報使用。

數字一律從 safe_area_spec 讀，不手抄——那份常數已有測試釘住，
手抄一次就多一個會過期的來源（規格出處：docs/examples/tvbs-safe-frame-locked-tool.md）。

用法：python scripts/build_safe_frame_diagram.py
輸出：docs/assets/report/safe-frame-spec.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import safe_area_spec  # noqa: E402

OUT = REPO / "docs" / "assets" / "report" / "safe-frame-spec.png"

SCALE = 0.62  # 1920x1080 → 1190x670，貼進報告不必再縮
PAD = 56  # 四周留給標註文字的空間

INK = (28, 36, 49)
MUTED = (110, 122, 138)
ACCENT = (11, 92, 171)
SAFE_FILL = (232, 241, 250)
OUTSIDE = (243, 245, 248)
LINE = (196, 206, 218)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """找一個裝得出繁體中文的字型；找不到就退回預設（英數仍可讀）。"""
    for name in ("msjhbd.ttc" if bold else "msjh.ttc", "msjh.ttc", "mingliu.ttc"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def main() -> None:
    canvas_w, canvas_h = safe_area_spec.BASE_CANVAS
    x, y, w, h = safe_area_spec.BASE_SAFE_RECT

    width = int(canvas_w * SCALE) + PAD * 2
    height = int(canvas_h * SCALE) + PAD * 2
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)

    def sx(v: float) -> float:
        return PAD + v * SCALE

    def sy(v: float) -> float:
        return PAD + v * SCALE

    f_small = load_font(19)
    f_body = load_font(22)
    f_big = load_font(30, bold=True)

    # 整張畫布
    d.rectangle([sx(0), sy(0), sx(canvas_w), sy(canvas_h)], fill=OUTSIDE, outline=LINE, width=2)
    # 安全框
    d.rectangle([sx(x), sy(y), sx(x + w), sy(y + h)], fill=SAFE_FILL, outline=ACCENT, width=3)

    d.text(
        (sx(x + w / 2), sy(y + h / 2) - 26),
        "安全框",
        font=f_big,
        fill=ACCENT,
        anchor="mm",
    )
    d.text(
        (sx(x + w / 2), sy(y + h / 2) + 14),
        f"{w} × {h}",
        font=f_body,
        fill=ACCENT,
        anchor="mm",
    )
    d.text(
        (sx(x + w / 2), sy(y + h / 2) + 46),
        f"起點 X={x}, Y={y}",
        font=f_small,
        fill=MUTED,
        anchor="mm",
    )

    right = canvas_w - x - w
    bottom = canvas_h - y - h

    # 四邊留白標註（畫在留白帶的中線上）。
    # 左右兩條帶子只有約 87px 寬，橫排會被畫布邊緣切掉，所以拆成兩行。
    marks = [
        ((x + w / 2, y / 2), f"上 {y}px"),
        ((x / 2, y + h / 2), f"左\n{x}px"),
        ((x + w + right / 2, y + h / 2), f"右\n{right}px"),
        ((x + w / 2, y + h + bottom / 2), f"下 {bottom}px　預留下標與跑馬燈"),
    ]
    for (mx, my), text in marks:
        d.multiline_text(
            (sx(mx), sy(my)), text, font=f_body, fill=INK, anchor="mm", align="center", spacing=4
        )

    # 外框尺寸與出處
    d.text((sx(0), sy(0) - 30), f"畫布 {canvas_w} × {canvas_h}", font=f_body, fill=INK, anchor="ls")
    d.text(
        (sx(canvas_w), sy(canvas_h) + 30),
        "數值來源：TVBS 官方安全框工具 Studio Locked-Frame（2026-07-24 實測）",
        font=f_small,
        fill=MUTED,
        anchor="rs",
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG", optimize=True)
    print(f"已產生 {OUT}（{OUT.stat().st_size / 1024:.0f} KB，{width}x{height}）")
    print(f"讀到的規格：畫布 {canvas_w}x{canvas_h}，安全框 X={x} Y={y} W={w} H={h}")
    print(f"四邊留白：上 {y} / 左 {x} / 右 {right} / 下 {bottom}")


if __name__ == "__main__":
    main()
