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

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import safe_area_spec

BRAND_DIR = pathlib.Path(__file__).resolve().parent / "static" / "brand"
TVBS_LOGO_WHITE = BRAND_DIR / "tvbs-logo-white.png"

# 中文字型：Pillow 不吃系統字型後備，必須指名檔案。依序找，第一個存在的就用。
#
# 2026-09-06 起第一順位是 repo 自帶的台北黑體 Bold（static/fonts/，SIL OFL）。
# 理由：日期／整點時間這類程式壓上去的數字，用微軟正黑體（本機）或 Noto CJK（Cloud Run）
# 都又寬又鬆、很醜，而且兩邊字型不同，本機看到的跟線上永遠對不起來。
# 字型隨 repo 進容器，本機與 Cloud Run 畫出來一模一樣。
#
# 後備維持原樣：開發機是 Windows，正式環境是 python:3.14-slim（Debian）——後者一個
# 中文字型都沒有，Dockerfile 因此裝 fonts-noto-cjk。Debian 各版的 Noto CJK 檔名／目錄
# 不一致（opentype/ vs truetype/、-Bold.ttc vs Black.otf），寫死路徑等於賭檔名，
# 所以 Linux 這段改用萬用字元掃出來。全部找不到就明確報錯——
# 悄悄改用預設點陣字會畫出一整排豆腐，比直接失敗糟得多。
FONT_DIR = pathlib.Path(__file__).resolve().parent / "static" / "fonts"
FONT_CANDIDATES_BUNDLED = (FONT_DIR / "TaipeiSansTCBeta-Bold.ttf",)
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
    bundled_candidates=FONT_CANDIDATES_BUNDLED,
):
    """找出可用的中文粗體字型，找不到回 None。

    順序即優先序：repo 自帶字型 → 具名的 Windows 字型 → 依 glob 由粗到細掃 Linux 字型目錄。
    同一個 glob 命中多個檔案時取排序後第一個，讓結果在不同機器上可重現。
    """
    for path in (*bundled_candidates, *windows_candidates):
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
            f"找過：{'、'.join(str(p) for p in (*FONT_CANDIDATES_BUNDLED, *FONT_CANDIDATES_WINDOWS))}"
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


# ============================================================
# YT 直播封面（2026-09-05）
#
# 底圖（附圖或 AI 生的無文字圖）鋪滿 16:9，上面疊：左上 LIVE 章＋日期條、右上
# 正版 Logo（＋可選副標）、底部兩行標題（白／黃、黑描邊）、AI 底圖時右側小字
# 「AI示意圖」。所有幾何以畫布比例計，量自使用者範例（1376×768）。
#
# LIVE 章是生圖模型重製的高清去背 PNG（static/brand/live-badge.png）；官方檔到手時
# 直接換檔即可，位置與尺寸不用動。日期每天不同，由程式畫在章下方的白色小條上。
# ============================================================

LIVE_BADGE = BRAND_DIR / "live-badge.png"

YT_CANVAS = (1920, 1080)
# 2026-09-06 改依 TVBS NEWS 頻道實際上線的直播封面量（maxresdefault 1280×720），
# 不再依 docx 範例：標題置中壓深藍科技底帶、右上藍色 TVBS 小標籤、
# 「原音呈現」白字紅邊在 LIVE 章上方、「AI即時翻譯」小白字在日期下方，兩者可並存。
YT_MARGIN_RATIO = 0.026              # LIVE 章左緣（33/1280）
YT_TOP_RATIO = 0.05                  # LIVE 章上緣（無原音呈現時）
YT_TOP_WITH_LABEL_RATIO = 0.128      # 有原音呈現時章往下讓位
YT_BADGE_WIDTH_RATIO = 0.227         # LIVE 章寬（290/1280）
YT_DATE_TAB_WIDTH_RATIO = 0.219      # 日期白條寬（280/1280）
YT_DATE_TAB_HEIGHT_RATIO = 0.111     # 日期白條高（80/720）
YT_DATE_FILL = (255, 255, 255)
YT_DATE_TEXT = (200, 20, 30)
YT_DATE_BORDER = (214, 22, 32)          # 頻道實際版：白框外圈一道紅邊，與 LIVE 章同色
YT_DATE_BORDER_RATIO = 0.0037           # 邊寬 4/1080
YT_ORIGINAL_AUDIO_LABEL = "原音呈現"
YT_ORIGINAL_AUDIO_SIZE_RATIO = 0.09  # 字高 64/720
YT_ORIGINAL_AUDIO_BASELINE_RATIO = 0.118
YT_ORIGINAL_AUDIO_FILL = (255, 255, 255)
YT_ORIGINAL_AUDIO_STROKE = (215, 25, 35)
YT_AI_TRANSLATION_LABEL = "AI即時翻譯"
YT_AI_TRANSLATION_SIZE_RATIO = 0.05
YT_AI_TRANSLATION_GAP_RATIO = 0.02   # 日期條底到小字頂的距離
YT_LOGO_TAB_LEFT_RATIO = 0.802       # 右上藍標籤：左上角 x（貼右上角、延伸出畫面）
YT_LOGO_TAB_SLANT_RATIO = 0.037      # 左邊斜切：底邊比頂邊內縮多少
YT_LOGO_TAB_HEIGHT_RATIO = 0.153
YT_LOGO_TAB_TOP = (70, 180, 255)
YT_LOGO_TAB_BOTTOM = (15, 95, 210)
YT_LOGO_WIDTH_RATIO = 0.14           # Logo 寬（180/1280）
# 畫面最頂端一道很窄的藍色漸層線，橫貫全寬、與右上標籤同色系（頻道實際版每張都有，
# 2026-09-06 使用者對照型錄指出漏畫）。實測 1280×720 縮圖約 4–10px，取中間值。
YT_TOP_LINE_HEIGHT_RATIO = 0.022
YT_TOP_LINE_TOP = (27, 122, 222)
YT_TOP_LINE_BOTTOM = (32, 165, 218)
YT_LOGO_LEFT_RATIO = 0.844
YT_LOGO_TOP_RATIO = 0.014
YT_BAND_TOP_RATIO = 0.60             # 深藍科技底帶起點
YT_BAND_FADE_RATIO = 0.06            # 頂端漸入高度
YT_BAND_FILL = (8, 25, 70)
YT_BAND_ALPHA = 205
YT_BAND_BLOCK_FILL = (60, 130, 230)
YT_LINE1_BASELINE_RATIO = 0.764      # 第一行字底
YT_LINE2_BASELINE_RATIO = 0.958      # 第二行字底
YT_TITLE_SIZE_RATIO = 0.145          # 標題起始字級（字高約 100/720）
YT_TITLE_MIN_SIZE_RATIO = 0.085
YT_TITLE_STROKE_RATIO = 0.05         # 描邊佔字級比例
YT_LINE1_FILL = (255, 255, 255)
YT_LINE2_FILL = (250, 215, 0)
YT_TITLE_STROKE = (8, 8, 8)
YT_AI_NOTE = "AI示意圖"
YT_AI_NOTE_SIZE_RATIO = 0.032
YT_AI_NOTE_TOP_RATIO = 0.20          # 藍標籤之下的右側空位
YT_AI_NOTE_PLATE = (0, 0, 0, 120)


def _paste_live_badge(canvas: Image.Image, box: tuple[int, int], width: int) -> int:
    """貼 LIVE 章，回傳貼上後的高度（日期條要接在它正下方）。"""
    if not LIVE_BADGE.exists():
        raise ComposeError(f"找不到 LIVE 章素材：{LIVE_BADGE}")
    with Image.open(LIVE_BADGE) as badge_file:
        badge = badge_file.convert("RGBA")
        height = round(badge.height * width / badge.width)
        badge = badge.resize((width, height), Image.LANCZOS)
        canvas.paste(badge, box, badge)
    return height


def _draw_ai_note(canvas: Image.Image, y0: int) -> None:
    """右側「AI示意圖」小標（半透明黑底、白字），y0 為標籤頂。"""
    width, height = YT_CANVAS
    margin = round(width * YT_MARGIN_RATIO)
    note_font = _font(round(height * YT_AI_NOTE_SIZE_RATIO))
    note_w = note_font.getbbox(YT_AI_NOTE)[2]
    note_h = round(height * YT_AI_NOTE_SIZE_RATIO * 1.5)
    x1 = width - margin - 12
    plate = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle(
        (x1 - note_w - 24, y0, x1, y0 + note_h), radius=8, fill=YT_AI_NOTE_PLATE
    )
    canvas.alpha_composite(plate)
    _draw_text(ImageDraw.Draw(canvas), (x1 - 12, y0 + note_h // 2), YT_AI_NOTE, note_font, stroke_width=0, anchor="rm")


def _draw_top_line(canvas: Image.Image) -> None:
    """畫面最頂端橫貫全寬的窄藍色漸層線（上深下淺）。要在標籤之前畫，標籤壓在它上面。"""
    width, height = YT_CANVAS
    line_h = max(2, round(height * YT_TOP_LINE_HEIGHT_RATIO))
    line = Image.new("RGBA", (width, line_h))
    px = line.load()
    for y in range(line_h):
        t = y / max(1, line_h - 1)
        c = tuple(round(a + (b - a) * t) for a, b in zip(YT_TOP_LINE_TOP, YT_TOP_LINE_BOTTOM)) + (255,)
        for x in range(width):
            px[x, y] = c
    canvas.alpha_composite(line, (0, 0))


def _draw_logo_tab(canvas: Image.Image) -> None:
    """右上角藍色漸層標籤（左邊斜切、左下圓角）＋白色 TVBS Logo，貼著畫面右上角。"""
    width, height = YT_CANVAS
    tab_h = round(height * YT_LOGO_TAB_HEIGHT_RATIO)
    x_top = round(width * YT_LOGO_TAB_LEFT_RATIO)
    x_bottom = x_top + round(width * YT_LOGO_TAB_SLANT_RATIO)
    radius = round(width * 0.02)
    # 4 倍超取樣畫遮罩，斜邊與圓角才不會鋸齒
    scale = 4
    mask = Image.new("L", (width * scale, (tab_h + radius) * scale), 0)
    md = ImageDraw.Draw(mask)
    pts = [
        (x_top * scale, -radius * scale),
        (width * scale + radius * scale, -radius * scale),
        (width * scale + radius * scale, tab_h * scale),
        ((x_bottom + radius) * scale, tab_h * scale),
        (x_bottom * scale, (tab_h - radius) * scale),
    ]
    md.polygon(pts, fill=255)
    md.pieslice(
        ((x_bottom) * scale, (tab_h - 2 * radius) * scale, (x_bottom + 2 * radius) * scale, tab_h * scale),
        90, 180, fill=255,
    )
    md.polygon(
        [((x_bottom) * scale, (tab_h - radius) * scale), ((x_bottom + radius) * scale, (tab_h - radius) * scale),
         ((x_bottom + radius) * scale, tab_h * scale), ((x_bottom) * scale, tab_h * scale)],
        fill=0,
    )
    md.pieslice(
        ((x_bottom) * scale, (tab_h - 2 * radius) * scale, (x_bottom + 2 * radius) * scale, tab_h * scale),
        90, 180, fill=255,
    )
    mask = mask.resize((width, tab_h + radius), Image.LANCZOS).crop((0, 0, width, tab_h))
    gradient = Image.new("RGBA", (width, tab_h))
    gd = ImageDraw.Draw(gradient)
    for y in range(tab_h):
        t = y / max(1, tab_h - 1)
        colour = tuple(round(YT_LOGO_TAB_TOP[i] * (1 - t) + YT_LOGO_TAB_BOTTOM[i] * t) for i in range(3))
        gd.line(((0, y), (width, y)), fill=colour + (255,))
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(gradient, (0, 0), mask)
    canvas.alpha_composite(layer)
    _paste_logo(canvas, (round(width * YT_LOGO_LEFT_RATIO), round(height * YT_LOGO_TOP_RATIO)), round(width * YT_LOGO_WIDTH_RATIO))


def _draw_title_band(canvas: Image.Image) -> None:
    """底部深藍科技底帶：頂端漸入，帶上撒幾塊半透明淡藍方塊模擬頻道的電路紋。"""
    width, height = YT_CANVAS
    top = round(height * YT_BAND_TOP_RATIO)
    fade = round(height * YT_BAND_FADE_RATIO)
    band = Image.new("RGBA", (width, height - top), YT_BAND_FILL + (0,))
    alpha = Image.new("L", band.size, YT_BAND_ALPHA)
    ad = ImageDraw.Draw(alpha)
    for y in range(fade):
        ad.line(((0, y), (width, y)), fill=round(YT_BAND_ALPHA * y / fade))
    band.putalpha(alpha)
    blocks = Image.new("RGBA", band.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(blocks)
    # 固定序列，不用亂數：同一張輸入永遠得到同一張輸出
    seq = [(0.02, 0.35, 0.09, 0.05), (0.13, 0.62, 0.05, 0.16), (0.21, 0.10, 0.12, 0.05),
           (0.36, 0.72, 0.08, 0.10), (0.47, 0.20, 0.05, 0.20), (0.58, 0.58, 0.13, 0.05),
           (0.70, 0.08, 0.06, 0.14), (0.79, 0.66, 0.10, 0.07), (0.90, 0.28, 0.07, 0.18)]
    for fx, fy, fw, fh in seq:
        x0, y0 = round(fx * width), round(fy * band.height)
        bd.rectangle((x0, y0, x0 + round(fw * width), y0 + round(fh * band.height)), fill=YT_BAND_BLOCK_FILL + (55,))
    blocks = blocks.filter(ImageFilter.GaussianBlur(3))
    band.alpha_composite(blocks)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(band, (0, top))
    canvas.alpha_composite(layer)


def compose_yt_cover(
    background: bytes,
    *,
    line1: str,
    line2: str,
    date_text: str,
    original_audio: bool = False,
    ai_translation: bool = False,
    ai_note: bool = False,
    draw_titles: bool = True,
) -> bytes:
    """合成 YT 國內外新聞直播封面（2026-09-06 依頻道實際版面）。

    draw_titles=False（標題由 AI 生成模式）：background 已經是模型畫好含標題與底帶的
    整張圖，這裡只貼固定元素（LIVE 章／日期／原音呈現／AI即時翻譯／藍標籤／AI示意圖）。

    background 是**無文字**底圖（使用者附圖或 AI 生成），任意尺寸，這裡等比例
    裁滿 1920×1080。line1／line2 是已分好的兩行標題（分段邏輯在 editor_formats），
    original_audio＝LIVE 章上方「原音呈現」、ai_translation＝日期下方「AI即時翻譯」，
    兩者獨立可並存；ai_note=True 時右側加「AI示意圖」（AI 生的底圖一律標，附圖不標）。
    """
    line1, line2 = (line1 or "").strip(), (line2 or "").strip()
    if not line1 or not line2:
        raise ComposeError("YT 直播封面需要兩行標題，缺一不可")
    if not date_text.strip():
        raise ComposeError("YT 直播封面需要日期")

    canvas = _cover_panel(background, YT_CANVAS).convert("RGBA")
    width, height = YT_CANVAS
    margin = round(width * YT_MARGIN_RATIO)

    # ---- 底帶先鋪，章與標籤壓在上面（AI 標題模式：底帶與標題都是模型畫的）----
    if draw_titles:
        _draw_title_band(canvas)
    _draw_top_line(canvas)
    _draw_logo_tab(canvas)
    draw = ImageDraw.Draw(canvas)

    # ---- 左上：（原音呈現）＋ LIVE 章 ＋ 日期條（＋AI即時翻譯）----
    top = round(height * (YT_TOP_WITH_LABEL_RATIO if original_audio else YT_TOP_RATIO))
    if original_audio:
        label_font = _font(round(height * YT_ORIGINAL_AUDIO_SIZE_RATIO))
        _draw_text(
            draw, (margin + round(width * 0.008), round(height * YT_ORIGINAL_AUDIO_BASELINE_RATIO)),
            YT_ORIGINAL_AUDIO_LABEL, label_font, fill=YT_ORIGINAL_AUDIO_FILL,
            stroke=YT_ORIGINAL_AUDIO_STROKE, stroke_width=max(4, round(height * 0.009)), anchor="ls",
        )
    badge_w = round(width * YT_BADGE_WIDTH_RATIO)
    badge_h = _paste_live_badge(canvas, (margin, top), badge_w)
    tab_w = round(width * YT_DATE_TAB_WIDTH_RATIO)
    tab_h = round(height * YT_DATE_TAB_HEIGHT_RATIO)
    tab_x0 = margin + (badge_w - tab_w) // 2
    tab_y0 = top + badge_h - 4          # 微微塞進章底，看起來像同一個物件
    tab_box = (tab_x0, tab_y0, tab_x0 + tab_w, tab_y0 + tab_h)
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (tab_box[0] + 3, tab_box[1] + 5, tab_box[2] + 3, tab_box[3] + 5), radius=14, fill=(0, 0, 0, 110)
    )
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        tab_box, radius=14, fill=YT_DATE_FILL,
        outline=YT_DATE_BORDER, width=max(2, round(height * YT_DATE_BORDER_RATIO)),
    )
    date_font = _fit_font(date_text, tab_w - 28, round(tab_h * 0.72), round(tab_h * 0.4))
    _draw_text(
        draw, ((tab_box[0] + tab_box[2]) // 2, (tab_box[1] + tab_box[3]) // 2 + 2),
        date_text, date_font, fill=YT_DATE_TEXT, stroke_width=0, anchor="mm",
    )
    if ai_translation:
        small = _font(round(height * YT_AI_TRANSLATION_SIZE_RATIO))
        _draw_text(
            draw, (tab_box[0] + 6, tab_box[3] + round(height * YT_AI_TRANSLATION_GAP_RATIO)),
            YT_AI_TRANSLATION_LABEL, small, stroke=YT_TITLE_STROKE, stroke_width=4, anchor="la",
        )

    # ---- 右側：AI 示意圖小標（只有 AI 底圖才有）----
    if ai_note:
        _draw_ai_note(canvas, round(height * YT_AI_NOTE_TOP_RATIO))
        draw = ImageDraw.Draw(canvas)

    # ---- 底部：兩行標題置中（白／黃、黑描邊）----
    max_w = width - margin * 2
    start = round(height * YT_TITLE_SIZE_RATIO)
    smallest = round(height * YT_TITLE_MIN_SIZE_RATIO)
    for text, fill, baseline_ratio in (
        (line1, YT_LINE1_FILL, YT_LINE1_BASELINE_RATIO),
        (line2, YT_LINE2_FILL, YT_LINE2_BASELINE_RATIO),
    ) if draw_titles else ():
        font = _fit_font(text, max_w, start, smallest)
        stroke = max(4, round(font.size * YT_TITLE_STROKE_RATIO))
        _draw_text(
            draw, (width // 2, round(height * baseline_ratio)), text, font,
            fill=fill, stroke=YT_TITLE_STROKE, stroke_width=stroke, anchor="ms",
        )

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


# ---- YT 整點直播（2026-09-06，範例：整點直播 YT 截圖 20:00）----
# 跟國內外新聞直播同一套底圖流程，只有版面不同：Logo 在左上（小）、LIVE 章在右上、
# 章下可掛整點時間（選填）、日期是紅底白字貼在第一行標題正上方、沒有副標。
# 比例量自截圖去掉 YT 介面後的縮圖區（約 415×220）。
YT_HOURLY_LOGO_WIDTH_RATIO = 0.118      # Logo 寬（48/415）
YT_HOURLY_LOGO_TOP_RATIO = 0.064
YT_HOURLY_BADGE_WIDTH_RATIO = 0.25      # LIVE 章寬（104/415）
YT_HOURLY_BADGE_TOP_RATIO = 0.024
YT_HOURLY_TIME_BAND_HEIGHT_RATIO = 0.095  # 章下時間帶高（21/220）
YT_HOURLY_TIME_BAND_FILL = (255, 255, 255)   # 頻道實際：白底紅字
YT_HOURLY_TIME_BAND_TEXT = (200, 20, 30)
YT_HOURLY_DATE_TAB_WIDTH_RATIO = 0.30   # 日期紅條寬（125/415）
YT_HOURLY_DATE_TAB_HEIGHT_RATIO = 0.095
YT_HOURLY_DATE_TOP_RATIO = 0.52         # 日期紅條上緣（114/220）
YT_HOURLY_DATE_FILL = (214, 22, 32)
YT_HOURLY_DATE_TEXT = (255, 255, 255)
YT_HOURLY_LINE1_BASELINE_RATIO = 0.80
YT_HOURLY_LINE2_BASELINE_RATIO = 0.965
YT_HOURLY_TITLE_SIZE_RATIO = 0.15       # 字高 32/220
YT_HOURLY_AI_NOTE_TOP_RATIO = 0.34      # LIVE 章（含時間帶）之下的右側空位


def compose_yt_hourly_cover(
    background: bytes,
    *,
    line1: str,
    line2: str,
    date_text: str,
    time_text: str = "",
    ai_note: bool = False,
    draw_titles: bool = True,
) -> bytes:
    """合成 YT 整點直播封面。time_text（如 20:00）選填，有填才在 LIVE 章下掛時間帶。

    draw_titles=False：標題已由模型畫在 background 上，這裡只貼固定元素。
    """
    line1, line2 = (line1 or "").strip(), (line2 or "").strip()
    if not line1 or not line2:
        raise ComposeError("YT 整點直播封面需要兩行標題，缺一不可")
    if not date_text.strip():
        raise ComposeError("YT 整點直播封面需要日期")
    time_text = (time_text or "").strip()

    canvas = _cover_panel(background, YT_CANVAS).convert("RGBA")
    width, height = YT_CANVAS
    margin = round(width * YT_MARGIN_RATIO)

    # ---- 左上：小 Logo ----
    _paste_logo(
        canvas, (margin, round(height * YT_HOURLY_LOGO_TOP_RATIO)), round(width * YT_HOURLY_LOGO_WIDTH_RATIO)
    )

    # ---- 右上：LIVE 章（＋整點時間帶）----
    badge_w = round(width * YT_HOURLY_BADGE_WIDTH_RATIO)
    badge_x0 = width - margin - badge_w
    badge_top = round(height * YT_HOURLY_BADGE_TOP_RATIO)
    badge_h = _paste_live_badge(canvas, (badge_x0, badge_top), badge_w)
    block_bottom = badge_top + badge_h
    if time_text:
        band_h = round(height * YT_HOURLY_TIME_BAND_HEIGHT_RATIO)
        band_y0 = block_bottom - 6          # 塞進章底一點，像同一個物件
        inset = round(badge_w * 0.04)       # 章本身有圓角留白，時間帶略窄才對得齊
        band = (badge_x0 + inset, band_y0, badge_x0 + badge_w - inset, band_y0 + band_h)
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle(band, radius=12, fill=YT_HOURLY_TIME_BAND_FILL)
        canvas.alpha_composite(layer)
        draw = ImageDraw.Draw(canvas)
        time_font = _fit_font(time_text, band[2] - band[0] - 24, round(band_h * 0.8), round(band_h * 0.4))
        _draw_text(
            draw, ((band[0] + band[2]) // 2, (band[1] + band[3]) // 2 + 2),
            time_text, time_font, fill=YT_HOURLY_TIME_BAND_TEXT, stroke_width=0, anchor="mm",
        )
        block_bottom = band[3]

    # ---- 右側：AI 示意圖小標（只有 AI 底圖才有）----
    draw = ImageDraw.Draw(canvas)
    if ai_note:
        _draw_ai_note(canvas, max(round(height * YT_HOURLY_AI_NOTE_TOP_RATIO), block_bottom + 16))
        draw = ImageDraw.Draw(canvas)

    # ---- 左中：紅底白字日期，貼在第一行標題正上方 ----
    tab_w = round(width * YT_HOURLY_DATE_TAB_WIDTH_RATIO)
    tab_h = round(height * YT_HOURLY_DATE_TAB_HEIGHT_RATIO)
    tab_y0 = round(height * YT_HOURLY_DATE_TOP_RATIO)
    tab_box = (margin, tab_y0, margin + tab_w, tab_y0 + tab_h)
    draw.rounded_rectangle(tab_box, radius=10, fill=YT_HOURLY_DATE_FILL)
    date_font = _fit_font(date_text, tab_w - 28, round(tab_h * 0.78), round(tab_h * 0.4))
    _draw_text(
        draw, ((tab_box[0] + tab_box[2]) // 2, (tab_box[1] + tab_box[3]) // 2 + 2),
        date_text, date_font, fill=YT_HOURLY_DATE_TEXT, stroke_width=0, anchor="mm",
    )

    # ---- 底部：兩行標題（白／黃、黑描邊），靠左貼邊 ----
    max_w = width - margin * 2
    start = round(height * YT_HOURLY_TITLE_SIZE_RATIO)
    smallest = round(height * YT_TITLE_MIN_SIZE_RATIO)
    for text, fill, baseline_ratio in (
        (line1, YT_LINE1_FILL, YT_HOURLY_LINE1_BASELINE_RATIO),
        (line2, YT_LINE2_FILL, YT_HOURLY_LINE2_BASELINE_RATIO),
    ) if draw_titles else ():
        font = _fit_font(text, max_w, start, smallest)
        stroke = max(4, round(font.size * YT_TITLE_STROKE_RATIO))
        _draw_text(
            draw, (margin, round(height * baseline_ratio)), text, font,
            fill=fill, stroke=YT_TITLE_STROKE, stroke_width=stroke, anchor="ls",
        )

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def crop_background_16x9(image_bytes: bytes) -> bytes:
    """把使用者附的原圖（任意比例）裁成 16:9 的無文字底圖，回 PNG。

    給「有 asis 附圖就不打生圖模型」那條路用：附圖本身就是底圖，只需要裁滿版面。
    """
    panel = _cover_panel(image_bytes, YT_CANVAS)
    buffer = io.BytesIO()
    panel.save(buffer, format="PNG")
    return buffer.getvalue()
