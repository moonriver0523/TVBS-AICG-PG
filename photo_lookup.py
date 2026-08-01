"""真人肖像的參考照片查詢（Wikipedia／Wikimedia）。

為什麼是 Wikimedia 而不是搜圖 API：
- 免費、不需金鑰，不增加營運成本與金鑰管理面積
- 授權明確（CC／公有領域），新聞台可用；一般搜圖 API 抓回來的圖版權不明
- 條目首圖（pageimages）對政商名人的覆蓋率夠用，查不到就退回不生成臉孔

刻意不做的事：
- 不做人臉比對、不驗證照片裡的人是不是本人。同名同姓、消歧義頁都可能回錯人，
  因此照片來源（條目網址、檔名）一律寫進 log 供人工回查，且肖像一律標示示意圖。
- 不快取。新聞素材每則不同，查詢量小，快取的複雜度換不到東西。
"""

from __future__ import annotations

import base64
import json
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import certifi

# Wikimedia 要求可辨識的 User-Agent，否則會擋（403）。
USER_AGENT = "TVBS-AICG-PG/1.0 (news CG generator; contact: moonriver0523@gmail.com)"

# 條目首圖抓這個寬度即可：參考圖只是給生圖模型看長相，不需要原尺寸。
THUMB_WIDTH = 800

# 防呆：超過這個大小就不用，避免把整個 payload 撐爆。
MAX_PHOTO_BYTES = 5 * 1024 * 1024

# 查詢順序：中文條目優先（台灣新聞的人物多半有中文條目且首圖較貼近本地認知），
# 查不到再退英文。
DEFAULT_LANGS = ("zh", "en")

_TIMEOUT = 10


@dataclass(frozen=True)
class ReferencePhoto:
    """一張可用的參考照片，連同它的出處（出處一定要能回查）。"""

    image_base64: str
    mime_type: str
    image_url: str
    source_page: str
    lang: str

    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.image_base64}"


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def _get(url: str, timeout: int) -> bytes | None:
    request = Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            return response.read(MAX_PHOTO_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError):
        # 查不到照片不是錯誤，是「這次沒有參考圖」——呼叫端會退回不生成臉孔。
        return None


def _lookup_lang(name: str, lang: str, timeout: int) -> ReferencePhoto | None:
    params = urlencode(
        {
            "action": "query",
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": THUMB_WIDTH,
            "titles": name,
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
        }
    )
    raw = _get(f"https://{lang}.wikipedia.org/w/api.php?{params}", timeout)
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    pages = (payload.get("query") or {}).get("pages") or []
    for page in pages:
        if page.get("missing"):
            continue
        thumbnail = page.get("thumbnail") or {}
        image_url = thumbnail.get("source")
        if not image_url:
            continue
        image_bytes = _get(image_url, timeout)
        if image_bytes is None or len(image_bytes) > MAX_PHOTO_BYTES:
            continue
        title = page.get("title") or name
        return ReferencePhoto(
            image_base64=base64.b64encode(image_bytes).decode("ascii"),
            mime_type=_guess_mime(image_url),
            image_url=image_url,
            source_page=f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
            lang=lang,
        )
    return None


def _guess_mime(url: str) -> str:
    lowered = url.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def find_reference_photo(
    name: str,
    *,
    langs: tuple[str, ...] = DEFAULT_LANGS,
    timeout: int = _TIMEOUT,
) -> ReferencePhoto | None:
    """依人名查一張參考照片；查不到回 None（呼叫端必須能接受沒有照片）。"""
    cleaned = (name or "").strip()
    if not cleaned:
        return None
    for lang in langs:
        photo = _lookup_lang(cleaned, lang, timeout)
        if photo is not None:
            return photo
    return None
