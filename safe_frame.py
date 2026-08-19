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


# 刻意不在置框前裁掉模型留的純背景：2026-08-17 做過「逐張偵測可安全裁掉的背景列，
# 裁完再拉伸」的版本，實測能把失真從 6.4% 壓到 0.25–1.24%，但使用者要求出圖後
# 不要再動任何像素，只做拉伸。所以失真固定 6.4%，換取「成品每個像素都來自模型」。
# prompt 那邊仍要求上下留背景帶（EDITOR_FULL_BLEED_RULES），效果變成廣播安全邊，
# 而不是拿來裁。要回復偵測裁切見 git log commit 395d0ba、6c9e8dc。


# ---- 四周背景的做法 ----
# 2026-07-30 用實際生成圖做過四種做法的並排對照後由使用者選定 backdrop 為預設。
# blur 的問題是它「試圖假裝無縫」卻失敗：重度模糊把文字糊成鬼影、又與中央清晰內容
# 形成硬邊，在大螢幕上會被讀成畫面出錯。backdrop 反過來不假裝，做成刻意的襯底。
BACKDROP = "backdrop"
CLAMP = "clamp"
BLUR = "blur"
BACKGROUNDS = (BACKDROP, CLAMP, BLUR)
DEFAULT_BACKGROUND = BACKDROP

# backdrop：襯底是垂直漸層，上下端點各自取自內容上／下緣的顏色。
#
# 2026-08-19 改版。原本的做法是「整張圖外圈的平均色 × 0.62（頂）～0.44（底）」，
# 實測 10 張線上成品（歷史紀錄 0818–0819）發現襯底**每一張都比內容亮**，色差
# 14–29，在深底 CG 上會讀成一圈灰紫色的外框。兩個成因疊加：
#   1. 取樣：整張外圈的「平均」被標題列、光暈這種亮元素拉高
#      （例：外圈平均 (44,44,44)，內容緊鄰邊界處其實只有 (12,12,12)）。
#   2. 合成：0.62/0.44 是憑空的壓暗係數，與內容實際亮度無關。
# 只修其中一個會讓誤差翻面（取樣修好、係數不動 → 襯底變成系統性偏暗），
# 所以兩個一起改：改取中位數、端點直接取自內容邊緣、壓暗降到僅 5%。
#
# ⚠️ 這推翻了 2026-07-30 使用者選定的「刻意做成襯底（deliberate mat）」設計方向，
# 是使用者 2026-08-19 看過還原重組對照圖後改的決定，不是程式自作主張。
BACKDROP_DIM = 0.95
# 2026-08-19 二次修改：使用者要求襯底改**單色**，不要漸層。
# 漸層版是上下端點各取自內容上／下緣，能重現 CG 自己的明暗走勢；單色版改取
# 整圈邊緣的中位數，代價是內容上下色差很大時只能取折衷（無法兩端都貼合）。
# 這是使用者明確指定的取捨，不是實作限制。要改回漸層見 git log。
# 取樣帶：自內容邊緣往內 1%～4%。跳過最外層那一絲是因為生成圖邊緣常有光暈，
# 與 safe_area_spec.TOLERANCE 存在的理由相同。
EDGE_SAMPLE_INSET = 0.01
EDGE_SAMPLE_DEPTH = 0.03
# 內容下方的柔和投影，讓它像浮在襯底上的卡片而不是硬貼上去的方塊。
# 襯底改成與內容同色後，原本的 170 會變成一圈明顯的黑暈，2026-08-19 降到 90。
SHADOW_SPREAD = 6
SHADOW_DROP = 14
SHADOW_ALPHA = 90
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


def _edge_strips(content: Image.Image) -> list[tuple[int, int, int, int]]:
    """內容四邊各一條取樣帶，位置是自邊緣往內 1%～4%。

    跳過最外層那一絲是因為生成圖邊緣常有光暈，與 safe_area_spec.TOLERANCE 同理。
    上下用高度算、左右用寬度算，四條帶的實際厚度才一致。
    """
    width, height = content.size
    v_inset = round(height * EDGE_SAMPLE_INSET)
    v_depth = max(1, round(height * EDGE_SAMPLE_DEPTH))
    h_inset = round(width * EDGE_SAMPLE_INSET)
    h_depth = max(1, round(width * EDGE_SAMPLE_DEPTH))
    return [
        (0, v_inset, width, v_inset + v_depth),
        (0, max(0, height - v_inset - v_depth), width, max(1, height - v_inset)),
        (h_inset, 0, h_inset + h_depth, height),
        (max(0, width - h_inset - h_depth), 0, max(1, width - h_inset), height),
    ]


def _backdrop_colour(content: Image.Image) -> tuple[int, int, int]:
    """襯底的單一顏色：取內容**上緣**那條取樣帶的逐通道中位數。

    用中位數而不是平均：橫幅標題、發光數字這種高亮元素只佔取樣帶的一小部分，
    平均會被它們整個拉高（實測讓襯底比內容亮 14–29），中位數則會忽略它們、
    回報這一帶真正的底色。

    只取上緣，是拿 10 張線上成品實測比出來的（數字＝襯底與內容邊緣的平均色差，
    愈小愈貼合，同時看上下兩邊的最差值）：

        只取上緣          7.2   ← 採用
        上下左右整圈     17.8
        上＋左右         22.6
        只取左右         28.1

    差距大到不像抽樣雜訊，原因也說得通：CG 底部常有 <蓋章> 橫幅、出處行與暗角，
    左右常是側欄卡片，都不是背景；上緣（標題所在那一帶的底）才是乾淨的背景色。

    代價：內容上下色差大時，單色只能貼合上緣。這是使用者 2026-08-19 指定改單色
    的先天限制，不是 bug——漸層版可以兩端都貼合（實測 上 8.0／下 5.9）。
    """
    box = _edge_strips(content)[0]  # 上緣
    strip = content.crop(box)
    # 先降到固定取樣數再排序：夠精準，又不會因為來源解析度變大而變慢。
    strip = strip.resize((min(64, strip.width), min(64, strip.height)), Image.LANCZOS)
    pixels = list(strip.getdata())
    return tuple(
        sorted(p[channel] for p in pixels)[len(pixels) // 2] for channel in range(3)
    )


def _backdrop_background(content: Image.Image, canvas: tuple[int, int]) -> Image.Image:
    """單色襯底，顏色取自內容整圈邊緣（2026-08-19 使用者指定改單色，不要漸層）。

    目標是四周留白讀起來像 CG 背景自己延伸出去的，而不是外掛的一圈色塊。
    """
    base = _backdrop_colour(content)
    return Image.new(
        "RGB",
        canvas,
        tuple(max(0, min(255, round(value * BACKDROP_DIM))) for value in base),
    )


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


def _shadow_fits(canvas: tuple[int, int], profile: str) -> bool:
    """留白夠不夠寬到容得下投影。

    投影的用意是讓內容讀起來像浮在襯底上的卡片，這需要一圈明顯比投影還寬的襯底。
    留白比投影窄時效果會整個反過來：投影鋪滿整條邊、且沒有空間衰減回襯底色，
    薄邊就從「配色一致的留白」變成「一圈暗邊」。

    門檻取投影伸展的兩倍，不是「剛好大於」——留白必須寬到讓投影衰減完還剩下
    一段乾淨襯底，看起來才是「浮起的卡片」而非「一圈暗邊」。實測（亮度 200
    的內容，襯底真色 175）：

        2% 薄邊 22px：整條 128→139，回不到 175
        4% 薄邊 43px：整條 132→167，仍然回不到 175（只差 7px 就過「剛好大於」
                      這個門檻，卻一樣難看，這就是門檻要加倍的理由）
        記者   109px 起：衰減得回去，投影是它原本就設計好的樣子
    """
    reach = (SHADOW_DROP + SHADOW_BLUR) * 2
    margins = safe_area_spec.required_margins_px(*canvas, profile)
    return min(margins.values()) > reach


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


def _stretch_to_zone(
    image_bytes: bytes, canvas: tuple[int, int], profile: str
) -> bytes:
    """成品＝生成圖不等比拉伸到安全區大小，就這樣，沒有下一步。

    刻意不輸出 1920×1080 畫布：那樣安全區之外還得補上四周留白，而那圈留白
    正是編輯 2026-08-17 反映「程式強制加上去、後製很難處理」的東西。既然
    內容已經精準等於對位框，直接交這一塊就好——編輯把它放進自己的模板即可。

    也因此這條路徑完全不碰 background 參數：沒有任何一個像素需要被補。
    """
    x0, y0, x1, y1 = safe_area_spec.safe_rect(*canvas, profile)
    with Image.open(io.BytesIO(image_bytes)) as opened:
        stretched = opened.convert("RGB").resize((x1 - x0, y1 - y0), Image.LANCZOS)
    buffer = io.BytesIO()
    stretched.save(buffer, format="PNG")
    return buffer.getvalue()


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

    拉伸 profile（編輯）不走置框那條：輸出就是拉伸後的安全區本身，
    沒有畫布、沒有四周留白。詳見 _stretch_to_zone。
    """
    if mode is None:
        mode = default_crop_ratio(profile)
    if not isinstance(mode, (int, float)) or not 0.0 <= mode <= 1.0:
        raise ValueError(f"未知 mode：{mode}")
    if background not in BACKGROUNDS:
        raise ValueError(f"未知 background：{background}（可用：{list(BACKGROUNDS)}）")

    if uses_stretch(profile):
        return _stretch_to_zone(image_bytes, canvas, profile)

    with Image.open(io.BytesIO(image_bytes)) as opened:
        source = opened.convert("RGB")

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
            # 取樣對象是「實際會被貼上去的 content」而非原圖：mode>0 時 content 被裁過，
            # 緊鄰襯底的是裁切後的邊緣，拿原圖取樣會對到一條根本不在成品上的色帶。
            base = _backdrop_background(content, canvas)
            if _shadow_fits(canvas, profile):
                base = _apply_content_shadow(base, box)
        elif background == CLAMP:
            base = _clamp_background(content, box, canvas)
        else:
            base = _blurred_background(source, canvas)
        base.paste(content, (paste_x, paste_y))

    buffer = io.BytesIO()
    base.save(buffer, format="PNG")
    return buffer.getvalue()
