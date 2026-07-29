"""LINE Bot：使用者在 LINE 貼新聞文字 → AI 消化 → 生圖 → 回貼圖片。

流程與第一頁（網頁版）相同，差別在完全跑在後端：
    文字 → /api/generate 的消化邏輯 → news_prompt.build_prompt → 生圖 → 存檔 → push

三個 LINE 平台限制決定了這個設計：
1. 圖片訊息只吃「公開 HTTPS 網址」，不能傳 base64 → 生成後存到 static/ 由 PUBLIC_BASE_URL 對外。
2. 生圖 30-120 秒遠超過 replyToken 時效 → 先 reply「生成中」（免費），完成後改用 push。
3. Webhook 必須「先回 200 再處理」，否則 LINE 判逾時並重送 → 實際工作丟到背景任務。
"""

import base64
import hashlib
import hmac
import io
import json
import os
import pathlib
import time
import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from PIL import Image

from news_prompt import build_prompt, compose_variable

LINE_MESSAGE_API = "https://api.line.me/v2/bot/message"

# 生成圖的落地位置；由 main.py 掛成 /static 對外
STATIC_ROOT = pathlib.Path(__file__).resolve().parent / "static"
GENERATED_DIR = STATIC_ROOT / "generated"

# LINE 規定 previewImageUrl 上限 1MB，原圖動輒 1-2MB，一律另存縮圖
PREVIEW_WIDTH = 480
# 原型階段沒有儲存體管理，超過這個時數的舊圖在每次請求時順手清掉
KEEP_FILES_HOURS = 24

router = APIRouter(prefix="/line", tags=["line"])


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=503, detail=f"尚未設定 {name}")
    return value


def valid_signature(secret: str, body: bytes, signature: str) -> bool:
    """LINE 簽章：channel secret 對 raw body 做 HMAC-SHA256 後 base64。"""
    if not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    # 用 compare_digest 避免時間差比對洩漏簽章
    return hmac.compare_digest(expected, signature)


def _line_post(path: str, payload: dict) -> None:
    token = _env("LINE_CHANNEL_ACCESS_TOKEN")
    response = httpx.post(
        f"{LINE_MESSAGE_API}/{path}",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=20,
    )
    if response.status_code >= 400:
        # LINE 的錯誤訊息很明確（額度用盡、token 失效、網址非 HTTPS 等），原文印出來
        print(f"[line] {path} failed {response.status_code}: {response.text}", flush=True)
        response.raise_for_status()


def reply_text(reply_token: str, text: str) -> None:
    _line_post("reply", {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]})


def push_text(to: str, text: str) -> None:
    _line_post("push", {"to": to, "messages": [{"type": "text", "text": text}]})


def push_image(to: str, original_url: str, preview_url: str) -> None:
    _line_post(
        "push",
        {
            "to": to,
            "messages": [
                {
                    "type": "image",
                    "originalContentUrl": original_url,
                    "previewImageUrl": preview_url,
                }
            ],
        },
    )


def _sweep_old_files() -> None:
    if not GENERATED_DIR.exists():
        return
    deadline = time.time() - KEEP_FILES_HOURS * 3600
    for path in GENERATED_DIR.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < deadline:
                path.unlink()
        except OSError:
            pass


def save_image(raw: bytes, mime_type: str) -> tuple[str, str]:
    """存原圖與縮圖，回傳 (原圖檔名, 縮圖檔名)。"""
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    _sweep_old_files()

    stem = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    ext = "jpg" if "jpeg" in mime_type or "jpg" in mime_type else "png"
    original = GENERATED_DIR / f"{stem}.{ext}"
    original.write_bytes(raw)

    preview = GENERATED_DIR / f"{stem}-preview.jpg"
    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB")
        ratio = PREVIEW_WIDTH / image.width
        image = image.resize((PREVIEW_WIDTH, max(1, round(image.height * ratio))))
        image.save(preview, "JPEG", quality=80)

    return original.name, preview.name


def generate_and_push(reply_token: str, to: str, news_text: str) -> None:
    """背景任務：先秒回收到，再跑完整生成流程並 push 圖片。

    main 匯入本模組的 router，這裡若在頂層 import main 會形成循環匯入，
    故延後到實際執行時才 import。
    """
    from main import (
        AUTO_TYPE_LABEL,
        GenerateRequest,
        ImageGenerateRequest,
        generate,
        generate_image,
    )

    try:
        reply_text(reply_token, "收到！AI 消化與生圖中，約 30-120 秒，完成後回傳圖片。")
    except Exception as exc:  # noqa: BLE001 - 秒回失敗不該中斷後續生成
        print(f"[line] ack reply failed: {exc}", flush=True)

    try:
        # 原型階段固定：記者角色、標準密度、圖表類型仍由 AI 自動判斷
        digest = generate(
            GenerateRequest(
                news_text=news_text,
                type_label=AUTO_TYPE_LABEL,
                role="記者",
                density="standard",
            )
        )
        provider = os.getenv("LINE_IMAGE_PROVIDER", "gemini")
        prompt = build_prompt(
            role="記者",
            engine=provider,
            type_label=digest.chart_type or "資料圖表",
            style=digest.style,
            structure=digest.structure,
            variable=compose_variable(digest.variable),
        )
        image = generate_image(ImageGenerateRequest(prompt=prompt, provider=provider))
        raw = base64.b64decode(image.image_data_base64)
        original_name, preview_name = save_image(raw, image.mime_type)

        base_url = _env("PUBLIC_BASE_URL").rstrip("/")
        push_image(
            to,
            f"{base_url}/static/generated/{original_name}",
            f"{base_url}/static/generated/{preview_name}",
        )
    except HTTPException as exc:
        _notify_failure(to, str(exc.detail))
    except Exception as exc:  # noqa: BLE001 - 背景任務不能讓例外靜默消失
        print(f"[line] generate failed: {exc}", flush=True)
        _notify_failure(to, "生成失敗，請稍後再試")


def _notify_failure(to: str, detail: str) -> None:
    try:
        push_text(to, f"⚠️ {detail}")
    except Exception as exc:  # noqa: BLE001
        print(f"[line] failure notice failed: {exc}", flush=True)


def target_of(event: dict) -> str:
    """回覆對象：群組／多人聊天室要回到該群，1:1 才回給個人。

    群組訊息的 source 會同時帶 groupId 與發話者的 userId，
    userId 優先會把圖私訊給發話者而不是回到群組，故 group/room 先判。
    """
    source = event.get("source") or {}
    return source.get("groupId") or source.get("roomId") or source.get("userId") or ""


@router.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str = Header(default=""),
) -> dict:
    body = await request.body()
    if not valid_signature(_env("LINE_CHANNEL_SECRET"), body, x_line_signature):
        raise HTTPException(status_code=403, detail="簽章驗證失敗")

    try:
        events = (json.loads(body or b"{}") or {}).get("events") or []
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="webhook 內容不是合法 JSON") from None

    for event in events:
        message = event.get("message") or {}
        text = (message.get("text") or "").strip()
        target = target_of(event)
        # 只處理文字訊息；貼圖／圖片／加好友等事件直接略過
        if event.get("type") != "message" or message.get("type") != "text":
            continue
        if not text or not event.get("replyToken") or not target:
            continue
        background_tasks.add_task(generate_and_push, event["replyToken"], target, text)

    # 一律先回 200，實際工作在背景跑，避免 LINE 判逾時重送
    return {"ok": True}
