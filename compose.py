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
import unicodedata

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import safe_area_spec

BRAND_DIR = pathlib.Path(__file__).resolve().parent / "static" / "brand"
TVBS_LOGO_WHITE = BRAND_DIR / "tvbs-logo-white.png"
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
COVER_AI_HEADER_RATIO = 0.10          # prompt 寫「about one tenth」，貼圖以此為準
COVER_AI_LEFT_RATIO = 0.015


def paste_cover_logo(image_bytes: bytes) -> bytes:
    """在 AI 畫好的封面標頭帶左半貼上正版白色 Logo 與節目標籤模板。

    prompt 已明令模型不准畫任何電視台標誌／節目名、並把標頭帶左半留白（見
    editor_formats.COVER_AI_PROMPT_TEMPLATE）。就算模型沒聽話畫了東西，
    貼上去也會蓋掉——與播出鏡面挖空框同一個原則：不靠模型自律。
    """
    with Image.open(io.BytesIO(image_bytes)) as opened:
        canvas = opened.convert("RGBA")
    width, height = canvas.size
    band_h = round(height * COVER_AI_HEADER_RATIO)
    logo_h = max(1, round(band_h * 0.70))
    with Image.open(TVBS_LOGO_WHITE) as logo_file:
        logo_w = max(1, round(logo_h * logo_file.width / logo_file.height))
    logo_x = round(width * COVER_AI_LEFT_RATIO)
    _paste_logo(canvas, (logo_x, (band_h - logo_h) // 2), logo_w)
    tag_h = max(1, round(band_h * 0.80))
    _paste_template(canvas, TEN_SHOW_TAG, (logo_x + logo_w + round(width * 0.02), (band_h - tag_h) // 2), tag_h)

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
    # AI 版的標頭帶高由 prompt 決定（about one tenth），與合成版的 COVER_HEADER_RATIO 不同
    note_y = round(height * COVER_AI_HEADER_RATIO) + round(height * 0.025)
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
    _draw_cover_highlight_stamp(canvas)

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


def _draw_cover_highlight_stamp(canvas: Image.Image) -> None:
    """精華標籤：紅色刷筆模板，貼在標頭帶中段（水平置中、垂直置中於帶內）。

    2026-09-08 使用者兩次裁決：先是實測回報原本的深藍圓章跨在底部標題區上（TOP_RATIO 0.67）
    會壓到標題，接著把樣式整個換成紅色刷筆底＋白字的橫式標籤（TEN_HIGHLIGHT_TAG）。
    標頭帶只有左半與右端有東西，中段本來就空，兩邊都不打架。

    幾何以**傳進來的畫布**的尺寸為準，不是 COVER_CANVAS：純 AI 版直接貼在模型回來的
    原圖上，那張的解析度是模型決定的（2026-09-07 起 paste_cover_highlight_stamp 共用這支）。
    帶高一律用比例算（合成版 COVER_HEADER_RATIO、AI 版 COVER_AI_HEADER_RATIO 都是十分之一上下，
    這裡取合成版那個值，AI 版的圖也對得上）。
    """
    width, height = canvas.size
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
        _draw_text(draw, (badge_x1 - badge_w - round(width * 0.02), tag_y0 + tag_h // 2), date_text, date_font, stroke_width=0, anchor="rm")
    return band_h


def _draw_cover_ai_note(canvas: Image.Image, x_anchor: int, y0: int, align_right: bool) -> None:
    """格內「AI示意圖」小標（半透明黑底白字）。

    幾何一律以**傳進來的畫布**的高為準，不是 COVER_CANVAS：純 AI 版直接畫在模型
    回來的原圖上，那張的解析度是模型決定的（2026-09-07 起 paste_cover_ai_note 共用這支）。
    """
    height = canvas.size[1]
    font = _font(round(height * 0.03))
    text_w = font.getbbox(COVER_AI_NOTE)[2]
    pad = round(height * 0.012)
    note_h = round(height * 0.03 * 1.6)
    if align_right:
        x0, x1 = x_anchor - text_w - pad * 2, x_anchor
    else:
        x0, x1 = x_anchor, x_anchor + text_w + pad * 2
    plate = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle((x0, y0, x1, y0 + note_h), radius=6, fill=(0, 0, 0, 130))
    canvas.alpha_composite(plate)
    _draw_text(ImageDraw.Draw(canvas), ((x0 + x1) // 2, y0 + note_h // 2), COVER_AI_NOTE, font, stroke_width=0, anchor="mm")


# 拆行點偏好：切在「數量詞結尾」之後（5年｜各自…、184億元｜提升…），比純粹對半自然得多。
_SPLIT_AFTER_CHARS = set("年月日元億萬千人次件位家戶%％度歲倍")


def _split_line_near_middle(text: str) -> tuple[str, str]:
    """把一行從中間附近切成兩行。

    優先切在中點附近（±3 字）緊接數量詞結尾的位置；沒有就取最靠近中點、且不切在數字
    中間的位置（184億元 不能變 18／4億元）。
    """
    n = len(text)
    mid = n // 2
    for offset in range(0, 4):
        for i in (mid - offset, mid + offset):
            if 2 <= i <= n - 2 and text[i - 1] in _SPLIT_AFTER_CHARS and not text[i].isdigit():
                return text[:i], text[i:]
    for offset in range(0, n):
        for i in (mid + offset, mid - offset):
            if 1 <= i < n and not (text[i - 1].isdigit() and text[i].isdigit()):
                return text[:i], text[i:]
    return text[:mid], text[mid:]


def _wrap_pairs(pairs: list[tuple[str, int]], max_w: int, size: int, max_lines: int) -> list[tuple[str, int]]:
    """超寬防呆（2026-09-07）：在起始字級塞不進格寬的行，從中間切成兩行（最長的先切）。

    行帶著段落索引一起走（拆出來的兩行都繼承原本那一段的索引），只是那個索引現在
    **只記錄出處、不決定顏色**——2026-09-08 同日第二輪裁決把配色改回依行序。
    """
    pairs = list(pairs)
    font = _font(size)
    while len(pairs) < max_lines:
        widths = [font.getbbox(text)[2] for text, _ in pairs]
        idx = max(range(len(pairs)), key=widths.__getitem__)
        text, seg = pairs[idx]
        if widths[idx] <= max_w or len(text) < 4:
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
) -> bytes:
    """合成「十點不一樣」封面圖（2026-09-06 斜切全幅版）。

    兩張底圖（AI 生的或使用者原圖）斜切鋪滿，薄標頭帶、日期、標籤、兩邊多行標題
    全部由這裡畫。title_left／title_right 可用空白或換行自己分行（最多 3 行），
    沒分行且太長時由 split_cover_title 對切；哪一格是 AI 底圖才印「AI示意圖」。

    right_image 為 None＝單張全版（2026-09-06 使用者裁決：只上傳一張原圖就是整版鋪滿，
    不切左右格），兩個標題仍各自壓在左下與右下。
    """
    if badge not in COVER_BADGES:
        raise ComposeError(f"未知的標籤：{badge!r}（可用：{list(COVER_BADGES)}）")
    width, height = COVER_CANVAS
    mid = width // 2
    if right_image is None:
        canvas = _cover_panel(left_image, COVER_CANVAS).convert("RGBA")
        left_box = (0, 0, mid, height)
        right_box = (mid, 0, width, height)
        _shade_panel_bottom(canvas, (0, 0, width, height))
    else:
        canvas = split_canvas([left_image, right_image], COVER_CANVAS).convert("RGBA")
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
    if right_is_ai:
        _draw_cover_ai_note(canvas, width - COVER_MARGIN, note_y, align_right=True)

    _draw_cover_bottom_line(canvas)
    if right_image is None and not title_right.strip():
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
# 2026-09-08 使用者定版（三個位置樣張挑第 3 個「第二行」）：底帶從第一行字底（基線）開始
# 羽化，到第二行字的墨水上緣稍上（0.8145）才到全濃度——漸層剛好落在兩行標題之間的空隙，
# 不糊第一行、也不把第二行切成兩截。原本 0.60／0.06 把照片下半整片吃掉。
YT_BAND_TOP_RATIO = 0.778            # 底帶起點＝第一行基線（YT_LINE1_BASELINE_RATIO）
YT_BAND_FADE_RATIO = 0.0365          # 上緣羽化高度：0.778 + 0.0365 = 0.8145 到全濃度
YT_BAND_FILL = (8, 25, 70)
# 2026-09-08 使用者裁決：底部壓色框改成開關（預設 OFF），開的時候要半透明——
# 原本 205／255 ≈ 80% 幾乎把照片下半整片吃掉。153／255 = 60%。
YT_BAND_ALPHA = 153
YT_BAND_BLOCK_FILL = (60, 130, 230)
# 2026-09-08 使用者回饋「字體再粗一點、行距略縮」（國內外新聞直播與今日熱搜共用這組）：
# 行距 0.194 → 0.180（縮約 7%），第二行貼底不動、第一行往下靠；
# 加粗用「同色描邊」做假粗體（字型檔只有台北黑體 Bold 一個字重，沒有更粗的可換）。
YT_LINE1_BASELINE_RATIO = 0.778      # 第一行字底
YT_LINE2_BASELINE_RATIO = 0.958      # 第二行字底
YT_TITLE_SIZE_RATIO = 0.145          # 標題起始字級（字高約 100/720）
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
    draw_titles: bool = True,
    bottom_band: bool = True,
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
YT_HOURLY_LINE1_BASELINE_RATIO = 0.815   # 2026-09-08 晚使用者「行距可略縮」：0.80→0.815（第二行不動）
YT_HOURLY_LINE2_BASELINE_RATIO = 0.965
YT_HOURLY_TITLE_SIZE_RATIO = 0.15       # 字高 32/220
YT_HOURLY_AI_NOTE_TOP_RATIO = 0.34      # LIVE 章（含時間帶）之下的右側空位
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
    draw_titles: bool = True,
    line_max_chars: int | None = None,
) -> bytes:
    """合成 YT 整點直播封面。time_text（如 20:00）選填，有填才在 LIVE 章下掛時間帶。

    draw_titles=False：標題已由模型畫在 background 上，這裡只貼固定元素。

    line_max_chars（2026-09-08 WP2）：每行字數上限，超過就報錯。給「雙則」用——
    那個模式的兩行各是一則新聞的完整標題，不是同一句拆兩段，長度沒有天然上限。
    單則模式不帶這個參數，維持原行為。
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


# ---- 左右兩張底圖的羽化拼接（2026-09-08 WP2）----
#
# 整點「雙則」的底圖是兩則新聞各一張，但標題是橫跨全寬的兩整行——中間若有 split_canvas
# 那種白色硬邊（或斜切），線會從標題字中間穿過去，兩者互相打架。使用者給的真實封面上
# 兩張圖是「柔和的深色漸層帶」接起來的，看不到任何直線，所以這裡走 alpha 漸融：
# 中線兩側各一段寬羽化，接縫再疊一層很淡的深色暈讓過渡自然。
YT_SEAM_FEATHER_RATIO = 0.07     # 羽化半寬佔畫面寬（中線兩側各 7%，使用者說 6–8%）
YT_SEAM_SHADE_ALPHA = 56         # 接縫深色暈的最深值（56/255 ≈ 22%，使用者上限 25%）
YT_SEAM_CENTRE_RATIO = 0.5       # 接縫中心，預設正中


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

    seam_ratio＝接縫中心佔畫面寬，預設正中（0.5），限 0.35–0.65。使用者範例裡接縫偏左
    是因為右圖主體剛好擋到才挪的，屬個案微調，所以留成參數但 API／UI 先不暴露。

    每一格各自 COVER 裁切到「自己那半再加上羽化帶」的尺寸（不變形）；羽化用 smoothstep
    而不是線性，線性的兩端會留下看得出來的折線。
    """
    if not 0.35 <= seam_ratio <= 0.65:
        raise ComposeError(f"接縫位置要在 0.35–0.65 之間：{seam_ratio}")
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
    draw_titles: bool = True,
    bottom_band: bool = True,
    band_top_ratio: float | None = None,
    band_fade_ratio: float | None = None,
) -> bytes:
    """合成 YT「今日熱搜」封面：紅色系標頭、無日期無 LIVE，底部兩行標題。

    draw_titles=False（標題由 AI 生成）：background 已含標題與底帶，只貼固定元素。
    bottom_band（2026-09-08 使用者裁決，預設關）：底部深紅壓色框，開關與透明度同新聞版。
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
# YT 直播「直標」PNG 壓標（2026-09-08 WP3 第二版，計畫書 E 段）
#
# 第一版做成底部橫向標題條，是誤讀規格：使用者說的「直標」是**垂直**的標題條。
# 這一版全部依兩張真實播出截圖重量：
#   D:\Downloads\20260908_直標參考_一般國內直播.png（718×404）
#   D:\Downloads\20260908_直標參考_原音呈現.png（721×404）
#
# 版面（左緣版，右緣版整組鏡射）：
#   LIVE 章（＋原音呈現／AI即時翻譯白底小標）壓在最上面，底下接兩欄直排文字。
#   內側欄＝主標，字大、欄寬；外側欄＝副標，字小、欄窄。兩欄**同一個上緣、同一個
#   下緣**，各自的字距＝共用欄高 ÷ 自己的格數——所以格數多的那欄字自動變小。
#   這是量出來的：ref1 兩欄都是 y 67→358，主標 9 格、副標 12 格，格距 8.0%／6.0%。
#
# 兩件跟直覺不一樣、但截圖就是這樣的事：
#   1. 兩欄都是深藍，沒有紅欄。ref1／ref2 取色外側 (28,53,99)、內側 (27,41,74)；
#      2026-09-08 使用者裁決兩欄同底色、同一塊色框，統一用內側那個色（fill 參數）。
#   2. 右上角是白色 TVBS NEWS 字標，不是 YT 封面那塊藍色斜標籤（logo_tab 參數）。
#
# 直排是逐字疊放，不是把整行轉 90°：標點要換成直排相容字元（「→﹁、。→︒），
# 連續的英數字（AI／AMD／30）併成一格橫著寫（縱中橫），截圖裡就是這樣排的。
# ============================================================

VSTRIP_LEFT_RATIO = 0.0265           # 整組直標離畫面外緣（19/718）
# 2026-09-08 使用者裁決：兩欄字級一樣大、底色一致、同一個色框不拆開——
# 所以兩欄同寬（都用主標欄寬）、中間沒有縫、共用一個格距，底色是一整塊。
# 2026-09-09 使用者回饋：整組直標太長、上下都貼邊，要縮短、字級再縮小、兩行之間的
# 行距也縮小，整體置中偏上。
#   - 欄寬本來是固定比例（0.0445w≈85px），字級卻是由格距算的，兩者脫鉤——字級一縮，
#     欄寬不動，兩行之間的空白反而變大。改成由字級推導（VSTRIP_COLUMN_WIDTH_EM），
#     字級縮 → 欄寬縮 → 行距自動變窄。舊常數留著給還在用它的呼叫端當參考值。
#   - 上緣本來釘死在 VSTRIP_TOP_RATIO 往下長，長標題就一路長到 BOTTOM_MAX 貼邊。
#     改成先算出色框長度，再用 VSTRIP_VERTICAL_ANCHOR 在可用範圍內置中偏上。
VSTRIP_COLUMN_WIDTH_EM = 1.12        # 欄寬＝字級 × 這個值（字左右各留一點）
VSTRIP_MAIN_WIDTH_RATIO = 0.0445     # 舊的固定欄寬（32/718）；現在只當參考值
VSTRIP_SUB_WIDTH_RATIO = VSTRIP_MAIN_WIDTH_RATIO
VSTRIP_SEAM_RATIO = 0.0              # 兩欄之間不留縫：同一個色框
VSTRIP_TOP_RATIO = 0.166             # 色框可用範圍的上緣，一般版（67/404）
VSTRIP_TOP_WITH_LABEL_RATIO = 0.191  # 有原音呈現／AI即時翻譯小標時（77/404）
VSTRIP_TOP_GAP_RATIO = 0.014         # 色框上緣與 LIVE 章／小標底之間至少留這麼多（2026-09-08 使用者：頂上的字快被吃掉）
VSTRIP_BOTTOM_MAX_RATIO = 0.94       # 可用範圍的下緣（不是實際長度，2026-09-09 起色框在範圍內浮動）
VSTRIP_VERTICAL_ANCHOR = 0.38        # 色框在可用範圍裡的位置：0＝貼上緣、1＝貼下緣，置中偏上
# 色框總長度的硬上限（佔畫布高）。光縮格距擋不住最長的標題：14 格 × 0.070 = 0.98h，
# 一定會被可用範圍夾成「從上緣長到下緣」，也就是使用者說的「上下都貼邊」。
# 直接封住總長度，格距與字級再由它反推，長標題才會真的變短。
VSTRIP_COLUMN_MAX_RATIO = 0.64
VSTRIP_MAIN_PITCH_RATIO = 0.070      # 格距上限（2026-09-09 由 0.080 縮小），兩欄共用
VSTRIP_SUB_PITCH_RATIO = VSTRIP_MAIN_PITCH_RATIO
VSTRIP_MIN_PITCH_RATIO = 0.040       # 縮到這裡還放不下就丟 ComposeError（2026-09-09 隨總長度上限一起下修）
VSTRIP_CELL_TIGHT = 0.92             # 字級佔格距（字距約 0.08em）
VSTRIP_MAIN_FILL = (27, 41, 74)      # 整塊色框：深藏青（截圖取色）
VSTRIP_SUB_FILL = VSTRIP_MAIN_FILL   # 2026-09-08 起兩欄同色（保留名字給舊呼叫）
VSTRIP_FILL_SHADE = 0.78             # 欄內由外而內的漸層，模擬截圖的漸層感
VSTRIP_LIVE_TOP_RATIO = 0.104        # LIVE 章上緣，一般版（42/404）
VSTRIP_LIVE_TOP_WITH_LABEL_RATIO = 0.057   # 有小標時 LIVE 往上讓（23/404）
VSTRIP_LIVE_WIDTH_RATIO = 0.0877     # LIVE 章寬（63/718）
VSTRIP_LABEL_HEIGHT_RATIO = 0.069    # 白底小標高（28/404）
VSTRIP_LABEL_WIDTH_RATIO = 0.0905    # 白底小標寬（65/718）
VSTRIP_LABEL_FILL = (255, 255, 255)
VSTRIP_LABEL_TEXT = (208, 20, 30)
VSTRIP_LABEL_BORDER = (208, 20, 30)
VSTRIP_SOURCE_SIZE_RATIO = 0.030     # 來源句字級
VSTRIP_SOURCE_GAP_RATIO = 0.014      # 來源句與 LIVE 章／Logo 的距離
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


def _vertical_column_layer(size: tuple[int, int], fill: tuple[int, int, int], outward: bool) -> Image.Image:
    """一欄的底色：由外緣往內做一道很淡的漸層，貼近截圖的漸層感。"""
    width, height = size
    column = Image.new("RGBA", size)
    draw = ImageDraw.Draw(column)
    dark = tuple(round(c * VSTRIP_FILL_SHADE) for c in fill)
    for x in range(width):
        t = (x / max(1, width - 1)) if outward else (1 - x / max(1, width - 1))
        colour = tuple(round(fill[i] + (dark[i] - fill[i]) * t) for i in range(3))
        draw.line(((x, 0), (x, height)), fill=colour + (255,))
    return column


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

    幾何跟畫圖拆開才驗得到「主標在內側」——兩欄都是深藍，用像素分不出誰是誰。
    回傳 live／label／main／sub／source／logo 的 (x0, y0, x1, y1)，以及兩欄的格數與格距。
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

    labelled = variant in VSTRIP_VARIANT_LABELS
    band_top = round(height * (VSTRIP_TOP_WITH_LABEL_RATIO if labelled else VSTRIP_TOP_RATIO))
    # LIVE 章（與小標）先算高度：色框上緣不准貼到它們，至少隔 VSTRIP_TOP_GAP_RATIO
    live_top = round(height * (VSTRIP_LIVE_TOP_WITH_LABEL_RATIO if labelled
                               else VSTRIP_LIVE_TOP_RATIO))
    with Image.open(LIVE_BADGE) as badge:
        live_h = round(badge.height * round(width * VSTRIP_LIVE_WIDTH_RATIO) / badge.width)
    stack_bottom = live_top + live_h + (round(height * VSTRIP_LABEL_HEIGHT_RATIO) if labelled else 0)
    band_top = max(band_top, stack_bottom + round(height * VSTRIP_TOP_GAP_RATIO))

    # Logo 要先算：同側下角時色框底緣得讓開它（2026-09-09 放寬下角同側之後的必要條件）
    logo_w = round(width * VSTRIP_LOGO_WIDTH_RATIO)
    logo_margin = round(width * VSTRIP_LOGO_MARGIN_RATIO)
    with Image.open(TVBS_LOGO_WHITE) as logo_file:
        logo_h = round(logo_file.height * logo_w / logo_file.width)
    logo_x0 = width - logo_margin - logo_w if logo_corner in ("tr", "br") else logo_margin
    logo_y0 = logo_margin if logo_corner in ("tr", "tl") else height - logo_margin - logo_h
    logo = (logo_x0, logo_y0, logo_x0 + logo_w, logo_y0 + logo_h)

    band_bottom = round(height * VSTRIP_BOTTOM_MAX_RATIO)
    same_side_bottom = logo_corner == ("bl" if title_side == "left" else "br")
    if same_side_bottom:
        band_bottom = min(band_bottom, logo_y0 - round(height * VSTRIP_TOP_GAP_RATIO))

    # 兩欄同字級（2026-09-08 裁決）：格距由格數多的那欄決定，另一欄用同一個格距、
    # 字少就早點結束；欄高＝格數多的那欄的長度（色框是一整塊，高度取這個）。
    most = max(len(main_cells), len(sub_cells))
    wanted = min(most * height * VSTRIP_MAIN_PITCH_RATIO, height * VSTRIP_COLUMN_MAX_RATIO)
    column_h = round(min(wanted, band_bottom - band_top))
    pitch = column_h / most
    if pitch < height * VSTRIP_MIN_PITCH_RATIO:
        longer = "第一標題" if len(main_cells) >= len(sub_cells) else "第二標題"
        hint = "（Logo 放在同一側的下角壓縮了可用高度）" if same_side_bottom else ""
        raise ComposeError(
            f"{longer} {most} 格，縮到最小字級仍放不進直標（欄高 {column_h}px）{hint}"
        )
    # 2026-09-09：色框不再從 band_top 往下長到底，改成在可用範圍內置中偏上
    top = band_top + round((band_bottom - band_top - column_h) * VSTRIP_VERTICAL_ANCHOR)

    # 欄寬由字級推導（2026-09-09）：字級縮 → 欄寬縮 → 兩行之間的行距跟著變窄。
    # 字級與 compose_yt_overlay 畫字時用的是同一個值，所以一併回傳。
    cell_size = max(1, round(pitch * VSTRIP_CELL_TIGHT))
    main_w = sub_w = max(1, round(cell_size * VSTRIP_COLUMN_WIDTH_EM))
    seam = round(width * VSTRIP_SEAM_RATIO)
    outer = round(width * VSTRIP_LEFT_RATIO)
    if title_side == "left":
        sub_x0 = outer
        main_x0 = sub_x0 + sub_w + seam
    else:
        sub_x0 = width - outer - sub_w
        main_x0 = sub_x0 - seam - main_w
    main = (main_x0, top, main_x0 + main_w, top + column_h)
    sub = (sub_x0, top, sub_x0 + sub_w, top + column_h) if sub_cells else (sub_x0, top, sub_x0, top)

    strip_x0 = min(main[0], sub[0]) if sub_cells else main[0]
    strip_x1 = max(main[2], sub[2]) if sub_cells else main[2]
    box = (strip_x0, top, strip_x1, top + column_h)   # 一整塊色框
    live_w = round(width * VSTRIP_LIVE_WIDTH_RATIO)
    live_x0 = strip_x0 if title_side == "left" else strip_x1 - live_w
    live = (live_x0, live_top, live_x0 + live_w, live_top + live_h)

    label_w = round(width * VSTRIP_LABEL_WIDTH_RATIO)
    label_h = round(height * VSTRIP_LABEL_HEIGHT_RATIO)
    label_x0 = strip_x0 if title_side == "left" else strip_x1 - label_w
    label = (label_x0, live[3], label_x0 + label_w, live[3] + label_h) if labelled else (0, 0, 0, 0)

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


def _vstrip_source_box_follow_logo(logo, logo_corner, src_w, src_h, gap):
    """source_follow_logo=True：Logo 在上→句子在 Logo 下方，在下→在上方。"""
    x1 = logo[2] if logo_corner in ("tr", "br") else logo[0] + src_w
    y0 = logo[3] + gap if logo_corner in ("tr", "tl") else logo[1] - gap - src_h
    return (x1 - src_w, y0, x1, y0 + src_h)


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
    fill: tuple[int, int, int] = VSTRIP_MAIN_FILL,
    size: tuple[int, int] = YT_CANVAS,
) -> bytes:
    """合成 YT 直播用的「直標」透明底 PNG，回傳 PNG bytes（RGBA，沒有底圖）。

    main_title 是主標（內側欄），sub_title 是副標（外側欄）；2026-09-08 起兩欄**同字級、
    同底色、同一塊色框**（fill 一個顏色畫整塊），字少的那欄早點結束。
    variant：normal／original_audio／ai_translation，後兩者在 LIVE 章下方多一枚白底小標。
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

    # ---- 底色：一整塊色框（兩欄不拆開），由外緣往內一道很淡的漸層 ----
    x0, y0, x1, y1 = layout["box"]
    canvas.alpha_composite(_vertical_column_layer((x1 - x0, y1 - y0), fill, title_side == "left"),
                           (x0, y0))

    # ---- 兩欄文字：白字、同字級，不用封面那套重描邊＋陰影（那是壓照片用的，壓深藍會糊）----
    pitch = layout["pitch"]
    for key, cells in (("main", layout["main_cells"]), ("sub", layout["sub_cells"])):
        if not cells:
            continue
        x0, y0, x1, _ = layout[key]
        # 欄寬 2026-09-09 起由字級推導，字級直接用 layout 算好的那個；仍夾一次欄寬
        # 當保險，免得哪天欄寬改回固定值又忘了這裡。
        size_px = min(layout["cell_size"], round((x1 - x0) * 0.94))
        font = _font(size_px)
        for index, cell in enumerate(cells):
            cell_y0 = y0 + round(index * pitch)
            _draw_vertical_cell(canvas, cell, (x0, cell_y0, x1, cell_y0 + round(pitch)),
                                font, (255, 255, 255))

    # ---- LIVE 章 ----
    if live:
        box = layout["live"]
        _paste_live_badge(canvas, (box[0], box[1]), box[2] - box[0])

    # ---- 原音呈現／AI即時翻譯：白底、紅框、紅字 ----
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
YT_SPLIT_MAX_PANELS = 3
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


def crop_background_16x9(image_bytes: bytes) -> bytes:
    """把使用者附的原圖（任意比例）裁成 16:9 的無文字底圖，回 PNG。

    給「有 asis 附圖就不打生圖模型」那條路用：附圖本身就是底圖，只需要裁滿版面。
    """
    panel = _cover_panel(image_bytes, YT_CANVAS)
    buffer = io.BytesIO()
    panel.save(buffer, format="PNG")
    return buffer.getvalue()
