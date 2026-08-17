"""真人肖像的參考照片查詢（Wikipedia／Wikimedia）。

為什麼是 Wikimedia 而不是搜圖 API：
- 免費、不需金鑰，不增加營運成本與金鑰管理面積
- 授權明確（CC／公有領域），新聞台可用；一般搜圖 API 抓回來的圖版權不明
- 條目首圖（pageimages）對政商名人的覆蓋率夠用，查不到就退回不生成臉孔

2026-08-18 起加上 Wikidata 身分驗證（原本只有「標題對上就用首圖」）：
先用 `pageprops` 拿到條目對應的 Wikidata 實體，確認 `P31` 含 `Q5`（是人）才採用。
純標題比對會抓到同名但根本不是人的條目——實測「馬斯克」在 Wikidata 的第一個
同名實體是「馬斯克（姓氏）」，「賴清德」「卓榮泰」則各有「內閣」「彈劾案」同名條目。

刻意保留「條目首圖優先、`P18` 只當備援」的順序（不是反過來）：實測 `P18` 常常
比首圖差——金正恩的 P18 是與普欽的**合照**、柯文哲的 P18 是 2014 年舊照，而首圖
分別是單人照與 2026 年近照。合照當肖像參考正是會讓模型畫錯臉的輸入。這個順序
也讓本次改動純粹是**加上一道身分閘門**，現在查得到的人拿到的照片與改動前完全一樣。

刻意不做的事：
- 不做人臉比對、不驗證照片裡的人是不是本人。Wikidata 只能確認「這個條目講的是一個人」，
  不能確認「照片裡的人是他」，也不保證是單人照（習近平的首圖與 P18 都是會面合照）。
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


def _get_json(url: str, timeout: int) -> dict | None:
    raw = _get(url, timeout)
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _claims(qid: str, prop: str, timeout: int) -> list:
    """取實體的單一屬性。刻意不抓 Special:EntityData 整包——熱門人物（如川普）
    整包有數 MB，在 10 秒逾時下會間歇性失敗，而失敗＝安靜地不畫臉。"""
    params = urlencode(
        {"action": "wbgetclaims", "entity": qid, "property": prop, "format": "json"}
    )
    payload = _get_json(f"https://www.wikidata.org/w/api.php?{params}", timeout)
    return ((payload or {}).get("claims") or {}).get(prop) or []


def _is_human(qid: str, timeout: int) -> bool:
    """P31（性質）含 Q5（人類）才算人。一個實體可能有多個 P31，逐個看。"""
    for claim in _claims(qid, "P31", timeout):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and value.get("id") == "Q5":
            return True
    return False


def _p18_url(qid: str, timeout: int) -> str | None:
    """Wikidata 指定圖片（P18）的縮圖網址；沒有就 None。

    只在條目沒有首圖時才走這條——見模組說明，P18 常比首圖差。
    """
    for claim in _claims(qid, "P18", timeout):
        filename = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(filename, str) and filename:
            # 檔名含空白與非 ASCII，一定要 quote；Special:FilePath 會轉址到實際檔案。
            return (
                "https://commons.wikimedia.org/wiki/Special:FilePath/"
                f"{quote(filename)}?width={THUMB_WIDTH}"
            )
    return None


def _download(image_url: str, timeout: int) -> tuple[str, str] | None:
    image_bytes = _get(image_url, timeout)
    if image_bytes is None or len(image_bytes) > MAX_PHOTO_BYTES:
        return None
    return base64.b64encode(image_bytes).decode("ascii"), _guess_mime(image_url)


def _lookup_lang(name: str, lang: str, timeout: int) -> ReferencePhoto | None:
    # 一次要齊首圖與 Wikidata 實體 ID：pageimages 給圖、pageprops 給 wikibase_item。
    # redirects=1 是台灣譯名的命脈——「普欽」「澤倫斯基」都是靠維基重導向才對得上
    # 條目，Wikidata 的 wbsearchentities 沒有重導向機制，改用它會弄丟這些人。
    params = urlencode(
        {
            "action": "query",
            "prop": "pageimages|pageprops",
            "piprop": "thumbnail",
            "pithumbsize": THUMB_WIDTH,
            "titles": name,
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
        }
    )
    payload = _get_json(f"https://{lang}.wikipedia.org/w/api.php?{params}", timeout)
    if payload is None:
        return None

    pages = (payload.get("query") or {}).get("pages") or []
    for page in pages:
        if page.get("missing"):
            continue
        qid = (page.get("pageprops") or {}).get("wikibase_item")
        # 沒有對應實體就不用——身分無從驗證時寧可不畫臉。實測 21 個人名，
        # 只要條目真的存在就一定有 wikibase_item，這條不會誤傷正常人物。
        if not qid or not _is_human(qid, timeout):
            continue

        title = page.get("title") or name
        article_url = f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
        image_url = (page.get("thumbnail") or {}).get("source")
        source_page = article_url
        if not image_url:
            # 條目沒首圖才退而求其次用 P18，出處也跟著改標實體頁（圖是從那裡來的）
            image_url = _p18_url(qid, timeout)
            source_page = f"https://www.wikidata.org/wiki/{qid}"
        if not image_url:
            continue

        downloaded = _download(image_url, timeout)
        if downloaded is None:
            continue
        image_base64, mime_type = downloaded
        return ReferencePhoto(
            image_base64=image_base64,
            mime_type=mime_type,
            image_url=image_url,
            source_page=source_page,
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
