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
import re
from datetime import datetime, timezone

ENABLED = os.getenv("AUDIT_ARCHIVE_DIR", "").strip() != ""
ARCHIVE_DIR = pathlib.Path(os.getenv("AUDIT_ARCHIVE_DIR", "").strip() or ".")

# 新聞原文完整留著才有稽核價值（input_filter 上限 5000 字，量級可接受）；
# prompt 截斷上限，與 request_log.MAX_PROMPT_CHARS 一致（理由與實測寫在那一支）。
# 2026-09-16 隨之從 4000 調到 24000：兩邊不同步的話，後台看到的 prompt 會比 JSONL 短，
# 回查時會誤以為資料沒寫進去。
MAX_PROMPT_CHARS = 24000

# 失敗摘要只留可分組的短句。traceback 與金鑰不能進磁碟。
MAX_ERROR_SUMMARY_CHARS = 300

STATUS_OK = "ok"
STATUS_FAILED = "failed"

_REDACT_RE = re.compile(
    r"(?i)"
    r"(?:authorization\s*[:=]\s*(?:bearer\s+)?)\S+"
    r"|(?:bearer\s+)[A-Za-z0-9._\-]+"
    r"|(?:(?:api[_-]?key|secret|password|token)\s*[:=]\s*)\S+"
    r"|sk-[A-Za-z0-9_-]{10,}"
    r"|AIza[A-Za-z0-9_-]{10,}"
)
_TRACE_LINE_RE = re.compile(
    r"^\s*(?:File \".+\", line \d+|Traceback \(most recent call last\):)"
)


def sanitize_error_summary(
    text: str, *, max_chars: int = MAX_ERROR_SUMMARY_CHARS
) -> str:
    """截短、去掉 traceback、蓋掉金鑰／Authorization。供寫入端與 retry note 共用。"""
    raw = str(text or "")
    if "Traceback (most recent call last)" in raw:
        lines = [line for line in raw.splitlines() if line.strip()]
        raw = lines[-1] if lines else raw
    kept = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not _TRACE_LINE_RE.match(line)
    ]
    cleaned = " ".join(kept) if kept else raw.replace("\n", " ")
    cleaned = _REDACT_RE.sub("[redacted]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    if max_chars <= 1:
        return cleaned[:max_chars]
    return cleaned[: max_chars - 1] + "…"


def record_type(record: dict) -> str:
    """後台類型欄的取值順序。舊紀錄若漏帶 type_label，退到 source 仍列得出來。"""
    return (
        record.get("type_label")
        or record.get("chart_type")
        or record.get("source")
        or "（未分類）"
    )


def record_status(record: dict) -> str:
    """舊紀錄沒有 status 欄＝當時只寫成功，視為 ok。讀取失敗不當生成失敗。"""
    status = record.get("status") or STATUS_OK
    return STATUS_FAILED if status == STATUS_FAILED else STATUS_OK


# 2026-09-20（F30／F39 正式站實查）：這是「這筆是不是追加修改」的答案，跟
# record_type() 回答的「這張圖畫的是什麼內容」是兩件事，不能混在同一欄。正式站
# 09-18～09-20 91 筆裡追加修改（/api/images/refine，prompt 開頭是
# IMAGE REFINE RULES）實際有 36 筆，但後台 type 欄只有 1 筆標成 web-refine，
# 其餘 35 筆都被 `_enrich_archive_fields`／`_recall_digest()` 回填成「使用者最近
# 一次消化」的內容分類（例如「自動判斷」「資料圖表」）——那個回填對 record_type()
# 要回答的問題（這張圖的內容分類）是正確的，只是不該拿來判斷「這是不是追加修改」。
#
# 用 source 判斷而不是 prompt 前綴：prompt 會被截斷（B29）、也可能改寫，source
# 是寫入當下就決定、不受任何下游回填影響的欄位，而且從 f24dba1 上線起每一筆都有，
# 對正式站既有的 360 筆歷史紀錄立刻生效，不需要回溯遷移或新增欄位。
_REFINE_SOURCES = ("web-refine",)
_DIGEST_SOURCES = ("digest", "hybrid-digest", "cover-titles")


def record_action(record: dict) -> str:
    """這筆是「新生成」「追加修改」「消化」還是「合成」——見上方模組層級註解。

    `action` 明確帶值時直接採用（目前沒有寫入端會帶，留給未來需要更細分類時用，
    不必再改這支函式的 fallback 表）；沒帶就照 source 的字面值／前綴推。
    """
    action = record.get("action")
    if action:
        return str(action)
    source = str(record.get("source") or "")
    if source in _REFINE_SOURCES:
        return "追加修改"
    if source in _DIGEST_SOURCES:
        return "消化"
    if source.startswith("editor-yt-overlay"):
        # 直標是純 Pillow 壓字（80ms 級），不呼叫生圖模型，耗時／逾時的判斷
        # 天生就跟其他要打生圖 API 的路徑（十秒到分鐘級）不是同一個量級，
        # 獨立分類讓後台看得出這兩種母體不能套同一套故障率／逾時門檻
        # （2026-09-20 正式站實查提醒）。
        return "合成"
    return "新生成"


def record_cursor(record: dict) -> str:
    return f"{record.get('ts', '')}|{record.get('request_id', '')}"


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
    """歸檔一次生成結果（成功帶圖；失敗不要求圖片）。例外一律吞掉，不波及請求本身。"""
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
        if "error_summary" in metadata and isinstance(metadata["error_summary"], str):
            metadata["error_summary"] = sanitize_error_summary(metadata["error_summary"])

        status = metadata.pop("status", None) or (
            STATUS_FAILED if metadata.get("error_type") or metadata.get("error_summary") else STATUS_OK
        )
        if status != STATUS_FAILED:
            status = STATUS_OK

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
            "status": status,
            **metadata,
        }
        (target / f"{stem}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001 - 歸檔失敗只印出來，不影響回應
        print(f"[audit_archive] write failed: {exc}", flush=True)


def _iter_month_dirs(*, month: str = "") -> list[pathlib.Path]:
    if month:
        return [ARCHIVE_DIR / month]
    try:
        return sorted(
            (p for p in ARCHIVE_DIR.iterdir() if p.is_dir()), reverse=True
        )
    except OSError:
        return []


def _iter_records(*, month: str = "", user: str = "", type_value: str = ""):
    """由新到舊產出可讀的紀錄。JSON 讀取失敗就跳過，不當生成失敗。"""
    needle = user.strip().lower()
    wanted_type = type_value.strip()
    for directory in _iter_month_dirs(month=month):
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
            if wanted_type and record_type(record) != wanted_type:
                continue
            record["_month"] = directory.name
            record["_cursor"] = record_cursor(record)
            yield record


def list_records(
    *,
    month: str = "",
    limit: int = 200,
    user: str = "",
    offset: int = 0,
    cursor: str = "",
    type_value: str = "",
) -> list[dict]:
    """列出歸檔紀錄，最新的在前。供後台頁面使用。

    month 格式 `YYYY-MM`，空字串代表全部月份。user 會同時比對 user_email 與
    user_name 的子字串（後台的搜尋框直接吃使用者輸入，不要求精確相符）。

    offset／cursor 用來分頁；預設 limit=200 維持舊呼叫相容。cursor 是上一頁
    最後一筆的 `ts|request_id`，找到後從下一筆開始取。讀取失敗的檔案直接跳過。
    """
    if not ENABLED:
        return []
    if offset < 0:
        offset = 0
    skipped = 0
    seen_cursor = not cursor
    records: list[dict] = []
    for record in _iter_records(month=month, user=user, type_value=type_value):
        if not seen_cursor:
            if record.get("_cursor") == cursor:
                seen_cursor = True
            continue
        if skipped < offset:
            skipped += 1
            continue
        records.append(record)
        if limit and len(records) >= limit:
            return records
    return records


def summarize_records(
    *, month: str = "", user: str = "", type_value: str = ""
) -> dict:
    """完整篩選區間的成功／失敗／全部。後台算失敗率不能只拿最新 200 筆當分母。"""
    if not ENABLED:
        return {"total": 0, "ok": 0, "failed": 0, "types": []}
    total = ok = failed = 0
    types: set[str] = set()
    # 類型下拉要看篩選前的全集，否則選了某一類之後其他類會從選單消失。
    for record in _iter_records(month=month, user=user):
        types.add(record_type(record))
        if type_value.strip() and record_type(record) != type_value.strip():
            continue
        total += 1
        if record_status(record) == STATUS_FAILED:
            failed += 1
        else:
            ok += 1
    return {
        "total": total,
        "ok": ok,
        "failed": failed,
        "types": sorted(types),
    }


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
    summary = summarize_records()
    users: set[str] = set()
    for record in _iter_records():
        label = record.get("user_email") or record.get("user_name") or "(未署名)"
        users.add(label)
    return {
        "enabled": True,
        "total": summary["total"],
        "ok": summary["ok"],
        "failed": summary["failed"],
        "users": sorted(users),
    }
