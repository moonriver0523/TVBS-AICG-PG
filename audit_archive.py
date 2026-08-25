"""生成紀錄長期歸檔（本機磁碟版），供後台逐筆回查「誰、什麼時候、生了什麼」。

2026-08-25 的缺口：既有的兩套機制都留不住完整紀錄。
- `request_log.py` 只寫文字、預設 14 天就掃掉，而且寫在容器本機磁碟，重新部署即清空。
- `gcs_archive.py` 會存圖，但靠 GCP 自動授權，搬到 Zeabur／自有機器後不會啟用。

這裡走「掛持久卷 + 寫本機磁碟」的路：一次生成寫兩個檔（metadata JSON + 圖片），
檔名帶 request_id，可與 request_log 的 JSONL 互相對照。

設計取捨（沿用 request_log.py 與 gcs_archive.py 的既有慣例）：
- 設了 AUDIT_ARCHIVE_DIR 才啟用。不設就是舊行為，不影響本機開發與既有部署。
- 絕不讓歸檔失敗影響請求。所有對外函式都吞掉自己的例外。
- **不做自動清除。** 這是稽核用途，跟 request_log 的 14 天保留期不同：那是為了不讓
  使用者內容無限堆積，這裡的目的正是長期保留。要清理由人決定。
- 圖片不放進 `static/generated/`——那個前綴在 main.py 的密碼門豁免清單裡、對外公開，
  把全部同仁的產出丟進去等於不設防地任人列舉。這裡的檔案只由後台端點讀出。
"""

import base64
import json
import os
import pathlib
from datetime import datetime, timezone

ENABLED = os.getenv("AUDIT_ARCHIVE_DIR", "").strip() != ""
ARCHIVE_DIR = pathlib.Path(os.getenv("AUDIT_ARCHIVE_DIR", "").strip() or ".")

# 新聞原文完整留著才有稽核價值（input_filter 上限 5000 字，量級可接受）；
# prompt 是規則拼出來的，截斷即可，與 request_log.MAX_PROMPT_CHARS 一致。
MAX_PROMPT_CHARS = 4000


def _month_dir(now: datetime) -> pathlib.Path:
    """按月分資料夾。單一目錄塞進數萬個檔案會讓後台列檔變慢，按月切開就夠了。"""
    return ARCHIVE_DIR / f"{now:%Y-%m}"


def archive_generation(
    *,
    request_id: str,
    image_base64: str = "",
    mime_type: str = "",
    user_id: str = "",
    user_email: str = "",
    user_name: str = "",
    **metadata,
) -> None:
    """歸檔一次成功的生成（metadata + 圖片）。例外一律吞掉，不波及請求本身。"""
    if not ENABLED:
        return
    try:
        now = datetime.now(timezone.utc).astimezone()
        target = _month_dir(now)
        target.mkdir(parents=True, exist_ok=True)
        stem = f"{now:%Y%m%d-%H%M%S}-{request_id}"
        # 檔名理論上唯一（秒 + request_id），但稽核紀錄被無聲覆蓋是不可接受的失敗
        # 模式——寧可多一個檔名也不要少一筆紀錄。
        if (target / f"{stem}.json").exists():
            suffix = 2
            while (target / f"{stem}-{suffix}.json").exists():
                suffix += 1
            stem = f"{stem}-{suffix}"

        image_name = ""
        if image_base64:
            ext = "png" if "png" in (mime_type or "") else "jpg"
            image_name = f"{stem}.{ext}"
            (target / image_name).write_bytes(base64.b64decode(image_base64))

        if "prompt" in metadata and isinstance(metadata["prompt"], str):
            metadata["prompt"] = metadata["prompt"][:MAX_PROMPT_CHARS]

        record = {
            "ts": now.isoformat(),
            "request_id": request_id,
            # 身分三欄分開存：user_id 是 Clerk 的穩定識別碼（不會變，用來比對），
            # email／name 是給人看的（可能被改，不能當主鍵）。
            "user_id": user_id,
            "user_email": user_email,
            "user_name": user_name,
            "image_file": image_name,
            "mime_type": mime_type,
            **metadata,
        }
        (target / f"{stem}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001 - 歸檔失敗只印出來，不影響回應
        print(f"[audit_archive] write failed: {exc}", flush=True)


def list_records(*, month: str = "", limit: int = 200, user: str = "") -> list[dict]:
    """列出歸檔紀錄，最新的在前。供後台頁面使用。

    month 格式 `YYYY-MM`，空字串代表全部月份。user 會同時比對 user_email 與
    user_name 的子字串（後台的搜尋框直接吃使用者輸入，不要求精確相符）。
    """
    if not ENABLED:
        return []
    try:
        if month:
            month_dirs = [ARCHIVE_DIR / month]
        else:
            month_dirs = sorted(
                (p for p in ARCHIVE_DIR.iterdir() if p.is_dir()), reverse=True
            )
    except OSError:
        return []

    needle = user.strip().lower()
    records: list[dict] = []
    for directory in month_dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json"), reverse=True):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if needle:
                haystack = (
                    f"{record.get('user_email', '')} {record.get('user_name', '')}"
                ).lower()
                if needle not in haystack:
                    continue
            record["_month"] = directory.name
            records.append(record)
            if len(records) >= limit:
                return records
    return records


def available_months() -> list[str]:
    if not ENABLED:
        return []
    try:
        return sorted(
            (p.name for p in ARCHIVE_DIR.iterdir() if p.is_dir()), reverse=True
        )
    except OSError:
        return []


def read_image(month: str, filename: str) -> tuple[bytes, str] | None:
    """讀出歸檔的圖片。路徑元素做過白名單檢查，避免後台端點被拿來讀任意檔案。"""
    if not ENABLED:
        return None
    # 只允許檔名字元，擋掉 `..`／`/` 之類的路徑穿越。
    if not month.replace("-", "").isalnum():
        return None
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    path = ARCHIVE_DIR / month / filename
    try:
        # 再確認一次解析後的真實路徑仍在歸檔目錄內（防 symlink 繞過）。
        if not path.resolve().is_relative_to(ARCHIVE_DIR.resolve()):
            return None
        data = path.read_bytes()
    except (OSError, ValueError):
        return None
    mime = "image/png" if filename.endswith(".png") else "image/jpeg"
    return data, mime


def stats() -> dict:
    """後台首頁的概況數字。"""
    if not ENABLED:
        return {"enabled": False}
    total = 0
    users: set[str] = set()
    for record in list_records(limit=100000):
        total += 1
        label = record.get("user_email") or record.get("user_name") or "(未署名)"
        users.add(label)
    return {"enabled": True, "total": total, "users": sorted(users)}
