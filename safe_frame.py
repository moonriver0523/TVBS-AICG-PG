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

from PIL import Image, ImageEnhance, ImageFilter

import safe_area_spec

# 官方基準畫布。輸出固定 1080P，與 TVBS 安全框工具一致。
DEFAULT_CANVAS = safe_area_spec.BASE_CANVAS

# 模糊半徑取畫布寬的這個比例：足以讓底圖的文字完全不可辨識，避免鬼影干擾。
BLUR_RATIO = 0.04

# 背景亮度係數。略暗可讓中央內容跳出來，同時不至於在邊界形成明顯色塊。
BACKGROUND_DIM = 0.72

FIT = "fit"
COVER = "cover"


def plan_placement(
    source_size: tuple[int, int],
    canvas: tuple[int, int] = DEFAULT_CANVAS,
    mode: str = FIT,
) -> tuple[int, int, int, int]:
    """算出內容要貼在畫布的哪個矩形 (x0, y0, x1, y1)。純函式，方便直接斷言。

    fit：等比縮放到「完全放進」安全框，置中。不裁切、不會超出安全框，
         代價是來源長寬比與安全框不同時，某一軸會留下比需求更寬的餘裕。
    cover：等比縮放到「填滿」安全框再裁掉溢出部分。利用率最好，但會裁掉內容，
         來源是滿版資訊圖表時可能切到標題或結論，故非預設。
    """
    src_w, src_h = source_size
    if src_w <= 0 or src_h <= 0:
        raise ValueError("來源尺寸不合法")

    x0, y0, x1, y1 = safe_area_spec.safe_rect(*canvas)
    zone_w = x1 - x0
    zone_h = y1 - y0

    scale_w = zone_w / src_w
    scale_h = zone_h / src_h
    scale = min(scale_w, scale_h) if mode == FIT else max(scale_w, scale_h)

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


def _solid_background(source: Image.Image, canvas: tuple[int, int]) -> Image.Image:
    """取原圖四角平均色當單色底。適合要求絕對乾淨、不要任何殘影的場合。"""
    small = source.resize((3, 3), Image.LANCZOS)
    corners = [small.getpixel((x, y)) for x, y in ((0, 0), (2, 0), (0, 2), (2, 2))]
    average = tuple(round(sum(channel) / len(corners)) for channel in zip(*corners))
    dimmed = tuple(round(value * BACKGROUND_DIM) for value in average)
    return Image.new("RGB", canvas, dimmed)


def apply_safe_frame(
    image_bytes: bytes,
    *,
    canvas: tuple[int, int] = DEFAULT_CANVAS,
    mode: str = FIT,
    background: str = "blur",
) -> bytes:
    """把生成圖置入安全框並補背景，回傳 PNG bytes。

    來源尺寸不設限：Gemini 實測會回 1376×768 而非要求的 1280×720，
    所以一切都按比例計算，不假設任何輸入解析度。
    """
    if mode not in (FIT, COVER):
        raise ValueError(f"未知 mode：{mode}")
    if background not in ("blur", "solid"):
        raise ValueError(f"未知 background：{background}")

    with Image.open(io.BytesIO(image_bytes)) as opened:
        source = opened.convert("RGB")

        if background == "blur":
            base = _blurred_background(source, canvas)
        else:
            base = _solid_background(source, canvas)

        left, top, right, bottom = plan_placement(source.size, canvas, mode)
        content = source.resize((right - left, bottom - top), Image.LANCZOS)
        base.paste(content, (left, top))

    buffer = io.BytesIO()
    base.save(buffer, format="PNG")
    return buffer.getvalue()
