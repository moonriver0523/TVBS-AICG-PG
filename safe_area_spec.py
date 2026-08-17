"""TVBS 官方安全框（Studio Locked-Frame）的唯一數值來源。

規格出處：`docs/examples/tvbs-safe-frame-locked-tool.md`（2026-07-24 實測）。
基準畫布 1920×1080，安全框 X=140 / Y=109 / W=1634 / H=751，四邊不對稱。

自 2026-07-24 起，凡驗收生圖是否符合安全框，一律以這組數值換算，
不得另外發明比例或沿用舊的對稱 80/80 草案。生圖 prompt 內**永遠不得**出現
這裡的任何數字——歷史實驗證實模型會把數字當文字畫進圖裡
（見 `docs/error-cases/2026-07-23-像素安全框-分析.md`）。
"""

# 官方基準畫布
BASE_CANVAS = (1920, 1080)

REPORTER_PROFILE = "記者"
EDITOR_PROFILE = "編輯"

# 記者：Studio Locked-Frame（預留跑馬燈，底部較深）
# 編輯：對位框紅線內緣 90/70/1748/924（1.892）。
#
# 2026-08-14 曾內縮成紅框內最大的 16:9（142/70/1643/924），讓 16:9 生圖 FIT 零裁切；
# 代價是左右各差 52px，那圈由 backdrop 漸層填滿。2026-08-17 編輯回報：裁到紅框後
# 那兩條漸層色帶還在，後製很難處理。量測確認左右各 53px，成因就是這個內縮。
#
# 改回整個紅框，靠 safe_frame 的水平拉伸填滿（見那邊 STRETCH_PROFILES 的說明）：
# 零裁切、零機制底色。試過的其他做法與淘汰原因記在 safe_frame.STRETCH_PROFILES。
PROFILES = {
    REPORTER_PROFILE: (140, 109, 1634, 751),
    EDITOR_PROFILE: (90, 70, 1748, 924),
}

BASE_SAFE_RECT = PROFILES[REPORTER_PROFILE]  # 預設記者，舊呼叫端不用改


def _fractions_for(rect: tuple[int, int, int, int]) -> dict[str, float]:
    x, y, w, h = rect
    base_w, base_h = BASE_CANVAS
    return {
        "top": y / base_h,
        "left": x / base_w,
        "right": (base_w - x - w) / base_w,
        "bottom": (base_h - y - h) / base_h,
    }


def margin_fractions(profile: str = REPORTER_PROFILE) -> dict[str, float]:
    rect = PROFILES.get(profile, PROFILES[REPORTER_PROFILE])
    return _fractions_for(rect)


# 四邊留白佔畫布的比例（記者；舊程式讀這個常數）
MARGIN_FRACTIONS = margin_fractions(REPORTER_PROFILE)

EDGES = ("top", "left", "right", "bottom")

# 留白超過需求的這個倍數時視為「過縮浪費」：內容雖然沒違規，但畫面利用率太差。
# 依據 docs/error-cases/2026-07-29-LINE-GPT恩智浦-過縮浪費.jpg（左右 26%，需求 7.3%）。
WASTEFUL_RATIO = 2.0

# 量測誤差容許值（佔畫布比例）。生成圖的邊緣有光暈與漸層，逐像素判定會過度嚴格。
TOLERANCE = 0.005


def safe_rect(
    width: int, height: int, profile: str = REPORTER_PROFILE
) -> tuple[int, int, int, int]:
    """回傳指定畫布尺寸下的安全區矩形 (x0, y0, x1, y1)，x1/y1 為右下界（不含）。"""
    fractions = margin_fractions(profile)
    x0 = round(fractions["left"] * width)
    y0 = round(fractions["top"] * height)
    x1 = round((1 - fractions["right"]) * width)
    y1 = round((1 - fractions["bottom"]) * height)
    return x0, y0, x1, y1


def required_margins_px(
    width: int, height: int, profile: str = REPORTER_PROFILE
) -> dict[str, int]:
    """回傳指定畫布尺寸下四邊所需的留白像素數。"""
    x0, y0, x1, y1 = safe_rect(width, height, profile)
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
