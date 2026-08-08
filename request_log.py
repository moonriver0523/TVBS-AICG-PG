"""成功請求落檔，供線上出事後回查。

2026-07-31 休達地圖案例暴露的缺口：失敗路徑才會 print，而且連原始新聞文字都沒
帶上，成功的請求完全不留痕跡。使用者拿著一張有問題的成圖回報時，後端沒有任何
紀錄可以說明那張圖是哪段文字、哪個消化結果、哪份 prompt 生出來的，只能請使用者
把原文再貼一次——若使用者已經找不到原文，這個案例就查不下去了。

因此把成功的請求也寫進 JSONL：一列一筆，含輸入、消化結果與最終 prompt。

設計取捨：
- 絕不讓記錄失敗影響請求。所有對外函式都吞掉自己的例外，記 log 是附帶效果，
  不是功能的一部分。
- 用日期切檔並自動清掉過期檔案。新聞原文屬於使用者內容，不該無限期堆在磁碟上，
  預設保留 14 天（LOG_RETENTION_DAYS 可調）。
- request_id 同時寫進成圖紀錄與 LINE 的圖檔名對照，讓「使用者傳來的一張圖」能
  回推到唯一一筆紀錄；只靠時間戳比對在同一秒有多筆請求時會對不準。

限制（與 input_filter 的狀態同一個性質）：寫的是本機磁碟，Render 之類的平台每次
重新部署都會清空，也不跨實例共享。要長期保存需改推外部儲存。
"""

import json
import os
import pathlib
import time
import uuid
from datetime import datetime, timezone

# 預設關閉會讓這個機制在最需要它的時候剛好沒開，所以預設開啟；
# 要停用設 REQUEST_LOG=0。
ENABLED = os.getenv("REQUEST_LOG", "1").strip() not in ("0", "false", "False")
LOG_DIR = pathlib.Path(
    os.getenv("REQUEST_LOG_DIR", str(pathlib.Path(__file__).parent / "logs"))
)
RETENTION_DAYS = int(os.getenv("REQUEST_LOG_RETENTION_DAYS", "14"))

# 新聞原文可能很長（filter 上限 5000 字），完整留著才有回查價值；但 prompt 是
# 規則拼出來的、每筆都差不多，留全文只會把檔案灌爆，截斷即可。
MAX_PROMPT_CHARS = 4000


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def _sweep_old_files() -> None:
    deadline = time.time() - RETENTION_DAYS * 86400
    for path in LOG_DIR.glob("generations-*.jsonl"):
        try:
            if path.stat().st_mtime < deadline:
                path.unlink()
        except OSError:
            pass


def _write(record: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _sweep_old_files()
    path = LOG_DIR / f"generations-{time.strftime('%Y%m%d')}.jsonl"
    record = {"ts": datetime.now(timezone.utc).astimezone().isoformat(), **record}
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_generation(
    *,
    request_id: str,
    source: str,
    news_text: str,
    style: str = "",
    structure: str = "",
    variable: str = "",
    prompt: str = "",
    chart_type: str = "",
    type_label: str = "",
    role: str = "",
    density: str = "",
    provider: str = "",
    image_model: str = "",
    prompt_version: str = "",
    client_id: str = "",
    portrait_subject: str = "",
    portrait_mode: str = "",
    portrait_photo_source: str = "",
) -> None:
    """記一筆成功的生成。任何例外都吞掉——記錄失敗不該波及請求本身。"""
    if not ENABLED:
        return
    try:
        _write(
            {
                "request_id": request_id,
                "source": source,
                "client_id": client_id,
                "provider": provider,
                "image_model": image_model,
                "prompt_version": prompt_version,
                "role": role,
                "density": density,
                "type_label": type_label,
                "chart_type": chart_type,
                "news_text": news_text,
                "style": style,
                "structure": structure,
                "variable": variable,
                # 肖像來源一定要能回查：自動查圖有抓到同名者照片的風險，
                # 事後複核靠的就是這個網址。
                "portrait_subject": portrait_subject,
                "portrait_mode": portrait_mode,
                "portrait_photo_source": portrait_photo_source,
                "prompt": prompt[:MAX_PROMPT_CHARS],
            }
        )
    except Exception as exc:  # noqa: BLE001 - 記 log 失敗只印出來，不影響回應
        print(f"[request_log] write failed: {exc}", flush=True)


def log_failure(
    *,
    request_id: str,
    source: str,
    news_text: str,
    error: str,
    style: str = "",
    structure: str = "",
    variable: str = "",
    prompt: str = "",
    chart_type: str = "",
    type_label: str = "",
    role: str = "",
    density: str = "",
    provider: str = "",
    client_id: str = "",
) -> None:
    """記一筆失敗的生成（例如上游安全過濾擋下）。

    2026-08-08 缺口：失敗只會 print，連原始新聞文字都沒留，事後排查不出是哪段
    文字/哪個 prompt 觸發拒絕。跟 log_generation 分開一支函式，避免混淆
    「這筆到底有沒有成功出圖」——查 log 時 ok=False 一眼就能篩出失敗案例。
    """
    if not ENABLED:
        return
    try:
        _write(
            {
                "request_id": request_id,
                "ok": False,
                "source": source,
                "client_id": client_id,
                "provider": provider,
                "role": role,
                "density": density,
                "type_label": type_label,
                "chart_type": chart_type,
                "news_text": news_text,
                "style": style,
                "structure": structure,
                "variable": variable,
                "prompt": prompt[:MAX_PROMPT_CHARS],
                "error": error[:MAX_PROMPT_CHARS],
            }
        )
    except Exception as exc:  # noqa: BLE001 - 記 log 失敗只印出來，不影響回應
        print(f"[request_log] write failed: {exc}", flush=True)


def log_image_file(*, request_id: str, image_name: str, client_id: str = "") -> None:
    """把成圖檔名接回 request_id。

    使用者回報時傳來的是 LINE 下載的圖（檔名已被 LINE 換掉），要靠這筆對照
    才能從 static/generated/ 的原始檔名回推到那次請求。
    """
    if not ENABLED:
        return
    try:
        _write(
            {
                "request_id": request_id,
                "source": "image-file",
                "client_id": client_id,
                "image_name": image_name,
            }
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[request_log] write failed: {exc}", flush=True)
