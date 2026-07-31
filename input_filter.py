"""Webhook／API 入口的前置過濾器：在任何付費 digest／生圖呼叫之前把關。

設計原則
--------
- `check_input()` 是唯讀的；`note_accepted()` 是唯一寫入者。讀寫分離讓同一則
  訊息通過兩個呼叫點（line_bot 先查、generate_news_image 再查）時，第一次
  檢查不會觸發第二次的 debounce。
- 頻率限制與重複偵測需要呼叫端身分（`client_id`）；沒給 `client_id` 時只做
  內容檢查（長度／亂碼／注入），這是 generate_news_image 內層的縱深防禦模式。
- 注入偵測只擋「針對系統 prompt 的攻擊」（覆寫指令、洩漏 prompt、jailbreak、
  角色重設、特殊 token）。編務指令（「指示: 完全依照文字…」「用手繪風」
  「標題放左邊」）不是注入，必須原封通過，交給消化端的
  USER INSTRUCTION 規則處理。若日後樣式誤傷編務指令，收窄樣式，不加白名單分支。

狀態限制（重要）
----------------
頻率限制與 dedup 狀態存在 process-local dict：
- 每次重啟／重新部署即清空；
- 不跨 uvicorn worker、不跨多實例——`--workers > 1` 時有效上限乘以實例數。
僅適用目前單一實例原型；公開對外前需改用 Redis／Postgres 等共享儲存。
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import deque
from dataclasses import dataclass

# ---- 門檻值 -----------------------------------------------------------------

# LINE 文字訊息上限本來就是 5000 字，這條實際保護的是 WorkCord 等 API 入口；
# 低於 pydantic 的 20000 上限，才能給友善訊息而非 422。
MAX_CHARS = 5000
MIN_CHARS = 15

# dedup 60 秒：目標是 LINE webhook 重送與手滑連按（都在幾秒內發生）。
# 不能設太長——重貼同一段文字是 LINE 使用者目前唯一的重骰方式（見 TODO.md）。
DEDUP_SECONDS = 60.0

# 生圖本來就要 30-120 秒，正常使用者拿到結果時 30 秒門檻多半已過，實際只擋連發。
MIN_INTERVAL_SECONDS = 30.0
RATE_WINDOW_SECONDS = 600.0
MAX_PER_WINDOW = 5

# ---- 結果型別 ---------------------------------------------------------------


@dataclass(frozen=True)
class FilterResult:
    accepted: bool
    reason_code: str = ""  # "" | too_short | too_long | rate_limited | duplicate | non_news
    user_message: str = ""  # 繁中，可直接原文回給使用者

    def __bool__(self) -> bool:
        return self.accepted


ACCEPTED = FilterResult(accepted=True)

REJECT_MESSAGES = {
    "too_short": "這段文字太短，AI 沒辦法消化成新聞圖卡。請貼上完整的新聞段落（約 15 字以上）。",
    "too_long": "文字太長了，請先擷取重點段落（5000 字以內）再貼一次。",
    "non_news": "我看不出這是新聞文字。請貼上新聞內容，我會幫你做成圖卡。",
    "duplicate": "這段文字剛剛已經生成過了，想重骰請稍等一下再貼一次。",
    "rate_limited": "你貼得有點快，請稍等約 30 秒再試一次，讓前一張先做完。",
}


def _reject(reason_code: str) -> FilterResult:
    return FilterResult(accepted=False, reason_code=reason_code, user_message=REJECT_MESSAGES[reason_code])


# ---- 內容檢查 ---------------------------------------------------------------

_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_ALNUM_RE = re.compile(r"[A-Za-z0-9]")
_LATIN_RUN_RE = re.compile(r"[A-Za-z]{4,}")

# 只匹配「針對系統 prompt」的攻擊措辭；編務指令天然不會命中任何一條。
# 三類樣式共用同一則回覆訊息（non_news），不揭露偵測到哪一種。
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"disregard\s+.{0,20}instructions", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"reveal\s+your\s+(prompt|instructions)", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"jailbreak", re.I),
    re.compile(r"<\|im_start\|>"),
    re.compile(r"```system"),
    re.compile(r"忽略(以上|前面|上面|所有|先前).{0,4}(指令|指示|規則)"),
    re.compile(r"(重複|複誦|洩漏|輸出|印出).{0,6}(系統)?(提示詞|提示|prompt)", re.I),
    re.compile(r"(系統|開發者)(提示詞|提示|指令)"),
]


def _looks_non_news(text: str) -> bool:
    stripped = "".join(text.split())
    if not stripped:
        return True
    informative = sum(1 for ch in stripped if _CJK_RE.match(ch) or _ALNUM_RE.match(ch))
    # 資訊性字元（中日韓／英數）比例過低 → 純表情符號、符號洗版
    if informative / len(stripped) < 0.3:
        return True
    # 完全沒有中文、又沒有像樣的英文單字 → 亂碼
    if not _CJK_RE.search(stripped) and not _LATIN_RUN_RE.search(text):
        return True
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


# ---- 頻率限制／重複偵測狀態（process-local，見模組 docstring 的限制） ------

_accept_times: dict[str, deque[float]] = {}
_last_text: dict[str, tuple[str, float]] = {}


def _normalise(text: str) -> str:
    return "".join(text.split())


def _digest_of(text: str) -> str:
    return hashlib.sha256(_normalise(text).encode("utf-8")).hexdigest()


def reset_state() -> None:
    """測試用：清空頻率限制與 dedup 狀態。"""
    _accept_times.clear()
    _last_text.clear()


# ---- 對外介面 ---------------------------------------------------------------


def check_input(text: str, *, client_id: str = "", now: float | None = None) -> FilterResult:
    """唯讀檢查。便宜的先跑；rate limit／dedup 僅在 client_id 非空時執行。"""
    if now is None:
        now = time.monotonic()

    if len(text) > MAX_CHARS:
        return _reject("too_long")
    if len(_normalise(text)) < MIN_CHARS:
        return _reject("too_short")
    if _looks_non_news(text):
        return _reject("non_news")

    if client_id:
        last = _last_text.get(client_id)
        if last is not None:
            last_digest, last_time = last
            if last_digest == _digest_of(text) and now - last_time < DEDUP_SECONDS:
                return _reject("duplicate")

        times = _accept_times.get(client_id)
        if times:
            if now - times[-1] < MIN_INTERVAL_SECONDS:
                return _reject("rate_limited")
            recent = sum(1 for t in times if now - t < RATE_WINDOW_SECONDS)
            if recent >= MAX_PER_WINDOW:
                return _reject("rate_limited")

    return ACCEPTED


def note_accepted(text: str, *, client_id: str, now: float | None = None) -> None:
    """記錄一次已接受的訊息。唯一的狀態寫入者；client_id 空字串時不記錄。"""
    if not client_id:
        return
    if now is None:
        now = time.monotonic()
    times = _accept_times.setdefault(client_id, deque(maxlen=MAX_PER_WINDOW * 2))
    times.append(now)
    _last_text[client_id] = (_digest_of(text), now)
