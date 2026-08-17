"""生成後把整張圖程式化置入 TVBS 安全框，四周補背景。

為什麼要有這支：安全框寫進 prompt 的四輪實驗（像素／百分比／純文字／參考圖與遮罩）
全部失敗，底部安全區至今 0 次合格。原因不是措辭不夠強，而是模型量不出比例——
它連自己畫的元素落在畫布幾成位置都不知道。

因此改成順著模型的天性走：讓它把畫面畫滿（實測「畫滿」它做得很好），
留白完全交給這支模組用數學算。結果 100% 精準且可重現，不需要抽卡。

背景補法採廣播常見的 blur-fill：把原圖放大鋪滿畫布、重度模糊當底，
再把清晰的內容貼在安全框中央。這樣四周留白與中央同一張圖同一個色調，
符合原本規則要求的「背景無縫延伸、不得有硬邊或色塊」。
"""

import io

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

import safe_area_spec

# 官方基準畫布。輸出固定 1080P，與 TVBS 安全框工具一致。
DEFAULT_CANVAS = safe_area_spec.BASE_CANVAS

# ---- 內容縮放比例：FIT(0.0) 到 COVER(1.0) 之間連續內插 ----
# 16:9 內容塞進安全區（長寬比 2.176:1）時，高度是綁定軸，寬度會多出餘裕——
# 這正是 FIT(0.0) 時左右留白遠超官方需求（15% vs 官方 7.3/7.6%）的原因。
# 2026-07-30 使用者用 TVBS 官方對框工具實測比對後指出「左右抓太寬，應該減半」：
# 把 mode 設在 0.0～1.0 之間會線性內插縮放比例，且這個內插在「餘裕像素數」上也是
# 線性的（見 plan_placement 內的推導），所以 mode=0.5 精確地讓餘裕減半，不是概略值。
# 代價：mode>0 時內容的縮放尺寸會超出安全區的高度，超出部分沿上下對稱裁掉——
# 裁的是模型自己留的「呼吸空間」（見 TODO 對這段留白成因的分析），不是真正的標題或
# 卡片內容，但無法保證每張生成圖都留了同樣多的呼吸空間，仍有極小機率裁到內容邊緣。
FIT = 0.0
COVER = 1.0
# 2026-07-30：曾把預設定為 0.5（餘裕減半）並用兩張既有樣本目視驗證過看似安全，
# 但使用者用真實生成圖實測後回報底部 <蓋章> 橫幅被裁到——鏡面留白會隨每次生成
# 變動，兩張樣本的驗證不足以保證安全，此路線改為結構性修法（改生成長寬比，見
# TODO），mode 的裁切用法仍保留給刻意想裁的呼叫端，但**不能是預設**。
DEFAULT_CROP_RATIO = FIT


def default_crop_ratio(profile: str) -> float:
    # 記者框已對齊 21:9 生成比例，FIT 零裁切。編輯走拉伸（見 STRETCH_PROFILES），
    # 不經過 mode 這條路。
    return DEFAULT_CROP_RATIO


# ---- 不等比水平拉伸填滿安全區 ----
# 編輯的對位框是 1.892，能拿到的最寬生成比例是 16:9（1.778）——OpenRouter 上
# OpenAI 全家在 16:9 與 21:9 之間沒有任何比例，也沒有模型吃自由尺寸（2026-08-17 查證）。
# 比例對不上就只能三選一，2026-08-17 全部用真實生成圖驗證過：
#   FIT   → 左右各留 53px，得補東西。漸層襯底就是編輯反映很難後製的那兩條色帶。
#   COVER → 上下各裁 3%。實測兩輪（共 6 張）模型的邊界習慣穩定落在 3% 上下，
#           拿掉 prompt 的滿版字眼也只推到 24–26px，正好卡在裁切線上，
#           會削到蓋章橫幅的下緣金框——賭運氣，不能上。
#   拉伸  → 水平 +6.4%，零裁切零補邊。使用者比對特寫後判定「失真輕微可接受」。
# 之所以是水平而非垂直：對位框比 16:9 寬，拉寬即可；垂直方向本來就吻合。
STRETCH_PROFILES = frozenset({safe_area_spec.EDITOR_PROFILE})


def uses_stretch(profile: str) -> bool:
    return profile in STRETCH_PROFILES


# ---- 先吃掉模型自己留的純背景，剩下的差額才用拉伸 ----
# 拉伸幅度取決於「來源比例離安全區多遠」，所以每從上下裁掉 1px 背景，
# 失真就少約 0.25%。2026-08-17 實測（6 張真實生成圖）：prompt 要求四周留純背景帶時
# 模型會留 21–23px，裁掉後殘餘失真只剩 0.75–1.24%；沒要求時留 8–14px，殘餘 3–4.4%。
#
# 關鍵是這裡**不寫死裁多少**：從邊界往內走，一遇到任何元素跡象就停，只裁已確認
# 是純背景的列。最壞情況（模型一點邊都沒留）退回全額拉伸，絕不會切到內容——
# 與寫死裁 3% 的 COVER 有本質差別（那個實測會削到蓋章橫幅的下緣金框）。
#
# 判準刻意保守：背景基準取該列最左／最右各 8px 的中位數（邊緣必為背景，否則
# 這張圖本來就不該裁），該列只要有 EDGE_SCAN_MIN_HITS 以上的像素明顯偏離就停。
EDGE_SAMPLE = 8          # 取樣寬度（每側）
EDGE_DEVIATION = 90      # RGB 三通道絕對差之和，超過視為「不是背景」
# 該列偏離像素數達此值就判定有元素。用絕對值而非比例——比例門檻會漏掉角落的小圖示。
# 8 是量出來的：2026-08-17 用 9 張真實生成圖掃 3/6/8/12/16/24，純背景列的雜訊
# （微光暈與壓縮痕）落在 0–4 個像素，而真元素動輒數百上千；門檻從 8 拉到 24 時
# 9 張裡有 7 張結果完全不變，代表雜訊與元素之間有很寬的空隙，8 落在中間很安全。
# 設 3 會被雜訊卡住（實測兩張本來可裁 15/25px 的圖掉到 8/0px）。
EDGE_SCAN_MIN_HITS = 8
# 相鄰兩列的基準色跳變上限。單看「這一列夠均勻」擋不住橫貫全寬的純色帶
# （例如貼邊的實心色條會整列同色，看起來就像背景）；但從邊界一路掃進來時，
# 背景漸層在幾十列內變化很小，色帶則是一次大跳，用這個把它攔下來。
EDGE_BASE_JUMP = 40


def _row_pixels(source: Image.Image, y: int) -> list[tuple[int, int, int]]:
    """第 y 列的像素。走 tobytes 而不是 getdata——後者在 Pillow 14 會移除。"""
    raw = source.crop((0, y, source.width, y + 1)).tobytes()
    return [tuple(raw[i : i + 3]) for i in range(0, len(raw), 3)]


def _row_base_colour(pixels: list[tuple[int, int, int]]) -> tuple[int, ...]:
    """該列的背景基準色：最左／最右各取樣後的中位數。邊緣必為背景，否則不該裁。"""
    sample = pixels[:EDGE_SAMPLE] + pixels[-EDGE_SAMPLE:]
    return tuple(sorted(channel)[len(channel) // 2] for channel in zip(*sample))


def _row_is_plain_background(
    pixels: list[tuple[int, int, int]], base: tuple[int, ...]
) -> bool:
    hits = 0
    for pixel in pixels:
        if sum(abs(p - b) for p, b in zip(pixel, base)) > EDGE_DEVIATION:
            hits += 1
            if hits >= EDGE_SCAN_MIN_HITS:
                return False
    return True


def plain_background_margin(source: Image.Image, limit: int) -> int:
    """上下各有多少列可安全裁掉。回傳兩側都成立的較小值，最多 limit。

    對稱裁切是刻意的：只裁一側會讓設計在框內上下偏移。

    掃描中途遇到基準色大跳變時，先前掃過的那幾列會整批作廢（回傳 0）。
    那代表邊緣壓著一塊與背景不同色的東西——例如貼邊的實心色條，它整列同色，
    只看「這列夠均勻」會誤判成背景。寧可退回全額拉伸，也不能裁到那種色條。
    """
    if limit <= 0:
        return 0
    height = source.size[1]
    counts = []
    for from_top in (True, False):
        found = 0
        previous: tuple[int, ...] | None = None
        for step in range(min(limit, height // 2)):
            y = step if from_top else height - 1 - step
            pixels = _row_pixels(source, y)
            base = _row_base_colour(pixels)
            if previous is not None and sum(
                abs(b - p) for b, p in zip(base, previous)
            ) > EDGE_BASE_JUMP:
                found = 0
                break
            if not _row_is_plain_background(pixels, base):
                break
            previous = base
            found += 1
        counts.append(found)
    return min(counts)


def _shave_plain_edges(source: Image.Image, zone: tuple[int, int]) -> Image.Image:
    """裁掉上下的純背景，讓來源比例更接近安全區，降低待會兒的拉伸幅度。"""
    zone_w, zone_h = zone
    width, height = source.size
    if width <= 0 or height <= 0 or zone_w <= 0 or zone_h <= 0:
        return source
    # 裁到「來源比例＝安全區比例」就零失真，再多裁只是白白丟畫面
    ideal_h = width * zone_h / zone_w
    limit = int((height - ideal_h) // 2)
    margin = plain_background_margin(source, limit)
    if margin <= 0:
        return source
    return source.crop((0, margin, width, height - margin))

# ---- 四周背景的做法 ----
# 2026-07-30 用實際生成圖做過四種做法的並排對照後由使用者選定 backdrop 為預設。
# blur 的問題是它「試圖假裝無縫」卻失敗：重度模糊把文字糊成鬼影、又與中央清晰內容
# 形成硬邊，在大螢幕上會被讀成畫面出錯。backdrop 反過來不假裝，做成刻意的襯底。
BACKDROP = "backdrop"
CLAMP = "clamp"
BLUR = "blur"
BACKGROUNDS = (BACKDROP, CLAMP, BLUR)
DEFAULT_BACKGROUND = BACKDROP

# backdrop：襯底由邊緣色做的垂直漸層構成，上亮下暗。這兩個係數是對照時定下來的，
# 夠暗讓中央內容跳出來，又不會暗到看起來像黑邊。
BACKDROP_TOP_FACTOR = 0.62
BACKDROP_FALLOFF = 0.18
# 內容下方的柔和投影，讓它像浮在襯底上的卡片而不是硬貼上去的方塊。
SHADOW_SPREAD = 6
SHADOW_DROP = 14
SHADOW_ALPHA = 170
SHADOW_BLUR = 22

# blur 模式的參數（保留作對照與回溯）：模糊半徑取畫布寬的比例，
# 大到讓底圖文字完全不可辨識；亮度係數壓暗避免與內容爭視覺。
BLUR_RATIO = 0.04
BACKGROUND_DIM = 0.72


def plan_placement(
    source_size: tuple[int, int],
    canvas: tuple[int, int] = DEFAULT_CANVAS,
    mode: float = FIT,
    profile: str = safe_area_spec.REPORTER_PROFILE,
) -> tuple[int, int, int, int]:
    """算出內容要貼在畫布的哪個矩形 (x0, y0, x1, y1)。純函式，方便直接斷言。

    mode 是 0.0（FIT）到 1.0（COVER）之間的數字：
    0.0：等比縮放到「完全放進」安全框，置中。不裁切，代價是來源長寬比與安全框
         不同時，某一軸會留下比官方需求更寬的餘裕（16:9 塞 2.176:1 安全區即如此）。
    1.0：等比縮放到「填滿」安全框兩軸，裁掉溢出部分。餘裕降到 0，但會裁掉內容，
         來源是滿版資訊圖表時有切到標題或結論的風險。
    0.0～1.0 之間：線性內插縮放比例。回傳的矩形可能超出安全區（甚至超出畫布）——
    呼叫端（apply_safe_frame）負責把超出畫布的部分裁掉。

    ⚠️ 這裡回傳的矩形不再保證落在安全區或畫布內（mode>0 時會超出）。
    mode=0.0（FIT）仍保證落在安全區內，行為與過去相同。

    拉伸 profile（見 STRETCH_PROFILES）直接回傳整個安全區——內容會被不等比
    縮放填滿它，沒有等比縮放這回事，mode 對它沒有意義。
    """
    if uses_stretch(profile):
        src_w, src_h = source_size
        if src_w <= 0 or src_h <= 0:
            raise ValueError("來源尺寸不合法")
        return safe_area_spec.safe_rect(*canvas, profile)
    if not isinstance(mode, (int, float)) or not 0.0 <= mode <= 1.0:
        raise ValueError(
            f"mode 必須是 0.0（FIT）到 1.0（COVER）之間的數字，收到：{mode!r}"
        )
    src_w, src_h = source_size
    if src_w <= 0 or src_h <= 0:
        raise ValueError("來源尺寸不合法")

    x0, y0, x1, y1 = safe_area_spec.safe_rect(*canvas, profile)
    zone_w = x1 - x0
    zone_h = y1 - y0

    fit_scale = min(zone_w / src_w, zone_h / src_h)
    cover_scale = max(zone_w / src_w, zone_h / src_h)
    scale = fit_scale + mode * (cover_scale - fit_scale)

    width = max(1, round(src_w * scale))
    height = max(1, round(src_h * scale))
    left = x0 + (zone_w - width) // 2
    top = y0 + (zone_h - height) // 2
    return left, top, left + width, top + height


def _blurred_background(source: Image.Image, canvas: tuple[int, int]) -> Image.Image:
    """把原圖鋪滿畫布、重度模糊、稍微壓暗，當成四周留白的底。"""
    canvas_w, canvas_h = canvas
    src_w, src_h = source.size
    scale = max(canvas_w / src_w, canvas_h / src_h)
    scaled = source.resize(
        (max(1, round(src_w * scale)), max(1, round(src_h * scale))), Image.LANCZOS
    )
    left = (scaled.width - canvas_w) // 2
    top = (scaled.height - canvas_h) // 2
    cropped = scaled.crop((left, top, left + canvas_w, top + canvas_h))
    blurred = cropped.filter(ImageFilter.GaussianBlur(radius=canvas_w * BLUR_RATIO))
    return ImageEnhance.Brightness(blurred).enhance(BACKGROUND_DIM)


def _edge_colour(source: Image.Image) -> tuple[int, int, int]:
    """取原圖外圈的平均色。縮成 9×9 後只採邊框那一圈，中央的主視覺不參與。"""
    small = source.resize((9, 9), Image.LANCZOS)
    border = [
        small.getpixel((x, y))
        for x in range(9)
        for y in range(9)
        if x in (0, 8) or y in (0, 8)
    ]
    return tuple(round(sum(channel) / len(border)) for channel in zip(*border))


def _backdrop_background(source: Image.Image, canvas: tuple[int, int]) -> Image.Image:
    """用邊緣色做上亮下暗的垂直漸層襯底。

    刻意不追求「與內容無縫」——內容會另外加投影，讀起來是一張卡片放在襯底上。
    這樣就沒有 blur 那種「像壞掉」的觀感，也不會出現鬼影或拉伸條紋。
    """
    canvas_w, canvas_h = canvas
    base_rgb = _edge_colour(source)
    backdrop = Image.new("RGB", canvas)
    draw = ImageDraw.Draw(backdrop)
    for y in range(canvas_h):
        factor = BACKDROP_TOP_FACTOR - BACKDROP_FALLOFF * (y / canvas_h)
        draw.line(
            [(0, y), (canvas_w, y)],
            fill=tuple(max(0, min(255, round(value * factor))) for value in base_rgb),
        )
    return backdrop


def _clamp_background(
    content: Image.Image, box: tuple[int, int, int, int], canvas: tuple[int, int]
) -> Image.Image:
    """邊緣延伸：把內容最外一列／一行往外拉滿畫布。

    可分離處理——先左右拉滿寬得到一條橫帶，再把橫帶上下拉滿，角落自然由前一步延伸而來。
    邊界處的顏色由定義與內容完全相同，因此接縫不可見；代價是外圈沒有新增細節，
    且萬一模型把元素畫到貼邊會被拉出條紋。
    """
    canvas_w, canvas_h = canvas
    left, top, right, bottom = box
    width, height = content.size

    strip = Image.new("RGB", (canvas_w, height))
    strip.paste(content, (left, 0))
    if left > 0:
        edge = content.crop((0, 0, 1, height)).resize((left, height), Image.NEAREST)
        strip.paste(edge, (0, 0))
    if right < canvas_w:
        edge = content.crop((width - 1, 0, width, height))
        strip.paste(edge.resize((canvas_w - right, height), Image.NEAREST), (right, 0))

    out = Image.new("RGB", canvas)
    out.paste(strip, (0, top))
    if top > 0:
        edge = strip.crop((0, 0, canvas_w, 1)).resize((canvas_w, top), Image.NEAREST)
        out.paste(edge, (0, 0))
    if bottom < canvas_h:
        edge = strip.crop((0, height - 1, canvas_w, height))
        out.paste(edge.resize((canvas_w, canvas_h - bottom), Image.NEAREST), (0, bottom))
    return out


def _apply_content_shadow(
    base: Image.Image, box: tuple[int, int, int, int]
) -> Image.Image:
    """在內容框下方鋪一層柔和投影。只有 backdrop 模式需要——它刻意不假裝無縫。"""
    shadow = Image.new("L", base.size, 0)
    ImageDraw.Draw(shadow).rectangle(
        (
            box[0] - SHADOW_SPREAD,
            box[1] - SHADOW_SPREAD,
            box[2] + SHADOW_SPREAD,
            box[3] + SHADOW_DROP,
        ),
        fill=SHADOW_ALPHA,
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=SHADOW_BLUR))
    return Image.composite(Image.new("RGB", base.size, (0, 0, 0)), base, shadow)


def apply_safe_frame(
    image_bytes: bytes,
    *,
    canvas: tuple[int, int] = DEFAULT_CANVAS,
    mode: float | None = None,
    background: str = DEFAULT_BACKGROUND,
    profile: str = safe_area_spec.REPORTER_PROFILE,
) -> bytes:
    """把生成圖置入安全框並補背景，回傳 PNG bytes。

    來源尺寸不設限：Gemini 實測會回 1376×768 而非要求的 1280×720，
    所以一切都按比例計算，不假設任何輸入解析度。

    mode 見 plan_placement。省略時一律 FIT（零裁切）。
    background 三種做法見上方 BACKGROUNDS 的說明，預設 backdrop。
    """
    if mode is None:
        mode = default_crop_ratio(profile)
    if not isinstance(mode, (int, float)) or not 0.0 <= mode <= 1.0:
        raise ValueError(f"未知 mode：{mode}")
    if background not in BACKGROUNDS:
        raise ValueError(f"未知 background：{background}（可用：{list(BACKGROUNDS)}）")

    with Image.open(io.BytesIO(image_bytes)) as opened:
        source = opened.convert("RGB")

        if uses_stretch(profile):
            x0, y0, x1, y1 = safe_area_spec.safe_rect(*canvas, profile)
            source = _shave_plain_edges(source, (x1 - x0, y1 - y0))

        left, top, right, bottom = plan_placement(source.size, canvas, mode, profile)
        full_content = source.resize((right - left, bottom - top), Image.LANCZOS)

        # mode>0 時置放框會超出「安全區」邊界（不是畫布邊界）——這裡裁掉超出安全區
        # 的部分，讓內容永遠落在官方安全區內。裁到畫布邊界是錯的：安全區比畫布小，
        # 若只裁到畫布邊界，超出安全區、還沒超出畫布的那圈會侵蝕官方留白（曾實測到
        # 這個錯法會讓上/下留白從精準的 10.09%/20.37% 被吃到只剩 2%/13%）。
        x0, y0, x1, y1 = safe_area_spec.safe_rect(*canvas, profile)
        crop_left = max(0, x0 - left)
        crop_top = max(0, y0 - top)
        crop_right = full_content.width - max(0, (left + full_content.width) - x1)
        crop_bottom = full_content.height - max(0, (top + full_content.height) - y1)
        content = full_content.crop((crop_left, crop_top, crop_right, crop_bottom))

        paste_x, paste_y = max(x0, left), max(y0, top)
        box = (paste_x, paste_y, paste_x + content.width, paste_y + content.height)

        if background == BACKDROP:
            base = _apply_content_shadow(_backdrop_background(source, canvas), box)
        elif background == CLAMP:
            base = _clamp_background(content, box, canvas)
        else:
            base = _blurred_background(source, canvas)
        base.paste(content, (paste_x, paste_y))

    buffer = io.BytesIO()
    base.save(buffer, format="PNG")
    return buffer.getvalue()
