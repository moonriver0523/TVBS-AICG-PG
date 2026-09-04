"""編輯專屬版型的後製合成：AI 生底圖，程式疊固定圖層。

為什麼固定元素一律由程式疊、不交給生圖模型：

1. **空間精準的東西模型做不到。** 安全框系列五輪實驗（見
   `docs/error-cases/2026-07-30-參考圖引導與遮罩-分析.md`）已經證死：連 API 遮罩
   硬約束那組都被無視，量到的左右留白只有 0.08%，五張全不合格。「播出鏡面」要在
   畫面裡挖一個**精確 16:9** 的空位給後製合成影片，靠 prompt 只會每張都不一樣。
   做法比照 `safe_frame.py`——由程式用數學貼上去。

2. **正版素材不能重畫。** TVBS Logo 讓模型畫必定變形。Logo、日期、ON AIR 標籤
   這類「錯了就是播出事故」的東西，只能是圖層合成。

3. **中文字交給程式畫零錯字。** 沿用 `docs/hybrid-rendering-proposal.md` 的核心
   原則：AI 負責視覺創意，APP 負責資訊正確性。

本模組刻意**不做**通用的圖層 DSL——目前只有兩個版型，兩個版型不值得一個直譯器。
兩支合成函式各自寫死自己的版面，共用底下的 `_paste_logo` / `_draw_text` 等小工具。
出現第三個版型時再抽表。
"""

import functools
import io
import pathlib

from PIL import Image, ImageDraw, ImageFont

import safe_area_spec

BRAND_DIR = pathlib.Path(__file__).resolve().parent / "static" / "brand"
TVBS_LOGO_WHITE = BRAND_DIR / "tvbs-logo-white.png"

# 中文字型：Pillow 不吃系統字型後備，必須指名檔案。依序找，第一個存在的就用。
# 開發機是 Windows，正式環境是 python:3.14-slim（Debian）——後者一個中文字型都沒有，
# Dockerfile 因此裝 fonts-noto-cjk。Debian 各版的 Noto CJK 檔名／目錄不一致
# （opentype/ vs truetype/、-Bold.ttc vs Black.otf），寫死路徑等於賭檔名，
# 所以 Linux 這段改用萬用字元掃出來。兩邊都找不到就明確報錯——
# 悄悄改用預設點陣字會畫出一整排豆腐，比直接失敗糟得多。
FONT_CANDIDATES_WINDOWS = (
    pathlib.Path("C:/Windows/Fonts/msjhbd.ttc"),
    pathlib.Path("C:/Windows/Fonts/NotoSansTC-VF.ttf"),
)
FONT_ROOTS_LINUX = (pathlib.Path("/usr/share/fonts"),)
# 粗體優先：這些字全是要壓在圖上的標題／浮水印，Regular 在照片上會糊掉。
FONT_GLOBS_LINUX = (
    "**/NotoSansCJK*Bold*",
    "**/NotoSansCJK*Black*",
    "**/NotoSansTC*Bold*",
    "**/NotoSansCJK*",
    "**/NotoSansTC*",
    "**/NotoSans*CJK*",
)


@functools.lru_cache(maxsize=None)
def discover_font(
    windows_candidates=FONT_CANDIDATES_WINDOWS,
    linux_roots=FONT_ROOTS_LINUX,
    linux_globs=FONT_GLOBS_LINUX,
):
    """找出這台機器上可用的中文粗體字型，找不到回 None。

    順序即優先序：先具名的 Windows 字型，再依 glob 由粗到細掃 Linux 字型目錄。
    同一個 glob 命中多個檔案時取排序後第一個，讓結果在不同機器上可重現。
    """
    for path in windows_candidates:
        if path.exists():
            return path
    for pattern in linux_globs:
        hits = []
        for root in linux_roots:
            if root.exists():
                hits.extend(p for p in root.glob(pattern) if p.is_file())
        if hits:
            return sorted(hits)[0]
    return None


class ComposeError(RuntimeError):
    """合成失敗。呼叫端必須讓它冒出去，不得默默回傳沒合成的圖。"""


def _font(size: int) -> ImageFont.FreeTypeFont:
    path = discover_font()
    if path is None:
        raise ComposeError(
            "找不到可用的中文粗體字型，合成會畫出豆腐。"
            f"找過：{'、'.join(str(p) for p in FONT_CANDIDATES_WINDOWS)}"
            f"，以及 {FONT_ROOTS_LINUX[0]} 底下的 Noto CJK"
        )
    return ImageFont.truetype(str(path), size)


def _fit_font(text: str, max_width: int, start_size: int, min_size: int) -> ImageFont.FreeTypeFont:
    """由大往小找第一個塞得進 max_width 的字級。

    標題長度由使用者決定，寫死字級遲早會撞到超出版面被裁掉的那一天。
    """
    size = start_size
    while size > min_size:
        font = _font(size)
        if font.getbbox(text)[2] <= max_width:
            return font
        size -= 2
    return _font(min_size)


def _draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    fill: tuple[int, int, int] = (255, 255, 255),
    stroke: tuple[int, int, int] | None = (8, 14, 32),
    stroke_width: int = 0,
    anchor: str = "la",
) -> None:
    draw.text(
        xy,
        text,
        font=font,
        fill=fill,
        anchor=anchor,
        stroke_width=stroke_width,
        stroke_fill=stroke if stroke_width else None,
    )


def _paste_logo(canvas: Image.Image, box: tuple[int, int], width: int) -> None:
    """把白色 TVBS Logo 貼在 box（左上角座標），等比例縮到 width。"""
    if not TVBS_LOGO_WHITE.exists():
        raise ComposeError(f"找不到 Logo 檔：{TVBS_LOGO_WHITE}")
    with Image.open(TVBS_LOGO_WHITE) as logo_file:
        logo = logo_file.convert("RGBA")
        height = round(logo.height * width / logo.width)
        logo = logo.resize((width, height), Image.LANCZOS)
        canvas.paste(logo, box, logo)


def _rounded(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=0) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


# ============================================================
# 版型 A：播出鏡面（在成品上挖一個 16:9 的空位給後製放影片）
# ============================================================

# 挖空框的幾何。全部由安全區換算，不寫死畫布座標——換 profile 時會自己跟著動。
# 這些數字**只存在於後製**，絕對不可以出現在任何 prompt 裡：模型會把數字當文字
# 畫進圖裡（見 docs/error-cases/2026-07-23-像素安全框-分析.md）。
HOLE_WIDTH_RATIO = 0.45     # 佔安全區寬度的比例；參考圖上約略是一半
HOLE_INSET = 24             # 距離安全區左右邊緣的內縮
# 垂直位置：0.0＝貼安全區頂、0.5＝正中央、1.0＝貼安全區底。
# 2026-09-03 使用者裁決「不要置底、往上靠中間」，從原本的貼底改成置中。
HOLE_VERTICAL_ANCHOR = 0.5
HOLE_RADIUS = 26
HOLE_FILL = (255, 255, 255)
HOLE_OUTLINE = (206, 206, 206)
HOLE_OUTLINE_WIDTH = 3

WATERMARK_TEXT = "示意圖"
WATERMARK_SIZE = 30
WATERMARK_FILL = (236, 236, 236)

BROADCAST_SIDES = ("left", "right")


def broadcast_hole_rect(
    canvas: tuple[int, int],
    side: str,
    profile: str = safe_area_spec.EDITOR_FRAME_PROFILE,
) -> tuple[int, int, int, int]:
    """算出挖空框在**成品畫布**上的座標。

    座標必須是成品座標，不是模型原圖座標——置框（safe_frame）會縮放並平移內容，
    在原圖上算好的框置框後會跑掉。所以這個框一律在 apply_safe_frame 之後才貼。
    """
    if side not in BROADCAST_SIDES:
        raise ComposeError(f"未知的挖空側：{side!r}（可用：{BROADCAST_SIDES}）")

    x0, y0, x1, y1 = safe_area_spec.safe_rect(*canvas, profile)
    # 寬度對齊 16 的倍數，高度才會是整數且長寬比**剛好** 16:9。
    # 四捨五入出來的 795×447 是 1.7785，後製把影片放進去會有半像素級的黑邊，
    # 這個框的整個存在意義就是給影片對位，不能將就。
    width = round((x1 - x0) * HOLE_WIDTH_RATIO) // 16 * 16
    height = width * 9 // 16

    band_top = y0 + HOLE_INSET
    band_bottom = y1 - HOLE_INSET
    if height > band_bottom - band_top:
        # 安全區太矮塞不下，改由高度反推寬度，維持 16:9 不變形
        height = (band_bottom - band_top) // 9 * 9
        width = height * 16 // 9
    top = band_top + round((band_bottom - band_top - height) * HOLE_VERTICAL_ANCHOR)

    left = x0 + HOLE_INSET if side == "left" else x1 - HOLE_INSET - width
    return left, top, left + width, top + height


def apply_broadcast_hole(
    image_bytes: bytes,
    side: str,
    *,
    canvas: tuple[int, int] = safe_area_spec.BASE_CANVAS,
    profile: str = safe_area_spec.EDITOR_FRAME_PROFILE,
    watermark: bool = True,
) -> bytes:
    """在置框後的成品上貼出挖空框（與右下角的示意圖浮水印）。

    刻意在模型畫完之後才蓋：就算模型在那一側畫了東西也無所謂，那塊本來就要留給
    後製合成影片。這正是「不靠模型自律」的意思。
    """
    with Image.open(io.BytesIO(image_bytes)) as opened:
        image = opened.convert("RGB")
        if image.size != canvas:
            # 置框輸出理應等於畫布；不等於就是上游改了尺寸，按實際尺寸重算比硬貼安全
            canvas = image.size
        draw = ImageDraw.Draw(image)
        rect = broadcast_hole_rect(canvas, side, profile)
        _rounded(
            draw, rect, HOLE_RADIUS, HOLE_FILL,
            outline=HOLE_OUTLINE, width=HOLE_OUTLINE_WIDTH,
        )
        if watermark:
            x0, y0, x1, y1 = safe_area_spec.safe_rect(*canvas, profile)
            _draw_text(
                draw,
                (x1 - HOLE_INSET, y1 - HOLE_INSET),
                WATERMARK_TEXT,
                _font(WATERMARK_SIZE),
                fill=WATERMARK_FILL,
                stroke_width=3,
                anchor="rs",
            )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ============================================================
# 版型 B：十點不一樣封面圖（左右兩張 AI 底圖＋程式畫的固定元素）
# ============================================================

COVER_CANVAS = (1920, 1080)
COVER_BG = (10, 24, 58)
COVER_BORDER = (24, 48, 104)

COVER_TOP_BAND = 208            # 標頭列高度
COVER_GUTTER = 18               # 左右兩張圖之間的溝
COVER_MARGIN = 26
COVER_IMAGE_HEIGHT = 656
COVER_TITLE_BAND = 216          # 208 + 656 + 216 = 1080，底部不留空帶

COVER_SHOW_NAME = "十點不一樣"
COVER_AI_NOTE = "AI示意圖"
COVER_BADGES = {
    "on_air": ("ON AIR", (206, 26, 32)),
    "highlight": ("精華", (206, 26, 32)),
}
COVER_DEFAULT_BADGE = "on_air"


# 純 prompt 版唯一的後製：把正版白色 Logo 貼在模型刻意留空的左上角。
# 位置與大小用畫布比例算，模型回什麼解析度都對得上。
# 比例取自使用者的範例封面（1672×941）：logo 佔 x 20..345、y 10..178。
COVER_LOGO_WIDTH_RATIO = 0.185
COVER_LOGO_LEFT_RATIO = 0.015
COVER_LOGO_TOP_RATIO = 0.015


def paste_cover_logo(image_bytes: bytes) -> bytes:
    """在 AI 畫好的封面左上角貼上正版白色 Logo。

    prompt 已明令模型不准畫任何電視台標誌、並把左上角留白（見
    editor_formats.COVER_AI_PROMPT_TEMPLATE）。就算模型沒聽話畫了東西，
    貼上去也會蓋掉——與播出鏡面挖空框同一個原則：不靠模型自律。
    """
    with Image.open(io.BytesIO(image_bytes)) as opened:
        canvas = opened.convert("RGB")
        width = max(1, round(canvas.width * COVER_LOGO_WIDTH_RATIO))
        box = (
            round(canvas.width * COVER_LOGO_LEFT_RATIO),
            round(canvas.height * COVER_LOGO_TOP_RATIO),
        )
        _paste_logo(canvas, box, width)

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def _cover_panel(image_bytes: bytes, size: tuple[int, int]) -> Image.Image:
    """把一張 AI 底圖等比例填滿指定版位（COVER 裁切，不變形）。"""
    with Image.open(io.BytesIO(image_bytes)) as opened:
        source = opened.convert("RGB")
    target_w, target_h = size
    scale = max(target_w / source.width, target_h / source.height)
    resized = source.resize(
        (max(target_w, round(source.width * scale)), max(target_h, round(source.height * scale))),
        Image.LANCZOS,
    )
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def compose_ten_cover(
    left_image: bytes,
    right_image: bytes,
    *,
    title_left: str,
    title_right: str,
    date_text: str,
    badge: str = COVER_DEFAULT_BADGE,
) -> bytes:
    """合成「十點不一樣」封面圖。

    AI 只提供左右兩張**無文字**底圖；節目名、Logo、日期、標籤、兩邊標題與
    AI 示意圖標註全部由這裡畫，所以不可能出現錯字或變形的 Logo。
    """
    if badge not in COVER_BADGES:
        raise ComposeError(f"未知的標籤：{badge!r}（可用：{list(COVER_BADGES)}）")

    canvas = Image.new("RGB", COVER_CANVAS, COVER_BG)
    draw = ImageDraw.Draw(canvas)
    width, height = COVER_CANVAS

    panel_w = (width - COVER_MARGIN * 2 - COVER_GUTTER) // 2
    panel_y = COVER_TOP_BAND
    for index, raw in enumerate((left_image, right_image)):
        panel = _cover_panel(raw, (panel_w, COVER_IMAGE_HEIGHT))
        x = COVER_MARGIN + index * (panel_w + COVER_GUTTER)
        canvas.paste(panel, (x, panel_y))

    # ---- 標頭列 ----
    _paste_logo(canvas, (COVER_MARGIN + 24, 48), 236)

    show_font = _fit_font(COVER_SHOW_NAME, 700, 104, 60)
    _draw_text(
        draw, (width // 2, COVER_TOP_BAND // 2), COVER_SHOW_NAME, show_font,
        stroke_width=6, anchor="mm",
    )

    badge_text, badge_colour = COVER_BADGES[badge]
    badge_font = _font(38)
    badge_w = badge_font.getbbox(badge_text)[2] + 44
    badge_x1 = width - COVER_MARGIN - 24
    _rounded(draw, (badge_x1 - badge_w, 44, badge_x1, 44 + 58), 10, badge_colour)
    _draw_text(draw, (badge_x1 - badge_w // 2, 44 + 29), badge_text, badge_font, stroke_width=0, anchor="mm")
    _draw_text(draw, (badge_x1, 122), date_text, _font(40), stroke_width=3, anchor="ra")

    # ---- 兩邊標題 ----
    title_y = panel_y + COVER_IMAGE_HEIGHT + COVER_TITLE_BAND // 2
    for index, title in enumerate((title_left, title_right)):
        text = (title or "").strip()
        if not text:
            continue
        font = _fit_font(text, panel_w - 72, 82, 34)
        centre_x = COVER_MARGIN + index * (panel_w + COVER_GUTTER) + panel_w // 2
        _draw_text(draw, (centre_x, title_y), text, font, stroke_width=8, anchor="mm")

    # ---- AI 示意圖標註（每張底圖右下角）----
    note_font = _font(28)
    for index in range(2):
        x = COVER_MARGIN + index * (panel_w + COVER_GUTTER) + panel_w - 16
        _draw_text(
            draw, (x, panel_y + COVER_IMAGE_HEIGHT - 14), COVER_AI_NOTE, note_font,
            stroke_width=4, anchor="rs",
        )

    draw.rectangle((0, 0, width - 1, height - 1), outline=COVER_BORDER, width=COVER_MARGIN)

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()
