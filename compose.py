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

import contextvars
import functools
import io
import math
import pathlib
import random
import re
import unicodedata

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import safe_area_spec

BRAND_DIR = pathlib.Path(__file__).resolve().parent / "static" / "brand"
TVBS_LOGO_WHITE = BRAND_DIR / "tvbs-logo-white.png"
# TVBS＋NEWS 兩層版（2026-09-11 從實際播出畫面摳出）。只有 live24 用：那個版型的
# Logo 在右上、跟頻道實際播出一致，其他版型維持單層版不動。
TVBS_LOGO_NEWS_WHITE = BRAND_DIR / "tvbs-logo-news-white.png"
# 2026-09-07：節目／單元標籤改貼固定模板（gpt-image-2 依型錄原版重繪、透明底），
# 程式畫的圓角矩形＋字型版本被使用者裁定不好看。模板只縮放不變形，缺檔直接報錯。
TEN_SHOW_TAG = BRAND_DIR / "ten-show-tag.png"  # 2026-09-07 換成正版樣式：藍色斜切、金「十」＋白字、NEWS NIGHT
HOT_SEARCH_TAG = BRAND_DIR / "hot-search-tag.png"  # 「今日｜熱搜🔍」紅色三格標籤
TEN_BOTTOM_LINE = BRAND_DIR / "ten-bottom-line.png"  # 十點封面底部：深藍帶＋發光直線（依 0901／0902 原版）
# 2026-09-08 使用者裁決：「精華」改成紅色刷筆底＋白字的橫式標籤，貼在標頭帶中段。
# 舊的圓章檔保留不刪（0819 原版樣式，之後要對照或還原時還在），但已經沒有程式碼引用它。
TEN_HIGHLIGHT_TAG = BRAND_DIR / "ten-highlight-tag.png"      # 精華標籤：紅色刷筆底＋白字「精華」，左右有刷痕
TEN_HIGHLIGHT_STAMP = BRAND_DIR / "ten-highlight-stamp.png"  # 舊版精華圓章（2026-09-08 起停用，檔案保留）

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
# 整點時間帶（XX:XX）專用字型（2026-09-13 使用者裁決：Times New Roman）。
# 直接包 Windows 的 timesbd.ttf 進 repo——Cloud Run 是 Linux，系統沒有這個字型，
# 不包進來正式站永遠看不到效果。Monotype 再散布的授權疑慮已告知使用者，由其裁決。
# 不走 discover_font() 那條 CJK 退路鏈：那條是「找得到什麼中文粗體就用什麼」，
# 時間帶只有數字與冒號，要的是釘死這一支。
TIME_FONT_PATH = FONT_DIR / "timesbd.ttf"
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


# ---- 程式壓的日期／時間一律粗體（2026-09-13 使用者：「現行都偏細」）----
#
# 字型已經是台北黑體 Bold（見 FONT_CANDIDATES_BUNDLED），沒有更粗的字重可換，
# 所以靠「同色描邊」把字幹撐開——Pillow 沒有合成粗體，這是唯一做得到的方式，
# 標題那條 _draw_yt_title_line 早就在用同一招。
#
# 描邊會把字整體撐寬 2×stroke。日期紅條／時間白帶的字級是 _fit_font 量出來剛好
# 塞得下的，直接加描邊就會爆框，所以量字寬時必須把描邊一起算進去（_fit_font_bold）。
#
# 使用者調了三輪，最後兩邊都落在 0.022：
#   第一版一律 0.045 →「又太粗了，取中間值」
#   折半後 →「十點不一樣新的粗度可以，是其他的要取中間值」（於是拆成兩個字重）
#   看到 YT 的 0.022 →「0.022 中間值很 OK，十點不一樣的也改改看」→ 十點也收到 0.022
# 1920×1080 的整點日期是 80 級字，描邊從 4px 收到 2px。
#
# 兩個常數即使同值也**不合併**：它們是兩次獨立的裁決，合成一個之後下次調其中一邊
# 就會靜默改掉另一邊。要各自回頭也只是改這裡的一個數字。
BOLD_STROKE_RATIO = 0.022        # 十點不一樣（第三輪跟進 YT）
YT_BOLD_STROKE_RATIO = 0.022     # YT 三處（使用者：取中間值，很 OK）


def _bold_stroke(font: ImageFont.FreeTypeFont, ratio: float = BOLD_STROKE_RATIO) -> int:
    """假粗體用的同色描邊寬（依字級等比例，小字才不會被糊掉）。"""
    return max(1, round(font.size * ratio))


def _time_font(size: int) -> ImageFont.FreeTypeFont:
    """整點時間帶的 Times New Roman Bold（見 TIME_FONT_PATH）。找不到就報錯，不退回黑體——
    退回會靜靜畫成另一個字型，使用者驗收時看不出是字型檔沒進 image。"""
    if not TIME_FONT_PATH.exists():
        raise ComposeError(f"找不到時間帶字型：{TIME_FONT_PATH}")
    return ImageFont.truetype(str(TIME_FONT_PATH), size)


def _fit_font_bold(
    text: str, max_width: int, start_size: int, min_size: int,
    *, ratio: float = BOLD_STROKE_RATIO, loader=None,
) -> ImageFont.FreeTypeFont:
    """同 _fit_font，但把假粗體描邊撐出來的寬度一起算進去。

    ratio 必須跟等一下實際畫的時候一致，否則量的是 A 字重、畫的是 B 字重，白算。
    loader＝哪一支字型載入器（預設 _font 的中文粗體；時間帶傳 _time_font）。
    """
    load = loader or _font
    size = start_size
    while size > min_size:
        font = load(size)
        if font.getbbox(text)[2] + 2 * _bold_stroke(font, ratio) <= max_width:
            return font
        size -= 2
    return load(min_size)


def _ink_centre_shift(font: ImageFont.FreeTypeFont, text: str) -> int:
    """anchor 的 'm'（垂直置中）要補多少 y，才是把**墨跡**置中。

    Pillow 的 'm' 是照字型的 ascent／descent 置中，不是照實際墨跡。日期字串的數字
    頂不到 ascent、而斜線又伸到基線以下，墨跡因此整片偏低——1920×1080 的整點日期
    紅條實測上緣留 20px、下緣只留 4px。原本勉強看不出來，加了假粗體之後字幹往下
    多撐 4px，直接貼到紅條下緣（2026-09-13 量到 20 個像素壓在邊線上）。
    中文字填滿度量框，這個差值是 0，所以只有數字牌會被挪動。

    所以這裡按墨跡置中；粗體是對稱長出來的，不影響這個差值。
    """
    x0, ink_top, x1, ink_bottom = font.getbbox(text)
    ascent, descent = font.getmetrics()
    return round((ascent + descent) / 2 - (ink_top + ink_bottom) / 2)


def _draw_bold_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    fill: tuple[int, int, int],
    anchor: str = "la",
    outline: tuple[int, int, int] | None = None,
    outline_width: int = 0,
    ratio: float = BOLD_STROKE_RATIO,
) -> None:
    """把程式壓的日期／時間畫成粗體。

    要外框時畫兩趟：第一趟用「外框寬＋假粗體寬」畫出外框，第二趟把粗體字蓋上去。
    一趟畫不出來——Pillow 一次只吃一個 stroke_fill，而這裡外框與字幹是兩個顏色。

    ratio 見 BOLD_STROKE_RATIO／YT_BOLD_STROKE_RATIO：十點與 YT 是兩個字重。
    """
    bold = _bold_stroke(font, ratio)
    if anchor[1:2] == "m":
        xy = (xy[0], xy[1] + _ink_centre_shift(font, text))
    if outline is not None and outline_width:
        _draw_text(
            draw, xy, text, font, fill=fill, stroke=outline,
            stroke_width=outline_width + bold, anchor=anchor,
        )
    _draw_text(draw, xy, text, font, fill=fill, stroke=fill, stroke_width=bold, anchor=anchor)


def _paste_logo(canvas: Image.Image, box: tuple[int, int], width: int) -> None:
    """把白色 TVBS Logo 貼在 box（左上角座標），等比例縮到 width。"""
    if not TVBS_LOGO_WHITE.exists():
        raise ComposeError(f"找不到 Logo 檔：{TVBS_LOGO_WHITE}")
    with Image.open(TVBS_LOGO_WHITE) as logo_file:
        logo = logo_file.convert("RGBA")
        height = round(logo.height * width / logo.width)
        logo = logo.resize((width, height), Image.LANCZOS)
        canvas.paste(logo, box, logo)


def _paste_template(canvas: Image.Image, path: pathlib.Path, xy: tuple[int, int], height: int) -> int:
    """把透明底模板等比縮到指定高度貼上，回傳貼上後的寬。"""
    if not path.exists():
        raise ComposeError(f"找不到模板：{path}")
    with Image.open(path) as tpl:
        tpl = tpl.convert("RGBA")
        width = max(1, round(tpl.width * height / tpl.height))
        tpl = tpl.resize((width, height), Image.LANCZOS)
        canvas.alpha_composite(tpl, xy)
    return width


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


def _scaled_pixel(value: int, canvas_height: int) -> int:
    """Scale a legacy pixel constant by canvas height and round to nearest.

    Python's ``round`` rule is explicit here: nearest integer, ties to even.
    At the 1920x1080 base canvas the scale is exactly 1.0.
    """
    scale = canvas_height / safe_area_spec.BASE_CANVAS[1]
    return round(value * scale)


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
    inset = _scaled_pixel(HOLE_INSET, canvas[1])
    # 寬度對齊 16 的倍數，高度才會是整數且長寬比**剛好** 16:9。
    # 四捨五入出來的 795×447 是 1.7785，後製把影片放進去會有半像素級的黑邊，
    # 這個框的整個存在意義就是給影片對位，不能將就。
    width = round((x1 - x0) * HOLE_WIDTH_RATIO) // 16 * 16
    height = width * 9 // 16

    band_top = y0 + inset
    band_bottom = y1 - inset
    if height > band_bottom - band_top:
        # 安全區太矮塞不下，改由高度反推寬度，維持 16:9 不變形
        height = (band_bottom - band_top) // 9 * 9
        width = height * 16 // 9
    top = band_top + round((band_bottom - band_top - height) * HOLE_VERTICAL_ANCHOR)

    left = x0 + inset if side == "left" else x1 - inset - width
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
        inset = _scaled_pixel(HOLE_INSET, canvas[1])
        radius = _scaled_pixel(HOLE_RADIUS, canvas[1])
        outline_width = _scaled_pixel(HOLE_OUTLINE_WIDTH, canvas[1])
        draw = ImageDraw.Draw(image)
        rect = broadcast_hole_rect(canvas, side, profile)
        _rounded(
            draw, rect, radius, HOLE_FILL,
            outline=HOLE_OUTLINE, width=outline_width,
        )
        if watermark:
            x0, y0, x1, y1 = safe_area_spec.safe_rect(*canvas, profile)
            _draw_text(
                draw,
                (x1 - inset, y1 - inset),
                WATERMARK_TEXT,
                _font(_scaled_pixel(WATERMARK_SIZE, canvas[1])),
                fill=WATERMARK_FILL,
                stroke_width=_scaled_pixel(3, canvas[1]),
                anchor="rs",
            )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ============================================================
# 具名肖像／新聞圖的「示意圖」標籤，與 F43「畫面來源」標籤（B70／F43，2026-09-20）
# ============================================================
#
# B70 根因：這個標籤以前完全交給生圖模型自己畫進「variable」，沒有程式保證——
# 4 張具名肖像實拍裡 2 張不合格：一張整張找不到標籤，一張寫成錯字「示憊佪」
# （見 MASTER-列管清單.md B70）。使用者 2026-09-16 裁定採甲案：比照播出鏡面
# 的 `apply_broadcast_hole` 浮水印與十點封面的 `paste_cover_ai_note`——標籤
# 一律由程式後貼，模型只被告知「這個角落留空」，不再自己找位置、自己選字。
#
# F43 追加「畫面來源」欄位，與「示意圖」互斥：圖是 AI 生成或被 AI 改過畫面 →
# 標「示意圖」；圖是使用者原圖、且程式保證像素未被動過 → 標「畫面來源：○○○」
# （沿用 vstrip 已有的 `VSTRIP_SOURCE_PREFIX`／`vstrip_source_text`，同一套「使用者
# 只填來源名，前綴自動補」的體貼）。兩者的互斥判定在 main.resolve_image_disclaimer，
# 這裡只管貼哪一種、貼在哪。
#
# 位置改用 `safe_area_spec.safe_rect` 的四個角落之一，內縮量沿用播出鏡面浮水印
# 同一個 HOLE_INSET——保證落在安全框內（B70 動工前要釘的第②件事），不會被摳圖裁掉。
PORTRAIT_DISCLAIMER_TEXT = "示意圖"
PORTRAIT_DISCLAIMER_CORNERS = ("lower_right", "lower_left", "upper_right", "upper_left")
PORTRAIT_DISCLAIMER_SIZE_RATIO = 0.03        # 字級佔畫布高（同 _draw_cover_ai_note）
PORTRAIT_DISCLAIMER_HEIGHT_RATIO = 1.6       # 底板高＝字級 × 這個倍數
PORTRAIT_DISCLAIMER_PAD_RATIO = 0.012        # 底板左右各留的內距（佔畫布高）
PORTRAIT_DISCLAIMER_PLATE_FILL = (0, 0, 0, 130)


def _disclaimer_box(
    canvas: tuple[int, int], corner: str, profile: str, box_w: int, box_h: int
) -> tuple[int, int, int, int]:
    """算出標籤底板要貼的座標，釘在安全區四個角落之一，內縮 HOLE_INSET。"""
    if corner not in PORTRAIT_DISCLAIMER_CORNERS:
        raise ComposeError(
            f"未知的標籤角落：{corner!r}（可用：{PORTRAIT_DISCLAIMER_CORNERS}）"
        )
    x0, y0, x1, y1 = safe_area_spec.safe_rect(*canvas, profile)
    inset = _scaled_pixel(HOLE_INSET, canvas[1])
    if corner.endswith("left"):
        left, right = x0 + inset, x0 + inset + box_w
    else:
        right, left = x1 - inset, x1 - inset - box_w
    if corner.startswith("upper"):
        top, bottom = y0 + inset, y0 + inset + box_h
    else:
        bottom, top = y1 - inset, y1 - inset - box_h
    return left, top, right, bottom


def paste_disclaimer_note(
    image_bytes: bytes,
    *,
    kind: str,
    source_text: str = "",
    corner: str = "lower_right",
    canvas: tuple[int, int] = safe_area_spec.BASE_CANVAS,
    profile: str = safe_area_spec.REPORTER_PROFILE,
) -> bytes:
    """程式端壓「示意圖」或「畫面來源：○○○」標籤（B70 甲案／F43）。

    kind="ai"     → 固定文字 PORTRAIT_DISCLAIMER_TEXT（「示意圖」）。
    kind="source" → **逐字**貼 source_text，不補任何前綴。
    兩者互斥，呼叫端負責只傳其中一種——見 main.resolve_image_disclaimer，這裡不
    重新判斷「該不該標」，只管「怎麼貼」。

    B90（2026-09-22 使用者裁決）：這條路以前套 `vstrip_source_text`，自動補上
    「畫面來源：」。使用者原話——「預設不要任何文字，讓使用者根據需要填寫，因為
    也可能是資料來源，也可能是兩者都要寫」。自動補前綴會讓「資料來源：中央社」
    變成「畫面來源：資料來源：中央社」，兩者都要寫更是直接做不到，所以這裡改成
    逐字照貼。⚠ 只改這一條：直標／十點／YT 那些呼叫端仍套
    `vstrip_source_text`，因為那邊是 AI 判出**光禿禿的來源名**（「美聯社」），
    前綴本來就該由程式補。

    視覺沿用 `_draw_cover_ai_note` 那一套：半透明黑底＋白字，高度以傳入的畫布為準
    （這裡的呼叫端可能是任意 provider 尺寸，不是固定的 COVER_CANVAS）。
    """
    if kind not in ("ai", "source"):
        raise ComposeError(f"未知的標籤種類：{kind!r}（可用：'ai'／'source'）")
    text = PORTRAIT_DISCLAIMER_TEXT if kind == "ai" else (source_text or "").strip()
    if not text:
        raise ComposeError("來源標籤沒有文字可貼（source_text 是空的）")

    with Image.open(io.BytesIO(image_bytes)) as opened:
        canvas_image = opened.convert("RGBA")
    if canvas_image.size != canvas:
        # 傳入的畫布只是預設值；實際以真正拿到的圖為準，理由同 apply_broadcast_hole。
        canvas = canvas_image.size
    height = canvas[1]
    font = _font(round(height * PORTRAIT_DISCLAIMER_SIZE_RATIO))
    pad = round(height * PORTRAIT_DISCLAIMER_PAD_RATIO)
    text_w = font.getbbox(text)[2]
    box_w = text_w + pad * 2
    box_h = round(height * PORTRAIT_DISCLAIMER_SIZE_RATIO * PORTRAIT_DISCLAIMER_HEIGHT_RATIO)
    x0, y0, x1, y1 = _disclaimer_box(canvas, corner, profile, box_w, box_h)

    plate = Image.new("RGBA", canvas_image.size, (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle(
        (x0, y0, x1, y1), radius=6, fill=PORTRAIT_DISCLAIMER_PLATE_FILL
    )
    canvas_image.alpha_composite(plate)
    _draw_text(
        ImageDraw.Draw(canvas_image), ((x0 + x1) // 2, (y0 + y1) // 2), text, font,
        stroke_width=0, anchor="mm",
    )

    buffer = io.BytesIO()
    canvas_image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


# ============================================================
# 版型 B：十點不一樣封面圖（左右兩張 AI 底圖＋程式畫的固定元素）
# ============================================================

COVER_CANVAS = (1920, 1080)
COVER_BG = (10, 24, 58)
COVER_BORDER = (24, 48, 104)

# 2026-09-06 改依 TVBS NEWS 頻道實際上線的十點不一樣封面重畫（型錄 catalog/15.png）：
# 兩張圖斜切鋪滿整個 16:9，上方只留一條很薄的深藍標頭帶（Logo、「十點不一樣」小標、
# 日期、ON AIR），標題壓在各自那格的下緣（白／黃／紅逐行變色），底部一道藍色波紋飾條。
# 舊版「標頭帶 208px＋兩圖並排＋圖下標題帶」已退場。
COVER_HEADER_RATIO = 0.105          # 標頭帶高（佔畫面高）
COVER_HEADER_FILL = (7, 18, 56)
COVER_HEADER_LINE = (40, 150, 245)  # 標頭帶底一條亮藍細線
COVER_HEADER_LINE_RATIO = 0.004
COVER_MARGIN = 26                    # 內容離左右畫框的距離
COVER_ONAIR_FILL = (206, 26, 32)
# 2026-09-07 使用者回報「字明顯太小」：起始字級 0.085 → 0.11、版位 0.90。
#
# 顏色一律**依行序**：第 1 行白、第 2 行黃、第 3 行紅（`COVER_TITLE_LINE_COLOURS`）。
# 2026-09-08 一度改成依段落（空格分段），同日使用者看了樣張後改回依行——要的是
# 「白黃紅三行」的固定視覺，兩段標題被拆成 3 行時第 3 行也要紅。段索引仍跟著行走
# （`cover_title_line_pairs` 的第二個元素），但**只記錄出處，不決定顏色**。
#
# 2026-09-08 使用者看了正式站成品後再裁決（雙切）：**兩格同一字級**。逐行各自撐滿的做法
# 讓「左格三行 6 字都最大、右格第三行 11 字被壓小」變成兩邊字大小差一截，看起來像兩張圖
# 拼的。改成：每格先各自算出逐行都塞得進的字級，再取兩格的全域最小值當所有行的字級
# （所以 COVER_TITLE_LINE_SIZE_SPREAD 退場）。配套是把行拆得夠短——只要一行超過
# COVER_TITLE_FILL_MIN_CHARS 就再拆，但總行數上限 3（白／黃／紅，使用者裁決不能四行）
# ——不然共同字級會被最長那行拖垮。
# 滿版是單一標題、沒有另一格可比，維持逐行各自撐滿。
# 2026-09-08 晚使用者：雙切合成版「字級還是不夠大」。起始字級 0.11→0.135、可用寬 0.90→0.94；
# 配套是消化標題每段 4–7 字（見 editor_formats），一行 11 字的那種段會把共同字級拖到 0.07。
COVER_TITLE_SIZE_RATIO = 0.135       # 標題起始字級（佔畫面高）
COVER_TITLE_MIN_SIZE_RATIO = 0.045
COVER_TITLE_WIDTH_RATIO = 0.94       # 標題最寬佔該格寬的比例
COVER_TITLE_FILL_MIN_CHARS = 7       # 雙切：長度超過這個字數的行就再拆（拆到夠短，共同字級才大）
COVER_TITLE_TOP_CLEARANCE_RATIO = 0.01   # 標題最上一行的字頂與標頭帶之間留的空隙
COVER_TITLE_LINE_GAP = 1.06          # 行距（字級倍數）
COVER_TITLE_BOTTOM_RATIO = 0.085     # 最後一行字底離畫面底的距離
# 滿版（單一標題，2026-09-07 使用者裁決）：比照今日熱搜，標題橫跨整個畫面寬、置中，
# 字級起點放大；每行各自以整寬決定字級（最寬行決定，全部同字級）。
COVER_FULL_TITLE_SIZE_RATIO = 0.15    # 每行各自撐滿寬（比照今日熱搜逐行 fit），此為字級上限
COVER_FULL_TITLE_WIDTH_RATIO = 0.90
COVER_TITLE_STROKE_RATIO = 0.055
COVER_TITLE_BOLD_RATIO = 0.012       # 假粗體（2026-09-08 晚使用者「十點雙切字還可再粗一點點」），做法同 YT
# 逐行配色：第 1 行白、第 2 行黃、第 3 行紅（紅字用白描邊，其餘深色描邊）。
# 這張表同時是 editor_formats.COVER_AI_PROMPT_TEMPLATE 對模型描述的配色規則，改要一起改。
# 2026-09-11 起這個耦合**只剩創意 0 級**：1 級起配色解放（使用者：「不必綁住一定要白黃紅
# 順序，也不用綁到同一句同一色」），main._lines_block 不再輸出 (white)／(yellow)／(red)，
# 改由 editor_formats.cover_line_annotation 依那一行的內容標。1–4 級的圖跟這張表對不起來
# 是刻意的，別當成 bug 去「修」。
COVER_TITLE_LINE_COLOURS = ((255, 255, 255), (250, 215, 0), (228, 28, 40))
COVER_TITLE_STROKE_DARK = (8, 8, 8)
COVER_TITLE_STROKE_LIGHT = (255, 255, 255)
COVER_SHADE_TOP_RATIO = 0.42         # 每格下半部壓暗漸層起點
COVER_SHADE_ALPHA = 190

COVER_SHOW_NAME = "十點不一樣"
COVER_AI_NOTE = "AI示意圖"
# 2026-09-07：精華不再是標頭紅標；標頭照樣 ON AIR，另貼一枚「精華」標籤。
# 2026-09-08 使用者裁決：從 0819 原版的深藍圓章改成**紅色刷筆底＋白字的橫式標籤**
# （模板 TEN_HIGHLIGHT_TAG），位置從畫面中下方（會壓到標題）改到標頭帶中段。
COVER_BADGES = {
    "on_air": ("ON AIR", (206, 26, 32)),
    "highlight": ("ON AIR", (206, 26, 32)),
}
COVER_DEFAULT_BADGE = "on_air"
# 幾何比照 paste_cover_logo／節目標籤：以標頭帶高為準，佔帶高 80%，水平與垂直都置中。
# 標頭帶只有左半（Logo＋節目標籤）與右端（日期＋ON AIR）有東西，中段本來就空。
COVER_STAMP_BAND_RATIO = 0.80        # 精華標籤高度佔標頭帶高的比例
COVER_MAX_TITLE_LINES = 3            # 滿版
# 2026-09-08 第二輪裁決：雙切一度放寬到 4 行，使用者看了樣張後改回 3 行——
# 「白黃紅三行」是固定的視覺，第四行沒有顏色可配。拆行規則不變，只是到 3 行就停。
COVER_MAX_TITLE_LINES_SPLIT = 3      # 雙切


# 純 prompt 版的後製：把正版白色 Logo＋「十點不一樣」節目標籤貼進模型留空的標頭帶左半。
# 位置與大小用畫布比例算，模型回什麼解析度都對得上。
# 2026-09-07：原本 Logo 寬佔 18.5%（量自舊範例），在一成高的標頭帶裡整個爆出來壓到照片；
# 改成跟合成版同一套幾何——以標頭帶高為準，Logo 佔帶高 70%、標籤佔 80%，垂直置中。
# 這一個數字同時是三件事，故意只留一個：prompt 要求模型畫多高、量不到時的退路、
# 以及模型畫太薄時程式補到的目標。分成兩個數字遲早會各走各的。
# 2026-09-09（第二輪）使用者改裁：「應該要藍框區域稍微變大一點點，你現在變成把 LOGO
# 那些縮太小才是問題。」——上一版量到帶薄（實測 58/720 = 8.1%）就把 Logo 縮小去遷就，
# 方向反了。改成**把帶補厚**而不是把 Logo 縮小，帶高直接借合成版那一個：
# 合成版的帶就是 COVER_HEADER_RATIO，Logo 佔帶高 70%、標籤 80%、垂直置中，
# 那是使用者早就看習慣的比例；AI 版另外訂一個數字只會讓兩版長得不一樣。
COVER_AI_HEADER_RATIO = COVER_HEADER_RATIO
COVER_AI_LEFT_RATIO = 0.015
COVER_AI_HEADER_MIN_RATIO = 0.055     # 量到的帶高低於這個就是量錯（誤把帶內的字當邊界）
COVER_AI_HEADER_MAX_RATIO = 0.145
COVER_AI_HEADER_DELTA = 90            # 判定「離開標頭帶」的 RGB 曼哈頓距離
COVER_AI_HEADER_GLOW_MAX_RATIO = 0.030   # 帶底輝光往上最多這麼厚
COVER_AI_HEADER_RULE_MAX_RATIO = 0.012   # 帶底那條亮藍細線往下最多這麼厚
COVER_AI_HEADER_FLAT_DELTA = 6           # 與帶身顏色差這麼多以內＝還算帶身（不是輝光）


def _ai_band_columns(width: int) -> range:
    """取樣用的直行：畫面中段。左邊是 Logo／節目標籤、右邊是日期／紅標，中間本來就空。"""
    return range(round(width * 0.40), round(width * 0.60), max(1, width // 64))


def _is_band_edge(pixel) -> bool:
    """帶底的輝光與亮藍細線：藍色壓倒性、而且紅幾乎是 0（實測 r ≤ 13）。

    只寫「藍比紅多、藍夠亮」會把天空也算進去（淡藍天 135,206,235 就過關），
    掃描一路衝進照片裡，帶底就量得太深——最後又變成標籤壓在亮線上，繞回原本的災情。
    """
    r, g, b = pixel[:3]
    return r < 40 and b > r + 40 and b > 80


def _probe_ai_header_band(canvas: Image.Image) -> tuple[int, int] | None:
    """量模型畫的標頭帶：回傳 (帶身結束的那一列, 含底部輝光與亮線在內的帶底)。

    量不到（帶跟照片同色、或量到離譜的值）回 None——這時候**不准動手畫**：
    連帶在哪裡都不知道，往下補一塊深藍很可能蓋掉模型畫的東西。
    """
    width, height = canvas.size
    limit = round(height * COVER_AI_HEADER_MAX_RATIO)
    rgb = canvas.convert("RGB")
    px = rgb.load()
    tops: list[int] = []
    for x in _ai_band_columns(width):
        base = px[x, 0]
        for y in range(1, limit + 1):
            if sum(abs(px[x, y][i] - base[i]) for i in range(3)) > COVER_AI_HEADER_DELTA:
                tops.append(y)
                break
    if not tops:
        return None
    tops.sort()
    top = tops[len(tops) // 2]
    if not (round(height * COVER_AI_HEADER_MIN_RATIO) <= top <= limit):
        return None

    edge_cap = round(height * COVER_AI_HEADER_RULE_MAX_RATIO)
    depths: list[int] = []
    for x in _ai_band_columns(width):
        depth = 0
        while depth < edge_cap and top + depth < height and _is_band_edge(px[x, top + depth]):
            depth += 1
        depths.append(depth)
    depths.sort()
    return top, top + depths[len(depths) // 2]


def measure_ai_header_band(canvas: Image.Image) -> int:
    """標頭帶（含底部亮線）到哪一列結束——後面要壓「AI示意圖」小標與精華圓章的都用這個。

    量不到就退回 prompt 要求的高度。注意這裡量的是**帶底**而不是帶身結束處，
    所以 `paste_cover_logo` 把帶補厚之後再量，拿到的就是補完的新帶底。
    """
    probe = _probe_ai_header_band(canvas)
    if probe is None:
        return round(canvas.size[1] * COVER_AI_HEADER_RATIO)
    return probe[1]


COVER_AI_HEADER_FILL_WINDOW = 41         # 填充列的水平中位濾波窗（要比字的筆畫寬得多）
COVER_AI_HEADER_FILL_CLAMP = 60          # 濾完仍離帶身主色這麼遠的直行＝寬色塊，改用主色


def _band_fill_row(canvas: Image.Image, top: int) -> Image.Image:
    """做一列拿來往下填的帶身：保留左右的細微漸層，但濾掉帶裡的字。

    取三列（避開單一列剛好穿過某個筆畫），逐行取中位數，再做一次水平中位濾波——
    日期與紅標的筆畫寬度遠小於濾波窗，會被整個吃掉；漸層是慢變化，濾波前後幾乎一樣。
    只把「明顯太亮」的換掉是不夠的：字邊的抗鋸齒像素比帶身還**暗**，
    一路拉下去就是一條深色直線（2026-09-09 第一版的實測災情）。
    """
    width = canvas.size[0]
    rgb = canvas.convert("RGB")
    px = rgb.load()
    rows = sorted({max(1, round(top * r)) for r in (0.33, 0.5, 0.67)})
    columns = [
        tuple(sorted(px[x, y][i] for y in rows)[len(rows) // 2] for i in range(3))
        for x in range(width)
    ]
    half = COVER_AI_HEADER_FILL_WINDOW // 2
    body = tuple(sorted(c[i] for c in columns)[width // 2] for i in range(3))
    out = Image.new("RGB", (width, 1))
    op = out.load()
    for x in range(width):
        window = columns[max(0, x - half):x + half + 1]
        here = tuple(sorted(c[i] for c in window)[len(window) // 2] for i in range(3))
        # 濾波窗整個落在紅標裡的時候，中位數就是紅的——寬色塊只能靠這一道擋。
        if sum(abs(here[i] - body[i]) for i in range(3)) > COVER_AI_HEADER_FILL_CLAMP:
            here = body
        op[x, 0] = here
    return out.convert("RGBA")


def ensure_ai_header_band(canvas: Image.Image) -> int:
    """把模型畫得太薄的標頭帶補到 COVER_AI_HEADER_RATIO，回傳補完後的帶底。

    做法是把帶底那組「輝光＋亮藍細線」整條原封不動往下搬，中間空出來的部分用帶身
    的一列填滿——不是把 Logo 縮小去遷就薄帶（那是 2026-09-09 第一版的錯誤方向）。
    照片被吃掉最上面那幾列，那正是「藍框變大一點點」的意思。
    """
    height = canvas.size[1]
    target = round(height * COVER_AI_HEADER_RATIO)
    probe = _probe_ai_header_band(canvas)
    if probe is None:
        return target
    top, bottom = probe
    if bottom >= target:
        return bottom

    rgb = canvas.convert("RGB")          # 要留住這個參照，px 是它的 buffer
    px = rgb.load()
    x_mid = round(canvas.size[0] * 0.5)
    body = px[x_mid, max(1, top // 2)]
    glow_cap = round(height * COVER_AI_HEADER_GLOW_MAX_RATIO)
    glow_top = top
    while (
        top - glow_top < glow_cap
        and glow_top > 1
        and sum(abs(px[x_mid, glow_top - 1][i] - body[i]) for i in range(3))
        > COVER_AI_HEADER_FLAT_DELTA
    ):
        glow_top -= 1

    edge = canvas.crop((0, glow_top, canvas.size[0], bottom))
    fill_to = target - edge.size[1]
    if fill_to > glow_top:
        canvas.paste(
            _band_fill_row(canvas, top).resize((canvas.size[0], fill_to - glow_top)),
            (0, glow_top),
        )
    canvas.paste(edge, (0, max(glow_top, fill_to)))
    return target


def paste_cover_header_right(
    canvas: Image.Image, band_h: int, date_text: str, badge: str
) -> None:
    """標頭帶右端的日期與 ON AIR 紅標，改由程式畫（2026-09-10）。

    為什麼搬過來：這兩樣本來寫在 prompt 裡讓模型畫，而 ensure_ai_header_band 會把
    模型畫得太薄的帶補厚——補法是「帶底那條邊往下搬、中間用帶身填滿」。填進去的那幾列
    正好蓋掉模型畫的日期與紅標的上半，被往下搬的邊又把下半重新貼出來，成品就是
    使用者看到的「日期與 ON AIR 被切斷、下面還留一層殘影」。

    根因不是補帶算錯，是**這兩樣東西本來就不該交給模型**：它們是固定素材，
    和 Logo、節目標籤同一類。畫在補帶之後，補多厚都不影響。

    幾何沿用合成版 _draw_cover_header 的那一套（同一個視覺，兩條路徑不該長不一樣）。
    """
    draw = ImageDraw.Draw(canvas)
    width = canvas.size[0]
    margin = round(width * COVER_AI_LEFT_RATIO)
    tag_h = max(1, round(band_h * 0.80))
    tag_y0 = (band_h - tag_h) // 2

    badge_text, badge_colour = COVER_BADGES[badge]
    badge_font = _font(round(band_h * 0.42))
    badge_w = badge_font.getbbox(badge_text)[2] + round(band_h * 0.9)
    badge_x1 = width - margin
    _rounded(draw, (badge_x1 - badge_w, tag_y0, badge_x1, tag_y0 + tag_h), 8, badge_colour)
    dot_r = max(1, round(tag_h * 0.14))
    dot_cx = badge_x1 - badge_w + round(band_h * 0.32)
    dot_cy = tag_y0 + tag_h // 2
    draw.ellipse(
        (dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r),
        fill=(255, 255, 255),
    )
    _draw_text(
        draw, (badge_x1 - round(band_h * 0.28), dot_cy), badge_text, badge_font,
        stroke_width=0, anchor="rm",
    )

    if date_text:
        # 黑色字框（2026-09-10 使用者裁決）：模型畫的藍帶厚度會飄，帶一薄，白色日期就
        # 落在照片上、亮背景下直接看不見。加一圈黑描邊後，落在帶上或落在照片上都讀得到——
        # 比「把帶補到剛好」穩，因為帶厚是模型決定的、我們控制不了。
        # 紅標不需要：它自己有紅底。Logo 與節目標籤是圖檔，本來就不受影響。
        date_font = _font(round(band_h * 0.40))
        _draw_bold_text(
            draw, (badge_x1 - badge_w - round(width * 0.02), dot_cy), date_text,
            date_font, fill=(255, 255, 255), outline=(0, 0, 0),
            outline_width=max(2, round(band_h * 0.05)), anchor="rm",
        )


def fit_cover_canvas(image_bytes: bytes) -> bytes:
    """把模型出的圖等比例放大裁滿十點定版尺寸；已經是定版尺寸就原樣回。

    2026-09-14 抓 bug 輪：原生 GPT 的 16:9 生成尺寸是 1280×720，十點 AI 模式以前照模型
    原尺寸出去（合成版與 YT 的 AI 標題都是 1920×1080）。只給十點 AI 路徑在貼 Logo 之前
    呼叫——paste_cover_logo 本身是多處共用的原始函式，量像素的測試都拿小圖打它。
    """
    with Image.open(io.BytesIO(image_bytes)) as opened:
        if opened.size == COVER_CANVAS:
            return image_bytes
    canvas = _cover_panel(image_bytes, COVER_CANVAS)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def paste_cover_header_band(image_bytes: bytes) -> bytes:
    """程式自己畫十點封面的深藍標頭帶（2026-09-21 使用者回報）。

    什麼時候需要：**「原圖放置」＋AI 標題**時，照片被程式硬保護，字帶以上一律還原
    成 base（`restore_photo_outside_title_band` 的硬邊界，透明圖層那條路則是整片
    列為保護區）。模型就算畫了標頭帶也一定會被還原掉，而 base 是使用者的原圖、
    本來就沒有帶——於是 `paste_cover_logo` 把 Logo、節目標籤、日期、ON AIR 直接貼
    在照片上，藍底整條不見。

    這是設計矛盾不是模型的錯：純 AI 版的帶一直都是模型畫的，改成「只有標題交給
    模型」之後就沒有人畫它了，所以要由程式補上。

    帶的幾何與合成版 `_draw_cover_header` 逐項相同（同一組 COVER_HEADER_* 常數），
    兩版長得一樣是刻意的——見 COVER_AI_HEADER_RATIO 上方那段。畫完之後
    `ensure_ai_header_band` 量得到這條帶（底部亮藍線就是它找的那個邊），不會再去
    搬動它。
    """
    with Image.open(io.BytesIO(image_bytes)) as opened:
        canvas = opened.convert("RGB")
    width, height = canvas.size
    band_h = round(height * COVER_AI_HEADER_RATIO)
    line_h = max(2, round(height * COVER_HEADER_LINE_RATIO))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, width, band_h), fill=COVER_HEADER_FILL)
    draw.rectangle((0, band_h - line_h, width, band_h), fill=COVER_HEADER_LINE)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def paste_cover_logo(
    image_bytes: bytes, date_text: str = "", badge: str = COVER_DEFAULT_BADGE
) -> bytes:
    """在 AI 畫好的封面標頭帶貼上正版白色 Logo、節目標籤模板、日期與 ON AIR 紅標。

    prompt 已明令模型不准畫任何電視台標誌／節目名／日期／紅標，整條標頭帶留白（見
    editor_formats.COVER_AI_PROMPT_TEMPLATE）。就算模型沒聽話畫了東西，
    貼上去也會蓋掉——與播出鏡面挖空框同一個原則：不靠模型自律。
    """
    with Image.open(io.BytesIO(image_bytes)) as opened:
        canvas = opened.convert("RGBA")
    width, height = canvas.size
    # 2026-09-09（第二輪）：帶太薄就把帶補厚（見 ensure_ai_header_band），
    # Logo 照補完的帶高算——第一版是反過來把 Logo 縮小去遷就薄帶，使用者退回。
    band_h = ensure_ai_header_band(canvas)
    logo_h = max(1, round(band_h * 0.70))
    with Image.open(TVBS_LOGO_WHITE) as logo_file:
        logo_w = max(1, round(logo_h * logo_file.width / logo_file.height))
    logo_x = round(width * COVER_AI_LEFT_RATIO)
    _paste_logo(canvas, (logo_x, (band_h - logo_h) // 2), logo_w)
    tag_h = max(1, round(band_h * 0.80))
    _paste_template(canvas, TEN_SHOW_TAG, (logo_x + logo_w + round(width * 0.02), (band_h - tag_h) // 2), tag_h)
    # 右端的日期與 ON AIR 也在補帶之後才畫，理由見 paste_cover_header_right。
    paste_cover_header_right(canvas, band_h, date_text, badge)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def paste_cover_ai_note(image_bytes: bytes, *, split: bool) -> bytes:
    """在純 AI 版封面壓上「AI示意圖」小標（2026-09-07）。

    為什麼改由程式壓：模板本來要模型自己畫這個小標，但只要使用者附了實景參考圖，
    `apply_user_references_to_image_request` 就會追加「Do NOT render any 示意圖 label」，
    位置在後、又是明文 OVERRIDE，模型會照做——標籤整個消失。合成版的標籤本來就是
    程式畫的，這裡改成同一套，標籤在不在就不再取決於模型聽不聽話。做法比照 YT
    ai-title：文字類固定元素一律後貼。

    split=True（雙切）左右格外側各一枚；False（滿版）只有左上一枚。位置與合成版
    `compose_ten_cover` 一致：標頭帶下方 2.5% 畫面高處。
    """
    with Image.open(io.BytesIO(image_bytes)) as opened:
        canvas = opened.convert("RGBA")
    width, height = canvas.size
    # AI 版的標頭帶高由模型畫多少決定，不是 prompt 說的一成（2026-09-09），所以量出來再往下讓
    note_y = measure_ai_header_band(canvas) + round(height * 0.025)
    margin = round(width * COVER_MARGIN / COVER_CANVAS[0])
    _draw_cover_ai_note(canvas, margin, note_y, align_right=False)
    if split:
        _draw_cover_ai_note(canvas, width - margin, note_y, align_right=True)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def paste_cover_highlight_stamp(image_bytes: bytes) -> bytes:
    """在純 AI 版封面貼上「精華」圓章（2026-09-07 使用者回報：AI 整張版選精華沒反應）。

    根因：合成版由 `compose_ten_cover` 在 `badge == "highlight"` 時貼圓章，AI 版只把
    `COVER_BADGES[badge][0]`（兩種標籤都是 "ON AIR"，標頭刻意維持 ON AIR）塞進 prompt，
    圓章從沒貼過。這裡重用 `_draw_cover_highlight_stamp`，位置與比例與合成版完全相同。
    """
    with Image.open(io.BytesIO(image_bytes)) as opened:
        canvas = opened.convert("RGBA")
    # 2026-09-09：帶高量出來再貼，理由同 paste_cover_logo
    _draw_cover_highlight_stamp(canvas, measure_ai_header_band(canvas))

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
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


def _shade_panel_bottom(canvas: Image.Image, box: tuple[int, int, int, int]) -> None:
    """把一格的下半部往下漸暗，標題才壓得住亮照片。box=(x0,y0,x1,y1)。"""
    x0, y0, x1, y1 = box
    h = y1 - y0
    top = round(h * COVER_SHADE_TOP_RATIO)
    shade = Image.new("RGBA", (x1 - x0, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(top, h):
        a = round(COVER_SHADE_ALPHA * ((y - top) / max(1, h - top)) ** 1.2)
        sd.line(((0, y), (x1 - x0, y)), fill=(0, 0, 0, a))
    canvas.alpha_composite(shade, (x0, y0))


def _draw_cover_bottom_line(canvas: Image.Image) -> None:
    """底部深藍飾帶＋一道發光直線：貼模板（TEN_BOTTOM_LINE），寬度撐滿畫面、等比縮放。

    2026-09-07 使用者裁決：波紋只在型錄 1 張出現，不是通用；查 YouTube 18 張原版，
    不帶警語的底部是「深藍帶＋直線光」（0901、0902），改依此用 gpt-image-2 生模板。
    """
    width, height = COVER_CANVAS
    if not TEN_BOTTOM_LINE.exists():
        raise ComposeError(f"找不到模板：{TEN_BOTTOM_LINE}")
    with Image.open(TEN_BOTTOM_LINE) as tpl:
        tpl = tpl.convert("RGBA")
        strip_h = max(1, round(tpl.height * width / tpl.width))
        tpl = tpl.resize((width, strip_h), Image.LANCZOS)
        canvas.alpha_composite(tpl, (0, height - strip_h))


def _draw_cover_highlight_stamp(canvas: Image.Image, band_h: int | None = None) -> None:
    """精華標籤：紅色刷筆模板，貼在標頭帶中段（水平置中、垂直置中於帶內）。

    2026-09-08 使用者兩次裁決：先是實測回報原本的深藍圓章跨在底部標題區上（TOP_RATIO 0.67）
    會壓到標題，接著把樣式整個換成紅色刷筆底＋白字的橫式標籤（TEN_HIGHLIGHT_TAG）。
    標頭帶只有左半與右端有東西，中段本來就空，兩邊都不打架。

    幾何以**傳進來的畫布**的尺寸為準，不是 COVER_CANVAS：純 AI 版直接貼在模型回來的
    原圖上，那張的解析度是模型決定的（2026-09-07 起 paste_cover_highlight_stamp 共用這支）。

    band_h：合成版的帶是程式自己畫的，帶多高一清二楚（None＝用 COVER_HEADER_RATIO）；
    AI 版的帶是模型畫的，實測只有 8%上下，照 10.5% 貼這枚標籤會跟 Logo 一樣戳出帶外
    （2026-09-09 使用者回報的就是 Logo 那一個），所以 AI 那條線要把量到的帶高傳進來。
    """
    width, height = canvas.size
    if band_h is None:
        band_h = round(height * COVER_HEADER_RATIO)
    # 垂直置中要扣掉帶底那條亮藍細線，才跟 Logo 與節目標籤同一條中線
    # （`_draw_cover_header` 兩者都是 (band_h - line_h - h) // 2）。
    line_h = max(2, round(height * COVER_HEADER_LINE_RATIO))
    tag_h = round(band_h * COVER_STAMP_BAND_RATIO)
    with Image.open(TEN_HIGHLIGHT_TAG) as tpl:
        tag_w = round(tpl.width * tag_h / tpl.height)
    _paste_template(canvas, TEN_HIGHLIGHT_TAG, ((width - tag_w) // 2, (band_h - line_h - tag_h) // 2), tag_h)


def _draw_cover_header(draw: ImageDraw.ImageDraw, canvas: Image.Image, date_text: str, badge: str) -> int:
    """薄標頭帶：Logo、「十點不一樣」小標、日期、ON AIR。回傳帶高。"""
    width, height = COVER_CANVAS
    band_h = round(height * COVER_HEADER_RATIO)
    draw.rectangle((0, 0, width, band_h), fill=COVER_HEADER_FILL)
    line_h = max(2, round(height * COVER_HEADER_LINE_RATIO))
    draw.rectangle((0, band_h - line_h, width, band_h), fill=COVER_HEADER_LINE)

    # Logo：帶高的 70%
    logo_h = round(band_h * 0.70)
    with Image.open(TVBS_LOGO_WHITE) as logo_file:
        ratio = logo_file.width / logo_file.height
    logo_w = round(logo_h * ratio)
    _paste_logo(canvas, (COVER_MARGIN, (band_h - line_h - logo_h) // 2), logo_w)

    # 「十點不一樣」標籤：貼模板（藍色斜切，見 TEN_SHOW_TAG），高度佔帶高 80%
    tag_x0 = COVER_MARGIN + logo_w + round(width * 0.02)
    tag_h = round(band_h * 0.80)
    tag_y0 = (band_h - line_h - tag_h) // 2
    _paste_template(canvas, TEN_SHOW_TAG, (tag_x0, tag_y0), tag_h)
    draw = ImageDraw.Draw(canvas)

    # ON AIR：靠右紅底白字（精華版標頭也是 ON AIR，圓章另貼）
    badge_text, badge_colour = COVER_BADGES[badge]
    badge_font = _font(round(band_h * 0.42))
    badge_w = badge_font.getbbox(badge_text)[2] + round(band_h * 0.9)
    badge_x1 = width - COVER_MARGIN
    _rounded(draw, (badge_x1 - badge_w, tag_y0, badge_x1, tag_y0 + tag_h), 8, badge_colour)
    dot_r = round(tag_h * 0.14)
    dot_cx = badge_x1 - badge_w + round(band_h * 0.32)
    draw.ellipse((dot_cx - dot_r, band_h // 2 - dot_r - line_h // 2, dot_cx + dot_r, band_h // 2 + dot_r - line_h // 2), fill=(255, 255, 255))
    _draw_text(draw, (badge_x1 - round(band_h * 0.28), tag_y0 + tag_h // 2), badge_text, badge_font, stroke_width=0, anchor="rm")

    # 日期：ON AIR 左側
    if date_text:
        date_font = _font(round(band_h * 0.40))
        _draw_bold_text(
            draw, (badge_x1 - badge_w - round(width * 0.02), tag_y0 + tag_h // 2),
            date_text, date_font, fill=(255, 255, 255), anchor="rm",
        )
    return band_h


def _draw_cover_ai_note(
    canvas: Image.Image, x_anchor: int, y0: int, align_right: bool, *, text: str = COVER_AI_NOTE
) -> None:
    """格內小標（半透明黑底白字），預設文字是「AI示意圖」。

    幾何一律以**傳進來的畫布**的高為準，不是 COVER_CANVAS：純 AI 版直接畫在模型
    回來的原圖上，那張的解析度是模型決定的（2026-09-07 起 paste_cover_ai_note 共用這支）。

    text 參數（2026-09-20，F43）：合成版原圖放置那格互斥改標「畫面來源：○○○」
    （呼叫端已用 vstrip_source_text 補好前綴），視覺與「AI示意圖」共用同一套版位／
    底板／字體，只換文字內容——見 compose_ten_cover。
    """
    height = canvas.size[1]
    font = _font(round(height * 0.03))
    text_w = font.getbbox(text)[2]
    pad = round(height * 0.012)
    note_h = round(height * 0.03 * 1.6)
    if align_right:
        x0, x1 = x_anchor - text_w - pad * 2, x_anchor
    else:
        x0, x1 = x_anchor, x_anchor + text_w + pad * 2
    plate = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle((x0, y0, x1, y0 + note_h), radius=6, fill=(0, 0, 0, 130))
    canvas.alpha_composite(plate)
    _draw_text(ImageDraw.Draw(canvas), ((x0 + x1) // 2, y0 + note_h // 2), text, font, stroke_width=0, anchor="mm")


# 拆行點偏好：切在「數量詞結尾」之後（5年｜各自…、184億元｜提升…），比純粹對半自然得多。
_SPLIT_AFTER_CHARS = set("年月日元億萬千人次件位家戶%％度歲倍條棟艘架台場波班組隊起成")
# 量詞前面要有數（2026-09-13 實拍抓到「歐洲熱浪台｜灣豪雨」：「台」在量詞集合裡，
# 沒有數字也被當「3台｜車」切）。「台灣／人民／成長／制度」這些字尾都在集合裡，
# 沒有數在前面的量詞字就只是普通字，不能當斷點。
_NUMBER_WORD_CHARS = set("一二三四五六七八九十百千萬億兩幾數多半")


def _quantifier_after_number(text: str, end: int) -> bool:
    """text[end] 是量詞字：往回跳過連續量詞字（億元、萬人），前面是不是數字／數字字。"""
    j = end
    while j >= 0 and text[j] in _SPLIT_AFTER_CHARS:
        j -= 1
    return j >= 0 and (text[j].isdigit() or text[j] in _NUMBER_WORD_CHARS)

# 虛詞邊界（2026-09-10）：切在這些字**之後**很少會腰斬一個詞——「容易被忽略的｜前兆」。
_SPLIT_AFTER_PARTICLES = set("的了與和及至到後前中上下內外時起才又也都就再")
# 切在這些字**之前**同理——「容易｜被忽略的前兆」。
_SPLIT_BEFORE_PARTICLES = set("被把將對於為讓使與和及因但而且或如若從向往自")


# 一段「數字」不是只有連續數字：9/12、5.5、20:00 中間的符號也在數字裡面，從那裡斷行
# 會把日期切成兩截（2026-09-09 使用者回報 9/12）。回傳所有**不准當斷點**的索引。
#
# B92（2026-09-22 正式站 18:15:07 王結玲）：拉丁字母串同理。「白宮封殺CNN遭提告」
# 10 字、中點落在 index 5，正好是第二個 N，成品印出「白宮封殺C／NN遭提告」。
# 中文方塊字可以逐字斷，拉丁字母串不行——CNN、AI、GDP、F-16、COVID-19 都是
# **一個不可分的記號**，跟數字是同一類結構，不是 `_SPLIT_KEEP_TOGETHER` 那種
# 會愈長愈胖的詞典（2026-09-14 裁決「不再加條目」針對的是那一份）。所以這裡
# 直接把原本的「數字記號」放寬成「英數記號」，一條規則同時管住三條路：
# 模型給的 hint（`_hint_cuts` 的結果會被 inner 濾）、括號邊緣、與保底中點切。
_ATOMIC_TOKEN_RE = re.compile(r"[0-9A-Za-z]+(?:[/.:\-][0-9A-Za-z]+)*")


def _atomic_token_inner_indices(text: str) -> set[int]:
    inner: set[int] = set()
    for match in _ATOMIC_TOKEN_RE.finditer(text):
        inner.update(range(match.start() + 1, match.end()))
    return inner


# 括號（2026-09-13 使用者回報「川普發布「擴張版」美國地圖」被切成「擴／張版」）：
# 引號裡的是一個詞，裡面一律不准切；引號兩側反而是最好的斷點。
_BRACKET_PAIRS = {"「": "」", "『": "』", "《": "》", "〈": "〉", "（": "）", "(": ")", "【": "】", "“": "”"}
_BRACKET_CLOSERS = set(_BRACKET_PAIRS.values())

# 常見專有名詞小詞典：沒有斷詞器（本機與 Cloud Run 都沒裝），只能用一份短名單擋最常見的
# 腰斬——「格陵蘭」被切成「格／陵蘭」（2026-09-13 同一則回報）。只收 3 字以上、新聞高頻的
# 國名／地名／機構名；2 字詞交給虛詞規則（切到 2 字詞中間的機率本來就低）——
# 例外是「台灣／臺灣」：新聞標題出現頻率最高，且「台」同時是量詞字（2026-09-13）。
_SPLIT_KEEP_TOGETHER = (
    "台灣", "臺灣",
    "格陵蘭", "加拿大", "墨西哥", "冰島", "巴拿馬", "委內瑞拉", "阿根廷", "哥倫比亞", "巴西", "古巴",
    "烏克蘭", "俄羅斯", "白俄羅斯", "波蘭", "立陶宛", "愛沙尼亞", "拉脫維亞", "羅馬尼亞", "保加利亞",
    "塞爾維亞", "克羅埃西亞", "斯洛伐克", "斯洛維尼亞", "匈牙利", "捷克", "奧地利", "瑞士", "比利時",
    "荷蘭", "丹麥", "挪威", "瑞典", "芬蘭", "葡萄牙", "西班牙", "義大利", "希臘", "土耳其", "以色列",
    "巴勒斯坦", "加薩", "黎巴嫩", "敘利亞", "伊拉克", "伊朗", "沙烏地", "阿拉伯", "卡達", "阿聯",
    "葉門", "埃及", "利比亞", "蘇丹", "衣索比亞", "索馬利亞", "肯亞", "奈及利亞", "南非",
    "巴基斯坦", "阿富汗", "孟加拉", "斯里蘭卡", "尼泊爾", "印尼", "馬來西亞", "新加坡", "菲律賓",
    "越南", "柬埔寨", "泰國", "緬甸", "澳洲", "紐西蘭", "北韓", "南韓", "日本", "印度",
    "加州", "德州", "佛州", "紐約", "華府", "華盛頓", "白宮", "五角大廈", "國會山莊",
    "北約", "歐盟", "聯合國", "世衛", "國際刑警", "國際法院", "海牙",
    "格陵蘭島", "巴拿馬運河", "墨西哥灣", "阿拉斯加", "夏威夷", "波多黎各",
    "無人機", "太空船", "核電廠", "半導體", "台積電", "航空母艦", "潛艦", "飛彈",
)


def _protected_inner_indices(text: str) -> set[int]:
    """所有**不准當斷點**的索引：英數記號中間、括號內、專有名詞中間。"""
    inner = _atomic_token_inner_indices(text)
    stack: list[str] = []
    for i, ch in enumerate(text):
        if ch in _BRACKET_PAIRS:
            stack.append(_BRACKET_PAIRS[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
        elif stack:
            inner.add(i)          # 括號內：切在這個字**之前**＝把引號裡的詞腰斬
    for word in _SPLIT_KEEP_TOGETHER:
        start = text.find(word)
        while start != -1:
            inner.update(range(start + 1, start + len(word)))
            start = text.find(word, start + 1)
    return inner


def _bracket_edge_split(text: str, inner: set[int]) -> tuple[str, str] | None:
    """最靠近中點的括號邊緣（開括號之前、閉括號之後）當斷點；沒有括號回 None。"""
    n = len(text)
    mid = n // 2
    edges = [i for i in range(2, n - 1) if (text[i] in _BRACKET_PAIRS or text[i - 1] in _BRACKET_CLOSERS)]
    edges = [i for i in edges if i not in inner]
    if not edges:
        return None
    i = min(edges, key=lambda e: (abs(e - mid), e))
    return text[:i], text[i:]


# ---- 模型給的斷句邊界（2026-09-14 使用者裁決）----
#
# 使用者：「為何要依賴斷詞機制，這個機制會一直長胖」——下面那套規則（量詞／虛詞／括號／
# 小詞典）每被抓到一次腰斬就長一條，追不完。改成：封面請求一進來就請消化模型把每段
# 標題切成詞組（main.segment_titles_for_breaks），這裡只在詞組邊界上切；模型沒回、
# 回得不忠實（接回去不等於原句）、或邊界踩到數字中間，才退回原本的規則。規則集從此
# 只當退路，不再加條目。
#
# 用 ContextVar 而不是改簽名：斷行從 wrap／fill／split_cover_title 好幾條路進來，
# 每一條都要穿參數太吵；FastAPI 的同步端點每個請求各自一份 context，互不污染。
_BREAK_HINTS: contextvars.ContextVar[dict[str, tuple[int, ...]]] = contextvars.ContextVar(
    "cover_break_hints", default={}
)


def set_break_hints(phrases_by_text: dict[str, list[str]]) -> None:
    """登記模型切好的詞組：{原段: [詞組, ...]}。詞組接回去不等於原段的一律丟掉。"""
    hints: dict[str, tuple[int, ...]] = {}
    for text, phrases in (phrases_by_text or {}).items():
        parts = [str(p) for p in (phrases or []) if str(p)]
        if len(parts) < 2 or "".join(parts) != text:
            continue
        cuts, pos = [], 0
        for part in parts[:-1]:
            pos += len(part)
            cuts.append(pos)
        hints[text] = tuple(cuts)
    _BREAK_HINTS.set(hints)


def clear_break_hints() -> None:
    _BREAK_HINTS.set({})


def _hint_cuts(text: str) -> list[int]:
    """這一行可用的模型邊界。行可能是登記段的子字串（拆過一次再拆），位移對回去。"""
    out: list[int] = []
    for seg, cuts in _BREAK_HINTS.get().items():
        start = seg.find(text)
        while start != -1:
            out.extend(c - start for c in cuts if 0 < c - start < len(text))
            start = seg.find(text, start + 1)
    return sorted(set(out))


def _split_line_near_middle(text: str) -> tuple[str, str]:
    """把一行從中間附近切成兩行。

    模型邊界優先（見 _BREAK_HINTS）：有可用邊界就取最靠近中點的那一個。

    偏好順序：數量詞結尾 → 虛詞結尾 → 虛詞開頭 → 最靠近中點且不切在數字中間。
    最後那條是保底，切出來的詞可能被腰斬（184億元 不能變 18／4億元 已由 inner 擋掉，
    但「忽略」這種實詞沒有規則擋得住），所以前三條要盡量先命中。
    """
    n = len(text)
    mid = n // 2
    inner = _protected_inner_indices(text)
    hinted = [i for i in _hint_cuts(text) if 1 <= i <= n - 1 and i not in inner]
    if hinted:
        i = min(hinted, key=lambda e: (abs(e - mid), e))
        return text[:i], text[i:]
    # 括號邊緣最優先（2026-09-13）：「川普發布「擴張版」美國地圖」→「川普發布／「擴張版」美國地圖」
    at_edge = _bracket_edge_split(text, inner)
    if at_edge is not None:
        return at_edge
    for offset in range(0, 4):
        for i in (mid - offset, mid + offset):
            if (
                2 <= i <= n - 2 and i not in inner and text[i - 1] in _SPLIT_AFTER_CHARS
                and _quantifier_after_number(text, i - 1) and not text[i].isdigit()
                and text[i] not in _SPLIT_AFTER_CHARS   # 184億｜元：量詞串要整串在前行
            ):
                return text[:i], text[i:]
    # 虛詞邊界（2026-09-10）：純粹取中點會把詞腰斬——使用者回報「容易被忽略的前兆」
    # 被切成「容易被忽／略的前兆」。沒有斷詞器可用（本機與 Cloud Run 都沒裝），
    # 但中文裡「的了在與和…」幾乎不會是一個詞的中間，切在它們前後就安全得多。
    # 掃描範圍放寬到中點 ±(n//4+1)：只在 ±3 內找，多數句子根本掃不到虛詞。
    reach = n // 4 + 1
    for offset in range(0, reach + 1):
        for i in (mid - offset, mid + offset):
            if 2 <= i <= n - 2 and i not in inner and text[i - 1] in _SPLIT_AFTER_PARTICLES and not text[i].isdigit():
                return text[:i], text[i:]
    for offset in range(0, reach + 1):
        for i in (mid - offset, mid + offset):
            if 2 <= i <= n - 2 and text[i] in _SPLIT_BEFORE_PARTICLES and i not in inner:
                return text[:i], text[i:]
    for offset in range(0, n):
        for i in (mid + offset, mid - offset):
            if 1 <= i < n and i not in inner:
                return text[:i], text[i:]
    return text[:mid], text[mid:]


def _wrap_pairs(pairs: list[tuple[str, int]], max_w: int, size: int, max_lines: int) -> list[tuple[str, int]]:
    """超寬防呆（2026-09-07）：在起始字級塞不進格寬的行，從中間切成兩行（最長的先切）。

    行帶著段落索引一起走（拆出來的兩行都繼承原本那一段的索引），只是那個索引現在
    **只記錄出處、不決定顏色**——2026-09-08 同日第二輪裁決把配色改回依行序。

    2026-09-11：**≤ COVER_TITLE_FILL_MIN_CHARS 字的段一律不切**。使用者回報
    「葉門青年運動 奪下紅海咽喉」被切成「葉門青年／運動／奪下紅海咽喉」，
    把專有名詞（葉門的青年運動＝胡塞武裝）腰斬成「葉門的年輕人在運動」。
    根因就在這裡：使用者用空白明確定好的斷點，被這支函式在段**內**又切一刀。

    而且那一刀什麼也沒換到。實測「葉門青年運動」在起始字級 146 寬 876，只超出
    max_w=833 共 43px（5%），縮一級到 138 就塞得下；而同格另一行「奪下紅海咽喉」
    同樣 6 字、同樣要縮到 138，所以**切與不切最終字級都是 138**。右格的
    「升息房貸夾擊」也是 6 字 876px 超寬，只因為它已經是第 3 行就沒被切——
    可見 6 字在這個版面本來就是正常長度，切它純粹是損失。

    門檻沿用 COVER_TITLE_FILL_MIN_CHARS（7）而不是另訂一個數字：這個 repo 已經
    三處用 7 表示「一行的合理上限」（消化規格每段 4–7 字、_fill_pairs、
    COVER_TITLE_AUTO_SPLIT_LEN）。真正超長的段（9 字、12 字）照舊拆——那些不拆
    會把兩格共用的字級一起壓垮，2026-09-07 建這道防呆就是為了它們。
    """
    pairs = list(pairs)
    font = _font(size)
    while len(pairs) < max_lines:
        widths = [font.getbbox(text)[2] for text, _ in pairs]
        idx = max(range(len(pairs)), key=widths.__getitem__)
        text, seg = pairs[idx]
        # 最寬的那行都不必切，其餘更不必——中文等寬，最寬幾乎就是最長。
        if widths[idx] <= max_w or len(text) < 4:
            break
        if len(text) <= COVER_TITLE_FILL_MIN_CHARS:
            break
        head, tail = _split_line_near_middle(text)
        pairs[idx : idx + 1] = [(head, seg), (tail, seg)]
    return pairs


def _fill_pairs(pairs: list[tuple[str, int]], max_lines: int) -> list[tuple[str, int]]:
    """雙切專用的字數拆行（2026-09-08）：只要一行超過 COVER_TITLE_FILL_MIN_CHARS 就再拆。

    為什麼要在寬度規則之外再來一條：雙切改成**兩格同一字級**之後，共同字級由最長的那一行
    決定。一格三行 6 字、另一格有一行 11 字，兩格就一起被壓到那個 11 字的字級。把行拆到
    都夠短（≤ 7 字），共同字級才撐得起來。滿版不套——它沒有另一格要遷就。
    """
    pairs = list(pairs)
    while len(pairs) < max_lines:
        idx = max(range(len(pairs)), key=lambda i: len(pairs[i][0]))
        text, seg = pairs[idx]
        if len(text) <= COVER_TITLE_FILL_MIN_CHARS:
            break
        head, tail = _split_line_near_middle(text)
        if not head.strip() or not tail.strip():
            break
        pairs[idx : idx + 1] = [(head, seg), (tail, seg)]
    return pairs


def wrap_cover_title_lines(lines: list[str], max_w: int, size: int, max_lines: int = COVER_MAX_TITLE_LINES) -> list[str]:
    """`_wrap_pairs` 的純文字版（不帶段落索引的呼叫端與測試用）。"""
    return [text for text, _ in _wrap_pairs([(ln, 0) for ln in lines], max_w, size, max_lines)]


def _fill_cover_title_lines(lines: list[str], max_lines: int = COVER_MAX_TITLE_LINES_SPLIT) -> list[str]:
    """`_fill_pairs` 的純文字版。"""
    return [text for text, _ in _fill_pairs([(ln, 0) for ln in lines], max_lines)]


def _cover_title_metrics(panel_w: int, full_width: bool) -> tuple[int, int, int]:
    """一格標題的 (可用寬, 起始字級, 最小字級)。合成版與 AI 版共用同一套推導。"""
    height = COVER_CANVAS[1]
    width_ratio = COVER_FULL_TITLE_WIDTH_RATIO if full_width else COVER_TITLE_WIDTH_RATIO
    size = round(height * (COVER_FULL_TITLE_SIZE_RATIO if full_width else COVER_TITLE_SIZE_RATIO))
    return round(panel_w * width_ratio), size, round(height * COVER_TITLE_MIN_SIZE_RATIO)


def cover_max_title_lines(full_width: bool) -> int:
    """滿版、雙切都最多 3 行（2026-09-08 裁決：白／黃／紅三行，不能四行）。"""
    return COVER_MAX_TITLE_LINES if full_width else COVER_MAX_TITLE_LINES_SPLIT


def cover_title_panel_width(full_width: bool) -> int:
    """一格標題的版位寬。滿版＝整寬；雙切＝左格安全內框扣掉邊界（見 compose_ten_cover）。"""
    width = COVER_CANVAS[0]
    if full_width:
        return width
    slant = round(width * YT_SPLIT_SLANT_RATIO)
    return (width // 2 - slant // 2) - COVER_MARGIN


def cover_title_segments(title: str) -> list[tuple[str, int]]:
    """使用者用空白分出來的段落，配上段落索引（0＝白、1＝黃、2＝紅）。"""
    from editor_formats import split_cover_title

    segments = [seg for seg in split_cover_title(title) if seg.strip()]
    return [(seg, i) for i, seg in enumerate(segments)]


def cover_title_line_pairs(title: str, *, full_width: bool = False) -> list[tuple[str, int]]:
    """標題分行的單一來源，回 (行, 段落索引)。合成版與 AI 版共用，斷句與配色都不分歧。"""
    pairs = cover_title_segments(title)
    if not pairs:
        return []
    max_lines = cover_max_title_lines(full_width)
    max_w, size, _ = _cover_title_metrics(cover_title_panel_width(full_width), full_width)
    pairs = _wrap_pairs(pairs, max_w, size, max_lines)
    return pairs if full_width else _fill_pairs(pairs, max_lines)


def cover_title_lines(title: str, *, full_width: bool = False) -> list[str]:
    """`cover_title_line_pairs` 的純文字版（純 AI 版組 prompt、前端顯示用）。"""
    return [text for text, _ in cover_title_line_pairs(title, full_width=full_width)]


def _cover_title_vertical_cap(line_count: int, start_size: int) -> int:
    """行數 × 行距要塞在標頭帶以下、底部標題基線以上，否則整體縮字（2026-09-08，上限 3 行）。"""
    height = COVER_CANVAS[1]
    baseline = height - round(height * COVER_TITLE_BOTTOM_RATIO)
    top_limit = round(height * COVER_HEADER_RATIO) + round(height * COVER_TITLE_TOP_CLEARANCE_RATIO)
    span = 1 + (line_count - 1) * COVER_TITLE_LINE_GAP
    return max(1, min(start_size, int((baseline - top_limit) / span)))


def cover_panel_title_size(pairs: list[tuple[str, int]], panel_w: int) -> int | None:
    """雙切一格的字級：所有行都塞得進格寬、且整疊塞得進版面高度的最大共同字級。

    回 None＝這格沒有標題。兩格取全域最小值才是最終字級（見 compose_ten_cover）。
    """
    if not pairs:
        return None
    max_w, size, min_size = _cover_title_metrics(panel_w, False)
    fitted = min(_fit_font(text, max_w, size, min_size).size for text, _ in pairs)
    return min(fitted, _cover_title_vertical_cap(len(pairs), size))


def _draw_cover_title(
    canvas: Image.Image, pairs: list[tuple[str, int]], panel_x0: int, panel_x1: int, align_right: bool,
    *, full_width: bool = False, size_override: int | None = None,
) -> None:
    """一格的標題：由下往上堆，配色**依行序**（第 1 行白、第 2 行黃、第 3 行紅白邊）。

    雙切：字級由 size_override 給（兩格同一個值，2026-09-08 使用者裁決「兩邊字不一樣大」不行）。
    full_width=True（滿版單一標題）：橫跨整個畫面、置中、逐行各自撐滿，比照今日熱搜。
    拆完縮到最小字級仍塞不進就整支失敗，不出超線的圖。
    """
    width, height = COVER_CANVAS
    pairs = [(text, seg) for text, seg in pairs if text.strip()][: cover_max_title_lines(full_width)]
    if not pairs:
        return
    panel_w = panel_x1 - panel_x0
    max_w, size, min_size = _cover_title_metrics(panel_w, full_width)
    if size_override is not None:
        fonts = [_font(size_override)] * len(pairs)
    else:
        fonts = [_fit_font(text, max_w, size, min_size) for text, _ in pairs]
    for (text, _), font in zip(pairs, fonts):
        if font.getbbox(text)[2] > max_w:
            hint = "請縮短這一段" if len(pairs) >= cover_max_title_lines(full_width) else "請用半形空格分段或縮短"
            raise ComposeError(f"標題太長，縮到最小字級仍超出版面：「{text}」（{hint}；最多 {cover_max_title_lines(full_width)} 行）")
    baseline = height - round(height * COVER_TITLE_BOTTOM_RATIO)
    if full_width:
        x, anchor = panel_x0 + panel_w // 2, "ms"
    elif align_right:
        x, anchor = panel_x1 - round(panel_w * (1 - COVER_TITLE_WIDTH_RATIO) / 2), "rs"
    else:
        x, anchor = panel_x0 + round(panel_w * (1 - COVER_TITLE_WIDTH_RATIO) / 2), "ls"
    draw = ImageDraw.Draw(canvas)
    # 由最後一行往上畫；顏色看**行序**（第 1 行白、第 2 行黃、第 3 行紅），不是段落索引
    for idx in range(len(pairs) - 1, -1, -1):
        text, _ = pairs[idx]
        font = fonts[idx]
        bold = round(font.size * COVER_TITLE_BOLD_RATIO)
        # 描邊先加上假粗體會吃掉的寬度，加粗完外框才不會只剩一兩個像素（同 _draw_yt_title_line）
        stroke = max(3, round(font.size * COVER_TITLE_STROKE_RATIO)) + bold
        colour = COVER_TITLE_LINE_COLOURS[min(idx, len(COVER_TITLE_LINE_COLOURS) - 1)]
        is_red = colour == COVER_TITLE_LINE_COLOURS[2]
        # 陰影一層再正字，字壓在照片上才立得住
        _draw_text(draw, (x + 4, baseline + 4), text, font, fill=(0, 0, 0), stroke=(0, 0, 0), stroke_width=stroke, anchor=anchor)
        _draw_text(
            draw, (x, baseline), text, font, fill=colour,
            stroke=COVER_TITLE_STROKE_LIGHT if is_red else COVER_TITLE_STROKE_DARK,
            stroke_width=stroke, anchor=anchor,
        )
        if bold > 0:
            _draw_text(draw, (x, baseline), text, font, fill=colour, stroke=colour, stroke_width=bold, anchor=anchor)
        # 往上一行：行距用**這一行**的字級算（滿版逐行不同字級時，大字行才不會壓到上面的小字行）
        baseline -= round(font.size * COVER_TITLE_LINE_GAP)


def compose_ten_cover(
    left_image: bytes,
    right_image: bytes | None,
    *,
    title_left: str,
    title_right: str,
    date_text: str,
    badge: str = COVER_DEFAULT_BADGE,
    left_is_ai: bool = True,
    right_is_ai: bool = True,
    prebuilt_split: bool = False,
    left_source_text: str = "",
    right_source_text: str = "",
) -> bytes:
    """合成「十點不一樣」封面圖（2026-09-06 斜切全幅版）。

    兩張底圖（AI 生的或使用者原圖）斜切鋪滿，薄標頭帶、日期、標籤、兩邊多行標題
    全部由這裡畫。title_left／title_right 可用空白或換行自己分行（最多 3 行），
    沒分行且太長時由 split_cover_title 對切；哪一格是 AI 底圖才印「AI示意圖」。

    right_image 為 None＝單張全版（2026-09-06 使用者裁決：只上傳一張原圖就是整版鋪滿，
    不切左右格），兩個標題仍各自壓在左下與右下。

    prebuilt_split=True（2026-09-14 雙切「只改文字」）：left_image 已經是拼好的 16:9 雙切
    底圖（split_canvas 的輸出，壓字前），right_image 必須是 None；版面照雙切走——斜切安全
    內框、兩格各自暗化、兩格同字級——只是不再重拼。

    left_source_text／right_source_text（2026-09-20，F43）：那一格不是 AI 底圖、且呼叫端
    填了來源名時，改標「畫面來源：○○○」，與「AI示意圖」互斥、同一個版位——AI 標籤贏
    （*_is_ai 為 True 時這兩個參數被忽略），因為 is_ai=True 代表那格畫面本來就不是使用者
    原圖，掛「畫面來源」等於對觀眾說謊。互斥判定與文字正規化交給呼叫端
    （main.resolve_image_disclaimer／compose.vstrip_source_text），這裡只管「貼哪一種」。
    """
    if badge not in COVER_BADGES:
        raise ComposeError(f"未知的標籤：{badge!r}（可用：{list(COVER_BADGES)}）")
    width, height = COVER_CANVAS
    mid = width // 2
    if prebuilt_split and right_image is not None:
        raise ComposeError("prebuilt_split 時 right_image 必須是 None（底圖已經拼好）")
    if right_image is None and not prebuilt_split:
        canvas = _cover_panel(left_image, COVER_CANVAS).convert("RGBA")
        left_box = (0, 0, mid, height)
        right_box = (mid, 0, width, height)
        _shade_panel_bottom(canvas, (0, 0, width, height))
    else:
        # 拼好的底圖尺寸就是 COVER_CANVAS，_cover_panel 對它是原樣回傳（不縮放不裁），
        # 所以「只改文字」重壓出來的成品跟第一次逐像素相同（tests/test_cover_split_recompose_20260914）。
        canvas = (
            _cover_panel(left_image, COVER_CANVAS) if prebuilt_split
            else split_canvas([left_image, right_image], COVER_CANVAS)
        ).convert("RGBA")
        slant = round(width * YT_SPLIT_SLANT_RATIO)
        # 兩格的「安全內框」：避開斜線最寬處
        left_box = (0, 0, mid - slant // 2, height)
        right_box = (mid + slant // 2, 0, width, height)
        for box in (left_box, right_box):
            _shade_panel_bottom(canvas, box)

    draw = ImageDraw.Draw(canvas)
    band_h = _draw_cover_header(draw, canvas, date_text, badge)

    note_y = band_h + round(height * 0.025)
    if left_is_ai:
        _draw_cover_ai_note(canvas, COVER_MARGIN, note_y, align_right=False)
    elif left_source_text.strip():
        _draw_cover_ai_note(
            canvas, COVER_MARGIN, note_y, align_right=False,
            text=vstrip_source_text(left_source_text),
        )
    if right_is_ai:
        _draw_cover_ai_note(canvas, width - COVER_MARGIN, note_y, align_right=True)
    elif right_source_text.strip():
        _draw_cover_ai_note(
            canvas, width - COVER_MARGIN, note_y, align_right=True,
            text=vstrip_source_text(right_source_text),
        )

    _draw_cover_bottom_line(canvas)
    if right_image is None and not prebuilt_split and not title_right.strip():
        # 滿版單一標題：橫跨整寬、置中、逐行各自撐滿（2026-09-07）
        _draw_cover_title(canvas, cover_title_line_pairs(title_left, full_width=True), 0, width,
                          align_right=False, full_width=True)
    else:
        # 雙切：兩格同一字級（2026-09-08 使用者裁決「兩邊字不一樣大」不行）。
        # 先各自算出這一格塞得下的最大字級，再取兩格的最小值當兩格所有行的字級。
        left_pairs = cover_title_line_pairs(title_left)
        right_pairs = cover_title_line_pairs(title_right)
        left_x0, left_x1 = left_box[0] + COVER_MARGIN, left_box[2]
        right_x0, right_x1 = right_box[0], right_box[2] - COVER_MARGIN
        candidates = [
            size for size in (cover_panel_title_size(left_pairs, left_x1 - left_x0),
                              cover_panel_title_size(right_pairs, right_x1 - right_x0))
            if size is not None
        ]
        shared = min(candidates) if candidates else None
        _draw_cover_title(canvas, left_pairs, left_x0, left_x1, align_right=False, size_override=shared)
        _draw_cover_title(canvas, right_pairs, right_x0, right_x1, align_right=True, size_override=shared)
    if badge == "highlight":
        _draw_cover_highlight_stamp(canvas)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
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
# 2026-09-08 使用者回饋「字體再粗一點、行距略縮」（國內外新聞直播與今日熱搜共用這組）：
# 行距 0.194 → 0.180（縮約 7%），第二行貼底不動、第一行往下靠；
# 加粗用「同色描邊」做假粗體（字型檔只有台北黑體 Bold 一個字重，沒有更粗的可換）。
# 2026-09-09 使用者「非 AI 的雙行標行距可以再縮減」：0.180 → 0.168，一樣只動第一行。
YT_LINE1_BASELINE_RATIO = 0.790      # 第一行字底（原 0.778）
YT_LINE2_BASELINE_RATIO = 0.958      # 第二行字底
YT_TITLE_SIZE_RATIO = 0.145          # 標題起始字級（字高約 100/720）
# 2026-09-08 使用者定版（三個位置樣張挑第 3 個「第二行」）：底帶從第一行字底（基線）開始
# 羽化，到第二行字的墨水上緣才到全濃度——漸層落在兩行標題之間的空隙，
# 不糊第一行、也不把第二行切成兩截。原本 0.60／0.06 把照片下半整片吃掉。
#
# 2026-09-09 使用者「底色框的邊緣可以再多一點漸層羽化」。這跟上面的行距縮減互相擠：
# 空隙變小，羽化沒地方長。做法是讓斜坡**往上多起跑一段**（LEAD）——smoothstep 在
# t 很小的時候幾乎是 0（t=0.13 → 濃度 4.6%），那一段藏在白字腳下看不出來，
# 卻讓整條斜坡從 3.65% 拉長到 6% 畫面高，硬邊感消失。全濃度仍然壓在黃字墨水上緣。
YT_BAND_LEAD_RATIO = 0.020           # 斜坡起點比第一行基線再高一點點（幾乎透明的那段）
YT_BAND_TOP_RATIO = YT_LINE1_BASELINE_RATIO - YT_BAND_LEAD_RATIO   # 0.770
# 結尾仍然壓在黃字墨水上緣之上（0.8231，見 _yt_title_ink_top_ratio）——2026-09-08
# 那條「不超過第二行標題」的裁決沒有被這批取消，所以羽化只能長到 0.822 為止。
YT_BAND_FADE_RATIO = 0.052           # 羽化高度（原 0.0365，+42%）：0.770 + 0.052 = 0.822
YT_BAND_FILL = (8, 25, 70)
# 2026-09-08 使用者裁決：底部壓色框改成開關（預設 OFF），開的時候要半透明——
# 原本 205／255 ≈ 80% 幾乎把照片下半整片吃掉。153／255 = 60%。
YT_BAND_ALPHA = 153
YT_BAND_BLOCK_FILL = (60, 130, 230)
YT_TITLE_MIN_SIZE_RATIO = 0.085
# 2026-09-08 晚使用者：國內外／熱搜「太粗、複雜的字分不出來」，整點「太細」，兩邊要對齊。
# 描邊 0.05→0.04、假粗體 0.015→0.008，三種版面統一走 _draw_yt_title_line（整點原本沒假粗體沒陰影）。
YT_TITLE_STROKE_RATIO = 0.04         # 深色描邊佔字級比例（假粗體吃掉的部分另外補，見 _draw_yt_title_line）
# 2026-09-08 第二輪：3.5% 太重，第二行黃字筆畫互相黏住、字腔（口、日的內白）被吃掉，
# 「關閉社群媒體」糊成一團。降到 1.5%——12 字的長行在最小字級下字腔仍然清楚。
YT_TITLE_BOLD_RATIO = 0.008          # 假粗體：同色描邊佔字級比例
YT_TITLE_SHADOW_RATIO = 0.02         # 陰影位移佔字級比例（底色框預設關之後才補的）
YT_LINE1_FILL = (255, 255, 255)
YT_LINE2_FILL = (250, 215, 0)
YT_TITLE_STROKE = (8, 8, 8)
YT_AI_NOTE = "AI示意圖"
YT_AI_NOTE_SIZE_RATIO = 0.032
# 右側小標的版位護欄（2026-09-20，獨立複查第三項）：底板左緣不得越過畫布 40%，
# 字級可以一路縮到 0.020 去遷就，再塞不下就報錯——見 _draw_ai_note。
YT_NOTE_MIN_LEFT_RATIO = 0.40
YT_NOTE_MIN_SIZE_RATIO = 0.020
YT_AI_NOTE_TOP_RATIO = 0.20          # 藍標籤之下的右側空位
YT_AI_NOTE_PLATE = (0, 0, 0, 120)

# ---- 底色框上界（2026-09-08 WP3）----
# 羽化結尾不准疊到第二行字：上界用**最大字級**的 ascent 算，不用某一句話 fit 完的字級：
# 短標題不會縮字，ink 會比長標題更高，拿長標題量出來的上緣當上界，換一句短的就被漸入層蓋到。
# outline 是描邊往外撐的部分。
def _yt_title_ink_top_ratio(baseline_ratio: float) -> float:
    """該行標題在最大字級下、含描邊的墨水上緣（佔畫布高的比例）。"""
    _, height = YT_CANVAS
    size = round(height * YT_TITLE_SIZE_RATIO)
    font = _font(size)
    ascent, _ = font.getmetrics()
    outline = max(4, round(size * YT_TITLE_STROKE_RATIO)) + round(size * YT_TITLE_BOLD_RATIO)
    return (round(height * baseline_ratio) - ascent - outline) / height


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


def _fit_note_font(text: str, max_text_w: int, blocked_by: str):
    """把小標字級縮到塞得進 max_text_w，回 (font, 實際寬度)；縮到下限仍塞不下就擋。

    2026-09-20 獨立複查（gpt-5.6-sol）第三項共用的護欄——`_draw_ai_note`（靠右，
    左邊是 LIVE 章與日期）與 `_draw_live24_ai_note`（靠左，右邊是 Logo）兩支都是
    為「AI示意圖」五個字寫死字級的，F43 讓 text 變成使用者輸入之後就會溢出去壓到
    固定元素。縮字優先（使用者拿得到成品），縮不下去才報錯（使用者自己改得掉）。
    """
    height = YT_CANVAS[1]
    floor = round(height * YT_NOTE_MIN_SIZE_RATIO)
    size = round(height * YT_AI_NOTE_SIZE_RATIO)
    while True:
        font = _font(size)
        note_w = font.getbbox(text)[2]
        if note_w <= max_text_w or size <= floor:
            break
        size -= 1
    if note_w > max_text_w:
        raise ComposeError(
            f"「{text}」太長（縮到最小字級仍有 {note_w}px，版位上限 {max_text_w}px），"
            f"再長會壓到{blocked_by}，請改用較短的來源名"
        )
    return font, note_w


def _draw_ai_note(canvas: Image.Image, y0: int, *, text: str = YT_AI_NOTE) -> None:
    """右側小標（半透明黑底、白字），y0 為標籤頂，預設文字是「AI示意圖」。

    text 參數（2026-09-20，F43）：那一格不是 AI 底圖、改標「畫面來源：○○○」時
    共用同一套版位／底板／字體，只換文字內容——見各 compose_yt_*cover 呼叫端。

    2026-09-20 獨立複查（gpt-5.6-sol）第三項：這支原本是為「AI示意圖」五個字寫的，
    字級與右靠位置都寫死、沒有任何寬度上限。F43 接上之後 text 變成使用者輸入
    （`YtCoverRequest.source_text` 允許 40 字），實測「畫面來源：」＋40 個全形字的
    底板是 (259, 216)-(1858, 268)——橫跨畫布 83%，直接蓋掉左上角的 LIVE 章與日期板
    （佔 (50, 54)-(486, 349)）。因此加一道版位護欄：先縮字，縮到下限還是塞不下就擋。
    """
    width, height = YT_CANVAS
    margin = round(width * YT_MARGIN_RATIO)
    note_h = round(height * YT_AI_NOTE_SIZE_RATIO * 1.5)
    x1 = width - margin - 12
    # 底板左緣的硬界線：左上角那一叢固定元素（LIVE 章／日期板）最右到 x=486，
    # 留一段安全距離取畫布 40%（=768）。標籤是右靠的，所以只需要管左緣。
    min_left = round(width * YT_NOTE_MIN_LEFT_RATIO)
    max_text_w = x1 - min_left - 24
    note_font, note_w = _fit_note_font(text, max_text_w, "左上角的 LIVE 章與日期")
    plate = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle(
        (x1 - note_w - 24, y0, x1, y0 + note_h), radius=8, fill=YT_AI_NOTE_PLATE
    )
    canvas.alpha_composite(plate)
    _draw_text(ImageDraw.Draw(canvas), (x1 - 12, y0 + note_h // 2), text, note_font, stroke_width=0, anchor="rm")


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


def _logo_tab_layer(
    top_colour: tuple[int, int, int] = YT_LOGO_TAB_TOP,
    bottom_colour: tuple[int, int, int] = YT_LOGO_TAB_BOTTOM,
) -> Image.Image:
    """右上角漸層標籤（左邊斜切、左下圓角）本身，畫在一張畫布大小的透明圖上。

    跟貼 Logo 拆開，是為了 PNG 壓標要把標籤鏡射到另外三個角——鏡射整張會連 Logo
    一起翻過去。預設藍色（新聞直播）；今日熱搜傳紅色。
    """
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
        colour = tuple(round(top_colour[i] * (1 - t) + bottom_colour[i] * t) for i in range(3))
        gd.line(((0, y), (width, y)), fill=colour + (255,))
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    layer.paste(gradient, (0, 0), mask)
    return layer


def _draw_logo_tab(
    canvas: Image.Image,
    top_colour: tuple[int, int, int] = YT_LOGO_TAB_TOP,
    bottom_colour: tuple[int, int, int] = YT_LOGO_TAB_BOTTOM,
) -> None:
    """右上角漸層標籤＋白色 TVBS Logo，貼著畫面右上角。"""
    width, height = YT_CANVAS
    canvas.alpha_composite(_logo_tab_layer(top_colour, bottom_colour))
    _paste_logo(canvas, (round(width * YT_LOGO_LEFT_RATIO), round(height * YT_LOGO_TOP_RATIO)), round(width * YT_LOGO_WIDTH_RATIO))


def _draw_yt_title_line(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
    font: ImageFont.FreeTypeFont, fill: tuple[int, int, int], anchor: str = "ms",
) -> None:
    """YT 封面的一行標題：深色描邊 → 同色描邊加粗（2026-09-08 使用者回饋「字體再粗一點」）。

    台北黑體只有 Bold 一個字重，沒有更粗的檔可換，所以用同色描邊把字身撐開。
    深色描邊要**先加上假粗體吃掉的寬度**，不然加粗完外框只剩一兩個像素，
    字壓在照片上（底色框現在預設關）就立不住。
    """
    # 不設下限：假粗體是「加多少」不是「至少多少」，設了 max(2, …) 會讓 1.5% 與完全不加粗
    # 在常見字級下畫出一模一樣的字（round(157 × 0.015)=2，撞到下限）。
    bold = round(font.size * YT_TITLE_BOLD_RATIO)
    outline = max(4, round(font.size * YT_TITLE_STROKE_RATIO)) + bold
    # 陰影一層再正字（比照十點封面的標題）：底色框 2026-09-08 起預設關，字直接壓在照片上，
    # 光靠描邊在亮背景仍然糊。位移用字級的比例算，字級縮了陰影跟著縮。
    shadow = round(font.size * YT_TITLE_SHADOW_RATIO)
    if shadow > 0:
        _draw_text(draw, (xy[0] + shadow, xy[1] + shadow), text, font, fill=(0, 0, 0),
                   stroke=(0, 0, 0), stroke_width=outline, anchor=anchor)
    _draw_text(draw, xy, text, font, fill=fill, stroke=YT_TITLE_STROKE, stroke_width=outline, anchor=anchor)
    if bold > 0:
        _draw_text(draw, xy, text, font, fill=fill, stroke=fill, stroke_width=bold, anchor=anchor)


def _yt_shared_title_font(lines: list[str], max_w: int, start: int, smallest: int):
    """YT 封面兩行標題共用一個字級（2026-09-08 使用者裁決：同一組標題各行一律同字級）。

    每行各自算出塞得進寬度的字級，取全域最小；兩行都短時就是起始字級。
    """
    sizes = [_fit_font(text, max_w, start, smallest).size for text in lines if text]
    return _font(min(sizes)) if sizes else _font(start)


def _yt_hourly_title_ink_top_ratio(font: ImageFont.FreeTypeFont, baseline_ratio: float) -> float:
    """整點封面某一行標題、用給定字級畫出來時，含描邊的墨水上緣（佔畫布高比例）。

    跟 `_yt_title_ink_top_ratio` 算法一樣，差別是那支只服務固定字級
    （`YT_TITLE_SIZE_RATIO`）的國內外／熱搜封面；整點的字級是 `_yt_shared_title_font`
    依標題長度動態決定的，所以字級要當參數傳進來，不能寫死。F36（2026-09-21 定案）
    的日期牌就是貼在這支算出來的墨水上緣往上 `YT_HOURLY_DATE_TAB_GAP_RATIO` 處。
    """
    _, height = YT_CANVAS
    size = font.size
    ascent, _ = font.getmetrics()
    outline = max(4, round(size * YT_TITLE_STROKE_RATIO)) + round(size * YT_TITLE_BOLD_RATIO)
    return (round(height * baseline_ratio) - ascent - outline) / height


def _draw_title_band(
    canvas: Image.Image,
    fill: tuple[int, int, int] = YT_BAND_FILL,
    block_fill: tuple[int, int, int] = YT_BAND_BLOCK_FILL,
    *,
    top_ratio: float | None = None,
    fade_ratio: float | None = None,
) -> None:
    """底部科技底帶：頂端漸入，帶上撒幾塊半透明方塊模擬頻道的電路紋。

    預設深藍（新聞直播）；今日熱搜傳深紅。
    top_ratio／fade_ratio 是出樣張用的覆寫，None＝沿用定版常數（2026-09-08 使用者挑定：
    第一行基線起羽化、第二行上緣到全濃度）。
    """
    width, height = YT_CANVAS
    top = round(height * (YT_BAND_TOP_RATIO if top_ratio is None else top_ratio))
    fade = round(height * (YT_BAND_FADE_RATIO if fade_ratio is None else fade_ratio))
    band = Image.new("RGBA", (width, height - top), fill + (0,))
    alpha = Image.new("L", band.size, YT_BAND_ALPHA)
    ad = ImageDraw.Draw(alpha)
    for y in range(fade):
        # smoothstep 羽化：兩端切線水平，看不到「這裡開始有框」的硬邊
        t = y / fade
        ad.line(((0, y), (width, y)), fill=round(YT_BAND_ALPHA * t * t * (3 - 2 * t)))
    band.putalpha(alpha)
    blocks = Image.new("RGBA", band.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(blocks)
    # 固定序列，不用亂數：同一張輸入永遠得到同一張輸出
    seq = [(0.02, 0.35, 0.09, 0.05), (0.13, 0.62, 0.05, 0.16), (0.21, 0.10, 0.12, 0.05),
           (0.36, 0.72, 0.08, 0.10), (0.47, 0.20, 0.05, 0.20), (0.58, 0.58, 0.13, 0.05),
           (0.70, 0.08, 0.06, 0.14), (0.79, 0.66, 0.10, 0.07), (0.90, 0.28, 0.07, 0.18)]
    for fx, fy, fw, fh in seq:
        x0, y0 = round(fx * width), round(fy * band.height)
        bd.rectangle((x0, y0, x0 + round(fw * width), y0 + round(fh * band.height)), fill=block_fill + (55,))
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
    source_text: str = "",
    draw_titles: bool = True,
    bottom_band: bool = False,
    band_top_ratio: float | None = None,
    band_fade_ratio: float | None = None,
) -> bytes:
    """合成 YT 國內外新聞直播封面（2026-09-06 依頻道實際版面）。

    bottom_band（2026-09-08 晚使用者裁決改預設**開**）：底部深藍壓色框。關＝完全不畫，
    標題靠描邊自己立在照片上；開＝畫，且只有 YT_BAND_ALPHA（60%）不透明，照片透得出來。

    draw_titles=False（標題由 AI 生成模式）：background 已經是模型畫好含標題與底帶的
    整張圖，這裡只貼固定元素（LIVE 章／日期／原音呈現／AI即時翻譯／藍標籤／AI示意圖）。

    background 是**無文字**底圖（使用者附圖或 AI 生成），任意尺寸，這裡等比例
    裁滿 1920×1080。line1／line2 是已分好的兩行標題（分段邏輯在 editor_formats），
    original_audio＝LIVE 章上方「原音呈現」、ai_translation＝日期下方「AI即時翻譯」，
    兩者獨立可並存；ai_note=True 時右側加「AI示意圖」（AI 生的底圖一律標，附圖不標）。

    source_text（2026-09-20，F43）：ai_note=False 且底圖是原圖放置時，填了來源名
    改標「畫面來源：○○○」，與「AI示意圖」互斥、同一個版位——ai_note=True 時這個
    參數被忽略（AI 標籤贏）。
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
    if draw_titles and bottom_band:
        _draw_title_band(canvas, top_ratio=band_top_ratio, fade_ratio=band_fade_ratio)
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
    date_font = _fit_font_bold(
        date_text, tab_w - 28, round(tab_h * 0.72), round(tab_h * 0.4),
        ratio=YT_BOLD_STROKE_RATIO,
    )
    _draw_bold_text(
        draw, ((tab_box[0] + tab_box[2]) // 2, (tab_box[1] + tab_box[3]) // 2 + 2),
        date_text, date_font, fill=YT_DATE_TEXT, anchor="mm", ratio=YT_BOLD_STROKE_RATIO,
    )
    if ai_translation:
        small = _font(round(height * YT_AI_TRANSLATION_SIZE_RATIO))
        _draw_text(
            draw, (tab_box[0] + 6, tab_box[3] + round(height * YT_AI_TRANSLATION_GAP_RATIO)),
            YT_AI_TRANSLATION_LABEL, small, stroke=YT_TITLE_STROKE, stroke_width=4, anchor="la",
        )

    # ---- 右側：AI 示意圖小標（只有 AI 底圖才有）／畫面來源（F43，互斥）----
    if ai_note:
        _draw_ai_note(canvas, round(height * YT_AI_NOTE_TOP_RATIO))
        draw = ImageDraw.Draw(canvas)
    elif source_text.strip():
        _draw_ai_note(
            canvas, round(height * YT_AI_NOTE_TOP_RATIO),
            text=vstrip_source_text(source_text),
        )
        draw = ImageDraw.Draw(canvas)

    # ---- 底部：兩行標題置中（白／黃、黑描邊）----
    max_w = width - margin * 2
    start = round(height * YT_TITLE_SIZE_RATIO)
    smallest = round(height * YT_TITLE_MIN_SIZE_RATIO)
    font = _yt_shared_title_font([line1, line2], max_w, start, smallest)
    for text, fill, baseline_ratio in (
        (line1, YT_LINE1_FILL, YT_LINE1_BASELINE_RATIO),
        (line2, YT_LINE2_FILL, YT_LINE2_BASELINE_RATIO),
    ) if draw_titles else ():
        if font.getbbox(text)[2] > max_w:
            raise ComposeError(f"標題太長，縮到最小字級仍超出版面：「{text}」（請縮短這一行）")
        _draw_yt_title_line(draw, (width // 2, round(height * baseline_ratio)), text, font, fill)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


# ---- YT 整點直播（2026-09-06，範例：整點直播 YT 截圖 20:00）----
# 跟國內外新聞直播同一套底圖流程，只有版面不同：Logo 在左上（小）、LIVE 章在右上、
# 章下可掛整點時間（選填）、日期是紅底白字貼在第一行標題正上方、沒有副標。
# 比例量自截圖去掉 YT 介面後的縮圖區（約 415×220）。
YT_HOURLY_LOGO_WIDTH_RATIO = 0.118      # Logo 寬（48/415）
YT_HOURLY_LOGO_TOP_RATIO = 0.064
# 2026-09-09 使用者：右上 LIVE 章與整點時間白框「再縮小一點點」。章寬 0.25→0.225，
# 時間帶寬度是從 badge_w 推的會跟著縮，帶高另外按同比例收（0.095→0.086）。
YT_HOURLY_BADGE_WIDTH_RATIO = 0.225     # LIVE 章寬（原 0.25）
YT_HOURLY_BADGE_TOP_RATIO = 0.024
YT_HOURLY_TIME_BAND_HEIGHT_RATIO = 0.086  # 章下時間帶高（原 0.095）
YT_HOURLY_TIME_BAND_FILL = (255, 255, 255)   # 頻道實際：白底紅字
YT_HOURLY_TIME_BAND_TEXT = (200, 20, 30)
# 2026-09-13 使用者：「日期 BAR 稍微縮小且往上一點點，不影響創意階梯」——只動 0 級程式畫的
# 寬與上緣（0.30→0.27、0.52→0.485）；高度不動，因為 editor_formats 那份同值常數是 1 級起
# 模型畫牌的護欄，動了就等於改到階梯。
YT_HOURLY_DATE_TAB_WIDTH_RATIO = 0.27   # 日期紅條寬（原 0.30＝125/415）
YT_HOURLY_DATE_TAB_HEIGHT_RATIO = 0.095
YT_HOURLY_DATE_TOP_RATIO = 0.485        # 日期紅條上緣（原 0.52＝114/220）；取 .485 讓 prompt 的 :.0% 取整後仍包住牌
YT_HOURLY_DATE_FILL = (214, 22, 32)
YT_HOURLY_DATE_TEXT = (255, 255, 255)
YT_HOURLY_LINE1_BASELINE_RATIO = 0.815   # 2026-09-08 晚使用者「行距可略縮」：0.80→0.815（第二行不動）
YT_HOURLY_LINE2_BASELINE_RATIO = 0.965
YT_HOURLY_TITLE_SIZE_RATIO = 0.15       # 字高 32/220
YT_HOURLY_AI_NOTE_TOP_RATIO = 0.34      # LIVE 章（含時間帶）之下的右側空位

# F36（2026-09-21 使用者定案）：0 級程式畫的日期牌，下緣一律離第一行標題墨水上緣
# 這個距離——不分字數多寡。定案過程：先問「≥6 字觸發要用多少」答 40px，再補問
# 「<6 字呢」，看過 104／80／60／40 四張樣張後同樣挑 40px，兩邊同一個數字，
# 所以「字數門檻」整個不必存在，規則收斂成一句話：永遠 40px。
# （樣張：D:\Downloads\AICG\後台紀錄\20260921\F36_樣張_短標題\）
YT_HOURLY_DATE_TAB_GAP_RATIO = 40 / 1080

# ---- 日期條的創意階梯（2026-09-11 使用者裁決）----
#
# 0 級：程式畫板、程式壓字，位置固定（＝這支函式一直以來的行為，一個像素都沒變）。
# 1–4 級：**整個日期牌交給生圖模型**——紅框、風格、位置、連日期數字本身都是它畫的，
#         程式完全不碰（compose_yt_hourly_cover(draw_date=False)）。
#
# 這條是使用者明確裁決的，而且他知道代價：它違反本模組開頭第二條原則
# （Logo、日期、ON AIR 這類「錯了就是播出事故」的東西只能是圖層合成）。
# 使用者的理由是程式壓字同樣有風險——模型畫的板跟程式壓的座標對不上就會露邊。
# 降風險的做法寫在 editor_formats.yt_hourly_date_clause：日期字串進 TEXT TO RENDER
# 的逐字清單，跟標題共用同一套「每個字元必須正確、不准多寫一個字」的約束。
#
# 驗收時**一定要逐張確認日期數字**。這是這條路唯一真正的風險，而且它在成品上
# 看起來完全正常——沒有人會在播出前去對那八個數字。
YT_HOURLY_DATE_TAB_BOX = (
    YT_MARGIN_RATIO,
    YT_HOURLY_DATE_TOP_RATIO,
    YT_MARGIN_RATIO + YT_HOURLY_DATE_TAB_WIDTH_RATIO,
    YT_HOURLY_DATE_TOP_RATIO + YT_HOURLY_DATE_TAB_HEIGHT_RATIO,
)

# 1 級起模型自己畫牌時，牌**跟著大標題走：貼在第一行標題的左上方、左緣與標題切齊**
# ——也就是 0 級程式貼出來的那個樣子（2026-09-11 使用者裁決，改了三次後定案：
# 先「位置整個交給 AI」，實拍 L1–L4 四張全擠在上半部偏左，變化不大又失去可預期性；
# 再「置頂置中」；最後是這個）。
#
# 為什麼這次可以用相對描述，而今天早上那個 bug 不行：早上是**AI 畫標題、程式貼日期**，
# 兩邊各自認定「標題上方」在哪，必然對不上；1 級起是**同一個模型畫標題也畫牌**，
# 相對定位對它自洽，而且跟著標題走比釘死一個座標更協調。
#
# 即使如此仍附上 YT_HOURLY_DATE_TAB_BOX 當**護欄**（補強，不是取代相對指示）：
# 純相對描述今天已經出過一次事，給個範圍讓它不會飄走。
#
# ⚠2026-09-21 起這個框**不再等於 0 級程式貼的位置**：F36 定案後，0 級的牌子會依標題
# 墨水上緣往下移（最大字級時約 +64px），這個框仍停在原處。
#
# 注意它只是 0 級的殘留基準與 B55 保護區來源——**1–4 級的 AI 護欄不是這個框**，是
# editor_formats.yt_hourly_date_guide_box(level)，那支本來就從該級的標題字頂往上推
# （YT_HOURLY_DATE_TITLE_GAP_RATIO = 0.02H ≈ 21.6px），塊高一變牌就跟著走。所以兩條
# 路的「位置邏輯」是一致的（都貼著標題），差的只有間距數字：壓字 40px／AI 21.6px。
#
# 2026-09-21 使用者看過 40 vs 21.6 的壓字對照樣張後裁決：**壓字版維持 40px，AI 版
# 不動**。兩邊不統一是他知情後的選擇，不要再「順手」改成同一個數字。


@functools.lru_cache(maxsize=1)
def yt_hourly_logo_extent() -> tuple[float, float]:
    """程式**實際**貼上的 Logo 佔到哪（右緣、下緣，佔畫面比例）。

    2026-09-11 抓到的碰撞：prompt 手打「保留左上角 14% 寬、14% 高」，而實際貼上去
    的 Logo 量出來是 14.4% 寬、**16.1% 高**——宣告值比實際小。實拍 L3／L4 的日期牌
    頂落在 15.9%，比 Logo 下緣還高，會疊上去。

    同一個病今天出現第三次（早上是日期條寫「標題正上方」、中午是 prompt 百分比手打）：
    **凡是模型要閃避的東西，座標都必須從程式實際畫的那個值算出來，不可以手打。**
    這支函式就是那個單一真相源；prompt 的保留區與日期牌的位置都從它推。
    """
    if not TVBS_LOGO_WHITE.exists():
        raise ComposeError(f"找不到 Logo 檔：{TVBS_LOGO_WHITE}")
    width, height = YT_CANVAS
    logo_w = round(width * YT_HOURLY_LOGO_WIDTH_RATIO)
    with Image.open(TVBS_LOGO_WHITE) as logo_file:
        logo_h = round(logo_file.height * logo_w / logo_file.width)
    right = (round(width * YT_MARGIN_RATIO) + logo_w) / width
    bottom = (round(height * YT_HOURLY_LOGO_TOP_RATIO) + logo_h) / height
    return right, bottom


def yt_hourly_logo_keep_out() -> tuple[float, float]:
    """要模型閃開的左上角保留區（寬、高）。實際佔用再往外留一格餘裕。"""
    right, bottom = yt_hourly_logo_extent()
    return (
        math.ceil((right + YT_KEEP_OUT_MARGIN_RATIO) * 100) / 100,
        math.ceil((bottom + YT_KEEP_OUT_MARGIN_RATIO) * 100) / 100,
    )


# 保留區比實際佔用再外擴這麼多。模型的落點本來就有 ±1.6% 的抖動（pre-test 量的），
# 貼齊實際邊緣等於把那點抖動全押在「剛好不撞」上。
YT_KEEP_OUT_MARGIN_RATIO = 0.01


# 「雙則」每行字數上限（2026-09-08 使用者裁決）：兩行各是一則新聞的完整標題，
# 不是同一句拆兩段，長度沒有天然上限，所以要有一條硬線。單則模式不套用。
YT_HOURLY_LINE_MAX_CHARS = 18          # 2026-09-08 晚使用者：14 放寬到 18


def title_display_width(text: str) -> float:
    """標題長度（全形字算 1、半形字算 0.5）。

    直接數 len() 會把「1380」這種半形數字當 4 個字——使用者自己給的樣張標題
    「尼泊爾洪災逾1380死家屬抗議」len() 是 15、實際排出來只有 13 個全形字寬。
    上限本來就是為了「排不排得下」，所以照顯示寬度算才對得上。
    """
    return sum(0.5 if unicodedata.east_asian_width(ch) in ("Na", "H") else 1.0 for ch in text)


def compose_yt_hourly_cover(
    background: bytes,
    *,
    line1: str,
    line2: str,
    date_text: str,
    time_text: str = "",
    ai_note: bool = False,
    source_text: str = "",
    draw_titles: bool = True,
    line_max_chars: int | None = None,
    draw_date: bool = True,
) -> bytes:
    """合成 YT 整點直播封面。time_text（如 20:00）選填，有填才在 LIVE 章下掛時間帶。

    draw_titles=False：標題已由模型畫在 background 上，這裡只貼固定元素。

    draw_date=False（2026-09-11 日期條創意階梯，創意 ≥1）：整個日期牌——紅框、風格、
    位置、數字——都是生圖模型畫的，程式一筆都不碰。預設 True＝0 級的原行為。
    date_text 這時仍是必填：它要進 prompt 給模型照抄。

    line_max_chars（2026-09-08 WP2）：每行字數上限，超過就報錯。給「雙則」用——
    那個模式的兩行各是一則新聞的完整標題，不是同一句拆兩段，長度沒有天然上限。
    單則模式不帶這個參數，維持原行為。

    source_text（2026-09-20，F43）：ai_note=False 且底圖是原圖放置時，填了來源名
    改標「畫面來源：○○○」，與「AI示意圖」互斥、同一個版位——ai_note=True 時這個
    參數被忽略（AI 標籤贏）。
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

    # 標題字級提前算好：F36 起日期牌的位置要看它（見下方「左中：日期」那段），
    # 畫字的迴圈仍然留在原本靠底部的位置，這裡只是把字級計算搬前面共用。
    max_w = width - margin * 2
    start = round(height * YT_HOURLY_TITLE_SIZE_RATIO)
    smallest = round(height * YT_TITLE_MIN_SIZE_RATIO)
    font = _yt_shared_title_font([line1, line2], max_w, start, smallest)

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
        # 時間用 Times New Roman Bold（2026-09-13 使用者裁決），不跟標題共用台北黑體
        time_font = _fit_font_bold(
            time_text, band[2] - band[0] - 24, round(band_h * 0.8), round(band_h * 0.4),
            ratio=YT_BOLD_STROKE_RATIO, loader=_time_font,
        )
        _draw_bold_text(
            draw, ((band[0] + band[2]) // 2, (band[1] + band[3]) // 2 + 2),
            time_text, time_font, fill=YT_HOURLY_TIME_BAND_TEXT, anchor="mm",
            ratio=YT_BOLD_STROKE_RATIO,
        )
        block_bottom = band[3]

    # ---- 右側：AI 示意圖小標（只有 AI 底圖才有）／畫面來源（F43，互斥）----
    draw = ImageDraw.Draw(canvas)
    if ai_note:
        _draw_ai_note(canvas, max(round(height * YT_HOURLY_AI_NOTE_TOP_RATIO), block_bottom + 16))
        draw = ImageDraw.Draw(canvas)
    elif source_text.strip():
        _draw_ai_note(
            canvas, max(round(height * YT_HOURLY_AI_NOTE_TOP_RATIO), block_bottom + 16),
            text=vstrip_source_text(source_text),
        )
        draw = ImageDraw.Draw(canvas)

    # ---- 左中：紅底白字日期（只有 0 級才由程式畫，見 YT_HOURLY_DATE_TAB_BOX 註解）----
    if draw_date:
        box = YT_HOURLY_DATE_TAB_BOX
        tab_box = (
            round(width * box[0]), round(height * box[1]),
            round(width * box[2]), round(height * box[3]),
        )
        if draw_titles:
            # F36（2026-09-21 使用者定案，取代 0920 那版「依字級自動判斷」）：
            # 日期牌下緣一律貼到離第一行標題墨水上緣 YT_HOURLY_DATE_TAB_GAP_RATIO
            # （＝40px @1080）的位置，不分字數。
            #
            # 為什麼 0920 那版要廢掉：那版是拿「現行成品」反推 GAP（實測 104px），
            # 再讓字級縮小時日期牌跟著下移。結果是這條規則只在「字級真的被縮小」時
            # 才會動，而字級要縮小得一行超過 max_w（約 11 個全形字）——整點直播的
            # 標題幾乎都 4~8 字，所以使用者實機驗收「F36 沒成功」：功能從來沒觸發過。
            # 使用者原本要的是「字數多就靠近」，被實作成「字級小才靠近」，兩者在這個
            # 版型幾乎不重疊。改成固定間距後，短標題也會往下靠，才看得出效果。
            #
            # 標題越長→字級越小→墨水上緣越低→日期牌跟著越往下，靠的是 ink_top
            # 本身，不必再有第二套判斷。
            ink_top = round(height * _yt_hourly_title_ink_top_ratio(font, YT_HOURLY_LINE1_BASELINE_RATIO))
            gap = round(height * YT_HOURLY_DATE_TAB_GAP_RATIO)
            # clamp 只是保險：ink_top 最高就是最大字級那一檔（730px），減掉 40 仍在
            # 牌的下緣（626px）之下，實務上永遠是正的，不會把牌往上拉。
            shift = max(0, (ink_top - gap) - tab_box[3])
            if shift:
                tab_box = (tab_box[0], tab_box[1] + shift, tab_box[2], tab_box[3] + shift)
        draw.rounded_rectangle(tab_box, radius=10, fill=YT_HOURLY_DATE_FILL)
        tab_w, tab_h = tab_box[2] - tab_box[0], tab_box[3] - tab_box[1]
        date_font = _fit_font_bold(
            date_text, tab_w - 28, round(tab_h * 0.78), round(tab_h * 0.4),
            ratio=YT_BOLD_STROKE_RATIO,
        )
        _draw_bold_text(
            draw, ((tab_box[0] + tab_box[2]) // 2, (tab_box[1] + tab_box[3]) // 2 + 2),
            date_text, date_font, fill=YT_HOURLY_DATE_TEXT, anchor="mm",
            ratio=YT_BOLD_STROKE_RATIO,
        )

    # ---- 底部：兩行標題（白／黃、黑描邊），靠左貼邊 ----
    max_w = width - margin * 2
    start = round(height * YT_HOURLY_TITLE_SIZE_RATIO)
    smallest = round(height * YT_TITLE_MIN_SIZE_RATIO)
    font = _yt_shared_title_font([line1, line2], max_w, start, smallest)
    for text, fill, baseline_ratio in (
        (line1, YT_LINE1_FILL, YT_HOURLY_LINE1_BASELINE_RATIO),
        (line2, YT_LINE2_FILL, YT_HOURLY_LINE2_BASELINE_RATIO),
    ) if draw_titles else ():
        if line_max_chars and title_display_width(text) > line_max_chars:
            raise ComposeError(f"標題超過 {line_max_chars} 字：「{text}」（請縮短這一行）")
        # 共用字級縮到最小仍塞不下時放著不管就是字被畫框裁掉
        if font.getbbox(text)[2] > max_w:
            raise ComposeError(f"標題太長，縮到最小字級仍超出版面：「{text}」（請縮短這一行）")
        # 與國內外／熱搜同一支畫字（描邊＋假粗體＋陰影），三種 YT 封面字重對齊
        _draw_yt_title_line(draw, (margin, round(height * baseline_ratio)), text, font, fill, anchor="ls")

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


# ============================================================
# 版型：YT 24H LIVE（live24）——hourly 的鏡像
# ============================================================
#
# 與 hourly 的差別：Logo 換成兩層版移到右上、LIVE 章換成左上的 24H LIVE 角標素材、
# 標題從兩行白黃改成一行深紅斜體。詳見 docs/plan-20260913-live24版型.md。
#
# **這個版型是純合成版**：標題／角標／日期／Logo 一律程式壓，創意階梯只作用在底圖。
# 標題規格（單行、指定紅、淺描邊、3.5° 斜度）精確到模型打不中，而這條線本來就有
# 零錯字的合成版可用，所以不開 AI 標題路徑。
#
# 角標是**一張生成好的固定素材**（2026-09-13 使用者裁決：不用向量畫、生一次固定壓），
# 程式只在上面壓日期。素材與日期框的關係見 LIVE24_BADGE_DATE_BOX。
LIVE24_BADGE = BRAND_DIR / "live24-badge.png"

# 素材的原始尺寸。釘死是為了擋「有人重新去背／重裁 PNG」——下面的日期框是相對
# **這一份裁切**量出來的，bbox 一變日期就會掉到鉚金屬框上，而且不會報錯，只會歪掉。
LIVE24_BADGE_SIZE = (2675, 1225)

# 日期壓字區（相對角標素材的比例）。已內縮避開 V2 那圈粗鉚金屬框，量法是
# 「從字標與板子之間那道透明縫切開，縫以下的不透明範圍＝板子」，再上下左右內縮。
# 材質板沒有單一實色區塊，不能用「最大實色塊」那套找（2026-09-13）。
LIVE24_BADGE_DATE_BOX = (0.097, 0.602, 0.911, 0.924)
# 日期跟著角標的斜度走，不然字是正的、板是斜的，一眼就看得出來是後貼的
LIVE24_DATE_SHEAR = 0.20
# **點**不是斜線。hourly 的 %Y/%m/%d 是另一個版型的格式，照抄會跟實際播出不一致。
LIVE24_DATE_FORMAT = "%Y.%m.%d"

# 以下三組全部量自 24H LIVE範本/Still0911_00009.jpg（1920×1080 實際播出 HD 截圖）。
# 不要拿 Sleekshot 那些螢幕截圖來量——有縮放與視窗邊框。
LIVE24_BADGE_WIDTH_RATIO = 0.31       # 角標寬佔畫面（範本量到 24H LIVE＋日期整塊 33%）
LIVE24_BADGE_LEFT_RATIO = 0.028
LIVE24_BADGE_TOP_RATIO = 0.045
LIVE24_LOGO_WIDTH_RATIO = 0.138       # 兩層版 Logo：範本 x 0.828–0.966
LIVE24_LOGO_RIGHT_RATIO = 0.966       # 右緣（不是左緣——這個版型的 Logo 靠右對齊）
LIVE24_LOGO_TOP_RATIO = 0.053
LIVE24_TITLE_SIZE_RATIO = 0.231       # 範本字高 249/1080
LIVE24_TITLE_BASELINE_RATIO = 0.894   # 範本紅字底緣
LIVE24_TITLE_LEFT_RATIO = 0.053       # 範本紅字左緣
LIVE24_TITLE_MAX_WIDTH_RATIO = 0.896  # 0.949 - 0.053
# 標題向右上斜。範本實測 +3.5°（斜率 0.0607）——2026-09-11 目視估的「2–3 度」偏小。
LIVE24_TITLE_SHEAR = 0.0607
# 範本紅字取樣中位色。memo 當初估 #901010，實測比那個亮一些。
LIVE24_TITLE_FILL = (159, 19, 20)
# 描邊是淺灰白（不是純白）：純白在亮底圖上跟背景黏在一起，範本用的是帶灰的白。
LIVE24_TITLE_STROKE = (236, 236, 236)
# 字太長時容許縮到這裡，再短就報錯要求改標題。0.150 是刻意訂高的下限：
# 這個版型的標題是唯一的文字主體，縮到跟內文一樣小就失去存在意義。
LIVE24_TITLE_MIN_SIZE_RATIO = 0.150
# 橫向壓縮下限。範本用的是**窄長體**——量到字高 249px、每字前進約 143px，
# 寬高比 0.63；台北黑體是方的，照原比例畫同樣字數只能用 0.132 的字高，
# 比範本小掉四成、氣勢整個垮掉。所以照範本比例把字橫向壓扁，壓到 0.60 為止；
# 再擠就變形得看得出來，那時改縮字級。
LIVE24_TITLE_SQUEEZE_FLOOR = 0.60


def _paste_live24_badge(canvas: Image.Image, box: tuple[int, int], width: int,
                        date_text: str) -> int:
    """貼 24H LIVE 角標並在它的日期板上壓日期，回傳貼上後的高度。

    日期在**素材原尺寸**上先壓好再整張縮到版面寬，而不是縮完再壓：素材 2675px 寬、
    版面只有 595px，先縮再壓等於用 1/4.5 的解析度畫字，數字邊緣會糊。
    """
    if not LIVE24_BADGE.exists():
        raise ComposeError(f"找不到 24H LIVE 角標素材：{LIVE24_BADGE}")
    with Image.open(LIVE24_BADGE) as badge_file:
        badge = badge_file.convert("RGBA")
        if badge.size != LIVE24_BADGE_SIZE:
            raise ComposeError(
                f"24H LIVE 角標素材尺寸是 {badge.size}，不是定版的 {LIVE24_BADGE_SIZE}。"
                "日期框的比例是相對定版那一份裁切量的，換了素材要重量一次"
                "（見 docs/plan-20260913-live24版型.md）"
            )
        badge = _stamp_live24_date(badge, date_text)
        height = round(badge.height * width / badge.width)
        badge = badge.resize((width, height), Image.LANCZOS)
        canvas.alpha_composite(badge, box)
    return height


def _stamp_live24_date(badge: Image.Image, date_text: str) -> Image.Image:
    """在角標的日期板上壓日期（白字、跟著角標斜）。"""
    text = (date_text or "").strip()
    if not text:
        raise ComposeError("YT 24H LIVE 封面需要日期")
    bw, bh = badge.size
    l, t, r, b = LIVE24_BADGE_DATE_BOX
    x0, y0, x1, y1 = round(bw * l), round(bh * t), round(bw * r), round(bh * b)
    box_w, box_h = x1 - x0, y1 - y0

    size = round(box_h * 0.95)
    while size > 8:
        font = _font(size)
        bb = font.getbbox(text)
        if bb[2] - bb[0] <= box_w and bb[3] - bb[1] <= box_h:
            break
        size -= 2
    layer = Image.new("RGBA", (box_w * 2, box_h * 2), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((box_w // 3, box_h // 3), text, font=font, fill=(255, 255, 255))
    bb = layer.getbbox()
    if bb is None:
        raise ComposeError(f"日期「{text}」畫不出任何墨跡")
    layer = layer.crop(bb)
    shear = LIVE24_DATE_SHEAR
    layer = layer.transform(
        (layer.width + int(layer.height * shear), layer.height), Image.AFFINE,
        (1, shear, -shear * layer.height, 0, 1, 0), resample=Image.BICUBIC,
    )
    layer = layer.crop(layer.getbbox())
    out = badge.copy()
    out.alpha_composite(layer, (x0 + (box_w - layer.width) // 2, y0 + (box_h - layer.height) // 2))
    return out


def _draw_live24_title(canvas: Image.Image, text: str) -> None:
    """一行深紅標題，淺灰白描邊＋深色陰影，整行向右上斜 LIVE24_TITLE_SHEAR。

    斜度是**把畫好的字整層做仿射**，不是逐字旋轉：範本上那行字是整條一起斜的，
    逐字旋轉會讓每個字自己歪掉、字間距也跟著亂。
    """
    width, height = canvas.size
    max_w = round(width * LIVE24_TITLE_MAX_WIDTH_RATIO)
    start = round(height * LIVE24_TITLE_SIZE_RATIO)
    smallest = round(height * LIVE24_TITLE_MIN_SIZE_RATIO)
    # 先用範本字高，塞不下就先靠橫向壓縮；壓到下限還塞不下才降字級（見 SQUEEZE_FLOOR）
    size = start
    while size > smallest:
        if _font(size).getbbox(text)[2] * LIVE24_TITLE_SQUEEZE_FLOOR <= max_w:
            break
        size -= 2
    font = _font(size)
    natural_w = font.getbbox(text)[2]
    if natural_w * LIVE24_TITLE_SQUEEZE_FLOOR > max_w:
        raise ComposeError(
            f"標題太長，縮到最小字級、壓到最扁仍超出版面：「{text}」"
            "（24H LIVE 是單行版型，全形上限約 17 字，請縮短）"
        )
    squeeze = min(1.0, max_w / natural_w)

    # 畫布要照**壓縮前**的自然寬度開。用 max_w 開會在壓縮之前就把字裁掉——
    # 壓縮是後面才做的，這裡的字還是原寬（2026-09-13 樣張抓到：12 字只畫出 8 字）。
    pad = round(size * 0.9)
    layer = Image.new("RGBA", (natural_w + pad * 2, round(size * 2.2)), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    bold = round(size * YT_TITLE_BOLD_RATIO)
    outline = max(4, round(size * YT_TITLE_STROKE_RATIO)) + bold
    shadow = round(size * YT_TITLE_SHADOW_RATIO)
    baseline = round(size * 1.5)
    if shadow > 0:
        _draw_text(d, (pad + shadow, baseline + shadow), text, font, fill=(0, 0, 0),
                   stroke=(0, 0, 0), stroke_width=outline, anchor="ls")
    _draw_text(d, (pad, baseline), text, font, fill=LIVE24_TITLE_FILL,
               stroke=LIVE24_TITLE_STROKE, stroke_width=outline, anchor="ls")
    if bold > 0:
        _draw_text(d, (pad, baseline), text, font, fill=LIVE24_TITLE_FILL,
                   stroke=LIVE24_TITLE_FILL, stroke_width=bold, anchor="ls")

    # 橫向壓縮成窄長體。壓在斜度**之前**：先壓再斜，斜度才是成品上看到的角度；
    # 先斜再壓會把角度一起壓掉（壓 0.63 會讓 3.5° 變成 5.5°）。
    if squeeze < 1.0:
        layer = layer.resize(
            (max(1, round(layer.width * squeeze)), layer.height), Image.LANCZOS
        )

    # 仿射：左端低、右端高。shear 為正時 x 越大 y 越小，所以係數帶負號。
    sh = LIVE24_TITLE_SHEAR
    lift = round(layer.width * sh)
    tall = Image.new("RGBA", (layer.width, layer.height + lift), (0, 0, 0, 0))
    tall.alpha_composite(layer, (0, lift))
    tall = tall.transform(tall.size, Image.AFFINE, (1, 0, 0, sh, 1, 0), resample=Image.BICUBIC)
    bb = tall.getbbox()
    if bb is None:
        raise ComposeError(f"標題「{text}」畫不出任何墨跡")
    tall = tall.crop(bb)
    # tall 已經裁到墨跡 bbox，pad 不在裡面了——這裡再扣一次 pad 會把字推到貼齊左邊框
    x = round(width * LIVE24_TITLE_LEFT_RATIO)
    y = round(height * LIVE24_TITLE_BASELINE_RATIO) - tall.height
    canvas.alpha_composite(tall, (max(0, x), max(0, y)))


# ---- live24 的第三種底圖：雙切疊圖（2026-09-13）----
#
# 大底圖鋪滿，右側再疊一張白框斜照片。三種底圖裡只有這一種要新寫合成器——
# 滿版就是原圖，雙切漸層用現成的 blend_backgrounds_lr。
#
# 幾何量自 24H LIVE範本/Still0911_00009.jpg 的右側照片面板：
#   上緣 (0.476, 0.231) → (0.917, 0.113)，斜率 -0.151（-8.7°，逆時針）
#   白框粗細中位數 6px / 1080 = 0.0056
# 高度：範本上那張照片的**下緣被標題壓住**，量不到。改量左邊緣——它從 (741,287)
# 一路到 (805,707) 都還在（0.655 佔高處被標題蓋掉，實際還更長）。上緣長 856px，
# 取 16:9 時高 481px、下緣落在 0.68，跟左邊緣量到的延伸方向一致；4:3 會算到 0.83，
# 整塊蓋過標題，與範本不符（第一版就是這樣做錯的）。
# ⚠️ 仍是**由左邊緣反推**，不是直接量到下緣。拿到下緣沒被壓住的範本要重量一次。
LIVE24_INSET_TOP_LEFT = (0.476, 0.231)     # 旋轉前的左上角（相對整張畫面）
LIVE24_INSET_WIDTH_RATIO = 0.446           # 上緣長度 856/1920
LIVE24_INSET_ASPECT = 16 / 9               # ⚠️ 由左邊緣反推，不是直接量到（見上）
LIVE24_INSET_ANGLE_DEG = 8.7               # 逆時針
LIVE24_INSET_BORDER_RATIO = 0.0056         # 白框粗細佔畫面高
LIVE24_INSET_BORDER_FILL = (255, 255, 255)
# 投影：範本上照片下緣有一圈可見的暗影，讓它浮在底圖上。偏移與模糊都用畫面高換算，
# 換解析度時才會跟著縮。
LIVE24_INSET_SHADOW_OFFSET_RATIO = 0.011
LIVE24_INSET_SHADOW_BLUR_RATIO = 0.014
LIVE24_INSET_SHADOW_ALPHA = 120


def compose_live24_inset_background(base: bytes, inset: bytes) -> bytes:
    """大底圖鋪滿＋右側白框斜照片，回傳 PNG bytes（16:9）。

    回傳的是**底圖**，不是成品：再送進 compose_yt_live24_cover 才會有角標、Logo 與標題。
    分兩支的理由與 blend_backgrounds_lr 相同——底圖三態共用同一個版面合成器。
    """
    canvas = _cover_panel(base, YT_CANVAS).convert("RGBA")
    width, height = YT_CANVAS

    inset_w = round(width * LIVE24_INSET_WIDTH_RATIO)
    inset_h = round(inset_w / LIVE24_INSET_ASPECT)
    border = max(2, round(height * LIVE24_INSET_BORDER_RATIO))

    photo = _cover_panel(inset, (inset_w, inset_h)).convert("RGBA")
    framed = Image.new("RGBA", (inset_w + border * 2, inset_h + border * 2),
                       LIVE24_INSET_BORDER_FILL + (255,))
    framed.alpha_composite(photo, (border, border))

    # 先做投影再轉正片：兩層要同一個角度，分開轉會對不齊
    shadow = Image.new("RGBA", framed.size, (0, 0, 0, LIVE24_INSET_SHADOW_ALPHA))
    rotated = framed.rotate(LIVE24_INSET_ANGLE_DEG, resample=Image.BICUBIC, expand=True)
    rotated_shadow = shadow.rotate(LIVE24_INSET_ANGLE_DEG, resample=Image.BICUBIC, expand=True)
    blur = max(1, round(height * LIVE24_INSET_SHADOW_BLUR_RATIO))
    rotated_shadow = rotated_shadow.filter(ImageFilter.GaussianBlur(blur))

    # 落點：旋轉前左上角的位置。expand=True 之後畫布變大，左上角會往左上跑一點，
    # 這裡不去反推精確的角點——用旋轉後畫布的左上角對齊量到的比例，誤差在一兩個
    # 百分點內，而這個版型的疊圖本來就沒有像素級對位需求。
    x = round(width * LIVE24_INSET_TOP_LEFT[0])
    y = round(height * LIVE24_INSET_TOP_LEFT[1])
    offset = round(height * LIVE24_INSET_SHADOW_OFFSET_RATIO)
    canvas.alpha_composite(rotated_shadow, (x + offset, y + offset))
    canvas.alpha_composite(rotated, (x, y))

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def live24_badge_keep_out_height() -> float:
    """角標貼上去之後佔畫面高的比例（含落點）。

    給 AI 標題模板宣告左上保留區用。**由素材長寬比實算**，不手打——2026-09-11 在
    hourly 踩過：手打的保留區比實際小，模型畫的東西就爬上去撞到程式貼的元素。
    """
    with Image.open(LIVE24_BADGE) as badge:
        ratio = badge.height / badge.width
    return LIVE24_BADGE_TOP_RATIO + LIVE24_BADGE_WIDTH_RATIO * ratio * (
        YT_CANVAS[0] / YT_CANVAS[1]
    )


def compose_yt_live24_cover(
    background: bytes,
    *,
    title: str,
    date_text: str,
    ai_note: bool = False,
    source_text: str = "",
    draw_title: bool = True,
) -> bytes:
    """合成 YT 24H LIVE 封面：底圖＋左上角標（含日期）＋右上兩層 Logo＋單行紅標題。

    draw_title=False：標題已由生圖模型畫在 background 上（創意 ≥1），這裡只貼固定
    元素。角標、日期與 Logo **任何模式下都是程式貼的**——那三個是頻道識別，
    交給模型畫就會有錯字與走樣的版本。

    source_text（2026-09-20，F43）：ai_note=False 且底圖是原圖放置時，填了來源名
    改標「畫面來源：○○○」，與「AI示意圖」互斥、同一個版位。
    """
    title = (title or "").strip()
    if not title:
        raise ComposeError("YT 24H LIVE 封面需要一行標題")

    canvas = _cover_panel(background, YT_CANVAS).convert("RGBA")
    width, height = YT_CANVAS

    # ---- 左上：24H LIVE 角標（日期壓在它的玻璃日期板上）----
    badge_w = round(width * LIVE24_BADGE_WIDTH_RATIO)
    badge_h = _paste_live24_badge(
        canvas,
        (round(width * LIVE24_BADGE_LEFT_RATIO), round(height * LIVE24_BADGE_TOP_RATIO)),
        badge_w, date_text,
    )

    # ---- 右上：TVBS＋NEWS 兩層版 Logo，靠右對齊 ----
    logo_w = round(width * LIVE24_LOGO_WIDTH_RATIO)
    logo_x = round(width * LIVE24_LOGO_RIGHT_RATIO) - logo_w
    if not TVBS_LOGO_NEWS_WHITE.exists():
        raise ComposeError(f"找不到兩層版 Logo：{TVBS_LOGO_NEWS_WHITE}")
    with Image.open(TVBS_LOGO_NEWS_WHITE) as logo_file:
        logo = logo_file.convert("RGBA")
        logo = logo.resize((logo_w, round(logo.height * logo_w / logo.width)), Image.LANCZOS)
        canvas.alpha_composite(logo, (logo_x, round(height * LIVE24_LOGO_TOP_RATIO)))

    # ---- 左側：AI示意圖小標／畫面來源（F43，互斥）。掛在角標正下方——右上被 Logo
    # 佔走了，不能照 hourly 放右邊 ----
    if ai_note:
        _draw_live24_ai_note(canvas, round(height * LIVE24_BADGE_TOP_RATIO) + badge_h + 16)
    elif source_text.strip():
        _draw_live24_ai_note(
            canvas, round(height * LIVE24_BADGE_TOP_RATIO) + badge_h + 16,
            text=vstrip_source_text(source_text),
        )

    # ---- 底部：單行紅標題（AI 標題模式下模型已經畫了，不再壓一次）----
    if draw_title:
        _draw_live24_title(canvas, title)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _draw_live24_ai_note(canvas: Image.Image, y0: int, *, text: str = YT_AI_NOTE) -> None:
    """live24 的小標：**靠左**，貼在角標下方，預設文字是「AI示意圖」。

    與 _draw_ai_note 分開一支的理由：那支寫死靠右，而 live24 的右上是 Logo，
    共用會直接壓在 Logo 上。

    text 參數（2026-09-20，F43）：改標「畫面來源：○○○」時共用同一套版位。
    版位護欄同 `_draw_ai_note`，只是方向相反——這支靠左，會撞到的是右上的 Logo。
    """
    width, height = YT_CANVAS
    x0 = round(width * LIVE24_BADGE_LEFT_RATIO)
    # 靠左，所以管右緣：底板右緣不得越過畫布 60%（＝右側 Logo 區之前）。
    max_text_w = round(width * (1 - YT_NOTE_MIN_LEFT_RATIO)) - x0 - 24
    note_font, note_w = _fit_note_font(text, max_text_w, "右上角的 Logo")
    note_h = round(height * YT_AI_NOTE_SIZE_RATIO * 1.5)
    plate = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle(
        (x0, y0, x0 + note_w + 24, y0 + note_h), radius=8, fill=YT_AI_NOTE_PLATE
    )
    canvas.alpha_composite(plate)
    _draw_text(ImageDraw.Draw(canvas), (x0 + 12, y0 + note_h // 2), text, note_font,
               stroke_width=0, anchor="lm")


# ---- 左右兩張底圖的羽化拼接（2026-09-08 WP2）----
#
# 整點「雙則」的底圖是兩則新聞各一張，但標題是橫跨全寬的兩整行——中間若有 split_canvas
# 那種白色硬邊（或斜切），線會從標題字中間穿過去，兩者互相打架。使用者給的真實封面上
# 兩張圖是「柔和的深色漸層帶」接起來的，看不到任何直線，所以這裡走 alpha 漸融：
# 中線兩側各一段寬羽化，接縫再疊一層很淡的深色暈讓過渡自然。
YT_SEAM_FEATHER_RATIO = 0.07     # 羽化半寬佔畫面寬（中線兩側各 7%，使用者說 6–8%）
YT_SEAM_SHADE_ALPHA = 56         # 接縫深色暈的最深值（56/255 ≈ 22%，使用者上限 25%）
# 接縫中心。**不是 0.5**：羽化帶是中心兩側各 ±feather_ratio，中心放正中時羽化帶的
# 右緣會落在 0.5+0.07=0.57，右圖在那裡才完全不透明——肉眼讀到的分界就在 0.57，明顯偏右
# （2026-09-10 使用者實拍指出：成品量到 1090/1920=0.568）。
# 0.43（＝0.5-feather）只是「剛好不偏右」的下限；使用者要的是**明確偏左**，
# 讓右格拿到多一點寬度，主體才不會被擠到最右邊撞上右上角的 LIVE／時間章。
# 定 0.40：羽化帶 0.33–0.47，分界穩穩在左半邊，右格佔畫面 67%。
YT_SEAM_CENTRE_RATIO = 0.40


def blend_backgrounds_lr(
    left: bytes,
    right: bytes,
    size: tuple[int, int] = YT_CANVAS,
    *,
    feather_ratio: float = YT_SEAM_FEATHER_RATIO,
    seam_ratio: float = YT_SEAM_CENTRE_RATIO,
    shade_alpha: int = YT_SEAM_SHADE_ALPHA,
) -> bytes:
    """左右兩張底圖羽化拼成一張，回 PNG bytes。沒有分隔線、沒有硬邊。

    seam_ratio＝接縫中心佔畫面寬，限 0.35–0.5，且會再被夾到 0.5-feather_ratio 以內。
    **分界絕對不可以偏右**（2026-09-10 使用者裁決）：肉眼讀到的分界是羽化帶的右緣
    （右圖在那裡才完全不透明），所以要限的是 seam+band ≤ 0.5，不是 seam ≤ 0.5。
    超過就夾回去而不是報錯——這是版面規矩，不是呼叫端寫錯參數。

    每一格各自 COVER 裁切到「自己那半再加上羽化帶」的尺寸（不變形）；羽化用 smoothstep
    而不是線性，線性的兩端會留下看得出來的折線。
    """
    if not 0.35 <= seam_ratio <= 0.5:
        raise ComposeError(f"接縫位置要在 0.35–0.5 之間（分界不可偏右）：{seam_ratio}")
    # 羽化帶右緣不得越過正中：肉眼讀到的分界就在那裡
    seam_ratio = min(seam_ratio, 0.5 - feather_ratio)
    width, height = size
    seam = round(width * seam_ratio)
    band = max(2, round(width * feather_ratio))
    x0 = max(0, seam - band)          # 羽化帶左緣：這裡右圖完全透明
    x1 = min(width, seam + band)      # 羽化帶右緣：這裡右圖完全不透明

    canvas = Image.new("RGB", size, (0, 0, 0))
    canvas.paste(_cover_panel(left, (x1, height)), (0, 0))
    right_panel = _cover_panel(right, (width - x0, height))

    mask = Image.new("L", (width - x0, height), 255)
    md = ImageDraw.Draw(mask)
    span = max(1, x1 - x0)
    for i in range(span):
        t = i / span
        md.line(((i, 0), (i, height)), fill=round(255 * t * t * (3 - 2 * t)))  # smoothstep
    canvas.paste(right_panel, (x0, 0), mask)

    # 接縫深色暈：中心最深、往兩側以同一條 smoothstep 收掉，讓兩張圖的亮度差不刺眼
    if shade_alpha > 0:
        shade = Image.new("RGBA", size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shade)
        for x in range(x0, x1):
            d = abs(x - seam) / max(1, band)
            t = max(0.0, 1.0 - d)
            sd.line(((x, 0), (x, height)), fill=(0, 0, 0, round(shade_alpha * t * t * (3 - 2 * t))))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), shade).convert("RGB")

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


# ============================================================
# YT 今日熱搜（2026-09-06 依型錄 H 類「《今日熱搜》獨立版型」）
#
# 底圖鋪滿；頂端一條紅色細條；左上「今日｜熱搜🔍」紅白標籤（今日＝紅底白字、
# 熱搜＝白底紅字、放大鏡）；右上紅色 TVBS 斜標；底部深紅底帶＋兩行置中標題（白／黃）。
# 沒有 LIVE 章、沒有日期、沒有時間——這是議題型版面，不掛播出資訊。
# ============================================================

YT_HOT_TOP_LINE_HEIGHT_RATIO = 0.03
YT_HOT_RED = (214, 22, 32)
YT_HOT_RED_DARK = (150, 10, 20)
YT_HOT_TAG_LEFT_RATIO = 0.027      # 2026-09-07 依 YouTube 實際縮圖量測（W0rMa3a15MA）：標籤 x 35→525、y 35→130 ＠1280×720
YT_HOT_TAG_TOP_RATIO = 0.045
YT_HOT_TAG_HEIGHT_RATIO = 0.13       # 型錄截圖被放大誤導過（曾設 0.27）；實際約佔畫面高 13%、寬 38%
YT_HOT_BAND_FILL = (58, 8, 14)
YT_HOT_BAND_BLOCK_FILL = (200, 40, 50)


def _draw_hot_header(canvas: Image.Image) -> None:
    """頂端紅細條＋左上「今日｜熱搜🔍」標籤＋右上紅色 Logo 斜標。"""
    width, height = YT_CANVAS
    # 頂端紅細條（上深下淺）
    line_h = max(2, round(height * YT_HOT_TOP_LINE_HEIGHT_RATIO))
    line = Image.new("RGBA", (width, line_h))
    ld = ImageDraw.Draw(line)
    for y in range(line_h):
        t = y / max(1, line_h - 1)
        col = tuple(round(YT_HOT_RED_DARK[i] * (1 - t) + YT_HOT_RED[i] * t) for i in range(3))
        ld.line(((0, y), (width, y)), fill=col + (255,))
    canvas.alpha_composite(line, (0, 0))
    _draw_logo_tab(canvas, YT_HOT_RED, YT_HOT_RED_DARK)

    # 「今日｜熱搜🔍」標籤：貼模板（紅色三格，見 HOT_SEARCH_TAG）
    tag_h = round(height * YT_HOT_TAG_HEIGHT_RATIO)
    x0 = round(width * YT_HOT_TAG_LEFT_RATIO)
    y0 = round(height * YT_HOT_TAG_TOP_RATIO)
    _paste_template(canvas, HOT_SEARCH_TAG, (x0, y0), tag_h)


def compose_yt_hot_cover(
    background: bytes,
    *,
    line1: str,
    line2: str,
    ai_note: bool = False,
    source_text: str = "",
    draw_titles: bool = True,
    bottom_band: bool = False,
    band_top_ratio: float | None = None,
    band_fade_ratio: float | None = None,
) -> bytes:
    """合成 YT「今日熱搜」封面：紅色系標頭、無日期無 LIVE，底部兩行標題。

    draw_titles=False（標題由 AI 生成）：background 已含標題與底帶，只貼固定元素。
    bottom_band（2026-09-08 使用者裁決，預設關）：底部深紅壓色框，開關與透明度同新聞版。
    source_text（2026-09-20，F43）：ai_note=False 且底圖是原圖放置時，填了來源名
    改標「畫面來源：○○○」，與「AI示意圖」互斥、同一個版位。
    """
    line1, line2 = (line1 or "").strip(), (line2 or "").strip()
    if not line1 or not line2:
        raise ComposeError("今日熱搜封面需要兩行標題，缺一不可")
    canvas = _cover_panel(background, YT_CANVAS).convert("RGBA")
    width, height = YT_CANVAS
    margin = round(width * YT_MARGIN_RATIO)
    if draw_titles and bottom_band:
        _draw_title_band(canvas, YT_HOT_BAND_FILL, YT_HOT_BAND_BLOCK_FILL,
                         top_ratio=band_top_ratio, fade_ratio=band_fade_ratio)
    _draw_hot_header(canvas)
    if ai_note:
        _draw_ai_note(canvas, round(height * YT_AI_NOTE_TOP_RATIO))
    elif source_text.strip():
        _draw_ai_note(
            canvas, round(height * YT_AI_NOTE_TOP_RATIO),
            text=vstrip_source_text(source_text),
        )
    draw = ImageDraw.Draw(canvas)
    max_w = width - margin * 2
    start = round(height * YT_TITLE_SIZE_RATIO)
    smallest = round(height * YT_TITLE_MIN_SIZE_RATIO)
    font = _yt_shared_title_font([line1, line2], max_w, start, smallest)
    for text, fill, baseline_ratio in (
        (line1, YT_LINE1_FILL, YT_LINE1_BASELINE_RATIO),
        (line2, YT_LINE2_FILL, YT_LINE2_BASELINE_RATIO),
    ) if draw_titles else ():
        if font.getbbox(text)[2] > max_w:
            raise ComposeError(f"標題太長，縮到最小字級仍超出版面：「{text}」（請縮短這一行）")
        _draw_yt_title_line(draw, (width // 2, round(height * baseline_ratio)), text, font, fill)
    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


# ============================================================
# YT 直播「直標」PNG 壓標（2026-09-08 WP3 第二版，計畫書 E 段；2026-09-20 B80 改版）
#
# 第一版做成底部橫向標題條，是誤讀規格：使用者說的「直標」是**垂直**的標題條。
#
# **B80（2026-09-20 使用者裁甲案）**：LIVE 章與藍色色框原本是生圖模型重製的近似圖
# （程式畫漸層＋貼一張去背 LIVE 章），使用者事後拿到官方真檔，裁決「整張官方底圖
# 當固定層，程式只壓直排文字與來源句；標題長度反過來遷就固定色框，超出就縮字級，
# 不准再拉長色框」。色框長度從此是**常數**，不再隨標題行數／格數伸長。
#
# 官方檔（`static/brand/`，本 session 用 `magick`／PIL 逐一量過像素，不是目測）：
#   yt-vstrip-live.png           （來源「直播底圖(直).png」，1914×1063）：一般版，
#                                 LIVE 章 184×71 @(31,100)、藍色框 189×485 @(31,171)。
#   yt-vstrip-live-labelled.png  （來源「原音呈現底圖(直).png」，1905×1070）：有
#                                 原音呈現／AI即時翻譯小標時，LIVE 章與白底小標貼合
#                                 無縫成一塊 194×146 @(19,67)，之後接藍色框 194×489
#                                 @(19,213)。
# 兩張圖右上角都烤了一枚 TVBS NEWS 字標——那不是這次要換的東西（程式自己的
# Logo／logo_corner 系統維持不變），裁切時只取左側 LIVE 章＋色框那一叢，右上的
# 字標整塊丟棄。
#
# 比例一律用「該圖自己的」寬高當分母（例如 31/1914），不換算成 1920×1080 再存一次
# ——兩張圖的長寬比跟畫布只差 1% 左右，直接把原生比例套進畫布不會看出破綻，換算
# 反而多一層誤差來源。放大縮小時是連同「裁切框」一起等比縮放到畫布尺寸，不是先把
# 整張圖縮放再裁切。
#
# **與原案的一處落差（唯一真的偏離「整張底圖」的地方）**：官方只給了「原音呈現」
# 那一種小標的成品圖，「AI即時翻譯」沒有官方檔。若整塊貼官方圖，AI即時翻譯就只能
# 顯示錯字。改法：兩種小標狀態的 LIVE 章都直接貼官方裁切（一般版用一般檔、有小標
# 版用有小標檔的 LIVE 章那一段），但白底小標本身照舊由程式畫（沿用 2026-09-08 就有
# 的 rounded_rectangle＋文字），文字依 variant 換成「原音呈現」或「AI即時翻譯」。
# 這樣兩種小標走同一條路徑，行為對稱，也維持 B46 裁決的「LIVE 章與小標貼合無縫」。
#
# 版面（左緣版，右緣版整組水平鏡射，含底圖像素——漸層方向也要跟著翻，不能只搬位置）：
#   LIVE 章（＋原音呈現／AI即時翻譯白底小標）在最上面，底下接兩欄直排文字。
#   內側欄＝主標，字大；外側欄＝副標，字小。兩欄同寬（各佔色框寬的一半）、同一個
#   上緣、同一個下緣，字距＝共用欄高 ÷ 各自格數——格數多的那欄字自動變小。
#
# 直排是逐字疊放，不是把整行轉 90°：標點要換成直排相容字元（「→﹁、。→︒），
# 連續的英數字（AI／AMD／30）併成一格橫著寫（縱中橫），截圖裡就是這樣排的。
# ============================================================

VSTRIP_BG_NORMAL = BRAND_DIR / "yt-vstrip-live.png"
VSTRIP_BG_LABELLED = BRAND_DIR / "yt-vstrip-live-labelled.png"

# ---- 一般版（yt-vstrip-live.png，1914×1063）----
# 官方口頭量測給的是 LIVE 章與色框合在一起的外框（189×485 @31,171），但實測發現
# 色框本身其實比 LIVE 章窄、往內縮了一截——不是同一個左緣／寬度。本 session 逐列
# 逐欄用 PIL 掃過（沿 y=171..651 每隔 20 列取一次，四個 x 樣本互相印證），色框的
# 實心矩形是 48..201（寬 153），不是 31..220；LIVE 章本身（31..214，寬 184）與
# 官方數字一致，只有色框的左緣／寬度需要用這次量到的值，上緣／高度不變。
VSTRIP_BG_BADGE_LEFT_RATIO = 31 / 1914
VSTRIP_BG_BADGE_TOP_RATIO = 100 / 1063
VSTRIP_BG_BADGE_WIDTH_RATIO = 184 / 1914
VSTRIP_BG_BADGE_HEIGHT_RATIO = 71 / 1063
VSTRIP_BG_BOX_LEFT_RATIO = 48 / 1914
VSTRIP_BG_BOX_TOP_RATIO = 171 / 1063
VSTRIP_BG_BOX_WIDTH_RATIO = 153 / 1914
VSTRIP_BG_BOX_HEIGHT_RATIO = 485 / 1063

# ---- 有小標版（yt-vstrip-live-labelled.png，1905×1070）----
# 官方量測只給了 LIVE 章＋白底小標的合體框（194×146 @19,67，兩者貼合無縫，上緣／
# 高度可信、已用色差交叉驗證）。跟一般版同一個毛病：色框本身比合體框窄，本 session
# 另外掃了三塊各自的實心矩形（LIVE 章 20..203、白底小標 21..212、色框 37..191）。
# 合體框內部 LIVE／小標的切分點同樣是掃像素量的（紅色描邊在 y≈130 收尾、白底
# y≈130 開始）。白底小標本身不用官方像素畫（見上方模組註解的落差說明）。
VSTRIP_BG_LABELLED_BADGE_LEFT_RATIO = 20 / 1905
VSTRIP_BG_LABELLED_BADGE_WIDTH_RATIO = 183 / 1905
VSTRIP_BG_LABELLED_LABEL_LEFT_RATIO = 21 / 1905
VSTRIP_BG_LABELLED_LABEL_WIDTH_RATIO = 191 / 1905
VSTRIP_BG_LABELLED_BOX_LEFT_RATIO = 37 / 1905
VSTRIP_BG_LABELLED_BOX_WIDTH_RATIO = 154 / 1905
VSTRIP_BG_LABELLED_BADGE_TOP_RATIO = 67 / 1070
VSTRIP_BG_LABELLED_BADGE_HEIGHT_RATIO = (130 - 67) / 1070
VSTRIP_BG_LABELLED_LABEL_HEIGHT_RATIO = (213 - 130) / 1070
VSTRIP_BG_LABELLED_BOX_TOP_RATIO = 213 / 1070
VSTRIP_BG_LABELLED_BOX_HEIGHT_RATIO = 489 / 1070

VSTRIP_CELL_TIGHT = 0.92             # 字級佔格距（字距約 0.08em）
# 2026-09-20 使用者裁決：色框長度變常數後，字級下限是唯一防線——縮到這裡還放不下
# 就是 ComposeError，不准再縮。32px＝約 0.030×畫布高（1080p），數字怎麼來的：
# 色框可用高度從舊版上限 0.64h 砍到官方實測的 0.456h（見上方 VSTRIP_BG_*_HEIGHT_
# RATIO），副標上限 14 格是最擠的情況——492.8px÷14 格＝35.2px 格距×0.92＝32.4px，
# 四捨五入正好卡在 32px，一點餘裕都沒有，所以這條線不能再往上調。
VSTRIP_MIN_FONT_RATIO = 0.030
VSTRIP_MIN_PITCH_RATIO = VSTRIP_MIN_FONT_RATIO / VSTRIP_CELL_TIGHT   # 反推的格距下限
# 2026-09-20 使用者看過樣張後追加：**色框要貼著 LIVE 章（B46），但框裡的字不能貼**——
# 第一個字原本從色框最頂端起排，看起來直接黏在 LIVE 章下緣。這條是色框內的上內距，
# 只推文字、不動色框，所以 B46 的零縫不受影響。13px@1080，約等於字級下限的 0.4 個字高，
# 拉開得出來又不會吃掉太多可用長度。⚠**這段內距會從可用欄高扣掉**，等於字級下限更容易
# 撞到——計算 pitch 時一律用扣掉內距之後的 column_h，不要拿色框原高去算。
VSTRIP_TEXT_TOP_PAD_RATIO = 0.012
VSTRIP_TOP_GAP_RATIO = 0.014         # Logo 與色框最小淨距（同側下角時的防呆，見下方 same_side_bottom）
VSTRIP_LABEL_FILL = (255, 255, 255)
VSTRIP_LABEL_TEXT = (208, 20, 30)
VSTRIP_LABEL_BORDER = (208, 20, 30)
VSTRIP_SOURCE_SIZE_RATIO = 0.030     # 來源句字級
VSTRIP_SOURCE_GAP_RATIO = 0.014      # 來源句與 LIVE 章的距離（截圖就是貼著章排）
# 來源句落在 Logo 那一角時，與 Logo 的水平間距（2026-09-09 使用者：都選右下會黏在一起）。
# 舊做法是疊在 Logo 正上／正下、只隔 15px，左右範圍又完全重疊，看起來像 Logo 的說明文字；
# 左版還會撞到 LIVE 章（left/tl/tl 實測重疊）。改成排在 Logo 的「內側」同一列、垂直置中對齊。
VSTRIP_SOURCE_LOGO_GAP_RATIO = 0.018  # 佔畫面寬（＝Logo 自己的外緣留白，35px @1920）
# 2026-09-09 使用者：「畫面來源：」這幾個字改成自動補，使用者只填來源名。
# 已經以「畫面來源」開頭的就不再補（使用者習慣整句貼上，補兩次很醜）。
VSTRIP_SOURCE_PREFIX = "畫面來源："
VSTRIP_SOURCE_CORNERS = ("tl", "tr", "bl", "br")
VSTRIP_LOGO_WIDTH_RATIO = 0.105      # 白色字標寬
VSTRIP_LOGO_MARGIN_RATIO = 0.018
VSTRIP_VARIANTS = ("normal", "original_audio", "ai_translation")
VSTRIP_VARIANT_LABELS = {"original_audio": "原音呈現", "ai_translation": "AI即時翻譯"}
VSTRIP_CORNERS = ("tr", "tl", "br", "bl")
VSTRIP_SIDES = ("left", "right")
VSTRIP_MAIN_MAX_CELLS = 12           # 主標格數上限（規格）
VSTRIP_SUB_MAX_CELLS = 14            # 副標格數上限（規格）

# 直排相容標點（U+FE1x／FE3x／FE4x）。台北黑體 Bold 這些字都有真字形，逐字render
# 驗過不是豆腐；沒有的字才退回旋轉 90°，所以 _VERTICAL_ROTATE_FALLBACK 平常不會用到。
VERTICAL_PUNCTUATION = {
    "「": "﹁", "」": "﹂", "『": "﹃", "』": "﹄",
    "（": "︵", "）": "︶", "(": "︵", ")": "︶",
    "〔": "︹", "〕": "︺", "【": "︻", "】": "︼",
    "，": "︐", "、": "︑", "。": "︒", "：": "︓", "；": "︔",
    "！": "︕", "？": "︖", "…": "︙", "—": "︱", "─": "︱", "－": "︱",
}


def _vertical_cells(text: str) -> list[str]:
    """把一行字拆成直排的格子。連續英數字併成一格（縱中橫），標點換直排字形。

    「明早晚涼「中午仍破30度」」→ 明 早 晚 涼 ﹁ 中 午 仍 破 30 度 ﹂ ＝ 12 格。
    30 是一格不是兩格，字數上限要照格數算，不是照字元數。
    """
    cells: list[str] = []
    run = ""
    for ch in text:
        if ch.isascii() and ch.isalnum():
            run += ch
            continue
        if run:
            cells.append(run)
            run = ""
        if ch.isspace():
            continue
        cells.append(VERTICAL_PUNCTUATION.get(ch, ch))
    if run:
        cells.append(run)
    return cells


def _draw_vertical_cell(
    canvas: Image.Image, cell: str, box: tuple[int, int, int, int],
    font: ImageFont.FreeTypeFont, fill: tuple[int, int, int],
) -> None:
    """畫一格直排文字。box 是格子的 (x0, y0, x1, y1)。

    單字用 anchor="ma" 貼在格子頂端置中——**不能**拿 getbbox 把墨水置中，
    那會把 ﹁ 從它該待的右上角拖到格子正中間，直排標點就白換了。
    英數字串（縱中橫）橫著寫，寬度超過格寬就縮字級。
    """
    x0, y0, x1, _ = box
    centre = (x0 + x1) // 2
    if len(cell) > 1 or (cell.isascii() and cell.isalnum()):
        # 縱中橫：整串橫排塞進格寬
        size = font.size
        small = _font(size)
        while size > 8 and small.getbbox(cell)[2] > (x1 - x0):
            size -= 2
            small = _font(size)
        ImageDraw.Draw(canvas).text((centre, y0 + (font.size - small.size) // 2), cell,
                                    font=small, fill=fill, anchor="ma")
        return
    if cell not in VERTICAL_PUNCTUATION.values() and _is_tofu(cell, font):
        # 沒有直排字形才退回旋轉（台北黑體目前不會走到這條）
        patch = Image.new("RGBA", (font.size * 2, font.size * 2), (0, 0, 0, 0))
        ImageDraw.Draw(patch).text((font.size, font.size), cell, font=font, fill=fill + (255,), anchor="mm")
        patch = patch.rotate(-90, resample=Image.BICUBIC)
        canvas.alpha_composite(patch, (centre - font.size, y0))
        return
    ImageDraw.Draw(canvas).text((centre, y0), cell, font=font, fill=fill, anchor="ma")


def _is_tofu(ch: str, font: ImageFont.FreeTypeFont) -> bool:
    probe = Image.new("L", (font.size * 2, font.size * 2), 0)
    ImageDraw.Draw(probe).text((font.size // 4, font.size // 4), ch, font=font, fill=255)
    return probe.getbbox() is None


def _vstrip_rect(
    width: int, height: int, left_ratio: float, top: int, width_ratio: float, height_ratio: float,
) -> tuple[int, int, int, int]:
    """比例矩形換算成畫布像素座標。

    top 收的是**已經算好的像素 y0**，不是比例——這樣才能把 badge→label→box 串接成
    「上一塊的下緣＝下一塊的上緣」，零縫銜接。三塊各自的比例獨立四捨五入的話，官方
    素材原本貼合無縫的設計會被捨入誤差撬出 0～1px 的縫，B46 就是在修這個。
    """
    x0 = round(width * left_ratio)
    h = round(height * height_ratio)
    return (x0, top, x0 + round(width * width_ratio), top + h)


def _vstrip_mirror(rect: tuple[int, int, int, int], width: int) -> tuple[int, int, int, int]:
    """水平鏡射一個矩形：title_side="right" 時色框整組（含底圖像素）鏡射用。"""
    x0, y0, x1, y1 = rect
    return (width - x1, y0, width - x0, y1)


def vstrip_source_text(raw: str) -> str:
    """來源句正規化：使用者只填來源名，「畫面來源：」自動補上（2026-09-09 使用者要求）。

    已經以「畫面來源」開頭的原樣回傳——使用者習慣整句貼上，補兩次很醜。
    冪等：對同一個字串套幾次結果都一樣，所以 layout 與 compose 各自呼叫都安全。
    """
    text = (raw or "").strip()
    if not text or text.startswith("畫面來源"):
        return text
    return VSTRIP_SOURCE_PREFIX + text


def vstrip_source_corner(
    *, source_corner: str = "", logo_corner: str = "tr", title_side: str = "left",
    source_follow_logo: bool = False,
) -> str:
    """來源句實際落在哪個角。

    source_corner 空字串＝舊呼叫端（沒帶這個欄位）：沿用 source_follow_logo，
    True 跟 Logo、False 跟 LIVE 章。行為與 2026-09-08 逐字元相同。
    """
    if source_corner:
        if source_corner not in VSTRIP_SOURCE_CORNERS:
            raise ComposeError(
                f"source_corner 只能是 {'／'.join(VSTRIP_SOURCE_CORNERS)}，收到 {source_corner!r}"
            )
        return source_corner
    return logo_corner if source_follow_logo else ("tl" if title_side == "left" else "tr")


def yt_vertical_layout(
    *, main_title: str, sub_title: str = "", title_side: str = "left",
    variant: str = "normal", logo_corner: str = "tr", source_text: str = "",
    source_follow_logo: bool = False, source_corner: str = "",
) -> dict:
    """算出直標每一塊的矩形，不畫任何東西。

    2026-09-20（B80）改版：LIVE 章／色框改用官方底圖當固定層，box／live／label 的
    位置與尺寸是常數（見模組開頭 VSTRIP_BG_* 比例），不再由標題格數反推——反過來是
    字級要遷就固定的欄高。幾何跟畫圖仍然拆開，好驗「主標在內側」（兩欄都是深藍，
    像素分不出誰是誰）。
    """
    width, height = YT_CANVAS
    main_cells = _vertical_cells(main_title)
    sub_cells = _vertical_cells(sub_title)
    if not main_cells:
        raise ComposeError("直標至少要有第一標題")
    if len(main_cells) > VSTRIP_MAIN_MAX_CELLS:
        raise ComposeError(f"第一標題 {len(main_cells)} 格，超過上限 {VSTRIP_MAIN_MAX_CELLS} 格")
    if len(sub_cells) > VSTRIP_SUB_MAX_CELLS:
        raise ComposeError(f"第二標題 {len(sub_cells)} 格，超過上限 {VSTRIP_SUB_MAX_CELLS} 格")

    # badge→label→box 依序串接（見 _vstrip_rect 註解）：B46 裁決「沒勾小標時 LIVE 與
    # 標題要黏合」，一般版跟有小標版現在走同一條鏈，天生零縫，不用另外判斷要不要留白。
    labelled = variant in VSTRIP_VARIANT_LABELS
    if labelled:
        badge = _vstrip_rect(
            width, height, VSTRIP_BG_LABELLED_BADGE_LEFT_RATIO,
            round(height * VSTRIP_BG_LABELLED_BADGE_TOP_RATIO),
            VSTRIP_BG_LABELLED_BADGE_WIDTH_RATIO, VSTRIP_BG_LABELLED_BADGE_HEIGHT_RATIO,
        )
        label = _vstrip_rect(
            width, height, VSTRIP_BG_LABELLED_LABEL_LEFT_RATIO, badge[3],
            VSTRIP_BG_LABELLED_LABEL_WIDTH_RATIO, VSTRIP_BG_LABELLED_LABEL_HEIGHT_RATIO,
        )
        box = _vstrip_rect(
            width, height, VSTRIP_BG_LABELLED_BOX_LEFT_RATIO, label[3],
            VSTRIP_BG_LABELLED_BOX_WIDTH_RATIO, VSTRIP_BG_LABELLED_BOX_HEIGHT_RATIO,
        )
    else:
        badge = _vstrip_rect(
            width, height, VSTRIP_BG_BADGE_LEFT_RATIO, round(height * VSTRIP_BG_BADGE_TOP_RATIO),
            VSTRIP_BG_BADGE_WIDTH_RATIO, VSTRIP_BG_BADGE_HEIGHT_RATIO,
        )
        label = (0, 0, 0, 0)
        box = _vstrip_rect(
            width, height, VSTRIP_BG_BOX_LEFT_RATIO, badge[3],
            VSTRIP_BG_BOX_WIDTH_RATIO, VSTRIP_BG_BOX_HEIGHT_RATIO,
        )

    # Logo 跟色框素材無關，維持既有系統：四角可選、同側上角擋掉（見 compose_yt_overlay）。
    logo_w = round(width * VSTRIP_LOGO_WIDTH_RATIO)
    logo_margin = round(width * VSTRIP_LOGO_MARGIN_RATIO)
    with Image.open(TVBS_LOGO_WHITE) as logo_file:
        logo_h = round(logo_file.height * logo_w / logo_file.width)
    logo_x0 = width - logo_margin - logo_w if logo_corner in ("tr", "br") else logo_margin
    logo_y0 = logo_margin if logo_corner in ("tr", "tl") else height - logo_margin - logo_h
    logo = (logo_x0, logo_y0, logo_x0 + logo_w, logo_y0 + logo_h)

    # 色框長度是常數了（B80 裁決），不會再因為同側下角有 Logo 而縮短；在 1080p 下
    # 色框底緣（約 0.66h）離同側下角的 Logo（約 0.98h）還有一大截，理論上碰不到。
    # 留這道防呆只是不讓未來畫布尺寸或 Logo 邊界一改，兩者悄悄疊在一起卻沒人發現。
    same_side_bottom = logo_corner == ("bl" if title_side == "left" else "br")
    if same_side_bottom and box[3] + round(height * VSTRIP_TOP_GAP_RATIO) > logo_y0:
        raise ComposeError("Logo 與直標色框同側下角太近，請把 Logo 換到另一邊或另一個角")

    # 兩欄同字級（2026-09-08 裁決不變）：格距由格數多的那欄決定；欄高＝色框高度，
    # B80 起是常數，不再由格數反推——反過來是字級要遷就它，見下面的下限檢查。
    most = max(len(main_cells), len(sub_cells))
    # 文字從色框頂端往下讓一點，不要黏在 LIVE 章下緣（2026-09-20 使用者看樣張後指出）。
    # 色框本身不動，所以 B46 的零縫維持不變。
    text_top = box[1] + round(height * VSTRIP_TEXT_TOP_PAD_RATIO)
    column_h = box[3] - text_top
    pitch = column_h / most
    cell_size = max(1, round(pitch * VSTRIP_CELL_TIGHT))
    floor = round(height * VSTRIP_MIN_FONT_RATIO)
    if cell_size < floor:
        longer = "第一標題" if len(main_cells) >= len(sub_cells) else "第二標題"
        raise ComposeError(
            f"{longer} {most} 格，縮到字級下限（{floor}px）仍放不進固定色框"
            f"（欄高 {column_h}px），請縮短標題"
        )

    # 欄寬＝色框寬度對半分（兩欄同寬，2026-09-08 裁決不變）；色框寬度本身固定了，
    # 不再由字級反推。畫字那段仍有「欄寬 ×0.94」的保險上限，見 compose_yt_overlay。
    # 先在「原生（左緣）」座標算好主／副標哪一半，兩側共用同一個規則：色框自己的
    # 右半永遠是主標（比較靠畫面中央那一半）——鏡射成右緣版之後這個關係還是成立
    # （鏡射會把左右反過來，原生右半鏡射後變成新畫面的左半，一樣是比較靠中央那半）。
    half_w = (box[2] - box[0]) // 2
    sub = (box[0], text_top, box[0] + half_w, box[3])
    main = (box[0] + half_w, text_top, box[2], box[3])
    if not sub_cells:
        sub = (sub[0], sub[1], sub[0], sub[1])

    if title_side == "right":
        box = _vstrip_mirror(box, width)
        badge = _vstrip_mirror(badge, width)
        label = _vstrip_mirror(label, width) if labelled else (0, 0, 0, 0)
        main = _vstrip_mirror(main, width)
        sub = _vstrip_mirror(sub, width)
    live = badge

    source = (0, 0, 0, 0)
    source_text = vstrip_source_text(source_text)
    corner = vstrip_source_corner(
        source_corner=source_corner, logo_corner=logo_corner,
        title_side=title_side, source_follow_logo=source_follow_logo,
    )
    if source_text:
        font = _font(round(height * VSTRIP_SOURCE_SIZE_RATIO))
        src_w = font.getbbox(source_text)[2]
        src_h = round(height * VSTRIP_SOURCE_SIZE_RATIO * 1.3)
        gap = round(height * VSTRIP_SOURCE_GAP_RATIO)
        live_corner = "tl" if title_side == "left" else "tr"
        if corner == logo_corner:
            # 同一角：讓開 Logo（Logo 在上→句子在下、在下→在上）
            source = _vstrip_source_box_follow_logo(logo, logo_corner, src_w, src_h, gap)
        elif corner == live_corner:
            # LIVE 章那一角：貼在章旁邊（截圖的預設做法）
            source = _vstrip_source_box(live, logo, logo_corner, title_side, src_w, src_h, gap)
        else:
            source = _vstrip_source_box_corner(corner, src_w, src_h, logo_margin)

    return {"live": live, "label": label, "main": main, "sub": sub, "box": box,
            "source": source, "logo": logo, "main_cells": main_cells,
            "sub_cells": sub_cells, "column_height": column_h, "pitch": pitch,
            "cell_size": cell_size, "source_corner": corner}


def _vstrip_source_box(live, logo, logo_corner, title_side, src_w, src_h, gap):
    """來源句預設貼在 LIVE 章右側同一列（截圖就是這樣）；跟 Logo 模式另算。"""
    width, _ = YT_CANVAS
    if title_side == "left":
        x0 = live[2] + gap
    else:
        x0 = live[0] - gap - src_w
    y0 = live[1] + (live[3] - live[1] - src_h) // 2
    return (x0, y0, x0 + src_w, y0 + src_h)


def _vstrip_source_box_corner(corner, src_w, src_h, margin):
    """來源句自己佔一個空角落（既沒有 Logo 也沒有 LIVE 章）：貼著該角內縮 margin。"""
    width, height = YT_CANVAS
    x0 = margin if corner in ("tl", "bl") else width - margin - src_w
    y0 = margin if corner in ("tl", "tr") else height - margin - src_h
    return (x0, y0, x0 + src_w, y0 + src_h)


def _vstrip_source_box_follow_logo(logo, logo_corner, src_w, src_h, gap=None):
    """來源句與 Logo 同一角：排在 Logo 內側的同一列，垂直置中對齊。

    2026-09-09 使用者：「都選右下會黏在一起」。舊做法上下疊、只隔 15px 且左右完全重疊，
    像 Logo 的附屬說明；而且左版 Logo 在左上時句子會壓進 LIVE 章。改成往畫面中央讓開一個
    Logo 留白的寬度——Logo 位置一律不動（使用者指定），只動來源句。

    gap 參數保留給舊呼叫端，實際用 VSTRIP_SOURCE_LOGO_GAP_RATIO；傳進來的值忽略。
    """
    width, _ = YT_CANVAS
    pad = round(width * VSTRIP_SOURCE_LOGO_GAP_RATIO)
    if logo_corner in ("tr", "br"):      # Logo 靠右 → 句子往左讓
        x1 = logo[0] - pad
        x0 = x1 - src_w
    else:                                 # Logo 靠左 → 句子往右讓
        x0 = logo[2] + pad
        x1 = x0 + src_w
    y0 = logo[1] + (logo[3] - logo[1] - src_h) // 2
    return (x0, y0, x1, y0 + src_h)


def _vstrip_crop_native(
    asset: pathlib.Path, left_ratio: float, top_ratio: float, width_ratio: float, height_ratio: float,
) -> Image.Image:
    """依比例從官方底圖裁出一塊（LIVE 章或色框），比例是該圖自己的寬高當分母
    （見模組開頭的 VSTRIP_BG_* 註解）——不是先換算成畫布尺寸再裁。
    """
    with Image.open(asset) as source:
        img = source.convert("RGBA")
        w, h = img.size
        x0 = round(w * left_ratio)
        y0 = round(h * top_ratio)
        return img.crop((x0, y0, x0 + round(w * width_ratio), y0 + round(h * height_ratio)))


def _paste_vstrip_crop(
    canvas: Image.Image, crop: Image.Image, target_rect: tuple[int, int, int, int], *, flip: bool,
) -> None:
    """把裁好的官方底圖貼到畫布的 target_rect，等比縮放到目標尺寸。

    flip=True（title_side="right"）先水平鏡射裁片本身——色框的漸層方向要跟著翻，
    不能只搬位置，不然右緣版的亮暗邊會反過來貼在錯的那一側。
    """
    if flip:
        crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
    width = target_rect[2] - target_rect[0]
    height = target_rect[3] - target_rect[1]
    if width <= 0 or height <= 0:
        return
    canvas.alpha_composite(crop.resize((width, height), Image.LANCZOS), (target_rect[0], target_rect[1]))


def compose_yt_overlay(
    *,
    main_title: str,
    sub_title: str = "",
    source_text: str = "",
    variant: str = "normal",
    logo_corner: str = "tr",
    title_side: str = "left",
    source_follow_logo: bool = False,
    source_corner: str = "",
    logo_tab: bool = False,
    live: bool = True,
    size: tuple[int, int] = YT_CANVAS,
) -> bytes:
    """合成 YT 直播用的「直標」透明底 PNG，回傳 PNG bytes（RGBA，沒有底圖）。

    2026-09-20（B80）起 LIVE 章與色框是官方去背 PNG 當固定層（見模組開頭註解），
    程式只在上面疊直排文字、（有小標時的）白底小標文字、Logo 與來源句；不再由
    程式畫漸層色塊，所以拿掉了舊版的 fill 參數（沒有任何呼叫端傳過非預設值）。
    main_title 是主標（內側欄），sub_title 是副標（外側欄）；2026-09-08 起兩欄**同字級**
    （色框寬度對半分），字少的那欄早點結束。
    variant：normal／original_audio／ai_translation，後兩者在 LIVE 章下方多一枚白底小標
    ——official 檔只給了「原音呈現」那張成品圖，所以白底小標本身（含文字）仍是程式畫的，
    兩種文案走同一條路徑（見模組開頭「與原案的一處落差」）。
    source_text 只要填來源名（例「美聯社」），「畫面來源：」由 vstrip_source_text 自動補。
    source_corner 指定它落在哪一角（tl／tr／bl／br），空字串＝舊行為
    （source_follow_logo=True 跟 Logo、False 跟 LIVE 章）。同一角有 Logo 或 LIVE 章時
    自動讓開，不會打架。
    logo_tab=True 才畫 YT 封面那塊藍色斜標籤；預設是截圖裡的白色字標。

    size 目前只支援 1920×1080，其他尺寸直接擋掉而不是默默畫錯。
    """
    if variant not in VSTRIP_VARIANTS:
        raise ComposeError(f"variant 只能是 {'／'.join(VSTRIP_VARIANTS)}，收到 {variant!r}")
    if logo_corner not in VSTRIP_CORNERS:
        raise ComposeError(f"logo_corner 只能是 {'／'.join(VSTRIP_CORNERS)}，收到 {logo_corner!r}")
    if title_side not in VSTRIP_SIDES:
        raise ComposeError(f"title_side 只能是 left／right，收到 {title_side!r}")
    if tuple(size) != YT_CANVAS:
        raise ComposeError(f"直標目前只支援 {YT_CANVAS[0]}×{YT_CANVAS[1]}，收到 {size}")
    # 2026-09-09 使用者裁決：直標縮短之後，同一側的**下**角空出來了，左下／右下一律
    # 開放；同一側的**上**角仍然會壓在直標上（LIVE 章與色框頂都在那裡），照舊擋掉。
    # 下角的實際避讓由 yt_vertical_layout 夾住色框底緣負責，不是靠這裡放行就沒事。
    same_side_top = logo_corner == ("tl" if title_side == "left" else "tr")
    if same_side_top:
        raise ComposeError(
            f"Logo 放 {logo_corner} 會壓在 {title_side} 側的直標上，請把 Logo 換到另一邊"
        )

    width, height = YT_CANVAS
    layout = yt_vertical_layout(main_title=main_title, sub_title=sub_title,
                               title_side=title_side, variant=variant,
                               logo_corner=logo_corner, source_text=source_text,
                               source_follow_logo=source_follow_logo,
                               source_corner=source_corner)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    labelled = variant in VSTRIP_VARIANT_LABELS
    flip = title_side == "right"
    bg_asset = VSTRIP_BG_LABELLED if labelled else VSTRIP_BG_NORMAL

    # ---- 色框：官方去背 PNG 當固定層（B80），裁「原生（左緣）」座標再依 flip 鏡射 ----
    if labelled:
        box_crop = _vstrip_crop_native(
            bg_asset, VSTRIP_BG_LABELLED_BOX_LEFT_RATIO, VSTRIP_BG_LABELLED_BOX_TOP_RATIO,
            VSTRIP_BG_LABELLED_BOX_WIDTH_RATIO, VSTRIP_BG_LABELLED_BOX_HEIGHT_RATIO,
        )
    else:
        box_crop = _vstrip_crop_native(
            bg_asset, VSTRIP_BG_BOX_LEFT_RATIO, VSTRIP_BG_BOX_TOP_RATIO,
            VSTRIP_BG_BOX_WIDTH_RATIO, VSTRIP_BG_BOX_HEIGHT_RATIO,
        )
    _paste_vstrip_crop(canvas, box_crop, layout["box"], flip=flip)

    # ---- 兩欄文字：白字、同字級，不用封面那套重描邊＋陰影（那是壓照片用的，壓深藍會糊）----
    pitch = layout["pitch"]
    for key, cells in (("main", layout["main_cells"]), ("sub", layout["sub_cells"])):
        if not cells:
            continue
        x0, y0, x1, _ = layout[key]
        # 欄寬＝色框寬度對半分（B80 起固定），仍夾一次 0.94 上限當保險。
        size_px = min(layout["cell_size"], round((x1 - x0) * 0.94))
        font = _font(size_px)
        for index, cell in enumerate(cells):
            cell_y0 = y0 + round(index * pitch)
            _draw_vertical_cell(canvas, cell, (x0, cell_y0, x1, cell_y0 + round(pitch)),
                                font, (255, 255, 255))

    # ---- LIVE 章：一般版與有小標版分別裁自各自的官方檔（B80）----
    if live:
        if labelled:
            badge_crop = _vstrip_crop_native(
                bg_asset, VSTRIP_BG_LABELLED_BADGE_LEFT_RATIO, VSTRIP_BG_LABELLED_BADGE_TOP_RATIO,
                VSTRIP_BG_LABELLED_BADGE_WIDTH_RATIO, VSTRIP_BG_LABELLED_BADGE_HEIGHT_RATIO,
            )
        else:
            badge_crop = _vstrip_crop_native(
                bg_asset, VSTRIP_BG_BADGE_LEFT_RATIO, VSTRIP_BG_BADGE_TOP_RATIO,
                VSTRIP_BG_BADGE_WIDTH_RATIO, VSTRIP_BG_BADGE_HEIGHT_RATIO,
            )
        # LIVE 章不能鏡射：裡面的「LIVE」字樣與播放三角形是有方向性的內容，鏡射
        # 會變成鏡像文字（實測抓到：「LIVE」變成反字、播放鍵朝左）——只搬位置、
        # 不翻轉像素，跟舊版行為一致（舊版本來就沒有鏡射過 LIVE 章）。
        _paste_vstrip_crop(canvas, badge_crop, layout["live"], flip=False)

    # ---- 原音呈現／AI即時翻譯：白底、紅框、紅字（官方只給「原音呈現」成品圖，
    # 這塊仍是程式畫的，兩種文案同一條路徑——見模組開頭「與原案的一處落差」）----
    if variant in VSTRIP_VARIANT_LABELS:
        box = layout["label"]
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(box, radius=round(height * 0.008), fill=VSTRIP_LABEL_FILL,
                               outline=VSTRIP_LABEL_BORDER, width=max(2, round(height * 0.004)))
        text = VSTRIP_VARIANT_LABELS[variant]
        font = _fit_font(text, (box[2] - box[0]) - round(width * 0.008),
                         round((box[3] - box[1]) * 0.72), round((box[3] - box[1]) * 0.4))
        _draw_text(draw, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), text, font,
                   fill=VSTRIP_LABEL_TEXT, stroke_width=0, anchor="mm")

    # ---- Logo ----
    if logo_tab:
        canvas.alpha_composite(_logo_tab_layer())
    logo = layout["logo"]
    _paste_logo(canvas, (logo[0], logo[1]), logo[2] - logo[0])

    # ---- 來源句（「畫面來源：」自動補，見 vstrip_source_text）----
    source_text = vstrip_source_text(source_text)
    if source_text:
        font = _font(round(height * VSTRIP_SOURCE_SIZE_RATIO))
        box = layout["source"]
        _draw_text(ImageDraw.Draw(canvas), (box[0], box[1]), source_text, font,
                   fill=(255, 255, 255), stroke=YT_TITLE_STROKE,
                   stroke_width=max(3, round(height * 0.004)), anchor="la")

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()



# 多圖分切底圖（2026-09-06 使用者裁決：「原圖放置」附圖 2 張＝左右雙切、3 張＝三切，
# 分隔線用斜切＋白色細線，比照頻道「閃兵案第四波」與十點不一樣的畫法）。
YT_SPLIT_MAX_PANELS = 4   # 2026-09-13 使用者：4 格放寬（原 3）
YT_SPLIT_SLANT_RATIO = 0.05          # 斜切：分隔線頂端比底端偏右多少（佔畫面寬）
YT_SPLIT_LINE_RATIO = 0.0055         # 白色分隔線寬（6/1080）
YT_SPLIT_LINE_FILL = (255, 255, 255)


def split_backgrounds(images: list[bytes]) -> bytes:
    """把 2–3 張附圖斜切拼成一張 16:9 無文字底圖，回 PNG。

    每格各自 COVER 裁切（不變形、置中），格與格之間一道斜的白色細線。
    只給一張就等同 crop_background_16x9；超過上限只取前幾張，呼叫端自己提示。
    """
    images = list(images)[:YT_SPLIT_MAX_PANELS]
    if not images:
        raise ComposeError("分切底圖至少要一張附圖")
    if len(images) == 1:
        return crop_background_16x9(images[0])
    canvas = split_canvas(images, YT_CANVAS)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def split_canvas(images: list[bytes], size: tuple[int, int]) -> Image.Image:
    """斜切拼圖的核心：n 張圖依序左→右鋪滿 size，格間白色斜線，回 RGB Image。

    YT 直播封面與十點不一樣封面共用（兩者畫布都是 1920×1080）。
    """
    width, height = size
    n = len(images)
    slant = round(width * YT_SPLIT_SLANT_RATIO)
    line_w = max(2, round(height * YT_SPLIT_LINE_RATIO))
    scale = 4
    canvas = Image.new("RGB", (width, height), (0, 0, 0))

    def divider_x(i: int, y: int) -> float:
        """第 i 條分隔線（i=0 是左畫框、i=n 是右畫框）在高度 y 的 x 座標。"""
        if i == 0:
            return -slant
        if i == n:
            return width + slant
        centre = width * i / n
        return centre + slant / 2 - slant * (y / height)

    for k, raw in enumerate(images):
        x_left = min(divider_x(k, 0), divider_x(k, height))
        x_right = max(divider_x(k + 1, 0), divider_x(k + 1, height))
        panel_w = int(round(x_right - x_left))
        panel = _cover_panel(raw, (panel_w, height))
        mask = Image.new("L", (width * scale, height * scale), 0)
        ImageDraw.Draw(mask).polygon(
            [
                (divider_x(k, 0) * scale, 0),
                (divider_x(k + 1, 0) * scale, 0),
                (divider_x(k + 1, height) * scale, height * scale),
                (divider_x(k, height) * scale, height * scale),
            ],
            fill=255,
        )
        mask = mask.resize((width, height), Image.LANCZOS)
        layer = Image.new("RGB", (width, height), (0, 0, 0))
        layer.paste(panel, (int(round(x_left)), 0))
        canvas.paste(layer, (0, 0), mask)

    lines = Image.new("L", (width * scale, height * scale), 0)
    ld = ImageDraw.Draw(lines)
    for i in range(1, n):
        ld.line(
            [(divider_x(i, 0) * scale, 0), (divider_x(i, height) * scale, height * scale)],
            fill=255, width=line_w * scale,
        )
    lines = lines.resize((width, height), Image.LANCZOS)
    canvas.paste(Image.new("RGB", (width, height), YT_SPLIT_LINE_FILL), (0, 0), lines)
    return canvas


# B55 面積防呆門檻（2026-09-16 使用者裁決＋2026-09-16 擴充到 YT）：字帶／保護區以外
# 「有差異」的像素比例超過這個值，代表模型根本沒有只加標題，而是把整張照片（或保護區
# 以內的大半個場景）重畫了一次。**全版型共用同一個值，不准各版型自己調**——使用者要
# 先看過一輪實拍再統一調整，數字只在這裡改一次，其他地方一律引用它。
PHOTO_PROTECT_MAX_CHANGE_RATIO = 0.5


def _restore_outside_protected_boxes(
    base_img: Image.Image, ai_img: Image.Image, *,
    protect_boxes: list[tuple[int, int, int, int]],
    diff_threshold: int = 24,
    max_change_ratio: float = PHOTO_PROTECT_MAX_CHANGE_RATIO,
) -> Image.Image:
    """B55 的核心比對邏輯：protect_boxes（像素座標，聯集）以內永遠是 base；以外只在
    模型「真的畫了東西」（逐像素與 base 有差異）的地方才用模型像素，沒被動過的仍是
    base。可編輯區域（畫布扣掉 protect_boxes）裡有差異的像素比例超過
    max_change_ratio 就丟 ComposeError——這是被 `restore_photo_outside_title_band`
    （十點）與 `restore_yt_cover_photo`（YT 四版型）共用的底層函式，兩者只是給的
    protect_boxes 來源不同（前者是一條字帶、後者是量出來的固定元素 bbox 聯集）。
    """
    width, height = base_img.size

    # 逐通道差異取最大值（不是轉灰階平均）：某個顏色的字剛好跟底圖亮度接近時，
    # 灰階平均會把差異洗掉，漏掉那個顏色通道其實差很多的像素。
    diff_r, diff_g, diff_b = ImageChops.difference(base_img, ai_img).split()
    diff_max = ImageChops.lighter(ImageChops.lighter(diff_r, diff_g), diff_b)
    changed = diff_max.point(lambda p: 255 if p > diff_threshold else 0)

    protect_mask = Image.new("L", (width, height), 0)
    pd = ImageDraw.Draw(protect_mask)
    for box in protect_boxes:
        x0, y0, x1, y1 = box
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(width, x1), min(height, y1)
        if x1 > x0 and y1 > y0:
            pd.rectangle([x0, y0, x1, y1], fill=255)
    editable_mask = ImageChops.invert(protect_mask)
    editable_pixel_count = editable_mask.histogram()[255]
    mask = ImageChops.multiply(changed, editable_mask)

    if editable_pixel_count:
        changed_in_editable = mask.histogram()[255]
        change_ratio = changed_in_editable / editable_pixel_count
        if change_ratio > max_change_ratio:
            raise ComposeError(
                "生圖模型把原圖放置的照片改動範圍過大（"
                f"可編輯區域內 {change_ratio:.0%} 的像素被重畫，上限 {max_change_ratio:.0%}），"
                "已擋下這次生成——原圖放置規則是照片不能被重畫，只能改標題設計，請重試或降低標題創意等級"
            )

    return Image.composite(ai_img, base_img, mask)


def restore_photo_outside_title_band(
    base_png: bytes, ai_png: bytes, *, band_top_ratio: float, diff_threshold: int = 24,
    max_band_change_ratio: float = PHOTO_PROTECT_MAX_CHANGE_RATIO,
) -> bytes:
    """B55（2026-09-16 使用者裁決）：單張「原圖放置」＋AI 標題時，照片本身一個像素都
    不准動，只有標題設計可以變。生圖模型永遠是整張重畫，prompt 只是請求、不是保證
    （AI_TITLE_BASE_IMAGE_NOTE 已經寫到不能再死照樣被改），保證只能來自程式回貼。

    做法是「限定字帶＋差異遮罩＋面積防呆」三件事合起來，缺一都不夠：
    - 字帶（band_top_ratio 以上）是**硬邊界**——不管模型畫了什麼，一律強制還原成
      base，logo／人臉／示意圖那一帶不可能被模型的任何輸出污染，不靠比對結果。
      邊界用既有的 COVER_HEADER_RATIO／COVER_TITLE_TOP_CLEARANCE_RATIO 算，
      不手打座標數字。
    - 字帶以內只在模型「真的畫了東西」（與 base 逐像素有差異）的地方才採用模型
      像素，帶內沒被動過的像素仍是 base——不能整條帶都給模型的畫布替換掉，
      否則等於放行模型把底下的照片內容也重畫一次（字帶本來就佔照片下半，
      直接整帶採用模型輸出跟不設限沒兩樣）。
    - 面積防呆：見 PHOTO_PROTECT_MAX_CHANGE_RATIO 與 `_restore_outside_protected_boxes`。

    回傳一律是 base 尺寸的 PNG；ai_png 尺寸不同時等比縮放對齊（生圖模型偶爾會回
    比要求略大/略小的畫布，此時仍要能比對）。
    """
    base_img = Image.open(io.BytesIO(base_png)).convert("RGB")
    ai_img = Image.open(io.BytesIO(ai_png)).convert("RGB")
    if ai_img.size != base_img.size:
        ai_img = ai_img.resize(base_img.size, Image.LANCZOS)
    width, height = base_img.size
    band_top = round(height * band_top_ratio)
    protect_boxes = [(0, 0, width, band_top)] if band_top < height else []

    result = _restore_outside_protected_boxes(
        base_img, ai_img, protect_boxes=protect_boxes,
        diff_threshold=diff_threshold, max_change_ratio=max_band_change_ratio,
    )
    buffer = io.BytesIO()
    result.save(buffer, format="PNG")
    return buffer.getvalue()


def cover_title_band_top_ratio() -> float:
    """十點封面標題可落筆的最上緣（佔畫面高的比例），與 `_cover_title_vertical_cap`
    用同一組常數推導，供 B55 的字帶保護取用——不要另外手打一份數字。"""
    return COVER_HEADER_RATIO + COVER_TITLE_TOP_CLEARANCE_RATIO


# ============================================================
# B55 擴充到 YT 四版型（2026-09-16 使用者裁決）
#
# 十點的字帶是一條簡單的水平線（COVER_HEADER_RATIO 以上）；YT 四版型的固定元素
# 幾何差異很大（news／hot 是頂端一叢＋右側 AI 標；hourly 多一塊卡在畫面中段的日期
# 紅牌；live24 是左上角標＋右上兩層 Logo，還是斜體），硬湊一條共用的水平線不是
# 「切到 Logo」就是「保護過頭把標題該站的位置也鎖住」。
#
# 做法：**直接把真正的固定元素繪製函式在一張透明畫布上跑一次，量出實際碰到的
# 像素外框**（見 _render_fixed_elements_bbox）——不是拿比例常數湊出來的猜測，是
# 跟成品逐像素一致的量測。四個版型各自組出「這個版型會畫哪些固定元素」，共用
# 同一支測量器。
# ============================================================

def _render_fixed_elements_bbox(render) -> tuple[int, int, int, int]:
    """在一張全透明畫布上跑 render()，回傳非透明像素的外框（左上到右下，像素座標）。"""
    canvas = Image.new("RGBA", YT_CANVAS, (0, 0, 0, 0))
    render(canvas)
    bbox = canvas.getbbox()
    if bbox is None:
        raise ComposeError("B55 固定元素量測失敗：測量畫布上沒有任何像素，量測函式本身可能有誤")
    return bbox


def _fixed_element_boxes(*renders) -> list[tuple[int, int, int, int]]:
    """逐件量框，**不合併成一個 union**。畫不到任何東西的那件自動略過。

    2026-09-21 實證（dev 後台三張被第 b 道閘擋下的圖層，逐像素量過）：union bbox
    會把元件之間那一大片「其實什麼都沒畫」的空白一起鎖住。

        news   union (0, 0, 1920, 350)
               真正畫到東西的只有 頂線 (0,0,1920,24)、右上斜標籤 (1554,0,1920,165)、
               左側 LIVE 章那一叢 (50,54,486,350)
        live24 union (54, 49, 1855, 321)
               真正畫到東西的只有 左上角標 (54,49,649,321)、右上 Logo (1590,57,1855,202)

    三筆違規（live24 (1715,298,1767,322)／news (1648,320,1884,351)／
    news (1223,342,1398,351)）全部落在那些空白裡——模型畫的是標題自己的上緣，
    沒有壓到任何固定元素，卻因為落在 union 框內被判成竄改，整張退回程式壓字。
    被畫到的像素 73~82% 是 alpha 201 以上的實心筆畫，不是縮放毛邊。

    刻意**不**比照十點改成「丟棄不擋下」：十點那條標頭帶事後會被
    `paste_cover_header_band` 整條重畫，丟掉看不出來；YT 這幾塊空白事後不會被重畫，
    丟掉會在保護區下緣留一道橫切邊。縮框才是對的修法——框準了，第 b 道閘就只會在
    真正壓到固定元素時才響。

    兩條 provider 路徑共用這組框，語意也一致（框內一律是 base、模型不准貢獻），
    所以縮框對 gpt 的 alpha 閘與 gemini 的差異遮罩是同一個方向，不會一邊過一邊被抹掉。
    """
    boxes: list[tuple[int, int, int, int]] = []
    for render in renders:
        canvas = Image.new("RGBA", YT_CANVAS, (0, 0, 0, 0))
        render(canvas)
        bbox = canvas.getbbox()
        if bbox is not None:
            boxes.append(bbox)
    if not boxes:
        raise ComposeError("B55 固定元素量測失敗：測量畫布上沒有任何像素，量測函式本身可能有誤")
    return boxes


def _yt_news_or_hot_fixed_boxes(
    *, original_audio: bool, ai_translation: bool, ai_note: bool, hot_header: bool,
) -> list[tuple[int, int, int, int]]:
    """news（`compose_yt_cover`）與 hot（`compose_yt_hot_cover`）共用的頂端固定元素：
    頂線／Logo 斜標籤／LIVE 章或今日熱搜標籤／日期條／原音呈現／AI即時翻譯。

    2026-09-21 改為**逐件量框**（見 `_fixed_element_boxes` 的實證）：原本整叢量成
    一個 bbox，頂線把寬度撐到 0→1920、左側日期條把高度撐到 350，結果 (0,0,1920,350)
    這片裡有一大半是照片。三張被擋下的圖層違規處全都落在那片空白。

    AI示意圖是右側獨立一塊，本來就另外量、另外回傳。
    """
    width, height = YT_CANVAS
    margin = round(width * YT_MARGIN_RATIO)

    def render_header(canvas: Image.Image) -> None:
        if hot_header:
            _draw_hot_header(canvas)
        else:
            _draw_top_line(canvas)

    def render_logo_tab(canvas: Image.Image) -> None:
        # hot 版型沒有右上斜標籤（它的頁首是整條 hot header）
        if not hot_header:
            _draw_logo_tab(canvas)

    def render_left_cluster(canvas: Image.Image) -> None:
        # 左上那一叢（原音呈現標＋LIVE 章＋日期條＋AI即時翻譯標）彼此相連，
        # 量成一框是對的——它們在 x 方向本來就擠在 margin 附近。
        # hot 且沒有原音呈現時這件什麼都不畫，`_fixed_element_boxes` 會自動略過。
        draw = ImageDraw.Draw(canvas)
        top = round(height * (YT_TOP_WITH_LABEL_RATIO if original_audio else YT_TOP_RATIO))
        if original_audio:
            label_font = _font(round(height * YT_ORIGINAL_AUDIO_SIZE_RATIO))
            _draw_text(
                draw, (margin + round(width * 0.008), round(height * YT_ORIGINAL_AUDIO_BASELINE_RATIO)),
                YT_ORIGINAL_AUDIO_LABEL, label_font, fill=YT_ORIGINAL_AUDIO_FILL,
                stroke=YT_ORIGINAL_AUDIO_STROKE, stroke_width=max(4, round(height * 0.009)), anchor="ls",
            )
        if not hot_header:
            # hot 版型沒有 LIVE 章／日期條（今日熱搜沒有播出資訊，見模組開頭註解）
            badge_w = round(width * YT_BADGE_WIDTH_RATIO)
            badge_h = _paste_live_badge(canvas, (margin, top), badge_w)
            tab_w = round(width * YT_DATE_TAB_WIDTH_RATIO)
            tab_h = round(height * YT_DATE_TAB_HEIGHT_RATIO)
            tab_x0 = margin + (badge_w - tab_w) // 2
            tab_y0 = top + badge_h - 4
            tab_box = (tab_x0, tab_y0, tab_x0 + tab_w, tab_y0 + tab_h)
            ImageDraw.Draw(canvas).rectangle(tab_box, fill=(255, 255, 255, 255))
            if ai_translation:
                small = _font(round(height * YT_AI_TRANSLATION_SIZE_RATIO))
                _draw_text(
                    draw, (tab_box[0] + 6, tab_box[3] + round(height * YT_AI_TRANSLATION_GAP_RATIO)),
                    YT_AI_TRANSLATION_LABEL, small, stroke=YT_TITLE_STROKE, stroke_width=4, anchor="la",
                )

    boxes = _fixed_element_boxes(render_header, render_logo_tab, render_left_cluster)
    if ai_note:
        def render_ai_note(canvas: Image.Image) -> None:
            _draw_ai_note(canvas, round(height * YT_AI_NOTE_TOP_RATIO))
        boxes.append(_render_fixed_elements_bbox(render_ai_note))
    return boxes


def _yt_hourly_fixed_boxes(
    *, ai_note: bool, has_time: bool, include_date_tab: bool = True,
) -> list[tuple[int, int, int, int]]:
    """整點直播：左上小 Logo 與右上 LIVE 章（可能帶整點時間帶）**各自量框**；日期紅牌
    （YT_HOURLY_DATE_TAB_BOX）卡在畫面中段、跟頂端那叢中間隔了一大段照片，
    分開量、分開保護，不要為了保這塊牌把中段整條也鎖住。

    2026-09-21：左右兩件原本也是量成一個 bbox，中間那一整條照片跟著被鎖。
    理由與 news／live24 相同，見 `_fixed_element_boxes`。
    """
    width, height = YT_CANVAS
    margin = round(width * YT_MARGIN_RATIO)

    def render_logo(canvas: Image.Image) -> None:
        _paste_logo(canvas, (margin, round(height * YT_HOURLY_LOGO_TOP_RATIO)), round(width * YT_HOURLY_LOGO_WIDTH_RATIO))

    def render_badge(canvas: Image.Image) -> None:
        badge_w = round(width * YT_HOURLY_BADGE_WIDTH_RATIO)
        badge_x0 = width - margin - badge_w
        badge_top = round(height * YT_HOURLY_BADGE_TOP_RATIO)
        badge_h = _paste_live_badge(canvas, (badge_x0, badge_top), badge_w)
        block_bottom = badge_top + badge_h
        if has_time:
            band_h = round(height * YT_HOURLY_TIME_BAND_HEIGHT_RATIO)
            band_y0 = block_bottom - 6
            inset = round(badge_w * 0.04)
            band = (badge_x0 + inset, band_y0, badge_x0 + badge_w - inset, band_y0 + band_h)
            ImageDraw.Draw(canvas).rounded_rectangle(band, radius=12, fill=YT_HOURLY_TIME_BAND_FILL + (255,))

    boxes = _fixed_element_boxes(render_logo, render_badge)

    # 日期牌只有「程式自己畫」的時候才需要保護。創意 1 級起整個日期牌是**模型畫的**
    # （0911 使用者裁決，見 YT_HOURLY_DATE_TAB_BOX 上方的階梯說明），這時把這塊列為
    # 保護區等於一邊叫模型畫、一邊禁止它畫，是設計自相矛盾。
    #
    # 2026-09-21 實證：使用者三次 原圖放置＋AI 標題 全部擋在第 b 道閘，保護區被畫
    # 51,016／52,224／53,081 px，而後台歸檔的圖層看得很清楚——被畫到的只有這一塊，
    # 頁首帶與角標那兩塊完全是空的，模型畫的正是它被要求畫的日期條。
    if include_date_tab:
        date_box = YT_HOURLY_DATE_TAB_BOX
        boxes.append((
            round(width * date_box[0]), round(height * date_box[1]),
            round(width * date_box[2]), round(height * date_box[3]),
        ))

    if ai_note:
        def render_ai_note(canvas: Image.Image) -> None:
            _draw_ai_note(canvas, round(height * YT_HOURLY_AI_NOTE_TOP_RATIO))
        boxes.append(_render_fixed_elements_bbox(render_ai_note))
    return boxes


def _yt_live24_fixed_boxes(*, ai_note: bool) -> list[tuple[int, int, int, int]]:
    """24H LIVE：左上角標（含日期）＋右上兩層版 Logo，都貼在頂端；AI示意圖（只有
    is_ai 底圖才有，B55 這條路是真照片所以理論上不會開，量出來備用不吃虧）貼在
    角標正下方——跟 news/hourly 共用的右側版型不同，是 live24 自己的位置。

    2026-09-21：角標與 Logo 一左一右，原本量成一個 bbox（54,49,1855,321），中間
    那一整片照片跟著被鎖——22:24 那張被擋下的違規就落在 Logo 下方的空白
    （Logo 底部只到 y=202，違規在 y=298~322）。改為逐件量框，見 `_fixed_element_boxes`。
    """
    width, height = YT_CANVAS
    badge_w = round(width * LIVE24_BADGE_WIDTH_RATIO)
    badge_top = round(height * LIVE24_BADGE_TOP_RATIO)

    def render_badge(canvas: Image.Image) -> None:
        _paste_live24_badge(
            canvas, (round(width * LIVE24_BADGE_LEFT_RATIO), badge_top),
            badge_w, "00.00.00",  # 只是量測用的佔位日期字串，不影響外框大小（板子尺寸固定）
        )

    def render_logo(canvas: Image.Image) -> None:
        logo_w = round(width * LIVE24_LOGO_WIDTH_RATIO)
        logo_x = round(width * LIVE24_LOGO_RIGHT_RATIO) - logo_w
        if TVBS_LOGO_NEWS_WHITE.exists():
            with Image.open(TVBS_LOGO_NEWS_WHITE) as logo_file:
                logo = logo_file.convert("RGBA")
                logo = logo.resize((logo_w, round(logo.height * logo_w / logo.width)), Image.LANCZOS)
                canvas.alpha_composite(logo, (logo_x, round(height * LIVE24_LOGO_TOP_RATIO)))

    boxes = _fixed_element_boxes(render_badge, render_logo)
    if ai_note:
        # 角標正下方那一塊。位置要接在角標實際高度之後，所以這裡重量一次角標高度。
        measure = Image.new("RGBA", YT_CANVAS, (0, 0, 0, 0))
        badge_h = _paste_live24_badge(
            measure, (round(width * LIVE24_BADGE_LEFT_RATIO), badge_top), badge_w, "00.00.00",
        )

        def render_ai_note(canvas: Image.Image) -> None:
            _draw_live24_ai_note(canvas, badge_top + badge_h + 16)

        boxes.append(_render_fixed_elements_bbox(render_ai_note))
    return boxes


def yt_cover_protect_boxes(
    layout: str, *, original_audio: bool = False, ai_translation: bool = False, ai_note: bool = False,
    protect_date_tab: bool = True,
) -> list[tuple[int, int, int, int]]:
    """B55 YT 擴充：該 YT 封面版型固定元素實際占用的像素框（聯集），供
    `restore_yt_cover_photo` 當硬保護區。layout 用 editor_formats.YT_COVER_LAYOUT_*
    的字面值（"news"／"hourly"／"hot"／"live24"）——compose.py 不 import
    editor_formats（避免循環 import），所以這裡收字串、不收那個模組的常數物件。
    """
    if layout == "hourly":
        return _yt_hourly_fixed_boxes(
            ai_note=ai_note, has_time=True, include_date_tab=protect_date_tab,
        )
    if layout == "hot":
        return _yt_news_or_hot_fixed_boxes(
            original_audio=False, ai_translation=False, ai_note=ai_note, hot_header=True,
        )
    if layout == "live24":
        return _yt_live24_fixed_boxes(ai_note=ai_note)
    # news（YT_COVER_LAYOUT_NEWS）與任何未來新 layout 的保守預設：照 news 的頂端叢量
    return _yt_news_or_hot_fixed_boxes(
        original_audio=original_audio, ai_translation=ai_translation,
        ai_note=ai_note, hot_header=False,
    )


def restore_yt_cover_photo(
    base_png: bytes, ai_png: bytes, *, layout: str,
    original_audio: bool = False, ai_translation: bool = False, ai_note: bool = False,
    diff_threshold: int = 24, max_change_ratio: float = PHOTO_PROTECT_MAX_CHANGE_RATIO,
    protect_date_tab: bool = True,
) -> bytes:
    """B55 YT 擴充（2026-09-16 使用者裁決）：YT 封面單張「原圖放置」＋AI 標題時，
    照片本身一個像素都不准動，只有標題設計可以變——與十點滿版 `restore_photo_outside_
    title_band` 同一條規則，只是保護區換成 `yt_cover_protect_boxes()` 量出來的
    固定元素 bbox 聯集，而不是十點那條簡單的水平字帶。

    `protect_date_tab=False`：創意 1 級起日期牌由模型自己畫，這塊不再是保護區。
    跟 `overlay_title_layer_over_yt_cover` 的同名參數是同一件事，呼叫端要傳的條件
    也跟 `compose_yt_hourly_cover(draw_date=...)` 是同一個（2026-09-21 使用者裁決）。
    這條是 provider=gemini 的差異遮罩路徑；gpt 走的是 alpha 圖層那條。兩條路對
    日期牌的處置**必須一致**，不然換一家 provider 同一張圖就一邊過一邊被還原。

    回傳一律是 base 尺寸的 PNG；ai_png 尺寸不同時等比縮放對齊。
    """
    base_img = Image.open(io.BytesIO(base_png)).convert("RGB")
    ai_img = Image.open(io.BytesIO(ai_png)).convert("RGB")
    if ai_img.size != base_img.size:
        ai_img = ai_img.resize(base_img.size, Image.LANCZOS)

    protect_boxes = yt_cover_protect_boxes(
        layout, original_audio=original_audio, ai_translation=ai_translation, ai_note=ai_note,
        protect_date_tab=protect_date_tab,
    )
    result = _restore_outside_protected_boxes(
        base_img, ai_img, protect_boxes=protect_boxes,
        diff_threshold=diff_threshold, max_change_ratio=max_change_ratio,
    )
    buffer = io.BytesIO()
    result.save(buffer, format="PNG")
    return buffer.getvalue()


# ============================================================
# B55 修法甲（2026-09-20 使用者裁決，見帳本）：模型只產一張透明底的標題圖層，
# 程式疊到未經觸碰的原圖上。
#
# 跟上面 `_restore_outside_protected_boxes` 那條差異遮罩回貼是兩種不同的保證路徑：
# 差異遮罩靠「比對像不像」決定要不要還原成 base，門檻放在哪裡都是機率性的（2026-09-16
# 實拍量到十點滿版創意 0 級 change_ratio 就有 68.1%，等於這條路本來就形同擋死，見帳本
# B55 那列）。這裡的保證來自 **alpha 通道本身**：alpha=0 的像素定義上就是「模型完全
# 沒有動過」，疊圖時原封不動地漏出 base，不需要比對、不會有機率性的假陽性或假陰性。
#
# 代價：只有支援 `background: "transparent"` 的模型才畫得出乾淨的透明底（本 session
# 查證：openai/gpt-image-2.5-sunburst 有這個 enum；google/gemini-3-pro-image 沒有）。
# 呼叫端只在 provider=="gpt" 時才走這條路，gemini 維持原本的差異遮罩回貼不變。
#
# 三道閘缺一不可，任何一道沒過就丟 ComposeError，不悄悄降級成半套保證：
#   (a) 模型是不是真的回了透明底——alpha 全不透明代表模型忽略了 background=transparent
#       這個請求（prompt 只是請求，跟 AI_TITLE_BASE_IMAGE_NOTE 同一個教訓）。
#   (b) 保護區（頁首帶／Logo／角標這些程式後貼元素要用的位置）內 alpha 必須全為 0——
#       模型不准在那些區域畫任何東西，畫了代表要蓋掉程式後貼的內容。
#   (c) 面積防呆：可疊區域裡非透明像素比例超過門檻，代表模型畫的不是標題，是整片
#       半透明背景——見 TITLE_LAYER_MAX_PAINT_RATIO（2026-09-21 起自己一個數字，
#       不再借用 PHOTO_PROTECT_MAX_CHANGE_RATIO；借用是張冠李戴，見該常數的註解）。
# ============================================================

# alpha 判定的雜訊容忍：反鋸齒邊緣、JPEG-like 壓縮偽影會讓「理論上全透明」的像素
# 落在 1-15 之間，門檻抓在肉眼看不出差異、又能濾掉這類雜訊的位置。
TITLE_LAYER_ALPHA_THRESHOLD = 16
# 標題圖層「畫太少」的下限。第四道閘原本只擋「完全沒畫」，但只吐出幾十個像素殘渣的
# 圖層疊出來一樣是「幾乎沒有標題的原圖」。
#
# 2026-09-20 先裁 1%，2026-09-21 獨立複查（gpt-5.6-sol，第三輪）用實際字形量過之後
# **改判 0.1%**——1% 訂太高，會誤擋合法的短標題。量到的數字（可疊區＝畫布扣掉保護區，
# 十點滿版 1,833,600px、YT news 1,399,680px、hourly 1,533,936px、hot 1,708,800px、
# live24 1,581,654px）：
#   十點一字 9,143px＝0.50%／十點二字一行 18,145px＝0.99%／YT news 每行一字 0.98%
#   ——這三種都是合法輸入（`TenCoverRequest.title_left`、`YtCoverRequest.title`
#   都允許一字標題），在 1% 下全部會被誤擋。
#   細字重、無描邊的單字更低，約 3,464px＝0.19%。
#   正常長度的標題：十點兩行 5.91%、YT 4.83~13.46%，離下限很遠。
# 0.1% 的餘裕：十點門檻約 1,834px，最瘦的合法案例（0.19%）仍有約 1.9 倍；
# 測試用的 60×20 殘渣約 1,281px＝0.07%，仍然擋得住。
TITLE_LAYER_MIN_PAINT_RATIO = 0.001

# 標題圖層「畫太多」的上限（第 c 道閘）。
#
# 2026-09-20 這條沿用 PHOTO_PROTECT_MAX_CHANGE_RATIO（0.5），理由是「不另訂數字」。
# 2026-09-21 使用者實機測三次，三次都是可疊區 **52.0%／51.4%／56.3%**——全部卡在
# 50% 這條線上。看模型回傳的圖層（後台已歸檔，`20260921-1713~1715` 三筆）：那是
# 完全正常的透明底標題設計，滿版兩行大字＋裝飾，照片一個像素都沒碰。
#
# 借用 0.5 本來就是張冠李戴：PHOTO_PROTECT_MAX_CHANGE_RATIO 量的是「照片被改動的
# 比例」，改超過一半代表模型把照片重畫了；這裡量的是「標題圖層蓋住多少畫面」，
# 滿版標題設計蓋掉下半部是**預期行為**，不是事故。兩者不該共用一個數字。
#
# 2026-09-21 使用者裁決：放寬到 70%。實測三張 51~56% 留約 1.25 倍餘裕，而「整片
# 半透明背景」那種真正要擋的情況會逼近 100%，仍然擋得住。
#
# 2026-09-21 第二次裁決：**十點與 YT 拆成兩個數字**（使用者：「要拆 怕誤判」）。
#
# 拆的理由不是「兩邊用量不同」——當天後台八筆實測，兩邊的比例幾乎一樣
# （十點 28.7／32.5／40.3／56.5%，YT 整點 41.5／51.4／52.0／56.3%）。
# 真正的理由是**分母不同**：這道閘量的是「佔可疊區的比例」，而可疊區＝畫布扣掉
# 保護區，各版型差很多——
#     十點滿版 88.4%／hot 82.4%／live24 76.3%／hourly 74.0%／news 67.5%（佔畫面）
# 把實測值換算回「佔整張畫面」：十點 56.5%→50.0%、YT 整點 56.3%→41.7%。
# 也就是說**同一份設計放到 YT，因為分母小，算出來的比例天生偏高**，YT 那側會先
# 撞到天花板。誤判風險集中在 YT，所以 YT 要更多餘裕，不是兩邊各給一樣的數字。
#
# 十點 75%＝實測最高的 1.33 倍；YT 85%＝實測最高的 1.51 倍。
# 兩個數字都遠低於「模型整片畫背景」的實際表現（逼近 100%），該擋的照樣擋。
#
# 下次要調：後台的閘門訊息會印「可疊區內 XX% 的像素非透明」，拿被擋那一側的
# 實際分佈來改那一側，不要兩邊一起動——拆開就是為了這件事。
TITLE_LAYER_MAX_PAINT_RATIO_TEN = 0.75
TITLE_LAYER_MAX_PAINT_RATIO_YT = 0.85

# 舊名保留給「沒有指定是哪一側」的呼叫（`_overlay_title_layer_core` 的預設值）。
# 兩支對外的疊圖函式都各自傳明確的值進去，實務上不會落到這個預設。
TITLE_LAYER_MAX_PAINT_RATIO = TITLE_LAYER_MAX_PAINT_RATIO_TEN


# ============================================================
# B55 標題圖層高度上限（2026-09-22 使用者裁定）
# ============================================================
#
# 這一組跟上面那三個閘門常數**不是同一件事**：閘門是「擋下或放行」，這一組是
# 「放行、但先把圖層等比例縮到上限之內」。沒有任何一張會因為這組數字失敗。
#
# 為什麼不是再調 prompt：prompt 那根槓桿已經用盡，實測證據如下（dev 後台
# 2026-09-21 21:20~2026-09-22 00:54，全部是原圖放置＋AI 標題）：
#
#   十點 prompt 要 18/24/30/36%　→　實際畫出 45.0 / 50.0 / 61.0 / 69.0%
#   YT   prompt 要 32/36/40/44%　→　實際畫出 －／－／53.9 / 46.9~59.0%
#
# 十點**要得比 YT 少**（18–36 對 32–44），卻**畫得比 YT 多**（45–69 對 47–59）。
# 模型讀得到「標題要比內文大、L4 要比 L1 張揚」這種相對語氣，但不理會絕對百分比。
# 同一件事的第二個證據：0921 把裝飾配件從 DESIGN BRIEF 源頭整組拿掉之後，
# L4 從 88.4% 掉到 69.0%，L3 卻是 61.1% → 61.0%（動都沒動）。配件只解釋得了
# 最上面那一級的爬升，解釋不了 45–61% 這個底。
#
# 數字怎麼訂（2026-09-22 使用者裁定「壓縮階梯 44/46/48/50」）：拿使用者自己驗收過的
# 話當刻度——十點 L1 45.0%／L2 50.0% 是「偏高但可以接受」，L3 61.0%／L4 69.0% 是
# 「誇張、完全遮住原圖」；YT 46.9~59.0% 是「勉強可以接受的邊緣」。50% 正好落在
# 「可以接受」與「誇張」之間那條線上。保留 44/46/48 這三階是為了不把創意階梯的
# 高低差完全抹平——單一 50% 會讓 L2 L3 L4 一樣高。
#
# 這組數字**取代**了 COVER_TITLE_BRIEF_SPECS／YT_BRIEF_SPECS 裡那些塊高百分比的
# 實際作用。那些字串留在 prompt 裡沒有壞處（相對語氣仍然有效），但不要再把它們
# 當成成品會長成什麼樣的預測——上面的實測已經證偽了。
TITLE_LAYER_MAX_HEIGHT_RATIOS = {1: 0.44, 2: 0.46, 3: 0.48, 4: 0.50}

# 縮放下限（2026-09-22 使用者裁定 0.6）。超過這個倍率就不再往下縮，寧可讓那一張
# 仍然高於上限，也不要把字縮到看不清楚。只有極端個案會碰到：要縮到 0.6 倍代表
# 原圖層高度超過 73%（以 L4 的 50% 上限算），實測最極端的一張是 88.4%。
TITLE_LAYER_MIN_HEIGHT_SCALE = 0.60


def title_layer_max_height_ratio(level: int | None) -> float:
    """創意等級 → 圖層高度上限。表外的等級一律夾到 1~4 之間。

    夾而不是回 0（關閉）：漏傳或傳錯等級時應該套**最寬鬆**的那一階（L4 的 50%），
    而不是整個不設限——「不確定是哪一級」不是「這一張可以畫滿整個畫面」的理由。
    """
    if level is None:
        return TITLE_LAYER_MAX_HEIGHT_RATIOS[4]
    try:
        clamped = min(4, max(1, int(level)))
    except (TypeError, ValueError):
        return TITLE_LAYER_MAX_HEIGHT_RATIOS[4]
    return TITLE_LAYER_MAX_HEIGHT_RATIOS[clamped]


def _shrink_title_layer(
    layer_img: Image.Image, bbox: tuple[int, int, int, int], scale: float,
) -> Image.Image:
    """把整張圖層等比例縮小，並讓 `bbox` 的**底邊中點**留在原位。

    錨在底邊中點而不是畫布中心，也不是字帶上緣：
    - 底邊：標題一律坐在畫面下半部，底邊等於視覺上的基線。錨在上緣的話整條字帶會
      往上飄，錨在畫布中心的話會往中間飄——兩種都會把字推向照片主體。
    - 中點：左右一起內縮，字帶維持在原本的水平位置上；錨在左緣會整條往左偏。

    縮完之後靠近頂端的保護區（標頭帶、角標 Logo）只會離字更遠，但這**不是**構造上
    的保證——hourly 的日期牌在畫面中段，理論上有可能被往中間縮的像素碰到。所以
    呼叫端縮完一定要重量一次，這支函式只負責幾何。
    """
    width, height = layer_img.size
    scaled = layer_img.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS,
    )
    x0, _, x1, y1 = bbox
    anchor_x = (x0 + x1) / 2
    anchor_y = y1
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(scaled, (round(anchor_x - anchor_x * scale), round(anchor_y - anchor_y * scale)))
    return canvas


# ============================================================
# B55 診斷（2026-09-21，使用者實機驗收「四道閘太嚴格，嘗試都沒有成功」之後加）
#
# 為什麼要有這一段：0921 使用者連打四次 原圖放置＋AI 標題，四次全部被閘門擋下、
# 退回程式壓字，後台四筆成品的**位元組完全相同**（md5 `0f4d13e8…`）。
# 當時程式只把「哪一句錯誤訊息」印到 stdout，沒有留下任何量到的數字，也沒有留下
# 模型真正回傳的那張圖層——於是「是哪一道閘在擋、擋在多少、模型到底畫了什麼」
# 全部無從得知，只能猜。這一段就是把那些數字與那張圖留下來。
#
# 設計原則：**只量不判**。四道閘的判斷邏輯、門檻常數一個字都沒有動
# （`TITLE_LAYER_MIN_PAINT_RATIO`／`PHOTO_PROTECT_MAX_CHANGE_RATIO` 維持原值）——
# 診斷要能證明「開了診斷之後閘門行為完全不變」，否則它自己就變成新的變因。
# 對應的守門測試：tests/test_b55_transparent_title_layer.py 的
# TitleLayerDiagnosticsTests（逐案比對「有無診斷」兩種呼叫的結果與訊息）。
#
# 成功的時候也要記。只記失敗的話拿到的是被截斷的分布，永遠不知道「正常的標題圖層
# 畫多少比例」，也就永遠訂不出正確的門檻。
# ============================================================

class TitleLayerGateError(ComposeError):
    """四道閘擋下時丟這個，附帶當下量到的每一個數字。

    仍然是 `ComposeError` 的子類別——`main._compose_error_status` 與所有既有的
    `except compose.ComposeError` 呼叫端行為完全不變，只是多了 `.diagnostics`
    可以取用。"""

    def __init__(self, message: str, diagnostics: dict):
        super().__init__(message)
        self.diagnostics = dict(diagnostics)


def format_title_layer_diagnostics(diag: dict) -> str:
    """把診斷數字縮成一句給人看的話（進 `notices`，使用者當場就看得到）。

    刻意短：這句會接在閘門的錯誤訊息後面一起顯示，不是報表。完整數字在稽核歸檔的
    `title_layer_diag` 欄位裡，後台那一列會印出來。"""
    if not diag:
        return ""
    return (
        f"［診斷］擋下的是第 {diag.get('gate', '?')} 道閘"
        f"／alpha {diag.get('alpha_min', '?')}–{diag.get('alpha_max', '?')}"
        f"（門檻 {diag.get('alpha_threshold', '?')}）"
        f"／保護區被畫 {diag.get('protect_painted_pixels', '?')} px"
        + ("（已丟棄，不計失敗）" if diag.get("protect_discarded") else "")
        + f"／圖層高度佔畫面 {diag.get('painted_bbox_height_ratio', 0):.1%}"
        # 縮過的話兩個數字都要印：只印縮完的看不出模型本來畫多大，只印原始的
        # 又對不上成品。沒縮就不印，維持這句話的長度。
        + (
            f"（已縮 {diag['height_scale']:.2f}×，原"
            f" {diag.get('painted_bbox_height_ratio_before', 0):.1%}"
            f"、上限 {diag.get('max_height_ratio', 0):.0%}）"
            if diag.get("height_scale", 1.0) != 1.0 else ""
        )
        + f"／可疊區畫了 {diag.get('paint_ratio', 0):.3%}"
        f"（上限 {diag.get('max_paint_ratio', 0):.0%}、下限 {diag.get('min_paint_ratio', 0):.2%}）"
    )


def _stamp_title_layer_diag(
    diagnostics: dict | None, layer_raw_size: tuple[int, int],
    base_size: tuple[int, int], path: str,
) -> None:
    """補上核心函式量不到的兩件事：模型回傳的原始尺寸、以及走的是哪一條疊圖路徑。

    呼叫端放在 `finally` 裡——閘門擋下時也要有這兩欄，否則看到一筆失敗紀錄會分不出
    是「YT news 版型」還是「十點滿版」擋的。"""
    if diagnostics is None:
        return
    diagnostics["path"] = path
    diagnostics["layer_raw_size"] = f"{layer_raw_size[0]}x{layer_raw_size[1]}"
    diagnostics["layer_resized"] = layer_raw_size != base_size


def _measure_title_layer(
    base_img: Image.Image, layer_img: Image.Image, *,
    protect_boxes: list[tuple[int, int, int, int]],
    alpha_threshold: int,
) -> dict:
    """把四道閘要用到的每一個數字一次量完。**只量不判**，不丟任何例外。

    刻意在跑任何一道閘之前就全部量好：閘 (a) 本來會在算保護區之前就丟出去，
    那樣失敗筆就只剩 alpha 一個數字，拿到手也判不出是哪一種失敗。多量的成本是
    兩三次全畫布的 PIL 運算（2M 像素等級），相對於一次 20~30 秒的生圖呼叫可忽略。
    """
    width, height = base_img.size
    alpha = layer_img.split()[3]
    painted = alpha.point(lambda p: 255 if p > alpha_threshold else 0)
    alpha_min, alpha_max = alpha.getextrema()

    protect_mask = Image.new("L", (width, height), 0)
    pd = ImageDraw.Draw(protect_mask)
    for box in protect_boxes:
        x0, y0, x1, y1 = box
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(width, x1), min(height, y1)
        if x1 > x0 and y1 > y0:
            pd.rectangle([x0, y0, x1, y1], fill=255)

    protect_violation = ImageChops.multiply(painted, protect_mask)
    editable_mask = ImageChops.invert(protect_mask)
    editable_pixel_count = editable_mask.histogram()[255]
    painted_in_editable = ImageChops.multiply(painted, editable_mask)
    painted_in_editable_count = painted_in_editable.histogram()[255]
    paint_ratio = (
        painted_in_editable_count / editable_pixel_count if editable_pixel_count else 0.0
    )
    # 畫過的像素的外接框：整片背景會是接近全畫布的框，真正的標題是一條帶狀。
    # 光看比例分不出「一大塊半透明」與「散落各處的殘渣」，這個框分得出來。
    bbox = painted_in_editable.getbbox()
    # 框高佔畫面的比例（2026-09-21 補）：使用者回報「標題太大幾乎遮住整個版面」時，
    # 我得把成品下載下來逐列量才知道有多大。這個數字直接回答那個問題，而且能跟
    # prompt 裡的塊高規格（COVER_TITLE_BRIEF_SPECS／YT_BRIEF_SPECS）直接對照。
    # 面積比例答不了這題：滿版一行大字與散在各處的小元件可以是同一個百分比。
    bbox_height_ratio = (bbox[3] - bbox[1]) / height if bbox else 0.0

    return {
        "canvas": f"{width}x{height}",
        "alpha_min": alpha_min,
        "alpha_max": alpha_max,
        "alpha_threshold": alpha_threshold,
        "protect_box_count": len(protect_boxes),
        "protect_pixels": protect_mask.histogram()[255],
        "protect_painted_pixels": protect_violation.histogram()[255],
        "editable_pixels": editable_pixel_count,
        "painted_in_editable_pixels": painted_in_editable_count,
        "paint_ratio": paint_ratio,
        "painted_bbox": list(bbox) if bbox else [],
        "painted_bbox_height_ratio": bbox_height_ratio,
        # 下面兩個由 _overlay_title_layer_core 補上（門檻是它的參數）
        "max_paint_ratio": 0.0,
        "min_paint_ratio": 0.0,
        "gate": "",
        "verdict": "",
    }, painted, painted_in_editable, protect_violation, alpha


def _overlay_title_layer_core(
    base_img: Image.Image, layer_img: Image.Image, *,
    protect_boxes: list[tuple[int, int, int, int]],
    max_paint_ratio: float = TITLE_LAYER_MAX_PAINT_RATIO,
    min_paint_ratio: float = TITLE_LAYER_MIN_PAINT_RATIO,
    max_height_ratio: float = 0.0,
    alpha_threshold: int = TITLE_LAYER_ALPHA_THRESHOLD,
    discard_protect_paint: bool = False,
    diagnostics: dict | None = None,
) -> Image.Image:
    """四道閘＋疊圖的核心邏輯，在 PIL Image 層級操作。base_img 必須是 RGB，
    layer_img 必須是 RGBA（呼叫端負責轉檔與縮放對齊）。

    `diagnostics`：傳一個 dict 進來就會被原地填入量到的數字（見 `_measure_title_layer`）。
    不傳也完全正常運作——四道閘的判斷與訊息跟有沒有傳這個參數無關。

    `max_height_ratio`：圖層高度上限（B55，2026-09-22 使用者裁定）。**不是第五道閘**
    ——量到的高度超過它時不擋下，而是把整張圖層等比例縮到上限之內再疊。0 代表不縮。
    刻意排在四道閘**全部通過之後**才跑，而且縮完踩到保護區就退回那張沒縮的：
    這樣設計是為了讓這件事在構造上不可能把「原本會成功的一張」變成失敗。

    `discard_protect_paint=True`：閘 (b) 由「擋下」改成「丟掉」——保護區裡被畫過的
    像素不再是失敗條件，而是在疊圖前直接歸零。只有「prompt 自己叫模型畫那一塊」的
    路徑才可以開（見 `overlay_title_layer_over_cover_band`）。保護區提供的保證完全
    沒變：那一帶最後一樣是 base 原封不動漏出來。
    """
    diag, painted, painted_in_editable, protect_violation, alpha = _measure_title_layer(
        base_img, layer_img, protect_boxes=protect_boxes, alpha_threshold=alpha_threshold,
    )
    diag["max_paint_ratio"] = max_paint_ratio
    diag["min_paint_ratio"] = min_paint_ratio
    editable_pixel_count = diag["editable_pixels"]
    paint_ratio = diag["paint_ratio"]

    def _block(gate: str, message: str) -> TitleLayerGateError:
        diag["gate"] = gate
        diag["verdict"] = "blocked"
        if diagnostics is not None:
            diagnostics.clear()
            diagnostics.update(diag)
        return TitleLayerGateError(message, diag)

    # (a) 全不透明防呆：alpha 的最小值都超過門檻，代表整張圖沒有一個像素是透明的，
    # 模型沒有理會 background=transparent 這個請求。
    if diag["alpha_min"] > alpha_threshold:
        raise _block("a", (
            "生圖模型沒有回傳透明底的標題圖層（畫面完全不透明），已擋下這次生成——"
            "原圖放置規則要求模型只畫標題、其餘保持透明，請重試"
        ))

    # (b) 保護區內不准有任何被畫過的像素——這一道跟面積無關，一個像素都不許。
    diag["protect_discarded"] = bool(discard_protect_paint)
    if protect_violation.getbbox() is not None and not discard_protect_paint:
        raise _block("b", (
            "生圖模型在保留給程式後貼元素（頁首帶／Logo／角標）的區域畫了東西，"
            "已擋下這次生成——那一帶必須維持透明，請重試"
        ))

    # (c) 面積防呆：可疊區域（畫布扣掉保護區）裡畫了多大比例。
    if editable_pixel_count:
        if paint_ratio > max_paint_ratio:
            raise _block("c", (
                "生圖模型的標題圖層畫的範圍過大（"
                f"可疊區域內 {paint_ratio:.0%} 的像素非透明，上限 {max_paint_ratio:.0%}），"
                "已擋下這次生成——這代表模型畫的不是標題、是整片背景，請重試或降低標題創意等級"
            ))

    # (d) 空圖層防呆（2026-09-20 獨立複查補）：前三道全是「畫太多／畫錯地方」的上限，
    # 沒有任何一道管「畫太少」。模型回一張**完全透明**的圖時 (a) 的 alpha 最小值是 0、
    # (b) 沒有畫過的像素、(c) 比例 0——三道全過，程式會**成功回傳一張跟原圖一模一樣、
    # 一個字都沒有的成品**。那比擋下來更糟：400 使用者看得見，靜默的無字成品會直接
    # 被當成品拿去上鏡。
    # 2026-09-20 使用者裁定：下限訂 1%（`TITLE_LAYER_MIN_PAINT_RATIO`）。原本這一道
    # 只擋「完全沒畫」這個零歧義的情況，但**畫得極少**（只吐出幾十個像素的殘渣）
    # 同樣會產生近乎無字的成品。1% 這個數字的意義：一行大標題實際遠超過可疊區的 1%，
    # 所以它只擋得到殘渣，誤擋正常成品的機率極低。
    if painted_in_editable.getbbox() is None:
        raise _block("d-empty", (
            "生圖模型回傳的標題圖層是空的（整張完全透明，沒有畫任何標題），"
            "已擋下這次生成——照原樣疊圖只會得到一張沒有標題的原圖，請重試"
        ))
    if editable_pixel_count and paint_ratio < min_paint_ratio:
        raise _block("d-min", (
            "生圖模型的標題圖層幾乎是空的（"
            f"可疊區域內只有 {paint_ratio:.3%} 的像素被畫過，下限 {min_paint_ratio:.2%}），"
            "已擋下這次生成——疊出來會是一張幾乎沒有標題的原圖，請重試"
        ))

    diag["gate"] = ""
    diag["verdict"] = "pass"

    # ---- 高度上限：縮，不是擋（B55，2026-09-22 使用者裁定）----------------
    # 四道閘到這裡已經全過，以下任何一步不順都只是「維持原樣不縮」，不會失敗。
    diag["max_height_ratio"] = max_height_ratio
    diag["painted_bbox_height_ratio_before"] = diag["painted_bbox_height_ratio"]
    diag["height_scale"] = 1.0
    height_ratio = diag["painted_bbox_height_ratio"]
    if max_height_ratio and height_ratio > max_height_ratio and diag["painted_bbox"]:
        scale = max(max_height_ratio / height_ratio, TITLE_LAYER_MIN_HEIGHT_SCALE)
        shrunk = _shrink_title_layer(layer_img, tuple(diag["painted_bbox"]), scale)
        redo, re_painted, re_editable, re_violation, re_alpha = _measure_title_layer(
            base_img, shrunk, protect_boxes=protect_boxes, alpha_threshold=alpha_threshold,
        )
        # 縮完必須自己重過閘 (b) 與 (d)：
        # (b) 不是構造上安全的——hourly 的日期牌在畫面中段，往中心縮的像素碰得到它。
        # (d) 著色量隨 scale² 掉，原本就貼近下限的圖層縮完可能掉到下限以下。
        # (c) 不用重驗：縮完畫的只會更少，面積上限不可能由過變不過。
        safe_protect = discard_protect_paint or re_violation.getbbox() is None
        safe_paint = (
            re_editable.getbbox() is not None
            and (not diag["editable_pixels"] or redo["paint_ratio"] >= min_paint_ratio)
        )
        if safe_protect and safe_paint:
            layer_img, painted, painted_in_editable, alpha = (
                shrunk, re_painted, re_editable, re_alpha
            )
            # 診斷改報縮完的實際數字——後台那一列要回答的是「成品上的標題多高」，
            # 不是「模型本來想畫多高」。想畫多高留在 ..._before 那一欄。
            for key in (
                "protect_painted_pixels", "painted_in_editable_pixels",
                "paint_ratio", "painted_bbox", "painted_bbox_height_ratio",
            ):
                diag[key] = redo[key]
            diag["height_scale"] = scale
        else:
            # 縮完反而不合格：退回那張已經過閘的原圖層。寧可高一點也不要踩保護區
            # 或疊出一張幾乎沒字的成品。
            diag["height_scale_rejected"] = scale

    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update(diag)

    # 疊圖前先把「低於判定門檻」的 alpha 真的歸零（2026-09-20 獨立複查補）。
    # 三道閘一律用 painted（alpha > alpha_threshold）判定「這個像素模型有沒有畫」，
    # 但 alpha_composite 吃的是**原始 alpha**——兩邊標準不一致的話，一張全畫布
    # alpha=16 的薄層可以三道閘全過（處處「沒畫」），卻在疊圖時以 16/255 的比例
    # 把整張照片染色，**連保護區都染**（實測：紅底 (255,0,0) 疊上 (0,0,255,16)
    # 會變成 (239,0,16)）。這直接打破這條路唯一的賣點——「保證來自 alpha 通道，
    # alpha=0 的像素定義上就是模型沒動過」。
    # 低 alpha 不只出現在惡意情境：layer 尺寸與 base 不符時上面的 LANCZOS 縮放，
    # 本來就會在字的邊緣內插出一圈 1~15 的殘值。
    # 歸零後語意才真正對齊：三道閘認定「沒畫」的像素，疊圖時 base 原封不動漏出來。
    # discard_protect_paint 時用 painted_in_editable（painted ∩ 可疊區）當遮罩：
    # 保護區裡模型畫過的像素在這一步歸零，疊圖後那一帶仍是 base 原封不動。
    # 這就是閘 (b) 本來要保證的事，只是從「整張擋掉」換成「只丟那一塊」。
    cleaned = layer_img.copy()
    cleaned.putalpha(ImageChops.multiply(
        alpha, painted_in_editable if discard_protect_paint else painted
    ))

    result = base_img.convert("RGBA")
    result.alpha_composite(cleaned)
    return result.convert("RGB")


def overlay_title_layer_over_cover_band(
    base_png: bytes, layer_png: bytes, *, band_top_ratio: float,
    max_paint_ratio: float = TITLE_LAYER_MAX_PAINT_RATIO_TEN,
    max_height_ratio: float = 0.0,
    diagnostics: dict | None = None,
) -> bytes:
    """十點封面（滿版）版本：保護區是標頭帶（`cover_title_band_top_ratio()` 以上），
    跟 `restore_photo_outside_title_band` 保護的區域完全一樣，只是保證機制換成
    上面那組 alpha 三道閘。回傳一律是 base 尺寸的 PNG。"""
    base_img = Image.open(io.BytesIO(base_png)).convert("RGB")
    layer_img = Image.open(io.BytesIO(layer_png)).convert("RGBA")
    layer_raw_size = layer_img.size
    if layer_img.size != base_img.size:
        layer_img = layer_img.resize(base_img.size, Image.LANCZOS)
    width, height = base_img.size
    band_top = round(height * band_top_ratio)
    protect_boxes = [(0, 0, width, band_top)] if band_top < height else []
    # 保護區的保證維持不變（那一帶最後一定是 base 原封不動），但這條路的處置方式是
    # 「把模型畫在那裡的像素丟掉」而不是「整張退回程式壓字」。
    #
    # 2026-09-21 使用者回報的第二次誤判，dev 紀錄 `20260921-180313`：保護區被畫
    # 117304 px＝1920×61，正好是頂端一條實心帶。真因跟日期牌那件同一類的設計矛盾——
    # 十點的 prompt 模板自己寫著「Across the very top runs a deep-navy header band」，
    # 模型照做畫了帶，判定卻把它算成竄改原圖。而那一帶本來就會被程式整條蓋掉
    # （`main._cover_ai` 在疊完圖之後跑 `paste_cover_header_band`），模型畫在那裡的
    # 東西一個像素都不會出現在成品上：為了看不見的像素把整張退掉是純粹的誤擋。
    # 帶以下到字帶上緣那 11 px 的間隙不在程式重畫範圍內，丟掉一樣不會漏出來。
    try:
        result = _overlay_title_layer_core(
            base_img, layer_img, protect_boxes=protect_boxes,
            max_paint_ratio=max_paint_ratio, max_height_ratio=max_height_ratio,
            discard_protect_paint=True, diagnostics=diagnostics,
        )
    finally:
        # 模型回傳的原始尺寸要留下來：跟 base 不一致就代表疊圖前做過 LANCZOS 縮放，
        # 而縮放本來就會在字緣內插出 1~15 的殘值（見下方歸零那段）。失敗時也要記，
        # 所以放 finally。
        _stamp_title_layer_diag(diagnostics, layer_raw_size, base_img.size, "ten-cover")
    buffer = io.BytesIO()
    result.save(buffer, format="PNG")
    return buffer.getvalue()


def overlay_title_layer_over_yt_cover(
    base_png: bytes, layer_png: bytes, *, layout: str,
    original_audio: bool = False, ai_translation: bool = False, ai_note: bool = False,
    max_paint_ratio: float = TITLE_LAYER_MAX_PAINT_RATIO_YT,
    max_height_ratio: float = 0.0,
    protect_date_tab: bool = True,
    diagnostics: dict | None = None,
) -> bytes:
    """YT 四版型版本：保護區沿用 `yt_cover_protect_boxes()`，跟 `restore_yt_cover_photo`
    保護的區域完全一樣，只是保證機制換成 alpha 三道閘。回傳一律是 base 尺寸的 PNG。

    `protect_date_tab=False`：創意 1 級起日期牌由模型自己畫，這塊不再是保護區
    （2026-09-21 使用者裁決，見 `_yt_hourly_fixed_boxes`）。呼叫端要傳的條件跟
    `compose_yt_hourly_cover(draw_date=...)` 是同一個，兩邊不可以各自判斷。
    """
    base_img = Image.open(io.BytesIO(base_png)).convert("RGB")
    layer_img = Image.open(io.BytesIO(layer_png)).convert("RGBA")
    layer_raw_size = layer_img.size
    if layer_img.size != base_img.size:
        layer_img = layer_img.resize(base_img.size, Image.LANCZOS)
    protect_boxes = yt_cover_protect_boxes(
        layout, original_audio=original_audio, ai_translation=ai_translation, ai_note=ai_note,
        protect_date_tab=protect_date_tab,
    )
    try:
        result = _overlay_title_layer_core(
            base_img, layer_img, protect_boxes=protect_boxes,
            max_paint_ratio=max_paint_ratio, max_height_ratio=max_height_ratio,
            diagnostics=diagnostics,
        )
    finally:
        _stamp_title_layer_diag(
            diagnostics, layer_raw_size, base_img.size, f"yt-cover:{layout}",
        )
    buffer = io.BytesIO()
    result.save(buffer, format="PNG")
    return buffer.getvalue()


def crop_background_16x9(image_bytes: bytes) -> bytes:
    """把使用者附的原圖（任意比例）裁成 16:9 的無文字底圖，回 PNG。

    給「有 asis 附圖就不打生圖模型」那條路用：附圖本身就是底圖，只需要裁滿版面。
    """
    panel = _cover_panel(image_bytes, YT_CANVAS)
    buffer = io.BytesIO()
    panel.save(buffer, format="PNG")
    return buffer.getvalue()
