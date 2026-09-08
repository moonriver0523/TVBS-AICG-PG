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
# 2026-09-08 使用者看了正式站成品後再裁決（雙切）：**兩格同一字級**。逐行各自撐滿的做法
# 讓「左格三行 6 字都最大、右格第三行 11 字被壓小」變成兩邊字大小差一截，看起來像兩張圖
# 拼的。改成：每格先各自算出逐行都塞得進的字級，再取兩格的全域最小值當所有行的字級
# （所以 COVER_TITLE_LINE_SIZE_SPREAD 退場）。配套是把行拆得夠短——只要一行超過
# COVER_TITLE_FILL_MIN_CHARS 就再拆，雙切放寬到 4 行——不然共同字級會被最長那行拖垮。
# 滿版是單一標題、沒有另一格可比，維持逐行各自撐滿。
COVER_TITLE_SIZE_RATIO = 0.11        # 標題起始字級（佔畫面高）
COVER_TITLE_MIN_SIZE_RATIO = 0.045
COVER_TITLE_WIDTH_RATIO = 0.90       # 標題最寬佔該格寬的比例
COVER_TITLE_FILL_MIN_CHARS = 7       # 雙切：長度超過這個字數的行就再拆（拆到夠短，共同字級才大）
COVER_TITLE_TOP_CLEARANCE_RATIO = 0.01   # 標題最上一行的字頂與標頭帶之間留的空隙
COVER_TITLE_LINE_GAP = 1.06          # 行距（字級倍數）
COVER_TITLE_BOTTOM_RATIO = 0.085     # 最後一行字底離畫面底的距離
# 滿版（單一標題，2026-09-07 使用者裁決）：比照今日熱搜，標題橫跨整個畫面寬、置中，
# 字級起點放大；每行各自以整寬決定字級（最寬行決定，全部同字級）。
COVER_FULL_TITLE_SIZE_RATIO = 0.15    # 每行各自撐滿寬（比照今日熱搜逐行 fit），此為字級上限
COVER_FULL_TITLE_WIDTH_RATIO = 0.90
COVER_TITLE_STROKE_RATIO = 0.055
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
COVER_MAX_TITLE_LINES_SPLIT = 4      # 雙切（2026-09-08）：拆得夠短，兩格的共同字級才撐得起來


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
    tag_h = round(band_h * COVER_STAMP_BAND_RATIO)
    with Image.open(TEN_HIGHLIGHT_TAG) as tpl:
        tag_w = round(tpl.width * tag_h / tpl.height)
    _paste_template(canvas, TEN_HIGHLIGHT_TAG, ((width - tag_w) // 2, (band_h - tag_h) // 2), tag_h)


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

    行帶著**段落索引**一起走：拆出來的兩行都繼承原本那一段的索引，配色才跟得上段落
    （2026-09-08 使用者規則：第一個空格後是黃字、第二個空格後是紅字，不是「第幾行」）。
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
    """滿版 3 行、雙切 4 行（2026-09-08）。"""
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
    """行數 × 行距要塞在標頭帶以下、底部標題基線以上，否則整體縮字（2026-09-08，雙切 4 行）。"""
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
    """一格的標題：由下往上堆，配色**依段落**（第 1 段白、第 2 段黃、第 3 段紅白邊）。

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
            raise ComposeError(f"標題太長，縮到最小字級仍超出版面：「{text}」（請用半形空格分段或縮短）")
    baseline = height - round(height * COVER_TITLE_BOTTOM_RATIO)
    if full_width:
        x, anchor = panel_x0 + panel_w // 2, "ms"
    elif align_right:
        x, anchor = panel_x1 - round(panel_w * (1 - COVER_TITLE_WIDTH_RATIO) / 2), "rs"
    else:
        x, anchor = panel_x0 + round(panel_w * (1 - COVER_TITLE_WIDTH_RATIO) / 2), "ls"
    draw = ImageDraw.Draw(canvas)
    # 由最後一行往上畫；顏色看**段落索引**，不是行序
    for idx in range(len(pairs) - 1, -1, -1):
        text, seg = pairs[idx]
        font = fonts[idx]
        stroke = max(3, round(font.size * COVER_TITLE_STROKE_RATIO))
        colour = COVER_TITLE_LINE_COLOURS[min(seg, len(COVER_TITLE_LINE_COLOURS) - 1)]
        is_red = colour == COVER_TITLE_LINE_COLOURS[2]
        # 陰影一層再正字，字壓在照片上才立得住
        _draw_text(draw, (x + 4, baseline + 4), text, font, fill=(0, 0, 0), stroke=(0, 0, 0), stroke_width=stroke, anchor=anchor)
        _draw_text(
            draw, (x, baseline), text, font, fill=colour,
            stroke=COVER_TITLE_STROKE_LIGHT if is_red else COVER_TITLE_STROKE_DARK,
            stroke_width=stroke, anchor=anchor,
        )
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
YT_BAND_TOP_RATIO = 0.60             # 深藍科技底帶起點
YT_BAND_FADE_RATIO = 0.06            # 頂端漸入高度
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
YT_TITLE_STROKE_RATIO = 0.05         # 深色描邊佔字級比例（假粗體吃掉的部分另外補，見 _draw_yt_title_line）
YT_TITLE_BOLD_RATIO = 0.035          # 假粗體：同色描邊佔字級比例
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


def _draw_logo_tab(
    canvas: Image.Image,
    top_colour: tuple[int, int, int] = YT_LOGO_TAB_TOP,
    bottom_colour: tuple[int, int, int] = YT_LOGO_TAB_BOTTOM,
) -> None:
    """右上角漸層標籤（左邊斜切、左下圓角）＋白色 TVBS Logo，貼著畫面右上角。

    預設藍色（新聞直播）；今日熱搜傳紅色。
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
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(gradient, (0, 0), mask)
    canvas.alpha_composite(layer)
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
    bold = max(2, round(font.size * YT_TITLE_BOLD_RATIO))
    outline = max(4, round(font.size * YT_TITLE_STROKE_RATIO)) + bold
    _draw_text(draw, xy, text, font, fill=fill, stroke=YT_TITLE_STROKE, stroke_width=outline, anchor=anchor)
    _draw_text(draw, xy, text, font, fill=fill, stroke=fill, stroke_width=bold, anchor=anchor)


def _draw_title_band(
    canvas: Image.Image,
    fill: tuple[int, int, int] = YT_BAND_FILL,
    block_fill: tuple[int, int, int] = YT_BAND_BLOCK_FILL,
) -> None:
    """底部科技底帶：頂端漸入，帶上撒幾塊半透明方塊模擬頻道的電路紋。

    預設深藍（新聞直播）；今日熱搜傳深紅。
    """
    width, height = YT_CANVAS
    top = round(height * YT_BAND_TOP_RATIO)
    fade = round(height * YT_BAND_FADE_RATIO)
    band = Image.new("RGBA", (width, height - top), fill + (0,))
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
    bottom_band: bool = False,
) -> bytes:
    """合成 YT 國內外新聞直播封面（2026-09-06 依頻道實際版面）。

    bottom_band（2026-09-08 使用者裁決，預設關）：底部深藍壓色框。關＝完全不畫，
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
    bottom_band: bool = False,
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
        _draw_title_band(canvas, YT_HOT_BAND_FILL, YT_HOT_BAND_BLOCK_FILL)
    _draw_hot_header(canvas)
    if ai_note:
        _draw_ai_note(canvas, round(height * YT_AI_NOTE_TOP_RATIO))
    draw = ImageDraw.Draw(canvas)
    max_w = width - margin * 2
    start = round(height * YT_TITLE_SIZE_RATIO)
    smallest = round(height * YT_TITLE_MIN_SIZE_RATIO)
    for text, fill, baseline_ratio in (
        (line1, YT_LINE1_FILL, YT_LINE1_BASELINE_RATIO),
        (line2, YT_LINE2_FILL, YT_LINE2_BASELINE_RATIO),
    ) if draw_titles else ():
        font = _fit_font(text, max_w, start, smallest)
        _draw_yt_title_line(draw, (width // 2, round(height * baseline_ratio)), text, font, fill)
    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
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
