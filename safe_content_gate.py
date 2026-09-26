"""D26（2026-09-26 使用者裁決）：「模型畫延伸背景」模式的安全框守門。

使用者看了 B106 實拍 T1／T2：「你成功讓生圖模型畫出四周延伸背景 這就是安全框的
最佳解法 比硬壓單底色還棒」。延伸背景模式下模型自己把背景畫到四邊、內容縮在中央，
程式不再縮圖補單色——但留白多大變成模型說了算，模型量不出比例（safe_frame.py 開頭
四輪實驗 0 次合格），所以一定要在交付前用程式確認。

判準只看**文字**：本機 RapidOCR 的文字偵測框（只跑 det，不辨識內容，約 1 秒），
任何一個框超出記者安全框就不合格。為什麼不用影像法判「主要內容」：延伸背景本來就
充滿建築、雲、紋理，單張壓平的圖分不出哪些是背景、哪些是內容（SOL 評估，
docs/回覆-20260926-SOL評估D26延伸背景.md 第 3 節）。

「無法確認」一律當不合格：偵測不到任何字（無字檔例外）、OCR 丟例外、載入失敗。
不合格的處置由呼叫端決定（main.py：同一張圖退回 FIT 置框，不重生），代價只是回到
今天已接受的硬壓效果——假陰性（出框的字被放行）才是播出事故，門檻寧可偏嚴。

4 張真圖回放（tests/test_d26_safe_content_gate.py）：T1／T2／字多記者判合格，
編輯實驗（標題與底部橫幅出框）判不合格。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import safe_area_spec

_ocr = None
_ocr_lock = threading.Lock()


def _engine():
    """RapidOCR 很重（載兩個 onnx 模型），整個行程共用一個，第一次用到才載。"""
    global _ocr
    with _ocr_lock:
        if _ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            _ocr = RapidOCR()
        return _ocr


def detect_text_boxes(image) -> list[tuple[float, float, float, float]]:
    """回傳每個文字偵測框的外接矩形 (x0, y0, x1, y1)，座標是 image 本身的像素。"""
    import numpy as np

    boxes, _ = _engine()(
        np.asarray(image.convert("RGB")), use_det=True, use_cls=False, use_rec=False
    )
    result = []
    for quad in boxes or []:
        xs = [float(p[0]) for p in quad]
        ys = [float(p[1]) for p in quad]
        result.append((min(xs), min(ys), max(xs), max(ys)))
    return result


@dataclass
class GateResult:
    passed: bool
    reason: str
    rect: tuple[int, int, int, int]
    boxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    outside: list[tuple[float, float, float, float]] = field(default_factory=list)


def check_text_inside_safe_area(
    image,
    *,
    profile: str = safe_area_spec.REPORTER_PROFILE,
    allow_no_text: bool = False,
    detector=None,
) -> GateResult:
    """所有文字框都要完整落在 `safe_area_spec.safe_rect()` 內才算合格。

    安全框依 image 自己的尺寸等比換算（2K 自然成立），不在這裡另抄一組座標。
    allow_no_text：無字檔本來就沒有字，偵測到零個框是正確結果而不是「無法確認」。
    """
    width, height = image.size
    rect = safe_area_spec.safe_rect(width, height, profile)
    x0, y0, x1, y1 = rect
    try:
        # 預設值在呼叫時才解析，測試 patch 模組上的 detect_text_boxes 才有效
        boxes = (detector or detect_text_boxes)(image)
    except Exception as exc:  # noqa: BLE001 — 任何失敗都當「無法確認」
        return GateResult(False, f"文字偵測失敗：{type(exc).__name__}", rect)
    if not boxes:
        if allow_no_text:
            return GateResult(True, "無字檔，未偵測到文字", rect)
        return GateResult(False, "偵測不到任何文字，無法確認是否在安全框內", rect)
    outside = [
        b for b in boxes if b[0] < x0 or b[1] < y0 or b[2] > x1 or b[3] > y1
    ]
    if outside:
        return GateResult(
            False, f"{len(outside)} 段文字超出安全框", rect, boxes, outside
        )
    return GateResult(True, f"{len(boxes)} 段文字都在安全框內", rect, boxes)
