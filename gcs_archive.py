"""網頁版生成歷史（prompt+圖檔）備份進 GCS，供之後手動同步進 Google Drive。

2026-08-16 缺口：`request_log.py` 只留 prompt/消化結果文字，網頁版生出來的圖完全
沒有落地（`static/generated/` 只有 LINE 版在寫，見 line_bot.py）；Cloud Run 本機磁碟
也不持久，重部署就清空。這裡把網頁版每次成功生成的圖＋對應 metadata JSON 一起丟進
GCS bucket，作為長期保存的第一站。

刻意不做自動排程同步進 Drive——使用者要的是隨要隨拉，之後由 agent 手動執行同步，
不是背景常駐工作。GCS bucket 本身設了生命週期規則自動清舊檔，兜底而非取代 Drive。

設計取捨同 request_log.py：絕不讓歸檔失敗影響生成請求本身，所有例外都吞掉只印出來。
"""

import base64
import json
import os
from datetime import datetime, timezone

ENABLED = os.getenv("GCS_HISTORY_BUCKET", "").strip() != ""
BUCKET_NAME = os.getenv("GCS_HISTORY_BUCKET", "")

_bucket = None


def _get_bucket():
    global _bucket
    if _bucket is None:
        from google.cloud import storage

        _bucket = storage.Client().bucket(BUCKET_NAME)
    return _bucket


def archive_generation(
    *,
    request_id: str,
    image_base64: str,
    mime_type: str,
    **metadata,
) -> None:
    """歸檔一次成功的網頁版生成。任何例外都吞掉——歸檔失敗不該波及請求本身。"""
    if not ENABLED:
        return
    try:
        ext = "png" if "png" in mime_type else "jpg"
        now = datetime.now(timezone.utc).astimezone()
        prefix = f"generations/{now:%Y%m%d}/{now:%H%M%S}-{request_id}"
        bucket = _get_bucket()
        bucket.blob(f"{prefix}.{ext}").upload_from_string(
            base64.b64decode(image_base64), content_type=mime_type
        )
        record = {"ts": now.isoformat(), "request_id": request_id, **metadata}
        bucket.blob(f"{prefix}.json").upload_from_string(
            json.dumps(record, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - 歸檔失敗只印出來，不影響回應
        print(f"[gcs_archive] upload failed: {exc}", flush=True)
