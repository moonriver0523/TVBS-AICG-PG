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

行程內 TTL 快取（B32，2026-09-15）：消化與生圖對同一人名會連查兩次。命中 15 分鐘、
查無 60 秒、上限 256 筆或 64 MB（以先到為準）從最舊淘汰。timeout 不進 key。呼叫端無感。

結構化查詢結果（F40，2026-09-16）：`find_reference_photo()` 只回得出「有沒有照片」，
分不出「這個人根本沒有維基條目」與「有條目、身分也驗過是人，只是條目沒有合格照片」——
這兩種在 F40 四層分流裡是不同層（第 3 層允許模型依語境自畫＋提示使用者，第 4 層才是
完全不安排人物）。`find_portrait_outcome()` 回傳 `PortraitLookupOutcome`，多帶一個
`entry_found` 欄位；`find_reference_photo()` 保留原樣signature/行為，改成只取
`.photo` 的相容 wrapper，呼叫端與既有測試不用改。快取也存完整 outcome。
"""

from __future__ import annotations

import base64
import json
import ssl
import threading
import time
from collections import OrderedDict
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

HIT_TTL_SECONDS = 15 * 60
MISS_TTL_SECONDS = 60
CACHE_MAX_ENTRIES = 256
CACHE_MAX_BYTES = 64 * 1024 * 1024

_CACHE_MISS = object()
_CACHE_LOCK = threading.Lock()
_CACHE: OrderedDict[tuple, tuple[float, "PortraitLookupOutcome"]] = OrderedDict()


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


@dataclass(frozen=True)
class PortraitLookupOutcome:
    """F40 四層分流要用的完整查詢結果，不只是「有沒有照片」。

    `entry_found`：任一候選名字／語系確認查到「這個人」的維基條目（Wikidata
    P31=Q5 驗過是人），不論那個條目有沒有合格首圖。`photo` 是 None 但
    `entry_found` 是 True＝F40 第 3 層（允許模型畫、要通知使用者）；
    兩者都是空／False＝第 4 層（連條目都沒有，畫面不安排這個人）。
    `matched_name`／`language`：命中時是哪個候選名字、哪個語系查到的，供落檔回查。
    """

    photo: ReferencePhoto | None
    entry_found: bool
    matched_name: str | None
    language: str | None


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


def _lookup_lang(name: str, lang: str, timeout: int) -> tuple[bool, ReferencePhoto | None]:
    """查單一語系：回傳 (entry_found, photo)。

    `entry_found` 只要求「確認是這個人的維基條目」（Wikidata P31=Q5 驗過），
    不要求有照片——F40 第 3 層就是靠這個旗標和「有沒有照片」分開才判得出來。
    """
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
        return False, None

    pages = (payload.get("query") or {}).get("pages") or []
    for page in pages:
        if page.get("missing"):
            continue
        qid = (page.get("pageprops") or {}).get("wikibase_item")
        # 沒有對應實體就不用——身分無從驗證時寧可不畫臉。實測 21 個人名，
        # 只要條目真的存在就一定有 wikibase_item，這條不會誤傷正常人物。
        if not qid or not _is_human(qid, timeout):
            continue

        # 走到這裡＝條目存在且確認是人：entry_found 成立，不論下面找不找得到照片。
        title = page.get("title") or name
        article_url = f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
        image_url = (page.get("thumbnail") or {}).get("source")
        source_page = article_url
        if not image_url:
            # 條目沒首圖才退而求其次用 P18，出處也跟著改標實體頁（圖是從那裡來的）
            image_url = _p18_url(qid, timeout)
            source_page = f"https://www.wikidata.org/wiki/{qid}"
        if not image_url:
            return True, None

        downloaded = _download(image_url, timeout)
        if downloaded is None:
            return True, None
        image_base64, mime_type = downloaded
        return True, ReferencePhoto(
            image_base64=image_base64,
            mime_type=mime_type,
            image_url=image_url,
            source_page=source_page,
            lang=lang,
        )
    return False, None


def _guess_mime(url: str) -> str:
    lowered = url.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def clear_photo_lookup_cache() -> None:
    """測試用：清掉行程內快取，避免題與題互相污染。"""
    with _CACHE_LOCK:
        _CACHE.clear()


def _cache_key(
    name: str,
    alt_names: tuple[str, ...] | list[str],
    langs: tuple[str, ...],
) -> tuple:
    primary = (name or "").strip()
    alts = tuple((alt or "").strip() for alt in alt_names if (alt or "").strip())
    return (primary, alts, tuple(langs))


def _cache_get(key: tuple):
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item is None:
            return _CACHE_MISS
        expires_at, value = item
        if time.monotonic() >= expires_at:
            del _CACHE[key]
            return _CACHE_MISS
        return value


def _entry_bytes(value: "PortraitLookupOutcome | None") -> int:
    if value is None or value.photo is None:
        return 0
    return len(value.photo.image_base64)


def _cache_nbytes() -> int:
    return sum(_entry_bytes(outcome) for _expires, outcome in _CACHE.values())


def _cache_put(key: tuple, value: "PortraitLookupOutcome") -> None:
    # 有照片或至少確認有條目（F40 第 3 層）都算「有意義的結果」，用長 TTL；
    # 兩者皆無（第 4 層／查無此人）才用短 TTL，理由同舊版註解：這種人有機會
    # 是還沒建條目或臺灣譯名還沒補上，短期內可能補上。
    informative = value is not None and (value.photo is not None or value.entry_found)
    ttl = HIT_TTL_SECONDS if informative else MISS_TTL_SECONDS
    expires_at = time.monotonic() + ttl
    with _CACHE_LOCK:
        if key in _CACHE:
            del _CACHE[key]
        _CACHE[key] = (expires_at, value)
        while _CACHE and (
            len(_CACHE) > CACHE_MAX_ENTRIES or _cache_nbytes() > CACHE_MAX_BYTES
        ):
            _CACHE.popitem(last=False)


# ---- 臺灣慣用譯名 → 維基查得到的條目名（B73，2026-09-16 使用者裁決）----
#
# 為什麼是人工表而不是自動解析：**兩種自動做法都實測否決過**。
#   ①中文全文搜尋——見下面 find_portrait_outcome 的 docstring，4 個譯名有 2 個
#     搜到完全不相干的條目（阿拉奇→阿布拉莫維奇、巴薩尼→威尼斯商人）。
#   ②Wikidata 別名搜尋（wbsearchentities，2026-09-16 實測）——在最該解決的那個
#     案例上最糟：查「鮑爾」回來的是蒙大拿州一個人口普查區、一位荷蘭軍官、
#     一位英國海軍上將和兩個姓氏，**傑羅姆·鮑威爾根本不在結果裡**；
#     「葉倫」「卡利巴夫」「阿拉奇」直接 0 筆。
# 猜錯人比查不到嚴重得多，所以這裡只收**逐條實查過、確認落在第 2 層（有條目有照片）**
# 的映射。新增條目前請照同樣方式驗過再寫進來。
#
# ⚠ 同名風險是這張表的固有代價，而且**程式無法自動化解**：`_is_human()` 只驗
# 「是不是人」，不驗「是不是對的那個人」。最典型的是「鮑爾」——臺灣財經新聞
# 幾乎一律指聯準會主席 Jerome Powell，但它同時也是 Colin Powell 的譯名。
# 這張表等於替這類短譯名**釘死一個解釋**，選的是臺灣新聞的壓倒性用法。
# 使用者 2026-09-16 在知悉此風險後仍裁定要做。
TW_PORTRAIT_NAME_ALIASES: dict[str, str] = {
    # 美國財經／政治（臺灣財經新聞最常出現，也是 B73 的起因）
    "鮑爾": "傑羅姆·鮑威爾",          # ⚠ 亦為 Colin Powell 的譯名，此處釘死聯準會主席
    "葉倫": "珍妮特·耶倫",
    "貝森特": "斯科特·貝森特",
    "盧比歐": "馬可·魯比奧",
    "范斯": "JD·萬斯",
    "奧特曼": "Sam Altman",           # 中文條目名對不上，英文條目查得到
    # 亞太
    "普拉伯沃": "普拉博沃·蘇比延多",
    "安瓦爾": "安瓦爾·易卜拉欣",       # ⚠ 安瓦爾是常見名，此處釘死馬來西亞首相
    "洪瑪奈": "Hun Manet",
    # 中東／歐洲（photo_lookup 舊註解列為「整類卡住」的那幾位）
    "卡利巴夫": "Mohammad Bagher Ghalibaf",
    "阿拉奇": "Abbas Araghchi",
    "瓦希迪": "Ahmad Vahidi",
    "蘇納克": "Rishi Sunak",
}


def resolve_tw_name_alias(name: str) -> str | None:
    """臺灣慣用譯名對應到的維基條目名；沒收錄就回 None。"""
    return TW_PORTRAIT_NAME_ALIASES.get((name or "").strip())


def find_portrait_outcome(
    name: str,
    *,
    alt_names: tuple[str, ...] | list[str] = (),
    langs: tuple[str, ...] = DEFAULT_LANGS,
    timeout: int = _TIMEOUT,
) -> PortraitLookupOutcome:
    """依人名查完整結果（F40 四層分流用）：照片、有沒有確認到條目、命中哪個候選／語系。

    `alt_names` 通常是英文原名（2026-08-18 加）。**臺灣譯名往往不是中文維基的
    條目名、也沒有重導向**——實測「卡利巴夫」「阿拉奇」「巴薩尼」「瓦希迪」四位
    中東／庫德人物在中文維基全部查無，但英文名 `Ahmad Vahidi` 查得到。整類國際
    新聞的肖像都卡在這裡。

    刻意不用「中文全文搜尋」補救：實測 4 個譯名裡 2 個搜到完全不相干的條目
    （阿拉奇→阿布拉莫維奇、巴薩尼→威尼斯商人），抓錯人比查不到嚴重得多。
    英文原名是結構化的事實，由消化端從新聞原文或既有知識給出，不用猜。

    找照片優先於找條目：只要任何候選／語系查到照片就立刻回傳；找不到照片時
    才退而求其次，看有沒有任何候選／語系至少確認到條目（entry_found），
    供 F40 第 3 層使用。兩者都沒有才是第 4 層（查無此人）。
    """
    key = _cache_key(name, alt_names, langs)
    cached = _cache_get(key)
    if cached is not _CACHE_MISS:
        return cached

    # 候選順序：原名 → 臺灣譯名對照表 → 英文原名。
    # 對照表排在英文名之前是刻意的：表裡的映射逐條實查過、確定命中第 2 層，
    # 而 alt_names 是消化端給的，可能空著也可能拼錯（main.py 的 prompt 明文禁止
    # 從常識填英文名，只准從原文抽取）。確定的先試。
    candidates = [
        candidate
        for candidate in [
            (name or "").strip(),
            resolve_tw_name_alias(name),
            *[(alt or "").strip() for alt in alt_names],
        ]
        if candidate
    ]
    # 同名去重但保留順序：中文優先（臺灣新聞的人物多半中文條目較貼近本地認知）
    seen: set[str] = set()
    entry_match: tuple[str, str] | None = None
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        for lang in langs:
            entry_found, photo = _lookup_lang(candidate, lang, timeout)
            if photo is not None:
                outcome = PortraitLookupOutcome(
                    photo=photo, entry_found=True, matched_name=candidate, language=lang
                )
                _cache_put(key, outcome)
                return outcome
            if entry_found and entry_match is None:
                entry_match = (candidate, lang)
    if entry_match is not None:
        outcome = PortraitLookupOutcome(
            photo=None, entry_found=True, matched_name=entry_match[0], language=entry_match[1]
        )
    else:
        outcome = PortraitLookupOutcome(
            photo=None, entry_found=False, matched_name=None, language=None
        )
    _cache_put(key, outcome)
    return outcome


def find_reference_photo(
    name: str,
    *,
    alt_names: tuple[str, ...] | list[str] = (),
    langs: tuple[str, ...] = DEFAULT_LANGS,
    timeout: int = _TIMEOUT,
) -> ReferencePhoto | None:
    """依人名查一張參考照片；查不到回 None（呼叫端必須能接受沒有照片）。

    相容 wrapper：只回傳 `find_portrait_outcome()` 的 `.photo`。既有呼叫端只在乎
    「有沒有照片」，不需要跟著改。要分辨「有條目沒照片」與「查無此人」的呼叫端
    請直接用 `find_portrait_outcome()`。
    """
    return find_portrait_outcome(
        name, alt_names=alt_names, langs=langs, timeout=timeout
    ).photo
