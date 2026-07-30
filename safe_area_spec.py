"""TVBS 官方安全框（Studio Locked-Frame）的唯一數值來源。

規格出處：`docs/examples/tvbs-safe-frame-locked-tool.md`（2026-07-24 實測）。
基準畫布 1920×1080，安全框 X=140 / Y=109 / W=1634 / H=751，四邊不對稱。

自 2026-07-24 起，凡驗收生圖是否符合安全框，一律以這組數值換算，
不得另外發明比例或沿用舊的對稱 80/80 草案。生圖 prompt 內**永遠不得**出現
這裡的任何數字——歷史實驗證實模型會把數字當文字畫進圖裡
（見 `docs/error-cases/2026-07-23-像素安全框-分析.md`）。
"""

# 官方基準畫布與安全框座標（像素）
BASE_CANVAS = (1920, 1080)
BASE_SAFE_RECT = (140, 109, 1634, 751)  # x, y, w, h

_base_w, _base_h = BASE_CANVAS
_x, _y, _w, _h = BASE_SAFE_RECT

# 四邊留白佔畫布的比例（與解析度無關，可換算到任意輸出尺寸）
MARGIN_FRACTIONS = {
    "top": _y / _base_h,  # 0.1009
    "left": _x / _base_w,  # 0.0729
    "right": (_base_w - _x - _w) / _base_w,  # 0.0760
    "bottom": (_base_h - _y - _h) / _base_h,  # 0.2037
}

EDGES = ("top", "left", "right", "bottom")

# 留白超過需求的這個倍數時視為「過縮浪費」：內容雖然沒違規，但畫面利用率太差。
# 依據 docs/error-cases/2026-07-29-LINE-GPT恩智浦-過縮浪費.jpg（左右 26%，需求 7.3%）。
WASTEFUL_RATIO = 2.0

# 量測誤差容許值（佔畫布比例）。生成圖的邊緣有光暈與漸層，逐像素判定會過度嚴格。
TOLERANCE = 0.005


def safe_rect(width: int, height: int) -> tuple[int, int, int, int]:
    """回傳指定畫布尺寸下的安全區矩形 (x0, y0, x1, y1)，x1/y1 為右下界（不含）。"""
    x0 = round(MARGIN_FRACTIONS["left"] * width)
    y0 = round(MARGIN_FRACTIONS["top"] * height)
    x1 = round((1 - MARGIN_FRACTIONS["right"]) * width)
    y1 = round((1 - MARGIN_FRACTIONS["bottom"]) * height)
    return x0, y0, x1, y1


def required_margins_px(width: int, height: int) -> dict[str, int]:
    """回傳指定畫布尺寸下四邊所需的留白像素數。"""
    x0, y0, x1, y1 = safe_rect(width, height)
    return {"top": y0, "left": x0, "right": width - x1, "bottom": height - y1}


def verdict_for_edge(edge: str, measured_fraction: float) -> str:
    """單邊判定。measured_fraction 為實測留白佔畫布的比例。

    回傳 "pass"（合格）／"fail"（內容侵入安全框外）／"wasteful"（合格但過縮浪費）。
    四邊各自獨立判定：即使左右合格，底部超線仍算不合格。
    """
    required = MARGIN_FRACTIONS[edge]
    if measured_fraction < required - TOLERANCE:
        return "fail"
    if measured_fraction > required * WASTEFUL_RATIO:
        return "wasteful"
    return "pass"


def summarize(measured: dict[str, float]) -> dict[str, object]:
    """把四邊實測比例整理成逐邊判定＋整體結論。"""
    verdicts = {edge: verdict_for_edge(edge, measured[edge]) for edge in EDGES}
    failed = [edge for edge, v in verdicts.items() if v == "fail"]
    wasteful = [edge for edge, v in verdicts.items() if v == "wasteful"]
    return {
        "measured_pct": {e: round(measured[e] * 100, 2) for e in EDGES},
        "required_pct": {e: round(MARGIN_FRACTIONS[e] * 100, 2) for e in EDGES},
        "verdicts": verdicts,
        "failed_edges": failed,
        "wasteful_edges": wasteful,
        "overall": "fail" if failed else ("wasteful" if wasteful else "pass"),
    }
