import base64
import concurrent.futures
import copy
import contextvars
import datetime
import hmac
import io
import json
import os
import pathlib
import re
import secrets
import ssl
import threading
import time
import unicodedata
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

# Langfuse 觀測（2026-09-14）：langfuse.openai 的 OpenAI 是原生 SDK 的直接替換，
# 換掉這一個名字，底下 20 個呼叫點一行都不用改，就會自動記錄每次呼叫的
# model／token／成本／延遲，並綁到發起請求的同仁（見 clerk_login_gate）。
#
# 為什麼不自己記 token：各家模型計價不同且會變動，自行維護價目表必然過期。
# Langfuse 內建價目表，且公司其他工具（EchoScript）已在同一個實例上，
# 日後要比較各工具的 AI 支出才有共同基準。
#
# 例外類別仍從原生 openai 匯入——langfuse.openai 只包裝 client，不保證
# re-export 那些類別，從它拿會在未來版本悄悄壞掉。
# 沒裝 langfuse（本機開發、未設定的環境）就退回原生，行為完全不變。
try:
    from langfuse.openai import OpenAI
except ImportError:
    from openai import OpenAI
from PIL import Image
from pydantic import BaseModel, Field

import admin_console
import audit_archive
import clerk_auth
import compose
import creativity
import editor_formats
import gcs_archive
import map_lookup
import photo_lookup
import name_aliases
import request_log
import safe_area_spec
import safe_content_gate
import safe_frame
from input_filter import check_input, note_accepted
from news_prompt import (
    broadcast_hole_layout_rules,
    localise_disclaimer_position,
    MAP_TYPE_LABEL,
    PORTRAIT_MODES,
    PROMPT_VERSION,
    USER_REFERENCE_ASIS_DIGEST_RULES,
    USER_REFERENCE_ASIS_MULTI_RULES_TEMPLATE,
    USER_REFERENCE_AIEDIT_FUSION_RULES_TEMPLATE,
    USER_REFERENCE_AIEDIT_INSTRUCTION_TEMPLATE,
    USER_REFERENCE_MODES,
    USER_REFERENCE_NO_DISCLAIMER_RULES,
    USER_REFERENCE_YT_SLOT_PLACEMENT_TEMPLATE,
    build_prompt,
    build_refine_prompt,
    compose_variable,
    ensure_final_image_baseline,
)

load_dotenv()

# Digest（生成 Prompt）預設走 OpenRouter，與生圖共用同一把 OPENROUTER_API_KEY；
# 未設定 OPENROUTER_API_KEY 時退回 OpenAI 原生直連。
#
# DIGEST_BACKEND=gemini（2026-07-30 暫時啟用）：OpenRouter 的「Key limit exceeded
# (weekly limit)」是整把 key 的帳號等級週配額，不分底層請求的是 GPT 還是 Gemini
# 模型——實測透過 OpenRouter 打 google/gemini-3.5-flash 一樣被 403 擋下，
# 「OpenRouter 的 Gemini 額度還能用」不成立。真正繞得過去的路是用 GEMINI_API_KEY
# 直連 Google 官方 OpenAI 相容端點（與 OpenRouter 完全獨立的一把 key、一條配額）。
# 端點與模型名稱已用結構化 JSON schema 實測驗證可用：v1beta/openai/、
# gemini-3.5-flash／gemini-3.6-flash 皆可正確回傳 strict JSON。
# OpenRouter 恢復後，把 .env 的 DIGEST_BACKEND 拿掉或設回 openrouter 即可切回。
_gemini_key = os.getenv("GEMINI_API_KEY")
_openrouter_key = os.getenv("OPENROUTER_API_KEY")
DIGEST_BACKEND = os.getenv(
    "DIGEST_BACKEND", "openrouter" if _openrouter_key else "native"
).strip()

# SDK 預設 max_retries=2。消化外層 DIGEST_ATTEMPTS=5 已經在重試，SDK 再重試會讓
# payload timeout=90 實際變成 270 秒，第一次 attempt 就能撞上 Cloud Run 300 秒硬砍
# （B31）。暫時性網路錯誤改由外層迴圈吸收，不是關掉重試。三個後端同一把尺子。
OPENAI_MAX_RETRIES = 0

if DIGEST_BACKEND == "gemini":
    if not _gemini_key:
        raise RuntimeError("DIGEST_BACKEND=gemini 但未設定 GEMINI_API_KEY")
    openai_client = OpenAI(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=_gemini_key,
        max_retries=OPENAI_MAX_RETRIES,
    )
    DEFAULT_DIGEST_MODEL = os.getenv("GEMINI_DIGEST_MODEL", "gemini-3.6-flash")
    DEFAULT_TITLE_BREAK_MODEL = DEFAULT_DIGEST_MODEL   # flash 本來就快
# 2026-09-03：這裡原本寫 `elif _openrouter_key:`，等於只要環境裡有一把
# OPENROUTER_API_KEY 就一定走 OpenRouter，DIGEST_BACKEND=native 完全沒有效果——
# 上面那段註解講的「設回 openrouter 即可切回」暗示這個變數是說了算的，實際上
# 切不回原生。使用者的 OPENROUTER_API_KEY 同時存在於 .env 與 Windows 使用者
# 環境變數，光在 .env 註解掉沒有用，因此改成 DIGEST_BACKEND 明說時聽它的。
elif DIGEST_BACKEND == "openrouter" and _openrouter_key:
    openai_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=_openrouter_key,
        max_retries=OPENAI_MAX_RETRIES,
    )
    # 2026-09-16 D21 裁決：主模型從 anthropic/claude-sonnet-5 換成
    # google/gemini-3.8-flash。四輪 ×10 次同稿實測（見
    # docs/交辦-20260916-D21改effort換Gemini.md）：sonnet-5 現況（reasoning.max_tokens）
    # 5/10 成功、131 秒平均、3 次截斷；sonnet-5+effort=low 7/10、18 秒；
    # gemini-3.8-flash+effort=low 9/10、6 秒、0 截斷、0 簡體，全面勝出，
    # 第二輪 10 則不同真實稿再驗一次（9/10、4-8 秒、耗時對稿長不敏感）泛化通過。
    # 退路：resolve_digest_model() 讀 DIGEST_MODEL／OPENAI_DIGEST_MODEL 環境變數
    # 覆寫，設回 anthropic/claude-sonnet-5 即可三分鐘內退回 Claude，不用改程式碼
    # （見該函式 2026-09-13 的「帶 / 的 slug 只在走 openrouter 時才採用」防呆，
    # 這條退路依賴它，不能破壞）。
    DEFAULT_DIGEST_MODEL = "google/gemini-3.8-flash"
    # 斷句原本走 openai/gpt-5.4-mini（2026-09-14 使用者裁決），2026-09-16 補做斷句
    # 自己的實測後換成 gemini（使用者裁定「要改就改到位」）。.env 與線上都是
    # OpenRouter 後端，只改原生分支等於沒改。
    #
    # 實測：19 則真實封面標題（後台 2026-09 紀錄的 news 欄）、**每則一次呼叫**
    # （production 的 apply_title_break_hints 就是這個粒度，一次塞 17 段會把耗時
    # 與輸出長度灌水），兩模型各 78 次、共 108 段：
    #   mini  ：呼叫層 0 次失敗，但**段被判不採用 29/108**，最終只有 73% 拿到模型斷句
    #   gemini：呼叫層 6 次失敗（4 逾時＋2 finish=error），**段最終 87% 拿到模型斷句**
    #   耗時中位 mini 3.1 秒 → gemini 2.2 秒
    # 代價說清楚：**硬失敗率從 0% 變 7.7%**，而斷句這條線沒有重試迴圈，失敗就直接
    # 退回規則斷行。但 mini 的「回了卻被判不採用」也同樣退回規則，兩者對使用者
    # 是同一件事，算總帳 gemini 淨勝 14 個百分點。明細
    # D:\Downloads\AICG\後台紀錄\20260916\F_斷句模型對照*.jsonl。
    #
    # ⚠ 連帶待裁：gemini 的 4 次逾時全部卡在 TITLE_BREAK_TIMEOUT_SECONDS=8.0 這道牆
    # （中位 2.2 秒、p90 5.5 秒），放寬到 10 秒應能回收大部分，但那是另一個決定，
    # 沒有使用者裁示不動。
    DEFAULT_TITLE_BREAK_MODEL = "google/gemini-3.8-flash"
else:
    openai_client = OpenAI(max_retries=OPENAI_MAX_RETRIES)
    # 2026-09-13：原生預設從 gpt-5.6-terra 換成 gpt-5.5。terra 在使用者 key 上
    # 其實存在，但 2026-09-05 已實測會頻道洩漏（.env 註解與 test_digest_quality）；
    # 5.5 是 /v1/models 列得到且 chat.completions 打得通的，內容乾淨與否待實拍。
    DEFAULT_DIGEST_MODEL = "gpt-5.5"
    # 標題斷句（2026-09-14 使用者裁決）：分詞不需要推理模型。實測同一組標題
    # gpt-5.5 8.6 秒（reasoning_tokens=512）、gpt-5.4-mini 4.6 秒、gpt-5.4-nano 2.0 秒
    # （皆 reasoning_tokens=0），mini 與 5.5 切出來的詞組一樣，取 mini。
    DEFAULT_TITLE_BREAK_MODEL = "gpt-5.4-mini"


def resolve_title_break_model() -> str:
    """標題斷句用的模型：TITLE_BREAK_MODEL → 後端預設的小模型。

    刻意**不**繼承 DIGEST_MODEL／OPENAI_DIGEST_MODEL：那兩個是主消化的覆寫，
    可能是 OpenRouter slug（見 resolve_digest_model 的 2026-09-13 真因），而且
    這是獨立覆寫、獨立回退的一條線，不該因為主消化換模型就被連動牽著走。

    2026-09-16：預設值已經跟著換成 gemini-3.8-flash（依斷句自己的 156 次實測，
    見 DEFAULT_TITLE_BREAK_MODEL 定義處），但**刻意不改成讀 DIGEST_MODEL**——
    兩條線要能分開回退：主消化出事時把 DIGEST_MODEL 設回 Claude，斷句不必跟著動；
    斷句出事時設 TITLE_BREAK_MODEL=openai/gpt-5.4-mini 即可，主消化不受影響。

    2026-09-16 Codex 複查抓到：這裡原本沒有 resolve_digest_model() 那道「帶 / 的
    slug 只在真的走 openrouter 時才採用」防呆，而上面那句回退指引推薦的
    `openai/gpt-5.4-mini` 正是一個 OpenRouter slug——在 native／Gemini 後端照單
    全收就會把它送進 api.openai.com，**斷句必然失敗、每張封面都退回規則斷行，
    而且因為失敗被吃掉只印一行 log，不會有人發現**。補上同一道防呆。
    """
    override = (os.getenv("TITLE_BREAK_MODEL") or "").strip()
    if not override:
        return DEFAULT_TITLE_BREAK_MODEL
    on_openrouter = "openrouter" in str(getattr(openai_client, "base_url", ""))
    if "/" in override and not on_openrouter:
        return DEFAULT_TITLE_BREAK_MODEL
    return override


def resolve_digest_model() -> str:
    """回傳這次消化要用的模型：DIGEST_MODEL → OPENAI_DIGEST_MODEL → 後端預設。

    2026-09-13 真因：.env 的 `DIGEST_MODEL=anthropic/claude-sonnet-5` 是 OpenRouter
    slug，`load_dotenv()` 後五處 `os.getenv("DIGEST_MODEL")` 不分後端照單全收，
    本機 `DIGEST_BACKEND=native` 時就把這串送進 api.openai.com → 400
    「invalid model ID」，畫面描述整段走退路、指令欄被丟掉。之前快照誤判成
    「gpt-5.6-terra 不存在」。

    規則：帶 `/` 的 OpenRouter 式 slug 只在 client 真的指向 openrouter 時才採用；
    否則當作沒設，退回該後端的預設。判斷看 `openai_client.base_url` 而不是
    `DIGEST_BACKEND` 字串——`DIGEST_BACKEND=openrouter` 但沒 key 也會落到原生
    client，那時字串仍寫 openrouter。讀模組全域而非重讀 env，測試才 patch 得到。
    """
    override = (os.getenv("DIGEST_MODEL") or os.getenv("OPENAI_DIGEST_MODEL") or "").strip()
    if not override:
        return DEFAULT_DIGEST_MODEL
    on_openrouter = "openrouter" in str(getattr(openai_client, "base_url", ""))
    if "/" in override and not on_openrouter:
        return DEFAULT_DIGEST_MODEL
    return override

# Gemini 的 OpenAI 相容端點有大量『看不見』的內部思考 token——實測一個一句話的
# 玩具範例，可見的 completion_tokens 只有 51，但 total_tokens 高達 613
# （差額都是思考 token）。用平常給 OpenRouter/原生 OpenAI 的 max_tokens
# （1200-1500）打 Gemini 幾乎必然被思考 token 吃光、正文遭截斷、JSON 解析失敗。
# 真實消化內容（含完整格式化的 style/structure/variable 文字）遠比玩具範例長，
# 這裡抓一個寬裕的下限，只在走 Gemini 這條路徑時生效，不影響其他 backend。
GEMINI_DIGEST_MIN_TOKENS = 6000

# 消化輸出上限。地圖類要寫的東西本來就比別類多——MAP_ACCURACY_RULES 要求雙層地圖
# （定位總覽 + 細部圖）、每張圖各自的涵蓋範圍、指北針與比例尺、多個地名的經緯度，
# 光 structure 一欄的英文就能吃掉一般預算。2026-07-31 休達案例實測：地圖類用 1500
# 幾乎每次第一輪都 finish_reason=length 被截斷，重試又在長度壓力下吐出摻雜垃圾字元
# 的 variable（語法上仍是合法 JSON，因此舊版直接收下送去生圖）。分開給預算是治本。
# 上限是天花板不是用量，只有真的寫出來的 token 才計費，因此寧可寬裕。
# 3000 實測仍會截斷（同案例），拉到 6000 比照 GEMINI_DIGEST_MIN_TOKENS 的量級。
#
# 2026-09-05 二度修訂。當天稍早曾把地圖類收到 3000，理由是「那些截斷其實是
# gpt-5.6-terra 脫軌後吐空白填到天花板，預算只是脫軌的成本上限」——脫軌那半段
# 沒錯（見 docs/error-cases/2026-09-05-消化模型頻道洩漏-賭博垃圾與空白填充.md），
# 但推論錯了，而且量測只在**記者**角色上做過。換 claude-sonnet-5 上線後，
# 編輯＋地圖 5 次 attempt 全部 budget=3000 ratio=1.00 finish=length，其中兩次
# raw content 整個空白——3000 在吐出第一個字之前就被思考 token 用光。
#
# 用 8000 的寬鬆上限量出真實分布（記者／編輯 × 自動判斷／資料圖表，16 次全過）：
#   實際寫出來的內容非常穩定，872-1259 token；
#   會爆的是思考，560-3140，編輯＋自動判斷那一格最兇；
#   total 因此落在 1591-4258。
# 也就是說預算對**不會脫軌的模型**就是真的要夠，不能拿脫軌的成本上限來訂。
# 這裡取 total 觀測最大值再留約四成餘裕。上限是天花板不是用量，只有真的寫出來
# 的 token 才計費，寧可寬裕——省下的那點錢遠不值一次 5 連截斷的 502。
#
# 2026-09-05 傍晚第三次調整。當天累積的規則把 system prompt 從 23,795 字元推到
# 28,105，**寫出來的內容完全沒變**（856-1361 token，與早上量的一樣），暴漲的
# 全是思考：早上 560-3140，傍晚 603-4873。編輯＋自動判斷的 total 量到 6042，
# 已經超過當時的 6000 預算，所以那類稿必然偶爾整個截斷（實測 raw content 空字串、
# 重試後 269 秒才回應）。餘裕要抓在思考上而不是正文上：思考量會隨規則增加而漲，
# 正文不會。這裡照 total 觀測最大值再留約六成。
#
# 2026-09-16 依 D21 甲案調整：DIGEST_MAX_TOKENS 6000→12000，
# MAP_DIGEST_MAX_TOKENS 10000→16000。思考常吃滿舊上限、正文寫不出來；
# timeout／attempt 不動。
# （原本這行還寫「reasoning headroom 不動」，2026-09-16 D21 已把
# DIGEST_REASONING_HEADROOM 整組刪除、改送 reasoning.effort，該詞已無對應物。）
# 地圖必須維持大於一般——這是 2026-09-05 一次真實回歸留下的防線
# （見上方 2026-09-05 註解與 tests/test_digest_quality.py TokenBudgetTests）：
# 地圖類要寫的東西本來就多，思考會先把預算吃光；一般預算拉高時地圖必須
# 跟著拉開，不准拆這條不變式。
DIGEST_MAX_TOKENS = 12000
MAP_DIGEST_MAX_TOKENS = 16000

# 消化的**思考**上限（2026-09-09 使用者：「播出鏡面消化的時間太長了，偶有失敗，
# 有精簡空間嗎？這也是先前使用者回報逾時沒有生成的原因」）。
#
# 這個 repo 自己量過兩次，結論一致（見上面 DIGEST_MAX_TOKENS 的註解）：真正寫出來
# 的內容非常穩定（856-1361 token），會爆的是思考（603-4873），而且思考量跟著規則
# **條數**漲、跟正文無關。播出鏡面又是規則最多的一條線，所以它最慢、最容易逾時。
# 一次消化最壞情況要五次 attempt（DIGEST_ATTEMPTS），Cloud Run 的請求上限是 300 秒，
# 實測撞過「重試後 269 秒才回應」——離被硬砍只差一點。
#
# 2026-09-16 D21：改送 reasoning.effort 而不是 reasoning.max_tokens。
# 原本這裡的註解寫「OpenAI 系走 effort，Anthropic 系走 max_tokens，這裡不送
# effort」——這句話是錯的，而且錯得剛好讓這條路一直沒被試過：實查
# OpenRouter `/models/anthropic/claude-sonnet-5/endpoints`，五個端點的
# supported_parameters 全部有 reasoning。真正的問題是：實測顯示
# reasoning.max_tokens 對 Claude 系模型根本沒被遵守（見下方 D21 四輪實測：
# 送了 max_tokens=2000，實測 reasoning_tokens 仍是 4005-11999，最高到所設
# 上限的六倍。⚠沒有跑過「完全不送 max_tokens」的對照組，所以能斷言的是
# 「設了上限但沒擋住」，不是「送與不送完全一樣」）；Codex
# 2026-09-16 的查證回覆指出官方文件說明該參數對 Claude 系不生效，但這句
# **未經本專案直接核對官方文件原文**，記在這裡供後續查證，不當作已證實的事實。
# 可以確定的是實測結果：舊版這個思考封頂從上線以來從來沒真的擋下過任何一次
# 思考爆量，DIGEST_REASONING_HEADROOM／DIGEST_REASONING_MIN_TOKENS 那套
# 「budget 要留多少空間給正文」的算法從頭到尾是在算一個沒人理會的數字。
#
# D21 四輪實測（各 10 次同稿同參數，明細見
# docs/交辦-20260916-D21改effort換Gemini.md）：reasoning.effort 才是真的被遵守
# 的欄位——sonnet-5 加上 effort=low 後 reasoning_tokens 從 4005-11999 掉到
# 0-842，成功率 5/10 → 7/10、耗時 131 秒 → 18 秒。換成 gemini-3.8-flash 再疊加
# effort=low 更進一步到 9/10、6 秒、0 截斷、0 簡體，第二輪 10 則不同真實稿泛化
# 通過。effort 只有 low/medium/high 三段式（沒有數字可調），因此不再需要
# 「留多少 token 給正文」的預算換算，DIGEST_REASONING_MAX_TOKENS／
# DIGEST_REASONING_MIN_TOKENS／DIGEST_REASONING_HEADROOM 三個常數的角色被
# effort 值本身取代，整組刪除，不留死碼。
#
# 值用環境變數 DIGEST_REASONING_EFFORT 設定，預設 "low"（D21 實測勝出的檔位）。
# 設成空字串或 "off"＝完全不送 reasoning 欄位，行為與舊版逐字元相同
# （沿用舊版「非 OpenRouter 一律不送」的判斷）。
#
# 2026-09-16 Codex 複查抓到的洞：這個值原本原封不動送上游，**環境變數拼錯就會
# 把亂碼當 effort 送出去**（例如 "lwo"）。而 digest_completion 的降級保護只在
# 錯誤訊息含 "reasoning" 時才拔掉欄位，上游若回的是 "invalid effort" 這類字眼，
# 整條消化就直接失敗。改成白名單擋在源頭：不認得的值退回 "low" 並印一行，
# 寧可跑預設檔位也不要因為一個錯字讓整站消化壞掉。
DIGEST_REASONING_EFFORT_CHOICES = ("low", "medium", "high")


def _validated_effort(raw: str) -> str:
    value = (raw or "").strip().lower()
    if not value or value == "off" or value in DIGEST_REASONING_EFFORT_CHOICES:
        return value
    print(
        f"[digest] reasoning effort {raw!r} 不是 "
        f"{'／'.join(DIGEST_REASONING_EFFORT_CHOICES)}／off，退回 low",
        flush=True,
    )
    return "low"


DIGEST_REASONING_EFFORT = _validated_effort(os.getenv("DIGEST_REASONING_EFFORT", "low"))

# 截斷重試時要退到的最低 effort（取代舊版 DIGEST_REASONING_MIN_TOKENS 的角色：
# 「重試時把思考預算壓到底線，把空間讓給正文」）。effort 只有三段，"low" 已經是
# 最低檔，沒有比它更低的量化值——但仍需要這個常數，因為 DIGEST_REASONING_EFFORT
# 是可以被環境變數調高的（例如日後想試 medium/high 當預設），這裡要能在截斷時
# 無條件退回最低檔，不是「退回目前預設」。
DIGEST_REASONING_RETRY_EFFORT = "low"


def digest_reasoning_body(effort_override: str | None = None) -> dict:
    """這次呼叫要不要送 reasoning.effort，送什麼值。不送就回空 dict。

    effort_override：可選，覆寫這一次的 effort（重試降級用）。未傳時走
    DIGEST_REASONING_EFFORT 的一般預設。
    """
    if DIGEST_BACKEND != "openrouter":
        return {}
    effort = (
        DIGEST_REASONING_EFFORT
        if effort_override is None
        else _validated_effort(effort_override)
    )
    if not effort or effort == "off":
        return {}
    return {"reasoning": {"effort": effort}}


# 消化的 provider 選擇（2026-09-11 起，2026-09-16 D21 改法）。使用者回報消化階段
# 常撞上游過載，選定的對策是「同模型換 provider」，換 provider 不換模型，品質零風險。
#
# 舊版寫死白名單 anthropic,claude-on-aws,azure/global,amazon-bedrock/global——
# 這四個全是 Anthropic 家族的端點，D21 換主模型成 google/gemini-3.8-flash 後
# 完全對不上，繼續沿用等於白名單一個端點都選不中。
#
# 改用 OpenRouter 的統一參數 provider.require_parameters：讓 OpenRouter 自己
# 只在真正吃得下本次請求參數（reasoning、strict json_schema 等）的端點裡選，
# 不用替每次換模型重新盤點一份端點白名單。這同時解掉帳本 B74——舊白名單裡的
# azure/global、amazon-bedrock/global 兩個端點其實不支援 structured_outputs，
# 過載 fallback 過去時 strict schema 會被靜默丟棄；require_parameters 會把
# 這兩個端點直接排除在候選之外，不會再有機會被 fallback 選中。
# 已實測：20 次呼叫送 require_parameters=true 全部順利路由，沒有出現「無
# provider 可用」，這是它唯一的疑慮，已排除。
# allow_fallbacks 維持 true：真的全部端點都不支援本次參數時，寧可讓
# OpenRouter 自己找一條活路，也不要整個請求失敗（這正是 2026-09-11 要解決的
# 問題）。
DIGEST_PROVIDER_REQUIRE_PARAMETERS = (
    os.getenv("DIGEST_PROVIDER_REQUIRE_PARAMETERS", "true").strip().lower()
    not in ("", "0", "false", "off")
)


def digest_provider_body() -> dict:
    """這次呼叫要不要限定 provider 只挑吃得下本次參數的端點。非 OpenRouter 後端一律不送。"""
    if DIGEST_BACKEND != "openrouter" or not DIGEST_PROVIDER_REQUIRE_PARAMETERS:
        return {}
    return {"provider": {"require_parameters": True, "allow_fallbacks": True}}


# 整個消化迴圈的牆鐘預算（2026-09-09）。Cloud Run 的請求上限是 300 秒，超過就是
# 連錯誤訊息都沒有的斷線——使用者看到的「逾時沒有生成」。與其讓第五次 attempt 在
# 第 290 秒才開始，不如在還來得及的時候停手，回一個講得清楚的 503。
DIGEST_DEADLINE_SECONDS = float(os.getenv("DIGEST_DEADLINE_SECONDS", "230"))
# 單次消化呼叫的上限（2026-09-10 線上事故）。沒有這個上限時，一通卡住的上游請求會用掉
# SDK 預設的 600 秒——比 DIGEST_DEADLINE_SECONDS(230) 與 Cloud Run 的 300 秒都長。
# 2026-09-14 B31：client max_retries=0，且死線在每個 attempt（含第 0 次）起跑前檢查，
# 所以 90 秒是整次呼叫的上限，不是「每通 HTTP」。
# 實測正常消化 22–26 秒，90 秒給到 3.5 倍餘裕；卡住時 90 秒就換下一次 attempt。
DIGEST_TIMEOUT_SECONDS = float(os.getenv("DIGEST_TIMEOUT_SECONDS", "90"))

# 「不消化」的輸出長度**由輸入長度決定**——模型要把整篇原文一字不差抄進 variable，
# 再另外寫 style/structure。固定 1500 等於「原文超過某個長度就一定失敗」。
# 2026-09-04 實測（正式站）：943 字過關且逐字相符；1850 字連續 5 次
# finish_reason=length 且 raw content 是空字串——DEFAULT_DIGEST_MODEL 是推理模型，
# 思考 token 也算進 max_completion_tokens，1500 在吐出第一個字之前就用光了，
# 使用者等 90 秒收到 502。中文在 o200k 約 1 字 1 token，這裡抓 2 倍當保險，
# OVERHEAD 要同時吃下 style/structure 與看不見的思考 token。
# 上限是天花板不是用量，只有真的寫出來的 token 才計費，因此寧可寬裕。
VERBATIM_TOKENS_PER_CHAR = 2
VERBATIM_DIGEST_OVERHEAD = 2500
# 天花板的天花板：news_text 上限 20000 字，照公式會算到 42500。真要那麼長的原文
# 本來就不該用不消化，讓它撞 length 收到明確錯誤，比默默燒一次大額呼叫好。
VERBATIM_DIGEST_MAX_TOKENS = 24000


def digest_token_budget(type_label: str, density: str, news_text: str) -> int:
    """這次消化該給多少輸出上限。

    地圖類與不消化各有各的理由要比一般寬裕，但兩者的依據不同：地圖是「要寫的
    東西本來就多」，是固定加碼；不消化是「輸出長度等於輸入長度」，必須隨輸入縮放。
    """
    base = (
        MAP_DIGEST_MAX_TOKENS
        if type_label in (MAP_TYPE_LABEL, AUTO_TYPE_LABEL)
        else DIGEST_MAX_TOKENS
    )
    if density != "verbatim":
        return base
    needed = len(news_text) * VERBATIM_TOKENS_PER_CHAR + VERBATIM_DIGEST_OVERHEAD
    return min(max(base, needed), VERBATIM_DIGEST_MAX_TOKENS)

# 消化重試次數。上游（OpenRouter 輪替的 provider）會間歇性脫軌——2026-08-01 實測
# 休達那則新聞，模型會在 variable 裡吐出韓文／西里爾／馬拉雅拉姆等隨機文字碎片，
# 單次成功率約 2/3，3 次重試仍整組摃摃、使用者收到 502 拿不到圖。消化是純文字
# 呼叫、單價低，多兩次重試換一次成功的成本遠低於讓使用者空手而回。
DIGEST_ATTEMPTS = 5

# B67（2026-09-16 使用者裁決）：塊數不足專用的較短上限。B57 的塊數防呆對「原文
# 本來就只有三個點」的稿是**每一次都必定不過**，不像上游脫軌那樣重試就有機會好，
# 所以讓它跑滿 DIGEST_ATTEMPTS 是純粹的等待——使用者原話「重試五次可能太多耗時」。
# 這個值只管塊數；真故障（截斷／亂碼／解析失敗）仍照 DIGEST_ATTEMPTS 擋滿，
# 那是 2026-08-01 實測出來的次數，不受這裡影響。
DIGEST_POINT_COUNT_ATTEMPTS = 3

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# 站台密碼門（2026-08-20 搬遷到 Zeabur 時加）。app.js:1160 的 _INTERNAL_API_KEY
# 是 entrypoint.sh 在容器啟動時烙進前端的——頁面公開就等於 NEWS_IMAGE_API_KEY
# 公開，任何拿到網址的人都能呼叫生成端點、消耗 API 額度。部署到公開網址時要有
# 一道門擋在最前面，把範圍收斂回「知道密碼的自己人」。
#
# 設計取捨：
# - 設了 SITE_PASSWORD 才啟用。不設就完全是舊行為，不影響本機開發與既有部署。
# - LINE webhook 走自己的 HMAC 簽章驗證（line_bot.py:158），被這道門擋住就收不到
#   訊息，必須放行。
# - /static/generated/ 也要放行：LINE 傳圖只吃公開 HTTPS 網址（line_bot.py:9），
#   LINE 伺服器抓圖時不會帶密碼。檔名帶隨機碼，不列目錄。
SITE_PASSWORD = os.getenv("SITE_PASSWORD", "").strip()
SITE_PASSWORD_EXEMPT_PREFIXES = ("/line/", "/static/generated/", "/healthz")


# Clerk 登入門（2026-08-25 加）。動機：稽核需求要每一筆生成都能對到人，但站台密碼門
# 是全體共用一組密碼，系統分不出誰是誰。設了 CLERK_PUBLISHABLE_KEY 就改由 Clerk 把關，
# 並接手 SITE_PASSWORD 的角色（兩道門都要過只是徒增麻煩，身分驗證本來就更嚴格）。
#
# 哪些路徑不需要登入：
# - `/` 與 `/hybrid.html` 是空殼頁，本身不含任何金鑰（entrypoint.sh 只烙進 app.js／
#   hybrid.js）。**必須放行**，否則使用者連 Clerk 的登入畫面都載不出來，變成死結。
# - `/static/` 是 logo 與 LINE 用的成圖，本來就要公開讀取。
# - `/line/` 走自己的 HMAC 驗簽、`/healthz` 給健康檢查，與 SITE_PASSWORD 的豁免一致。
# 其餘一律要有效 session——特別是 `/app.js`／`/hybrid.js`（帶著 NEWS_IMAGE_API_KEY）
# 與所有 `/api/`，這才是真正要守住的東西。
_current_user = contextvars.ContextVar("current_user", default=None)

CLERK_PUBLIC_PATHS = (
    "/",
    "/index.html",
    "/hybrid.html",
    "/auth-config.json",
    # 2026-08-25 修正：app.js／hybrid.js 必須放行。原本擋著它們，想靠 __session
    # cookie 驗身分，實測失敗——`<script src>` 這類子資源請求帶不到 Clerk 的 cookie
    # （Clerk 的 cookie 由它自己的前端程式管理），結果登入後 app.js 仍一路 401，
    # 頁面變成沒有任何程式碼的空殼，所有按鈕都沒反應。
    #
    # 改成：這兩支公開，但**不烙進真實金鑰**（見 _serve_js_with_key），
    # 真正的防線移到 API 端——verify_internal_api_key 改認 Clerk 權杖，
    # 而權杖由 index.html 包的那層 fetch 自動帶上。
    # 少了金鑰的 app.js 對匿名訪客沒有價值：它呼叫任何生成端點都會被擋。
    "/app.js",
    "/hybrid.js",
)
CLERK_PUBLIC_PREFIXES = ("/line/", "/static/", "/healthz", "/favicon")


def current_user() -> dict:
    """目前這個請求的登入者。沒啟用 Clerk 或走 LINE 時回空 dict。"""
    return _current_user.get() or {}


# Langfuse 的身分綁定（2026-09-14）。掛在登入門那一層，所有端點一次涵蓋——
# 逐個端點加等於每新增一個版型就要記得補一次，遲早漏掉（稽核歸檔就是這樣漏掉
# 四個編輯端點的，見 2026-09-11 的修正）。
#
# user_id 用 email 而非 Clerk 的 user_xxx：Langfuse 介面上要能一眼看出是誰，
# 而 email 在本站已是穩定識別（Clerk 的 allowlist 只放公司網域）。
try:
    from langfuse import propagate_attributes as _lf_propagate
except ImportError:  # 沒裝 langfuse 時退成什麼都不做的空 context manager
    import contextlib

    def _lf_propagate(**_kwargs):
        return contextlib.nullcontext()


# 消化與生圖是兩次獨立的請求（app.js:1145-1146 的 AI_BACKEND_URL / IMAGE_BACKEND_URL），
# 生圖那支只收到 prompt，專案原本就把 news_text 寫死成 ""（見 main.py 的 web-image
# 歸檔呼叫）。但稽核要求「完整記錄同仁生成的內容」，新聞原文是其中最重要的一項，
# 所以在這裡把同一位使用者最近一次消化的原文補回去。
#
# 為什麼用「使用者＋時間窗」關聯而不是嚴格的請求 ID：前端兩次呼叫之間沒有傳遞任何
# 關聯欄位，要做嚴格關聯就得改 app.js 的呼叫參數與後端的 request model，動到一萬多行
# 的前端主檔，風險高於效益。同一人短時間內換稿再生圖時，補上的是最近一次消化的原文,
# 與使用者當下畫面上看到的內容一致。
_DIGEST_MEMO_TTL = 1800
_digest_memo: dict[str, tuple[float, dict]] = {}
_digest_memo_lock = threading.Lock()


def _remember_digest(**fields) -> None:
    """記下這位使用者最近一次消化的新聞原文與消化結果。"""
    user_id = current_user().get("user_id") or ""
    if not user_id:
        return
    now = time.time()
    with _digest_memo_lock:
        _digest_memo[user_id] = (now, fields)
        # 順手清掉過期的，避免這個 dict 隨使用者數無限成長。
        for key in [k for k, (ts, _) in _digest_memo.items() if now - ts > _DIGEST_MEMO_TTL]:
            _digest_memo.pop(key, None)


def _recall_digest() -> dict:
    user_id = current_user().get("user_id") or ""
    if not user_id:
        return {}
    with _digest_memo_lock:
        found = _digest_memo.get(user_id)
    if not found or time.time() - found[0] > _DIGEST_MEMO_TTL:
        return {}
    return found[1]


_UPSTREAM_STATUS_RE = re.compile(r"[（(](\d{3})[）)]")


def _generation_clock() -> float:
    return time.monotonic()


def _generation_duration_ms(started: float) -> int:
    return max(0, int(round((time.monotonic() - started) * 1000)))


def _reset_generation_retries() -> None:
    _generation_retry_count.set(0)


def _note_generation_retry() -> None:
    _generation_retry_count.set(_generation_retry_count.get() + 1)


def _generation_retries() -> int:
    return _generation_retry_count.get()


# 上游錯誤的真話（B94，2026-09-22）：消化這條路以前把 OpenRouter 丟回來的例外
# 整個吞掉，只 print 到 stdout，後台紀錄裡留下的永遠是同一句「AI 服務處理失敗，
# 請確認模型權限或稍後重試」。2026-09-22 DEV 連倒五筆就是卡在這裡——看得到
# `provider_5xx · HTTP 502`，卻看不出是額度、是模型權限、還是 provider 掛了，
# 等於每次都要重跑一次才能猜。生圖那條早就把 OpenRouter 的 JSON 原文帶進訊息
# （見 2026-09-17 那筆 safety system 的紀錄），消化這條補上同樣的待遇。
UPSTREAM_DETAIL_MAX_CHARS = 200


def upstream_error_detail(
    exc: BaseException, base: str = "AI 服務處理失敗，請確認模型權限或稍後重試"
) -> str:
    """上游例外 → 使用者與後台都看得懂的一句話，**帶上游的狀態碼與訊息摘要**。

    連不上是另一回事（沒有狀態碼可帶），維持原本的講法。
    """
    if isinstance(exc, APIConnectionError):
        return "無法連線至 AI 服務，請稍後再試"
    status = getattr(exc, "status_code", None)
    body = audit_archive.sanitize_error_summary(
        str(getattr(exc, "message", "") or exc),
        max_chars=UPSTREAM_DETAIL_MAX_CHARS,
    ).replace("[redacted]", "[已遮蔽]")
    parts = [p for p in (f"上游 {status}" if status else "", body) if p]
    return f"{base}（{' · '.join(parts)}）" if parts else base


def non_retryable_upstream_error(exc: BaseException) -> HTTPException | None:
    """確定性 4xx → 立刻停手；408、429 與 5xx 等暫時性錯誤回 None。

    B95（2026-09-22）：B94 上線後第一筆 DEV 失敗就寫出了真因——
    `上游 402 · This request requires more credits, or fewer max_tokens.
    You requested up to 16000 tokens, but can only afford 15030.`
    DEV 那把 OpenRouter 金鑰餘額見底，跟 B91 的 prompt 一點關係也沒有。

    但它走的是通用的 `APIError` 分支，被當成「上游間歇脫軌」重試滿
    `DIGEST_ATTEMPTS`（5 次）。**餘額不會因為重試變多**，那五次是純粹的等待，
    使用者每按一次就空等 9 秒才看到錯誤。金鑰無效（`AuthenticationError`）與
    用量超限（`RateLimitError`）早就是「不重試」了，402 漏掉只是因為 SDK 把它
    丟成一般的 `APIStatusError`，不是因為它該重試。

    B101（2026-09-23）：401／403／404（模型不存在）等錯誤重試也不會成功，
    與 402 一樣立即回報；訊息保留上游原文。408、429 與 5xx 仍交給重試圈。
    """
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int) or not (400 <= status < 500) or status in (408, 429):
        return None
    base = "AI 服務額度不足，請儲值後再試" if status == 402 else "AI 服務拒絕這次請求，重試不會成功"
    return HTTPException(
        status_code=503,
        detail=upstream_error_detail(exc, base=base),
    )


def _error_type_from_http(
    status: int | None, summary: str, *, upstream: bool = False
) -> str:
    text = summary or ""
    lowered = text.lower()
    if (
        "太久沒有回應" in text
        or "timeout" in lowered
        or "timed out" in lowered
        or "無法連線" in text
    ):
        return "timeout"
    if "無法解析" in text:
        return "parse"
    if "封面生成失敗" in text or "合成失敗" in text or "直標合成" in text:
        return "compose"
    if "金鑰" in text or "計費" in text or "credits" in lowered:
        return "provider_4xx"
    if status in (408, 504):
        return "timeout"
    if status in (400, 422) and not upstream:
        return "input"
    if status in (401, 402, 403, 429) or (status is not None and 400 <= status < 500):
        return "provider_4xx"
    if status is not None and status >= 500:
        return "provider_5xx"
    return "unknown"


def classify_generation_error(exc: BaseException) -> dict:
    """把例外收成可分組的 error_type／http_status／截短去敏摘要。"""
    summary = str(exc)
    http_status = None
    error_type = "unknown"
    if isinstance(exc, HTTPException):
        http_status = exc.status_code
        detail = exc.detail
        summary = detail if isinstance(detail, str) else str(detail)
        error_type = _error_type_from_http(http_status, summary)
        match = _UPSTREAM_STATUS_RE.search(summary)
        if match:
            http_status = int(match.group(1))
            error_type = _error_type_from_http(http_status, summary, upstream=True)
    elif isinstance(exc, compose.ComposeError):
        http_status = _compose_error_status(exc)
        summary = str(exc)
        error_type = "compose"
    else:
        name = type(exc).__name__
        lowered = summary.lower()
        if name in {"TimeoutError", "APITimeoutError"} or "timeout" in lowered:
            error_type = "timeout"
            http_status = 504
        elif name in {"URLError", "APIConnectionError"}:
            error_type = "timeout"
            http_status = 502
        else:
            error_type = _error_type_from_http(None, summary)
    return {
        "error_type": error_type,
        "http_status": http_status,
        "error_summary": audit_archive.sanitize_error_summary(summary),
    }


def _outcome_meta(
    started: float,
    *,
    provider: str = "",
    image_model: str = "",
    exc: BaseException | None = None,
) -> dict:
    """成功／失敗共用的耗時、重試、provider。request log 與 audit 都吃同一份。

    2026-09-20（B72）：這裡也塞 digest_model。resolve_digest_model() 只讀環境設定
    （DIGEST_MODEL／OPENAI_DIGEST_MODEL／後端預設），跟這次請求本身有沒有真的呼叫
    消化無關——查的是「出事當下系統設定的消化模型是哪一支」，這正是 B72 的問題
    （使用者當面問「現在消化模型是？」查不出來）。放在這裡而不是逐一端點各自傳，
    是因為全部 8 個會落檔的端點（成功與失敗）都經過這支函式，漏傳的風險比
    F30 那次「新版型忘了接歸檔」小得多。
    """
    meta = {
        "status": audit_archive.STATUS_FAILED if exc is not None else audit_archive.STATUS_OK,
        "duration_ms": _generation_duration_ms(started),
        "retry_count": _generation_retries(),
        "provider": provider,
        "image_model": image_model,
        "digest_model": resolve_digest_model(),
    }
    if exc is not None:
        meta.update(classify_generation_error(exc))
    return meta


def _enrich_archive_fields(kwargs: dict) -> dict:
    enriched = dict(kwargs)
    memo = _recall_digest()
    if memo:
        for key, value in memo.items():
            if not enriched.get(key):
                enriched[key] = value
    return enriched


def _archive_generation(**kwargs) -> None:
    """歸檔一次成功的生成：既有的 GCS 備份，加上帶身分的本機稽核歸檔。

    包成一支的理由：三個生成端點（news-image、web-refine、hybrid）都要歸檔，
    身分注入與原文補齊只想寫一次；日後要換／加歸檔目的地也只改這裡。
    兩支底層函式都自己吞例外，這裡不需要再包 try。

    2026-09-20（B72／F31）：`gcs_archive.archive_generation` 的 `image_base64`／
    `mime_type` 是必填（無預設值），沒圖時直接 `**kwargs` 展開會在 `ENABLED`
    判斷之前就丟 `TypeError`。消化階段（`generate()`）現在也會呼叫這支函式落一筆
    「只有文字、沒有圖」的稽核紀錄（網頁版消化完才在前端組 prompt、還沒生圖），
    因此這裡要能接受沒有圖的呼叫——沒圖就只跳過 GCS 那份備份，本機稽核照寫。

    2026-09-20（team-lead 複查點名）：`_enrich_archive_fields()`／`current_user()`
    以前沒有包 try——落檔本來是「附帶效果」，但這兩支萬一炸掉會把一次**成功**的
    生成也弄失敗，這比「沒歸檔」更糟。整支包起來，落檔失敗只印一行，不影響呼叫端。
    """
    try:
        kwargs.setdefault("status", audit_archive.STATUS_OK)
        # `extra_images`（B55 診斷用的標題圖層）只進本機稽核歸檔，不進 GCS 備份——
        # gcs_archive.archive_generation 不認得這個參數，展開進去會直接 TypeError。
        extra_images = kwargs.pop("extra_images", None)
        if kwargs.get("image_base64"):
            gcs_archive.archive_generation(**kwargs)

        # 只補「這條路徑本來就沒有」的欄位，不覆蓋呼叫端已經給值的欄位——
        # news-image 那條路徑自己就帶著正確的原文，補寫反而可能蓋成舊的。
        enriched = _enrich_archive_fields(kwargs)

        user = current_user()
        audit_archive.archive_generation(
            user_id=user.get("user_id", ""),
            user_email=user.get("email", ""),
            user_name=user.get("name", ""),
            extra_images=extra_images,
            **enriched,
        )
    except Exception as exc:  # noqa: BLE001 - 歸檔失敗只印出來，不能讓成功的生成變失敗
        print(f"[audit] 成功筆的落檔失敗（不影響原本的生成結果）: {exc}", flush=True)


def _archive_generation_failure(**kwargs) -> None:
    """歸檔一次失敗的生成。不要求圖片，也不寫 GCS（那支要圖）。

    2026-09-20（team-lead 複查點名）：同 `_archive_generation`，整支包 try——
    落檔失敗不能蓋掉原本要往外丟的那個例外。
    """
    try:
        kwargs.setdefault("status", audit_archive.STATUS_FAILED)
        kwargs.pop("image_base64", None)
        kwargs.pop("mime_type", None)
        enriched = _enrich_archive_fields(kwargs)
        user = current_user()
        audit_archive.archive_generation(
            user_id=user.get("user_id", ""),
            user_email=user.get("email", ""),
            user_name=user.get("name", ""),
            image_base64="",
            mime_type="",
            **enriched,
        )
    except Exception as exc:  # noqa: BLE001 - 落檔失敗只印出來，不能蓋掉原本的錯誤
        print(f"[audit] 失敗筆的落檔失敗（不影響原本要往外丟的例外）: {exc}", flush=True)


def _record_generation_failure(
    request_id: str,
    started: float,
    exc: BaseException,
    **fields,
) -> None:
    """失敗只落一筆：request log 與 audit 共用同一 request id、耗時與去敏摘要。

    2026-09-20（team-lead 複查點名，正確）：`_outcome_meta(..., exc=exc)` 內部會呼叫
    `classify_generation_error()`（正則比對、`_compose_error_status()`、`str(exc)`），
    這些以前完全沒有包 try——**記錄失敗這件事本身，絕對不能把原本要往外丟的例外
    蓋掉**：使用者原本該看到的是消化逾時的 503，不能因為分類例外訊息時自己又炸出
    一個無關的 500。整支函式包一層 try，記錄失敗只印一行，然後繼續讓原例外往外拋
    （呼叫端的 `raise` 不受影響——這裡只負責記錄，不負責重新拋出）。
    """
    try:
        meta = _outcome_meta(
            started,
            provider=str(fields.get("provider") or ""),
            image_model=str(fields.get("image_model") or ""),
            exc=exc,
        )
        request_log.log_failure(
            request_id=request_id,
            source=str(fields.get("source") or ""),
            news_text=str(fields.get("news_text") or ""),
            error=meta["error_summary"],
            style=str(fields.get("style") or ""),
            structure=str(fields.get("structure") or ""),
            variable=str(fields.get("variable") or ""),
            prompt=str(fields.get("prompt") or ""),
            chart_type=str(fields.get("chart_type") or ""),
            type_label=str(fields.get("type_label") or ""),
            role=str(fields.get("role") or ""),
            density=str(fields.get("density") or ""),
            provider=str(fields.get("provider") or ""),
            client_id=str(fields.get("client_id") or ""),
            digest_model=meta["digest_model"],
        )
        archive_fields = dict(fields)
        archive_fields.update(meta)
        _archive_generation_failure(request_id=request_id, **archive_fields)
    except Exception as log_exc:  # noqa: BLE001 - 記錄失敗不能蓋掉原本要往外丟的例外
        print(
            f"[audit] 記錄失敗筆本身出錯（不影響原本的錯誤，原例外仍會往外丟）: "
            f"{log_exc}；原例外：{exc}",
            flush=True,
        )


def _abort_generation(exc: Exception, **fields) -> None:
    """輸入 4xx 等還沒開始生圖就失敗的路徑：記一筆再把例外丟回去。"""
    _reset_generation_retries()
    _record_generation_failure(
        request_log.new_request_id(), _generation_clock(), exc, **fields
    )
    raise exc


@app.middleware("http")
async def clerk_login_gate(request, call_next):
    if not clerk_auth.ENABLED:
        return await call_next(request)
    path = request.url.path
    # 後台由 ADMIN_PASSWORD 自己把關，不吃同仁的登入（見 admin_console.py）。
    if path.startswith("/admin"):
        return await call_next(request)
    if path in CLERK_PUBLIC_PATHS or path.startswith(CLERK_PUBLIC_PREFIXES):
        return await call_next(request)

    user = clerk_auth.verify_token(clerk_auth.extract_token(request))
    if user is None:
        return PlainTextResponse("請先登入", status_code=401)

    token = _current_user.set(user)
    try:
        # 這個 with 內發出的每一次 LLM 呼叫都會帶上 user_id 送進 Langfuse
        with _lf_propagate(user_id=user.get("email") or user.get("user_id", "")):
            return await call_next(request)
    finally:
        _current_user.reset(token)


@app.middleware("http")
async def site_password_gate(request, call_next):
    # 啟用 Clerk 後由上面那道門負責，不再另外要密碼。
    if not SITE_PASSWORD or clerk_auth.ENABLED:
        return await call_next(request)
    if request.url.path.startswith(SITE_PASSWORD_EXEMPT_PREFIXES):
        return await call_next(request)

    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
        except Exception:
            decoded = ""
        # 帳號欄不檢查，只認密碼——少一個要交代給使用者的欄位。
        _, _, supplied = decoded.partition(":")
        if hmac.compare_digest(supplied, SITE_PASSWORD):
            return await call_next(request)

    return PlainTextResponse(
        "需要密碼",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="TVBS AICG"'},
    )


# 2026-09-10 使用者：「字少字多拉桿可否也做成 5 階梯，最左邊：不改字，最右邊：字超多，
# 預設還是字少。」——兩端各補一級。新的兩級是**既有級的加碼**，不是新寫一套：
# minimal = SIMPLIFIED 再收緊、maximum = STANDARD 再放寬，這樣自由度／資訊量一定單調。
# 由少到多的順序寫在 DIGEST_DENSITY_ORDER，前台拉桿與測試都以它為準。
#
# 2026-09-14 D14 使用者裁決：再加一檔「完全不要文字」，放在**最左端**。拉桿因此
# 六段。兩個極端（無字／不改字）被推到拉桿兩頭，不會擠在同一側被選錯——這正是
# 使用者在 D14 裡要解決的事。預設仍是字少，沒有改。
DigestDensity = Literal["no_text", "verbatim", "minimal", "simplified", "standard", "maximum"]
DIGEST_DENSITY_ORDER = ("no_text", "verbatim", "minimal", "simplified", "standard", "maximum")
# 色調。None＝呼叫端沒表態（LINE、舊呼叫端），完全不注入。
DigestTone = Literal["light", "dark"]


# 一張圖最多畫幾張具名真人的臉（2026-08-18 使用者裁定，從「兩人以上一律不畫臉」放寬）。
# 3 是保守值：2026-08-18 的實驗只驗到 3 人（9/9 張臉正確對應、0 交換、0 捏臉），
# 沒有 4 人以上的證據。消化端用同一個上限把版面壓在 3 人以內（見
# REAL_WORLD_FIDELITY_RULES 第 6 條），生圖端則絕不自行截斷（見 resolve_portraits）。
MAX_PORTRAIT_FACES = 3


# ============================================================
# F0：三條線共用的 seed（D1，2026-09-14 使用者裁決）
#
# 使用者要的兩件事同時成立：**重生會變**（不然「再生一張」等於白按）與
# **好的那張撈得回來**（回報「這組好」時要能重現）。作法是請求帶一顆明確的
# 整數 seed，前端按「重新生成」才遞增；沒帶時後端現抽一顆並在回應裡回報。
#
# **seed 絕對不進 prompt**（監督 2026-09-14 Q2 升級為硬規則）。理由不只是模型
# 會把數字寫錯：seed 一旦拼進 prompt 就改變了生圖輸入，同一顆 seed 再也複現不出
# 原圖——F0 這個功能本身就自我否定了。它只走「請求欄位 → 程式抽籤 → 回應／
# request_log／audit_archive」這條資料路徑。
#
# 上限取 2**31：JSON 與 JavaScript 的整數在這個範圍內都不會失真，前端遞增後送
# 回來也還是同一個值。用 secrets 而不是 random：後者的預設種子在同一個行程裡
# 是共享狀態，別處呼叫 random.seed() 就會讓「不可預測」悄悄失效。
SEED_MAX = 2 ** 31


def next_generation_seed() -> int:
    """抽一顆新的生成 seed。呼叫端沒帶 seed 時用，每個請求只抽一次。"""
    return secrets.randbelow(SEED_MAX)


class GenerateRequest(BaseModel):
    news_text: str
    type_label: str
    role: str = "記者"
    density: DigestDensity = "standard"
    # CG 美術創意 0–4（2026-09-10）。0＝現行成品，完全不注入。None／未帶＝0。
    # 十點封面那條拉桿是另一個欄位（TenCoverRequest.title_creativity），兩條互不影響。
    # 上下界寫字面值：CG_CREATIVITY_LEVEL_MIN/MAX 定義在條文區塊，比這個類別晚。
    visual_creativity: int = Field(default=0, ge=0, le=4)
    # True＝留白改由後端 safe_frame 置框，消化階段要出滿版版面而非縮小置中
    safe_frame: bool = False
    # D26（2026-09-26）：記者＋安全框 ON 時可選「模型畫延伸背景」。空字串＝現行行為。
    # 消化階段要知道：版面要改成中央內容（full_bleed=False），見 model_extension_active。
    frame_strategy: Literal["", "model_extension"] = ""
    # 網頁版「給 AI 的指令」專用欄位（PLAN.md ①）。這是文內解析之外**多出來**的
    # 高信賴度通道，不是取代：LINE 是聊天框拆不了欄位，且有人習慣把「逐字保留」
    # 寫在完稿裡，文內解析（USER_INSTRUCTION_RULES）必須原樣保留。
    user_instruction: str = Field(default="", max_length=2_000)
    # 這些人查不到參考照，版面不得畫他們（2026-08-18 使用者裁決）。
    # 由第二段消化填入，呼叫端通常不用管。
    exclude_people: list[str] = Field(default_factory=list, max_length=10)
    # 網頁版使用者已上傳幾張肖像照。消化端據此判斷「查不到的人」是不是其實有照片：
    # 使用者上傳的肖像照視為對應**系統查不到的人**（吳軒彤那個原始情境就是這樣），
    # 依序對應。上傳的圖本身在生圖階段才送，消化階段只需要知道張數。
    portrait_photo_count: int = Field(default=0, ge=0, le=MAX_PORTRAIT_FACES)
    # 網頁版使用者已上傳幾張「原圖放置」參考圖（2026-08-23）。消化端據此讓
    # STRUCTURE 明確交代這塊版位放的是使用者原圖、不是插畫描繪——不注入時
    # 消化端有時會隨手寫成「illustrative depiction」，把生圖階段的原圖放置
    # 規則蓋掉，模型因此憑空捏一張替代圖（記者/編輯版都各出過一次）。
    # 上傳的圖本身在生圖階段才送，消化階段只需要知道張數。
    asis_reference_count: int = Field(default=0, ge=0, le=3)
    # 蓋章開關（2026-09-03）。None＝呼叫端不表態，維持舊行為（由消化階段自行決定）；
    # 網頁版一律送明確的 True／False。
    stamp: bool | None = None
    tone: DigestTone | None = None
    # 編輯專屬版型（2026-09-03）。記者角色帶了也會被忽略，見 editor_formats。
    editor_format: str = editor_formats.DEFAULT_FORMAT
    # 播出鏡面的挖空側（2026-09-08 WP1：左切／右切合併成一個版型後改由請求決定）。
    # 消化階段就要知道方向——內容要趕到影片那半邊的對面，方向講錯等於重點被蓋掉。
    # 只有 editor_format="broadcast" 吃得到；舊別名一律用自己釘死的那一側。
    hole_side: Literal["left", "right"] = "left"
    # 變化池的 seed（F0／D1）。None＝後端現抽一顆並在回應裡回報。
    seed: int | None = Field(default=None, ge=0, lt=SEED_MAX)


class MapPoint(BaseModel):
    """一個查得到真實座標的地點。name 是要標在圖上的名字，不是查詢字串。"""

    name: str = Field(min_length=1, max_length=40)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


# 一張圖上最多查幾個地點。Nominatim 要求每秒一次，四個就是四秒的等待——
# 再多，使用者等待的時間就開始比省下來的錯誤還貴。
MAX_MAP_PLACES = 4
# 少於兩個點不做底圖：一個點沒有「相對位置」可言，那正是地圖類存在的理由，
# 而且單點底圖只會是一張放大的街廓，不如讓模型自己畫示意圖。
MIN_MAP_POINTS = 2


class GenerateResponse(BaseModel):
    style: str
    structure: str
    variable: str
    # 這次實際採用的圖表類型（自動判斷模式下為 AI 所選）
    chart_type: str = ""
    # 版面會畫出臉孔的每一位具名真實人物，全部列進來（沒有就空陣列）。
    # 後端據此決定要不要查參考照片、以及套哪一種肖像處理規則。
    # 為什麼是陣列不是單一字串：2026-08-05 出過事——使用者要「鄭明典／吳軒彤兩顆人頭」，
    # 單一欄位只裝得下第一個人，第二格因此完全沒進肖像流程，被模型自由發揮還掛上真名。
    portrait_subjects: list[str] = Field(default_factory=list)
    # 同順序同長度的英文原名，查參考照的備援（2026-08-18）。臺灣譯名常常不是中文
    # 維基的條目名——「卡利巴夫」「阿拉奇」「巴薩尼」「瓦希迪」實測全部查無條目，
    # 但英文名查得到。不確定就留空字串，絕不亂猜拼寫。
    portrait_subjects_en: list[str] = Field(default_factory=list)
    # 消化端依人物身分推測的英文拼寫；只供英文維基查照，絕不進畫面文字或忠實內容。
    portrait_subjects_en_guess: list[str] = Field(default_factory=list)
    # 地圖類專用：消化端列出的地點裡，**實查得到真實座標**的那些。
    # 查不到的不會出現在這裡——標錯地點在新聞畫面上就是播出事故，寧可少標。
    # 前端把它原樣帶進生圖請求，後端據此產生真實底圖（見 build_map_reference）。
    map_points: list[MapPoint] = Field(default_factory=list)
    # 地圖類：消化端列了但實查不到座標（或被查點白名單擋掉）的地名。前端據此提示使用者，
    # 否則「只查到 1 點不做底圖」對使用者是完全安靜的失敗（2026-09-08）。
    map_missing: list[str] = Field(default_factory=list)
    # F40 第 3 層：有維基條目但沒有合格照片時，非致命提示一路帶到前端。
    notices: list[str] = Field(default_factory=list)
    # 這次實際採用的 seed（F0）：前端要拿它當「重新生成」的遞增起點，稽核要拿它回查。
    seed: int = 0


# input_references 的上限。模型端 GPT Image 2／2.5 收 0–16、Gemini 0–14（PLAN.md 查證），
# 這裡抓遠低於兩者的值：一張肖像參考照＋幾張使用者參考圖已綽綽有餘，
# 塞更多只會稀釋每張的權重、還把 base64 請求撐爆。
MAX_INPUT_REFERENCES = 6


# 使用者上傳參考圖的單筆描述。purpose 決定注入哪一段用途 prompt（見
# news_prompt.USER_REFERENCE_MODES）：map＝地圖底稿（地理關係以附圖為準）、
# scene＝實景參考（場景／建物／器材外觀依附圖）、portrait＝肖像照
# （2026-08-17 使用者裁決開放；使用者親自上傳時「兩位以上具名真人不畫臉」
# 鐵律解除，但沒附照片的人仍不畫臉——見 USER_REFERENCE_PORTRAIT_RULES）、
# asis＝原圖放置（2026-08-23 使用者裁決；不重繪、原封不動放進成圖指定
# 區塊——注意這是 prompt 層級要求，模型仍可能有壓縮/色偏等落差，不保證
# 像素級一致，見 USER_REFERENCE_ASIS_RULES）、aiedit＝AI改圖（2026-09-13
# 使用者裁決；這張圖就是成品那塊畫面，但交給生圖模型照版型風格重畫一次——
# 與 asis 差在會被重畫，與 scene 差在畫的是同一個畫面，見 USER_REFERENCE_AIEDIT_RULES）。
#
# 這組 key 與前台下拉的順序、標籤由 editor_formats.REF_PURPOSE_ORDER 統一（唯一真相源），
# titlelayer 除外——它是內部用途，下拉裡沒有，見下面欄位註解。
class UserReferenceImage(BaseModel):
    data_url: str = Field(min_length=1, max_length=2_800_000)  # 約 2MB base64
    # titlelayer＝B55 修法甲的透明底標題圖層專用（2026-09-20 獨立複查補）：
    # 附圖只是位置／配色參考，模型輸出透明圖層，照片由程式疊。標成 aiedit 會注入
    # USER_REFERENCE_AIEDIT_RULES 的「Re-draw that same picture」，跟同一份 prompt 裡
    # editor_formats.AI_TITLE_LAYER_ONLY_NOTE 的「Do NOT reproduce, redraw…」正面矛盾。
    purpose: Literal["map", "scene", "portrait", "asis", "aiedit", "titlelayer"] = "scene"


# ============================================================
# 附圖位（十點不一樣／YT整點直播的「一標一附圖」）的共用讀法（2026-09-13）
#
# 2026-09-10 的附圖位一格只收一張、固定當原圖放置，欄位就是一個 data URL 字串。
# 2026-09-13 使用者要求全站上傳統一：每一格改成收一份清單，每張各有自己的用途。
# 舊的 asis_left／asis_right 字串欄位**保留**並在這裡正規化成「單張 asis 清單」，
# 舊呼叫端（LINE、既有測試）一字不用改。
#
# 一格只放得下一張版位圖：清單裡第一張 asis 才是那格直接上版的圖，同格其他張
# （aiedit／scene／portrait／map）是那格生底圖時的參考。


def slot_reference_list(
    refs: list[UserReferenceImage], legacy_data_url: str = ""
) -> list[UserReferenceImage]:
    """一格的附圖清單。新欄位優先；沒有新欄位才看舊的單張 data URL。"""
    if refs:
        return list(refs)
    url = (legacy_data_url or "").strip()
    return [UserReferenceImage(data_url=url, purpose="asis")] if url else []


def slot_placement_url(refs: list[UserReferenceImage], tag: str = "slot") -> str:
    """這一格直接上版的那張圖（data URL）；沒有 asis 就回空字串＝這格要生底圖。"""
    asis = [ref for ref in refs if ref.purpose == "asis"]
    if len(asis) > 1:
        print(f"[{tag}] 同一格放了 {len(asis)} 張原圖放置，一格只有一個版位，只取第 1 張", flush=True)
    return asis[0].data_url if asis else ""


def slot_generation_refs(refs: list[UserReferenceImage]) -> list[UserReferenceImage]:
    """這一格生底圖時要附上的參考圖：原圖放置以外全算（含 AI改圖）。"""
    return [ref for ref in refs if ref.purpose != "asis"]


def merge_mixed_slot_to_aiedit(refs: list[UserReferenceImage], tag: str = "slot") -> list[UserReferenceImage]:
    """滿版（單格）同時放了原圖放置與 AI改圖：原圖全部轉 AI改圖（2026-09-13 使用者裁決：
    任一張選 AI改圖 → 整版鎖成 AI改圖、合成一張）。

    不轉的話原圖那條路會搶先（裁滿版／切格），AI改圖 那張就被靜靜丟掉。
    只在滿版／單則用；雙切半格另有 lock_half_slot_asis（≥2 張就鎖）。
    """
    if not (any(ref.purpose == "aiedit" for ref in refs) and any(ref.purpose == "asis" for ref in refs)):
        return list(refs)
    n = sum(1 for ref in refs if ref.purpose == "asis")
    print(f"[{tag}] 滿版附圖混了 AI改圖 → {n} 張原圖放置一併改 AI改圖，整版合成一張", flush=True)
    return [ref.model_copy(update={"purpose": "aiedit"}) if ref.purpose == "asis" else ref for ref in refs]


def lock_half_slot_asis(refs: list[UserReferenceImage], tag: str = "slot") -> list[UserReferenceImage]:
    """半版格子放了 2 張以上：原圖放置一律改成 AI改圖（2026-09-13 使用者裁決）。

    一個半格只有一個版位，塞兩張原圖本來就放不下（以前是默默只取第 1 張）；
    放多張的用意是讓模型把它們重新構圖融成同一張示意圖，所以整格鎖成 AI改圖。
    前端下拉同步鎖（renderRefList 的 lockAsis），這裡是給 LINE 等繞過 UI 的呼叫端兜底。
    只管半格：滿版那一格多張原圖是「自動切 N 格」，另一條規則。
    """
    if len(refs) <= 1:
        return list(refs)
    n = sum(1 for ref in refs if ref.purpose == "asis")
    if n:
        print(f"[{tag}] 半版附圖位放了 {len(refs)} 張、其中 {n} 張原圖放置 → 整格改 AI改圖", flush=True)
    return [ref.model_copy(update={"purpose": "aiedit"}) if ref.purpose == "asis" else ref for ref in refs]


def reject_excess_asis(
    refs: list[UserReferenceImage], *, where: str, limit: int = compose.YT_SPLIT_MAX_PANELS
) -> None:
    """滿版一格的原圖放置超過自動切格上限就 400（2026-09-14 使用者裁決：「限制滿版最多 4 張」）。

    以前 _cover_full_base／_yt_cover_background 默默只取前 4 張，使用者以為 5 張都上了。
    在端點入口就擋，擋在斷句／消化任何模型呼叫之前，白燒不到一通。只管會自動切格的
    滿版格（十點滿版、整點單則）；雙切的半格 ≥2 張本來就鎖成 AI改圖，不歸這裡。
    """
    # 上限來自版型能力矩陣（editor_formats.FORMAT_CAPABILITIES.asis_max），呼叫端傳進來
    n = sum(1 for ref in refs if ref.purpose == "asis")
    if limit and n > limit:
        raise HTTPException(
            status_code=400,
            detail=f"{where}原圖放置最多 {limit} 張（收到 {n} 張），請移除多的再送",
        )


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    provider: Literal["gemini", "gpt"] = "gemini"
    aspect_ratio: str = "16:9"
    image_size: str = "1K"
    density: str = ""
    # 使用者的安全框開關。⚠️ 不等於「要不要後製」——編輯版兩檔都會後製，
    # 這個旗標只決定用哪一種（見 resolve_frame_plan）。
    safe_frame: bool = False
    # D26（2026-09-26）：見 GenerateRequest.frame_strategy 與 model_extension_active。
    frame_strategy: Literal["", "model_extension"] = ""
    # 帶的是**角色**（記者／編輯），不是解析後的 profile 名稱。
    # 實際用哪個框由 resolve_frame_plan 依（角色, safe_frame）決定：
    #   記者      → 官方 Locked-Frame（底部較深）
    #   編輯 OFF  → 對位框，拉伸填滿
    #   編輯 ON   → 2% 薄框，等比例置中
    safe_frame_profile: str = "記者"
    # 播出鏡面的程式白色壓框側（'left'／'right'）。空字串＝不壓白框。白框在可能的
    # 安全框後製之後才貼，因為安全框會縮放平移內容（見 compose.py）。
    broadcast_hole: str = ""
    # B110：AI 版面的挖空側，與上面的程式白框開關分離。空字串＝非播出鏡面；
    # left/right 即使 broadcast_hole 為空也要把該半邊限制成只有連續背景。
    hole_side: Literal["", "left", "right"] = ""
    # 真人肖像的參考照片（data URL）。空字串＝這次不附參考圖。
    reference_image_data_url: str = ""
    # 使用者上傳的參考圖（地圖底稿／實景參考）。與肖像參考照分開兩個欄位：
    # 肖像那格語意寫死是「人臉參考照」且由後端自動填，混用會打架。
    # 上限在 request 層就擋（不是只在 OpenRouter 傳輸層），任何後端路徑都收不進超量。
    reference_images: list[UserReferenceImage] = Field(
        default_factory=list, max_length=MAX_INPUT_REFERENCES
    )
    # 地圖類的真實座標（來自 /api/generate 的 map_points）。後端據此拼一張真實
    # 底圖、把標點畫在正確位置，再當參考圖附上去——地理不交給模型憑印象畫。
    map_points: list[MapPoint] = Field(default_factory=list, max_length=MAX_MAP_PLACES)
    # 後端自動查來的肖像參考照（2-3 人時用；data URL）。刻意與 reference_images
    # 分開兩個欄位：後者代表「使用者親自提供素材」，會觸發「不標示意圖」override，
    # 而自動查來的維基照片沒有那個語意——寫實感＋真名＋沒有示意圖標籤是最糟組合。
    # 由 resolve_portraits 決定內容，呼叫端不該自己填。
    portrait_reference_data_urls: list[str] = Field(
        default_factory=list, max_length=MAX_PORTRAIT_FACES
    )
    # 網頁版消化後回傳的具名真人名單。後端據此查參考照並注入肖像規則。
    # LINE／generate_news_image 已在組 prompt 時處理過，不要再傳，以免規則灌兩次。
    portrait_subjects: list[str] = Field(default_factory=list)
    # 同順序的英文原名，查圖備援（見 GenerateResponse.portrait_subjects_en）
    portrait_subjects_en: list[str] = Field(default_factory=list)
    # 使用者在指令欄寫的需求原文（2026-09-13）。只有**附了 AI改圖 用途的圖**時才會
    # 用到：apply_user_references_to_image_request 會把它接在 aiedit 區塊後面，當成
    # 「這張附圖要改哪裡」。其他用途的指令欄照舊由文字模型消化進畫面描述，不走這裡。
    editor_instruction: str = Field(default="", max_length=2_000)
    # B55 修法甲（2026-09-20）：只在「原圖放置只有一張＋provider=gpt」的判準下由
    # 呼叫端設 True，要求模型回一張透明底的標題圖層，疊在未經觸碰的原圖上。
    # provider=gemini 不支援 background=transparent（本 session 查證，見 compose.py
    # 那段長註解），呼叫端不會對 gemini 設這個旗標，這裡不另外擋——擋的責任在呼叫端，
    # 這裡只負責「設了就送」。
    transparent_background: bool = False
    # B70／F43（2026-09-20）：這次成品要不要程式端壓「示意圖」或「畫面來源」標籤、
    # 貼在哪個角落。兩者互斥（見 resolve_image_disclaimer），呼叫端不自己判斷該貼
    # 哪一種——一律把 portrait_mode／source_text 交給那支函式決定。空字串＝不貼。
    disclaimer_kind: Literal["", "ai", "source"] = ""
    # 只有 disclaimer_kind="source" 時使用；上限比照 vstrip 的 source_text 欄位。
    disclaimer_source_text: str = Field(default="", max_length=40)
    # 方位詞（非數字）——與版型 prompt 的鐵律同一個理由：貼的位置若要塞進 prompt
    # 告訴模型「這裡留空」，只能用方位詞。四個角落都落在安全區內（見
    # compose._disclaimer_box），不會被裁切。
    disclaimer_corner: Literal[
        "lower_right", "lower_left", "upper_right", "upper_left", "lower_center"
    ] = "lower_right"


class ImageGenerateResponse(BaseModel):
    # image_data_base64：給人看的成品（已置框／拉伸），拿去顯示與下載。
    # source_image_base64：置框「前」的原始生成圖，**只**供追加修改（refine）再編輯用。
    # 兩者不可混用——把成品餵回去改圖會二次拉伸，失真 6.4%→13.2%→20.5% 疊上去，
    # 而且每輪只多一點、很難察覺（PLAN.md ③ 的失真疊加坑）。
    # 未置框（safe_frame=False）且沒貼標籤時 source_image_base64 為空字串，成品本身
    # 就是原圖。**有貼標籤時例外**（B86）：未置框那條路的成品已經帶著一枚標籤，
    # 直接拿去 refine／restamp 會被貼上第二枚，所以 apply_image_disclaimer 會把
    # 「貼標籤之前」那張補進這一格。
    # source_mime_type＝原圖實際的 MIME（模型可能回 png 也可能回 jpeg），
    # 前端組 refine 請求時要用它，不能假設一律是 png。
    image_data_base64: str
    mime_type: str
    model: str
    source_image_base64: str = ""
    source_mime_type: str = ""
    # F40 第 3 層通知（2026-09-16）：查不到合格參考照但確認有維基條目時，允許模型
    # 依新聞語境自畫具名真人，但**不**在圖上標「長相為 AI 推測」（使用者明確裁定）——
    # 改成這裡回一則文字給前端訊息欄。空清單＝這次沒有需要通知的事。
    notices: list[str] = Field(default_factory=list)
    # B83（2026-09-22）：這次成品上**實際**貼了哪一種標籤、什麼文字、哪個角落。
    # 空字串＝這次沒貼。追加修改（/api/images/refine）與事後重貼
    # （/api/images/restamp-disclaimer）一律把這三格原樣送回來，後端**不重判**——
    # refine 不帶 portrait_subjects，重判會讓一張本來是「示意圖」的具名肖像因為
    # 來源名還留著而被降級成「畫面來源」，那是對觀眾說謊（互斥優先序見
    # resolve_image_disclaimer）。
    disclaimer_kind: Literal["", "ai", "source"] = ""
    disclaimer_source_text: str = ""
    disclaimer_corner: str = ""


# 第一頁「懶人機制」：type_label 傳這個值代表由 AI 自行判斷最適合的圖表類型
AUTO_TYPE_LABEL = "自動判斷"

# AI 可自行選擇的四大類型，需與 app.js 的 CHART_TYPES label 完全一致
CHART_TYPE_CHOICES = ["資料圖表", "情境示意圖", MAP_TYPE_LABEL, "3D示意／流程"]

DIGEST_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "style": {"type": "string"},
        "structure": {"type": "string"},
        "variable": {"type": "string"},
        # 回報這次實際採用的圖表類型；自動判斷模式下前端用它顯示 AI 選了什麼
        "chart_type": {"type": "string", "enum": CHART_TYPE_CHOICES},
        # 版面會畫出臉孔的具名真實人物，全部列出；其餘一律空陣列
        # （見 REAL_WORLD_FIDELITY_RULES 第 5 條）
        "portrait_subjects": {"type": "array", "items": {"type": "string"}},
        # 與 portrait_subjects 同順序同長度的英文（或原文拉丁拼寫）姓名，
        # 後端查參考照時當備援：臺灣譯名常常不是中文維基的條目名（見第 7 條）
        "portrait_subjects_en": {"type": "array", "items": {"type": "string"}},
        "portrait_subjects_en_guess": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "style",
        "structure",
        "variable",
        "chart_type",
        "portrait_subjects",
        "portrait_subjects_en",
        "portrait_subjects_en_guess",
    ],
    "additionalProperties": False,
}


# 地圖類專用的 schema 變體。刻意做成變體而不是直接加欄位：strict 模式下新欄位必須
# 進 required，等於每一則新聞（含記者、含非地圖類）都要多回一個永遠是空陣列的欄位。
# 只有地圖類與自動判斷會拿到它，非地圖類的 schema 物件與過去逐位元組相同。
MAP_PLACES_PROPERTY = {"type": "array", "items": {"type": "string"}}


def digest_schema(type_label: str) -> dict:
    """這次消化要用哪份 schema。地圖／自動判斷多一個 map_places。"""
    if type_label not in (MAP_TYPE_LABEL, AUTO_TYPE_LABEL):
        return DIGEST_OUTPUT_SCHEMA
    schema = copy.deepcopy(DIGEST_OUTPUT_SCHEMA)
    schema["properties"]["map_places"] = MAP_PLACES_PROPERTY
    schema["required"] = [*schema["required"], "map_places"]
    return schema


AUTO_TYPE_SELECTION_RULES = """

CHART TYPE AUTO-SELECTION (do this first):
No chart type was specified. Read the news material and choose the ONE most suitable type:
- "資料圖表": the story's core is numbers to compare or track (markets, prices, polls, statistics).
- "情境示意圖": the story's core is what a scene or incident looked like (accidents, disasters,人物場景).
- "地圖／位置": the story's core is where something is — location, route, territory, or geographic relationship.
- "3D示意／流程": the story's core is how something happened step by step, or how a mechanism works.
GEOGRAPHY WINS OVER THE INCIDENT. If the user asks for a place to be located, marked or drawn (「請畫出地理位置」「標出…的位置」「位置圖」), or if the named places in the material only make sense when the viewer sees where they are relative to one another, the answer is "地圖／位置" — even when the incident itself (a flood, a fire, a crash, a protest) would otherwise read as 情境示意圖. Drawing what the scene looked like is NOT a substitute for showing where it happened, and a request naming several places in one city is a location story, not a scene story.
Pick the single best fit; do not blend types. Report it in the "chart_type" field, and design "style" and
"structure" for the type you picked.
"""


def chart_type_directive(type_label: str) -> str:
    """自動判斷模式加上選型規則；指定類型則要求原樣回報。"""
    if type_label == AUTO_TYPE_LABEL:
        return AUTO_TYPE_SELECTION_RULES
    return f'\n\nThe "chart_type" field MUST be exactly "{type_label}".'


# ---- 兩段式消化：先便宜分類、再只注入該類型的規則（條件注入）----
#
# 為什麼：網頁預設是「自動判斷」，而自動判斷組 prompt 時不知道 AI 會選哪一類，
# 只好把 MAP_ACCURACY_RULES 一律注入——每一則新聞都在付地圖稅，即使內容跟地理
# 無關。2026-09-05 量測（同一則稿、n=7）：自動判斷 28,501 字元思考 2,184、
# 耗時 38.7s；不注入地圖規則 19,615 字元思考 1,063、耗時 23.7s。同日另一組對照
# 證明「合併精簡」省不到（約束數不變、字元 −6%，思考沒降）：思考量是被約束數量
# 推高的，不是字元數。所以要省，就得讓非地圖新聞真的少掉那一整塊約束。
#
# 作法：分類呼叫只帶 AUTO_TYPE_SELECTION_RULES 與原文，輸出只有一個 enum；
# 分類成功就把這次消化當成「使用者明確指定該類型」來組 prompt、選 schema、給預算。
#
# 失敗一律退回舊路徑（注入地圖規則的自動判斷）：逾時、例外、finish=length、
# 空內容、不認得的類型都算失敗。單次呼叫、不重試——多一個呼叫不可以變成新的
# 失敗模式（當天已有一次 502 是重試風暴造成的）。
#
# 旗標預設關：DIGEST_TWO_STAGE=1 才啟用。分類正確率與總延遲要先量過再上，
# 分類錯的代價是整張圖用錯類型，比多花思考 token 嚴重。
DIGEST_TWO_STAGE = os.getenv("DIGEST_TWO_STAGE", "") == "1"
# 推理模型的思考 token 算在輸出上限內；給太小會 finish=length → 全數退回舊路徑，
# 測試全綠、零效益、沒人知道。實測請以「分類器實際回標籤率」為準。
CLASSIFY_MAX_TOKENS = 1500
CLASSIFY_TIMEOUT_SECONDS = 20.0
CLASSIFY_SYSTEM_PROMPT = (
    "You are a broadcast news graphics director for a Taiwanese news desk. "
    "Read the news material (and any user instruction that follows it) and decide "
    "which ONE chart type the graphic should be. Return ONLY the JSON object."
    + AUTO_TYPE_SELECTION_RULES
)
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {"chart_type": {"type": "string", "enum": CHART_TYPE_CHOICES}},
    "required": ["chart_type"],
    "additionalProperties": False,
}


def classify_chart_type(
    news_text: str, user_instruction: str, model: str
) -> str | None:
    """先用一次便宜的呼叫決定圖表類型。回 None 代表「用舊路徑」。

    一定要連 user_instruction 一起看：現行 DEDICATED_INSTRUCTION_RULES 允許指令欄
    改類型（「請畫出地理位置」），改成明確指定後那條路就沒了，分類器若只看原文，
    會重演 test_map_gate_and_usage 記錄的那個病灶。
    """
    material = f'News Source Material:\n"{news_text}"'
    if user_instruction.strip():
        material += f"\n\nUser instruction:\n{user_instruction.strip()}"
    try:
        response = digest_completion(
            model=model,
            system_prompt=CLASSIFY_SYSTEM_PROMPT,
            news_text=material,
            max_output_tokens=CLASSIFY_MAX_TOKENS,
            schema_name="news_cg_chart_type",
            schema=CLASSIFY_SCHEMA,
            site="classify",
            raw_user_message=True,
            timeout=CLASSIFY_TIMEOUT_SECONDS,
        )
        choice = response.choices[0]
        if choice.finish_reason != "stop":
            print(f"[classify] finish_reason={choice.finish_reason}，退回舊路徑", flush=True)
            return None
        data = json.loads(choice.message.content or "")
    except Exception as exc:  # noqa: BLE001 — 任何失敗都只是退回舊路徑
        print(f"[classify] 失敗，退回舊路徑：{type(exc).__name__}: {exc}", flush=True)
        return None
    label = data.get("chart_type") if isinstance(data, dict) else None
    if label not in CHART_TYPE_CHOICES:
        print(f"[classify] 回了不認得的類型 {label!r}，退回舊路徑", flush=True)
        return None
    return label


def resolve_effective_type_label(req: "GenerateRequest", model: str) -> str:
    """這次消化實際依哪個類型組 prompt。只有自動判斷＋旗標開才會去分類。"""
    if req.type_label != AUTO_TYPE_LABEL or not DIGEST_TWO_STAGE:
        return req.type_label
    label = classify_chart_type(req.news_text, req.user_instruction, model)
    if label is None:
        return AUTO_TYPE_LABEL
    print(f"[classify] 自動判斷 → {label}，只注入該類型規則", flush=True)
    return label


def extract_image_content(result: dict) -> dict | None:
    """Extract the final image from SDK, current REST, or legacy REST shapes."""
    output_image = result.get("output_image")
    if isinstance(output_image, dict) and output_image.get("data"):
        return output_image

    for collection_name in ("steps", "outputs"):
        for item in reversed(result.get(collection_name) or []):
            if not isinstance(item, dict):
                continue
            content_blocks = item.get("content") or [item]
            for content in reversed(content_blocks):
                if (
                    isinstance(content, dict)
                    and content.get("type") == "image"
                    and content.get("data")
                ):
                    return content

    return None


# structure 的版面規則。安全框模式維持原本「縮小置中留厚邊」；滿版模式（safe_frame）
# 改成用滿畫布，留白交由後端 safe_frame.py 數學置框——四輪實驗證實模型量不出比例，
# 底部安全區 0 次合格，但「畫滿」它做得很好。兩種模式都嚴禁出現任何數字：
# 數字會被模型當文字畫進圖裡（見 docs/error-cases/2026-07-23-像素安全框-分析.md）。
REPORTER_LAYOUT_SAFE_AREA = """   - BROADCAST SAFE AREA (NON-NEGOTIABLE): the structure description MUST begin with this exact sentence: "The entire infographic — including the title, icon cards, and side panels — is treated as one group and scaled down so it occupies only the central region of the frame, surrounded by a thick, clearly visible empty margin of unchanged background on the top, left and right, and an even deeper empty band along the bottom; every element stays well inside this central zone and nothing reaches into the surrounding empty border." After that sentence, every element you place (headline, stat cards, indicators, icons) MUST be positioned using ONLY qualitative spatial words (e.g. "in the upper-left area", "centred", "along the right side well clear of the edge", "with generous empty space around it"). NEVER express any position, inset, gutter, margin, or size as a percentage, pixel, ratio, or number of any kind — those figures get drawn as visible text labels in the final image. Never describe anything as spanning, flush, or edge-to-edge. The words "footer", "bottom edge", "anchored at bottom", "full-screen", "full-bleed", "full-width", "edge-to-edge", "flush left", "flush right", "spans the entire width", "corner-to-corner" and "bleed" are FORBIDDEN. Any closing banner or data-source line is the LOWEST ROW OF THE CONTENT AREA, sitting well above the reserved bottom margin, never at the frame bottom or against any edge."""

EDITOR_LAYOUT_SAFE_AREA = """   - BROADCAST SAFE AREA (NON-NEGOTIABLE): the structure description MUST begin with this exact sentence: "The entire infographic — including the title, icon cards, and data charts — is treated as one group and scaled down so it occupies only the central region of the frame, surrounded by a thick, clearly visible empty margin of unchanged background on the top, left and right, and an even deeper empty band along the bottom; every element stays well inside this central zone and nothing reaches into the surrounding empty border." After that sentence, every element you place MUST be positioned using ONLY qualitative spatial words (e.g. "in the upper-left area", "centred", "along the right side well clear of the edge", "with generous empty space around it"). NEVER express any position, inset, gutter, margin, or size as a percentage, pixel, ratio, or number of any kind — those figures get drawn as visible text labels in the final image. Never describe anything as spanning, flush, or edge-to-edge. The words "footer", "bottom edge", "anchored at bottom", "full-screen", "full-bleed", "full-width", "edge-to-edge", "flush left", "flush right", "flush top", "flush bottom", "spans the entire width", "corner-to-corner" and "bleed" are FORBIDDEN. The <蓋章> stamp banner and any data-source line are the LOWEST ROW OF THE CONTENT AREA, sitting well above the reserved bottom margin, never at the frame bottom or against any edge."""

REPORTER_LAYOUT_FULL_BLEED = """   - FULL-FRAME LAYOUT (NON-NEGOTIABLE): the structure description MUST begin with this exact sentence: "The infographic uses the entire frame edge to edge, with only a slim even breathing space just inside the frame border so that no element is clipped; the background is one single continuous image covering the whole canvas." After that sentence, every element you place (headline, stat cards, indicators, icons) MUST be positioned using ONLY qualitative spatial words (e.g. "across the upper area", "centred", "along the right side", "with clear separation from its neighbours"). NEVER express any position, inset, gutter, margin, or size as a percentage, pixel, ratio, or number of any kind — those figures get drawn as visible text labels in the final image. Never reserve an empty margin, empty band, or letterboxed area, and never scale the design down into a smaller central region. Any closing banner or data-source line is the LOWEST ROW OF THE DESIGN, sitting just inside the frame border rather than reserved away from it."""

EDITOR_LAYOUT_FULL_BLEED = """   - FULL-FRAME LAYOUT (NON-NEGOTIABLE): the structure description MUST begin with this exact sentence: "The infographic uses the entire frame edge to edge, with only a slim even breathing space just inside the frame border so that no element is clipped; the background is one single continuous image covering the whole canvas." After that sentence, every element you place MUST be positioned using ONLY qualitative spatial words (e.g. "across the upper area", "centred", "along the right side", "with clear separation from its neighbours"). NEVER express any position, inset, gutter, margin, or size as a percentage, pixel, ratio, or number of any kind — those figures get drawn as visible text labels in the final image. Never reserve an empty margin, empty band, or letterboxed area, and never scale the design down into a smaller central region. The <蓋章> stamp banner and any data-source line are the LOWEST ROW OF THE DESIGN, sitting just inside the frame border rather than reserved away from it."""


SYSTEM_PROMPT_TEMPLATE = """You are an elite broadcast news graphics director for a Taiwanese international news desk.
The current chart type is: "{type_label}".
Digest the raw news text and organize it into a structured infographic specification suited to this chart type.

Return ONLY a JSON object (no markdown, no prose) with exactly these keys: style, structure, variable.

Requirements:
1. "variable": Extract key points. Format using [標題], [內文小標], <強調文字>.
   - CONTENT MUST BE IN TRADITIONAL CHINESE (Taiwan standard).
   - Concise phrases, no punctuation.
   - NUMERAL FORMAT: Use Arabic numerals (0-9) for any value naturally read as a figure — percentages, statistics, money, counts, measurements, dates, times, scores, index points (e.g. 10%, 4.25%, 350點, 2萬, 3公里). NEVER spell such figures out as Chinese numerals (write 10% not 十成/百分之十; write 350 not 三百五十). Chinese numerals are allowed only for idiomatic / non-quantitative words (e.g. 三度, 兩次, 第一). Use your own judgement on which category a number falls into.
2. "style": Choose a professional visual style appropriate for a "{type_label}", written in professional English.
3. "structure": Design the most readable, intuitive layout for a "{type_label}".
   - Propose concrete spatial arrangement and add instructions for relevant icons, technical illustrations, 3D diagrams, maps, or scene depictions that aid comprehension.
   - Written in professional English.
{layout_rule}"""


# 編輯版：規範取自編輯台實戰 GEM「整理小幫手」（見 editor-templates/PROMPTS.md）
EDITOR_SYSTEM_PROMPT_TEMPLATE = """你是一名專業的「新聞編播重點分析師」。你的任務是從繁雜的記者文稿、節目逐字稿或數據資訊中，去蕪存菁，提煉出最適合電視新聞主播解說的「鏡面 CG 文案」（圖表類型：{type_label}）。

Return ONLY a JSON object (no markdown, no prose) with exactly these keys: style, structure, variable.

1. "variable"（鏡面 CG 文案，必須嚴格遵守）:
   - 台灣繁體中文。總字數嚴禁超過 150-180 個字。寫作難度預設為高中程度，專業但不艱澀。
   - 嚴禁出現「，」與「。」，短句停頓統一使用全形空格替代。
   - 格式依序為（使用真實換行 \\n，缺一不可）：
     [標題] 大標題預設拆分為兩行、不含標點；只有字極少 MODE 可依可讀性使用單行，但不強制單行
     [內文小標]＋條列重點，每行不超過 15 字
     最後一行必須是 <蓋章> 開頭，標示整張 CG 最核心的結論或金句（精簡有力）
   - 需要變色或加框的關鍵詞（數據、人名）用 <文字> 標示。
   - 若原始資訊包含統計數據，優先列入重點。
   - 數字格式：凡本質上以數值呈現的資訊（百分比、統計數據、金額、點數、次數、度量、日期時間），一律使用阿拉伯數字（例如 10%、4.25%、350點、2萬、3公里），嚴禁改寫成中文數字（須寫 10% 而非「十成」「百分之十」；須寫 350 而非「三百五十」）。中文數字僅限慣用語或非計量詞（例如「三度」「兩次」「第一」）。需要時自行判斷該數字屬於哪一類。
   - variable 格式範例（示意，內容依實際新聞）：
     "[標題] 聯準會三度降息\\n利率降至<4.25%>\\n[內文小標] 通膨降溫 就業穩健\\n[內文小標] 市場預期 明年再降<兩次>\\n[內文小標] 道瓊應聲<上漲350點>\\n<蓋章> 降息循環正式啟動"
2. "style": 根據新聞調性（財經、災難、溫馨、政治）自行選擇最合適的主色調與畫面風格，written in professional English.
3. "structure": Design the most readable anchor-wall CG layout for a "{type_label}", with concrete spatial arrangement and instructions for flat icons or 3D data charts that aid comprehension. Written in professional English.
{layout_rule}"""


# 「字多」檔（2026-09-09 使用者回饋）。三檔裡以前只有字少與不改字有 override 區塊，
# 字多什麼都不注入——它就是樣板本身，所以選了跟沒選一樣。使用者回報「字多消化後
# 資訊量還是太少，可以放寬資訊卡的數量／資訊密度／內文字數」，這一塊就是那個放寬。
#
# 蓋掉的是編輯版樣板寫死的「150-180 字」與「每行不超過 15 字」；記者版樣板沒有數量
# 上限可蓋，對它而言這塊是正向指示（多列幾點、每點帶得動細節）。
#
# 第 6 條刻意留給後面的版型區塊：播出鏡面的第 6 條寫「exactly four．．．no more and
# no fewer」，那是版面實體限制（卡片就那幾列），不能被這塊的 target／下限蓋掉。
# POINT COUNT 的數字只准從 density_point_bounds() 填進來，禁止在這段文字再寫一份。
_DENSITY_COUNT_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
}
_DENSITY_COUNT_VALUES = {word: n for n, word in _DENSITY_COUNT_WORDS.items()}
_DENSITY_POINT_LINE_RE = re.compile(r"^\s*[\[【]內文小標[\]】]")
_DENSITY_POINT_TARGETS = {"simplified": 4, "standard": 6, "maximum": 8}
_DENSITY_POINT_FLOOR_DELTA = 1
# B105：字少只有在來源確實有一定資訊量時才守三點下限。六十個可見字約能支撐
# 三個十四至十八字的重點，並保留標題／取捨空間；低於門檻視為薄稿，不要求補點。
SIMPLIFIED_SOURCE_MIN_VISIBLE_CHARS = 60
MINIMAL_POINT_HARD_MAX = 3


def density_count_word(n: int) -> str:
    """把塊數寫進 prompt 用的英文數字。業務數字本身不在這裡。"""
    return _DENSITY_COUNT_WORDS[n]


def _format_exact_point_count(format_key: str | None, density: str | None) -> int | None:
    """版型若釘死卡片列數，回傳那個整數；否則 None。

    播出鏡面的張數以 editor_formats._broadcast_point_count 為唯一來源，
    這裡只做 three／four → 3／4 的用詞轉換，不另寫一份 3、4。
    """
    if not format_key:
        return None
    if not editor_formats.resolve_hole_side(format_key):
        return None
    word = editor_formats._broadcast_point_count(density)["count_word"]
    return _DENSITY_COUNT_VALUES[word]


def density_point_bounds(
    density: str | None, format_key: str | None = None
) -> tuple[int | None, int | None]:
    """[內文小標] 的 (minimum, target)。沒有塊數契約時兩邊都是 None。

    一般版型：simplified target 4／素材足夠時下限 3；standard target 6／下限 5，
    maximum target 8／下限 7。
    特定版型若有更嚴格的 exact count，exact 優先——minimum 與 target 都等於該數。
    minimal 的 1～3 點契約另由 hard max 守門；逐字／無字沒有塊數契約。
    """
    if density not in _DENSITY_POINT_TARGETS:
        return None, None
    exact = _format_exact_point_count(format_key, density)
    if exact is not None:
        return exact, exact
    target = _DENSITY_POINT_TARGETS[density]
    return target - _DENSITY_POINT_FLOOR_DELTA, target


def _density_bound_words(density: str) -> dict[str, str]:
    """把 density_point_bounds 的數字編成 prompt 佔位符。不含 format_key：
    通用密度區塊永遠寫級距本身，版型 exact 由後面的區塊覆蓋。"""
    minimum, target = density_point_bounds(density)
    if minimum is None or target is None:
        raise ValueError(f"{density} 沒有塊數契約，不能編成密度規則")
    _, standard_target = density_point_bounds("standard")
    if standard_target is None:
        raise ValueError("standard 必須有 target，才能寫進字超多區塊")
    return {
        "minimum_word": density_count_word(minimum),
        "target_word": density_count_word(target),
        "target_word_upper": density_count_word(target).upper(),
        "standard_target_word": density_count_word(standard_target),
    }


def count_density_points(variable: str) -> int:
    """數 variable 裡以 [內文小標]／【內文小標】開頭的塊。

    只認行首標記，不數換行、不把 [標題]、<蓋章>、<底帶>、來源、備註算進去。
    播出鏡面「短標｜細節」寫在同一行仍是一塊。
    """
    return sum(
        1 for line in (variable or "").splitlines() if _DENSITY_POINT_LINE_RE.match(line)
    )


STANDARD_DENSITY_RULES = """

字多 MODE (THE USER ASKED FOR THE DENSE VERSION) — THIS BLOCK OVERRIDES THE LENGTH AND COUNT LIMITS STATED ABOVE:
1. This is the densest of the three digestion settings, and the user chose it because the graphic was coming back carrying too little information. Your job here is to fill the graphic, not to summarise it down.
2. POINT COUNT: TARGET {target_word} [內文小標] lines. Never fewer than {minimum_word}. Carry every distinct point the source material genuinely supports up to that target. Do not stop at three out of habit. Two facts that belong to different aspects of the story are two points, not one merged line.
3. LINE LENGTH: {line_limit_clause} Each [內文小標] line may run to about twenty-four characters, long enough to carry a figure and what that figure means in the same line.
4. TOTAL LENGTH: {total_limit_clause} Aim for roughly two hundred and forty to three hundred and twenty characters in total.
5. DENSITY PER POINT: a point that states only a bare fact is under-written at this setting. Give each line its figure AND its consequence, its comparison, its timing or its source — whichever the material supplies.
6. A LATER BLOCK MAY FIX AN EXACT COUNT FOR A SPECIFIC LAYOUT. When a format-specific block below states an exact number of [內文小標] lines, that number wins over the target of {target_word} and the minimum of {minimum_word} in rule two: the card stack of that layout physically has that many rows. Rules three, four and five still apply inside those rows.
7. THIS LICENSES NOTHING NEW. Every added line must come from the source material. Do not invent a figure, do not restate a point you already made in different words, and do not pad with generic background to reach a length. Falling short of {minimum_word} lines is a defect — do not stop at three out of habit.
8. Design "structure" for that quantity: enough rows or cards for the points you wrote, sized so the longer lines stay legible on air rather than shrinking to fit.
9. HEADLINE LIMIT: [標題] may contain no more than 18 visible characters. Count after removing all whitespace and the < and > markers; markers themselves do not count. Never delete or alter an existing fact merely to shorten the headline.
"""

# 第 3、4 條要指名蓋掉的上限——但那兩個上限只寫在編輯版樣板裡。對記者版指名一個
# 不存在的句子只會讓模型去找它，所以兩個角色各給一句自己的措辭。
_STANDARD_LIMIT_CLAUSES = {
    True: {
        "line_limit_clause": "The 「每行不超過 15 字」 limit above is LIFTED.",
        "total_limit_clause": "The 「總字數嚴禁超過 150-180 個字」 target above is LIFTED.",
    },
    False: {
        "line_limit_clause": "There is no per-line character cap at this setting.",
        "total_limit_clause": "There is no total-length cap at this setting.",
    },
}


SIMPLIFIED_DENSITY_RULES = """

SIMPLIFIED MODE OVERRIDE — THESE RULES OVERRIDE ANY EARLIER STANDARD-MODE LENGTH OR FORMAT REQUIREMENT:
1. POINT COUNT: TARGET four [內文小標] lines. When the source genuinely supplies enough distinct facts, never fewer than three. For a genuinely thin source, use one or two instead: never pad, repeat, split one fact unnaturally, or invent material merely to reach the target. This rule overrides the three-point example above.
2. LINE LENGTH: aim for about fourteen to eighteen visible characters per [內文小標] line. Each point communicates one fact in a short, scan-friendly line and may be shorter when that is all the fact needs. Do not repeat the same fact in the title, points, or conclusion.
3. TOTAL BODY LENGTH: aim for roughly forty-five to seventy-five visible characters across the [內文小標] lines. Remove secondary background, side facts, repeated numbers, and details that do not improve immediate understanding; source fidelity always wins over the length target.
4. Use ONE dominant visual focus and choose the best presentation for the material:
   A. one hero map/chart/person/scene/process with up to four short callouts;
   B. one dominant number or conclusion with up to three supporting labels;
   C. one large thematic image/map/scene with text confined to one compact area.
5. Do not add multiple secondary card groups, unnecessary decorative icons, competing focal points, or invented filler text.
6. For editor role, ignore the earlier 150-180 character target. <蓋章> is optional and must appear only when the source supports a clear conclusion or quote; it does not replace any [內文小標] point required by rule one.
7. HEADLINE LIMIT: [標題] may contain no more than 13 visible characters. Count after removing all whitespace and the < and > markers; markers themselves do not count. Never delete or alter an existing fact merely to shorten the headline.
"""


# 「字極少」檔（2026-09-10 五段拉桿的左二）。SIMPLIFIED 之後才注入，所以它只要
# 講「再往下收」就好，不必重寫一套。這一級的用途是「一眼看完」的大字卡。
MINIMAL_DENSITY_RULES = """

字極少 MODE — THIS BLOCK IS EVEN TIGHTER THAN THE SIMPLIFIED BLOCK ABOVE AND OVERRIDES IT WHEREVER THEY DISAGREE:
1. POINT COUNT: TARGET ONE [內文小標] point. One to three points are acceptable, but THREE is the HARD MAXIMUM. Pick the single fact that the audience must leave with first; add a second or third only when the source genuinely needs them for immediate understanding. Never pad, repeat or invent.
2. LINE LENGTH: each [內文小標] line runs to at most about twelve visible characters. If it will not fit, cut words, never shrink the meaning into jargon.
3. TOTAL BODY LENGTH: aim for roughly twelve to thirty visible characters across all [內文小標] lines. The graphic is one dominant statement — one huge number, name or conclusion — with at most two short supporting points beside or beneath it. No card stack, no secondary group, no callout cluster.
4. The headline and the points must not say the same thing twice in different words. If they would, rewrite a point to carry what the headline does not.
5. Design "structure" for that: one focal element occupying the middle of the content area at a size readable across a room, everything else empty.
6. HEADLINE LIMIT: [標題] may contain no more than 10 visible characters. Count after removing all whitespace and the < and > markers; markers themselves do not count. Never delete or alter an existing fact merely to shorten the headline.
"""

# 「字超多」檔（2026-09-10 五段拉桿的右一）。STANDARD 之後才注入。
# 加的是**密度**，不是新的許可——第 3 條刻意重申「不准編」，因為要求更多字最容易
# 誘發模型自己補料，而封面／CG 上編出來的數字是對外事故。
MAXIMUM_DENSITY_RULES = """

字超多 MODE — THIS BLOCK GOES BEYOND THE 字多 BLOCK ABOVE AND OVERRIDES IT WHEREVER THEY DISAGREE:
1. POINT COUNT: TARGET {target_word_upper} [內文小標] lines. Never fewer than {minimum_word}. The rule above targeted {standard_target_word}; this setting raises both the target and the floor.
2. LINE LENGTH AND TOTAL: each [內文小標] line may run to about thirty characters, and the whole graphic may reach roughly three hundred and sixty to four hundred and eighty characters. Every line still has to be readable on air — long is not the same as cramped.
3. THIS STILL LICENSES NOTHING NEW. Every added line comes from the source material. Do not invent a figure, a date, a name or a cause to reach the count; do not restate an earlier point in different words; do not pad with generic background. Falling short of {minimum_word} lines is a defect — do not stop at three out of habit.
4. YOU MAY SPLIT WHAT IS ALREADY THERE. Where the source states a compound fact in one breath — one sentence carrying two distinct figures, two places, two measures or two consequences — you may write it out as two separate points instead of one crowded entry. This is the one thing this setting unlocks that the 字多 block did not.
5. THAT IS A LICENCE TO SPLIT, NEVER A LICENCE TO SUPPLY. The split halves must both already be present in the source, in the source's own terms. Do not add a cause, a person, a time, a figure, a place, a consequence or any background the source did not state; do not manufacture a second point by saying the same thing again in other words; and where the second half would have to be invented to make the split work, leave the fact whole as one point. After splitting, the set of facts on the graphic must be identical to the set of facts in the source — only their arrangement changed.
6. Group the points: when you write more than five, say in "structure" that they are arranged in labelled groups or two columns rather than one long list, so the viewer can find the one that matters.
7. A LATER BLOCK MAY STILL FIX AN EXACT COUNT FOR A SPECIFIC LAYOUT, and that number wins over the target of {target_word} and the minimum of {minimum_word} here: those card stacks physically have that many rows.
8. HEADLINE LIMIT: [標題] may contain no more than 22 visible characters. Count after removing all whitespace and the < and > markers; markers themselves do not count. Never delete or alter an existing fact merely to shorten the headline.
"""


# ============================================================
# CG 創意拉桿（2026-09-10 使用者：「創意程度除了十點不一樣之外，編輯的播出鏡面、
# 記者版的，是否也可以加入這個功能。編輯的 yt 封面就不用了。」）
#
# 為什麼不能直接把十點那一段接過來：十點調的是「封面上那三行標題長什麼樣」，
# 整段條文都在講標題塊。播出鏡面／記者版沒有那種標題塊，它們是一整張資訊圖，
# 而且身上綁著安全框、卡片列數、標題強制拆兩行這些硬規則。照抄只會被忽略。
#
# 所以這一套調的是標題與關鍵數字的字體、描邊、壓框、立體、裝飾，外加**版面結構**。
#
# 2026-09-10 第二版：第一版只調美術、明文寫「排列與卡片數維持上面所述」，實拍 0–4
# 五張（記者版／高溫熱傷害）證明那條拉桿是平的——0、3、4 都是同一種橫幅條列卡，
# 1、2 抽到地圖版反而比「最狂」還敢，級數之間不成單調。diff 五級的 structure 文字
# 看得很清楚：五級第一句一字不差，差異全部落在標題的表面加工形容詞
# （heavier cut → thick outline → hard drop shadow → chrome extrusion），
# 而真正拉開差距的結構變數（幾欄、有沒有數字英雄區、卡片形狀語言、去背主體）
# 完全不受等級控制、由消化模型自由發揮。教訓與十點那條同一句：
# **形容詞會被圖模平均掉，結構才有階梯。**
#
# 所以第二版把槓桿換成結構性的：L1 分區、L2 英雄區＋形狀語言、L3 破格排列＋
# 去背主體越界、L4 斜切分割＋英雄元素跨區（傾斜從「可以」改成「必須」）。
# 每一級尾巴那句「排列與卡片數維持上面所述」全部刪掉——留著等於自相矛盾，
# 模型會往限制較嚴的那句收斂，這正是第一版平掉的機制。
#
# 仍然不准碰的是 _CG_CREATIVITY_FIXED：點數／[內文小標] 行數（上鏡規約）、
# 安全留白、禁數字幾何、不准新增文字。結構拉桿改的是「怎麼排」，不是「排幾個」。
# FIXED (g) 是這一版新加的：等級叫模型挑一個主視覺，而地圖是它最愛挑的——
# 但行政區界一律畫錯（見 docs/error-cases/2026-09-10-台灣行政區界-錯誤-分析.md）。
#
# 注入點在 editor_formats.digest_rules 之後（本 repo 慣例：位置在後＋明文 OVERRIDE
# 才壓得住），但條文自己第一句就聲明「只覆蓋美術，不覆蓋版面與內容」。
# 等級名稱 0-4 搬進 creativity.py（P2），與 editor_formats.COVER_AI_TITLE_LEVEL_NAMES
# 共用同一份字典——兩邊手寫值原本逐字相同，改一處忘了改另一處的風險同 target="digest"
# 那段收斂的理由。這裡留舊名稱當別名，呼叫端（cg_creativity_rules 等）不用跟著改。
CG_CREATIVITY_LEVEL_MIN = creativity.LEVEL_MIN
CG_CREATIVITY_LEVEL_MAX = creativity.LEVEL_MAX
CG_CREATIVITY_LEVEL_NAMES = creativity.LEVEL_NAMES

# 「拉桿不准碰的東西」搬進 creativity.py（target="digest"），三處共用的持有權
# 收在一起，改一處忘了改另外兩處的問題見該檔案開頭說明。這裡刻意不留本地副本，
# 逐字元原封不動地轉呼叫，維持 tests/test_reporter_prompt_frozen.py 的位元組凍結。
_CG_CREATIVITY_FIXED = creativity.fixed_block(target="digest")

_CG_L1 = """

VISUAL CREATIVITY — LEVEL 1 OF 4 (LIGHT). This paragraph overrides the earlier wording ONLY where they disagree about how the graphic is ARRANGED and how the text LOOKS; it changes nothing about what the text SAYS, how many points there are, or the reserved broadcast margin.
In "structure", require both:
- LAYOUT: the content area is divided into a clearly dominant visual zone and a clearly subordinate text zone. Say which side each occupies. One of them leads; they are not two halves of equal weight.
- FINISH: a designed display treatment for the headline and the key figures — a heavier display cut, a clean outline, a soft drop shadow, and one accent colour used consistently.
"""

_CG_L2 = """

VISUAL CREATIVITY — LEVEL 2 OF 4 (DESIGNED). This paragraph overrides the earlier wording ONLY where they disagree about how the graphic is ARRANGED and how the text LOOKS; it changes nothing about what the text SAYS, how many points there are, or the reserved broadcast margin.
In "structure", require all of the following, not as options:
- HERO ZONE: one single element — the most important figure, the most important short phrase, or the one subject image the story is about — is given a zone of its own that dominates the content area, and every remaining point is laid out around it as clearly smaller supporting material. Name in "structure" which element is the hero. A layout where every point gets the same weight is under-designed at this setting.
- SHAPE LANGUAGE: the cards and panels share one deliberate shape — all softly rounded, or all hard-cornered, or all cut on the same slant — and each one carries a defined edge (a thin bright rule, a subtle inner glow, or a soft outer shadow) so it reads as an object rather than a rectangle of colour.
- The headline carries a designed display treatment: heavy cut, thick outline, hard drop shadow.
- IN EVERY CARD OR POINT, the figure or key phrase already marked with angle brackets is pulled out visually — set larger than the words around it and given a contrasting colour, or reversed out of a solid colour block.
"""

_CG_L3_EXTRA = """- BREAK THE GRID: the supporting points stop being a stack of equal rows. Arrange them asymmetrically — stepped down a diagonal, split into a short column beside the hero zone, or wrapped around the hero element on two sides — and say in "structure" which arrangement you chose. The number of points does not change; only how they sit.
- THE SUBJECT IMAGE BECOMES AN OBJECT, NOT A BACKDROP: cut the main subject out and let it overlap the edge of a panel or the hero zone, instead of sitting flat behind everything as a full-frame photograph.
- SIZE HIERARCHY INSIDE THE TYPE: the headline and the single most important figure are set far larger than the supporting lines — a clear step, not a nudge — while the supporting lines stay at one consistent size as each other.
- The background carries a themed texture or gradient related to the subject (circuitry, water, smoke, topography), kept dark and low-contrast behind the text so nothing competes with the words.
"""

# 高一級＝低一級的全文再加碼，不用「照 level two 那樣做」的引用：模型看不到別份
# prompt，引用等於沒寫。（十點那條拉桿是同一個做法。）
_CG_L3 = _CG_L2.replace("LEVEL 2 OF 4 (DESIGNED)", "LEVEL 3 OF 4 (LOUD)") + _CG_L3_EXTRA

_CG_L4_EXTRA = """- GO FURTHER — THIS IS THE LOUDEST SETTING. Everything above still applies; now push both the arrangement and the art to the edge of what still reads:
- THE DIVISION OF THE FRAME IS NO LONGER ORTHOGONAL: the boundary between the hero zone and the supporting material is a slant, a sweep or a torn edge running across the content area, and the panels follow that same angle. Straight horizontal bands stacked one above another are the thing this setting exists to get away from.
- THE HERO ELEMENT BREAKS ITS OWN ZONE: it overlaps the dividing edge and sits partly over the supporting side, so the two zones interlock instead of abutting.
- THE SUPPORTING PANELS FOLLOW THE ANGLE THEMSELVES: each is cut on the same slant and set at a different offset from its neighbour, stepping along the dividing edge instead of sitting in a tidy column.
- THE HERO FIGURE OR PHRASE IS SET AT LEAST TWICE THE HEIGHT of anything else on the graphic — a gap nobody could mistake for ordinary emphasis.
- ONE SIDE OF THE FRAME IS GIVEN TO A SINGLE DRAMATIC IMAGE running the full height of the content area, so the graphic reads as picture-and-panels rather than as text over a background.
- Stack outlines on the headline and the hero figure (a thick dark one, then a bright one outside it) and give them a deep three-dimensional extrusion with a treatment drawn from the story — molten metal, neon, cracked stone, wet chrome.
- THE HEADLINE BLOCK TILTS OR ARCS — this is required at this setting, not offered (a few degrees, never more than about eight) — and its characters step up and down instead of sitting on one baseline.
- Add energy around the hero element: radiating lines, sparks, shards, a splashed or torn colour shape, a burst of glow.
- The background may darken further so all of this still reads.
- LOUD IS NOT THE SAME AS BROKEN: nothing tilts far enough to touch or overrun the reserved empty margin, no decoration crosses a stroke, every point the material supports is still present and still legible at broadcast distance, and no card is dropped, merged or duplicated to make an angle work.
"""

_CG_CREATIVITY_BLOCKS = {
    1: _CG_L1,
    2: _CG_L2,
    3: _CG_L3,
    4: _CG_L3.replace("LEVEL 3 OF 4 (LOUD)", "LEVEL 4 OF 4 (LOUDEST)") + _CG_L4_EXTRA,
}


# ---- A1／A5／A2：CG 線接上既有變化池與程式決定的配件（2026-09-15）----
#
# 使用者回報「最高級還是不夠亮」的直接原因不是條文寫得不夠狠，是**每一級注入的
# 都是同一段固定文字**：沒有抽籤，模型每次讀到一模一樣的指示，自然每次交同一個
# 長相。十點封面 2026-09-11 已經把這件事驗過一輪，解法是同一批池子＋同一顆 seed，
# 而且輸出一律是命令句——「你可以選」推不動模型，這個 repo 記過三次。
#
# 池子與抽籤順序沿用 creativity.draw()：plate → stagger → typeface → palette →
# anchor → tilt_dir。**不另立一套 CG 專用池**，那正是 A5（十點創意階梯移植回通用版）
# 要消掉的重複。配件接著同一顆 rng 往下抽（見 creativity.accessories 的 rng 參數）。
_CG_DESIGN_DRAW_TEMPLATE = """
THE DESIGN DRAW FOR THIS GRAPHIC — THESE SIX ARE ALREADY DECIDED FOR YOU. THEY ARE GIVENS, NOT A MENU, AND THEY DO NOT CHANGE WHAT THE TEXT SAYS:
- PLATE SHAPE: every panel, card or plate sitting behind text is {plate}. One shape language across the whole graphic.
- ARRANGEMENT: {stagger}.
- TYPEFACE: set the headline and the key figures in {typeface}.
- PALETTE: work in these four and no others — {c0} leads, {c1} is the ground, {c2} is the accent, {c3} is held in reserve. WHICH element carries the accent is decided by meaning, never by row order; the directional colour convention stated earlier still wins for any rise or fall in the data.
- HEADLINE BLOCK: sit it {anchor}.
- TILT DIRECTION: wherever a level above asks for a tilt or an angle, it runs {tilt_dir}.
"""

# 配件段的抬頭。測試與注入點都指名它，所以是模組層常數而不是內嵌字串。
CG_ACCESSORY_HEADING = (
    "WORDLESS DEVICES CHOSEN FOR THIS GRAPHIC — DRAW EVERY ONE OF THEM, THEY ARE NOT OPTIONS:"
)

# 釘在每一件配件後面的幾何。十點那句寫的是「中央切線」（雙切版面才有的東西），
# CG 沒有那條線；CG 的硬邊界是播出安全留白。
_CG_ACCESSORY_NOTE = (
    "  ← INSIDE THE CONTENT AREA ONLY: never into the reserved empty margin, never"
    " across a stroke, and it carries no writing of its own."
)

# 池子裡唯一帶著十點版面家具的條目：iconrow 寫的是「深藍底條的上方」，那是十點封面
# 的底帶，CG 沒有。只換這一條的措辭，**不動池子長度也不動抽籤順序**——增刪條目會把
# 所有既有 seed 的長相換掉（見 creativity.py 開頭的風險 2）。
_CG_ACCESSORY_OVERRIDES = {
    "iconrow": (
        "A SHORT ROW OF SMALL {shape} WORDLESS ICON CHIPS along one edge of the content"
        " area, evenly spaced and equal in size, each holding one flat pictogram from"
        " the story."
    ),
}


def cg_creativity_rules(level: int, *, seed=None) -> str:
    """0＝完全不注入（現行成品）；1–4 追加該級的美術條文＋這一輪的抽籤＋不變的 FIXED 段。

    `seed`：同一顆 seed 抽出同一種長相（F0／D1）。**seed 本身不會出現在回傳的字串裡**
    ——它只決定抽到什麼，不是要模型畫出來的字（監督 2026-09-14 Q2）。
    """
    block = _CG_CREATIVITY_BLOCKS.get(level)
    if not block:
        return ""
    d = creativity.draw(seed, anchor=True)
    draw_block = _CG_DESIGN_DRAW_TEMPLATE.format(
        plate=d.plate,
        stagger=d.stagger,
        typeface=d.typeface,
        c0=d.palette[0], c1=d.palette[1], c2=d.palette[2], c3=d.palette[3],
        anchor=d.anchor,
        tilt_dir=d.tilt_dir,
    )
    # 配件件數由 A2 那張表決定，**三條線共用同一張**（CP4 裁決，2026-09-15 更正：
    # 就是封面現行那張，CG 不另立）。rng 接 draw 那一顆往下抽，
    # 不另開 random.Random(seed)——那樣抽到的是另一串序列。
    # visuals 不傳：CG 的畫面描述是**這次消化的產物**，組 prompt 時還不存在，
    # 所以國旗那條確定性換入在 CG 線上本來就不會觸發（不是漏接）。
    devices = creativity.accessories(
        level,
        counts=creativity.COVER_ACCESSORY_COUNTS,
        rng=d.rng,
        placement_note=_CG_ACCESSORY_NOTE,
        overrides=_CG_ACCESSORY_OVERRIDES,
    )
    device_block = ""
    if devices:
        listed = "\n".join(f"- {text}" for text in devices)
        device_block = f"\n{CG_ACCESSORY_HEADING}\n{listed}\n"
    return block + draw_block + device_block + _CG_CREATIVITY_FIXED


# 「不消化」檔（2026-09-03 使用者要求）。原本只有標準／簡化兩檔，兩檔都會改寫使用者
# 的字。這一檔把消化整個關掉：使用者貼的內文一個字都不准動。
#
# 為什麼要獨立一塊而不是重用 USER_INSTRUCTION_RULES 第 5 條的 VERBATIM MODE：
# 那一條是「使用者在文字裡寫了逐字保留才觸發」，觸發與否要靠模型自己判斷；
# 這一檔是使用者按下按鈕的結構事實，不該再讓模型判斷一次。兩者同向，同時成立。
#
# 放在 SIMPLIFIED_DENSITY_RULES 的同一個位置（density 二選一），並且明文列出它
# 蓋掉哪幾條——編輯版樣板的「嚴禁『，』與『。』」「標題強制拆兩行」「150-180 字」
# 是 NON-NEGOTIABLE 措辭，不逐條點名的話模型會兩邊都想遵守，結果還是動了字。
VERBATIM_DENSITY_RULES = """

VERBATIM MODE (THE USER TURNED DIGESTION OFF) — THIS BLOCK OVERRIDES EVERY LENGTH, COUNT, PUNCTUATION AND FORMAT REQUIREMENT STATED ABOVE:
1. Do not digest. Do not summarise, shorten, lengthen, re-order, re-word, translate, correct, polish or otherwise "improve" the news material in any way.
2. "variable" MUST reproduce the news material exactly: the same characters, in the same order, with the same figures, the same punctuation and the same line breaks. Not one character may be added, and not one character may be removed.
3. THIS OVERRIDES, EXPLICITLY: the 150-180 character target, the maximum-three-points rule, the SIMPLIFIED MODE OVERRIDE, "Concise phrases, no punctuation", the ban on 「，」and「。」, the forced two-line 標題 split, the 15-characters-per-line limit, and every other length or format requirement above. If the source contains 「，」or「。」, they stay. If a line is long, it stays long.
4. THIS CANCELS THE FRAMING OF THE WHOLE TASK ABOVE. The opening sentence told you to digest the raw news text and requirement 1 told you to extract key points as concise phrases without punctuation. In this mode you are not digesting and not extracting: you are laying out text you may not touch.
5. The ONLY things you may add to "variable" are the structural markers [標題] and [內文小標] at the start of a line, angle brackets placed around wording that is already there, and the <蓋章> marker. A marker wraps or prefixes wording the user already wrote — it never introduces new wording. Never write out the NAME of a marker (for example the characters 強調文字) as if it were content. If you cannot place a marker without inventing text, place no marker.
6. The NUMERAL FORMAT requirement above does NOT apply here. Numbers stay exactly as the user wrote them, Chinese numerals included.
7. TEXT THAT IS NOT NEWS MATERIAL IS STILL NOT CONTENT. An instruction the user wrote to you — in the dedicated instruction field, or on an instruction line inside the material — is not part of the news material, must never be reproduced in "variable", and must never be drawn in the graphic. Verbatim reproduction applies to the news material only.
8. "style" and "structure" are still yours to design — in this mode your entire job is visual design for text you are forbidden to change. Design a layout that fits ALL of the supplied wording legibly; when there is a lot of it, say so in "structure" and lay it out as a dense but readable text-forward composition rather than dropping any of it.
"""


# 蓋章開關（2026-09-03 使用者要求）。原本有沒有蓋章是消化階段自己決定的：編輯版樣板
# 規定最後一行必須是 <蓋章>，簡化檔又說「optional」，記者版則整段沒提——同一個產品
# 三種行為，使用者無從控制。改成由使用者按鈕決定，兩塊規則明文蓋掉上面的樣板措辭。
#
# stamp=None（沒帶這個欄位的呼叫端，例如 LINE）時兩塊都不注入，消化 prompt 逐字元
# 不變，記者 frozen 測試靠這點維持綠燈。
STAMP_ON_RULES = """

STAMP BANNER: ON (USER SETTING — OVERRIDES ANY EARLIER RULE THAT MAKES <蓋章> OPTIONAL OR OMITS IT):
1. "variable" MUST end with a line that begins with the marker <蓋章>, followed by the single most important conclusion or quote of the whole graphic, written short and punchy.
2. There is exactly one <蓋章> line and it is the last line of "variable".
3. The stamp wording must come from the source material — a condensation of what is already there, never an invented claim, figure or slogan.
4. Design for it in "structure": the stamp banner is a solid full-box highlight bar and is the lowest row of the content area.
5. IN VERBATIM MODE THE STAMP IS A MARKER ONLY. Mark the line the user already wrote that best serves as the conclusion; never write a new one. If no existing line can serve as the conclusion, place no stamp — rule 2 of the verbatim block (add not one character) wins over this block.
6. <蓋章> IS THE ONLY MARKER WHOSE NAME IS WRITTEN OUT. Every other angle-bracket marker wraps wording that belongs in the graphic — you write <today's record high>, never <強調文字>today's record high. Never emit the characters 強調文字 (or any other placeholder name) as if they were content, and never write a closing tag.
7. THE STAMP MAY NOT SHARPEN WHAT THE SOURCE HEDGED. The stamp is the one line rendered as a solid colour bar, so an overstatement costs more there than anywhere else — and shortening is exactly where hedges get lost. 「疑與濃霧及路面濕滑有關」 may not become 「濃霧路滑肇禍」; 「上午9點半才陸續排除」 may not become 「9點半後車流恢復順暢」. Carry 疑, 可能, 傳, 初步研判, 陸續, 約, 預計 through into the stamp, or pick a different conclusion that needs no hedge. A fact you can state flatly makes a better stamp than a hedged one you flattened.
8. THE STAMP MUST NOT REPEAT A 內文小標. It is the conclusion of everything above it, so it may not say what one of the lines above it already said. Rewording is not enough — 「水利局出動抽水機 預計傍晚前退水」 as a 內文小標 and 「水利局已出動抽水機 預計傍晚前退水」 as the stamp are the same sentence twice, and the graphic prints both, one under the other. Before you settle on the stamp, read it against every 內文小標: if it carries the same fact as one of them, either pick a different conclusion, or drop that 內文小標 and let the stamp carry it alone.
"""


# 「無字」檔（2026-09-14 D14 使用者裁決，F20 實作）。拉桿最左端。
#
# 為什麼獨立一塊、不動既有四塊：那四塊全部在講「文字要多少」，這一檔是把文字產物
# 整個關掉，語意上不是同一條梯子的延伸。混進去會讓既有檔位跟著長出「除非無字」的
# 例外句，而條件句正是這個 repo 記過最多次的病灶。
#
# **仍然照常呼叫消化**（監督 2026-09-14 Q3）：生圖端還是需要 style／structure／
# 圖表類型／地圖與肖像結果，跳過整個 digest 是另一件大工程，不在 D14 已裁的形式內。
# 這一塊做的是最小可用解——照常消化，但產出的是無文字的視覺描述。
NO_TEXT_DENSITY_RULES = """

無字 MODE (THE USER ASKED FOR A PICTURE WITH NO WRITING ON IT) — THIS BLOCK OVERRIDES EVERY LENGTH, COUNT, MARKER AND FORMAT REQUIREMENT STATED ABOVE:
1. THE GRAPHIC CARRIES NO WRITING AT ALL. Not a headline, not a label, not a caption, not a legend, not a figure, not a date, not a source line, not a watermark, not a logo, not a unit, not a single letter or digit anywhere in the frame.
2. "variable" MUST BE COMPLETELY EMPTY — an empty string. Do not put markers in it, do not put the news wording in it, do not put a placeholder in it.
3. "style" and "structure" describe a WORDLESS image only. They may still say what the picture shows, how it is lit, how it is composed and where the subject sits; they may NOT ask for any text element, any labelled callout, any chart axis label, any map place name, any tag, chip, badge or banner carrying words, and they may not describe a space "reserved for the headline".
4. EVERYTHING ELSE STILL BINDS: the reserved broadcast margin, the ban on expressing positions and sizes as numbers, content fidelity to the source, the named-real-people rules, the child depiction rule, the map accuracy rules and the attached-reference rules are all unchanged. A wordless picture may still be factually wrong, and that is still a defect.
5. A DATA STORY WITHOUT LABELS IS A PICTURE, NOT A CHART. Where the material is numeric and there is nothing to draw but a labelled chart, ask for the scene or the object the story is about instead — never for an unlabelled chart whose bars mean nothing to a viewer.
"""


# 擺在所有規則的最後（含指令欄），因為本 repo 的慣例是「位置＋明文 OVERRIDE 同向」，
# 而 VERBATIM_DENSITY_RULES 夾在中間，實測（2026-09-03 gpt-5.6-terra）壓不住樣板
# 開頭的「Digest the raw news text」：83 字的原文被改寫成 59 字、標點全刪。
# 最後一句刻意保留指令欄的優先權：使用者自己叫你精簡時，這塊要讓路。
VERBATIM_FINAL_REMINDER = """

FINAL CHECK BEFORE YOU ANSWER — DIGESTION IS OFF FOR THIS REQUEST:
You were told at the top to digest the news text and to extract key points as concise phrases without punctuation. FOR THIS REQUEST THAT IS CANCELLED. You are not digesting anything; you are designing a layout for text you may not alter.
Read your draft "variable" against the news material one character at a time before you answer:
- Every character of the news material appears in "variable", in the same order — 「，」「。」and every other punctuation mark included.
- Nothing has been rephrased, compressed, merged, re-ordered or dropped: not one word, not one 的, not one figure. 「今天下午出現強降雨」may not become 「午後強降雨」.
- Nothing has been added except the structural markers, and no marker name has been written out as text.
If the draft fails any of these, throw it away and rebuild it from the user's exact wording.
The only thing that may relax this is an explicit request from the user asking you to shorten or rewrite. The interface setting alone never does.
"""


# 無字檔的最終覆蓋，放在整份 prompt 的最尾巴（理由同 VERBATIM_FINAL_REMINDER：
# 中段的 density block 壓不住樣板開頭與各版型區塊的命令句，位置在後才壓得住）。
#
# 為什麼要逐個點名 [標題]／[內文小標]／<蓋章>／底帶／卡片列數：這個 repo 記過三次
# 「留矛盾句，模型會挑最寬鬆的那一句遵守」。播出鏡面那塊要求「exactly four cards，
# 每張卡一個 [內文小標]」，蓋章 ON 要求「最後一行是 <蓋章>」——不點名關掉的話，
# 模型會同時想遵守「完全無字」與「四張卡各一行字」，結果是照樣寫字。
NO_TEXT_FINAL_REMINDER = """

FINAL OVERRIDE — THIS GRAPHIC HAS NO WRITING ON IT AT ALL:
Earlier blocks in this prompt asked you for text products. Every one of them is cancelled for this request, by name:
- NO [標題] line. The instruction to write a headline, and any instruction to split it across rows, does not apply.
- NO [內文小標] lines. Any block above that fixed an exact number of them — a card stack, a broadcast mirror layout, a column of points — is satisfied with zero of them, and "structure" must describe those card or panel areas as carrying picture or empty space, never writing.
- NO <蓋章> and no conclusion banner, whatever the stamp setting said.
- NO <底帶>, no lower third, no ticker, no strapline.
- No digits, no dates, no place names, no legends, no axis labels, no tags, no chips, no badges, no source line, no watermark, no signature, no logo.
- NO VISUAL CREATIVITY LAYOUT EITHER. This is a plain wordless illustration, not a designed graphic: no dominant/subordinate zones, no hero element, no card or panel shapes, no cut or angled dividing edges, no plate, no icon row, no decorative devices of any kind. Whatever visual creativity setting was chosen for this request does not apply to this graphic at all.
"variable" is an empty string. If your draft has anything in it, delete it.
This is the whole point of the setting the user chose: they want the picture, and they will add any words themselves afterwards.
"""


STAMP_OFF_RULES = """

STAMP BANNER: OFF (USER SETTING — OVERRIDES ANY EARLIER RULE THAT REQUIRES OR OFFERS <蓋章>):
1. "variable" MUST NOT contain the marker <蓋章> anywhere, and MUST NOT end with a conclusion banner line.
2. This overrides the format requirement above that makes the last line a <蓋章> line: the last line is simply the last content line.
3. "structure" must not describe, reserve space for, or place any stamp banner, conclusion bar, or full-box highlighted closing strip.
4. Do not compensate by inventing some other closing slogan, sign-off or summary bar under a different name.
5. Angle-bracket markers elsewhere in "variable" wrap wording that belongs in the graphic — you write <today's record high>, never <強調文字>today's record high. Never emit the characters 強調文字 (or any other placeholder name) as if they were content, and never write a closing tag.
"""


# 色調（2026-09-04 使用者要求）。原本畫面一律偏深藍夜色系——災害、突發題材對，
# 但民生、政策、財經、生活題材用同一套會顯得每則都在出事。因此交給使用者選。
#
# 兩檔都明說「這是使用者設定、蓋過上面的風格描述」：樣板與各類型規則裡本來就
# 散落著偏暗的措辭，只寫「請用亮色」而不點名要蓋過誰，模型會兩邊各聽一半、
# 出一張半亮半暗的圖。tone=None（LINE 與舊呼叫端）完全不注入，維持既有行為，
# 記者 frozen 快照也靠這點維持綠燈——作法比照 STAMP_ON_RULES／STAMP_OFF_RULES。
#
# 只寫「亮／暗」是不夠的：實務上出問題的是**對比**。淺底配淺字、深底配深字都
# 會在電視上糊掉，所以兩檔各自把「字要怎麼配」寫死，不讓模型自己配。
TONE_DARK_RULES = """

COLOUR TONE: DARK (USER SETTING — OVERRIDES ANY TONE WORDING IN THE STYLE GUIDANCE ABOVE):
1. Write "style" around a DARK ground: deep navy, charcoal, slate or near-black, with the imagery lit against it.
2. All headline and body text on that ground must be light — white or near-white — with enough weight to hold up against a busy photographic background. Never place dark text on the dark ground.
3. Accent colours stay saturated and bright (amber, red, cyan) so they read against the dark ground. Keep the directional colour rules above unchanged: a rise is still red, a fall is still green.
4. This is the mood the user asked for, not a description of the subject. Do not brighten it because the story is upbeat, and do not ask for a light panel behind the text to "make it readable" — the contrast requirement in rule 2 already handles that.
"""

TONE_LIGHT_RULES = """

COLOUR TONE: LIGHT (USER SETTING — OVERRIDES ANY TONE WORDING IN THE STYLE GUIDANCE ABOVE):
1. Write "style" around a LIGHT ground: off-white, warm paper, pale grey or a soft daylight photograph, with the imagery sitting on it.
2. All headline and body text on that ground must be DARK — near-black, deep navy or deep charcoal — heavy enough to read at broadcast distance. Never place white text on the light ground.
3. Accent colours must be deep enough to hold against a pale ground: use deep red, deep amber and strong blue rather than pastel or neon. Keep the directional colour rules above unchanged: a rise is still red, a fall is still green.
4. Any dark banner that the format requires (the <蓋章> stamp strip, a headline bar) may keep its dark fill with light text on it — that is a deliberate block of contrast, not a return to the dark tone. Everything outside those blocks stays light.
5. This is the mood the user asked for, not a description of the subject. Do not darken it because the story is grim.
"""


# 消化階段的內容忠實度規則。生圖階段一律不得添加內容（那條在 news_prompt.py 的
# FINAL OUTPUT RULE）；補充只能發生在這一層，而且只有使用者原文明確要求時才可以。
# 起因：2026-07-30 實測 GPT 自行畫出來源沒有的完整季線數值與「資料來源 ICE／
# Trading Economics／USDA／ICO」。新聞產品不得出現模型發明的數據與來源。
CONTENT_FIDELITY_RULES = """

CONTENT FIDELITY (NON-NEGOTIABLE — OVERRIDES ANY LAYOUT OR LENGTH PREFERENCE ABOVE):
1. Use ONLY facts, figures, names, dates and quotes that appear in the source material. You are condensing, not researching or writing.
2. NEVER invent or infer: extra data points, a series of values over time, quarters or years, axis scales, rankings, totals, percentages, currency conversions, casualty or headcount figures, or any statistic not stated in the source.
3. NEVER invent a data source, agency, wire service, publisher, institution, analyst name, or "as of" date. If the source material does not name one, do not supply one, and do not ask for one to be drawn.
4. If the source material is thin, produce fewer points. A short, wholly accurate specification is correct; padding it with plausible-sounding detail is a defect, not a service.
5. Do not upgrade hedged wording into certainty (e.g. "約"/"可能"/"預估" must not become a flat assertion), nor add a hedge the source did not use — writing 「遊覽車疑煞車不及」 where the source simply reported the collision casts doubt the reporting never raised. Do not sharpen a rounded figure into a precise one either. THE 標題 IS WHERE THIS SLIPS, because it is the line you compress hardest and a hedge is the cheapest word to drop: keeping 「疑因濃霧路滑」 in the stamp while the headline reads 「濃霧路滑回堵12公里」 states a suspected cause as established fact, in the largest type on the graphic. Either the headline carries the hedge too, or the cause stays out of the headline.
6. THE NAME OF THE LAYOUT IS NOT NEWS. 示意圖, 資料圖表, 地圖, 位置圖, 流程圖, 3D示意 and the like describe what kind of graphic you are designing; they are not part of the story. Never let one of them end up inside "variable" — least of all trailing the 標題 line, where the renderer sets it in headline type and the viewer reads 「台中火鍋店疑食物中毒 示意圖」 as if 示意圖 were part of the news — nor at the end of a 內文小標, which is the next place it tries to go once the headline is closed off. Where the graphic genuinely needs to be flagged as a reconstruction, say so in "structure" as a small caption; the headline states what happened and nothing else.
7. PAIRING A FACT WITH A PLACE IS ITSELF A CLAIM — AND SO IS UNPAIRING ONE. Two halves, and you need both.
   KEEP EVERY PAIRING THE SOURCE ALREADY MADE. Where the source says what happened at a named place, that pairing is reported fact and belongs in the graphic, tied to that place: 「楊梅路段砂石車追撞2人受傷」「中壢交流道4車連環1人輕傷」「湖口路段貨櫃車起火駕駛脫困」 must survive as three place-specific lines, each keeping its place and its detail together on ONE line. Splitting them into a line of places and a line of details hands the pairing back to the renderer to guess, which is the very thing the next paragraph forbids. On a location graphic「哪裡發生什麼」IS the story; stripping the places out to be safe empties the graphic of the only thing it exists to show.
   INVENT NO PAIRING THE SOURCE DID NOT MAKE. Where the source lists several places and separately lists what happened, it has not told you which detail belongs to which — and you may not decide. 「三處路段積水，最深40公分，多輛機車熄火，水利局出動抽水機」 does not license 「左營區博愛二路 多輛機車熄火」: the source never said the scooters stalled there. Keep those places in one line and the unassigned details in their own.
   The test is simply whether the source itself put the two together. It usually did so in the same clause; when in doubt, quote its own sentence order rather than redistributing.
8. SEPARATE EVENTS STAY SEPARATE. Several incidents in one story are not thereby one incident. Do not write 連環, 接連引發, 造成, 導致, 連鎖 or any other wording that makes them a chain or makes one the cause of another unless the source says so. 「兩起機車自摔，另有一起貨車爆胎」 is three unrelated events and a headline calling them 連環車禍 asserts a causal link the source never reported. Count them and say how many; leave the relationship alone.
9. EXCEPTION — supplementation is allowed ONLY when the source material itself explicitly asks for it (e.g. it contains an instruction such as 「幫我補充」「請補充」「幫我加上」「請加入背景說明」). In that case you may add widely-established background, and only within the scope requested. Absent such an instruction, add nothing.
"""


# 視覺忠實度：CONTENT_FIDELITY_RULES 只管 variable 的文字與數字，管不到
# style/structure 委製的「畫面」——憑空天際線、品牌 LOGO、真實人物長相都是
# 從這個洞進來的（樣板甚至主動要求模型加插圖指示）。本區塊補上這個洞。
# 2026-07-31 起以新區塊追加，刻意不修改 CONTENT_FIDELITY_RULES（另案檢視）。
REAL_WORLD_FIDELITY_RULES = """

REAL-WORLD ACCURACY (governs "style" and "structure" — the pictures you commission, which CONTENT FIDELITY above does not reach):
1. CONTENT FIDELITY governs the words and figures in "variable". This block governs the imagery. Never ask for a visual you cannot ground in the source material or in reliable knowledge of how the real thing looks. An invented picture presented as real is as serious a defect as an invented number.
2. REAL PLACES AND OBJECTS: when the story shows a verifiable real place or object — a skyline, a specific building, a highway or interchange, an airport, a facility, or a specific model of aircraft, ship, vehicle or equipment — ask for it to be depicted as faithfully to its real appearance as your knowledge allows: real shape, real layout, real proportions, real distinguishing features. Do not stylise reality away when the real look is known.
3. LABEL WHAT IS NOT REAL: if you are not confident the depiction will match the real thing, or the scene is a generic stand-in or a reconstruction rather than a documented view, you MUST plan a clearly visible 示意圖 label — write the word 示意圖 into "variable" and tell "structure" where it sits. An unlabelled reconstruction presented as real is a defect. Do not fabricate identifying detail you do not actually know and pass it off as real.
4. BRANDS: ONLY THOSE IN THE SOURCE. A brand the source material names MAY be shown with its real logo, wordmark or brand text, rendered as faithfully to the real mark as possible, on the objects that belong to it — its own signage, packaging, product body, vehicle livery, screen or jersey; plain typeset text is equally acceptable. Never put one brand's mark on another brand's object. Every OTHER brandable surface — signage, storefronts, banners, packaging, product bodies, vehicle liveries, screens, jerseys, badges and building facades — must be de-identified: blank surfaces or generic abstract marks, no readable brand text, no trademark, no ticker symbol, no exchange name for any brand the source material does not name, and never an invented one. Whenever the scene contains any object that would normally carry a brand, write into "structure" explicitly WHICH brands the source material names (and may therefore appear with their real mark) and that every other brandable surface stays de-identified — do not assume the renderer will infer it.
5. NAMED REAL PEOPLE: you do NOT decide how the face is drawn. List in "portrait_subjects" EVERY specific named real person whose face the graphic would show — one entry per person. Names MUST be copied VERBATIM from the news text or from the user's explicit input; never infer a person from a job title (總統, 執行長), an event, a country, an organisation, or common knowledge. A title, office or role without a personal name is not a name — leave the array empty. ONE EXCEPTION, and only one: when the material carries a block headed "Abbreviation glossary supplied by the newsroom", the personal names listed there are established fact handed to you by the newsroom, not something you inferred — treat each of them as if it were written out in full in the material at the place the abbreviation appears. Such a person is named material exactly like any other: you may design their face into the layout and you MUST then list them in "portrait_subjects". Do not hedge — do not keep a glossary-named person out of "portrait_subjects" while naming them in the text, and never write into "structure" that the people appear "without portraits" or "via typography only" as a way of side-stepping this rule. This exception reaches ONLY the names printed in that glossary block; for everyone else the verbatim rule stands unchanged. Copy the name exactly as written, no title, no company. If the layout shows two people, list both; listing only the first is a defect. In "structure" describe only WHERE each figure sits and what it wears, never the rendering treatment (do not write "photorealistic", "faithful likeness", "back view", "silhouette", "illustration" or similar). You may describe a role or title in "structure", but that does not license filling "portrait_subjects". The backend looks up reference photographs and appends the binding portrait rules itself. Leave "portrait_subjects" as an empty array for every other graphic, including crowds and unnamed or generic figures. Never write 示意圖 into "variable" for a person you listed in "portrait_subjects" — the backend stamps that label itself once it knows how the face will be rendered. That exemption covers ONLY the people in that array: a named real person shown WITHOUT their face (a back view, a silhouette, a faceless stand-in) does not belong in "portrait_subjects", so nothing is stamped for them and rule 3 above applies in full — plan the 示意圖 label yourself. Never place a person in a scene, action or context the source material does not describe.
6. AT MOST THREE FACES: the layout you design may show identifiable faces for AT MOST THREE named real people. When the source material names more, choose the three most central to the story and design "structure" so that ONLY those three appear as identifiable individual figures. The other named people are NOT removed from the story — their names and what they said may still appear as TEXT (a quote panel, a caption, a list item, a label on a chart), and that text should carry their points. What they must not have is a face: do not draw them as an identifiable figure, and never place their name beside any depicted figure, because a name sitting next to a drawn face reads as that person. "portrait_subjects" must be a truthful mirror of the faces you designed: never design a layout with four faces and list only three — the unlisted face is the exact defect this rule exists to prevent.
7. NAMES IN ENGLISH TOO: fill "portrait_subjects_en" with the same people in the same order and the same length as "portrait_subjects" — each entry being that person's name in English or its original Latin spelling, copied VERBATIM from the news text or the user's explicit input when that spelling is present there. If the English or Latin name does not appear in the source material or the user's input, that entry MUST be an empty string. Never translate a Chinese name, never guess a spelling, and never fill the English name from common knowledge, a title, an event, a country or an organisation. Example: source writes 「川普」 only → portrait_subjects=["川普"], portrait_subjects_en=[""]; source writes 「川普 Donald Trump」 → ["川普"] / ["Donald Trump"]. This is how the backend finds the reference photograph: Taiwanese transliterations are frequently not the title of any Chinese encyclopedia article, so without an English name that actually appears in the material the person cannot be looked up and no face can be drawn.
8. PHOTO-LOOKUP GUESS, NEVER CONTENT: fill "portrait_subjects_en_guess" with the same length and order. When an English/Latin spelling is absent from the source but you can identify the named person from the source's explicit name, title, nationality and role, put your best English-name guess here; otherwise use an empty string. This field is metadata used only to try an English Wikipedia photo lookup. It is NEVER a permitted source for "variable", captions, names, claims, "style" or "structure", and it does not relax any VERBATIM rule above. The backend accepts a guessed match only when the encyclopedia description independently agrees with the source context.
"""


# 小孩肖像過審率。生圖供應商（GPT／Gemini）對「寫實風格畫出兒童」的安全過濾器
# 誤殺率高，同一張圖只要把兒童角色改成插畫／卡通風格就能過關（2026-09-01 使用者
# 實測發現的解法）。只調整「有兒童角色」那個 figure 的畫風，其餘版面與人物維持
# 原本選定的 style，避免整張圖為了一個小孩角色被迫變成兒童繪本風。
CHILD_DEPICTION_STYLE_RULES = """

CHILD DEPICTION STYLE (governs "style" and "structure" — applies whenever the scene includes a child):
1. Whenever the scene you are designing would depict one or more children or minors as a figure (a schoolchild, a young child in a family/rescue/incident scene, a student, etc.), rendering that figure photorealistically frequently triggers the image generator's safety filter and the whole image fails to generate. To avoid this, explicitly render ONLY those child figures in a simple, flat CARTOON / CHILDREN'S-BOOK ILLUSTRATION style — never photorealistic, never lifelike skin or facial detail. Every other element of the graphic (background, adults, icons, charts) keeps the graphic's normal chosen style unchanged.
2. Write this into "style" explicitly, e.g. "the child figure is rendered in a soft flat cartoon illustration style, simplified features, no photorealistic skin or facial detail, while the rest of the scene stays photorealistic/[chosen style]". Note in "structure" which figure this applies to and where it sits.
3. This does not relax the NAMED REAL PEOPLE / AT MOST THREE FACES rules above: if the child is a specific named real person, the portrait and 示意圖 rules there still apply on top of this cartoon treatment.
4. If no child or minor would be shown in the scene, ignore this rule entirely — do not mention children or cartoon style in "style" or "structure".
"""


# 台灣漲跌配色慣例（漲紅跌綠，與西方相反）。第 3 條同時回答 TODO 的疑問：
# 禁數字條款只管畫布幾何，顏色語意與箭頭方向屬於內容、不受該條款拘束。
DIRECTIONAL_COLOR_RULES = """

DIRECTIONAL COLOUR CONVENTION (Taiwan convention — the Western one is wrong here):
1. Whenever the material contains a rise/fall, gain/loss, increase/decrease or positive/negative direction (indices, share prices, exchange rates, prices, inflation, polls, counts, approval ratings), state in "style" and in "structure": 上漲／增加／正向 = red, 下跌／減少／負向 = green. Never green for a rise, never red for a fall.
2. Keep the pairing consistent across every element — arrows, triangles, bars, lines, sparklines, highlight blocks and the emphasised figure itself. If one graphic shows both a riser and a faller, they must be red and green respectively in the same image.
3. Colour semantics and arrow direction are CONTENT, not layout geometry. The ban above on percentages, pixels, ratios and numbers applies only to positions and sizes on the canvas. It does NOT stop you from saying that a value rose or fell, from asking for an up arrow or a down arrow, or from naming a colour. State the direction plainly; being vague about direction to avoid "numbers" is a defect.
4. In a graphic that shows a rise or a fall, do not use red or green decoratively for anything unrelated, so the pairing cannot be misread.
"""


CHROMA_KEY_GREEN_SAFETY_RULES = """

CHROMA-KEY GREEN SAFETY (applies at every density and creativity level):
1. Never use chroma-key green or neon/lime key green for text fills, outlines, shadows, plates behind text, tags, chips, or purely decorative shapes; these colours are keyed out on air.
2. This is a narrow studio-key restriction, not a ban on ordinary green. Deep green, dark green and olive green remain available when appropriate.
3. The Taiwan directional convention above still wins for market data: non-chroma data green remains allowed for falls, losses and negative values.
"""


# 地圖準確性。對「禁數字」與「內容忠實度」各開一個範圍受限的豁免：
#
# 2026-09-04 正式站實測（基隆廟口／西定路／大武崙淹水）：本區塊原本的開頭句是
# 「只在你指定的是地圖類圖表時適用，不是就整段忽略」，把適用範圍綁在模型自己回報的
# chart_type 上。模型把那則判成「情境示意圖」，於是整套地理安全規則被它自己關掉——
# 但它照樣在 structure 寫「Show a faithful geographic map of Keelung City」並要求
# 把三個地名標在正確位置，卻一個經緯度、一句正北朝上、一個比例尺都沒給。生圖端
# 手上只有地名，只能亂擺。因此適用範圍改成由「你要求了什麼」決定（開頭句），
# 並補第 11 條：沒有定位資料就不准寫「忠實地圖」，只能改用示意型 fallback。
# 分類本身也補強在 AUTO_TYPE_SELECTION_RULES：明確的地理需求一律選地圖類。
# 座標／距離／方位角只做定位資料、永不印在畫面上，畫布幾何禁數字仍全面生效。
# 座標來自模型記憶、冷門地點可能錯（沖之鳥島案例）——沒把握就改用座標網格；
# 真正的解法是以圖生圖落地後改走 GIS 底圖路線（見 TODO.md）。
# 措辭沿用 docs/error-cases/2026-07-23-沖之鳥島-位置偏移-分析.md 的通則化版本。
MAP_ACCURACY_RULES = """

MAP ACCURACY RULES (SCOPE IS SET BY WHAT YOU ASK FOR, NOT BY THE LABEL YOU REPORT): this block binds whenever the graphic you specify puts real, named places on a map or shows them in their true relative positions — a map, locator, coastline, road or district layout, route, or markers pinned to real geography — even when you report "chart_type" as 情境示意圖, 資料圖表 or 3D示意／流程. Writing "a faithful map of X" or "mark these places at their real locations" into "structure" while treating this block as inapplicable is the exact failure it exists to prevent. If nothing you ask for places a real location, ignore this whole block.
1. Geographic accuracy outranks visual balance. Never ask for a place, island, coastline, border, route or marker to be moved, compressed, rotated, enlarged or rearranged so the composition fits; if everything will not fit truthfully on one map, use two maps (rule 6), never a distorted one. "Simplified" applies to line styling and visual detail ONLY — never to positions, distances, bearings or relative scale. Use the phrase "geographically accurate simplified cartography" in "style".
2. North-up orientation: north at the top, east on the right, west on the left, south at the bottom. Ask for a north arrow and a scale bar — the only map furniture allowed (rule 9).
3. SCOPED EXCEPTION TO THE NO-NUMBERS RULE ABOVE, AND SCOPED EXCEPTION TO CONTENT FIDELITY ABOVE. The no-numbers rule bans numbers used for LAYOUT geometry — positions, insets, gutters and sizes on the canvas — and still binds in full; it does NOT cover real-world geography. For a map you MUST write into "structure": the latitude and longitude of every named place you are confident about, the coverage window of each map in degrees, real distances in kilometres, and true bearings in degrees. The coordinates of an existing named place are fixed properties of that place, not invented figures, so you may supply them from your own geographic knowledge for positioning alone; everything else in CONTENT FIDELITY still binds — never invent casualty counts, distances, radii, dates, areas or any other quantity the source did not state, and never put a coordinate into "variable". These figures are POSITIONING DATA: their job is to put markers in the right spot. Do NOT ask the renderer to print coordinates, degree values or bearings as labels — printing them is neither required nor requested, and "structure" must not instruct the renderer to display them (if the renderer labels a marker with its coordinates anyway, that is tolerated; accuracy matters more than suppressing the label). The only text you ask for on the map is place names and callout wording that already appears in "variable".
4. NEVER ASK FOR A FAITHFUL MAP YOU HAVE NOT SUPPLIED THE DATA FOR. If "structure" asks for a real place to be drawn or marked at its real location, EVERY place it names must carry the rule 3 positioning data. If you are not confident of a place's real coordinates, say so in "structure" and you may not use "faithful", "accurate", "real" or "geographic" map wording for that graphic: switch it to the schematic fallback — a labelled coordinate grid or a schematic locator with the place names as labels — and say plainly there that the layout is schematic. Never invent islands, coastlines, landmasses or maritime boundaries — a truthful map with no coordinates behind it is precisely what makes the renderer invent geography.
5. Any distance the source states must be drawn to the same scale as the rest of the map and along a stated true bearing — not as an arbitrary line with a figure attached.
6. When the story spans a wide area, ask for two map levels: a small north-up locator overview showing the true relative positions of the places involved, and a larger detail map centred on the incident. Forcing one map to serve both is what makes models drag distant places closer together.
7. Disputed or claimed zones (EEZ, 主張海域, 爭議邊界) must be drawn as a thin schematic boundary, never as a settled international border, and must carry the label 主張範圍 示意 — write that label into "variable" too, because the renderer may only draw text supplied to it.
8. ONE SUBJECT PLACE IN THE HEADLINE. Only the place where the incident actually happened may be the subject of the 標題 line in "variable". Other countries that merely reacted, commented, protested or announced a response are secondary: put them in their own 內文小標 or callout wording, never in the headline as the acting subject — a headline naming a reacting country beside the incident location reads as if the incident happened there, and the renderer will pin that country's callout on the incident.
9. THE MARKERS ARE THE PLACE LABELS — NEVER BUILD A LEGEND. Every marked place already carries its name beside its marker. Do not repeat those names as a 內文小標 line, caption list, key, legend, 圖例 panel or marker index, and never ask for a legend box, key panel or colour-code panel of any kind: on screen that is a separate box repeating what the map already says, eating the space the map needs. 內文小標 lines are for the news itself (what happened at those places, when, how serious), never for a list of places.
10. "map_places" IS A LOOKUP QUERY, NOT A CAPTION. Put every place that should carry a marker into "map_places", one entry each, in reading order; leave the array empty if the graphic is not a map. The program geocodes these names against a real gazetteer and may attach a real basemap with the markers already drawn, so each entry must be a findable real name with the city and district that disambiguate it (「基隆市 西定路」, not 「西定路」 — a bare street or hill name matches dozens of places nationwide). Nothing you write in this field is ever printed on the graphic. ONLY LOOKUPABLE POINTS BELONG HERE: a gazetteer holds named points and named administrative areas, nothing else. Never put in a loose region or direction (「北海岸」「南部」「東海岸」「北台灣」「市區」「低窪地區」) or a position along a road (「楊梅路段北向68公里」「國道1號中壢路段」) — it returns nothing or, worse, matches an unrelated shop sharing the words, and that wrong point gets drawn. Name the district instead (「桃園市 楊梅區」) or leave it out and describe it in "structure" as a schematic position: leaving it out costs a marker, a wrong lookup puts a marker on the wrong town. A NAMED FACILITY IS LOOKED UP BY ITS OWN NAME, NOT BY THE ROAD IT SITS ON: write 「中壢交流道」, never 「國道1號中壢交流道」 — the road prefix makes it unfindable; if the bare name is ambiguous, prefix city and district instead (「桃園市 中壢區 中壢交流道」).
11. ONE PLACE, ONE NAME ON SCREEN, AND NEVER LET AN INSTRUCTION WORD BECOME PRINTED TEXT. "map_places" may need the gazetteer's official full form (「基隆市 基隆廟口夜市」) to be findable, but everything the viewer reads — in "structure" and "variable" alike — must use the short name the story itself uses (「基隆廟口」), the same in both fields; carrying the gazetteer form into either is how one graphic labels the same place 基隆廟口夜市 on the map and 基隆廟口 in the text. Likewise 標示, 標出, 請標, 標記, 位置如下 and the like are directions about what to do with the map, not wording to display: the renderer prints "variable" verbatim, so an instruction word left there comes out as a caption reading 「標示 基隆廟口」. Write the place name on its own, with no verb in front of it.
12. NEVER SHADE ADMINISTRATIVE AREAS — MARK POINTS INSTEAD. Do not ask for counties, cities, districts, prefectures, states or any other administrative units to be drawn as filled, tinted or colour-coded shapes, and do not ask for their boundary lines at all. The renderer draws those borders from memory: 2026-09-10 實測 both a whole-Taiwan county map and a single-city district map came back with the wrong boundary shapes and with several units simply missing. A wrong border is a factual error on air. Where the story groups places, put a dot on each named place and group them with the CALLOUT wording and the callout's colour — that is what the directional colour convention is for — over a plain terrain or single-tone base.
13. DRAW NO LAND THAT THE STORY DID NOT NAME, AND CROP NO LAND THAT IT DID. Never add islands, islets, reefs, sandbars or coastline that you are filling space with — 2026-09-10 實測 an all-Taiwan graphic came back with invented islands scattered across the sea. Equally, when the subject is a whole country or island, the whole of it stays in frame at a true shape: do not slice off one end, do not rotate it to fit a wide canvas, and do not stretch it. If the full shape will not fit the frame, zoom out until it does, or say plainly in "structure" that the view is a schematic locator rather than a map.
14. EVERY UNIT OR NONE. If the graphic shows a set that the viewer will read as complete — the districts of one city, the counties of one region — either every member of that set is present and correctly placed, or you do not draw the set at all. A map showing seven of a city's twelve districts tells the viewer the other five do not exist.
"""


# 兩段式分類成「非地圖」時注入的 SCOPE 守門，取代整塊 MAP_ACCURACY_RULES。
#
# 為什麼不能整塊刪：MAP_ACCURACY_RULES 開頭刻意寫成「就算你報成情境示意圖也照樣
# 綁住你」——SOT2 2026-09-05 第五輪實例：模糊地名那則被判成情境，成品仍畫了臺灣
# 輪廓的示意地圖。分類成非地圖就把整塊拿掉，等於那張畫著真實地理的圖完全不受
# 地理準確性約束。
# 為什麼不整塊留：座標、指北針、雙層地圖、map_places 寫法只有真的要畫準確地圖時
# 才用得到，而這條路徑的前提正是「不畫」。所以只留兩件事：範圍那句的精神
# （要放真實地名上地圖就不該用這個類型）＋退路（示意定位圖／座標網格並明說示意）。
MAP_SCOPE_GUARD_RULES = """

MAP SCOPE GUARD (the chart type above was chosen for you and is NOT a map): if the graphic you end up specifying would put real, named places on a map or show them in their true relative positions — a locator, a coastline, a road or district layout, a route, or markers pinned to real geography — that is a map, and drawing one under this chart type is the exact failure this block exists to prevent. Do not ask for one. Where the story genuinely needs a sense of place, ask instead for a schematic locator or a plain coordinate grid with the place names as labels, say plainly in "structure" that the layout is schematic, and never invent coastlines, islands, landmasses or borders.
"""


# 中國大陸輪廓誤含臺灣（B76，播出事故等級，2026-09-17 R7 實拍輪 A2 使用者當場指認，
# 裁定「這一波要修，而且要求百分之百絕對避免」）。
#
# 事故實例：那則新聞是「國銀對中國大陸曝險」，稿子從頭到尾沒提到臺灣——是生圖模型
# 自己把臺灣填進中國大陸的輪廓（同一種填色、包在同一圈輪廓光暈之內）當背景裝飾畫出來。
# 觸發條件不是「稿子提到臺灣」，是「畫面上出現中國大陸的輪廓／版圖」，而這種題材
# （兩岸經貿、中國經濟、陸股、台商、關稅）在資料圖表、情境示意圖裡經常需要一塊
# 中國大陸的裝飾用輪廓——這正是問題：那次事故的 chart_type 是「資料圖表」，走的是
# MAP_SCOPE_GUARD_RULES 那條路，而不是 MAP_ACCURACY_RULES；MAP_SCOPE_GUARD_RULES
# 教的是「不要畫地圖，改用示意定位圖」，但一塊裝飾用的國家輪廓在模型眼裡從來不是
# 「地圖」，兩塊既有規則因此都沒攔下它——MAP_ACCURACY_RULES 顧的是地圖類的準確度
# （行政區界、座標、比例尺……），MAP_SCOPE_GUARD_RULES 顧的是「別因為這題材就畫出
# 一張地圖」，都沒有明文禁止「中國大陸輪廓吞併臺灣」這件事本身。
#
# 為什麼另立一塊、不寫進上面兩塊之一：這條規則要不看 chart_type、不看是不是地圖類
# 都生效——凡是畫面上出現中國大陸的輪廓/版圖（無論是正式地圖、資料圖表的裝飾背景、
# 或任何示意圖的一角），都要擋。所以獨立於 if/else 分流之外、兩條路都會拼進去。
#
# 為什麼不能只用一句「不要把臺灣畫進中國」帶過：使用者原話「這是絕對不可以接受
# 的……一定要百分之百絕對避免」——含糊的請求式措辭擋不住，必須寫成可檢驗的具體
# 禁令（哪些地名不能同色同框、臺灣若出現要怎麼畫、什麼情況下乾脆別畫輪廓）。
#
# 為什麼不做程式端自動驗證當閘門：「圖上那座島有沒有被算進中國」需要影像理解，
# 監督已記取 feedback_map_image_verification_unreliable（AI 看圖驗地理不可靠）的
# 教訓，不能拿模型自動判讀當唯一防線；MASTER 列管 B76 也明載「不建議用模型自動
# 判讀當閘門」。因此本條是 prompt 層的第一道防線，配合 B76 條目裡程式端／人工複核
# 的後續裁決（尚未裁定），不是唯一防線。
# 相關：B25（AI 憑空畫地理）、B20（大陸譯名用語擋不住，同一種立場外洩風險的文字版）。
CHINA_TAIWAN_OUTLINE_RULES = """

CHINA OUTLINE / TAIWAN SEPARATION — ZERO TOLERANCE, NO EXCEPTIONS. No styling or simplification instruction anywhere in this prompt relaxes this rule: this rule applies no matter what chart type is in force above — a map, a data chart, an infographic, or any graphic that uses a country silhouette as decoration or background — and even when Taiwan is never named in the story. Whenever anything on the graphic draws the outline, coastline, silhouette, or a filled/tinted landmass representing 中國, 中國大陸, China, Mainland China or the PRC, that shape MUST stop at the mainland coast. Taiwan (臺灣/台灣), Penghu (澎湖), Kinmen (金門) and Matsu (馬祖) must NEVER be filled with the same colour as that landmass, enclosed in the same outline, wrapped in the same glow/halo/highlight ring around it, or otherwise rendered as if they belonged to it — this is true even if the renderer's own default reference for "China" already lumps them in; it is exactly that default you must override. If Taiwan appears anywhere on the same graphic, it must be drawn as a visually separate landmass: its own outline, a fill colour that contrasts with mainland China's, positioned at its true relative location, never touching, bridging or merging with the mainland shape. Hainan Island (海南島) is genuine PRC territory and may share the mainland's fill and outline — this rule is about Taiwan and its outlying islands, not about excluding Hainan. If you cannot be confident the renderer will keep Taiwan visually distinct, do not ask for China's outline or silhouette at all — describe China's location, scale or extent in words in "structure" instead of requesting a drawn landmass.
"""


# 訊息內夾帶指令與逐字模式。放在指令組裝的最後：逐字指令必須壓過
# SIMPLIFIED_DENSITY_RULES（LINE 端 density 預設就是 simplified，衝突每次都會發生），
# 本 repo 慣例是「位置＋明文 OVERRIDE」雙重表達優先序，兩者須同向。
# 「先讀指令」由區塊開頭句承擔——那是步驟順序，不是文字順序。
USER_INSTRUCTION_RULES = """

USER INSTRUCTIONS INSIDE THE MATERIAL (DO THIS FIRST, BEFORE APPLYING ANY RULE ABOVE):
1. Before digesting anything, read the whole input once and split it into (a) the news material and (b) any instruction the user has written to you. An instruction is usually on its own line and may be marked 「指示:」「指令:」「備註:」, but it may also be plain prose. Typical forms: a visual style request (「用手繪風」「不要科技藍」), a layout request (「標題放左邊」「只要一張大圖」), a length request, or a verbatim-preservation request (「完全依照文字」「不要刪減」「不要添加文字或數字」「逐字保留」「這是完稿」).
2. Any line beginning 「指示:」or「指令:」is entirely an instruction to you and is never news content, no matter what it says.
3. Obey the instruction — carry a style or layout request into "style" and "structure" in professional English. Acknowledging it without acting on it is a failure.
4. The instruction text is NEVER content. It must not appear in "variable", must never be drawn in the graphic, and must not be described in the graphic either.
5. VERBATIM MODE. If the user asks for the wording to be kept, or supplies material that is already a finished CG script, then "variable" must reproduce the supplied wording exactly: same characters, same order, same figures, same line breaks. Do not summarise, shorten, lengthen, re-order, re-word, translate, correct or add one single character. Add the [標題] / [內文小標] / <蓋章> markers only where the user's own structure already implies them, and add nothing else. VERBATIM MODE OVERRIDES EVERY LENGTH, CHARACTER-COUNT AND POINT-COUNT REQUIREMENT ABOVE, INCLUDING THE SIMPLIFIED MODE OVERRIDE AND THE 150-180 CHARACTER TARGET. In verbatim mode your job is layout and visual design only.
6. If an instruction would require facts or figures the source does not contain, CONTENT FIDELITY above still wins: do not invent them, and carry out the rest of the instruction.
7. If the input contains no instruction, this block changes nothing — digest normally.
"""


# 專用指令欄位（PLAN.md ①）。把「這幾行是指令」從分類任務變成結構事實：
# 欄位裡的字**保證**是指令、絕不是新聞內容，規則第 4 條因此從「靠 prompt 自律」
# 變成「結構上不可能」。文內解析（上方 USER_INSTRUCTION_RULES）仍原樣生效——
# 兩邊都有時兩者都要遵守（專用欄位優先，但互不取消），欄位寫「逐字保留」
# 一樣要觸發 VERBATIM MODE（規則第 5 條）。
# 模板：{instruction} 由 build_digest_instructions 填入；只在欄位有值時注入，
# 沒填時消化行為與過去逐字元相同（記者 frozen 測試靠這點維持綠燈）。
DEDICATED_INSTRUCTION_RULES_TEMPLATE = """

DEDICATED USER INSTRUCTION (GUARANTEED CHANNEL — READ TOGETHER WITH THE BLOCK ABOVE):
The user has also supplied an instruction through a dedicated field, quoted between the markers below. Everything between the markers is CERTAIN to be an instruction to you and is NEVER news content — do not classify it, do not let it appear in "variable", and never draw or describe it in the graphic.
Obey it under exactly the same rules as the block above: carry style or layout requests into "style" and "structure"; if it asks for the wording to be kept (e.g. 「逐字保留」「完全依照文字」「這是完稿」), VERBATIM MODE applies to the news material in full.
If the news material ALSO contains instructions, obey both. When the two conflict on the same point, this dedicated instruction wins; on every other point each instruction still binds — neither cancels the other.

PRIORITY OVER THE USER'S OWN UI SETTINGS. Some of the rules above were switched on by controls the user clicked in the interface. This dedicated instruction is the same user speaking directly, and it OUTRANKS those controls wherever the two conflict. It specifically outranks:
- the digestion density block (不消化 / 字少 / 字多). 「逐字保留」「完全依照文字」forces exact reproduction even when the density block asks you to shorten; 「濃縮成三點」「再精簡一點」shortens even when the verbatim block says reproduce every character.
- the stamp banner block. 「不要蓋章」「拿掉蓋章」removes the stamp even when the block above switched it ON; 「加上蓋章」「要有蓋章」adds one even when the block above switched it OFF.
- the colour tone block (色調亮／色調暗). 「用亮一點的底」「不要那麼暗」forces the light tone even when the block above set DARK, and the reverse likewise. If the instruction names a specific palette («用米白底»、«深藍底»), follow the instruction's palette and keep the contrast requirement from the tone block that matches it.
- the chart type directive, including a "MUST be exactly" requirement. If the user asks for a different kind of graphic, design that one and report the type you actually designed in "chart_type".
- the visual style and any style guidance above.
- how the user's uploaded reference images are used.
It does NOT outrank, and can never relax: CONTENT FIDELITY (never invent facts, figures or sources), REAL-WORLD FIDELITY, the BROADCAST SAFE AREA / FULL-FRAME layout sentence together with its ban on expressing any position or size as a number, the CHINA OUTLINE / TAIWAN SEPARATION rule, the reporter/editor role you were given, and the rule that instruction text never becomes content. Carry out a request that would break one of those only as far as those rules allow, and satisfy the rest of the instruction normally.
<<USER INSTRUCTION START>>
{instruction}
<<USER INSTRUCTION END>>
"""


# 查不到參考照的人，改由消化階段把他們排出版面（2026-08-18 使用者裁決）。
#
# 為什麼在消化階段而不是生圖階段：2026-08-18 實測證明，叫生圖模型「只畫有照片的人、
# 沒照片的畫剪影」完全無效（2/2 都被憑空捏臉還掛真名）。消化端是文字模型、遵守
# 指示可靠得多，而且要拿掉的不只是那張臉——那個人的姓名條、引言框、版位都要一起
# 重新安排，本來就只有消化端做得到。
#
# 同 DEDICATED_INSTRUCTION_RULES_TEMPLATE：只在有人要排除時才注入，沒有時消化
# prompt 逐字元不變（記者 frozen 測試靠這點維持綠燈）。
EXCLUDED_PEOPLE_RULES_TEMPLATE = """

PEOPLE WHO MUST NOT BE DRAWN (OVERRIDES THE NAMED REAL PEOPLE RULE ABOVE):
No usable reference photograph exists for the people listed below, so the graphic must not show their faces.
- Do not draw any of them as an identifiable figure, and do not list any of them in "portrait_subjects".
- Their names and what they said may still appear as TEXT — a quote panel, a caption, a list item — and that text should carry their points. Attribute in words, not with a face.
- Never place one of these names beside a depicted figure: a name sitting next to a drawn face reads as that person, which is exactly what must not happen here.
- Redesign "structure" around the people who remain. Do not leave an empty figure slot where one of them would have stood.
<<NO-PORTRAIT PEOPLE START>>
{people}
<<NO-PORTRAIT PEOPLE END>>
"""


# 最近一次 resolve_map_points 查不到／被擋掉的地名（2026-09-08 使用者回報：路竹車站六次查無，
# 畫面上沒有任何訊息）。純函式回傳型別不動（呼叫端與測試都只收 list），用 ContextVar 帶出去。
_map_missing_places: contextvars.ContextVar[list[str]] = contextvars.ContextVar("map_missing_places", default=[])


def map_missing_places() -> list[str]:
    return list(_map_missing_places.get())


# F40 第 3 層通知（2026-09-16）：resolve_portraits／apply_portrait_to_image_request 決定
# 用 entry_only 模式（維基有條目、沒有合格照片，允許模型依語境自畫）時，要讓前端訊息欄
# 顯示一句提示——但這兩個函式呼叫端很多、簽名不想全部改成回傳 notices，所以比照
# _map_missing_places 用 ContextVar 帶出去。端點在處理一次請求前呼叫
# reset_portrait_notices()，結尾用 collected_portrait_notices() 取回、寫進 response。
_portrait_notices: contextvars.ContextVar[list[str]] = contextvars.ContextVar("portrait_notices", default=[])


def reset_portrait_notices() -> None:
    _portrait_notices.set([])


def collected_portrait_notices() -> list[str]:
    return list(_portrait_notices.get())


def _record_portrait_notice(text: str) -> None:
    _portrait_notices.set(_portrait_notices.get() + [text])


# ============================================================
# B55 診斷（2026-09-21，使用者實機驗收「太嚴格，嘗試都沒有成功」之後加）
#
# 用 ContextVar 的理由跟 _portrait_notices 完全一樣：十點那條路的 `_cover_ai()`
# 回的是一個 tuple，要把診斷帶出去就得改它的回傳簽名與所有呼叫端；YT 那條路則是
# 在函式中段。兩邊都只是「順手記一筆」，不值得為它動兩條主線的簽名。
#
# 記什麼：`compose._measure_title_layer` 量到的全部數字，外加被擋下時模型回傳的
# 那張**原始標題圖層**。那張圖是這組診斷裡最有價值的一項——0921 的四次失敗只留下
# 一句錯誤訊息，「模型是畫了深色底板、畫了漸層、還是根本沒理會 background=
# transparent」三種假設一個都排除不掉。看一眼那張圖就分得出來。
# ============================================================
_title_layer_diags: contextvars.ContextVar[list[dict]] = contextvars.ContextVar(
    "title_layer_diags", default=[]
)
_title_layer_blocked: contextvars.ContextVar[list[bytes]] = contextvars.ContextVar(
    "title_layer_blocked", default=[]
)

# B109（2026-09-26 使用者裁決）：AI 標題出問題時，只有畫面描述無法還原模型實際
# 收到的完整 prompt。用 request-local ContextVar 從組 prompt 的深層函式帶回端點，
# 不改既有回傳 tuple／API response；只供成功稽核歸檔使用。
_cover_image_prompt: contextvars.ContextVar[str] = contextvars.ContextVar(
    "cover_image_prompt", default=""
)


def reset_title_layer_diags() -> None:
    _title_layer_diags.set([])
    _title_layer_blocked.set([])


def reset_cover_image_prompt() -> None:
    _cover_image_prompt.set("")


def _record_cover_image_prompt(prompt: str) -> None:
    _cover_image_prompt.set(prompt)


def collected_cover_image_prompt() -> str:
    return _cover_image_prompt.get()


def _record_title_layer_diag(
    diag: dict, blocked_png: bytes = b"", *, creativity: int | None = None,
) -> None:
    """記一次四道閘的量測結果。`blocked_png` 只在被擋下時給（成功筆的圖層已經疊進
    成品，不必另存一份）。

    `creativity`（2026-09-21）：稽核歸檔本來**完全沒有存創意等級**。使用者回報
    「AI生成純標題太大了」時，「模型畫多大」與「prompt 叫它畫多大」要對照才判得出
    是模型沒照做還是規格本身訂太大，而後者的數字正是由等級決定的——少這一欄就只能
    從成品反推（數招式件數、看有沒有傾斜）。跟圖層高度佔比放同一行，一眼對得起來。
    """
    if diag:
        entry = dict(diag)
        if creativity is not None:
            entry["creativity"] = creativity
        _title_layer_diags.set(_title_layer_diags.get() + [entry])
    if blocked_png:
        _title_layer_blocked.set(_title_layer_blocked.get() + [blocked_png])


def _title_layer_archive_fields() -> dict:
    """把本次請求記到的診斷整理成 `_archive_generation` 的 metadata 欄位。

    沒有走過透明圖層這條路（gemini、composite 模式、沒有 asis）就回空 dict，
    一個欄位都不會多出來——後台那一列的顯示也就跟以前完全一樣。"""
    diags = _title_layer_diags.get()
    if not diags:
        return {}
    fields: dict = {
        "title_layer_diag": diags if len(diags) > 1 else diags[0],
        # 給後台列表用的一句話：不用點開 JSON 就看得到是過還是被哪一道擋的。
        "title_layer_gate": "、".join(
            (d.get("gate") or "pass") for d in diags
        ),
    }
    blocked = _title_layer_blocked.get()
    if blocked:
        fields["extra_images"] = {
            (f"layer{i + 1}" if len(blocked) > 1 else "layer"): png
            for i, png in enumerate(blocked)
        }
    return fields


def portrait_entry_only_notice(names: list[str]) -> str:
    """F40 第 3 層的訊息欄文案。⚠使用者明確裁定：不要在圖上標「長相為 AI 推測」，
    改成這則 notice 顯示在前端既有的紅色訊息框（非致命提示，見 MASTER 列管 F40）。"""
    return (
        f"「{'、'.join(names)}」目前查不到可用的維基百科照片，"
        "畫面由生圖模型依新聞語境自行繪製，並非本人的精確肖像。"
    )


def resolve_map_points(chart_type: str, places: list[str] | None) -> list[MapPoint]:
    """把消化端列出的地名查成真實座標。查不到就少一個，全程不丟例外。

    為什麼要實查而不用模型寫的經緯度：2026-09-04 量過，「基隆廟口」差 107 公尺
    還可用，「西定路」差 1,470 公尺、「大武崙」差 2,296 公尺——在市區地圖上
    已經標到別的行政區。地名越冷門越不準，而新聞要標的往往正是冷門地名。

    失敗一律 fail-open：查不到、逾時、服務掛掉都只是沒有底圖，退回原本那條
    純 prompt 的路。地理編碼打嗝不可以讓一則本來出得了圖的新聞變成錯誤。
    """
    if chart_type != MAP_TYPE_LABEL or not places:
        return []
    points: list[MapPoint] = []
    missing: list[str] = []
    for place in places[:MAX_MAP_PLACES]:
        name = (place or "").strip()
        if not name:
            continue
        try:
            found = map_lookup.geocode(name)
        except Exception as exc:  # noqa: BLE001 — 監控用，不能拖垮消化
            print(f"[map] geocode 例外 {name}：{type(exc).__name__}: {exc}", flush=True)
            continue
        if found is None:
            print(f"[map] 查無座標，略過：{name}", flush=True)
            missing.append(name)
            continue
        # 標在圖上的是最後一段（「基隆市 西定路」→「西定路」）：查詢字串要夠明確
        # 才找得到，但畫面上不該出現「基隆市 西定路」這種查詢用的寫法。
        label = name.split()[-1] if " " in name else name
        points.append(MapPoint(name=label[:40], lat=found[0], lon=found[1]))
    _map_missing_places.set(missing)
    if len(points) < MIN_MAP_POINTS:
        if points:
            print(
                f"[map] 只查到 {len(points)} 個點（{'、'.join(p.name for p in points)}），"
                f"查不到：{'、'.join(missing) or '—'}，不足以構成相對位置，不做底圖",
                flush=True,
            )
        return []
    print(f"[map] 已定位 {len(points)} 個地點：{'、'.join(p.name for p in points)}", flush=True)
    return points


def build_digest_instructions(
    role: str,
    density: DigestDensity,
    type_label: str,
    full_bleed: bool = False,
    user_instruction: str = "",
    exclude_people: list[str] | None = None,
    asis_reference_count: int = 0,
    stamp: bool | None = None,
    editor_format: str | None = None,
    tone: DigestTone | None = None,
    map_scope_guard: bool = False,
    hole_side: str | None = None,
    visual_creativity: int = 0,
    seed: int | None = None,
) -> str:
    # seed（F0）：這一步只把資料流打通到這裡，實際拿去抽變化池是 2-6 的事。
    # 它**永遠不會被拼進回傳的字串**——見 next_generation_seed 上方的說明。
    is_editor = role == "編輯"
    template = EDITOR_SYSTEM_PROMPT_TEMPLATE if is_editor else SYSTEM_PROMPT_TEMPLATE
    if full_bleed:
        layout_rule = EDITOR_LAYOUT_FULL_BLEED if is_editor else REPORTER_LAYOUT_FULL_BLEED
    else:
        layout_rule = EDITOR_LAYOUT_SAFE_AREA if is_editor else REPORTER_LAYOUT_SAFE_AREA
    # 自動判斷模式下，樣板裡的類型描述改為由 AI 自選（實際選型規則見下方 directive）
    rendered_label = (
        "the chart type you select below"
        if type_label == AUTO_TYPE_LABEL
        else type_label
    )
    instructions = template.format(type_label=rendered_label, layout_rule=layout_rule)
    instructions += chart_type_directive(type_label)
    instructions += CONTENT_FIDELITY_RULES
    instructions += REAL_WORLD_FIDELITY_RULES
    instructions += CHILD_DEPICTION_STYLE_RULES
    instructions += DIRECTIONAL_COLOR_RULES
    instructions += CHROMA_KEY_GREEN_SAFETY_RULES
    # 自動判斷模式組 prompt 時還不知道 AI 會選哪一類，也要注入；
    # 區塊開頭自我限縮「非地圖類整段忽略」。
    #
    # 2026-09-10：明確指定非地圖類型時，原本兩塊都不注入（map_scope_guard 只有
    # 兩段式分類才會是 True，而 DIGEST_TWO_STAGE 預設關）——等於那條路徑上一條
    # 地理約束都沒有。實例：type_label=資訊卡 的高溫新聞，消化端寫出
    # "geographically accurate Taiwan map"，成品縣市界全錯（見
    # docs/error-cases/2026-09-10-台灣行政區界-錯誤-分析.md）。
    # 「明確指定非地圖類型」不等於「這張圖不會畫地圖」，所以守門條文改成一律有。
    if type_label in (MAP_TYPE_LABEL, AUTO_TYPE_LABEL):
        instructions += MAP_ACCURACY_RULES
    else:
        # 兩段式把自動判斷分類成非地圖（map_scope_guard=True，見 resolve_effective_type_label）
        # 與使用者自己指定非地圖類型，走的是同一條守門：兩者的前提都是「這張圖不畫地圖」。
        instructions += MAP_SCOPE_GUARD_RULES
    # B76：獨立於上面地圖／非地圖分流之外一律注入。事故發生時的圖正是走
    # MAP_SCOPE_GUARD_RULES 那條路（chart_type=資料圖表），證明「這張圖不算地圖」
    # 擋不住「畫一塊裝飾用的中國大陸輪廓」；兩條路都可能出現這塊輪廓，因此兩條都要有。
    instructions += CHINA_TAIWAN_OUTLINE_RULES
    if density in ("standard", "maximum"):
        instructions += STANDARD_DENSITY_RULES.format(
            **_STANDARD_LIMIT_CLAUSES[is_editor],
            **_density_bound_words("standard"),
        )
        if density == "maximum":
            instructions += MAXIMUM_DENSITY_RULES.format(**_density_bound_words("maximum"))
    elif density in ("simplified", "minimal"):
        instructions += SIMPLIFIED_DENSITY_RULES
        if density == "minimal":
            instructions += MINIMAL_DENSITY_RULES
    elif density == "verbatim":
        instructions += VERBATIM_DENSITY_RULES
    elif density == "no_text":
        instructions += NO_TEXT_DENSITY_RULES
    # 蓋章緊接在 density 之後：ON 的第 5 條要引用逐字模式，順序不能倒過來。
    # None＝呼叫端沒表態（LINE、舊呼叫端），完全不注入，維持既有行為。
    #
    # 無字檔一律不注入蓋章條文（2026-09-14 D14）：STAMP_ON 要求「最後一行是 <蓋章>」，
    # 跟「完全無字」正面衝突，兩條一起送出模型會挑寬鬆的那句遵守。關掉這件事由
    # NO_TEXT_FINAL_REMINDER 點名負責，那裡壓在整份 prompt 最後面。
    if density == "no_text":
        pass
    elif stamp is True:
        instructions += STAMP_ON_RULES
    elif stamp is False:
        instructions += STAMP_OFF_RULES
    # 色調緊接在蓋章之後：亮色調第 4 條要引用蓋章那條深色橫幅的例外，順序不能倒。
    # None＝不注入（見 DigestTone 的說明）。
    if tone == "dark":
        instructions += TONE_DARK_RULES
    elif tone == "light":
        instructions += TONE_LIGHT_RULES
    # 編輯專屬版型（播出鏡面）。editor_formats.digest_rules 對非編輯角色一律回空字串，
    # 這是「記者不可能誤用」的第三層防呆（前兩層在前端）。
    # density 一併傳進去：字多檔位在播出鏡面要把每張卡從一行改成兩行（2026-09-08 回饋 D）
    # hole_side 同理：合併後的播出鏡面靠請求決定挖哪一側（2026-09-08 WP1）
    instructions += editor_formats.digest_rules(
        editor_format, role, stamp, density, side=hole_side
    )
    # 創意拉桿放在版型區塊之後：本 repo 的慣例是「位置在後＋明文 OVERRIDE」才壓得住
    # 前面那些命令句。但它自己第一句就限縮成「只覆蓋美術」，而 FIXED 段再把
    # 字句、點數、安全框、清單外文字四件事釘回去。
    #
    # 無字檔完全不注入（2026-09-20 B78）。逐段檢查過 cg_creativity_rules 產出的
    # 四塊東西，沒有一塊乾淨地只描述「插圖本身的風格」：L1-L4 每一級的正文都在講
    # LAYOUT／HERO ZONE／SHAPE LANGUAGE／BREAK THE GRID 這些版面結構；
    # _CG_DESIGN_DRAW_TEMPLATE 的 PLATE SHAPE／ARRANGEMENT／HEADLINE BLOCK／
    # TILT DIRECTION 同樣是版面幾何，唯一例外 PALETTE 也寫成「work in these four
    # and no others」的硬性配色令，不是可有可無的插圖風格提示；device_block
    # （WORDLESS DEVICES）更是使用者原話點名的「設計」本身（icon 列、爆裂色塊……）
    # ——一律「draw every one of them」，不是選項。無字要的是「只要示意圖插圖」，
    # 這整組東西沒有半塊留得住，所以直接整段跳過，不試著切一半保留。
    if density != "no_text":
        instructions += cg_creativity_rules(visual_creativity, seed=seed)
    # 沒有 asis 附圖時完全不注入，消化 prompt 逐字元不變。
    if asis_reference_count:
        instructions += USER_REFERENCE_ASIS_DIGEST_RULES
    # 固定放最後：逐字模式必須壓過 SIMPLIFIED_DENSITY_RULES（位置＋明文 OVERRIDE 同向）
    instructions += USER_INSTRUCTION_RULES
    # 專用欄位緊接在文內解析規則之後（要引用「the block above」），沒填時不注入，
    # 確保既有輸出逐字元不變。
    if user_instruction.strip():
        instructions += DEDICATED_INSTRUCTION_RULES_TEMPLATE.format(
            instruction=user_instruction.strip()
        )
    # 排除名單放最末：要 OVERRIDE 上方第 5、6 條的「把人畫進來」語意。
    # 沒有人要排除時完全不注入，消化 prompt 逐字元不變。
    excluded = clean_portrait_subjects(exclude_people or [])
    if excluded:
        instructions += EXCLUDED_PEOPLE_RULES_TEMPLATE.format(
            people="\n".join(f"- {name}" for name in excluded)
        )
    # 真正的最後一塊：不消化必須壓過樣板開頭的「Digest the raw news text」，
    # 中段的 VERBATIM_DENSITY_RULES 實測壓不住（見該區塊上方的註解）。
    if density == "verbatim":
        instructions += VERBATIM_FINAL_REMINDER
    # 無字同理，而且要更後面：它要壓過的不只是樣板開頭，還有版型區塊釘死的卡片數
    # 與蓋章行（見 NO_TEXT_FINAL_REMINDER 上方的說明）。
    elif density == "no_text":
        instructions += NO_TEXT_FINAL_REMINDER
    return instructions


# generate_news_image() 會自己記一筆含最終 prompt 的完整紀錄，它內部呼叫的
# generate() 就不該再記一次半套的。用 contextvar 而不是函式參數，免得這個純內部
# 的旗標變成 /api/generate 對外可見的欄位。
_inside_pipeline = contextvars.ContextVar("inside_pipeline", default=False)
# apply_photo_availability 會再呼叫一次 generate()。deadline 放 contextvar，
# 第二次沿用同一條牆鐘，單一請求不會變成 230+230（B31）。
_digest_deadline = contextvars.ContextVar("digest_deadline", default=None)
# 同一 request 的 digest／封面重試次數，給稽核紀錄用，不另開計時器。
_generation_retry_count = contextvars.ContextVar("generation_retry_count", default=0)


# 截斷監控。三個呼叫端（generate／hybrid／cover）各有各的預算，過去只有真的炸了
# 才看得到蛛絲馬跡，而且訊息是「AI 回傳格式無法解析」這種看不出病因的話——
# 2026-09-04 的不消化截斷就是這樣被埋掉的，raw content 空字串，連截在哪都看不到。
# 這裡在唯一的收斂點記一行可 grep 的結構化紀錄，並在「差一點就截斷」時就先示警：
# 該提早看到的是逼近上限，不是已經撞牆。cover 那條寫死 600、hybrid 寫死 1200，
# 兩個都沒有隨輸入縮放，是下一個會撞的地方，靠這行紀錄提前現形。
DIGEST_USAGE_WARN_RATIO = 0.8


def log_digest_usage(site: str, model: str, budget: int, response) -> None:
    """把這次消化的用量記成一行。純觀測，絕不改變回傳或丟例外。"""
    try:
        usage = getattr(response, "usage", None)
        completion = getattr(usage, "completion_tokens", None) or 0
        # 思考 token 也算在 completion_tokens 裡（Anthropic／OpenRouter 都是），
        # 但拆不開就看不出「爆掉的是思考還是正文」——2026-09-09 追消化速度時
        # 只能靠 completion 9535 vs 觀測正文 1361 去反推。拆出來記著。
        details = getattr(usage, "completion_tokens_details", None)
        reasoning = getattr(details, "reasoning_tokens", None)
        finish = response.choices[0].finish_reason if response.choices else "?"
        ratio = completion / budget if budget else 0.0
        flag = ""
        if finish == "length":
            flag = " TRUNCATED"
        elif ratio >= DIGEST_USAGE_WARN_RATIO:
            flag = " NEAR-LIMIT"
        # provider 是 OpenRouter 在回應裡多帶的欄位（原生／Gemini 端點沒有）。
        # 2026-09-05 追這件事時最想知道卻查不到的就是它：同一個模型名可能被路由到
        # 不同 provider，脫軌到底是模型本身還是某一家的部署，沒有這欄分不出來。
        provider = (getattr(response, "model_extra", None) or {}).get("provider") or "-"
        print(
            f"[digest_usage] site={site} model={model} provider={provider} "
            f"budget={budget} completion_tokens={completion} "
            f"reasoning_tokens={'-' if reasoning is None else reasoning} "
            f"ratio={ratio:.2f} finish={finish}{flag}",
            flush=True,
        )
    except Exception as exc:  # 監控壞掉不可以拖垮消化
        print(f"[digest_usage] 記錄失敗（不影響本次消化）：{exc}", flush=True)


def digest_excerpt(raw: str, head: int = 600, tail: int = 300) -> str:
    """把原始輸出壓成一行可 grep 的摘要，保留頭也保留尾。

    2026-09-05 的病因全在尾巴：模型脫軌後吐純空白直到撞天花板，而舊版只記
    `raw_content[:800]`，日誌看到的永遠是正常的開頭，只好在本機重跑才看得到。
    整段照印又不行——實測一筆 12,391 字元有 84% 是空白，塞進日誌只是洗版。
    折衷是頭尾都留，中間換成統計，並把連續空白摺成一個記號。
    """
    if len(raw) <= head + tail:
        return re.sub(r"\s{4,}", " ⋯空白⋯ ", raw)
    ws = sum(1 for ch in raw if ch.isspace())
    middle = (
        f"\n…（中間省略 {len(raw) - head - tail} 字；全長 {len(raw)} 字、"
        f"{raw.count(chr(10)) + 1} 行、空白佔 {ws / len(raw):.0%}）…\n"
    )
    return (
        re.sub(r"\s{4,}", " ⋯空白⋯ ", raw[:head])
        + middle
        + re.sub(r"\s{4,}", " ⋯空白⋯ ", raw[-tail:])
    )


def digest_retry_note(attempt: int, category: str, summary: str) -> str:
    """給下一輪 digest 的修正說明。只含分類後原因，不含 provider 原文。"""
    clipped = audit_archive.sanitize_error_summary(summary)
    return (
        f"[Retry context] Previous attempt {attempt} failed "
        f"(category={category}): {clipped}. "
        "Correct this failure and return complete valid JSON."
    )


def digest_completion(
    *,
    model: str,
    system_prompt: str,
    news_text: str,
    max_output_tokens: int,
    schema_name: str,
    schema: dict,
    site: str = "digest",
    raw_user_message: bool = False,
    timeout: float | None = None,
    retry_context: str = "",
    reasoning_effort: str | None = None,
):
    """呼叫 Chat Completions 取結構化消化結果。

    raw_user_message：呼叫端已自行組好 user 訊息（分類器要把指令欄一起帶上），
    不再套 News Source Material 包裝。

    timeout：不給就用 DIGEST_TIMEOUT_SECONDS。**不可以是 None**——SDK 預設 600 秒，
    比 Cloud Run 的 300 秒還長，一通卡住的請求就會讓前端停在 35% 永遠不動
    （2026-09-10 線上事故）。分類呼叫自己給更短的值，因為它必須快、失敗就退回舊路徑。

    輸出長度上限的參數名兩邊不同：OpenRouter 吃 max_tokens，OpenAI 原生的新模型
    （如 gpt-5.6-terra）只吃 max_completion_tokens，送錯直接 400。因此先送
    max_tokens，被明確拒絕時再改用 max_completion_tokens——否則沒設
    OPENROUTER_API_KEY 時的原生退路等於是壞的（實測 2026-07-30 撞到）。

    走 Gemini 時把呼叫端要求的上限拉到 GEMINI_DIGEST_MIN_TOKENS 以上——Gemini
    的隱藏思考 token 用一般上限（1200-1500）幾乎必然截斷正文（同日實測撞到）。

    retry_context：可選，只附加在 user message 尾端，不改 system prompt。
    未傳時產生的 payload 與舊版相同。

    reasoning_effort：可選，覆寫這一次的 reasoning.effort（重試降級用）。
    未傳時仍走 digest_reasoning_body() 的一般預設。
    """
    if DIGEST_BACKEND == "gemini":
        max_output_tokens = max(max_output_tokens, GEMINI_DIGEST_MIN_TOKENS)
    user_content = (
        news_text
        if raw_user_message
        else f'News Source Material:\n"{news_text}"'
    )
    if retry_context:
        user_content = f"{user_content}\n\n{retry_context}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_content,
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    # 逾時走 payload 而不是 with_options：with_options 會複製出**另一個 client**，
    # 呼叫端與測試對 openai_client 的 patch 就都失效了。
    payload["timeout"] = DIGEST_TIMEOUT_SECONDS if timeout is None else timeout
    client = openai_client
    # effort 只有 OpenRouter 吃得到，而且不是每個模型都支援；被明確拒絕時原樣重送
    # 一次不帶這個欄位的請求，換模型不會把整條線弄壞（見 digest_reasoning_body）。
    # provider 選擇同樣只有 OpenRouter 吃得到，兩者共用同一個 extra_body
    # （2026-09-11 一起加進來，見 digest_provider_body）。
    reasoning = digest_reasoning_body(reasoning_effort)
    extra_body = {**digest_provider_body(), **reasoning}
    if extra_body:
        payload["extra_body"] = extra_body
    try:
        response = client.chat.completions.create(
            **payload, max_tokens=max_output_tokens
        )
    except BadRequestError as exc:
        message = str(exc)
        if reasoning and "reasoning" in message:
            print(f"[digest] 模型不吃 reasoning effort，改用預設思考量：{message}", flush=True)
            # 只拿掉 reasoning，provider 順序要留著——整包 pop 會把換 provider
            # 的能力一起丟掉，而那正是撞過載時唯一還有用的東西。
            extra_body.pop("reasoning", None)
            if extra_body:
                payload["extra_body"] = extra_body
            else:
                payload.pop("extra_body", None)
            reasoning = {}
            try:
                response = client.chat.completions.create(
                    **payload, max_tokens=max_output_tokens
                )
            except BadRequestError as retry_exc:
                if "max_completion_tokens" not in str(retry_exc):
                    raise
                response = client.chat.completions.create(
                    **payload, max_completion_tokens=max_output_tokens
                )
        elif "max_completion_tokens" not in message:
            raise
        else:
            response = client.chat.completions.create(
                **payload, max_completion_tokens=max_output_tokens
            )
    log_digest_usage(site, model, max_output_tokens, response)
    return response


# 消化輸出健檢用：新聞稿消化結果應該只由中文、日文假名、拉丁字母（含歐洲人名的
# 附加符號）、數字、標點與空白組成。實測 2026-07-31 休達案例，模型在輸出長度壓力下
# 會在 variable 尾端接上亞美尼亞文、西里爾文與博弈垃圾字串——語法上仍是合法 JSON，
# 所以只檢查 json.loads 的舊版會直接收下並送去生圖。這裡把「不可能出現的文字系統」
# 當成污染訊號。
DIGEST_ALLOWED_CHARS = re.compile(
    r"[一-鿿㐀-䶿"      # 中日韓統一表意文字（含擴充 A）
    r"　-〿぀-ヿ"       # 中日韓標點、日文假名
    r"＀-￯"                    # 全形字母數字與標點
    r"‐-⁞"                    # 一般標點（破折號、引號、刪節號）
    r" -ÿ"                    # 拉丁字母補充（é ñ ü 等歐洲人名、°）
    r"\x20-\x7e\r\n\t]"                 # ASCII 可見字元與空白
)
# 單一雜字不足以判定污染（模型偶爾夾一個罕用符號），連續出現才是。
DIGEST_MAX_STRAY_CHARS = 3
# variable 是繁中新聞文字，正常情況拉丁字母只佔少數（地名、機型代號）。比例過高
# 代表模型開始用英文自言自語（實測撞到 "Need correct. We accidentally weird."）。
# 2026-08-24 熱修：asis 消化規則區塊整段英文，疑似把正常輸出的拉丁字母比例推到
# 36~46%，卡在舊門檻 0.35 造成 5 次重試全滅、拖到 502。先放寬到 0.55 止血，
# 真正的自言自語（實測撞過 100%）仍會被擋下。
DIGEST_MAX_LATIN_RATIO = 0.55
# 角色／頻道標記洩漏。2026-09-05 實測 openai/gpt-5.6-terra（OpenRouter，
# provider=OpenAI）：模型會把自己的頻道路由語法當成一般文字吐進內容，形如
# 「<蓋章>提醒民眾避開低窪路段}} դժassistant to=system.summary  天天中彩票不json: {」，
# 後面常接簡體賭博站語料與多語系碎片。
# 字元集與拉丁字母比例都攔不到這一種：異常字元只有兩個（未達
# DIGEST_MAX_STRAY_CHARS），其餘是 CJK 與 ASCII。於是它通過健檢、原樣寫進最終
# prompt 被畫上成品。真正的指紋是標記本身，字元統計看不到。
# 「assistant」單獨出現是正常英文字（AI assistant），只有帶 to= 的路由形式才算。
#
# 簡體與異體字。2026-09-05 實測撞到「貨櫃車起火脱困」——「脱」（U+8131）不是
# 臺灣標準的「脫」（U+812B），單字級的異體形，消化端那句「台灣繁體中文」擋不住，
# 成品照樣印出來。這是程式判得出來的事，而同日已經證明「再加一條 prompt 規則」
# 會推高思考 token、程式檢查不會，所以擋在品質閘而不是寫進 prompt。
#
# 這份清單刻意**不追求完整**：完整的簡繁對照要靠 OpenCC 那類詞庫，為了一個
# 字元級健檢引進相依套件不划算。收錄範圍是「臺灣新聞文字裡出現就一定是錯」的
# 高頻簡體字，加上實測撞過的異體形。漏網的下次撞到再補——擋掉多數勝過都不擋。
# 「台」刻意不收：台灣／電視台／台積電都是正當用法，收進來只會製造假警報。
#
# 2026-09-11：清單裡原本收了「致」，那是**誤收**——「致」是臺灣標準正字
# （導致／一致／致命／致詞），繁簡同形。當初大概是想擋「精緻」被寫成「精致」，
# 但那是詞級的問題，用字元級清單擋等於把最高頻的正字之一整個封殺。
# 代價不是「偶爾誤判」而是必然失敗：模型只要寫出「導致」就被打回，五次 attempt
# 每次都寫得出來，於是每次都被擋，最後撞 DIGEST_DEADLINE_SECONDS 收 503。
# 實測 2026-09-09 雲端與 2026-09-11 本機各撞過一次，使用者看到的是「消化失敗」。
# 收字進這份清單前必須確認它**不是繁體正字**——繁簡同形的字一個都不能收。
DIGEST_NON_TW_CHARS = frozenset(
    "脱说这个们时会对关电车长门问见现义应学实发医华国图书报广东头马鸟龙汉"
    "丽临举乐习乡买乱争产亲从价众优伟传伤纪级红约细纸练组经给统绝继续维绿"
    "网罗职联胜脑舰艰苏药处备复够夺奋妇孙宁宝宪审层岁岛峡师带帮庆废弃张"
    "强归录彻恋总恶闷闻阅阳阴际陆随难题风"
)
DIGEST_CHANNEL_LEAK = re.compile(
    r"assistant\s+to\s*=|to=(?:assistant|system|final)\b|numerusform",
    re.IGNORECASE,
)
# 放寬 token 上限後出現的另一種失控：模型不再截斷，改成把原文每個詞都拆成一條
# [內文小標] 灌到幾十行（實測撞到 90 行、同一詞重複出現）。長度本身不能當判準——
# 逐字模式本來就會產生長 variable——但大量重複的行是失控獨有的訊號。
# 行數上限刻意抓得寬鬆：逐字模式重現的完稿 CG 腳本本來就可能有十幾行，不能誤傷。
# 實測的失控案例是 90 行，跟正常輸出差一個量級，40 行足以區隔。
DIGEST_MAX_VARIABLE_LINES = 40
DIGEST_REPETITION_MIN_LINES = 10
DIGEST_MIN_UNIQUE_LINE_RATIO = 0.8


def parse_digest_json(raw_content: str) -> dict:
    """解析消化輸出。模型有時會包 ```json 圍欄，必須先拆掉再 json.loads。"""
    text = (raw_content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)


# 不消化模式的逐字守門員（2026-09-03）。
#
# 為什麼還需要它：prompt 已經寫得夠死，實測內容也確實一字不差了，但模型會在
# variable 的頭尾多吐東西——實測撞到兩種：整段被 " 包起來、以及尾巴接上
# 「}】}⟦json_schema_error_recovery: remove extraneous⟧{」。內容對、外殼不對，
# 而這些字元會原樣被畫進鏡面。通用的 DIGEST_ALLOWED_CHARS 檢查抓不到（雜訊只有
# 兩個字元超出白名單，沒到 3 個的門檻）。
#
# 原本只在「指令欄是空的」時才啟用（指令欄優先於消化程度）。B106（2026-09-26）
# 使用者把不改字收緊成硬承諾：指令欄有字也照比，衝突時報錯請使用者二選一。
_VERBATIM_MARKER_RE = re.compile(r"\[標題\]|\[內文小標\]|<蓋章>|<底帶>|[<>]")
_VERBATIM_WS_RE = re.compile(r"\s+")


# 逐字要求（不消化那一檔，或指令欄寫「逐字保留」）會誘發模型把整段 variable 用
# 引號包起來——它以為自己在「引用」使用者的原文。那對引號會被原樣畫進鏡面。
# 只在「頭尾是同一個引號、且整段只出現這兩次」時才剝，正常的 CG 文案不會長這樣，
# 內文自己帶引號的句子（例如 他說「…」）也不會被誤傷。
_WRAPPING_QUOTES = ('"', "'", "「", "『", "“", "‘")
_CLOSING_QUOTES = {"「": "」", "『": "』", "“": "”", "‘": "’"}


def strip_wrapping_quotes(variable: str) -> str:
    text = (variable or "").strip()
    for opening in _WRAPPING_QUOTES:
        closing = _CLOSING_QUOTES.get(opening, opening)
        if not (text.startswith(opening) and text.endswith(closing) and len(text) > 2):
            continue
        inner = text[len(opening):-len(closing)]
        if opening in inner or closing in inner:
            continue
        return inner.strip()
    return text


_STAMP_LINE_RE = re.compile(r"^\s*[<＜]\s*蓋章\s*[>＞]")


def drop_stamp_lines(variable: str) -> str:
    """蓋章 OFF 的硬保險（2026-09-07）：不管消化模型有沒有聽話，<蓋章> 行一律拿掉。

    使用者回報播出鏡面 OFF 仍蓋章——prompt 層已修（editor_formats 第 6 條），但 prompt
    只是勸告，這裡做確定性的兜底，任何版型都適用。只刪以 <蓋章> 開頭的整行。
    """
    kept = [line for line in (variable or "").splitlines() if not _STAMP_LINE_RE.match(line)]
    return "\n".join(kept).strip()


def unmark_stamp_lines(variable: str) -> str:
    """不改字模式的蓋章 OFF（B106，2026-09-26）：那一行是使用者自己的正文，
    整行刪掉就是掉字。只拿掉 <蓋章> 標記，正文留下。"""
    lines = [
        _STAMP_LINE_RE.sub("", line).strip() if _STAMP_LINE_RE.match(line) else line
        for line in (variable or "").splitlines()
    ]
    return "\n".join(line for line in lines if line.strip()).strip()


# 播出鏡面 ＋ 蓋章 OFF 的底帶（2026-09-09 第四批）。挖空框是寬扁的 16:9 視窗、垂直
# 置中，底下本來就空著一條橫帶；蓋章 ON 時那條由 <蓋章> 填，OFF 時使用者要求「其他
# 資訊還是可以放底下」。prompt 已經改成要求一行 <底帶>，但 prompt 只是勸告——第三批
# 就是敗在這裡（叫模型「把最後一張卡下移」，模型分不出哪張是最後一張）。這裡做確定性
# 兜底：漏寫就把最後一行 [內文小標] 升級成 <底帶>，位置與內容都不動，只換標記。
_BOTTOM_BAND_LINE_RE = re.compile(r"^\s*[<＜]\s*底帶\s*[>＞]")
_POINT_LINE_RE = re.compile(r"^\s*\[內文小標\]\s*")


def ensure_bottom_band_line(variable: str) -> str:
    lines = (variable or "").splitlines()
    if any(_BOTTOM_BAND_LINE_RE.match(line) for line in lines):
        return variable
    for index in range(len(lines) - 1, -1, -1):
        if _POINT_LINE_RE.match(lines[index]):
            body = _POINT_LINE_RE.sub("", lines[index]).strip()
            if not body:
                return variable
            promoted = lines[:index] + lines[index + 1:] + [f"<底帶> {body}"]
            return "\n".join(promoted).strip()
    return variable


# B106（2026-09-26）：以「指示:」「指令:」開頭的行保證是指令、不是正文
# （USER_INSTRUCTION_RULES 第 2 條），比對前先從原文剔除——模型照規則把它排掉，
# 不能反過來被判成掉字。沒標記的散文指令無法確定性辨識，仍當正文比對。
_VERBATIM_INSTRUCTION_LINE_RE = re.compile(r"^\s*(?:指示|指令)\s*[:：]")
VERBATIM_MISMATCH_DETAIL = (
    "「不改字」模式下，AI 重試多次仍無法把原文一字不差地排進去。"
    "常見原因：①原文裡夾了沒標記的指令——請在那行開頭加「指示:」，或改寫進指令欄；"
    "②指令欄要求精簡／濃縮，與「不改字」互相衝突——請擇一。"
)


def verbatim_source_text(news_text: str) -> str:
    """不改字要逐字保留的原文：剔除保證是指令的行。"""
    return "\n".join(
        line
        for line in (news_text or "").splitlines()
        if not _VERBATIM_INSTRUCTION_LINE_RE.match(line)
    )


def _verbatim_normalise(text: str) -> str:
    # 兩邊走同一套：使用者貼的完稿本身常帶 [標題]／<蓋章>，正文裡也可能有 < >。
    return _VERBATIM_WS_RE.sub("", _VERBATIM_MARKER_RE.sub("", text))


def verbatim_fidelity_problem(variable: str, news_text: str) -> str:
    """不消化模式：variable 去掉標記與空白後必須與原文（剔除指令行）逐字相同。"""
    body = _verbatim_normalise(strip_wrapping_quotes(variable))
    source = _verbatim_normalise(verbatim_source_text(news_text))
    if body == source:
        return ""
    missing = "".join(dict.fromkeys(ch for ch in source if ch not in body))
    extra = "".join(dict.fromkeys(ch for ch in body if ch not in source))
    return (
        f"不消化模式但 variable 與原文不符（原文 {len(source)} 字、輸出 {len(body)} 字；"
        f"缺 {ascii(missing[:20])}；多 {ascii(extra[:20])}）"
    )


def digest_quality_problem(
    data: dict,
    finish_reason: str,
    density: str | None = None,
    format_key: str | None = None,
    news_text: str = "",
) -> str:
    """檢查消化結果是否可用，通過回傳空字串，否則回傳給 log 用的問題描述。

    語法合法不等於內容可用。截斷（finish_reason=length）與字元污染都會產生
    「能解析但不能用」的結果，必須跟解析失敗一樣走重試，不能直接送去生圖。

    `density`（2026-09-14 D14）：無字檔**要求** variable 是空字串，所以「欄位為空」
    對它是正確答案而不是故障。不分檔一律擋的話，無字會連撞 5 次重試然後回 502，
    而且使用者看到的是「AI 回傳內容異常」——完全看不出是設定本身被擋掉。
    其餘檢查（型別、異常字元、頻道洩漏、簡體字）對無字照舊全部生效。
    """
    if finish_reason == "length":
        return "輸出被截斷（finish_reason=length）"

    variable_may_be_empty = density == "no_text"
    for field in ("style", "structure", "variable"):
        value = data.get(field) or ""
        # 模型偶爾無視 strict schema 把欄位回成巢狀物件／陣列（2026-08-17 實測：
        # 使用者帶指令＋參考圖時 variable 回成 dict，.strip() 直接 AttributeError
        # 炸 500）。型別不對與截斷同級：能解析不代表能用，走重試。
        if not isinstance(value, str):
            return f"{field} 不是字串（{type(value).__name__}）"
        if not value.strip() and not (field == "variable" and variable_may_be_empty):
            return f"{field} 為空"
        stray = DIGEST_ALLOWED_CHARS.sub("", value)
        if len(stray) >= DIGEST_MAX_STRAY_CHARS:
            # 用 ascii() 轉義：這些字元照原樣印會在 Windows cp950 主控台丟
            # UnicodeEncodeError，把診斷訊息本身變成當掉整條請求的新故障
            return f"{field} 含 {len(stray)} 個異常字元：{ascii(stray[:40])}"
        if leak := DIGEST_CHANNEL_LEAK.search(value):
            return f"{field} 含角色／頻道標記「{leak.group(0)}」，模型頻道洩漏"
        # 只檢查 variable：style／structure 是寫給生圖模型的英文指令，不是畫面
        # 文字，偶爾夾一個中文字不影響觀眾看到的東西，擋它只會製造無謂重試。
        if field == "variable":
            bad = sorted({ch for ch in value if ch in DIGEST_NON_TW_CHARS})
            if bad:
                return f"{field} 含簡體／異體字「{''.join(bad)}」，非臺灣標準字形"

    variable = data.get("variable") or ""
    latin = sum(1 for ch in variable if "a" <= ch.lower() <= "z")
    if variable and latin / len(variable) > DIGEST_MAX_LATIN_RATIO:
        return f"variable 拉丁字母比例 {latin / len(variable):.0%} 過高，疑似模型自言自語"

    # 比對去掉標記後的文字，才抓得到同一句話掛在不同標記下重複出現。只剝
    # [標題]／【內文小標】這種「前綴」標記——<...> 是整句強調、不是前綴，
    # 連同內容一起剝掉會把數個強調行都變成空字串、誤判成重複。
    lines = [
        stripped
        for line in variable.splitlines()
        if (stripped := re.sub(r"^\s*[\[【][^\]】]*[\]】]", "", line).strip())
    ]
    if len(lines) > DIGEST_MAX_VARIABLE_LINES:
        return f"variable 共 {len(lines)} 行，疑似逐詞灌行失控"
    if len(lines) >= DIGEST_REPETITION_MIN_LINES:
        ratio = len(set(lines)) / len(lines)
        if ratio < DIGEST_MIN_UNIQUE_LINE_RATIO:
            return f"variable {len(lines)} 行中僅 {ratio:.0%} 不重複，疑似逐詞灌行失控"

    return digest_point_count_problem(variable, density, format_key, news_text=news_text)


def digest_point_count_problem(
    variable: str,
    density: str | None = None,
    format_key: str | None = None,
    *,
    news_text: str = "",
) -> str:
    """B57 的塊數防呆，單獨一支是為了讓 `generate()` 能問「這次唯一的問題是不是
    只有塊數」——B67（2026-09-16 使用者裁決）要在最後一次嘗試放行塊數不足，
    但截斷／型別錯／頻道洩漏那些仍然要擋到底，兩者必須分得出來。"""
    observed = count_density_points(variable)
    if density == "minimal" and observed > MINIMAL_POINT_HARD_MAX:
        return (
            "variable [內文小標] 塊數超過上限"
            f"（observed={observed} maximum={MINIMAL_POINT_HARD_MAX}）"
        )

    minimum, target = density_point_bounds(density, format_key)
    if minimum is None:
        return ""
    if density == "simplified":
        # 薄稿不補點；播出鏡面的張數等 D17 落地後另驗，B105 不替它加守門。
        if source_visible_char_count(news_text) < SIMPLIFIED_SOURCE_MIN_VISIBLE_CHARS:
            return ""
        if _format_exact_point_count(format_key, density) is not None:
            return ""
    if target is not None and minimum == target:
        if observed != minimum:
            return (
                f"variable [內文小標] 塊數不符"
                f"（observed={observed} required={minimum}）"
            )
    elif observed < minimum:
        return (
            f"variable [內文小標] 塊數不足"
            f"（observed={observed} required={minimum}）"
        )
    return ""


def source_visible_char_count(news_text: str) -> int:
    """來源可見字數：只排除 Unicode 空白，標點仍是觀眾可見且承載句界的字元。"""
    return sum(1 for ch in (news_text or "") if not ch.isspace())


def verify_internal_api_key(
    x_api_key: str = Header(default=""),
    authorization: str = Header(default=""),
) -> None:
    # 啟用 Clerk 後，登入本身就是憑證：前端拿不到 NEWS_IMAGE_API_KEY（公開的
    # app.js 不烙金鑰），改由 index.html 包的那層 fetch 帶上 Bearer 權杖。
    # 這裡再驗一次而不是信任 middleware，是為了讓這支 Depends 自成防線——
    # 日後有人改動 middleware 的放行清單，這道門不會跟著破掉。
    # JWKS 有快取，重複驗證不會產生額外的對外請求。
    if clerk_auth.ENABLED and authorization.startswith("Bearer "):
        if clerk_auth.verify_token(authorization[7:].strip()):
            return

    # 未設定金鑰時 fail-closed（與 LINE webhook 的驗簽同一原則），
    # 避免忘記設定就把端點裸奔給外部呼叫。這把金鑰同時保護所有內部
    # 生成端點（news-image / generate / hybrid-digest / images-generate），
    # LINE webhook 不受影響，因為它走自己的簽章驗證，不掛這個 Depends。
    expected = os.getenv("NEWS_IMAGE_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="尚未設定 NEWS_IMAGE_API_KEY")
    if not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="API Key 無效")


def apply_photo_availability(
    result: GenerateResponse, req: GenerateRequest
) -> GenerateResponse:
    """網頁版消化端接上 F40 四層分流。

    只有第 4 層（連維基條目都查不到）才重新消化、把人排出版面；第 3 層（有條目但
    沒有合格照片）保留在版面，並以 nonfatal notice 告知使用者。

    使用者上傳的肖像照視為對應**系統查不到的人**、依序對應：會自己上傳照片，通常
    正是因為那個人維基查不到（吳軒彤那個原始情境）。這是一個假設，寫在這裡是為了
    日後有人覺得對應錯了時，知道該改哪裡。

    使用者上傳肖像照的數量仍依序覆蓋查不到照片的人；其餘才進四層判斷。第 4 層
    只重試一次，理由同 resolve_digest_portraits。
    """
    subjects = result.portrait_subjects
    if not subjects:
        return result
    outcomes = lookup_portrait_outcomes(
        subjects, result.portrait_subjects_en, result.portrait_subjects_en_guess,
        req.news_text,
    )
    photos = {
        name: outcome.photo
        for name, outcome in outcomes.items()
        if outcome.photo is not None
    }
    missing = [name for name in subjects if name not in photos]
    if req.portrait_photo_count:
        missing = missing[req.portrait_photo_count :]
    entry_only = [name for name in missing if outcomes[name].entry_found]
    lookup_failed = [name for name in missing if outcomes[name].lookup_failed]
    no_entry = [
        name for name in missing
        if not outcomes[name].entry_found and not outcomes[name].lookup_failed
    ]
    # B73 第二半（2026-09-16 使用者裁決）：查不到條目的人不再被排出版面。
    # 這裡是第二個必須跟著改的地方——只改 resolve_portraits 不改這裡的話，
    # 網頁版會**先在消化階段把人踢掉**，根本走不到那個分流（exclude_people 一下去，
    # portrait_subjects 就空了）。兩處同一個開關，出事一起關。
    if PORTRAIT_NO_ENTRY_FALLBACK:
        told = entry_only + no_entry
        if told:
            _record_portrait_notice(portrait_entry_only_notice(told))
        if lookup_failed:
            print(
                f"[portrait] 肖像查詢失敗（{'、'.join(lookup_failed)}），保留安全退路",
                flush=True,
            )
        return result
    if not no_entry:
        if entry_only:
            _record_portrait_notice(portrait_entry_only_notice(entry_only))
        return result

    print(
        f"[portrait] 網頁版連維基條目都查不到（{'、'.join(no_entry)}），"
        "重新消化一次把他們排出版面",
        flush=True,
    )
    # 設 _inside_pipeline 是為了讓第二次消化不要又跑一次可用性檢查（會無限遞迴），
    # 也不要重複落檔——最終結果由外層那筆記錄。
    token = _inside_pipeline.set(True)
    try:
        retried = generate(
            req.model_copy(update={"exclude_people": no_entry})
        )
        retried_outcomes = lookup_portrait_outcomes(
            retried.portrait_subjects, retried.portrait_subjects_en,
            retried.portrait_subjects_en_guess, req.news_text,
        )
        retried_missing = [
            name for name in retried.portrait_subjects if name not in retried_outcomes
            or retried_outcomes[name].photo is None
        ]
        if req.portrait_photo_count:
            retried_missing = retried_missing[req.portrait_photo_count :]
        retried_entry_only = [
            name for name in retried_missing if retried_outcomes[name].entry_found
        ]
        if retried_entry_only:
            _record_portrait_notice(portrait_entry_only_notice(retried_entry_only))
        return retried
    finally:
        _inside_pipeline.reset(token)


# 純業務邏輯，不掛路由——網頁版的 /api/generate（見下面 generate_stream，B39
# 改成串流）與 LINE／整合端的 generate_news_image() 共用同一份實作，兩邊都是
# 直接呼叫這個函式，不經 HTTP。呼叫端要的是「消化完成或明確失敗」，跟外面那層
# 用什麼格式把結果送出去無關。
def generate(req: GenerateRequest):
    # own_clock：這支函式會被巢狀呼叫兩種情境——apply_photo_availability 第 4 層
    # 補救（下面呼叫它那行）與 generate_news_image() 的 pipeline，兩邊都會在呼叫
    # 前把 _inside_pipeline 設 True，而且各自有自己的落檔（外層決定最終結果後
    # 才記一筆），這裡再記一次就是重複。只有「真的是最外層」才記消化階段自己的
    # 成功／失敗。
    #
    # 2026-09-20（B72／F31 正式站實查）：`/api/generate` 這支消化端點原本完全沒有
    # 失敗落檔——所有 HTTPException（逾時 503、認證 503、限流 429、格式錯 502、
    # verbatim 太長 400）都直接往外丟，`request_log.log_generation` 只有成功路徑
    # 才會走到。正式站實查 09-18～09-20 共 91 筆後台紀錄失敗數是 0，但同期已知
    # 有 Cloudflare 524（消化太久）與上游 502——這些全部發生在消化階段、完全沒
    # 進稽核歸檔，「成功率 100%」是假的。成功那半邊也一樣：這裡以前只寫
    # request_log 的 JSONL（14 天會被掃掉、重新部署即清空），沒有寫進
    # audit_archive，所以連「消化階段總共跑了幾次」這個分母都答不出來。
    own_clock = not _inside_pipeline.get()
    if own_clock:
        reset_portrait_notices()
    # seed（F0）在最前面就定下來，並寫回 req：apply_photo_availability 會拿這份 req
    # 再呼叫一次 generate()，沒寫回的話第二次會再抽一顆，同一個請求的兩段消化就用了
    # 兩種長相，回應報的 seed 也重現不出成品。
    if req.seed is None:
        req = req.model_copy(update={"seed": next_generation_seed()})
    seed = req.seed
    # DIGEST_MODEL 可覆寫；沿用舊環境變數 OPENAI_DIGEST_MODEL 作為次要相容
    model = resolve_digest_model()
    digest_request_id = request_log.new_request_id() if own_clock else ""
    digest_started = _generation_clock() if own_clock else 0.0
    if own_clock:
        _reset_generation_retries()
    # 兩段式（條件注入）：分類成功就整段當成使用者指定了該類型——組 prompt、
    # 選 schema、給預算、chart_type 退路四處一致；分類失敗則 type_label 原樣，
    # 下面每一行都與舊路徑逐字元相同。
    type_label = resolve_effective_type_label(req, model)
    # 分類成非地圖時仍要一道短的地理範圍守門（理由見 MAP_SCOPE_GUARD_RULES）；
    # 使用者自己指定非地圖類型時維持舊行為，不注入。
    classified_non_map = (
        req.type_label == AUTO_TYPE_LABEL and type_label not in (AUTO_TYPE_LABEL, MAP_TYPE_LABEL)
    )
    system_prompt = build_digest_instructions(
        role=req.role,
        density=req.density,
        type_label=type_label,
        map_scope_guard=classified_non_map,
        # 編輯版兩檔都要滿版版面，不能直接看 safe_frame（見 resolve_frame_plan）
        full_bleed=(
            False
            if model_extension_active(req.role, req.safe_frame, req.frame_strategy)
            else resolve_frame_plan(req.role, req.safe_frame, req.density)[0]
        ),
        user_instruction=req.user_instruction,
        exclude_people=req.exclude_people,
        asis_reference_count=req.asis_reference_count,
        stamp=req.stamp,
        tone=req.tone,
        editor_format=req.editor_format,
        hole_side=req.hole_side,
        visual_creativity=req.visual_creativity,
        seed=seed,
    )

    # 上游（OpenRouter 多 provider 輪替）偶發 502、輸出截斷或不合 schema 的回傳是常態，
    # 重試圈必須涵蓋「呼叫＋解析」全程——只重試呼叫，解析失敗一樣會把錯誤丟給使用者。
    # 作法比照 hybrid_digest：金鑰／用量問題不重試（重試也沒用），其餘 3 次 × 1.5 秒。
    # 輸出上限依類型與消化程度分開給，理由見 digest_token_budget。
    max_output_tokens = digest_token_budget(type_label, req.density, req.news_text)
    last_detail = "AI 服務處理失敗，請確認模型權限或稍後重試"
    retry_context = ""
    reasoning_effort = None
    existing_deadline = _digest_deadline.get()
    if existing_deadline is None:
        deadline = time.monotonic() + DIGEST_DEADLINE_SECONDS
        deadline_token = _digest_deadline.set(deadline)
    else:
        deadline = existing_deadline
        deadline_token = None
    try:
        for attempt in range(DIGEST_ATTEMPTS):
            # 還沒開始就已經沒時間了：與其讓 Cloud Run 在第 300 秒直接斷線（使用者看到
            # 的是「沒有生成」，連錯誤都沒有），不如在這裡停手，回一個看得懂的訊息。
            # 看的是「這一次跑滿也來不及」而不是「現在超過死線沒」（2026-09-10）：
            # 每次 attempt 最久跑 DIGEST_TIMEOUT_SECONDS，在死線前一刻才起跑的那次
            # 會整整超出一個 timeout，剛好把 Cloud Run 的 300 秒吃掉。
            # 2026-09-14 B31：attempt 0 也查，第二次 generate() 沿用同一條 deadline。
            if time.monotonic() + DIGEST_TIMEOUT_SECONDS > deadline:
                print(
                    f"[generate] 已用掉 {DIGEST_DEADLINE_SECONDS:.0f} 秒預算，"
                    f"停在第 {attempt + 1} 次 attempt 不再重試",
                    flush=True,
                )
                raise HTTPException(
                    status_code=503,
                    detail="AI 服務這次太久沒有回應，請縮短新聞內容或稍後重試",
                )
            try:
                response = digest_completion(
                    model=model,
                    system_prompt=system_prompt,
                    # B88（2026-09-22 使用者回報「川習被畫成背影」）：簡稱對照表
                    # 以前只接在兩條封面推導上（`resolve_cover_visuals`／
                    # `derive_yt_cover_plan`），一般 CG 這條完全沒接——而 B82 的
                    # 因果鏈在這裡一字不差地重演：簡稱推導不出人名 →
                    # `portrait_subjects` 交白卷 → 查不到參考照 →
                    # `news_prompt.py:334`「沒有附照片的具名真人必須畫成背影或剪影」
                    # → 背影。沒命中時回空字串，素材與加表之前逐字相同。
                    news_text=req.news_text + name_aliases.alias_hint_block(
                        req.news_text, req.user_instruction
                    ),
                    max_output_tokens=max_output_tokens,
                    schema_name="news_cg_digest",
                    schema=digest_schema(type_label),
                    site="generate",
                    retry_context=retry_context,
                    reasoning_effort=reasoning_effort,
                )
            except AuthenticationError as exc:
                raise non_retryable_upstream_error(exc) or HTTPException(
                    status_code=503,
                    detail=upstream_error_detail(exc, "AI 服務金鑰無效或尚未啟用計費"),
                ) from exc
            except (APIConnectionError, APIError) as exc:
                stop = non_retryable_upstream_error(exc)
                if stop is not None:
                    raise stop from exc
                last_detail = upstream_error_detail(exc)
                print(f"[generate] attempt {attempt + 1}/{DIGEST_ATTEMPTS} API error: {exc}", flush=True)
                retry_context = digest_retry_note(
                    attempt + 1,
                    "upstream",
                    f"{type(exc).__name__} on attempt {attempt + 1}",
                )
                reasoning_effort = None
                _note_generation_retry()
                time.sleep(1.5)
                continue

            raw_content = response.choices[0].message.content or ""
            finish_reason = response.choices[0].finish_reason if response.choices else "?"
            try:
                data = parse_digest_json(raw_content)
            except (json.JSONDecodeError, IndexError, TypeError) as exc:
                last_detail = "AI 回傳格式無法解析"
                print(
                    f"[generate] attempt {attempt + 1}/{DIGEST_ATTEMPTS} parse failed "
                    f"(finish_reason={finish_reason}): {exc}\n"
                    f"[generate] raw content: {digest_excerpt(raw_content)}",
                    flush=True,
                )
                if req.density == "verbatim" and finish_reason == "length":
                    # 不消化的預算已經照原文長度放大過（digest_token_budget），還撞到
                    # length 就是這篇真的塞不下——重試每次都會撞同一面牆，5 次要燒掉
                    # 90 秒才讓使用者收到一句看不懂的「格式無法解析」。直接講清楚。
                    raise HTTPException(
                        status_code=400,
                        detail="原文太長，「不消化」要模型逐字抄完整篇才做得到；"
                        "請改用「字少」／「字多」，或把原文縮短再試。",
                    )
                retry_context = digest_retry_note(
                    attempt + 1, "parse", "JSON 解析失敗"
                )
                reasoning_effort = (
                    DIGEST_REASONING_RETRY_EFFORT
                    if finish_reason == "length"
                    else None
                )
                _note_generation_retry()
                time.sleep(1.5)
                continue

            # 能解析不代表能用：截斷與字元污染都要跟解析失敗一樣重試，不能送去生圖
            problem = digest_quality_problem(
                data,
                finish_reason,
                density=req.density,
                format_key=req.editor_format if req.role == "編輯" else None,
                news_text=req.news_text,
            )
            # B67（2026-09-16 使用者裁決）：塊數不足在第 DIGEST_POINT_COUNT_ATTEMPTS
            # 次之後不再擋。防呆分不出「模型偷懶」與「原文本來就只有三個點」——兩者
            # 長得一模一樣，硬擋到底的結果是素材單薄的稿連撞滿次數然後整條 502，
            # 使用者一張圖都拿不到。手上那張少一點的圖是完全可用的成品，不是壞資料。
            # ⚠只放行塊數這一種：截斷／型別錯／頻道洩漏／亂碼仍然擋滿 DIGEST_ATTEMPTS，
            # 所以要先確認「這次唯一的問題就是塊數」才放行（2026-08-01 實測，上游
            # 間歇脫軌的單次成功率只有約 2/3，那些是真故障不能放水）。
            if problem and attempt >= DIGEST_POINT_COUNT_ATTEMPTS - 1:
                count_problem = digest_point_count_problem(
                    data.get("variable") or "",
                    req.density,
                    req.editor_format if req.role == "編輯" else None,
                    news_text=req.news_text,
                )
                if count_problem and problem == count_problem:
                    # 塊數不足（含 B105 字少的三點下限）照 B67 放行；只有字極少超過
                    # 硬上限三點（B34 裁決）是模型不守規矩，不是素材單薄，才擋。
                    if req.density != "minimal":
                        print(
                            f"[generate] 塊數已試滿 {DIGEST_POINT_COUNT_ATTEMPTS} 次仍不足，"
                            f"放行（{problem}）",
                            flush=True,
                        )
                        problem = ""
                    else:
                        print(
                            f"[generate] 塊數已試滿 {DIGEST_POINT_COUNT_ATTEMPTS} 次仍不符，"
                            f"停止（{problem}）",
                            flush=True,
                        )
                        raise HTTPException(
                            status_code=502,
                            detail="AI 多次產出的重點數量仍不符合所選字量，請再試一次",
                        )
            # 不消化的逐字比對排在通用檢查之後：兩者都過不了時，先報通用的那個。
            # B106（2026-09-26 使用者裁決「不改文字不加文字，使用者貼的全部文字都要，
            # 但要排除參雜的指令文字」）：
            # - 最後一次**不再放行**。以前放行的理由是「通常只是頭尾雜訊」，但交出去的
            #   就是改過字的「不改字」，與承諾正面衝突；改成回一個說得出原因的錯誤。
            # - 專用指令欄有字**不再**關掉比對。以前的前提是「指令欄優先於消化程度」
            #   （「濃縮成三點」＋不改字時該縮），新裁決把不改字收緊成硬承諾，
            #   兩者衝突時改為報錯請使用者二選一，不再默默縮寫。
            if not problem and req.density == "verbatim":
                verbatim_problem = verbatim_fidelity_problem(
                    data.get("variable") or "", req.news_text
                )
                if verbatim_problem:
                    if attempt < DIGEST_ATTEMPTS - 1:
                        problem = verbatim_problem
                    else:
                        print(
                            f"[generate] 最後一次嘗試仍未逐字相符，停止：{verbatim_problem}",
                            flush=True,
                        )
                        raise HTTPException(
                            status_code=400,
                            detail=VERBATIM_MISMATCH_DETAIL,
                        )
            if problem:
                last_detail = "AI 回傳內容異常，請稍後重試"
                print(
                    f"[generate] attempt {attempt + 1}/{DIGEST_ATTEMPTS} quality check failed: {problem}",
                    flush=True,
                )
                truncated = finish_reason == "length" or "截斷" in problem
                retry_context = digest_retry_note(
                    attempt + 1,
                    "truncated" if truncated else "quality",
                    problem,
                )
                reasoning_effort = (
                    DIGEST_REASONING_RETRY_EFFORT if truncated else None
                )
                _note_generation_retry()
                time.sleep(1.5)
                continue

            chart_type = data.get("chart_type", "")
            if chart_type not in CHART_TYPE_CHOICES:
                # AI 未回報或回報不在清單內；指定類型時退回原值，自動判斷時留空由前端處理
                chart_type = "" if type_label == AUTO_TYPE_LABEL else type_label

            variable = strip_wrapping_quotes(data.get("variable", ""))
            if req.stamp is False and any(_STAMP_LINE_RE.match(line) for line in variable.splitlines()):
                if req.density == "verbatim" and editor_formats.resolve_hole_side(
                    req.editor_format, req.hole_side
                ):
                    # 播出鏡面：蓋章本來就在最底一列，直接改標成底帶。若只拿掉標記，
                    # 下面的 ensure_bottom_band_line 會把最後一張卡搬到最後，正文順序就變了。
                    print("[generate] 蓋章 OFF＋不改字＋播出鏡面：<蓋章> 改標為 <底帶>", flush=True)
                    variable = "\n".join(
                        _STAMP_LINE_RE.sub("<底帶>", line, count=1)
                        for line in variable.splitlines()
                    )
                elif req.density == "verbatim":
                    print("[generate] 蓋章 OFF＋不改字：<蓋章> 標記拿掉、正文保留", flush=True)
                    variable = unmark_stamp_lines(variable)
                else:
                    print("[generate] 蓋章 OFF 但消化結果仍有 <蓋章> 行，已強制移除", flush=True)
                    variable = drop_stamp_lines(variable)
            # 播出鏡面 ＋ 蓋章 OFF：底帶那一行沒生出來就自己補（見 ensure_bottom_band_line）
            if req.stamp is False and editor_formats.resolve_hole_side(req.editor_format, req.hole_side):
                filled = ensure_bottom_band_line(variable)
                if filled != variable:
                    print("[generate] 蓋章 OFF 但消化結果沒有 <底帶> 行，已把最後一張卡升級成底帶", flush=True)
                variable = filled
            result = GenerateResponse(
                style=data.get("style", ""),
                structure=data.get("structure", ""),
                variable=variable,
                chart_type=chart_type,
                # 只有地圖類會真的去查（resolve_map_points 自己擋掉其他類型）。
                # 查不到就是空陣列，後續一切照舊，不會有人拿到錯誤。
                map_points=resolve_map_points(chart_type, data.get("map_places")),
                map_missing=map_missing_places(),
                portrait_subjects=clean_portrait_subjects(data.get("portrait_subjects")),
                portrait_subjects_en=align_english_names(
                    clean_portrait_subjects(data.get("portrait_subjects")),
                    data.get("portrait_subjects_en"),
                    data.get("portrait_subjects"),
                ),
                portrait_subjects_en_guess=align_english_names(
                    clean_portrait_subjects(data.get("portrait_subjects")),
                    data.get("portrait_subjects_en_guess"),
                    data.get("portrait_subjects"),
                ),
                seed=seed,
            )
            # 網頁版走這個端點後自己在前端組生圖 prompt，後端看不到最終 prompt，
            # 因此這裡只記到消化為止——有輸入與消化結果，事後仍可重跑重現。
            if own_clock:
                # 網頁版的第二段消化在這裡做（LINE 走 generate_news_image 自己那條，
                # 兩邊都做會白查一次圖）。落檔放在後面，記的是最終採用的那份。
                result = apply_photo_availability(result, req)
                notices = collected_portrait_notices()
                if notices:
                    result = result.model_copy(update={"notices": notices})
                digest_meta = _outcome_meta(digest_started, image_model="")
                request_log.log_generation(
                    request_id=digest_request_id,
                    source="digest",
                    news_text=req.news_text,
                    style=result.style,
                    structure=result.structure,
                    variable=result.variable,
                    chart_type=result.chart_type,
                    type_label=req.type_label,
                    role=req.role,
                    density=req.density,
                    seed=seed,
                    digest_model=model,
                )
                # B72／F31（2026-09-20）：消化階段自己也要進 audit_archive，不能只靠
                # request_log 的 JSONL——後台 `/admin` 只讀 audit_archive，這裡沒寫，
                # 消化階段的成功次數（分母）就永遠是 0，跟失敗次數一起被後台漏看。
                # 沒有圖可帶（網頁版消化完才在前端組 prompt），_archive_generation
                # 對沒有 image_base64 的呼叫會略過 GCS 那份（見該函式說明），
                # 只寫本機的稽核歸檔。
                _archive_generation(
                    request_id=digest_request_id,
                    source="digest",
                    news_text=req.news_text,
                    style=result.style,
                    structure=result.structure,
                    variable=result.variable,
                    chart_type=result.chart_type,
                    type_label=req.type_label,
                    role=req.role,
                    density=req.density,
                    seed=seed,
                    **digest_meta,
                )
                # 存給稍後的生圖請求取用：那支端點只收到 prompt，拿不到新聞原文，
                # 稽核歸檔要靠這裡記住的內容才補得齊（見 _archive_generation）。
                _remember_digest(
                    news_text=req.news_text,
                    style=result.style,
                    structure=result.structure,
                    variable=result.variable,
                    chart_type=result.chart_type,
                    type_label=req.type_label,
                    role=req.role,
                    density=req.density,
                    digest_model=model,
                )
            return result

        raise HTTPException(status_code=502, detail=last_detail)
    except BaseException as exc:
        # B72／F31（2026-09-20）：這裡涵蓋整個重試迴圈，包含 apply_photo_availability
        # 巢狀呼叫 generate() 再往外傳的例外（它自己的 try/finally 只重置
        # _inside_pipeline，不吞例外）——這是消化階段目前唯一會失敗的路徑，
        # 全部在這裡截下來記一筆，不必在每個 raise HTTPException 旁邊各補一次。
        if own_clock:
            _record_generation_failure(
                digest_request_id, digest_started, exc,
                source="digest", news_text=req.news_text,
                role=req.role, density=req.density, type_label=req.type_label,
                seed=seed,
            )
        raise
    finally:
        if deadline_token is not None:
            _digest_deadline.reset(deadline_token)


# B39（2026-09-15）：公司 Cloudflare 的 proxy timeout 不能調，實測約 100～120 秒
# 就會對「一個位元組都沒回」的連線送 524，遠比 DIGEST_DEADLINE_SECONDS=230 短。
# 524 的定義是源站在時限內完全沒回應——連線上只要持續有位元組流動就不會觸發，
# 所以不必讓 generate() 跑得更快，只要別讓連線在消化期間看起來像斷線。
# 心跳間隔取 5～10 秒中段：夠短能穩穩躲過 CF 的切線，也不會為了心跳白費頻寬。
DIGEST_HEARTBEAT_SECONDS = 7


def _generate_ndjson_lines(req: GenerateRequest, ctx: contextvars.Context):
    """背景執行緒跑 generate()（可能長達 DIGEST_DEADLINE_SECONDS 秒），
    主執行緒每隔 DIGEST_HEARTBEAT_SECONDS 送一行 ping 讓連線看起來活著；
    結束送一行 result 或 error，兩者都是這個 generator 的最後一行。

    ⚠ HTTP 狀態碼在第一個位元組送出後就定死是 200，這裡送出第一行 ping 或
    result／error 之後就再也不能改成別的狀態碼了——所有成敗都編在內容裡，
    前端要看這裡送出的 type 欄位判斷，不能看 response.ok（見 app.js _digestFetch）。

    ctx：呼叫端在還沒離開 Clerk middleware 的 context 時複製好的
    contextvars.Context（見 generate_stream）。threading.Thread 起於一個
    全新的空 context，不會自動帶著 _current_user 這類 contextvar——改之前
    generate() 是跑在 Starlette 用 anyio to_thread.run_sync 開的執行緒，
    那條路徑會複製 context，才會一直「湊巧」拿得到登入身分；換成自己開
    thread 之後若不手動複製，current_user() 在背景執行緒裡會是空字典，
    generate() 尾端 _remember_digest() 第一行就 return，稽核歸檔悄悄漏記
    新聞原文，跟 0911 查到的「後台缺欄位」是同一類缺陷。
    """
    outcome: dict = {}

    def worker():
        try:
            outcome["result"] = generate(req)
        except HTTPException as exc:
            outcome["error"] = (exc.status_code, exc.detail)
        except Exception as exc:  # noqa: BLE001 — 背景執行緒的例外不能悶掉，否則連線會卡死到 fetch 逾時都沒有提示
            print(f"[generate-stream] 未預期的例外：{exc}", flush=True)
            outcome["error"] = (500, "AI 服務處理失敗，請確認模型權限或稍後重試")

    thread = threading.Thread(target=ctx.run, args=(worker,), daemon=True)
    thread.start()
    while thread.is_alive():
        thread.join(timeout=DIGEST_HEARTBEAT_SECONDS)
        if thread.is_alive():
            yield json.dumps({"type": "ping"}) + "\n"
    if "error" in outcome:
        status, detail = outcome["error"]
        yield json.dumps({"type": "error", "status": status, "detail": detail}, ensure_ascii=False) + "\n"
    else:
        payload = {"type": "result", **outcome["result"].model_dump(mode="json")}
        yield json.dumps(payload, ensure_ascii=False) + "\n"


@app.post("/api/generate", dependencies=[Depends(verify_internal_api_key)])
def generate_stream(req: GenerateRequest):
    # ⚠ 一定要在這裡複製——這裡還在 Clerk middleware 的 context 內
    # （_current_user 已經 set 好）。StreamingResponse 的 body 是 middleware
    # 的 finally 跑完（_current_user 已 reset）之後才被消耗的，複製寫在
    # generator 函式體裡就太晚了，見 _generate_ndjson_lines 的說明。
    ctx = contextvars.copy_context()
    return StreamingResponse(_generate_ndjson_lines(req, ctx), media_type="application/x-ndjson")


# ---- 混合版型：新聞原文 → 結構化內容（文字數字由 APP 繪製，AI 不碰像素文字）----

class HybridDigestRequest(BaseModel):
    news_text: str = Field(min_length=1, max_length=20_000)


class HybridItem(BaseModel):
    label: str
    value: str
    change: str
    direction: Literal["up", "down", "flat"]


class HybridDigestResponse(BaseModel):
    title: str
    # 標題裡要上色的關鍵詞。AI 只指出「哪個詞是重點」，配色由前端決定——
    # 與「AI 不得產生座標」同一原則：語意歸 AI，視覺歸 APP
    title_key: str = ""
    subtitle: str
    items: list[HybridItem]
    source: str
    visual_subject: str


HYBRID_DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "title_key": {"type": "string"},
        "subtitle": {"type": "string"},
        # Anthropic 結構化輸出不支援 minItems/maxItems（0/1 除外），
        # 「恰好 3 項」由 system prompt 要求＋端點內正規化保證
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "change": {"type": "string"},
                    "direction": {"type": "string", "enum": ["up", "down", "flat"]},
                },
                "required": ["label", "value", "change", "direction"],
                "additionalProperties": False,
            },
        },
        "source": {"type": "string"},
        "visual_subject": {"type": "string"},
    },
    "required": [
        "title",
        "title_key",
        "subtitle",
        "items",
        "source",
        "visual_subject",
    ],
    "additionalProperties": False,
}

HYBRID_SYSTEM_PROMPT = """You are a Taiwanese TV news graphics editor. Digest the news material into structured data for a fixed-layout 3-column comparison news card. The APP renders all text itself, so your output IS the on-screen text — accuracy is everything.

Rules:
- All text in Traditional Chinese (Taiwan standard, 台灣慣用語). NEVER Simplified Chinese. Keep proper nouns customarily shown in original language as-is (e.g. NASDAQ, S&P 500, B-1).
- title: 電視新聞主標題, punchy, at most 12 full-width characters, no punctuation.
- title_key: the single focal word inside title that deserves visual emphasis, 2-4 full-width characters (e.g. title 美國臨時關稅將到期 → title_key 關稅; title 美股三大指數收黑 → title_key 收黑). It MUST be copied verbatim from title as an exact substring — never rephrase it, never wrap it in brackets or any markup. Empty string if the title has no single focal word.
- subtitle: 補充副標（時間、範圍等）, at most 12 full-width characters; empty string if nothing suitable.
- items: EXACTLY 3 key data points, the most newsworthy numbers in the material.
  - label: at most 6 full-width characters.
  - value: the number with its unit (e.g. 44,023.29 / 3.2萬人 / 24枚). Numbers must come from the source material — NEVER invent or estimate missing figures.
  - change: magnitude of change without any arrow symbol (e.g. 0.98% / 267點); empty string when not applicable.
  - direction: up = 上漲/上升/增加, down = 下跌/下降/減少, flat = 持平或無漲跌方向.
- Convert units for Taiwan audience when needed: currency to 新台幣或美元, °F to °C, miles to 公里.
- source: data source line formatted like 資料來源：Reuters, from the material; empty string if unknown.
- visual_subject: one Traditional Chinese sentence describing a TEXT-FREE background scene for the card (place, mood, lighting; dark navy broadcast tone preferred). Describe imagery only — never mention any text, numbers or logos."""


@app.post(
    "/api/hybrid/digest",
    response_model=HybridDigestResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
def hybrid_digest(req: HybridDigestRequest):
    model = resolve_digest_model()
    request_id = request_log.new_request_id()
    started = _generation_clock()
    _reset_generation_retries()
    # 一鍵成圖是無人值守流程：上游偶發失敗（provider 輪替錯誤、輸出截斷、
    # 不合 schema 的回傳）都必須在後端自動吸收重試，不能丟回給外勤記者
    last_detail = "AI 服務處理失敗，請確認模型權限或稍後重試"
    try:
        for attempt in range(3):
            try:
                response = digest_completion(
                    model=model,
                    system_prompt=HYBRID_SYSTEM_PROMPT,
                    news_text=req.news_text,
                    # 2026-09-05：思考 token 算進同一個上限，而它的變異遠大於
                    # 正文（同日量測 560-3140）。實測這條路徑只用 493（294 是
                    # 思考），但 1200 擋不住一次思考尖峰，留到 3000。
                    # 上限是天花板不是用量，只有真的寫出來的 token 才計費。
                    max_output_tokens=3000,
                    schema_name="hybrid_card_digest",
                    schema=HYBRID_DIGEST_SCHEMA,
                    site="hybrid",
                )
            except AuthenticationError as exc:
                raise non_retryable_upstream_error(exc) or HTTPException(
                    status_code=503,
                    detail=upstream_error_detail(exc, "AI 服務金鑰無效或尚未啟用計費"),
                ) from exc
            except (APIConnectionError, APIError) as exc:
                stop = non_retryable_upstream_error(exc)
                if stop is not None:
                    raise stop from exc
                last_detail = upstream_error_detail(exc)
                print(f"[hybrid] attempt {attempt + 1}/3 API error: {exc}", flush=True)
                _note_generation_retry()
                time.sleep(1.5)
                continue

            raw_content = response.choices[0].message.content or ""
            finish_reason = response.choices[0].finish_reason if response.choices else "?"
            try:
                data = parse_digest_json(raw_content)
                items = data.get("items") or []
                if len(items) > 3:
                    items = items[:3]
                while len(items) < 3:
                    items.append(
                        {"label": "", "value": "", "change": "", "direction": "flat"}
                    )
                data["items"] = items
                # 模型偶爾會改寫或加標記，導致 key 不是 title 的子字串；
                # 前端靠字串比對定位上色，對不上就整條標題失去強調，故此處直接丟棄
                key = (data.get("title_key") or "").strip()
                data["title_key"] = key if key and key in (data.get("title") or "") else ""
                result = HybridDigestResponse(**data)
                meta = _outcome_meta(started, image_model="")
                request_log.log_generation(
                    request_id=request_id, source="hybrid-digest",
                    news_text=req.news_text, variable=result.title,
                    digest_model=meta["digest_model"],
                )
                _archive_generation(
                    request_id=request_id, source="hybrid-digest",
                    news_text=req.news_text, variable=result.title,
                    **meta,
                )
                return result
            except (json.JSONDecodeError, IndexError, TypeError, ValueError) as exc:
                last_detail = "AI 回傳格式無法解析"
                print(
                    f"[hybrid] attempt {attempt + 1}/3 parse failed "
                    f"(finish_reason={finish_reason}): {exc}\n"
                    f"[hybrid] raw content: {digest_excerpt(raw_content)}",
                    flush=True,
                )
                _note_generation_retry()
                time.sleep(1.5)

        raise HTTPException(status_code=502, detail=last_detail)
    except BaseException as exc:
        # B72／F31（2026-09-20）：跟 generate() 同一個根因——一鍵成圖這條消化路徑
        # 以前完全沒有失敗落檔，`/api/hybrid/digest` 的 502／逾時在後台一筆都查不到。
        _record_generation_failure(
            request_id, started, exc,
            source="hybrid-digest", news_text=req.news_text,
        )
        raise


@app.post(
    "/api/images/generate",
    response_model=ImageGenerateResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
def generate_image(req: ImageGenerateRequest):
    """Generate one news CG image without exposing provider API keys.

    IMAGE_BACKEND=openrouter（預設）時，兩家都改走 OpenRouter：
    GPT 用 OPENROUTER_GPT_MODEL、Gemini 用 OPENROUTER_GEMINI_MODEL。
    設 IMAGE_BACKEND=native 可切回原生 OpenAI / Gemini 直連。

    req.safe_frame=True 時，生成後再由 safe_frame 置入 TVBS 安全框。
    網頁版可帶 portrait_subjects，在這裡查參考照並注入肖像規則。
    generate_news_image 已組好 prompt，走這支時不要重複落檔。
    """
    own_notices = not _inside_pipeline.get()
    if own_notices:
        reset_portrait_notices()
    req = apply_portrait_to_image_request(req)
    # 順序有意義：自動底圖要先加進 reference_images，下一行才會替它注入
    # ATTACHED MAP REFERENCE 那段用途規則（「標點已在真實位置，不要移動」）。
    req = apply_map_reference_to_image_request(req)
    req = apply_user_references_to_image_request(req)
    # B110：一定壓在 asis／aiedit 用途規則之後，才能覆蓋「主視覺／延伸裁切」等語意。
    req = apply_broadcast_hole_layout_to_image_request(req)
    # F48：留空提示跟著使用者選的標籤位置走（右下＝預設時 prompt 逐字不變）
    localised = localise_disclaimer_position(
        req.prompt, req.disclaimer_corner,
        stamping=bool(req.disclaimer_kind) and not req.broadcast_hole,
    )
    if localised != req.prompt:
        req = req.model_copy(update={"prompt": localised})
    _, output_canvas = image_generation_size(req)
    request_id = request_log.new_request_id()
    own_clock = not _inside_pipeline.get()
    started = _generation_clock() if own_clock else 0.0
    if own_clock:
        _reset_generation_retries()
    try:
        # safe_frame_profile 帶的是「角色」，實際要用哪個框在這裡才決定——
        # 全系統只有這一個解析點，pipeline 與網頁版直呼都會經過。
        _, needs_frame, frame_profile = resolve_frame_plan(
            req.safe_frame_profile, req.safe_frame, req.density
        )
        if model_extension_active(
            req.safe_frame_profile, req.safe_frame, req.frame_strategy
        ) and not req.broadcast_hole:
            result = finalize_model_extension(
                generate_image_raw(req),
                aspect_ratio=req.aspect_ratio,
                canvas=output_canvas,
                allow_no_text=req.density == "no_text",
            )
        else:
            result = finalize_image_result(
                generate_image_raw(req),
                aspect_ratio=req.aspect_ratio,
                safe_frame=needs_frame,
                profile=frame_profile,
                broadcast_hole=req.broadcast_hole,
                canvas=output_canvas,
            )
        # B70／F43：置框、挖空框都處理完後最後貼「示意圖」／「畫面來源」標籤。
        # 播出鏡面挖空框已經在同一套安全區角落自己貼過一次「示意圖」浮水印
        # （compose.apply_broadcast_hole／compose.WATERMARK_TEXT），這裡不重貼第二次
        # ——兩者文案（「示意圖」vs 這裡固定的 PORTRAIT_DISCLAIMER_TEXT，剛好同一個字）
        # 目前相同所以不會互相矛盾，但角落與樣式是兩套獨立實作，之後要合併是後續工作。
        if req.disclaimer_kind and not req.broadcast_hole:
            result = apply_image_disclaimer(result, req, profile=frame_profile)
    except Exception as exc:
        if own_clock:
            _record_generation_failure(
                request_id, started, exc,
                source="web-image", news_text="", prompt=req.prompt,
                provider=req.provider,
            )
        raise
    if own_clock:
        meta = _outcome_meta(started, provider=req.provider, image_model=result.model)
        request_log.log_generation(
            request_id=request_id,
            source="web-image",
            news_text="",
            prompt=req.prompt,
            provider=req.provider,
            image_model=result.model,
            digest_model=meta["digest_model"],
        )
        _archive_generation(
            request_id=request_id,
            image_base64=result.image_data_base64,
            mime_type=result.mime_type,
            source="web-image",
            prompt=req.prompt,
            **meta,
        )
    if own_notices:
        notices = collected_portrait_notices()
        if notices:
            result = result.model_copy(update={"notices": notices})
    return result


# 生成端不保證給到小數點精確的比例（21:9 可能回 1808x768＝2.354），所以要留容差；
# 但真正要抓的降級差很遠（3:2＝1.50 vs 21:9＝2.33，差 36%），5% 分得非常開。
ASPECT_RATIO_TOLERANCE = 0.05


def parse_aspect_ratio(aspect_ratio: str) -> float | None:
    """'21:9' → 2.33。不是 W:H 形式（例如 auto）就回 None，代表沒有可驗的目標。"""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*", aspect_ratio or "")
    if not match:
        return None
    width, height = float(match.group(1)), float(match.group(2))
    if width <= 0 or height <= 0:
        return None
    return width / height


def verify_output_aspect_ratio(result: ImageGenerateResponse, aspect_ratio: str) -> None:
    """成圖比例與要求不符就當場失敗，不讓它默默播出去。

    存在理由：`assert_aspect_ratio_supported` 只擋得住「模型宣告不支援」，擋不住
    「宣告支援卻回別的尺寸」。2026-08-01 附參考圖的兩張 21:9 回來是 3:2，模型與
    參數都合法；2026-08-03 同樣條件（同一人、同一張參考照、同一模型、同一份 prompt）
    又完全正常，三次全對。這種**間歇性**降級只有量成圖才抓得到。
    整條安全框流程都建立在「要到的比例真的拿得到」上，悄悄降級的圖會直接上鏡。

    刻意不自動重試：生圖是付費的，靜靜多花一次錢不該由這裡決定。失敗訊息會明講
    可以重試。
    """
    expected = parse_aspect_ratio(aspect_ratio)
    if expected is None:
        return

    try:
        with Image.open(io.BytesIO(base64.b64decode(result.image_data_base64))) as image:
            width, height = image.size
    except Exception as exc:  # noqa: BLE001 — 讀不出尺寸就無從驗證，必須讓呼叫端知道
        raise HTTPException(
            status_code=502, detail=f"成圖無法解析，無法驗證比例：{type(exc).__name__}: {exc}"
        ) from exc

    if height <= 0:
        raise HTTPException(status_code=502, detail="成圖高度為 0，無法驗證比例")

    actual = width / height
    if abs(actual - expected) / expected <= ASPECT_RATIO_TOLERANCE:
        return

    print(
        f"[aspect] 比例不符：要求 {aspect_ratio} 實得 {width}x{height} "
        f"({actual:.2f}:1) model={result.model}",
        flush=True,
    )
    raise HTTPException(
        status_code=502,
        detail=(
            f"生成端回傳的比例不符：要求 {aspect_ratio}（{expected:.2f}:1），"
            f"實得 {width}x{height}（{actual:.2f}:1），模型 {result.model}。"
            "這種降級是間歇性的，重試一次通常就正常；若持續發生請換模型或引擎。"
        ),
    )


def _split_data_url(data_url: str) -> tuple[str, str, str]:
    """拆 data URL，回傳 (mime_type, 編碼方式, base64 內容)；格式不對回空內容。"""
    if not data_url.startswith("data:"):
        return "", "", ""
    header, _, encoded = data_url.partition(",")
    if not encoded:
        return "", "", ""
    meta = header[len("data:") :]
    mime_type, _, encoding = meta.partition(";")
    return mime_type or "image/jpeg", encoding, encoded


def decode_attached_image(data_url: str, *, what: str = "附圖") -> bytes:
    """附圖 data URL → 原始 bytes，並保證 PIL 開得起來；壞的一律 400。

    2026-09-14 抓 bug 輪：text/plain 或 base64 壞掉的 data URL 以前一路走到
    compose 的 Image.open 才炸 UnidentifiedImageError，對外是 500。使用者貼錯檔
    是輸入問題，要在入口就用 400 講清楚。
    """
    _, _, encoded = _split_data_url(data_url)
    if not encoded:
        raise HTTPException(status_code=400, detail=f"{what}格式不對（不是 data URL）")
    try:
        raw = base64.b64decode(encoded)
    except Exception:  # noqa: BLE001 — 任何解碼失敗都是輸入壞掉
        raise HTTPException(status_code=400, detail=f"{what}的 base64 內容壞了，請重新上傳")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.verify()
    except Exception:  # noqa: BLE001 — PIL 認不得就是不是圖
        raise HTTPException(
            status_code=400, detail=f"{what}不是可讀的圖片檔（支援 JPEG／PNG／WebP），請重新上傳"
        )
    return raw


def using_openrouter_images() -> bool:
    """這次生圖實際會不會走 OpenRouter——判斷式與 `generate_image_raw` 完全同源。

    2026-09-16 抽出來的（B65）。在此之前底下三支能力函式各自寫一份 `os.getenv`
    判斷，寫法還互不相同：`supports_map_basemap` 是「非 openrouter 就看 provider」、
    `supports_multiple_reference_images` 只認字面上的 `"openai"`、
    `supports_reference_image` 又是第三種。於是同一次請求會出現
    **「路由說走原生 GPT、能力判斷說送不出參考圖」這種自相矛盾**。

    實際踩到的那次：`dev-local-openai.sh` 設的是 `IMAGE_BACKEND=native`
    （不是 `openai`），多張判斷因此回 False，肖像參考照被整批丟掉、真人題全部
    退回背影——log 為證 `portrait_subjects=['華許'] … 參考照=0 張`，而維基那張
    官方肖像其實查得到。

    所以能力判斷一律以「這次會走哪條後端」為準，不要再各自解讀環境變數的拼法：
    `generate_image_raw` 的規則是「`openrouter` 且有 key 才走 OpenRouter，
    其餘一律走原生」，這支就是那一句。
    """
    return os.getenv("IMAGE_BACKEND", "openrouter") == "openrouter" and bool(
        os.getenv("OPENROUTER_API_KEY")
    )


def supports_map_basemap(provider: str) -> bool:
    """這次的路徑能不能把真實地圖底圖送進生圖模型。

    2026-09-10 決定性實測：同一份 4000 字元的地圖 prompt，只差有沒有附底圖——
    無底圖時澎湖被畫到臺灣北方，附底圖時全部就位。座標寫在文字裡模型當參考，
    座標畫成圖釘在畫面上模型才照著擺（與 safe_frame.py 同一條原則）。

    所以底圖不能只在 OpenRouter 那條路才附：原生 OpenAI 走 images.edit 一樣送得出去
    （generate_gpt_image 依 reference_images 自動改走 edit 端點）。
    刻意與 supports_multiple_reference_images() 分開一支：那條同時管肖像參考照，
    順手放寬會連多人肖像的行為一起改掉，不在這次的範圍內。
    """
    if using_openrouter_images():
        return True
    return provider == "gpt"


def supports_reference_image(provider: str) -> bool:
    """這次的生圖後端能不能真的把參考圖送出去（單張就算數）。

    存在理由：附圖能力與 prompt 措辭必須一致。送不出去卻照樣叫模型「參考附圖」，
    模型只能憑印象捏一張臉——比不提附圖更糟。所以送不出去時，呼叫端要改用
    「不生成臉孔」的規則。

    🔻**2026-09-16 更正（B64）**：原本的實作是 `return provider != "gpt"`，理由寫著
    「原生 OpenAI 的 images.generate 沒有參考圖通道」。**那句話在 2026-09-10 之後
    就不成立了**——`generate_gpt_image` 只要 `_native_reference_files` 拿得到圖
    就改走 `images.edit`，送的是 `reference_image_data_url` 加上整個
    `reference_images` 陣列。2026-09-13 的 b70f89d 修了多張那一支，**單張這支
    沒跟著修**，於是本機切原生後端時，查到的肖像參考照會被 `resolve_portraits`
    當成「送不出去」整批丟掉，真人題一律退回背影。實測 log：
    `[yt-cover:ai-title] portrait_subjects=['華許'] en=['Kevin Warsh'] 參考照=0 張`。

    現況四種組合都送得出單張：OpenRouter 兩家都行；原生 GPT 走 images.edit；
    原生 Gemini 把 `reference_image_data_url` 塞進 content（generate_gemini_image）。
    **多張**是另一回事，看 supports_multiple_reference_images。

    刻意不寫成 `return True`：呼叫端要的是「能力與措辭一致」這個語意，日後真的
    接上送不出參考圖的後端時，改這裡一處就好。
    """
    if using_openrouter_images():
        return True
    # 原生兩家都送得出單張（GPT 走 images.edit、Gemini 走 content 內嵌）
    return provider in ("gpt", "gemini")


def supports_multiple_reference_images(provider: str | None = None) -> bool:
    """多張參考圖（reference_images 陣列）這條路送不送得出去。

    存在理由：supports_reference_image() 對原生 Gemini 回 True，但那條只送得出
    單張 reference_image_data_url——若拿它當放行條件，使用者上傳的
    reference_images 會被靜默丟掉、prompt 卻已寫著「依附圖」，正是
    「叫模型參考不存在的附圖」這個最糟情境。判斷必須用這支。

    2026-09-13：原生 GPT 放行。2026-09-10 起 generate_gpt_image 有參考圖就改走
    images.edit，_native_reference_files 送的是整個 reference_images 陣列。
    原生 Gemini 仍只送單張，維持 False。provider 不給時視為 gpt（舊呼叫端相容）。

    🔻**2026-09-16 更正（B65）**：原本用 `backend == "openai"` 認原生，但
    `generate_image_raw` 的路由是「非 openrouter 一律原生」，`IMAGE_BACKEND=native`
    （dev-local-openai.sh 用的正是這個拼法）因此掉進最後那個 `return False`。
    改讀 using_openrouter_images() 之後，能力判斷與實際路由不會再分岔。
    """
    if using_openrouter_images():
        return True
    return (provider or "gpt") == "gpt"


# 一家一個模型，OpenRouter 與原生兩條路徑共用同一個——否則切 IMAGE_BACKEND 會連模型一起
# 換掉，而兩個模型的能力並不相同（2026-08-01 清查：OpenRouter 那條原本是 gpt-5.4-image-2、
# 原生那條是 gpt-image-2，文件卻只寫後者）。
# GPT 選 gpt-image-2.5-sunburst 的理由（2026-09-10 使用者裁決，兩輪本機實打對照）：
# 對 gpt-image-2 同 prompt／同 21:9／同 quality=medium，畫質更好（稻穗有結構、金屬有質感，
# gpt-image-2 右半糊成一片）、快約 2 倍（12.9s vs 28.5s）、便宜約 4 倍（193 vs 809 輸出 tokens，
# 單價同為 $30/1M），中文字兩者都全對。安全框要的 21:9 有支援，參考圖上限一樣是 16 張。
# 對照圖：D:\Downloads\20260910-2.5對照*.png。
# 不選 flare 的理由：同價同 tokens，但細節較軟——沒有理由買便宜貨當預設。
# 仍不選 gpt-5.4-image-2 / gpt-5-image 系列：連 aspect_ratio 參數都沒有。
NATIVE_GPT_IMAGE_MODEL = "gpt-image-2.5-sunburst"
NATIVE_GEMINI_IMAGE_MODEL = "gemini-3-pro-image"
# 2026-09-10 線上事故與其根因（實打定位，不是推測）：
# OpenRouter 的 aspect_ratio → OpenAI size 正規化**沒有套用到 GPT Image 2.5 系列**，
# aspect_ratio 被整個丟掉，落回 OpenAI 預設的 1536x1024（3:2）。
# verify_output_aspect_ratio 當場擋下來回 502＝網頁版所有 GPT 生圖全掛。
#
#   只給 aspect_ratio     sunburst 16:9 / 21:9、flare 16:9 → 全部 1536x1024   ✗
#   只給 size             sunburst 1536x864 / 1680x720 / 1280x720、flare → 全對 ✓
#   size + aspect_ratio   以 size 為準，正確                                   ✓
#   size + 參考圖 1 張     1536x864，正確                                      ✓
#   對照組 gpt-image-2 只給 aspect_ratio 16:9 → 1536x864，正常
#
# 所以解法不是退回 2（那會白白丟掉快一倍、便宜四倍、畫質更好），而是**自己送 size**：
# 見 _openrouter_gpt_size。size 這條路 21:9 與參考圖都對，兩條傳輸層從此做法一致
# （原生本來就是送 size）。
# 注意 size **不在** OpenRouter images/models 宣告的參數清單裡，屬未公開行為；
# 真的哪天被拿掉，verify_output_aspect_ratio 會照樣當場擋下來，不會默默出錯比例的圖。
OPENROUTER_GPT_IMAGE_MODEL = f"openai/{NATIVE_GPT_IMAGE_MODEL}"
OPENROUTER_GEMINI_IMAGE_MODEL = f"google/{NATIVE_GEMINI_IMAGE_MODEL}"

# 各模型在 API 層支援的 aspect_ratio。
# 來源：GET https://openrouter.ai/api/v1/images/models（2026-08-01 取得，含 enum 值）。
# 存在理由：帶了不支援的參數，OpenRouter 不會報錯也不會警告，就是靜靜忽略——
# 2026-08-01 的 21:9 悄悄掉成 3:2 查了整晚，根因就是這個。做不到的比例必須當場擋下來，
# 因為整條安全框流程都建立在「要到的比例真的拿得到」這個假設上。
_RATIOS_OPENAI_FULL = frozenset(
    {"1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16", "21:9", "auto"}
)
_RATIOS_OPENAI_LEGACY = frozenset({"1:1", "3:2", "2:3", "auto"})
_RATIOS_GEMINI = frozenset(
    {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
)
_RATIOS_GEMINI_FLASH_31 = _RATIOS_GEMINI | {"1:4", "1:8", "4:1", "8:1"}
_RATIOS_WIDE_STANDARD = frozenset(
    {"1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "21:9", "auto"}
)

MODEL_ASPECT_RATIOS: dict[str, frozenset[str]] = {
    # GPT Image 2.5（2026-09-08 上架）：sunburst 精準向、flare 速度向，
    # aspect_ratio enum 與 gpt-image-2 相同（2026-09-10 向 OpenRouter images/models 端點查證）。
    # 注意這裡登記的是**宣告值**，而 2.5 系列在 OpenRouter 上並不真的照著做：
    # aspect_ratio 會被整個丟掉。所以那條路額外送明確的 size 才拿得到這些比例，
    # 見上面 OPENROUTER_GPT_IMAGE_MODEL 的註解與 _openrouter_gpt_size。
    "openai/gpt-image-2.5-sunburst": _RATIOS_OPENAI_FULL,
    "openai/gpt-image-2.5-flare": _RATIOS_OPENAI_FULL,
    "openai/gpt-image-2": _RATIOS_OPENAI_FULL,
    "openai/gpt-image-1": _RATIOS_OPENAI_LEGACY,
    "openai/gpt-image-1-mini": _RATIOS_OPENAI_LEGACY,
    # GPT-5 影像系列沒有 aspect_ratio 參數，比例只能靠 prompt 內文碰運氣。
    "openai/gpt-5-image": frozenset(),
    "openai/gpt-5-image-mini": frozenset(),
    "openai/gpt-5.4-image-2": frozenset(),
    "google/gemini-2.5-flash-image": _RATIOS_GEMINI,
    "google/gemini-3-pro-image": _RATIOS_GEMINI,
    "google/gemini-3-pro-image-preview": _RATIOS_GEMINI,
    "google/gemini-3.1-flash-image": _RATIOS_GEMINI_FLASH_31,
    "google/gemini-3.1-flash-image-preview": _RATIOS_GEMINI_FLASH_31,
    "google/gemini-3.1-flash-lite-image": _RATIOS_GEMINI_FLASH_31,
    "black-forest-labs/flux.2-pro": _RATIOS_WIDE_STANDARD,
    "black-forest-labs/flux.2-max": _RATIOS_WIDE_STANDARD,
    "black-forest-labs/flux.2-flex": _RATIOS_WIDE_STANDARD,
    "black-forest-labs/flux.2-klein-4b": _RATIOS_WIDE_STANDARD,
    "sourceful/riverflow-v2-pro": _RATIOS_WIDE_STANDARD,
    "sourceful/riverflow-v2-fast": _RATIOS_WIDE_STANDARD,
    "sourceful/riverflow-v2.5-pro": _RATIOS_WIDE_STANDARD,
    "sourceful/riverflow-v2.5-fast": _RATIOS_WIDE_STANDARD,
}


def _openrouter_gpt_size(
    model: str, aspect_ratio: str, resolved_size: str | None = None
) -> str | None:
    """OpenRouter 上的 GPT Image 系列要送明確的 size，不能只靠 aspect_ratio。

    2026-09-10 實打：GPT Image 2.5（sunburst／flare）在 OpenRouter 上會把 aspect_ratio
    整個丟掉，落回 1536x1024；同一支腳本只改成送 size 就完全正確，21:9 與帶參考圖都對。
    gpt-image-2 兩種都吃，一起送不會有壞處，所以整個 openai/gpt-image 系列統一送 size。
    尺寸沿用原生那張表，兩條傳輸層拿到的畫素完全一樣。
    """
    if not model.startswith("openai/gpt-image"):
        return None
    if resolved_size is not None:
        return resolved_size
    return NATIVE_GPT_IMAGE_SIZES.get(aspect_ratio)


def assert_aspect_ratio_supported(model: str, aspect_ratio: str) -> None:
    """模型做不到要求的比例就當場擋下，不讓它靜靜降級成別的尺寸。

    表上沒有的模型只警告不擋——不確定不等於不支援，擋下來會誤傷新模型。
    真的要用做不到的組合，設 ALLOW_UNSUPPORTED_ASPECT_RATIO=1 明示放行。
    """
    supported = MODEL_ASPECT_RATIOS.get(model)
    if supported is None:
        print(
            f"[OpenRouter image] 未知模型 {model!r}，無法確認是否支援 "
            f"aspect_ratio={aspect_ratio!r}，照送不擋",
            flush=True,
        )
        return
    if aspect_ratio in supported:
        return

    available = "、".join(sorted(supported)) if supported else "（此模型沒有 aspect_ratio 參數）"
    message = (
        f"模型 {model} 不支援 aspect_ratio={aspect_ratio}，"
        f"送出去只會被靜靜忽略、拿回別的尺寸。可用值：{available}。"
        f"請改用支援的模型（安全框需要 21:9，OpenAI 家族只有 {OPENROUTER_GPT_IMAGE_MODEL} 支援），"
        f"或設 ALLOW_UNSUPPORTED_ASPECT_RATIO=1 明示接受任何尺寸。"
    )
    if os.getenv("ALLOW_UNSUPPORTED_ASPECT_RATIO", "").strip() == "1":
        print(f"[OpenRouter image] {message}（已由環境變數放行）", flush=True)
        return
    raise HTTPException(status_code=400, detail=message)


def generate_image_raw(req: ImageGenerateRequest) -> ImageGenerateResponse:
    # B61／B62：唯一強制層。copy 再注入，不 mutate 呼叫端物件（retry／稽核
    # 會再讀原 prompt）。冪等靠 FINAL_IMAGE_BASELINE_MARKER，不是模糊 substring。
    req = req.model_copy(
        update={"prompt": ensure_final_image_baseline(req.prompt)}
    )
    backend = os.getenv("IMAGE_BACKEND", "openrouter")
    if backend == "openrouter" and os.getenv("OPENROUTER_API_KEY"):
        if req.provider == "gpt":
            model = os.getenv("OPENROUTER_GPT_MODEL", OPENROUTER_GPT_IMAGE_MODEL)
        else:
            model = os.getenv("OPENROUTER_GEMINI_MODEL", OPENROUTER_GEMINI_IMAGE_MODEL)
        return generate_via_openrouter(model, req)

    if req.provider == "gpt":
        return generate_gpt_image(req)

    return generate_gemini_image(req)


def frame_image_response(
    result: ImageGenerateResponse,
    profile: str = "記者",
    *,
    canvas: tuple[int, int] = safe_area_spec.BASE_CANVAS,
) -> ImageGenerateResponse:
    """把回傳圖置入安全框。

    置框失敗就整支失敗，不默默回傳沒置框的圖——呼叫端要的是「保證合格」，
    悄悄降級成不合格的圖會直接播出去。
    """
    # 背景做法預設 backdrop（2026-07-30 使用者實圖對照後選定）。
    # SAFE_FRAME_BACKGROUND 可切成 clamp（無縫邊緣延伸）或 blur（舊做法）。
    background = os.getenv("SAFE_FRAME_BACKGROUND", safe_frame.DEFAULT_BACKGROUND).strip()
    if background not in safe_frame.BACKGROUNDS:
        print(
            f"[safe_frame] SAFE_FRAME_BACKGROUND={background!r} 不是可用值，"
            f"改用預設 {safe_frame.DEFAULT_BACKGROUND}",
            flush=True,
        )
        background = safe_frame.DEFAULT_BACKGROUND

    try:
        framed = safe_frame.apply_safe_frame(
            base64.b64decode(result.image_data_base64),
            background=background,
            profile=profile,
            canvas=canvas,
        )
    except Exception as exc:  # noqa: BLE001 — 任何影像處理失敗都必須讓呼叫端知道
        print(f"[safe_frame] 置框失敗：{type(exc).__name__}: {exc}", flush=True)
        raise HTTPException(
            status_code=500,
            detail=f"安全框置框失敗：{exc}",
        ) from exc

    return ImageGenerateResponse(
        image_data_base64=base64.b64encode(framed).decode("ascii"),
        mime_type="image/png",
        model=result.model,
    )


def _compose_error_status(exc: Exception) -> int:
    """合成失敗的 HTTP 狀態：使用者能自己修的（標題太長、B55 面積防呆、修法甲的四道閘）
    回 400，其餘 500。四道閘的訊息字面見 compose._overlay_title_layer_core：都是
    「重試就可能過」的失敗，不是程式錯誤，比照既有 B55 差異遮罩防呆一樣回 400。"""
    message = str(exc)
    if (
        "標題太長" in message
        or "改動範圍過大" in message
        or "沒有回傳透明底的標題圖層" in message
        or "保留給程式後貼元素" in message
        or "標題圖層畫的範圍過大" in message
        or "標題圖層是空的" in message
    ):
        return 400
    return 500


def broadcast_hole_for(req: "NewsImageGenerateRequest") -> str:
    """/api/news-image 要不要蓋播出鏡面的白色壓框：版型有挖空側**且**使用者開了壓框。"""
    if not req.hole:
        return ""
    return editor_formats.hole_side(req.editor_format, req.role, side=req.hole_side) or ""


def broadcast_layout_hole_for(req: "NewsImageGenerateRequest") -> str:
    """播出鏡面的 AI 版面挖空側；不受白色壓框開關影響。"""
    return editor_formats.hole_side(req.editor_format, req.role, side=req.hole_side) or ""


def apply_broadcast_hole_response(
    result: ImageGenerateResponse,
    side: str,
    profile: str,
    *,
    canvas: tuple[int, int] = safe_area_spec.BASE_CANVAS,
) -> ImageGenerateResponse:
    """在置框後的成品上貼出播出鏡面的挖空框。

    與置框同一個原則：失敗就整支失敗。悄悄回傳一張沒有挖空框的圖，編輯會直接
    拿去給後製，那邊才發現沒有位置放影片。
    """
    try:
        holed = compose.apply_broadcast_hole(
            base64.b64decode(result.image_data_base64),
            side,
            canvas=canvas,
            profile=profile,
        )
    except Exception as exc:  # noqa: BLE001 — 影像處理失敗必須讓呼叫端知道
        print(f"[compose] 挖空框失敗：{type(exc).__name__}: {exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"播出鏡面挖空框失敗：{exc}") from exc
    return result.model_copy(
        update={
            "image_data_base64": base64.b64encode(holed).decode("ascii"),
            "mime_type": "image/png",
        }
    )


def apply_image_disclaimer(
    result: ImageGenerateResponse, req: ImageGenerateRequest, *, profile: str
) -> ImageGenerateResponse:
    """B70／F43：在置框（與可能的播出鏡面挖空框）都貼完之後，最後貼「示意圖」或
    「畫面來源」標籤。

    與挖空框同一個原則：失敗就整支失敗，不要悄悄回傳一張沒標籤的具名肖像圖出去——
    那正是 B70 的原始事故（合規缺陷不是美觀問題）。
    """
    try:
        stamped = compose.paste_disclaimer_note(
            base64.b64decode(result.image_data_base64),
            kind=req.disclaimer_kind,
            source_text=req.disclaimer_source_text,
            corner=req.disclaimer_corner,
            canvas=_image_dimensions(result.image_data_base64),
            profile=profile,
        )
    except Exception as exc:  # noqa: BLE001 — 影像處理失敗必須讓呼叫端知道
        print(f"[compose] 標籤貼字失敗：{type(exc).__name__}: {exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"標籤貼字失敗：{exc}") from exc
    return result.model_copy(
        update={
            "image_data_base64": base64.b64encode(stamped).decode("ascii"),
            "mime_type": "image/png",
            # B86（2026-09-22）：未置框那條路（記者＋安全框 OFF）`finalize_image_result`
            # 會提早 return，`source_image_base64` 留空，前端
            # `refineSourceFromResponse()` 就退而取成品本身——而成品此刻**已經有一枚
            # 標籤**。那張再送回 refine／restamp 就會被貼上第二枚（舊角落一枚、新角落
            # 一枚）。所以這裡把「貼標籤之前」那張補進去；上游已經填過（置框那條路）
            # 就不動它，那格的語意是「置框前原圖」，優先序不能倒過來。
            "source_image_base64": (
                result.source_image_base64 or result.image_data_base64
            ),
            "source_mime_type": result.source_mime_type or result.mime_type,
            # B83：留下這次**實際**貼的那一組，供 refine／restamp 原樣帶回（見欄位說明）
            "disclaimer_kind": req.disclaimer_kind,
            "disclaimer_source_text": req.disclaimer_source_text,
            "disclaimer_corner": req.disclaimer_corner,
        }
    )


def _image_dimensions(image_base64: str) -> tuple[int, int]:
    """讀一張 base64 圖的實際尺寸。貼標籤要用成品真正的尺寸算安全區，不是請求時
    預期的 output_canvas——理由同 apply_broadcast_hole：上游可能改了尺寸。"""
    with Image.open(io.BytesIO(base64.b64decode(image_base64))) as opened:
        return opened.size


def finalize_image_result(
    result: ImageGenerateResponse,
    *,
    aspect_ratio: str,
    safe_frame: bool,
    profile: str,
    broadcast_hole: str = "",
    canvas: tuple[int, int] = safe_area_spec.BASE_CANVAS,
) -> ImageGenerateResponse:
    """生成後的共同收尾：驗比例，需要時置框並保留置框前原圖。

    generate_image 與 refine_image 共用。置框前的原圖（含實際 MIME）要留給
    追加修改（refine）用：把置框後成品餵回去改圖會二次拉伸
    （見 ImageGenerateResponse 的欄位說明）。
    """
    verify_output_aspect_ratio(result, aspect_ratio)
    if not safe_frame and not broadcast_hole:
        return result
    # D24/B110：白色壓框是獨立的後製步驟，不能被「不置安全框」的早退一起略過。
    # safe_frame=False 時原圖已是成品座標；apply_broadcast_hole 會再依實際圖片尺寸重算。
    framed = frame_image_response(result, profile, canvas=canvas) if safe_frame else result
    if broadcast_hole:
        framed = apply_broadcast_hole_response(
            framed, broadcast_hole, profile, canvas=canvas
        )
    return framed.model_copy(
        update={
            # 追加修改要餵**置框前**原圖回去，不是挖過洞的成品（見欄位說明）
            "source_image_base64": result.image_data_base64,
            "source_mime_type": result.mime_type,
        }
    )


# D26 修正（2026-09-26 使用者裁決）：守門不過**不再退回置框**。原話：「退回置框有問題
# 不要退回置框 還是生圖給使用者 但訊息跳出 警告:超出安全框 讓使用者自行決定要用
# 還是重新生成」。驗收時 OCR 曾把樹叢當成字（假陽性），硬退回會把一張能用的圖換掉。
MODEL_EXTENSION_WARNING_NOTICE = (
    "警告：超出安全框（{reason}）。圖照常交付，請自行判斷要使用還是重新生成。"
)


def finalize_model_extension(
    result: ImageGenerateResponse,
    *,
    aspect_ratio: str,
    canvas: tuple[int, int],
    allow_no_text: bool = False,
) -> ImageGenerateResponse:
    """D26：延伸背景模式的收尾。模型的圖一律縮放到交付畫布後交付；守門只負責
    發警告——文字不在記者安全框內（或無法確認）時留一則通知，由使用者決定。

    守門一律在**交付畫布**上量（safe_rect 依畫布等比換算），2K 自然成立。
    """
    verify_output_aspect_ratio(result, aspect_ratio)
    image = None
    try:
        image = Image.open(io.BytesIO(base64.b64decode(result.image_data_base64)))
        image.load()
        if image.size != canvas:
            image = image.resize(canvas, Image.LANCZOS)
        gate = safe_content_gate.check_text_inside_safe_area(
            image, allow_no_text=allow_no_text
        )
    except Exception as exc:  # noqa: BLE001 — 解不開圖也是「無法確認」
        gate = None
        reason = f"成品無法檢查：{type(exc).__name__}"
    else:
        reason = gate.reason
    passed = bool(gate and gate.passed)
    print(f"[d26] 延伸背景守門：{'通過' if passed else '不通過，照常交付＋警告'}（{reason}）", flush=True)
    if not passed:
        _record_portrait_notice(MODEL_EXTENSION_WARNING_NOTICE.format(reason=reason))
    if image is None:
        # 圖解不開就沒辦法縮放，原樣交付（上面已經發了警告）
        return result
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return result.model_copy(
        update={
            "image_data_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "mime_type": "image/png",
            # 追加修改一律餵模型的原圖（語意同置框那條路，見欄位說明）
            "source_image_base64": result.image_data_base64,
            "source_mime_type": result.mime_type,
        }
    )


def generate_via_openrouter(
    model: str,
    req: ImageGenerateRequest,
    *,
    resolved_size: str | None = None,
) -> ImageGenerateResponse:
    """透過 OpenRouter 統一圖片端點生成，一把 OPENROUTER_API_KEY 涵蓋多家模型。"""
    if resolved_size is None and model.startswith("openai/gpt-image"):
        resolved_size, _ = image_generation_size(
            req.model_copy(update={"provider": "gpt"})
        )
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="尚未設定 OPENROUTER_API_KEY，無法生成圖片",
        )

    assert_aspect_ratio_supported(model, req.aspect_ratio)

    payload = {
        "model": model,
        "prompt": req.prompt,
        "aspect_ratio": req.aspect_ratio,
    }
    # 只有支援 resolution enum 的模型才帶 resolution（Gemini / Seedream / Riverflow）；
    # GPT 系列不吃 resolution，帶了會 400。
    if any(tag in model for tag in ("gemini", "seedream", "riverflow")):
        payload["resolution"] = req.image_size
    # GPT Image 系列額外送明確的 size（2026-09-10 熱修，根因見 OPENROUTER_GPT_IMAGE_MODEL
    # 上面那段）：2.5 系列的 aspect_ratio 會被整個丟掉，size 才吃得到。aspect_ratio 一併
    # 留著，對 2 與其他模型仍然有效；兩者並存時以 size 為準（實打確認）。
    gpt_size = _openrouter_gpt_size(model, req.aspect_ratio, resolved_size)
    if gpt_size:
        payload["size"] = gpt_size
    # B55 修法甲：只有 openai/gpt-image 系列公告支援 background enum（本 session
    # 查證：google/gemini-3-pro-image 沒有這個參數）。呼叫端只在 provider=="gpt"
    # 時才會設這個旗標，這裡再用模型名多擋一層，帶去 gemini 系模型只會白白 400。
    if req.transparent_background and model.startswith("openai/gpt-image"):
        payload["background"] = "transparent"
    # 參考圖兩個來源合併送出：肖像參考照（自動查圖）在前、使用者上傳在後。
    # GPT Image 2／2.5 支援 0–16 張、Gemini 0–14 張（PLAN.md 已向 models 端點查證），
    # 但實務上不需要塞滿，超過 MAX_INPUT_REFERENCES 的直接擋下。
    reference_urls = [
        url
        for url in (
            [req.reference_image_data_url] if req.reference_image_data_url else []
        )
        + list(req.portrait_reference_data_urls)
        + [ref.data_url for ref in req.reference_images]
        if url
    ]
    if len(reference_urls) > MAX_INPUT_REFERENCES:
        raise HTTPException(
            status_code=400,
            detail=f"參考圖最多 {MAX_INPUT_REFERENCES} 張（本次共 {len(reference_urls)} 張）",
        )
    if reference_urls:
        payload["input_references"] = [
            {"type": "image_url", "image_url": {"url": url}} for url in reference_urls
        ]

    request = Request(
        "https://openrouter.ai/api/v1/images",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    try:
        with urlopen(request, timeout=180, context=ssl_context) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        print(f"[OpenRouter image HTTPError] {exc.code}: {body}", flush=True)
        raise HTTPException(
            status_code=502,
            detail=f"OpenRouter 圖片生成失敗（{exc.code}）：{body}"
            if body
            else "OpenRouter 圖片生成失敗，請確認金鑰、模型權限或稍後重試",
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(
            status_code=502,
            detail="無法連線至 OpenRouter 圖片服務，請稍後再試",
        ) from exc

    data = result.get("data") or []
    item = data[0] if data else {}
    image_data = item.get("b64_json")
    if not image_data:
        raise HTTPException(
            status_code=502,
            detail="OpenRouter 未回傳可用圖片，請調整 Prompt 後重試",
        )

    return ImageGenerateResponse(
        image_data_base64=image_data,
        mime_type=item.get("media_type", "image/png"),
        model=model,
    )


# 原生 OpenAI 沒有 aspect_ratio，只吃 size。GPT Image 2／2.5 接受任意 16 的倍數
# （gpt-image-2 標準上限 2560×1440；2.5 實測長邊上限放寬到 3840，錯誤訊息明講），
# 這裡挑貼合比例、又不超過兩者共同上限的尺寸——沿用同一組值，換模型不會連尺寸一起變。
# 2026-08-01 之前這裡寫死 1280x720，等於無視呼叫端要的比例——安全框開 21:9
# 也會靜靜拿回 16:9，是與 OpenRouter 那條同一類的靜默降級。
# 原生 images.generate／edit 以前沒傳 timeout，吃 SDK 預設 read 600 秒（B31）。
# 對齊 OpenRouter 那條 urlopen timeout=180。
NATIVE_IMAGE_TIMEOUT_SECONDS = 180

NATIVE_GPT_IMAGE_SIZES = {
    "1:1": "1024x1024",
    "4:3": "1280x960",
    "3:4": "960x1280",
    "3:2": "1440x960",
    "2:3": "960x1440",
    "16:9": "1280x720",
    "9:16": "720x1280",
    "21:9": "1680x720",
}

# F38（2026-09-20 使用者裁決：「把旗標打開」）：字多／字超多在播出時容易糊
# （現況 1280x720／1680x720 被 apply_safe_frame 升採樣到 1920x1080），拉高生成
# 畫布能救「糊」；「錯字」那一半已經另外查證結案——解析度救不了錯字，甚至反相關
# （見 MASTER-列管清單.md F38：同一張圖裡全圖最大的字反而是壞字），只圖利銳利度。
#
# 旗標名稱歷史留著 EDITOR，但這次使用者原話「記者/編輯 字多/字超多的時候」明講
# 兩個角色都要涵蓋，不能再寫死只有編輯——見下面 HIGH_RES_ROLES。
#
# 實際會送出的**生成**尺寸：16:9→2560x1440、21:9→3360x1440（交付畫布是另一回事，
# 一律 16:9，見下面 HIGH_RES_OUTPUT_CANVAS）。預設模型
# NATIVE_GPT_IMAGE_MODEL="gpt-image-2.5-sunburst"（見上方 generate_gpt_image），
# 2.5 系列長邊上限放寬到 3840（見本檔開頭的模型註記），3360 在界內；若透過
# OPENAI_IMAGE_MODEL 環境變數換回 gpt-image-2（標準上限 2560×1440），21:9 這條
# 高解析度會在送出時被 provider 拒絕（400），不是這裡的責任範圍。
#
# 代價（2026-09-15/16 實測，記在 MASTER-列管清單.md）：耗時多 12–17%，單價未查證
# （上線前仍要對一次帳單，量最大的檔位組合正是這批）。
HIGH_RES_EDITOR_ENABLED = True
HIGH_RES_EDITOR_DENSITIES = frozenset({"standard", "maximum"})
HIGH_RES_ROLES = frozenset({safe_area_spec.REPORTER_PROFILE, safe_area_spec.EDITOR_PROFILE})
HIGH_RES_GPT_IMAGE_SIZES = {
    "16:9": "2560x1440",
    "21:9": "3360x1440",
}

# B87（2026-09-22 使用者回報：「記者CG 字多 安全框比例完全是錯的 沒有跟著 2K 調整」）
#
# 這裡以前是一張 `{"16:9": (2560,1440), "21:9": (3360,1440)}` 的表，理由寫的是
# 「高解析度是不再靠升採樣，provider 尺寸與交付畫布必須是同一組數字」。那句話對
# 16:9 成立，對 21:9 **不成立**，而且會毀掉安全框：
#
#   交付畫布**永遠是 1080p 那個形狀**（16:9）。21:9 從來不是交付比例，它是**生成**
#   技巧——記者開安全框時 `resolve_aspect_ratio()` 會挑 21:9，因為那個比例的生成圖
#   FIT 進記者安全區幾乎零裁切（見 SAFE_FRAME_ASPECT_RATIO 那段）。非高解析度那條
#   路無論生成比例是什麼，`output_canvas` 一律 `BASE_CANVAS`，21:9 的圖就是被放進
#   16:9 畫布裡。F38 把交付畫布改成跟著生成比例走，等於悄悄把記者的交付檔從
#   1920×1080 換成 3360×1440。
#
# 實測（`safe_area_spec.safe_rect(*canvas, "記者")`）：
#   字少 21:9 → 畫布 1920×1080（1.778），安全框 1634×751，框比例 2.176  ✅
#   字多 16:9 → 畫布 2560×1440（1.778），安全框 2178×1002，框比例 2.174  ✅
#   字多 21:9 → 畫布 3360×1440（**2.333**），安全框 2859×1002，框比例 **2.853** ❌
# 最後一列就是使用者看到的那張：畫布與安全框的形狀雙雙跑掉。
#
# 改成單一畫布 (2560, 1440)＝1920×1080 等比放大到模型長邊上限內的最大 16:9。
# provider size **不動**（21:9 仍送 3360x1440）：生成比例是生成比例，交付畫布是交付
# 畫布，本來就是兩件事，混在同一張表就是這個缺陷的成因。
# 「不再靠升採樣」那個目的仍然達成——記者安全區在這張畫布上是 2178×1002，
# 比 1920 畫布的 1634×751 多 77% 像素，而且來源是 3360 寬的生成圖，全程只有縮小。
HIGH_RES_OUTPUT_CANVAS = (2560, 1440)


def image_generation_size(
    req: ImageGenerateRequest,
) -> tuple[str | None, tuple[int, int]]:
    """Resolve provider size and local framing canvas from one request.

    The high-resolution path is gated by the module flag and applies to both
    the reporter and editor roles (HIGH_RES_ROLES) at the two approved
    high-density values. Other aspect ratios retain the existing base framing
    canvas. Gemini keeps its existing "1K" image_size regardless (see below):
    this means the gemini provider's upscale ratio to the high-res output
    canvas gets worse when the flag is on, not better — that trade-off was
    accepted at e0f4df6/fc71891 and is not revisited here.
    """
    extension = model_extension_active(
        req.safe_frame_profile, req.safe_frame, req.frame_strategy
    )
    high_res = (
        HIGH_RES_EDITOR_ENABLED
        and req.safe_frame_profile in HIGH_RES_ROLES
        # D26：延伸背景模式不看檔位一律 2K——模型的圖就是交付物，不能再靠升採樣。
        and (extension or req.density in HIGH_RES_EDITOR_DENSITIES)
        # 閘門看的是「這個生成比例有沒有高解析度的 provider size」，不是交付畫布
        # ——交付畫布只有一個（B87）。
        and req.aspect_ratio in HIGH_RES_GPT_IMAGE_SIZES
    )
    output_canvas = (
        HIGH_RES_OUTPUT_CANVAS if high_res else safe_area_spec.BASE_CANVAS
    )
    if req.provider == "gpt":
        size_map = HIGH_RES_GPT_IMAGE_SIZES if high_res else NATIVE_GPT_IMAGE_SIZES
        provider_size = size_map.get(req.aspect_ratio)
    else:
        # Gemini's existing image_size enum is intentionally unchanged in F38.
        # D26 延伸背景模式例外：一律 2K（同上，模型的圖就是交付物）。
        provider_size = "2K" if extension else req.image_size
    return provider_size, output_canvas


def _native_reference_files(req: ImageGenerateRequest) -> list[tuple[str, io.BytesIO, str]]:
    """把這次請求的參考圖轉成 images.edit 收得下的檔案清單（順序：肖像照、使用者上傳）。

    上限沿用 MAX_INPUT_REFERENCES（模型端 0–16，這裡本來就抓得更保守）。
    解不開的 data URL 直接略過——參考圖是加分項，不能讓一張壞圖擋掉整次成圖。
    """
    files: list[tuple[str, io.BytesIO, str]] = []
    sources = []
    if req.reference_image_data_url:
        sources.append(req.reference_image_data_url)
    sources.extend(ref.data_url for ref in req.reference_images)
    for index, data_url in enumerate(sources[:MAX_INPUT_REFERENCES]):
        mime, _, encoded = _split_data_url(data_url)
        if not encoded:
            continue
        try:
            raw = base64.b64decode(encoded)
        except Exception as exc:  # noqa: BLE001 — 壞圖只略過，不擋成圖
            print(f"[GPT image] 參考圖 {index} 解碼失敗，略過：{type(exc).__name__}", flush=True)
            continue
        ext = "png" if "png" in (mime or "") else "jpg"
        files.append((f"reference-{index}.{ext}", io.BytesIO(raw), mime or "image/png"))
    return files


def generate_gpt_image(
    req: ImageGenerateRequest, *, resolved_size: str | None = None
) -> ImageGenerateResponse:
    model = os.getenv("OPENAI_IMAGE_MODEL", NATIVE_GPT_IMAGE_MODEL)
    quality = os.getenv("OPENAI_IMAGE_QUALITY", "medium")

    if resolved_size is None:
        resolved_size, _ = image_generation_size(
            req.model_copy(update={"provider": "gpt"})
        )
    size = resolved_size
    if size is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"原生 OpenAI 生圖沒有對應 aspect_ratio={req.aspect_ratio} 的尺寸，"
                f"可用比例：{'、'.join(NATIVE_GPT_IMAGE_SIZES)}。"
                "改走 OpenRouter（IMAGE_BACKEND=openrouter）可支援更多比例。"
            ),
        )

    # 有參考圖就改走 images.edit（2026-09-10）：原生路徑的 images.generate 沒有參考圖
    # 通道，以前只能把圖丟掉。地圖底圖正是非送不可的那一種——實測同一份 prompt，
    # 有底圖地理全對、沒底圖澎湖被畫到臺灣北方。edit 端點吃得下同一個模型與尺寸。
    edit_images = _native_reference_files(req)
    # B55 修法甲：原生 OpenAI SDK 的 images.generate／images.edit 都吃 background
    # 參數（gpt-image 系列），跟 size／quality 同一層 kwargs，不必另外組 payload。
    background_kwargs = {"background": "transparent"} if req.transparent_background else {}
    try:
        if edit_images:
            print(f"[GPT image] 附 {len(edit_images)} 張參考圖，改走 images.edit", flush=True)
            result = openai_client.images.edit(
                model=model,
                image=edit_images,
                prompt=req.prompt,
                size=size,
                quality=quality,
                timeout=NATIVE_IMAGE_TIMEOUT_SECONDS,
                **background_kwargs,
            )
        else:
            result = openai_client.images.generate(
                model=model,
                prompt=req.prompt,
                size=size,
                quality=quality,
                output_format="png",
                timeout=NATIVE_IMAGE_TIMEOUT_SECONDS,
                **background_kwargs,
            )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API 金鑰無效或尚未啟用 API 計費",
        ) from exc
    except RateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail="OpenAI API 圖片用量已達限制，請稍後再試",
        ) from exc
    except APIConnectionError as exc:
        raise HTTPException(
            status_code=502,
            detail="無法連線至 OpenAI 圖片服務，請稍後再試",
        ) from exc
    except APIError as exc:
        reason = str(getattr(exc, "message", "") or exc)[:300]
        print(f"[GPT image APIError] {type(exc).__name__}: {reason}", flush=True)
        raise HTTPException(
            status_code=502,
            detail=f"GPT 圖片生成失敗：{reason}",
        ) from exc

    image_data = result.data[0].b64_json if result.data else None
    if not image_data:
        raise HTTPException(
            status_code=502,
            detail="GPT 未回傳可用圖片，請調整 Prompt 後重試",
        )

    return ImageGenerateResponse(
        image_data_base64=image_data,
        mime_type="image/png",
        model=model,
    )


def generate_gemini_image(req: ImageGenerateRequest) -> ImageGenerateResponse:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="尚未設定 GEMINI_API_KEY，無法生成圖片",
        )

    model = os.getenv("GEMINI_IMAGE_MODEL", NATIVE_GEMINI_IMAGE_MODEL)
    content: list[dict[str, object]] = [{"type": "text", "text": req.prompt}]
    if req.reference_image_data_url:
        mime_type, _, encoded = _split_data_url(req.reference_image_data_url)
        if encoded:
            content.append({"type": "image", "mime_type": mime_type, "data": encoded})
    # B63：具名換臉同時需要原圖與目標肖像。原生 Gemini 的一般多圖路徑仍維持
    # 原有能力界線；這裡只補送 refine 明確標成 portrait 的第二張參考圖。
    for ref in req.reference_images:
        if ref.purpose != "portrait":
            continue
        mime_type, _, encoded = _split_data_url(ref.data_url)
        if encoded:
            content.append({"type": "image", "mime_type": mime_type, "data": encoded})
    payload = {
        "model": model,
        "input": content,
        "response_format": {
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": req.aspect_ratio,
            "image_size": req.image_size,
        },
    }
    request = Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    try:
        with urlopen(request, timeout=120, context=ssl_context) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        print(f"[Gemini image HTTPError] {exc.code}: {body}", flush=True)
        raise HTTPException(
            status_code=502,
            detail=f"Gemini 圖片生成失敗（{exc.code}）：{body}" if body else "Gemini 圖片生成失敗，請確認金鑰、模型權限或稍後重試",
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(
            status_code=502,
            detail="無法連線至 Gemini 圖片服務，請稍後再試",
        ) from exc

    output_image = extract_image_content(result)
    if not output_image:
        raise HTTPException(
            status_code=502,
            detail="Gemini 未回傳可用圖片，請調整 Prompt 後重試",
        )

    return ImageGenerateResponse(
        image_data_base64=output_image["data"],
        mime_type=output_image.get("mime_type", "image/jpeg"),
        model=model,
    )


# ============================================================
# 一次到位端點：新聞文字 -> AI 消化 -> 套安全框/文字規則組 prompt -> 生圖
# 給外部整合方（如 WorkCord Agent）呼叫，避免呼叫端自己重組
# /api/generate 結果與 /api/images/generate 之間的規則——那段目前只存在
# news_prompt.py，若外部各自重做一次容易日後漂移、且容易漏掉安全框規則。
# LINE Bot 與這支端點共用同一個 generate_news_image()，兩邊不會各自維護
# 一份邏輯。
# ============================================================


class NewsImageGenerateRequest(BaseModel):
    news_text: str = Field(min_length=1, max_length=20_000)
    type_label: str = AUTO_TYPE_LABEL
    role: str = "記者"
    # 呼叫端身分，給 input_filter 的頻率限制用。空字串＝不做頻率限制、只做內容
    # 檢查。LINE 端已在 line_bot 自己做過頻率限制，刻意不傳；WorkCord 等其他
    # 入口可傳自己的識別值選擇加入。
    client_id: str = ""
    density: DigestDensity = "standard"
    # CG 美術創意 0-4（2026-09-10）：與 /api/generate 同一個旋鈕，一次到底的管線也要吃得到。
    visual_creativity: int = Field(default=0, ge=0, le=4)
    provider: Literal["gemini", "gpt"] = "gemini"
    # None＝依 safe_frame 自動選擇（見 generate_news_image）；呼叫端仍可明確指定覆寫。
    aspect_ratio: str | None = None
    image_size: str = "1K"
    # True＝滿版生成＋後端置框（安全框由數學保證，不靠模型自律）
    safe_frame: bool = False
    # 落檔時標示來源（line／workcord／…），純粹方便回查時篩選；空值用預設值
    source: str = ""
    # 專用指令欄位（PLAN.md ①），語意同 GenerateRequest.user_instruction。
    # LINE 端不傳（聊天框拆不了欄位，維持文內解析）。
    user_instruction: str = Field(default="", max_length=2_000)
    # 蓋章開關（2026-09-03），語意同 GenerateRequest.stamp。LINE 端不傳。
    stamp: bool | None = None
    tone: DigestTone | None = None
    # 編輯專屬版型（2026-09-03），語意同 GenerateRequest.editor_format。
    editor_format: str = editor_formats.DEFAULT_FORMAT
    # 播出鏡面的白色壓框開關（2026-09-07 使用者裁決：預設 OFF）。False＝不蓋白框，
    # 底圖完整交給後製自己決定影片位置；True＝置框後蓋白框給後製對位。
    # 消化規則不受此開關影響：不管蓋不蓋框，內容都要避開影片那半邊。
    hole: bool = False
    # 挖空側（2026-09-08 WP1），語意同 GenerateRequest.hole_side：只有合併後的
    # editor_format="broadcast" 吃得到，舊別名 broadcast_left／right 一律用自己那側。
    hole_side: Literal["left", "right"] = "left"
    # 變化池的 seed（F0／D1），語意同 GenerateRequest.seed。LINE 端不傳。
    seed: int | None = Field(default=None, ge=0, lt=SEED_MAX)


class NewsImageGenerateResponse(BaseModel):
    image_data_base64: str
    mime_type: str
    model: str
    title: str = ""
    prompt_version: str = PROMPT_VERSION
    # 回查用：對應 logs/generations-*.jsonl 裡的那一筆
    request_id: str = ""
    # 置框前原圖與其實際 MIME，僅供 /api/images/refine 再編輯用；語意同
    # ImageGenerateResponse.source_image_base64（成品拿去顯示，這格拿去改圖）
    source_image_base64: str = ""
    source_mime_type: str = ""
    # 這次實際採用的 seed（F0），語意同 GenerateResponse.seed。
    seed: int = 0
    # F40 第 3 層的 nonfatal notice；只走訊息欄，不畫進圖。
    notices: list[str] = Field(default_factory=list)


def _extract_title(variable: str) -> str:
    """從消化結果的 [標題] 那行取出標題，純粹方便呼叫端顯示用；抓不到就回空字串。"""
    match = re.search(r"\[標題\]\s*([^\n]+)", variable)
    return match.group(1).strip() if match else ""


# 2026-07-30：safe_frame 模式下 21:9 已用 4 個真實生成樣本驗證幾何穩定
# （左右留白 4/4 落在官方需求 ±1pp 內，取代 16:9 慣性多出的一倍左右留白）。
# 內容瑕疵（括號滲入、捏造來源）發生率約 50%，但與 16:9 同樣存在、非 21:9 新增，
# 使用者拍板接受現狀切換。safe_frame=False 時維持 16:9——21:9 只在搭配後端
# 置框時才有幾何優勢，未置框的畫面沒有理由跟著改。
SAFE_FRAME_ASPECT_RATIO = "21:9"
DEFAULT_ASPECT_RATIO = "16:9"


def resolve_frame_plan(
    role: str, safe_frame: bool, density: str = ""
) -> tuple[bool, bool, str]:
    """把（角色, 安全框開關, 檔位）翻成（要滿版版面?, 要後製置框?, 置框 profile）。

    這是編輯版兩種模式的唯一決定點，三個呼叫端（消化、生圖、整條 pipeline）
    都問這裡，才不會有人漏接就悄悄退回舊行為。

    編輯版：
      ON                    → 四周各壓 2% 薄框，輸出完整 1920×1080（2026-08-19 起不變）
      OFF ＋ 字多／字超多   → **不後製**，直接交付生成圖（D24，見下）
      OFF ＋ 其餘檔位       → 拉伸填滿對位框（2026-08-19 的行為，維持不變）
    版面一律滿版生成（第一個回傳值恆為 True），兩檔都是。

    ⚖ **D24（2026-09-22 使用者裁決）**：原話「記者/編輯CG 字多/字超多 安全框OFF時
    生成 16:9 2K 無任何色框」。同日稍早先實作成「所有檔位都不後製」，使用者隨即
    修正為「**只在字多 字超多生效**」，所以命中條件就是字面那兩檔，其餘檔位仍走
    2026-08-19 的對位框（交付 1748×924）。

    為什麼命中條件借 `HIGH_RES_EDITOR_DENSITIES` 而不是自己再寫一份：裁決原話把
    「字多／字超多」與「2K」綁在同一句，而那個 frozenset 就是 F38 定義 2K 的地方
    （standard＝字多、maximum＝字超多）。兩邊各寫一份遲早會分岔。

    `density` 給預設值是為了舊呼叫端：漏傳就落到「非字多」那條，也就是改動前的
    行為，不會有人因為漏傳而悄悄拿到不後製的圖。

    記者版不受影響：OFF 就是不出滿版版面、也不後製（本來就符合 D24）。
    """
    if role == safe_area_spec.EDITOR_PROFILE:
        if not safe_frame:
            # profile 兩條路都回對位框那組：不後製那條只拿它算貼標籤的版位
            # （見 apply_image_disclaimer），置框那條真的拿它置框。
            needs_frame = density not in HIGH_RES_EDITOR_DENSITIES
            return True, needs_frame, safe_area_spec.EDITOR_PROFILE
        return True, True, safe_area_spec.EDITOR_FRAME_PROFILE
    return safe_frame, safe_frame, safe_area_spec.REPORTER_PROFILE


def model_extension_active(role: str, safe_frame: bool, frame_strategy: str) -> bool:
    """D26（2026-09-26 使用者裁決）：這次是不是「模型畫延伸背景」模式。

    只開給記者＋安全框 ON（使用者：「只要處理記者版 編輯版不需要處理」）。
    編輯、安全框 OFF、LINE（不送這個欄位）一律 False，行為與改動前逐位元相同。

    這個模式的三件事都從這裡分流：
    - 消化：版面寫成「中央內容＋四周背景區」（full_bleed=False），不是滿版
    - 生圖：16:9 一律 2K 生成（使用者裁決「勾選後一律生 2K」），交付 2560×1440
    - 收尾：模型的圖一律交付；safe_content_gate 驗到文字出框（或無法確認）時
      只發警告通知，由使用者決定要用還是重生（2026-09-26 使用者改裁，不退回置框）
    """
    return (
        frame_strategy == "model_extension"
        and safe_frame
        and role == safe_area_spec.REPORTER_PROFILE
    )


def resolve_aspect_ratio(
    requested: str | None, safe_frame: bool, role: str = "記者"
) -> str:
    if requested:
        return requested
    # 編輯對位框接近 16:9，用 21:9 反而左右會被硬塞進較方的框。
    if safe_frame and role == "編輯":
        return DEFAULT_ASPECT_RATIO
    return SAFE_FRAME_ASPECT_RATIO if safe_frame else DEFAULT_ASPECT_RATIO


def clean_portrait_subjects(raw: object) -> list[str]:
    """把消化端回傳的名單洗乾淨：去空白、丟掉非字串與空值、去重但保留順序。

    模型偶爾會回 null、回字串而不是陣列、或同一個人重複列兩次，這些都不該讓
    後面的判斷跟著歪掉。
    """
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned


def align_english_names(
    subjects: list[str], raw_en: object, raw_subjects: object
) -> list[str]:
    """把消化端的英文名單對齊到清洗後的 portrait_subjects，回傳同長度的清單。

    模型是以「原始 portrait_subjects」的順序給英文名的，而 clean_portrait_subjects
    會去掉空值與重複——直接按索引取會錯位（第 2 個人拿到第 3 個人的英文名，
    等於用別人的名字去查照片）。所以先用原始名單建對照表再取。
    """
    if isinstance(raw_en, str):
        raw_en = [raw_en]
    if isinstance(raw_subjects, str):
        raw_subjects = [raw_subjects]
    if not isinstance(raw_en, list) or not isinstance(raw_subjects, list):
        return ["" for _ in subjects]
    pairs: dict[str, str] = {}
    for original, english in zip(raw_subjects, raw_en):
        if not isinstance(original, str) or not isinstance(english, str):
            continue
        key, value = original.strip(), english.strip()
        if key and key not in pairs:
            pairs[key] = value
    return [pairs.get(name, "") for name in subjects]


def lookup_portrait_photos(
    subjects: list[str],
    english_names: list[str] | None = None,
) -> tuple[dict[str, photo_lookup.ReferencePhoto], list[str]]:
    """逐位查參考照，回傳 (查到的 {人名: 照片}, 查不到的人名)。

    查圖失敗（網路、逾時、查無此人）一律當成「這位查不到」，不讓整條請求失敗：
    新聞生產不能因為維基查不到人就整張圖生不出來。

    `english_names` 與 subjects 同順序（消化端的 portrait_subjects_en），中文譯名
    查不到時用它再查一次——臺灣譯名常常不是中文維基的條目名（2026-08-18）。

    只回得出「有沒有照片」，分不出「查無此人」與「有條目沒照片」——F40 四層分流
    要分這兩種的呼叫端請用 `lookup_portrait_outcomes()`。這支保留給還沒接上 F40
    的既有呼叫端（`apply_photo_availability`、`resolve_digest_portraits`、
    `apply_portrait_to_image_request` 的使用者上傳分支），行為與改動前逐字相同。
    """
    found: dict[str, photo_lookup.ReferencePhoto] = {}
    missing: list[str] = []
    english_names = english_names or []
    for index, subject in enumerate(subjects):
        alt = english_names[index : index + 1] if index < len(english_names) else []
        try:
            photo = photo_lookup.find_reference_photo(subject, alt_names=alt)
        except Exception as exc:  # noqa: BLE001 — 查圖是加分項，不該拖垮生圖
            print(f"[portrait] 查參考照片失敗（{subject}）：{exc}", flush=True)
            photo = None
        if photo is None:
            missing.append(subject)
        else:
            found[subject] = photo
    return found, missing


def lookup_portrait_outcomes(
    subjects: list[str],
    english_names: list[str] | None = None,
    guessed_english_names: list[str] | None = None,
    source_context: str = "",
) -> dict[str, photo_lookup.PortraitLookupOutcome]:
    """逐位查完整 outcome（含 entry_found），F40 四層分流判斷用。

    與 `lookup_portrait_photos` 平行存在，不是取代它：查圖失敗一樣不讓整條請求
    失敗時標成 `lookup_failed`，不可誤當成「確認查無條目」而開放模型猜臉。
    """
    outcomes: dict[str, photo_lookup.PortraitLookupOutcome] = {}
    english_names = english_names or []
    guessed_english_names = guessed_english_names or []
    for index, subject in enumerate(subjects):
        alt = english_names[index : index + 1] if index < len(english_names) else []
        guessed = guessed_english_names[index : index + 1] if index < len(guessed_english_names) else []
        try:
            outcome = photo_lookup.find_portrait_outcome(
                subject, alt_names=alt, guessed_alt_names=guessed,
                source_context=source_context,
            )
        except Exception as exc:  # noqa: BLE001 — 查圖是加分項，不該拖垮生圖
            print(f"[portrait] 查參考照片失敗（{subject}）：{exc}", flush=True)
            outcome = photo_lookup.PortraitLookupOutcome(
                photo=None, entry_found=False, matched_name=None, language=None,
                lookup_failed=True,
            )
        outcomes[subject] = outcome
    return outcomes


# B73（2026-09-16 使用者裁決）：連維基條目都查不到時，是否仍交給生圖模型依語境
# 自畫具名真人的臉。使用者在知悉 B45 風險後仍裁定要開。
#
# 預設開啟；仍保留環境開關供事故時立即退回無人場景。全有或全無、最多三張臉、
# 使用者上傳肖像與查詢失敗不猜臉等安全不變式，不受這個開關影響。
PORTRAIT_NO_ENTRY_FALLBACK = (
    os.getenv("PORTRAIT_NO_ENTRY_FALLBACK", "true").strip().lower()
    not in ("", "0", "false", "off")
)


# B70（2026-09-20 使用者裁定採甲案）：哪些 portrait_mode 代表「畫面上這張臉不是
# 使用者提供的真實素材」，需要程式端壓「示意圖」標籤——
#   reference／reference_multi：模型依附上的參考照畫，仍是重新畫過的一張臉；
#   entry_only：連參考照都沒有，模型純依新聞語境猜長相（F40 第 3 層）。
# no_reference 沒有畫臉（改成不畫人形），none 不是具名真人案例，兩者都不需要。
PORTRAIT_MODES_NEEDING_DISCLAIMER = frozenset({"reference", "reference_multi", "entry_only"})


def resolve_image_disclaimer(portrait_mode: str, source_text: str = "") -> tuple[str, str]:
    """B70／F43 共用的互斥判定：這張成品該貼「示意圖」還是「畫面來源」，或都不貼。

    優先序（2026-09-16 使用者裁定 F43 互斥判準——「原圖沒改圖才需要畫面來源」）：
    **AI 標籤贏**。只要 portrait_mode 落在 PORTRAIT_MODES_NEEDING_DISCLAIMER，代表
    畫面上這張臉是模型生成或猜出來的，不可能同時滿足「畫面來源＝程式保證原圖未被
    動過」的前提，一律標「示意圖」，source_text 直接忽略。沒有這種肖像時，才看
    呼叫端有沒有填 source_text——有才標「畫面來源」，兩者都沒有就回 ("", "")，
    表示這次成品不貼任何標籤。

    回傳 (kind, text)：kind 直接對應 ImageGenerateRequest.disclaimer_kind／
    compose.paste_disclaimer_note 的 kind 參數；text 只在 kind="source" 時有值
    （只去除前後空白。B90 起 compose 那層**逐字照貼**、不再自動補「畫面來源：」，
    所以這裡拿到什麼字，成品上就是什麼字。）
    """
    if portrait_mode in PORTRAIT_MODES_NEEDING_DISCLAIMER:
        return "ai", ""
    text = (source_text or "").strip()
    if text:
        return "source", text
    return "", ""


def resolve_portraits(
    portrait_subjects: list[str],
    provider: str,
    *,
    photos: dict[str, photo_lookup.ReferencePhoto] | None = None,
    english_names: list[str] | None = None,
    outcomes: dict[str, photo_lookup.PortraitLookupOutcome] | None = None,
) -> tuple[str, list[photo_lookup.ReferencePhoto]]:
    """決定這次的肖像處理方式，回傳 (portrait_mode, 參考照片清單)。

    F40 四層分流（2026-09-16 使用者裁決，優先序固定）：
    - 不是真人肖像題 → ("none", [])，沿用一般規則
    - 1 位且查到照片 → ("reference", [照片])
    - 2-3 位且**每一位都查到照片** → ("reference_multi", [照片…])
    - 沒照片但**每一位都確認查得到維基條目** → ("entry_only", [])：允許模型依新聞
      語境自畫具名人物，呼叫端要用 `portrait_entry_only_notice()` 記一則 notice
      （見 apply_portrait_to_image_request）——⚠使用者裁定不在圖上標「長相為 AI
      推測」，通知走 response 的 notices，不畫進圖裡。
    - 其餘（有人連條目都查不到、超過 3 位、後端送不出參考圖）→ ("no_reference", [])：
      畫面不安排這個人（PORTRAIT_NO_REFERENCE_RULES 已改寫成無人場景，不是背影／剪影）。

    **全有或全無，後端絕不自行截斷**（2026-08-18 實驗結論，entry_only 沿用同一原則）：
    只要有一位沒有照片，整張退回「不逐人區分」的安全值。理由是實測 2/2 證明「有照片
    的畫、沒照片的畫剪影」這種逐人區分生圖模型辦不到，沒照片的那位會被憑空捏臉還掛
    真名。也不能把 4 人截成 3 人——版面是照 4 個人設計的，砍掉一個會留下一個沒人的
    空位。超過 3 人要在**消化階段**就壓下來（見 REAL_WORLD_FIDELITY_RULES 第 6 條）。
    這也是為什麼「一人有照片、另一人只有條目」混合時整組退到 entry_only、放棄那張
    已查到的照片——同一個全有或全無的理由，屬於本輪判斷但計畫沒寫死的地方，
    細節見任務回報。

    `photos`／`outcomes` 可由呼叫端先查好傳進來（兩段式消化流程會重複用到同一批
    查詢結果），沒傳就自己查。
    """
    if not portrait_subjects:
        return "none", []
    if not supports_reference_image(provider):
        return "no_reference", []
    if len(portrait_subjects) > MAX_PORTRAIT_FACES:
        print(
            f"[portrait] 畫面有 {len(portrait_subjects)} 位具名真人"
            f"（{'、'.join(portrait_subjects)}），超過上限 {MAX_PORTRAIT_FACES}，不生成臉孔",
            flush=True,
        )
        return "no_reference", []
    # 2 位以上要靠多張參考圖通道，原生路徑送不出去（措辭與能力必須一致）
    if len(portrait_subjects) > 1 and not supports_multiple_reference_images(provider):
        print("[portrait] 目前後端送不出多張參考圖，多人肖像退回不生成臉孔", flush=True)
        return "no_reference", []
    if outcomes is not None and photos is None:
        photos = {name: o.photo for name, o in outcomes.items() if o.photo is not None}
    if photos is None:
        photos, _ = lookup_portrait_photos(portrait_subjects, english_names)
    missing = [name for name in portrait_subjects if name not in photos]
    if not missing:
        ordered = [photos[name] for name in portrait_subjects]
        mode = "reference" if len(ordered) == 1 else "reference_multi"
        return mode, ordered
    if outcomes is None:
        outcomes = lookup_portrait_outcomes(portrait_subjects, english_names)
    if any(
        outcomes.get(name) is not None and outcomes[name].lookup_failed
        for name in portrait_subjects
    ):
        print("[portrait] 肖像查詢失敗，整張退回「無人場景」", flush=True)
        return "no_reference", []
    all_have_entries = all(
        (outcomes.get(name) is not None and outcomes[name].entry_found)
        for name in portrait_subjects
    )
    if all_have_entries:
        print(
            f"[portrait] 沒有合格參考照但查得到條目（{'、'.join(missing)}），"
            "允許模型依語境自畫並通知使用者",
            flush=True,
        )
        return "entry_only", []
    # B73 第二半（2026-09-16 使用者裁決：「就算維基查不到還是走第三層，讓生圖 AI
    # 自己判斷」）。原本這裡一律退回 no_reference（整張畫成無人場景）。
    #
    # 為什麼這是一個比字面更大的改動——監督已把實測攤給使用者看過，使用者仍維持原裁：
    # 實測 32 個人名（17 位臺灣政要＋15 位外國領袖），**第 3 層命中 0 次**，
    # 全部落在第 2 層（有條目有照片）或第 4 層（連條目都沒有）。也就是說
    # `entry_only` 這條路在實務上幾乎不會自然觸發，**把第 4 層導到第 3 層，
    # 等於是替「完全查不到的人」開放讓生圖模型自己捏一張臉**，而那正是帳本
    # [B45] 登記的事故（YT 整點直播把真實具名人物配上 AI 捏造的臉）。
    #
    # 留下的防線：①notice 一定會送到前端（呼叫端用 portrait_entry_only_notice），
    # 使用者看得到「這張臉是 AI 推測的」；②B73 的譯名對照表已先把 13 位常見人物
    # 從第 4 層救回第 2 層，真正落到這條路的人比修之前少很多。
    # 可退：環境變數 PORTRAIT_NO_ENTRY_FALLBACK=off 立刻回到舊行為（畫成無人場景）。
    if PORTRAIT_NO_ENTRY_FALLBACK:
        print(
            f"[portrait] 連維基條目都查不到（{'、'.join(missing)}），"
            "依 B73 裁決仍交給生圖模型依語境自畫，並通知使用者",
            flush=True,
        )
        return "entry_only", []
    print(
        f"[portrait] 查不到參考照（{'、'.join(missing)}），整張退回「無人場景」",
        flush=True,
    )
    return "no_reference", []


def resolve_portrait(
    portrait_subjects: list[str], provider: str
) -> tuple[str, photo_lookup.ReferencePhoto | None]:
    """單人版的舊介面：只回傳第一張照片。網頁版單人路徑仍在用。"""
    mode, photos = resolve_portraits(portrait_subjects, provider)
    return mode, (photos[0] if len(photos) == 1 else None)


def _fill_in_disclaimer_kind(req: ImageGenerateRequest) -> ImageGenerateRequest:
    """沒有肖像題時的 `disclaimer_kind`：**只補，不覆蓋**。

    這支只服務 `apply_portrait_to_image_request` 那條「沒有 portrait_subjects 就
    早退」的路。沒有肖像＝不可能判出 "ai"，所以唯一可能補上的是 F43 的 "source"。

    ⚠**不准覆蓋呼叫端已經設好的值**：LINE 路徑（`generate_news_image`）是自己先
    算好 `disclaimer_kind` 再組 request，而且不傳 `portrait_subjects`——走的正是
    這條早退路。無條件改寫會把它算好的 "ai" 洗成空字串，標籤整個消失（本 session
    第一版就是這樣寫的，被 `GenerateImageWiringTests` 當場抓到）。

    什麼都不用補時回原物件：這支函式對「沒改到東西」的輸入一直都是回同一個 req。
    """
    if req.disclaimer_kind:
        return req
    kind, _ = resolve_image_disclaimer("none", req.disclaimer_source_text)
    if not kind:
        return req
    return req.model_copy(update={"disclaimer_kind": kind})


def apply_portrait_to_image_request(req: ImageGenerateRequest) -> ImageGenerateRequest:
    """網頁版生圖路徑：依 portrait_subjects 注入規則並附上參考照。

    LINE／generate_news_image 已在 build_prompt 處理過，不會傳 portrait_subjects。
    規則字串若已在 prompt 裡，不再灌第二次。

    使用者上傳的肖像照（purpose="portrait"）優先於自動查圖，**不足的人由自動查圖
    補上**（2026-08-18 使用者裁決，取代 2026-08-17 的「有上傳就整段跳過」）：
    跳過的舊行為會讓沒附到照片的人被模型憑空捏臉還掛真名（2026-08-18 實測 2/2 重現）。

    補完仍有人沒照片時**擋下不生圖**（400），沿用 2026-08-05 的裁決：對不上就不要
    花這筆生圖錢。正常情況下不會走到這裡——消化端（apply_photo_availability）
    已經先把查不到照片的人排出版面了。
    """
    subjects = clean_portrait_subjects(req.portrait_subjects)
    if not subjects:
        # F43（2026-09-21）：沒有肖像題也可能要標「畫面來源」。這裡以前直接 return，
        # 於是「沒有人臉＋使用者填了來源名」這個 F43 最主要的情境永遠拿不到 kind，
        # 標籤整個不會出現——跟 B70 那個洞是同一種斷線（prompt 說軟體會壓，軟體那半
        # 沒被叫到），只是發生在更前面一步。
        # 沒填來源名的話原封不動把 req 還回去；呼叫端已經設好的 kind 也不動。
        return _fill_in_disclaimer_kind(req)
    english = align_english_names(
        subjects, req.portrait_subjects_en, req.portrait_subjects
    )
    uploaded = [ref for ref in req.reference_images if ref.purpose == "portrait"]
    if not uploaded:
        mode, photos = resolve_portraits(
            subjects, req.provider, english_names=english
        )
        if mode == "entry_only":
            _record_portrait_notice(portrait_entry_only_notice(subjects))
        block = PORTRAIT_MODES.get(mode, "")
        # 網頁版專用路徑的 B70 缺陷（2026-09-20 team-lead 複查點名，獨立複查
        # gpt-5.6-sol 發現、team-lead 實測驗證）：這支函式從沒呼叫過
        # resolve_image_disclaimer，disclaimer_kind 永遠是空字串——prompt 已經告訴
        # 模型「不要自己畫、軟體會壓」，但軟體那半從沒被叫到，兩邊斷開＝標籤整個消失。
        # LINE 路徑（generate_news_image）另外呼叫這支函式，沒有這個洞。
        # 2026-09-21：source_text 要一起交出去，否則「查不到肖像（mode=none/
        # no_reference）＋使用者填了來源名」永遠判不出 kind="source"（F43）。
        # AI 標籤仍然贏——優先序寫在 resolve_image_disclaimer 裡，這裡不重判。
        disclaimer_kind, _ = resolve_image_disclaimer(mode, req.disclaimer_source_text)
        # 2026-09-21 使用者要求：AI 贏的時候要講一聲。使用者打了來源名卻拿到「示意圖」，
        # 畫面上看不出那個欄位被丟掉了，只會以為自己填錯或功能壞了。
        if disclaimer_kind == "ai" and req.disclaimer_source_text.strip():
            _record_portrait_notice(
                f"你填的畫面來源「{req.disclaimer_source_text.strip()}」這次沒有用上："
                "畫面裡有 AI 生成或推測的人物長相，一律只能標「示意圖」，"
                "兩種標籤不能並存。要標來源請改用沒有 AI 人物的畫面。"
            )
        prompt = req.prompt
        if block and block not in prompt:
            prompt = f"{prompt.rstrip()}\n\n{block}"
        reference = req.reference_image_data_url
        portrait_urls = list(req.portrait_reference_data_urls)
        if len(photos) == 1 and not reference:
            reference = photos[0].data_url()
        elif len(photos) > 1 and not portrait_urls:
            portrait_urls = [photo.data_url() for photo in photos]
        if (
            prompt == req.prompt
            and reference == req.reference_image_data_url
            and portrait_urls == list(req.portrait_reference_data_urls)
            and disclaimer_kind == req.disclaimer_kind
        ):
            return req
        return req.model_copy(
            update={
                "prompt": prompt,
                "reference_image_data_url": reference,
                "portrait_reference_data_urls": portrait_urls,
                "disclaimer_kind": disclaimer_kind,
            }
        )

    # 有上傳：把系統查得到的人補上照片，湊齊「每個人都有照片」。
    # 上傳的照片視為對應「系統查不到的人」（假設與理由見 apply_photo_availability）。
    photos, missing = lookup_portrait_photos(subjects, english)
    still_missing = missing[len(uploaded) :]
    if still_missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"這幾位沒有可用的參考照片：{'、'.join(still_missing)}。"
                "請補上他們的照片，或重新消化讓版面不要畫他們。"
            ),
        )
    # B28 例外三：即使使用者親自上傳肖像照，具名真人仍要標「示意圖」——這裡走到
    # 這一步代表每一位都湊到照片了（自己上傳或自動查到），一定會畫出具名真人的臉，
    # 不受「有上傳就不標」的一般原則影響（見 apply_user_references_to_image_request
    # 的「例外三」與 USER_REFERENCE_PORTRAIT_RULES 的後貼措辭）。同一個洞：以前這裡
    # 也從沒設過 disclaimer_kind。
    disclaimer_kind = "ai"
    if not photos or req.portrait_reference_data_urls:
        if req.disclaimer_kind == disclaimer_kind:
            return req
        return req.model_copy(update={"disclaimer_kind": disclaimer_kind})
    return req.model_copy(
        update={
            "portrait_reference_data_urls": [
                photos[name].data_url() for name in subjects if name in photos
            ],
            "disclaimer_kind": disclaimer_kind,
        }
    )


# 拿不到真實底圖時貼在 prompt 尾巴的降級條文（2026-09-10）。位置在最後＝優先權最高，
# 與 attach_map_basemap 附上底圖時貼 verified_dots_block 的位置相同，兩者互斥。
NO_VERIFIED_BASEMAP_BLOCK = """NO VERIFIED BASEMAP IS ATTACHED TO THIS REQUEST — THIS PARAGRAPH OUTRANKS ANY EARLIER WORDING THAT ASKS FOR AN ACCURATE MAP.
Nothing in this request carries verified geography, so you have no source for real coastlines, real borders or real relative positions, and drawing them from memory produces a factually wrong map on air.
Therefore: draw NO administrative boundaries of any kind, do NOT tint or colour-fill any county, city, district or region, do NOT invent islands, coastline or landmasses, and do NOT crop, rotate or stretch a country or island to fit the frame.
Show place names as labelled markers over a plain, clearly schematic base — a flat tone, a soft terrain texture or a simple grid — and keep any land shape you do draw to one wordless silhouette with no internal divisions.
The wording rendered on the graphic still comes only from the supplied text; this paragraph changes the picture, never the words."""


def verified_dots_block(points: list[MapPoint]) -> str:
    """把「這張底圖上有哪幾個點」寫成一段由程式產生的事實陳述。

    為什麼不繼續改 prompt 措辭：2026-09-05 第五到第七輪，同一條「沒有橘點的
    地點不准畫標記」被繞過三次，每次換一種形狀——三角形警示圖示、末端停在
    路面上的虛線、最後直接畫一支 pin。措辭再嚴，模型仍然要自己判斷「哪些
    地點沒有點」，而它手上只有一張圖和一段文字，判斷本來就會出錯。

    這裡改成不要它判斷：點的數量與名稱是程式已知的事實，直接列出來，並說明
    清單之外的地點在這張圖上沒有位置。比照 safe_frame／compose 的原則——
    能算出來的事情不要問模型。
    """
    names = "、".join(point.name for point in points)
    return (
        "==================================================\n"
        "VERIFIED MAP POSITIONS (GENERATED — AUTHORITATIVE)\n"
        "==================================================\n"
        f"- The attached basemap carries EXACTLY {len(points)} verified dots, "
        f"and they are these: {names}.\n"
        "- Every other place mentioned anywhere in this prompt has NO verified position. "
        "Do not give any of them a spot on the map: no pin, no marker of any other shape, "
        "no icon, no highlighted segment, and no line that ends on the map. Mention them "
        "only in text that touches no part of the map.\n"
        f"- The finished graphic therefore carries {len(points)} map markers. "
        "If you find yourself placing one more, the position for it is one you invented."
    )


def apply_map_reference_to_image_request(
    req: ImageGenerateRequest,
) -> ImageGenerateRequest:
    """地圖類：把真實底圖（標點已畫在正確座標上）加進參考圖。

    三個「不做」是刻意的：
    1. **後端送不出參考圖時完全不做。** 原生 OpenAI 這條沒有多圖通道，硬加只會讓
       apply_user_references_to_image_request 丟 400——那是使用者沒做錯任何事卻
       收到的錯誤。沒有通道就安靜退回原本的純 prompt 路徑。
    2. **失敗不擋成圖。** 圖磚抓不到、範圍太大、Pillow 出事，一律只是沒有底圖。
       地圖底圖是加分項，不是必要條件。
    3. **不覆寫使用者自己上傳的地圖底稿。** 使用者親自附的圖永遠優先，
       自動底圖只在他沒附的時候補位。
    """
    if not req.map_points:
        return req
    if not supports_map_basemap(req.provider):
        # 2026-09-10：拿不到底圖就明講拿不到，把這張圖降級成示意，不留「假裝有依據」
        # 的空間。零定位資料還照樣要求地理準確的地圖，模型只能憑記憶畫、一畫就錯。
        # 原生 OpenAI 的 gpt 路徑已改走 images.edit（送得出底圖），所以現在只有
        # 原生 Gemini 會落到這裡。
        print(
            "[map] 目前的生圖後端送不出參考圖，略過自動底圖（改注入無底圖降級條文）",
            flush=True,
        )
        return req.model_copy(
            update={"prompt": f"{req.prompt.rstrip()}\n\n{NO_VERIFIED_BASEMAP_BLOCK}"}
        )
    if any(ref.purpose == "map" for ref in req.reference_images):
        print("[map] 使用者已自行附上地圖底稿，不再自動產生", flush=True)
        return req
    if len(req.reference_images) >= MAX_INPUT_REFERENCES:
        print("[map] 參考圖已達上限，略過自動底圖", flush=True)
        return req
    try:
        png = map_lookup.render_basemap(
            [(point.lat, point.lon) for point in req.map_points],
            width=1024,
            height=576,
            mark=True,
            # 地名跟著點一起烙進底圖。少了這個，模型只看得到三個一模一樣的
            # 橘點，只能自己猜哪個是誰——2026-09-05 連兩輪把最北的中壢交流道
            # 標成楊梅，連旁邊的事故圖示都跟著配錯。
            labels=[point.name for point in req.map_points],
        )
    except Exception as exc:  # noqa: BLE001 — 底圖是加分項，不能拖垮成圖
        print(f"[map] 底圖產生失敗（照舊出圖）：{type(exc).__name__}: {exc}", flush=True)
        return req
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    print(
        f"[map] 已附上真實底圖（{len(req.map_points)} 個標點，{len(png)} bytes）",
        flush=True,
    )
    return req.model_copy(
        update={
            "prompt": f"{req.prompt.rstrip()}\n\n{verified_dots_block(req.map_points)}",
            "reference_images": [
                *req.reference_images,
                UserReferenceImage(data_url=data_url, purpose="map"),
            ],
        }
    )


def apply_user_references_to_image_request(
    req: ImageGenerateRequest,
) -> ImageGenerateRequest:
    """使用者上傳參考圖（PLAN.md ②）：依 purpose 注入用途區塊。

    附圖能力與 prompt 措辭必須一致（同 supports_reference_image 的理由）：
    後端送不出參考圖（原生 OpenAI 路徑）卻叫模型「依附圖」，它只能憑印象亂捏，
    比不附更糟——所以送不出去時直接 400，不靜靜忽略使用者的上傳。
    每種 purpose 的區塊只注入一次（同用途多張圖共用同一段措辭）。
    """
    if not req.reference_images:
        return req
    # 2026-09-10：程式自己貼的地圖底圖不受這道 400 管——它不是使用者上傳的東西，
    # 而且原生 GPT 已改走 images.edit 送得出去（見 supports_map_basemap）。
    # 使用者親自上傳的參考圖仍照舊擋：那條路的措辭與能力必須一致。
    only_auto_basemap = all(ref.purpose == "map" for ref in req.reference_images)
    if not supports_multiple_reference_images(req.provider) and not (
        only_auto_basemap and supports_map_basemap(req.provider)
    ):
        raise HTTPException(
            status_code=400,
            detail="目前的生圖後端無法附上上傳的參考圖（僅 OpenRouter 路徑支援多張參考圖），"
            "請移除上傳的參考圖，或改回 OpenRouter 生圖設定",
        )
    prompt = req.prompt
    purposes = dict.fromkeys(ref.purpose for ref in req.reference_images)
    aiedit_count = sum(1 for ref in req.reference_images if ref.purpose == "aiedit")
    asis_count = sum(1 for ref in req.reference_images if ref.purpose == "asis")
    for purpose in purposes:
        block = USER_REFERENCE_MODES.get(purpose, "")
        if purpose == "aiedit" and aiedit_count >= 2:
            # 2026-09-14：多張 AI改圖 走融合版——單張版的「One of the attached images」
            # 會讓模型只挑一張畫（第四輪 A2：4 張參考只剩 1 張）
            block = USER_REFERENCE_AIEDIT_FUSION_RULES_TEMPLATE.format(count=aiedit_count)
        elif purpose == "asis" and asis_count >= 2:
            # 2026-09-14 B26＋D9：多張原圖放置同樣不能走單數「One of」
            block = USER_REFERENCE_ASIS_MULTI_RULES_TEMPLATE.format(count=asis_count)
        if block and block not in prompt:
            prompt = f"{prompt.rstrip()}\n\n{block}"
    # AI改圖 專屬：使用者指令欄要真的送到生圖模型手上（2026-09-13 使用者裁決）。
    # 只在有 aiedit 附圖時注入——scene／portrait／map 那幾條路的指令欄本來就
    # 只管「畫面長什麼樣」，由文字模型消化過了，再塞一次是重複下令。
    # 緊接在上面的 aiedit 區塊之後，模型才讀得出「這條指令管的是那張附圖」。
    instruction = (req.editor_instruction or "").strip()
    if "aiedit" in purposes and instruction:
        block = USER_REFERENCE_AIEDIT_INSTRUCTION_TEMPLATE.format(instruction=instruction)
        if block not in prompt:
            prompt = f"{prompt.rstrip()}{block}"
    # 有上傳就不標「示意圖」（2026-08-17 使用者裁決）；固定放最後才能 OVERRIDE
    # REAL_WORLD_RENDERING_RULES 的「標籤不得移除」條款。
    # 例外：這張圖裡混了後端自動查來的肖像照時仍要標（2026-08-18）——那個 override
    # 的語意是「照著使用者親自提供的素材生成」，維基照片沒有那個語意，而
    # 寫實照片感＋真名＋沒有示意圖標籤是最糟的組合。
    if req.portrait_reference_data_urls:
        return req.model_copy(update={"prompt": prompt}) if prompt != req.prompt else req
    # 例外二（2026-09-13 使用者裁決）：AI改圖的畫面是模型重繪出來的，不是使用者
    # 親自提供的真實素材——那個 override 的語意不成立，「AI示意圖」標籤照舊要留。
    # 混了別種用途也一樣留：同一張成品只有一個標籤，有任何一塊是 AI 重繪就得標。
    # titlelayer 同列（2026-09-20 獨立複查補）：理由不同但結論一樣。這條路的成品
    # 是「程式底圖 ＋ 模型只畫的標題圖層」，模型輸出裡根本沒有照片，標不標
    # 「示意圖」不是它能決定的事；而 USER_REFERENCE_NO_DISCLAIMER_RULES 的內文
    # 還會引用 REAL-WORLD ACCURACY／NAMED REAL PERSON 兩個封面 prompt 裡不存在的
    # 區塊，注進去只是懸空指涉。維持修法甲上線前的行為：不注入。
    if any(ref.purpose in ("aiedit", "titlelayer") for ref in req.reference_images):
        return req.model_copy(update={"prompt": prompt}) if prompt != req.prompt else req
    # 例外三（2026-09-14 B28）：畫真人並掛真實姓名時，「有上傳就不標示意圖」
    # 的 override 不成立——D13 的前提就是畫面上還有 AI示意圖標籤。
    if any(str(name).strip() for name in (req.portrait_subjects or [])):
        return req.model_copy(update={"prompt": prompt}) if prompt != req.prompt else req
    if USER_REFERENCE_NO_DISCLAIMER_RULES not in prompt:
        prompt = f"{prompt.rstrip()}\n\n{USER_REFERENCE_NO_DISCLAIMER_RULES}"
    if prompt == req.prompt:
        return req
    return req.model_copy(update={"prompt": prompt})


def apply_broadcast_hole_layout_to_image_request(
    req: ImageGenerateRequest,
) -> ImageGenerateRequest:
    """把播出鏡面背景-only 半邊規則冪等地壓在所有附圖用途規則之後。"""
    block = broadcast_hole_layout_rules(req.hole_side)
    if not block or block in req.prompt:
        return req
    return req.model_copy(update={"prompt": f"{req.prompt.rstrip()}\n\n{block}"})


class ImageRefineRequest(BaseModel):
    # 置框「前」的原始生成圖（base64，不是 data URL）。一律送
    # ImageGenerateResponse.source_image_base64；把已置框成品送進來會二次拉伸
    # （見 ImageGenerateResponse 欄位說明）。未置框流程則送 image_data_base64。
    source_image_base64: str = Field(min_length=1, max_length=28_000_000)
    source_mime_type: str = "image/png"
    # 使用者的修改指令，例如「把標題改成紅色」「左邊那張圖換成長條圖」
    instruction: str = Field(min_length=1, max_length=2_000)
    provider: Literal["gemini", "gpt"] = "gemini"
    aspect_ratio: str = "16:9"
    image_size: str = "1K"
    safe_frame: bool = False
    # D26：延伸背景模式要跟著過來，否則改完／重貼會被 FIT 縮小補底色。
    frame_strategy: Literal["", "model_extension"] = ""
    safe_frame_profile: str = "記者"
    # 追加修改要沿用同一個挖空側，否則改完圖那塊空位就不見了
    broadcast_hole: str = ""
    # B110：追加修改也要保住同一個背景-only 半邊；與白色壓框開關分離。
    hole_side: Literal["", "left", "right"] = ""
    # YT 直播封面：附圖是無文字底圖，改完仍須無文字（文字由程式疊）。
    # 見 news_prompt.TEXT_FREE_REFINE_RULES。
    text_free: bool = False
    # B63：具名換臉只接受這個結構化欄位，不從 instruction 猜姓名。
    replacement_person: str = ""
    # B63：有提供時，purpose="portrait" 的第一張使用者上傳肖像優先於自動查圖。
    reference_images: list[UserReferenceImage] = Field(
        default_factory=list, max_length=MAX_INPUT_REFERENCES
    )
    # B51（2026-09-16）：結構化的封面種類，白名單值見 editor_formats.COVER_REFINE_KINDS。
    # 非空時 refine_image() 直接跳過 resolve_frame_plan()，不置對位框——封面的固定元素
    # （Logo／節目標籤／日期）由前端 recompose 貼，置框會把整張畫面縮放/推出版面，
    # 角標跟著跑位。刻意不依 safe_frame_profile 這個角色字串猜（編輯身分一律會被
    # resolve_frame_plan 置框，見該函式 docstring），白名單值不對就讓 pydantic 擋掉，
    # 不接受任意 client 拿它繞過一般編輯圖片的安全框。
    cover_kind: Literal[
        "", "ten_cover", "yt_live_cover", "yt_hourly_cover", "yt_live24_cover", "yt_hot_cover"
    ] = ""
    # B84（2026-09-22）：消化檔位。這裡以前沒有這格，於是 image_generation_size()
    # 永遠看到 density=""，F38 的高解析度閘門在追加修改這條路上**從來沒有成立過**
    # ——字多／字超多生成的圖只要一改就悄悄掉回 1K 畫布。語意同
    # ImageGenerateRequest.density，前端原樣送回這次那張圖用的檔位。
    density: str = ""
    # B83（2026-09-22）：上一張成品**實際**貼的標籤，原樣帶回來重貼。這條路以前
    # 完全沒有貼標籤這件事（refine 直呼 generate_image_raw，從不經過
    # apply_image_disclaimer），所以「畫面來源」與「示意圖」追加修改後都會整個消失。
    # 刻意不重判：refine 不送 portrait_subjects，重判會把「示意圖」降級成
    # 「畫面來源」（見 ImageGenerateResponse 同名欄位）。
    disclaimer_kind: Literal["", "ai", "source"] = ""
    disclaimer_source_text: str = Field(default="", max_length=40)
    disclaimer_corner: Literal[
        "lower_right", "lower_left", "upper_right", "upper_left", "lower_center"
    ] = "lower_right"


@app.post(
    "/api/images/refine",
    response_model=ImageGenerateResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
def refine_image(req: ImageRefineRequest) -> ImageGenerateResponse:
    """追加指令修改既有圖（PLAN.md ③）。

    刻意不重用 /api/images/generate：那條的語意是「從 prompt 生成」，refine 的
    語意是「以附圖為基礎改圖」，混在同一個函式裡兩種行為會打架。
    這條**不呼叫消化端**（省錢也省時間）——指令直接組進 refine prompt。
    """
    request_id = request_log.new_request_id()
    started = _generation_clock()
    _reset_generation_retries()
    reset_portrait_notices()
    prompt = ""
    try:
        if not supports_reference_image(req.provider):
            raise HTTPException(
                status_code=400,
                detail="目前的生圖後端無法附上參考圖，無法以圖改圖；請整張重新生成",
            )
        replacement_person = req.replacement_person.strip()
        replacement_mode = ""
        replacement_reference = ""
        replacement_images = [
            ref for ref in req.reference_images if ref.purpose == "portrait"
        ][:1]
        if replacement_person and replacement_images:
            replacement_mode = "user_uploaded"
        elif replacement_person:
            outcome = lookup_portrait_outcomes([replacement_person]).get(replacement_person)
            if outcome is not None and outcome.photo is not None:
                replacement_mode = "wikipedia_photo"
                replacement_reference = outcome.photo.data_url()
                replacement_images = [
                    UserReferenceImage(data_url=replacement_reference, purpose="portrait")
                ]
            elif outcome is not None and outcome.entry_found:
                replacement_mode = "entry_only"
                _record_portrait_notice(portrait_entry_only_notice([replacement_person]))
            else:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"無法完成具名換臉：「{replacement_person}」：查不到對應的 Wikipedia "
                        "人物條目，不能讓模型自行捏造一張臉。請改走「原圖放置」並自行上傳照片。"
                    ),
                )
        image_req = ImageGenerateRequest(
            prompt=build_refine_prompt(
                req.instruction,
                text_free=req.text_free,
                replacement_person=replacement_person,
                replacement_mode=replacement_mode,
            ),
            provider=req.provider,
            aspect_ratio=req.aspect_ratio,
            image_size=req.image_size,
            # B84：檔位要跟著過來，F38 的高解析度閘門才判得出來（見欄位說明）
            density=req.density,
            safe_frame=req.safe_frame,
            frame_strategy=req.frame_strategy,
            safe_frame_profile=req.safe_frame_profile,
            broadcast_hole=req.broadcast_hole,
            hole_side=req.hole_side,
            reference_image_data_url=(
                f"data:{req.source_mime_type};base64,{req.source_image_base64}"
            ),
            reference_images=replacement_images if replacement_person else [],
            # B83：原樣帶回上一張實際貼的標籤，不重判（見欄位說明）。具名換臉一定是
            # 模型畫的臉，這裡強制「示意圖」——否則使用者只要把來源名留著，一張換過
            # 臉的圖就會掛上「畫面來源」。
            disclaimer_kind="ai" if replacement_person else req.disclaimer_kind,
            disclaimer_source_text=(
                "" if replacement_person else req.disclaimer_source_text
            ),
            disclaimer_corner=req.disclaimer_corner,
        )
        image_req = apply_broadcast_hole_layout_to_image_request(image_req)
        prompt = image_req.prompt
        if req.cover_kind:
            # B51：封面追加修改一律不置框——resolve_frame_plan 對編輯身分永遠回
            # needs_frame=True（兩檔都是滿版生成＋後製，見該函式 docstring），照舊問
            # 下去只要使用者是編輯就一定被置框，safe_frame=False 完全無效。封面的
            # 固定元素靠前端 recompose 貼，不能讓對位框把角標／Logo 縮放推出版面。
            needs_frame, frame_profile = False, safe_area_spec.REPORTER_PROFILE
        else:
            # 追加修改也要走同一個解析點，否則編輯 OFF 改完圖會整個跳過後製，
            # 出來一張沒置框的原始生成圖（尺寸與版面都不對，卻不會報錯）。
            _, needs_frame, frame_profile = resolve_frame_plan(
                req.safe_frame_profile, req.safe_frame, req.density
            )
        if not req.cover_kind and not req.broadcast_hole and model_extension_active(
            req.safe_frame_profile, req.safe_frame, req.frame_strategy
        ):
            # D26：改過的圖要重驗一次（模型可能把字改到框外）
            result = finalize_model_extension(
                generate_image_raw(image_req),
                aspect_ratio=req.aspect_ratio,
                canvas=image_generation_size(image_req)[1],
                allow_no_text=req.density == "no_text",
            )
        else:
            result = finalize_image_result(
                generate_image_raw(image_req),
                aspect_ratio=req.aspect_ratio,
                safe_frame=needs_frame,
                profile=frame_profile,
                broadcast_hole=req.broadcast_hole,
                canvas=image_generation_size(image_req)[1],
            )
        # B83（2026-09-22）：這一段以前整個不存在——refine 從不貼標籤，所以
        # 「畫面來源」與「示意圖」追加修改後都會消失。條件與 generate_image()
        # 的同一行一字不差（挖空框自己已經貼過浮水印，不重貼第二次）。
        if image_req.disclaimer_kind and not req.broadcast_hole:
            result = apply_image_disclaimer(result, image_req, profile=frame_profile)
    except Exception as exc:
        _record_generation_failure(
            request_id, started, exc,
            source="web-refine", news_text="", prompt=prompt, provider=req.provider,
        )
        raise
    meta = _outcome_meta(started, provider=req.provider, image_model=result.model)
    request_log.log_generation(
        request_id=request_id,
        source="web-refine",
        news_text="",
        prompt=image_req.prompt,
        provider=req.provider,
        image_model=result.model,
        digest_model=meta["digest_model"],
    )
    _archive_generation(
        request_id=request_id,
        image_base64=result.image_data_base64,
        mime_type=result.mime_type,
        source="web-refine",
        prompt=image_req.prompt,
        **meta,
    )
    notices = collected_portrait_notices()
    if notices:
        result = result.model_copy(update={"notices": notices})
    return result


# ---- F47：事後重貼「示意圖」／「畫面來源」標籤（2026-09-22 使用者要求）----
#
# 使用者原話：「畫面來源(與AI示意圖標籤) 的位置，是 PILLOW，理論上成圖之後要讓
# 使用者修改位置」。確實如此——貼標籤這件事從頭到尾沒有模型參與
# （compose.paste_disclaimer_note 是純 Pillow），但角落以前只能在**生圖前**選，
# 想換一個角落就得整張重生一次，等於為了挪一行字付一次生圖費。
#
# 這支端點拿回應裡那張**置框前原圖**（source_image_base64），照原本的參數重跑
# 置框→挖空框→貼標籤，得到的成品與當初那張逐像素相同、只差標籤位置。
# 一次生圖 API 都不打。
#
# ⚠️ 不接受「把成品送回來再貼一次」：成品上已經有一枚標籤，再貼會變兩枚，而且
# 對位框那條路會二次拉伸（失真疊加，見 ImageGenerateResponse 欄位說明）。所以
# 收的一律是置框前原圖；未置框且未貼標籤（source_image_base64 為空）才送成品本身，
# 規矩與 /api/images/refine 完全一致。
class ImageRestampRequest(BaseModel):
    # 置框「前」的原始生成圖（base64，不是 data URL），同 ImageRefineRequest。
    source_image_base64: str = Field(min_length=1, max_length=28_000_000)
    source_mime_type: str = "image/png"
    model: str = ""
    # 下面這組必須與當初那次生圖**完全一致**，否則重算出來的不是同一張圖：
    # 畫布尺寸由 image_generation_size() 依 provider／density／檔位／角色推導，
    # 少帶一個（尤其 density）就會把一張 2K 成品悄悄重算成 1K。
    provider: Literal["gemini", "gpt"] = "gemini"
    aspect_ratio: str = "16:9"
    image_size: str = "1K"
    density: str = ""
    safe_frame: bool = False
    # D26：延伸背景模式要跟著過來，否則改完／重貼會被 FIT 縮小補底色。
    frame_strategy: Literal["", "model_extension"] = ""
    safe_frame_profile: str = "記者"
    broadcast_hole: str = ""
    # 要貼的標籤：kind 與文字原樣沿用上一張（不重判，理由同 refine），
    # 只有 corner 是這次真正要改的東西。
    disclaimer_kind: Literal["ai", "source"]
    disclaimer_source_text: str = Field(default="", max_length=40)
    disclaimer_corner: Literal[
        "lower_right", "lower_left", "upper_right", "upper_left", "lower_center"
    ]


@app.post(
    "/api/images/restamp-disclaimer",
    response_model=ImageGenerateResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
def restamp_disclaimer(req: ImageRestampRequest) -> ImageGenerateResponse:
    """把標籤改貼到另一個角落，不重新生圖（F47）。"""
    request_id = request_log.new_request_id()
    started = _generation_clock()
    try:
        if req.disclaimer_kind == "source" and not req.disclaimer_source_text.strip():
            raise HTTPException(status_code=400, detail="畫面來源文字不可空白")
        if req.broadcast_hole:
            # 播出鏡面的標籤版位綁在挖空框上，不能單獨挪動。
            raise HTTPException(
                status_code=400,
                detail="播出鏡面的「示意圖」浮水印位置綁在挖空框上，不能單獨挪動",
            )
        base = ImageGenerateResponse(
            image_data_base64=req.source_image_base64,
            mime_type=req.source_mime_type,
            model=req.model,
        )
        sizing = ImageGenerateRequest(
            prompt="restamp",  # 只為了算畫布，不會送給任何模型
            provider=req.provider,
            aspect_ratio=req.aspect_ratio,
            image_size=req.image_size,
            density=req.density,
            safe_frame=req.safe_frame,
            frame_strategy=req.frame_strategy,
            safe_frame_profile=req.safe_frame_profile,
            disclaimer_kind=req.disclaimer_kind,
            disclaimer_source_text=req.disclaimer_source_text,
            disclaimer_corner=req.disclaimer_corner,
        )
        _, needs_frame, frame_profile = resolve_frame_plan(
            req.safe_frame_profile, req.safe_frame, req.density
        )
        if model_extension_active(
            req.safe_frame_profile, req.safe_frame, req.frame_strategy
        ):
            # D26：同一張原圖、同一支確定性守門，結果與當初生成時相同
            result = finalize_model_extension(
                base,
                aspect_ratio=req.aspect_ratio,
                canvas=image_generation_size(sizing)[1],
                allow_no_text=req.density == "no_text",
            )
        else:
            result = finalize_image_result(
                base,
                aspect_ratio=req.aspect_ratio,
                safe_frame=needs_frame,
                profile=frame_profile,
                canvas=image_generation_size(sizing)[1],
            )
        result = apply_image_disclaimer(result, sizing, profile=frame_profile)
    except Exception as exc:
        # 失敗也要留紀錄：這條路沒有生圖模型可以怪，出事一定是置框或貼字，
        # 後台查得到才知道是哪一種（沿用 web-refine 的同一套失敗歸檔）。
        _record_generation_failure(
            request_id, started, exc,
            source="web-restamp", news_text="", prompt="", provider=req.provider,
        )
        raise
    # 交出去的成品換了一張（標籤挪了角落），後台就得記一筆——不記的話稽核裡
    # 停在舊角落那版，跟使用者手上那張對不起來。分類是「合成」（純 Pillow，
    # 沒有生圖模型，耗時量級與其他端點不同），見 audit_archive.record_action。
    meta = _outcome_meta(started, provider=req.provider, image_model=result.model)
    _archive_generation(
        request_id=request_id,
        image_base64=result.image_data_base64,
        mime_type=result.mime_type,
        source="web-restamp",
        prompt="",
        **meta,
    )
    return result


def resolve_digest_portraits(
    digest: GenerateResponse, req: NewsImageGenerateRequest, provider: str
) -> tuple[GenerateResponse, dict[str, photo_lookup.ReferencePhoto]]:
    """查參考照；只有連維基條目都查不到的人才重新消化排出版面。

    回傳 (最終採用的消化結果, 已查到的照片)。

    為什麼要重新消化而不是在生圖階段處理（2026-08-18 使用者裁決）：
    2026-08-18 實測 2/2 證明，叫生圖模型「只畫有照片的人、沒照片的畫剪影」完全無效
    ——沒照片的那位被憑空捏臉還掛上真名。而且要拿掉的不只是一張臉：那個人的姓名條、
    引言框、版位都要重新安排，本來就只有消化端做得到。消化端是文字模型，遵守指示
    可靠得多。他們的話仍會以純文字留在圖上（使用者 2026-08-18 補充），只是不畫臉。

    **只重試一次**：第二次消化可能又挑出別的沒照片的人，無限重試會一直燒消化費用。
    第二次仍有人查不到就交給 resolve_portraits 退回全員不畫臉——那仍是可播的結果。
    一次消化只要幾分錢，遠比浪費一次生圖便宜。
    """
    subjects = digest.portrait_subjects
    if not subjects or not supports_reference_image(provider):
        return digest, {}

    outcomes = lookup_portrait_outcomes(
        subjects, digest.portrait_subjects_en, digest.portrait_subjects_en_guess,
        req.news_text,
    )
    photos = {
        name: outcome.photo
        for name, outcome in outcomes.items()
        if outcome.photo is not None
    }
    missing = [name for name in subjects if name not in photos]
    entry_only = [name for name in missing if outcomes[name].entry_found]
    lookup_failed = [name for name in missing if outcomes[name].lookup_failed]
    no_entry = [
        name for name in missing
        if not outcomes[name].entry_found and not outcomes[name].lookup_failed
    ]
    if PORTRAIT_NO_ENTRY_FALLBACK:
        told = entry_only + no_entry
        if told:
            _record_portrait_notice(portrait_entry_only_notice(told))
        if lookup_failed:
            print(
                f"[portrait] 肖像查詢失敗（{'、'.join(lookup_failed)}），保留安全退路",
                flush=True,
            )
        return digest, photos
    if not no_entry:
        if entry_only:
            _record_portrait_notice(portrait_entry_only_notice(entry_only))
        return digest, photos

    print(
        f"[portrait] 連維基條目都查不到（{'、'.join(no_entry)}），重新消化一次把他們排出版面",
        flush=True,
    )
    retried = generate(
        GenerateRequest(
            news_text=req.news_text,
            type_label=req.type_label,
            role=req.role,
            density=req.density,
            safe_frame=req.safe_frame,
            user_instruction=req.user_instruction,
            stamp=req.stamp,
            tone=req.tone,
            editor_format=req.editor_format,
            hole_side=req.hole_side,
            exclude_people=no_entry,
        )
    )
    if not retried.portrait_subjects:
        return retried, {}
    retried_outcomes = lookup_portrait_outcomes(
        retried.portrait_subjects, retried.portrait_subjects_en,
        retried.portrait_subjects_en_guess, req.news_text,
    )
    photos = {
        name: outcome.photo
        for name, outcome in retried_outcomes.items()
        if outcome.photo
    }
    retried_missing = [name for name in retried.portrait_subjects if name not in photos]
    retried_entry_only = [
        name for name in retried_missing if retried_outcomes[name].entry_found
    ]
    retried_no_entry = [
        name for name in retried_missing if not retried_outcomes[name].entry_found
    ]
    if retried_entry_only:
        _record_portrait_notice(portrait_entry_only_notice(retried_entry_only))
    if retried_no_entry:
        print(
            f"[portrait] 重新消化後仍有人連維基條目都查不到（{'、'.join(retried_no_entry)}），不再重試",
            flush=True,
        )
    return retried, photos


def generate_news_image(req: NewsImageGenerateRequest) -> NewsImageGenerateResponse:
    # 前置過濾（縱深防禦）：擋垃圾／亂碼／注入輸入，避免燒掉付費呼叫。
    # LINE 路徑在 line_bot 已含頻率限制地查過一次，這裡 client_id 為空時
    # 只做內容檢查、不重複觸發頻率限制。
    reset_portrait_notices()
    request_id = request_log.new_request_id()
    started = _generation_clock()
    _reset_generation_retries()
    # 編輯固定 GPT＋16:9＋對位框；記者維持呼叫端 provider、safe_frame 時 21:9
    provider = "gpt" if req.role == "編輯" else req.provider
    aspect_ratio = resolve_aspect_ratio(req.aspect_ratio, req.safe_frame, req.role)
    digest = None
    prompt = ""
    token = _inside_pipeline.set(True)
    try:
        verdict = check_input(req.news_text, client_id=req.client_id)
        if not verdict.accepted:
            raise HTTPException(status_code=400, detail=verdict.user_message)
        if req.client_id:
            note_accepted(req.news_text, client_id=req.client_id)
        digest = generate(
            GenerateRequest(
                news_text=req.news_text,
                type_label=req.type_label,
                role=req.role,
                density=req.density,
                safe_frame=req.safe_frame,
                user_instruction=req.user_instruction,
                stamp=req.stamp,
                tone=req.tone,
                editor_format=req.editor_format,
                hole_side=req.hole_side,
                visual_creativity=req.visual_creativity,
                # F0：這支端點自己重組一份 GenerateRequest，漏掉哪個欄位都不會報錯，
                # 只會安靜地讓網頁版有、LINE／整合端沒有。
                seed=req.seed,
            )
        )
        digest, portrait_photos = resolve_digest_portraits(digest, req, provider)
        portrait_mode, reference_photos = resolve_portraits(
            digest.portrait_subjects, provider, photos=portrait_photos
        )
        # B70：這張成品要不要程式端壓「示意圖」標籤，由 portrait_mode 決定
        # （見 resolve_image_disclaimer）。這條管線沒有「畫面來源」的來源可填，
        # 所以只傳 portrait_mode，source_text 用預設空字串。
        disclaimer_kind, _disclaimer_text = resolve_image_disclaimer(portrait_mode)
        prompt = build_prompt(
            role=req.role,
            engine=provider,
            type_label=digest.chart_type or req.type_label,
            style=digest.style,
            structure=digest.structure,
            variable=compose_variable(digest.variable),
            safe_frame=req.safe_frame,
            aspect_ratio=aspect_ratio,
            portrait_mode=portrait_mode,
            # 無字檔（D14／F20）：消化端已經產出空的 variable，生圖端還要一段
            # 明文覆蓋才壓得住前面那些「把 VARIABLE FIELDS 畫上去」的條款。
            no_text=(req.density == "no_text"),
            hole_side=broadcast_layout_hole_for(req),
        )
        image = generate_image(
            ImageGenerateRequest(
                prompt=prompt,
                provider=provider,
                broadcast_hole=broadcast_hole_for(req),
                hole_side=broadcast_layout_hole_for(req),
                aspect_ratio=aspect_ratio,
                image_size=req.image_size,
                density=req.density,
                safe_frame=req.safe_frame,
                # 傳角色而非解析後的 profile：generate_image 會解析一次，
                # 這裡先解析會讓它拿「編輯安全框」當角色再解析一次而解錯。
                safe_frame_profile=req.role,
                # 地圖類的真實座標。generate_image 會據此拼底圖並附上去；
                # 送不出參考圖的後端會安靜略過（見 apply_map_reference_to_image_request）。
                map_points=digest.map_points,
                # 單人走既有的單張欄位（措辭與行為與放寬前逐字相同），
                # 2-3 人才走多張通道
                reference_image_data_url=(
                    reference_photos[0].data_url()
                    if len(reference_photos) == 1
                    else ""
                ),
                portrait_reference_data_urls=(
                    [photo.data_url() for photo in reference_photos]
                    if len(reference_photos) > 1
                    else []
                ),
                disclaimer_kind=disclaimer_kind,
            )
        )
        meta = _outcome_meta(started, provider=provider, image_model=image.model)
        request_log.log_generation(
            request_id=request_id,
            source=req.source or "news-image",
            client_id=req.client_id,
            news_text=req.news_text,
            style=digest.style,
            structure=digest.structure,
            variable=digest.variable,
            prompt=prompt,
            chart_type=digest.chart_type,
            type_label=req.type_label,
            role=req.role,
            density=req.density,
            provider=provider,
            image_model=image.model,
            prompt_version=PROMPT_VERSION,
            portrait_subject="、".join(digest.portrait_subjects),
            portrait_mode=portrait_mode,
            # 多人時把每一張的出處都記下來——回查時要能一位一位對，
            # 只記第一張等於另外兩張沒有出處可查
            portrait_photo_source="、".join(
                photo.source_page for photo in reference_photos
            ),
            seed=digest.seed,
            digest_model=meta["digest_model"],
        )
        # LINE 版圖檔已由 line_bot.py 存進 static/generated/，這裡只補網頁版的缺口
        if req.source != "line":
            _archive_generation(
                request_id=request_id,
                image_base64=image.image_data_base64,
                mime_type=image.mime_type,
                source=req.source or "news-image",
                client_id=req.client_id,
                news_text=req.news_text,
                style=digest.style,
                structure=digest.structure,
                variable=digest.variable,
                prompt=prompt,
                chart_type=digest.chart_type,
                type_label=req.type_label,
                role=req.role,
                density=req.density,
                portrait_subject="、".join(digest.portrait_subjects),
                seed=digest.seed,
                **meta,
            )
        return NewsImageGenerateResponse(
            image_data_base64=image.image_data_base64,
            mime_type=image.mime_type,
            model=image.model,
            title=_extract_title(digest.variable),
            request_id=request_id,
            source_image_base64=image.source_image_base64,
            source_mime_type=image.source_mime_type,
            # 回報實際用的那顆（沒帶 seed 時是消化階段現抽的）
            seed=digest.seed,
            notices=collected_portrait_notices(),
        )
    except Exception as exc:
        fields = {
            "source": req.source or "news-image",
            "client_id": req.client_id,
            "news_text": req.news_text,
            "prompt": prompt,
            "type_label": req.type_label,
            "role": req.role,
            "density": req.density,
            "provider": provider,
        }
        if digest is not None:
            fields.update(
                style=digest.style,
                structure=digest.structure,
                variable=digest.variable,
                chart_type=digest.chart_type,
            )
        _record_generation_failure(request_id, started, exc, **fields)
        raise
    finally:
        _inside_pipeline.reset(token)


@app.post(
    "/api/news-image/generate",
    response_model=NewsImageGenerateResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
def news_image_generate(req: NewsImageGenerateRequest) -> NewsImageGenerateResponse:
    return generate_news_image(req)


# ============================================================
# 編輯專屬版型 B：十點不一樣封面圖
#
# 刻意不走 generate_news_image：那條是「新聞原文 → 消化 → 一張 CG」，這裡是
# 「使用者給兩個標題 → 兩張無文字底圖 → 程式合成」，中間根本沒有消化這一段。
# 硬塞進同一條會讓兩邊都變醜。前端仍在同一頁、同一個下拉選到它（見 app.js）。
#
# 文字全部由 compose.compose_ten_cover 用字型畫，不交給模型：Logo 畫了會變形、
# 中文標題畫了會有錯字，而封面圖上的錯字是對外事故。
# ============================================================


class TenCoverRequest(BaseModel):
    title_left: str = Field(min_length=1, max_length=40)
    # 2026-09-07：layout=full（滿版）只有一個標題，title_right 允許空；split（雙切）兩個都要
    title_right: str = Field(default="", max_length=40)
    # 2026-09-08 WP1：可省略。沒帶時由 editor_formats.resolve_cover_layout 依第二標題
    # 自動判定（有值＝雙切、空＝滿版）；有帶就以請求為準（舊呼叫端與 ten_cover_full 別名）。
    layout: Literal["split", "full"] | None = None
    # 給生圖模型的視覺描述（畫什麼場景），不會出現在成品文字上。
    # 2026-09-03 起改選填：留空時由 resolve_cover_visuals 依標題請文字模型補。
    # 2026-09-08 WP1 起前端不再有這兩個輸入欄（改用下面的 instruction），欄位保留給
    # 舊呼叫端與回填相容；resolve_cover_visuals 仍會把有值的那欄原樣沿用。
    visual_left: str = Field(default="", max_length=500)
    visual_right: str = Field(default="", max_length=500)
    # 給 AI 的指令（2026-09-08 WP1：封面／YT 版型重新顯示這一欄）。餵給
    # resolve_cover_visuals 的推導步驟當畫面提示，兩格共用——不直接拼進生圖 prompt，
    # 那條線的規則明令底圖不得出現任何文字，指令裡的字會被模型畫上去。
    instruction: str = Field(default="", max_length=500)
    # 新聞原文（B53，2026-09-16）：選填，有預設值不影響舊呼叫端。畫面描述只餵標題
    # 時模型會認錯同名人物、拼錯英文名（見 MASTER 列管 B53）。有這欄時
    # resolve_cover_visuals 會把它和標題一起當補畫面描述的來源材料。
    news_text: str = Field(default="", max_length=20_000)
    date_text: str = Field(default="", max_length=20)
    badge: str = compose.COVER_DEFAULT_BADGE
    provider: Literal["gemini", "gpt"] = "gpt"
    # ai＝整張交給生圖模型畫（要設計感，2026-09-03 使用者裁決）
    # composite＝AI 只出兩張無文字底圖、文字由 Pillow 畫（零錯字）
    # 省略（None）＝交給 editor_formats.title_mode_for_creativity 依創意等級挑預設
    #（0 級 → composite，1 級起 → ai）。2026-09-14 晚：0 級不再鎖死，明送 ai 就照辦。
    mode: Literal["ai", "composite"] | None = None
    # 2026-09-08 使用者要求：AI 整張版的標題要有「設計感＋滿框」的選項（像節目片頭字卡）。
    # plain＝現行排版（預設）；designed＝在 TYPOGRAPHY 段追加 COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE。
    # 只影響 mode=ai：合成版的字是 Pillow 畫的，排版由 compose 的常數決定，這個欄位用不到。
    title_style: Literal["plain", "designed"] | None = None
    # 2026-09-09 第八批 使用者：「創意奔放程度能不能設好幾個等級，讓使用者自己選」
    # ——前台改成 0–4 的拉桿（像 AI effort 那條）。上面的 title_style 降級成別名，
    # 只為了舊呼叫端：沒帶 title_creativity 時 plain→0、designed→4；兩個都帶以本欄為準。
    title_creativity: int | None = Field(
        default=None, ge=editor_formats.COVER_AI_TITLE_LEVEL_MIN,
        le=editor_formats.COVER_AI_TITLE_LEVEL_MAX,
    )
    # 側邊標籤（2026-09-10）：使用者自己打的幾個短詞，畫成一排小籤。空白＝不畫。
    # 刻意由使用者填而不是讓 AI 想——理由見 editor_formats.cover_side_labels_block。
    side_labels: str = Field(default="", max_length=120)
    # 畫面小籤（2026-09-11）：地點籤、數據徽章、危險標示那種散落在畫面上的小牌。
    # 同樣由使用者自己填——理由與側邊標籤相同，見 editor_formats.cover_info_chips_block。
    info_chips: str = Field(default="", max_length=120)
    # 「畫面來源」（F43，2026-09-20）：只在那一格是原圖放置（asis，非 AI 生）時才會
    # 顯示——與「AI示意圖」互斥，AI 標籤贏（見 compose.compose_ten_cover）。**只對
    # mode="composite" 生效**：mode="ai" 那條路整張都是模型畫的（即使附了 asis 參考圖，
    # 那也只是生圖的參考依據，成品像素仍是模型重繪的），沒有「保證原圖未被動過」的前提，
    # 掛「畫面來源」等於對觀眾說謊，_cover_full_composite／_cover_composite 只在
    # mode="composite" 分支才會讀這兩欄。純使用者輸入（跟 title_left 同一類），
    # 「只改文字」重壓時前端原樣重送即可，不像 background_is_ai 需要另開一欄carry
    # forward——那個是後端算出來的衍生值，這個是使用者自己打的字，同一欄位重送就好。
    # 空字串＝不標。滿版（layout=full）只有一格，只看 source_left。
    source_left: str = Field(default="", max_length=40)
    source_right: str = Field(default="", max_length=40)

    def creativity_level(self) -> int:
        if self.title_creativity is not None:
            return self.title_creativity
        return editor_formats.COVER_TITLE_STYLE_LEVELS.get(self.title_style or "", 0)
    # 2026-09-06：十點也收附圖。用途 asis（原圖放置）1 張＝整版鋪滿（使用者裁決，不切格）、
    # 2 張＝左格、右格。
    # 2026-09-13 使用者裁決起這段註解已過時：composite 模式才是「真照不進生圖模型」；
    # AI 標題模式（COVER_MODE_AI）下 ai_over_base 這條路一樣把 asis 真照當唯一附圖送進
    # 模型（見 _editor_cover_full／_cover_ai），只是原圖放置只有 1 張時，B55（2026-09-16）
    # 起會在模型輸出後用 compose.restore_photo_outside_title_band 把字帶以外的像素強制
    # 還原成原檔，不讓模型「重畫整張」的通病波及照片本身。
    # 其他用途（實景／肖像／地圖）當兩格 AI 底圖的生圖參考。
    reference_images: list[UserReferenceImage] = Field(
        default_factory=list, max_length=MAX_INPUT_REFERENCES
    )
    # 2026-09-07 使用者裁決：左右格各自一個上傳位，才不會分不清哪張是左、哪張是右。
    # data URL；有圖的那格直接上版，沒圖的那格照舊生底圖（左有右無＝只生右格）。
    # 兩欄都空時才退回上面 reference_images 的 asis 順序規則（舊呼叫端相容）。
    asis_left: str = Field(default="", max_length=2_800_000)
    asis_right: str = Field(default="", max_length=2_800_000)
    # 2026-09-13：每一格改收一份清單，每張各有自己的用途（原圖放置／AI改圖／實景／
    # 肖像／地圖）。上面兩個字串欄位留著給舊呼叫端，讀法一律走 slot_refs()。
    slot_left: list[UserReferenceImage] = Field(
        default_factory=list, max_length=MAX_INPUT_REFERENCES
    )
    slot_right: list[UserReferenceImage] = Field(
        default_factory=list, max_length=MAX_INPUT_REFERENCES
    )

    def slot_refs(self, side: int) -> list[UserReferenceImage]:
        """第 side 格（0＝左／滿版、1＝右）的附圖清單。雙切的半格 >1 張時原圖放置轉 AI改圖
        （見 lock_half_slot_asis）；滿版那一格不鎖——多張原圖走自動切格。"""
        refs = slot_reference_list(
            self.slot_left if side == 0 else self.slot_right,
            self.asis_left if side == 0 else self.asis_right,
        )
        if editor_formats.resolve_cover_layout(self.layout, self.title_right) == "split":
            refs = lock_half_slot_asis(refs, "cover")
        elif side == 0:
            refs = merge_mixed_slot_to_aiedit(refs, "cover")
        return refs

    def slot_placements(self) -> tuple[str, str]:
        """左右兩格直接上版的圖（data URL；沒有就是空字串）。"""
        return (
            slot_placement_url(self.slot_refs(0), "cover"),
            slot_placement_url(self.slot_refs(1), "cover"),
        )

    # 追加修改後回來重貼固定元素（2026-09-07，比照 YT 封面的同名欄位）：純 AI 版的
    # 成品是「模型畫的整張圖＋程式後貼的 Logo／節目標籤／AI示意圖」，refine 改的是
    # 貼之前的模型原圖，改完要再走一次後貼才是成品。base64，不是 data URL。
    # 2026-09-08 起滿版合成版（layout=full＋mode=composite）也吃這個欄位，語意換成
    # 「只改文字」：帶回上一次的壓字前底圖，零 API 重壓一次標題（比照 YT 的 yt-cover:recomposite）。
    # 2026-09-14 起雙切合成版也吃：回應把「拼好但還沒壓字」的雙切底圖帶回來，這裡收到就
    # 只重壓兩個標題（compose_ten_cover prebuilt_split=True），不重拼也不重生任何一格。
    background_image_base64: str = Field(default="", max_length=28_000_000)
    background_mime_type: str = "image/png"
    # 那張底圖是不是 AI 生的——決定要不要壓「AI示意圖」。前端原樣帶回上一次的回應值。
    # 合成版的「只改文字」讀它（AI 版的後貼路徑本來就一定是模型圖）；雙切時它是左格，
    # 右格看 background_right_is_ai（回應的 right_is_ai 原樣帶回）。
    background_is_ai: bool = False
    background_right_is_ai: bool = False
    # 那張底圖是哪個版面生的（full／split）。滿版底圖是一張整圖、雙切底圖是拼好的兩格，
    # 光看 bytes 分不出來；前端帶回來才能在版面變了（改了第二標題）時明講 400，而不是
    # 默默把雙切標題壓在一張整圖上。空字串＝舊呼叫端沒帶，不檢查。
    background_layout: str = ""
    # 變化池的 seed（F0／D1）。None＝後端現抽一顆並在回應裡回報；帶了就照那顆抽，
    # 同一顆 seed ＝同一種長相。取代原本 seed=None 每次隨機、重現不出來的行為。
    seed: int | None = Field(default=None, ge=0, lt=SEED_MAX)


# 版型名稱：跟前台下拉選單（app.js 的 EDITOR_FORMATS.label）用同一組字，
# 後台「類型」欄就是編輯自己看得到的名字，不必再對照代碼。
# 這裡只列**會生圖**的版型；第一頁那條路徑走 type_label，本來就有值。
COVER_TYPE_LABEL_TEN = "十點不一樣"
COVER_TYPE_LABEL_YT = {
    "news": "YT國內外新聞直播",
    "hourly": "YT整點直播",
    "hot": "YT今日熱搜",
}
COVER_TYPE_LABEL_VSTRIP = "YT直播直標"


class TenCoverResponse(ImageGenerateResponse):
    # 這次實際採用的畫面描述（使用者留空時是 AI 補的）。前端會填回欄位——
    # 不回報的話使用者永遠不知道 AI 幫他決定了什麼，也沒辦法微調後重生。
    visual_left: str = ""
    visual_right: str = ""
    # 哪一格是 AI 底圖（決定「AI示意圖」印在哪格）；實際採用的模式（asis 會強制 composite）
    left_is_ai: bool = True
    right_is_ai: bool = True
    mode: str = editor_formats.COVER_MODE_AI
    # 「只改文字」用的壓字前底圖（合成版會帶：滿版＝整圖、雙切＝拼好的兩格）。刻意**不塞進 source_image_base64**：
    # 那格的語意是「餵回 /api/images/refine 的原圖」，合成版一律留空（見 tests/test_cover_refine.py
    # 的紅線 1）。兩者混用會讓前端的「修改」鈕誤以為合成版可以 refine。
    background_image_base64: str = ""
    background_mime_type: str = ""
    background_is_ai: bool = False
    # 那一格實際貼了「畫面來源」（F43，2026-09-20）。空字串＝這格沒有標——不論是
    # 因為那格是 AI 底圖（left_is_ai／right_is_ai=True）還是使用者沒填來源名。
    source_left: str = ""
    source_right: str = ""
    # 這次實際採用的 seed（F0）。前端拿它當「重新生成」的遞增起點。
    seed: int = 0


def ten_cover_asis_images(req: "TenCoverRequest") -> list[bytes]:
    """依順序取出「原圖放置」附圖的原始 bytes（最多兩張）。1 張＝全版、2 張＝左格＋右格。"""
    raws: list[bytes] = []
    asis = [ref for ref in req.reference_images if ref.purpose == "asis"]
    for ref in asis[:2]:
        raws.append(decode_attached_image(ref.data_url))
    if len(asis) > 2:
        print(f"[cover] 原圖放置附圖 {len(asis)} 張，十點封面只有兩格，只取前 2 張", flush=True)
    return raws


def ten_cover_slot_images(req: "TenCoverRequest") -> tuple[bytes | None, bytes | None]:
    """左右上傳位**直接上版**那張圖的原始 bytes；那格沒有原圖放置就是 None。

    None 不代表那格沒附圖——只放了 AI改圖／實景參考的格子也是 None，
    那格照樣要生底圖，只是生的時候帶著那些參考（見 slot_generation_refs）。
    """
    out: list[bytes | None] = []
    for data_url in req.slot_placements():
        if not data_url.strip():
            out.append(None)
            continue
        out.append(decode_attached_image(data_url))
    return out[0], out[1]


def ten_cover_uses_slots(req: "TenCoverRequest") -> bool:
    """有沒有用附圖位。格子裡只放了 AI改圖／參考圖也算——那些圖是指定給那一格的，
    退回共用清單會被兩格一起吃掉，等於使用者指的那一格失效。"""
    return bool(req.slot_refs(0) or req.slot_refs(1))




class CoverVisuals(tuple):
    """(visual_left, visual_right) 加上每格的具名真人名單（2026-09-07）。

    做成 tuple 子類別：既有呼叫端與測試都用 `left, right = resolve_cover_visuals(...)` 解包，
    mock 回傳純 tuple 也照樣能用（沒有 subjects 屬性就當沒有人）。
    """

    subjects: tuple[list[str], list[str]] = ([], [])
    english: tuple[list[str], list[str]] = ([], [])
    excluded: tuple[list[str], list[str]] = ([], [])
    # 這次查到的參考照（{人名: ReferencePhoto}，每格一份）。留著是為了落檔記出處
    # （portrait_photo_source），不是為了傳給生圖端——見 keep_subjects_with_photos。
    photos: tuple[dict, dict] = ({}, {})

    def __new__(cls, left: str, right: str, subjects=None, english=None, photos=None):
        self = super().__new__(cls, (left, right))
        self.subjects = tuple(subjects) if subjects else ([], [])
        self.english = tuple(english) if english else ([], [])
        self.photos = tuple(photos) if photos else ({}, {})
        return self


def cover_portraits(visuals, side: int) -> tuple[list[str], list[str]]:
    """從 resolve_cover_visuals 的結果取某一格（0 左／1 右）的肖像名單；純 tuple 就是沒有人。"""
    subjects = getattr(visuals, "subjects", ([], []))
    english = getattr(visuals, "english", ([], []))
    return list(subjects[side]), list(english[side])


def cover_excluded(visuals, side: int) -> list[str]:
    """某一格被剔除（查不到參考照）的人；純 tuple 或沒有就空清單。"""
    excluded = getattr(visuals, "excluded", None) or ([], [])
    return list(excluded[side]) if side < len(excluded) else []


def cover_portrait_photos(visuals, side: int) -> dict:
    """某一格查到的參考照；純 tuple（mock）就是沒有。"""
    photos = getattr(visuals, "photos", ({}, {}))
    return dict(photos[side])


COVER_EXCLUDED_PEOPLE_BLOCK = """

PEOPLE WHO MUST NOT APPEAR AS A FIGURE (OVERRIDES EVERYTHING ABOVE ABOUT THEM):
No Wikipedia entry could be confirmed for: {names}.
- Do not depict any of them as a human figure of any kind — not facing the camera, not turned away, not a faceless stand-in body. If the scene description mentions them, redesign the scene around non-person elements instead (buildings, venues, logos, signage, objects, documents) and leave them out as a figure entirely.
- Never invent, guess or approximate their facial features, and never place any of their names beside a drawn figure."""


def excluded_people_block(names: list[str]) -> str:
    """被剔除（連維基條目都查不到）的人：接在生圖 prompt 後的禁畫條款；沒有人就回空字串。"""
    names = [n for n in names if n]
    if not names:
        return ""
    return COVER_EXCLUDED_PEOPLE_BLOCK.format(names="、".join(names))


def keep_subjects_with_photos(
    subjects: list[str],
    english: list[str],
    *,
    guessed_english: list[str] | None = None,
    source_context: str = "",
    uploaded_portraits: int = 0,
    tag: str,
) -> tuple[list[str], list[str], dict, list[str]]:
    """依 F40 四層分流整理封面／YT 封面的肖像名單。

    回傳 (留在版面的人, 對應英文名, 查到的照片, **連條目都查不到**而被移除的人)。
    「留在版面的人」包含有照片的（第 1／2 層）與查得到條目但沒照片的（第 3 層，
    entry_only）——這些人下游 `apply_portrait_to_image_request`／`resolve_portraits`
    會依同一批查詢結果（有快取，重查很便宜）自己再判一次該用哪種肖像規則、
    要不要回 notice，這裡不用先分流出「entry_only」清單。只有第 4 層（連條目都
    查不到）才會被真正移出名單，交給呼叫端用 `excluded_people_block` 寫進 prompt。

    被移除的人**必須**由呼叫端接進 `excluded_people_block` 寫進生圖 prompt（2026-09-08 審查
    必修）：畫面描述仍寫著「兩人同框」，剩一人時走的單人肖像規則沒有「其他人不畫臉」條款，
    被剔除的那位會被模型憑空捏臉。

    封面與 YT 封面的 `apply_photo_availability` 等價物（2026-09-07）。主流程在**消化階段**
    就把查不到照片的人排出版面；封面這兩條線沒有消化階段，名單是補畫面描述時一併產生的，
    所以在同一個地方做。

    不做這件事會怎樣：`resolve_portraits` 是全有或全無——兩個人裡有一個查不到，
    整張退回不畫臉。使用者看到的是「明明有照片還是不見了」。

    使用者上傳的肖像照視為對應**系統查不到的人**、依序對應（假設與理由完整寫在
    `apply_photo_availability`）：`uploaded_portraits` 張就保留前幾位查不到的人，
    否則會把「正因為維基查不到才自己上傳照片」的那位刪掉。

    回傳的 photos 只用來落檔記出處。生圖端（`apply_portrait_to_image_request`）沒有可以
    收現成照片的參數，會再查一次——刻意接受這次重查，而不是為了省一次查詢在
    `ImageGenerateRequest` 上開一個只有封面用得到的欄位。查圖有快取層，重查很便宜。
    """
    if not subjects:
        return [], [], {}, []
    if guessed_english and any(name.strip() for name in guessed_english):
        outcomes = lookup_portrait_outcomes(
            subjects, english, guessed_english, source_context,
        )
    else:
        # 沒有猜測值時維持舊介面，既有呼叫與測試替身不用承擔無效參數。
        outcomes = lookup_portrait_outcomes(subjects, english)
    photos = {name: o.photo for name, o in outcomes.items() if o.photo is not None}
    missing = [name for name in subjects if name not in photos]
    if uploaded_portraits:
        missing = missing[uploaded_portraits:]
    if not missing:
        return list(subjects), list(english), photos, []
    # 沒有使用者肖像時，封面也跟一般 CG 的 B73 開關走；下游會整組改走
    # entry_only，不會把「有照片的畫、沒照片的猜臉」混在同一張。
    if PORTRAIT_NO_ENTRY_FALLBACK and not uploaded_portraits:
        return list(subjects), list(english), photos, []
    no_entry = [
        name for name in missing
        if not outcomes[name].entry_found and not outcomes[name].lookup_failed
    ]
    kept = [(name, en) for name, en in zip(subjects, english) if name not in no_entry]
    if not kept:
        # 全部都查無條目時**不清空名單**（刻意與 apply_photo_availability 不同）：
        # 主流程清掉之後會重新消化一次，版面描述也跟著不提那個人；封面這條線
        # 沒有第二次消化，畫面描述仍寫著「梅爾茨站在講台前正面半身」。名單一空，
        # apply_portrait_to_image_request 就不注入任何肖像規則，模型會替一個真名
        # 憑空捏一張臉——這個專案定義最糟的組合。保留名單才會走 no_reference
        # （現在是「無人場景」，不是背影／剪影），那仍是可播的結果。
        print(
            f"[{tag}] 查不到任何一位的照片或條目（{'、'.join(no_entry)}），"
            "保留名單走「無人場景」規則",
            flush=True,
        )
        return list(subjects), list(english), photos, []
    if no_entry:
        print(
            f"[{tag}] 查無條目（{'、'.join(no_entry)}），從肖像名單移除，"
            "剩下的人照樣處理",
            flush=True,
        )
    return [name for name, _ in kept], [en for _, en in kept], photos, no_entry


# ---- 標題斷句交給消化模型（2026-09-14 使用者裁決）----
# 使用者：「為何要依賴斷詞機制，這個機制會一直長胖，不讓生圖階段時自己判斷斷句」。
# 生圖模型畫出來的字沒辦法逐字驗，行數一變版面全連動，所以斷點要在能檢查的階段決定：
# 請消化模型把標題切成詞組，程式只做硬檢查（接回去等於原段），compose 只在詞組邊界上切。
# 失敗（逾時、格式壞、改了字）一律退回原本的規則，封面不會因此失敗。
# 2026-09-14 改小模型後 20 → 8 秒：mini 實測 4.6 秒，8 秒是它的近兩倍；超過就退回規則，
# 封面不會因此失敗，只是斷句差一點。
#
# 2026-09-16 實測後 8 → 10 秒（使用者裁定）。斷句換 gemini-3.8-flash 的 156 次實測裡，
# **6 次失敗有 4 次是撞在 8.0 這道牆上**，而中位數只有 2.2 秒、p90 5.5 秒——
# 也就是說牆的位置卡在分布的尾巴上，多給兩秒就能把那 4 次撈回來。
# ⚠ 順帶記一個實測發現：**這個值不是「總時長上限」**。它一路傳到 httpx 的 timeout，
# 而 httpx 算的是「兩段資料之間的間隔」；mini 實測有兩次分別跑了 8.29／8.96 秒仍然
# 順利回來（作廢的那批甚至有一次 33.1 秒 finish=stop）。所以放寬到 10 不代表
# 最壞情況就是 10 秒，只代表「卡在這道牆上的機率變低」。
TITLE_BREAK_TIMEOUT_SECONDS = 10.0
# 小模型（gpt-5.4-mini／nano）會把送去的「1. 」清單編號原樣抄回 text 與第一個詞組，
# 接回去就不等於原段、整段被丟掉——等於模型切了白切。送的時候不編號，回來的再剝一次。
_LIST_NUMBER_RE = re.compile(r"^\s*\d+\s*[.、)]\s*")


def _strip_list_number(text: str) -> str:
    return _LIST_NUMBER_RE.sub("", text, count=1)


def _normalise_break_phrases(phrases: list[str]) -> list[str]:
    """丟掉純編號的詞組（"1."／"1. "），第一個詞組前面黏的編號也剝掉。"""
    out = [p for p in phrases if not re.fullmatch(r"\s*\d+\s*[.、)]?\s*", p)]
    if out:
        out[0] = _strip_list_number(out[0])
    return [p for p in out if p]


def _break_match_text(text: str) -> str:
    """只供 hint 對位：忽略空白與全／半形差異，不把台／臺等實字當同字。"""
    return "".join(
        unicodedata.normalize("NFKC", ch)
        for ch in text
        if not ch.isspace()
    )


def _realign_break_phrases(original: str, phrases: list[str]) -> list[str] | None:
    """把模型的安全等價邊界套回原文，成品永遠使用原始字元。

    模型偶爾把全形標點改半形或吃掉空白；舊版因嚴格字串不等直接丟 hint。只有 NFKC
    與空白差異才對位，任何實字變更仍拒收。邊界若落在單一原字的正規化展開中也拒收。
    """
    if not phrases or _break_match_text("".join(phrases)) != _break_match_text(original):
        return None
    targets: list[int] = []
    length = 0
    for phrase in phrases[:-1]:
        length += len(_break_match_text(phrase))
        targets.append(length)
    cuts: list[int] = []
    seen = 0
    target_index = 0
    for index, char in enumerate(original, start=1):
        if not char.isspace():
            seen += len(unicodedata.normalize("NFKC", char))
        while target_index < len(targets) and seen == targets[target_index]:
            cuts.append(index)
            target_index += 1
        if target_index < len(targets) and seen > targets[target_index]:
            return None
    if target_index != len(targets):
        return None
    points = [0, *cuts, len(original)]
    return [original[points[i]:points[i + 1]] for i in range(len(points) - 1)]
# 一段 ≤ 7 字（COVER_TITLE_FILL_MIN_CHARS）永遠不會被拆，這種標題不必打模型。
TITLE_BREAK_MIN_CHARS = compose.COVER_TITLE_FILL_MIN_CHARS + 1


def title_break_inputs(*titles: str) -> list[str]:
    """要送去切詞組的段：使用者用空白分好的每一段，只留長到可能被拆的。"""
    out: list[str] = []
    for title in titles:
        for seg in editor_formats._COVER_TITLE_SPLIT_RE.split((title or "").strip()):
            seg = seg.strip()
            if len(seg) >= TITLE_BREAK_MIN_CHARS and seg not in out:
                out.append(seg)
    return out


def segment_titles_for_breaks(segments: list[str]) -> dict[str, list[str]]:
    """{段: [詞組...]}。模型沒回、回錯、改字的段不會出現在結果裡（那些退回規則）。"""
    segments = [s for s in segments if s]
    if not segments:
        return {}
    material = "\n".join(segments)
    started = time.monotonic()
    try:
        response = digest_completion(
            model=resolve_title_break_model(),
            system_prompt=editor_formats.TITLE_BREAK_SYSTEM,
            news_text=material,
            max_output_tokens=1200,
            schema_name="title_breaks",
            schema=editor_formats.TITLE_BREAK_SCHEMA,
            site="title-break",
            timeout=TITLE_BREAK_TIMEOUT_SECONDS,
        )
        data = parse_digest_json(response.choices[0].message.content or "")
    except Exception as exc:  # noqa: BLE001 — 斷句失敗退回規則，封面照出
        print(
            f"[title-break] 模型斷句失敗，退回規則（{time.monotonic() - started:.1f}s）："
            f"{type(exc).__name__}: {exc}", flush=True,
        )
        return {}
    print(f"[title-break] {resolve_title_break_model()} {time.monotonic() - started:.1f}s", flush=True)
    out: dict[str, list[str]] = {}
    for row in data.get("segments") or []:
        if not isinstance(row, dict):
            continue
        # 編號只在對不上原段時才剝：無條件剝會把「1.2兆資本支出」吃成「2兆資本支出」
        raw_text = str(row.get("text") or "")
        text = raw_text if raw_text in segments else _strip_list_number(raw_text)
        phrases = [str(x) for x in (row.get("phrases") or []) if str(x)]
        if "".join(phrases) != text:
            phrases = _normalise_break_phrases(phrases)
        if text not in segments:
            matches = [segment for segment in segments if _break_match_text(segment) == _break_match_text(text)]
            if len(matches) == 1:
                text = matches[0]
        if text in segments and "".join(phrases) != text:
            phrases = _realign_break_phrases(text, phrases) or phrases
        # B108：單一長機構名／人名本身就可能是完整不可拆詞。舊版要求至少兩個
        # phrase，模型正確回 ["中華民國中央銀行"] 也會被當成「沒切」丟掉，compose
        # 隨後回退到逐字硬切。這裡只驗忠實度；一個 phrase 是有效的「零個可切邊界」。
        if text in segments and len(phrases) >= 1 and "".join(phrases) == text:
            out[text] = phrases
        elif text:
            print(f"[title-break] 不採用（改了字或沒切）：{text!r} → {phrases!r}", flush=True)
    return out


def apply_title_break_hints(*titles: str) -> None:
    """封面端點入口呼叫：切詞組並登記給 compose；沒有要切的段就一次模型都不打。

    B109（2026-09-26 使用者裁決）撤回 B75 的 AI 模式守衛：十點與 YT（live24
    除外）的 AI 生圖 prompt 都會先由程式算好最終列，`compose.cover_title_lines()`／
    `fallback_split_title()` 會讀詞組邊界，所以 AI 模式也必須切。是否屬於會使用
    預切列的版型，由端點呼叫處判斷。

    ⚠ 無論走哪條路都**先把 hints 清空**：ContextVar 雖然是每個請求各自一份
    （見 compose 的 `_BREAK_HINTS` 註解），但「跳過就不設」會讓這個不變式
    依賴外部行為，清一次的成本是零。
    """
    compose.set_break_hints({})
    inputs = title_break_inputs(*titles)
    if inputs:
        compose.set_break_hints(segment_titles_for_breaks(inputs))


def resolve_cover_visuals(req: "TenCoverRequest") -> tuple[str, str]:
    """畫面描述留空時依標題補齊，並列出每格的具名真人。

    2026-09-07 使用者回報：十點封面把德國總理畫成背影。根因有二——這條線從沒接肖像查圖，
    且舊 prompt 明文禁止具名真人的臉。現在即使兩欄描述都填了也照打一次文字模型：不打就
    沒有 portrait_subjects，生圖規則會把具名真人一律畫成背影。
    """
    left, right = req.visual_left.strip(), req.visual_right.strip()

    material = 'LEFT headline: {}\nLEFT description already supplied: {}\nRIGHT headline: {}\nRIGHT description already supplied: {}'.format(
        req.title_left.strip(),
        left or "(none — write one)",
        req.title_right.strip(),
        right or "(none — write one)",
    )
    # 新聞原文（B53，2026-09-16）：選填，只有帶了才附加，留空時 material 與改動前
    # 逐字相同（rng_pins fixture 不受影響）。標題與原文都只是**來源素材**，明講
    # 不得逐字畫上圖——這段只餵給推導步驟當認人與畫面依據，畫面文字仍只能來自
    # portrait_subjects／視覺描述本身，不能把原文字句抄進 visual_left／visual_right。
    news_text = (getattr(req, "news_text", "") or "").strip()
    if news_text:
        material += (
            "\n\nNews article source material (background only, for identifying the correct "
            "named people and an accurate scene — do not copy its wording verbatim into your "
            "output, and the headline above is source material under the same rule): "
            + news_text
        )
    # 簡稱對照（B82，2026-09-21）：「川習會」這類事件簡稱裡沒有逐字人名，推導模型
    # 照 VERBATIM 規則不准認出他們，描述就退成「兩位領導人」、參考照零張、臉自己編。
    # 這裡由程式查表把人名補成**已知事實**再交給模型——查表是確定性的，跟放寬護欄
    # 讓模型自己聯想是兩回事。沒命中時回空字串，material 與加表之前逐字相同。
    material += name_aliases.alias_hint_block(
        req.title_left, req.title_right, left, right, news_text,
    )
    # 使用者的指令欄（2026-09-08 WP1）：兩格共用，只當畫面提示。放在最後、明講它
    # 管的是「畫面長什麼樣」——不然模型會把它讀成「標題要改成這樣」。
    instruction = (getattr(req, "instruction", "") or "").strip()
    if instruction:
        material += (
            "\n\nExtra instruction from the editor about how the photographs should look "
            "(applies to both sides; it is guidance for the scene, never text to render): "
            + instruction
        )
    model = resolve_digest_model()
    try:
        response = digest_completion(
            model=model,
            system_prompt=editor_formats.COVER_VISUAL_DERIVE_SYSTEM,
            news_text=material,
            # 同上：600 對推理模型太窄，一次思考尖峰就整條截斷。
            # 實測這條路徑只用 186（74 是思考），留到 2000 當緩衝。
            max_output_tokens=2000,
            schema_name="cover_visuals",
            schema=editor_formats.COVER_VISUAL_SCHEMA,
            site="cover",
        )
        data = parse_digest_json(response.choices[0].message.content or "")
    except Exception as exc:  # noqa: BLE001
        # 補描述失敗不該讓整張封面失敗：退回用標題本身當畫面提示，
        # 畫出來會比較平淡但仍是一張可用的封面。
        print(f"[cover] 自動補畫面描述失敗，改用標題：{type(exc).__name__}: {exc}", flush=True)
        return CoverVisuals(left or req.title_left.strip(), right or req.title_right.strip())

    derived_left = (data.get("visual_left") or "").strip()
    derived_right = (data.get("visual_right") or "").strip()
    # 上傳的肖像照兩格共用（附圖清單不分左右），所以每格都以同一個張數計。
    uploaded = sum(1 for ref in req.reference_images if ref.purpose == "portrait")
    subjects, english, photos, excluded = [], [], [], []
    for index, side in enumerate(("left", "right")):
        names = clean_portrait_subjects(data.get(f"portrait_subjects_{side}"))
        aligned = align_english_names(
            names,
            [str(x) for x in (data.get(f"portrait_subjects_{side}_en") or [])],
            [str(x) for x in (data.get(f"portrait_subjects_{side}") or [])],
        )
        guessed = align_english_names(
            names,
            [str(x) for x in (data.get(f"portrait_subjects_{side}_en_guess") or [])],
            [str(x) for x in (data.get(f"portrait_subjects_{side}") or [])],
        )
        # 查不到參考照的人先移除，不然 resolve_portraits 的「全有或全無」會讓
        # 查得到的那位也一起變背影（見 keep_subjects_with_photos）
        kept, kept_en, found, dropped = keep_subjects_with_photos(
            names, aligned, guessed_english=guessed, source_context=material,
            uploaded_portraits=uploaded, tag=f"cover:{side}"
        )
        subjects.append(kept)
        english.append(kept_en)
        photos.append(found)
        excluded.append(dropped)
    # 使用者填的永遠優先，AI 只補空的那一欄；肖像名單一律採 AI 的
    visuals = CoverVisuals(
        left or derived_left or req.title_left.strip(),
        right or derived_right or req.title_right.strip(),
        subjects, english, photos,
    )
    visuals.excluded = tuple(excluded)
    return visuals


def _cover_apply_portraits(
    image_req: ImageGenerateRequest, tag: str, *, text_free: bool = False, excluded: list[str] | None = None
) -> ImageGenerateRequest:
    """十點封面共用：肖像規則＋參考照 → 被剔除者禁畫 → 附圖用途規則 →（合成版）無文字覆寫。順序同 YT 封面。

    text_free=True（合成版的無文字底圖）時，最後壓上與 YT 封面同一段 override：
    前面兩段規則都提到「示意圖標籤要保持可見」，不壓掉模型會自己在底圖上畫一個
    「示意圖」字樣，而合成版的文字全部由程式疊，模型畫的字蓋不掉（見 _yt_cover_background）。
    AI 整張版（tag="ai"）就是要模型畫字，不壓。
    """
    image_req = apply_portrait_to_image_request(image_req)
    if image_req.portrait_subjects:
        attached = len(image_req.portrait_reference_data_urls) + (1 if image_req.reference_image_data_url else 0)
        print(
            f"[ten-cover:{tag}] portrait_subjects={image_req.portrait_subjects} en={image_req.portrait_subjects_en} 參考照={attached} 張",
            flush=True,
        )
    block = excluded_people_block(list(excluded or []))
    if block:
        image_req = image_req.model_copy(update={"prompt": f"{image_req.prompt.rstrip()}{block}"})
    if image_req.reference_images:
        image_req = apply_user_references_to_image_request(image_req)
    if text_free:
        image_req = image_req.model_copy(
            update={"prompt": f"{image_req.prompt.rstrip()}\n\n{editor_formats.YT_COVER_TEXT_FREE_OVERRIDE}"}
        )
    return image_req


def _cover_panel_image(
    visual: str, provider: str, references: list[UserReferenceImage] | None = None,
    subjects: list[str] | None = None, english: list[str] | None = None,
    excluded: list[str] | None = None, instruction: str = "",
) -> bytes:
    """生一張 1:1 的無文字底圖。references＝非 asis 的附圖，依用途規則當生圖參考；
    subjects／english＝這格的具名真人（查得到參考照才畫臉）。回 (PNG bytes, 生圖模型名)。"""
    image_req = ImageGenerateRequest(
        prompt=editor_formats.COVER_VISUAL_PROMPT_TEMPLATE.format(visual=visual.strip()),
        provider=provider,
        aspect_ratio="1:1",
        image_size="1K",
        safe_frame=False,
        reference_images=[ref for ref in (references or []) if ref.purpose != "asis"],
        portrait_subjects=list(subjects or []),
        portrait_subjects_en=list(english or []),
        editor_instruction=instruction,
    )
    image_req = _cover_apply_portraits(image_req, "panel", text_free=True, excluded=excluded)
    result = generate_image_raw(image_req)
    # 比例驗證：這條線直呼 generate_image_raw，繞過 finalize_image_result，
    # 悄悄降級的方圖進 split_canvas 會被裁掉一半（見 verify_output_aspect_ratio）。
    verify_output_aspect_ratio(result, image_req.aspect_ratio)
    return base64.b64decode(result.image_data_base64), result.model


def _base_data_url(raw: bytes) -> str:
    """程式拼好的底圖 → 送模型用的 data URL。轉 JPEG（q=90）：1920×1080 的真照 PNG 動輒
    3–4MB，base64 後超過 UserReferenceImage 的 2.8M 字元上限（實拍抓到）；JPEG 幾百 KB。"""
    with Image.open(io.BytesIO(raw)) as opened:
        buffer = io.BytesIO()
        opened.convert("RGB").save(buffer, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _cover_ai(
    req: TenCoverRequest, date_text: str, visuals: tuple[str, str], base: bytes | None = None,
    protect_base: bool = False, ai_sides: tuple[bool, bool] = (True, True),
) -> tuple[bytes, str, bytes, str]:
    """純 prompt 版：整張封面由生圖模型畫，之後只補貼正版 Logo＋節目標籤＋AI示意圖。

    base（2026-09-13 使用者裁決）＝程式已拼好的無字底圖（原圖放置裁滿版／N 張切格／
    雙切兩格各自 AI改圖 後拼起來）。有 base 時它是**唯一**附圖，模型只在上面畫字；
    其他附圖與肖像參考照都不送——畫面已經定了，再送只會讓模型重新構圖。

    protect_base（B55，2026-09-16 使用者裁決）＝滿版只有 1 張原圖放置時為 True：
    「只畫標題，照片一個像素都不准動」。走哪條保證路徑依 provider 分岔（2026-09-20
    修法甲）：
    - provider=="gpt"（`transparent_mode`）：改請模型只回一張透明底標題圖層
      （`editor_formats.with_title_layer_note`＋`ImageGenerateRequest.
      transparent_background`），生成後用 `compose.overlay_title_layer_over_cover_band`
      逐像素疊到 base 上——base 本身完全不經過模型，保證不是機率性的。
    - provider=="gemini"：background=transparent 不支援（本 session 查證），維持原路：
      模型仍整張重畫，prompt（AI_TITLE_BASE_IMAGE_NOTE）只是請求、不是保證，靠生成後
      compose.restore_photo_outside_title_band 的差異遮罩把字帶以外的像素強制還原成
      base（2026-09-16 實拍量到這條路 change_ratio 常態超標，功能等同不可用，見帳本
      B55 那列——保留給 gemini 是因為目前沒有更好的替代，不是認可它有效）。
    只在**這次生圖**生效——追加修改（req.background_image_base64 那條路）目前收不到
    原始 asis，兩條路都還原不了，這是已知的範圍限制，不是漏改（見呼叫端註解）。
    ≥2 張（切格）的 base 不受影響：多圖語意本來就允許 AI 融合，使用者尚未裁決要不要
    也鎖到逐像素不動。

    回 (成品 PNG, 生圖模型名, 後貼前的模型原圖, 那張圖的 MIME)。第三、四項給追加修改用：
    把貼過 Logo 的成品餵回生圖模型改圖，模型會把 Logo 一起重畫（那是播出事故），
    所以 refine 一律拿後貼前的原圖（與主流程「refine 送置框前原圖」同一個道理）。

    `req.background_image_base64` 有值＝追加修改後回來，模型圖已改好，這裡一次 API
    都不打，只重跑後貼（比照 YT 封面的 `yt-cover:overlay`）。

    標題**先由程式拆好行**再進模板（2026-09-07）：以前 AI 版讓模型自己拆，同一個標題
    在 ai 與 composite 兩種模式下的斷句不一樣，使用者切模式比對時看到的是兩張不同版面
    的圖。拆法與合成版同一支 `compose.cover_title_lines`（使用者自己分的行優先，超寬再
    防呆拆），比照 YT ai-title 的 line1／line2。
    """
    def _post_paste(raw: bytes) -> bytes:
        # 日期與 ON AIR 紅標從 2026-09-10 起也由程式貼（原本寫在 prompt 給模型畫，
        # 而補帶會把模型畫的那兩樣切成上下兩截，見 compose.paste_cover_header_right）。
        # 先放大裁滿定版 1920×1080（原生 GPT 16:9 出 1280×720），後面貼的東西才照定版比例算
        raw = compose.fit_cover_canvas(raw)
        cover = compose.paste_cover_logo(raw, date_text=date_text, badge=req.badge)
        # B107（2026-09-26）：AI 標題不再等同 AI 素材。標籤只看底圖是否實際由 AI
        # 生成／修改；十點雙切按左右分側。refine 的呼叫端會傳回 (True, True)。
        cover = compose.paste_cover_ai_note(
            cover,
            split=req.layout != "full",
            left_is_ai=ai_sides[0],
            right_is_ai=ai_sides[1],
        )
        # 精華圓章（2026-09-07 使用者回報 AI 版選精華沒反應）：合成版由 compose_ten_cover 貼，
        # AI 版標頭刻意維持 ON AIR，圓章要在這裡補貼；追加修改回來的 overlay 路徑同一串。
        if req.badge == "highlight":
            cover = compose.paste_cover_highlight_stamp(cover)
        return cover

    if req.background_image_base64:
        raw = base64.b64decode(req.background_image_base64)
        return _post_paste(raw), "ten-cover:overlay", raw, req.background_mime_type or "image/png"

    badge_text = compose.COVER_BADGES[req.badge][0]

    # 2026-09-08 使用者回報 AI 整張版把 3 行併成 2 行、只上白黃兩色：行數與顏色改成
    # 逐行標在清單上（Line 2 (yellow): …），並在前面先講死總行數。顏色照**行序**走
    # （同日第二輪裁決：白黃紅三行是固定的視覺），與合成版 _draw_cover_title 同一套。
    # 這三個字要跟模板圖例的 (white)／(yellow)／(red) 完全一樣——標記與圖例對不起來，
    # 模型就得自己猜 "red, white outline" 是不是圖例裡那個 (red)。
    _LINE_COLOUR_NAMES = ("white", "yellow", "red")

    # 2026-09-11 第九批 使用者：「標題的顏色其實也可以解放，不必綁住一定要白黃紅順序，
    # 也不用綁到同一句同一色。」1 級起就**不再輸出顏色標記**——L2 以後的條文早就寫著
    # 「白黃紅只是提示、可以忽略」，實拍卻照樣白黃紅，因為顏色標記就釘在每一行後面，
    # 條文區離得太遠壓不過去（同一個教訓見下面反色底字那段）。改由
    # editor_formats.cover_line_annotation 依這一行的內容（鉤子行／數字／引號詞）
    # 寫出該行要怎麼處理，位置一樣釘在行上。0 級完全不變，仍與合成版同一套配色。
    def _lines_block(
        title: str, *, full_width: bool, reverse_out: bool = False, level: int = 0
    ) -> str:
        lines = compose.cover_title_lines(title.strip(), full_width=full_width)
        if not lines:
            return ""
        head = f"  (exactly {len(lines)} lines — render each on its own row, in this order)"
        if level >= 1:
            body = [
                f"  Line {i}: {text}{editor_formats.cover_line_annotation(text, level)}"
                for i, text in enumerate(lines, start=1)
            ]
        else:
            body = [
                f"  Line {i} ({_LINE_COLOUR_NAMES[min(i - 1, len(_LINE_COLOUR_NAMES) - 1)]}): {text}"
                for i, text in enumerate(lines, start=1)
            ]
        # 反色底字（2026-09-10 第二輪）：3 級起條文已經寫成「必做」，實拍卻仍然沒出現——
        # 那條規則離行清單太遠，模型讀到行清單時只看到顏色標記。改成把指示釘在**這一行上**，
        # 與顏色標記同一個位置，模型想漏掉都難。挑第一行：程式拆行時它就是那句鉤子。
        if reverse_out and body:
            body[0] += (
                "  ← SET THIS LINE KNOCKED OUT OF A SOLID COLOUR BLOCK: draw a filled shape"
                " (vivid red, black or gold, edge torn or slanted) and let these characters be"
                " the empty space inside it. This is required, not a suggestion."
            )
        return "\n".join([head, *body])

    # 設計標題（2026-09-08 ON/OFF → 2026-09-09 第八批改成 0–4 拉桿）：
    # 0 完全不追加（維持白／黃／紅排版），1–4 在 TYPOGRAPHY 段尾追加該級的條文。
    # 2026-09-11：條文後面再接一段「招式」——件數由等級決定（2 級 1 件、3 級 2 件、
    # 4 級 3 件），抽哪幾件由程式隨機抽，所以同一則新聞重生會換一組。標題傳進去是為了
    # 「N種／N大」時第一件固定用數量呼應的無字圖示列。
    level = req.creativity_level()
    # F0：整張圖的變化全部掛在同一顆 seed 上。以前這兩支都拿 seed=None，各自
    # 開一顆 random.Random(None)，所以「這一張好」永遠撈不回來。
    # （style_clause 那段沒有抽籤，招式已搬進 design_brief，所以不必帶 seed。）
    seed = req.seed
    style_clause = editor_formats.cover_ai_title_style_clause(level)
    # 2026-09-11 第二輪：數字全部搬到 CANVAS 正後方那塊 DESIGN BRIEF。第一輪把整份條文
    # 放在 TYPOGRAPHY 段尾，實拍四級長得一模一樣——L4 的 prompt 14K 字元，條文坐在
    # 第 8,000 字元之後，模型只讀得進前面那幾段（斜切線的數字就是寫在 CANVAS 才生效的）。
    titles = (req.title_left, req.title_right)
    # visuals=（2026-09-11 第十批）：畫面描述傳進去只為了讓招式段判斷有沒有旗子可用
    # （見 editor_formats.cover_accessories）——不影響其餘措辭。
    # transparent_mode 提前算（原本在下面注入 note 的地方才算）：DESIGN BRIEF 要不要
    # 帶招式，取決於走不走透明標題圖層那條路（2026-09-21 使用者裁決「只要設計標題字」）。
    transparent_mode = protect_base and base is not None and req.provider == "gpt"
    design_brief = editor_formats.cover_design_brief(
        level, titles=titles, seed=seed, full_width=(req.layout == "full"), visuals=visuals,
        layer_mode=transparent_mode,
    )
    colour_rule = editor_formats.cover_title_colour_rule(level)
    # 3 級起才把反色底字釘在行清單上（條文本身也是 3 級起才要求）。
    reverse_out = req.creativity_level() >= 3
    # 側邊標籤只在 3 級起才畫（2026-09-10 使用者裁決）：0–2 是「規矩」到「有設計」，
    # 版面本來就滿，多一排籤會擠掉標題；功能也還在測試期，先只開給高創意。
    # 側邊標籤與畫面小籤共用模板上那個插槽：兩者都是「清單以外、由使用者負責的字」，
    # 也都只在 3 級起才畫（2026-09-10 裁決：0–2 級版面本來就滿，多一排籤會擠掉標題）。
    side_labels_block = (
        editor_formats.cover_side_labels_block(req.side_labels)
        + editor_formats.cover_info_chips_block(req.info_chips)
        if req.creativity_level() >= 3
        else ""
    )
    if req.layout == "full":
        prompt = editor_formats.COVER_AI_FULL_PROMPT_TEMPLATE.format(
            badge_text=badge_text,
            date_text=date_text,
            title_left_lines=_lines_block(req.title_left, full_width=True, reverse_out=reverse_out, level=level),
            visual_left=visuals[0],
            side_labels_block=side_labels_block,
            title_style_clause=style_clause,
            title_design_brief=design_brief,
            title_colour_rule=colour_rule,
        )
    else:
        prompt = editor_formats.COVER_AI_PROMPT_TEMPLATE.format(
            badge_text=badge_text,
            date_text=date_text,
            title_left_lines=_lines_block(req.title_left, full_width=False, reverse_out=reverse_out, level=level),
            title_right_lines=_lines_block(req.title_right, full_width=False, reverse_out=reverse_out, level=level),
            visual_left=visuals[0],
            visual_right=visuals[1],
            side_labels_block=side_labels_block,
            title_style_clause=style_clause,
            title_design_brief=design_brief,
            title_colour_rule=colour_rule,
        )
    # B55 修法甲（2026-09-20）：protect_base 且 provider=gpt 時整套改走透明底標題圖層
    # ——這條路的 note 跟 AI_TITLE_BASE_IMAGE_NOTE 直接矛盾（一個要求重現照片、一個
    # 要求除了字以外全部透明），兩句不能同時注入，這裡二選一。provider=gemini 不支援
    # background=transparent（見 compose.py 那段長註解），原路（差異遮罩回貼）不動。
    # transparent_mode 已在 DESIGN BRIEF 之前算好（招式要不要發取決於它）。
    prompt = (
        editor_formats.with_title_layer_note(
            # 塊高數字跟 DESIGN BRIEF 取自同一張表，不手打（2026-09-21）。
            prompt, block_height=editor_formats.cover_title_block_height(level),
        )
        if transparent_mode
        else editor_formats.with_base_image_note(prompt, base is not None)
    )
    # 整張一起生：兩格的具名真人合成一份名單（去重、保持順序）
    subjects, english = [], []
    for side in (0, 1) if req.layout != "full" else (0,):
        for name, en in zip(*cover_portraits(visuals, side)):
            if name not in subjects:
                subjects.append(name); english.append(en)
    ai_excluded: list[str] = []
    for side in (0, 1) if req.layout != "full" else (0,):
        for name in cover_excluded(visuals, side):
            if name not in ai_excluded and name not in subjects:
                ai_excluded.append(name)
    image_req = ImageGenerateRequest(
        prompt=prompt,
        provider=req.provider,
        aspect_ratio="16:9",
        image_size="1K",
        safe_frame=False,
        # asis 走不到這裡（有 asis 端點就強制 composite）；其他用途依規則當生圖參考。
        # 2026-09-13：附圖位裡的 AI改圖／實景／肖像／地圖也要收——整張 AI 版是十點的
        # 預設模式，漏掉這裡等於使用者在那一格選了 AI改圖 卻完全沒送進模型。
        # 整張 AI 只有一個畫面，兩格的參考都歸這一張。
        # 用途跟著 transparent_mode 走（2026-09-20 獨立複查補）：透明圖層那條路的底圖
        # 是「只給你看位置與配色」的參考，標成 aiedit 會注入「Re-draw that same picture」，
        # 跟 with_title_layer_note 注入的「Do NOT reproduce, redraw…」互相抵銷。
        reference_images=(
            [UserReferenceImage(
                data_url=_base_data_url(base),
                purpose="titlelayer" if transparent_mode else "aiedit",
            )]
            if base is not None else
            [ref for ref in req.reference_images if ref.purpose != "asis"]
            + slot_generation_refs(req.slot_refs(0)) + slot_generation_refs(req.slot_refs(1))
        ),
        portrait_subjects=[] if base is not None else subjects,
        portrait_subjects_en=[] if base is not None else english,
        # 有 base 時指令欄不再帶：第一段每格已經吃過了，第二段再帶會對著拼好的底圖再改一次畫面
        editor_instruction="" if base is not None else req.instruction,
        transparent_background=transparent_mode,
    )
    if base is None:
        image_req = _cover_apply_portraits(image_req, "ai", excluded=ai_excluded)
    else:
        print("[cover:ai-over-base] 程式底圖當唯一附圖，模型只畫標題", flush=True)
        image_req = apply_user_references_to_image_request(image_req)
    # generate_image_raw 會在真正送 provider 前強制補上共用 final baseline；稽核記的
    # 必須是補完後的實際 prompt，而不是呼叫端手上的前一版。
    _record_cover_image_prompt(ensure_final_image_baseline(image_req.prompt))
    result = generate_image_raw(image_req)
    verify_output_aspect_ratio(result, image_req.aspect_ratio)
    raw = base64.b64decode(result.image_data_base64)
    if transparent_mode:
        # B55 診斷（2026-09-21）：量到的數字與被擋下的那張原始圖層都要留下來，
        # 理由見 _record_title_layer_diag 上方那段。
        title_layer_diag: dict = {}
        title_layer_raw = raw
        try:
            raw = compose.overlay_title_layer_over_cover_band(
                base, raw, band_top_ratio=compose.cover_title_band_top_ratio(),
                # 高度上限依創意等級（B55，2026-09-22 使用者裁定 44/46/48/50%）。
                # 這是「縮」不是「擋」，不會多出任何一種失敗情形，所以放在 try 裡
                # 不影響下面 except 的語意。
                max_height_ratio=compose.title_layer_max_height_ratio(level),
                diagnostics=title_layer_diag,
            )
            _record_title_layer_diag(title_layer_diag, creativity=level)
        except compose.ComposeError as exc:
            # 2026-09-20 使用者裁定：四道閘任一沒過不要回 400，退回程式壓字，但要明講。
            # 退的是**標題怎麼畫**，不是照片——base 本來就沒經過模型，這裡直接拿它走
            # 合成版那條路（compose_ten_cover 自己會貼標頭／Logo／圓章，所以不能再
            # 套 _post_paste，那會貼第二次）。transparent_mode 只在滿版成立
            # （protect_base 只有滿版端點會給 True），所以這裡固定走單一標題。
            print(f"[cover:title-layer] 閘門沒過，退回程式壓字：{exc}"
                  f" ｜{title_layer_diag}", flush=True)
            _record_portrait_notice(
                f"AI 標題圖層沒通過檢查（{exc}）。這張已改用程式壓字的標題，"
                "版面與字體會跟 AI 標題不一樣；想要 AI 標題請重新生成一次。"
                + compose.format_title_layer_diagnostics(title_layer_diag)
            )
            _record_title_layer_diag(title_layer_diag, title_layer_raw, creativity=level)
            # B109（2026-09-26）：AI 模式入口也已登記詞組邊界；fallback 直接沿用，
            # 不再補打第二次斷句模型。
            cover = compose.compose_ten_cover(
                base, None,
                title_left=req.title_left.strip(), title_right="",
                date_text=date_text, badge=req.badge,
                left_is_ai=False, right_is_ai=False,
                left_source_text=req.source_left.strip(),
            )
            return cover, f"{result.model}＋ten-cover:title-layer-fallback", base, "image/png"
    elif protect_base and base is not None:
        raw = compose.restore_photo_outside_title_band(
            base, raw, band_top_ratio=compose.cover_title_band_top_ratio(),
        )
    # B55（2026-09-21 使用者回報）：兩條「原圖放置」路徑（gpt 的透明圖層、gemini 的
    # 差異遮罩）都會把字帶以上還原成 base，模型畫的標頭帶一定不會留下來，而 base 是
    # 使用者的原圖、本來就沒有帶——不補的話 Logo／節目標籤／日期／ON AIR 會直接貼在
    # 照片上，藍底整條不見。純 AI 版（base is None）的帶仍是模型畫的，不補。
    #
    # 補在**回傳給呼叫端的 raw 上**而不是只補在成品上：第三個回傳值是「壓字前底圖」，
    # 前端「只改文字」會原樣帶回來再走一次 _post_paste（上面 background_image_base64
    # 那條路）。只補成品的話第二趟拿到的還是沒有帶的照片，帶又不見了。
    # fit_cover_canvas 對已是定版尺寸的圖是原樣回，所以這裡先跑一次不影響 _post_paste。
    if protect_base and base is not None:
        raw = compose.paste_cover_header_band(compose.fit_cover_canvas(raw))
    return _post_paste(raw), result.model, raw, result.mime_type


def _cover_full_image(
    visual: str, provider: str, references: list[UserReferenceImage] | None = None,
    subjects: list[str] | None = None, english: list[str] | None = None,
    excluded: list[str] | None = None, instruction: str = "",
) -> bytes:
    """滿版：生一張 16:9 的無文字底圖。回 (PNG bytes, 生圖模型名)。"""
    image_req = ImageGenerateRequest(
        prompt=editor_formats.COVER_VISUAL_FULL_PROMPT_TEMPLATE.format(visual=visual.strip()),
        provider=provider,
        aspect_ratio="16:9",
        image_size="1K",
        safe_frame=False,
        reference_images=[ref for ref in (references or []) if ref.purpose != "asis"],
        portrait_subjects=list(subjects or []),
        portrait_subjects_en=list(english or []),
        editor_instruction=instruction,
    )
    image_req = _cover_apply_portraits(image_req, "full", text_free=True, excluded=excluded)
    result = generate_image_raw(image_req)
    verify_output_aspect_ratio(result, image_req.aspect_ratio)
    return base64.b64decode(result.image_data_base64), result.model


def _cover_full_composite(
    req: TenCoverRequest, date_text: str, visual
) -> tuple[bytes, bool, str, bytes, str]:
    """滿版合成：附圖（asis_left）有就直接鋪滿，沒有就生一張 16:9；單一標題壓左下。

    回 (PNG, 是否 AI 底圖, 生圖模型名, 壓字前底圖, 底圖 MIME)。附圖直接上版時一次 API
    都不打，模型名記 `ten-cover-full:asis`（比照 YT 封面的 `yt-cover:asis`），落檔才看得出
    那張沒經過模型。壓字前底圖回給呼叫端塞進回應，前端下次「只改文字」原樣帶回來。
    """
    if req.background_image_base64:
        # 「只改文字」（2026-09-08）：前端帶回上一次的壓字前底圖，底圖不重生也不重取，
        # 只用目前欄位重壓一次標題。同時帶了附圖時以底圖為準——使用者按的是「只改文字」。
        slot = base64.b64decode(req.background_image_base64)
        return (
            compose.compose_ten_cover(
                slot, None,
                title_left=req.title_left.strip(), title_right="",
                date_text=date_text, badge=req.badge,
                left_is_ai=req.background_is_ai, right_is_ai=False,
                left_source_text=req.source_left.strip(),
            ),
            req.background_is_ai,
            "ten-cover-full:recomposite",
            slot,
            req.background_mime_type or "image/png",
        )
    asis_raws = ten_cover_full_asis_images(req)
    slot_mime = ""
    if len(asis_raws) == 1:
        slot = asis_raws[0]
        # 附圖的 MIME 照實回報（上傳的可能是 JPEG），不要一律寫死 PNG
        placement = req.slot_placements()[0]
        slot_mime, _, _ = _split_data_url(placement) if placement else ("", "", "")
    elif asis_raws:
        # 2026-09-13 使用者裁決：滿版放幾張原圖就自動切幾格（以前只放第 1 張）
        print(f"[cover] 滿版原圖放置 {len(asis_raws)} 張 → 自動切 {min(len(asis_raws), compose.YT_SPLIT_MAX_PANELS)} 格", flush=True)
        slot = _cover_full_base(asis_raws)
    else:
        slot = None
    is_ai = slot is None
    image_model = "ten-cover-full:asis"
    if is_ai:
        # 滿版只有一格＝左格：那一格附圖位裡的 AI改圖／實景／肖像／地圖要一起送進去，
        # 不然使用者對著那一格放的 AI改圖等於沒放（2026-09-13）。
        references = [
            ref for ref in req.reference_images if ref.purpose != "asis"
        ] + slot_generation_refs(req.slot_refs(0))
        subjects, english = cover_portraits(visual, 0)
        slot, image_model = _cover_full_image(
            visual[0] if isinstance(visual, CoverVisuals) else visual, req.provider, references, subjects, english,
            excluded=cover_excluded(visual, 0), instruction=req.instruction,
        )
        slot_mime = "image/png"
    cover = compose.compose_ten_cover(
        slot, None,
        title_left=req.title_left.strip(), title_right="",
        date_text=date_text, badge=req.badge, left_is_ai=is_ai, right_is_ai=False,
        left_source_text=req.source_left.strip(),
    )
    return cover, is_ai, image_model, slot, slot_mime or "image/png"


def _cover_panels(
    req: TenCoverRequest, visuals: tuple[str, str]
) -> tuple[list[bytes | None], list[int], list[str]]:
    """雙切兩格的底圖：附圖直接用、沒附圖的格生 1:1。回 (panels, 生過的格, 模型名)。

    合成版（程式壓字）與「AI 標題疊底圖」（2026-09-13）共用；後者拿 panels 拼成
    無字底圖再送模型畫字。舊路徑單張原圖＝全版那條在這裡回 [raw, None] 且不生。
    """
    references = [ref for ref in req.reference_images if ref.purpose != "asis"]
    # 每一格自己的參考圖（2026-09-13）：共用清單兩格都吃，附圖位裡的只進那一格。
    panel_references = [references + slot_generation_refs(req.slot_refs(i)) for i in (0, 1)]
    if ten_cover_uses_slots(req):
        # 左右上傳位（2026-09-07）：有圖的格直接上版，沒圖的格生底圖；只有一格有圖也不做全版
        slot_left, slot_right = ten_cover_slot_images(req)
        panels: list[bytes | None] = [slot_left, slot_right]
    else:
        asis = ten_cover_asis_images(req)
        if len(asis) == 1:
            # 舊路徑（不分左右的附圖）：單張原圖＝全版，由呼叫端處理（panels[1] 留 None 不生）
            return [asis[0], None], [], ["ten-cover:asis"]
        panels = [asis[0] if len(asis) >= 1 else None, asis[1] if len(asis) >= 2 else None]
    todo = [i for i, panel in enumerate(panels) if panel is None]
    models: list[str] = []
    # 要生的圖平行生。序列跑會讓等待時間直接加倍——單張本來就要 30–90 秒。
    if todo:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                i: pool.submit(
                    _cover_panel_image, visuals[i], req.provider, panel_references[i],
                    *cover_portraits(visuals, i), excluded=cover_excluded(visuals, i),
                    instruction=req.instruction,
                )
                for i in todo
            }
            for i, future in futures.items():
                panels[i], model = future.result()
                if model not in models:
                    models.append(model)
    return panels, todo, models


def _cover_composite(
    req: TenCoverRequest, date_text: str, visuals: tuple[str, str]
) -> tuple[bytes, tuple[bool, bool], str, bytes]:
    """合成版：AI 只出無文字底圖（或直接用原圖放置的附圖），文字全部由 Pillow 畫。

    回 (PNG, (左格是否 AI, 右格是否 AI), 生圖模型名, 壓字前底圖)。兩格都是附圖時一次 API
    都不打，模型名記 `ten-cover:asis`；兩格都生時兩個模型名相同就只記一次。

    壓字前底圖＝兩格拼好（split_canvas）還沒畫任何文字／標頭的那張，回給前端存起來，
    「只改文字」時原樣帶回來零 API 重壓（2026-09-14；比照滿版 _cover_full_composite）。
    舊路徑（不分左右的單張原圖全版）不回底圖：前台早已到不了那條路。
    """
    if req.background_image_base64:
        # 「只改文字」（2026-09-14 雙切）：一定要在 _cover_panels 之前回頭——前端重送時附圖位
        # 通常還在，若有一格沒放原圖，_cover_panels 會替那格生底圖，一個本該零 API 的請求就燒錢了。
        background = base64.b64decode(req.background_image_base64)
        cover = compose.compose_ten_cover(
            background, None,
            title_left=req.title_left.strip(), title_right=req.title_right.strip(),
            date_text=date_text, badge=req.badge,
            left_is_ai=req.background_is_ai, right_is_ai=req.background_right_is_ai,
            prebuilt_split=True,
            left_source_text=req.source_left.strip(), right_source_text=req.source_right.strip(),
        )
        return cover, (req.background_is_ai, req.background_right_is_ai), "ten-cover:recomposite", background
    panels, todo, models = _cover_panels(req, visuals)
    if panels[1] is None and not todo:
        # 舊路徑（不分左右的附圖）：單張原圖＝全版，兩個標題壓在同一張圖的左下與右下
        cover = compose.compose_ten_cover(
            panels[0], None,
            title_left=req.title_left.strip(), title_right=req.title_right.strip(),
            date_text=date_text, badge=req.badge, left_is_ai=False, right_is_ai=False,
            left_source_text=req.source_left.strip(), right_source_text=req.source_right.strip(),
        )
        return cover, (False, False), "ten-cover:asis", b""
    left_is_ai, right_is_ai = 0 in todo, 1 in todo
    cover = compose.compose_ten_cover(
        panels[0],
        panels[1],
        title_left=req.title_left.strip(),
        title_right=req.title_right.strip(),
        date_text=date_text,
        badge=req.badge,
        left_is_ai=left_is_ai,
        right_is_ai=right_is_ai,
        left_source_text=req.source_left.strip(),
        right_source_text=req.source_right.strip(),
    )
    buffer = io.BytesIO()
    compose.split_canvas([panels[0], panels[1]], compose.COVER_CANVAS).save(buffer, format="PNG")
    return cover, (left_is_ai, right_is_ai), "、".join(models) or "ten-cover:asis", buffer.getvalue()


def _cover_split_base(
    req: TenCoverRequest, visuals: tuple[str, str]
) -> tuple[bytes, tuple[bool, bool], list[str]]:
    """雙切「AI 標題疊底圖」的第一段（2026-09-13 使用者裁決）：兩格各自取得（原圖直接用、
    AI改圖／沒圖的格各自生 1:1）後拼成一張無字無元素的 16:9 底圖。
    B107 起回 (PNG, (左右是否 AI 素材), 生圖模型名)，讓 AI 標題不再覆蓋素材 provenance。

    這張底圖不能有標頭帶／Logo／日期／AI示意圖——那些是模板要模型畫或 _post_paste 後貼的，
    先畫上去會被模型重畫成兩層。所以走 compose.split_canvas（純拼圖），不走 compose_ten_cover。
    """
    panels, todo, models = _cover_panels(req, visuals)
    raws = [panel for panel in panels if panel is not None]
    canvas = compose.split_canvas(raws, compose.COVER_CANVAS)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue(), (0 in todo, 1 in todo), models


def ten_cover_full_asis_images(req: TenCoverRequest) -> list[bytes]:
    """滿版那一格所有原圖放置的 bytes（附圖位優先，沒有才看舊的共用清單）。"""
    refs = [ref for ref in req.slot_refs(0) if ref.purpose == "asis"]
    if not refs:
        return ten_cover_asis_images(req)
    out = []
    for ref in refs:
        out.append(decode_attached_image(ref.data_url))
    return out


def _cover_full_base(raws: list[bytes]) -> bytes:
    """滿版底圖：1 張裁滿版、N 張自動切 N 格（2026-09-13 使用者裁決，斜切白線同 YT 多圖分切）。
    上限 compose.YT_SPLIT_MAX_PANELS，超過只取前幾張。回無字 PNG。"""
    if not raws:
        raise compose.ComposeError("滿版底圖至少要一張原圖")
    raws = raws[: compose.YT_SPLIT_MAX_PANELS]
    if len(raws) == 1:
        canvas = compose._cover_panel(raws[0], compose.COVER_CANVAS)
    else:
        canvas = compose.split_canvas(raws, compose.COVER_CANVAS)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


class CoverTitleDigestRequest(BaseModel):
    news_text: str = Field(min_length=10, max_length=20_000)
    # yt_hourly（2026-09-08 WP2）＝整點直播，與十點同款「先判 1／2 主題」；
    # yt_cover＝國內外新聞直播與今日熱搜，維持單標題。
    # yt_vstrip（2026-09-09）＝直播直標：兩段標題＋自動判來源，見 editor_formats
    target: Literal[
        "ten_cover", "ten_cover_full", "yt_cover", "yt_hourly", "yt_vstrip"
    ] = "ten_cover"


TEN_DIGEST_MAX_ATTEMPTS = 2   # 十點三段字數不合格時最多問幾次（含第一次）

# 標題消化的輸出上限。原本寫死 2000，2026-09-09 直標那條（prompt 又多兩千多字元）
# 實測整個被思考吃光：completion_tokens=1905 裡 reasoning_tokens=1856，正文只剩
# 四十幾個 token，稍長一點的通稿就吐空字串 → JSONDecodeError → 502。
# 理由與主消化的 DIGEST_MAX_TOKENS 完全相同（見該常數上方的長註解）：正文很短很穩，
# 爆的是思考，而上限是天花板不是用量，只有真的寫出來的 token 才計費。
# 拉到與主消化同一個量級。
# （原本這裡還寫「順便讓 digest_reasoning_body 的思考封頂在這條線上也生效——
# 2000 的預算扣掉正文保留額之後低於 1024，等於封不到」。2026-09-16 D21 之後
# 封頂改成 reasoning.effort，不再從輸出上限反推思考預算，那段換算已無對應物；
# 拉高上限的理由只剩下前面那個——爆的是思考，上限是天花板不是用量。）
COVER_TITLE_DIGEST_MAX_TOKENS = DIGEST_MAX_TOKENS

# 這條路徑原本零重試：上游一次暫時性故障就直接 502（2026-09-17 B77）。主消化那條
# 有 DIGEST_ATTEMPTS=5 吸收得掉，這條沒有，所以 Gemini 在 OpenRouter 約 7.7% 的
# 硬失敗率會原封不動打到使用者臉上。
# 只重試暫時性故障：schema／參數不相容（400）、認證（401）、權限（403）、找不到
# 模型（404）、驗證失敗（422）都是確定性錯誤，重送同一個 payload 必然再失敗，
# 重試只會拖長使用者等待並多燒額度。429 也不重試——短暫 backoff 清不掉用量限制，
# 照既有慣例直接讓使用者知道要等。
# SDK 層不會疊第二層重試：OPENAI_MAX_RETRIES = 0（見該常數）。
COVER_TITLE_UPSTREAM_ATTEMPTS = 3


def _is_transient_upstream(exc: Exception) -> bool:
    # 逾時不重試：APITimeoutError 是 APIConnectionError 的子類，放行的話一次
    # 耗盡就是 3 × DIGEST_TIMEOUT_SECONDS（90 秒）＋ backoff ≈ 272 秒，外層
    # TEN_DIGEST_MAX_ATTEMPTS 再來一輪會破 460 秒，正好重演 main.py 的
    # digest_completion 註解記載的 2026-09-10 事故（Zeabur 300 秒上限、前端卡死）。
    # 要救的 7.7% 硬失敗本來就是秒級的 finish=error／provider 5xx，不含 90 秒卡死。
    if isinstance(exc, APITimeoutError):
        return False
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, RateLimitError):
        return False
    status = getattr(exc, "status_code", None)
    return status == 408 or (isinstance(status, int) and status >= 500)


def _cover_title_completion(**kwargs):
    """digest_completion 外面包一層有界重試，只吃暫時性上游故障。"""
    for attempt in range(COVER_TITLE_UPSTREAM_ATTEMPTS):
        try:
            return digest_completion(**kwargs)
        except Exception as exc:  # noqa: BLE001
            last = attempt == COVER_TITLE_UPSTREAM_ATTEMPTS - 1
            if last or not _is_transient_upstream(exc):
                raise
            print(
                f"[cover-titles] 上游暫時性故障，{attempt + 1}/{COVER_TITLE_UPSTREAM_ATTEMPTS} "
                f"重試：{type(exc).__name__}: {exc}",
                flush=True,
            )
            time.sleep(0.5 * (attempt + 1))


class CoverTitleDigestResponse(BaseModel):
    title_left: str = ""
    title_right: str = ""
    title: str = ""
    # 整點雙則的第二標題（target=yt_hourly；單主題時空）
    title_second: str = ""
    # 直標（target=yt_vstrip）判出來的畫面來源；只有來源名，「畫面來源：」由 compose 補
    source_text: str = ""
    # 消化順便建議的兩個籤（2026-09-11）：回填到欄位讓編輯看過再生圖，
    # 與標題同一條路。生圖那一步仍然只畫欄位裡的字，一個字都不准自己加。
    side_labels: str = ""
    info_chips: str = ""
    # 十點／整點：這篇內文被判定成幾個主題（1＝滿版、2＝雙切）。前端據此更新版面指示器。
    # 一致性以「第二標題有沒有值」為準：模型說 2 卻只給一個標題就退回 1，
    # 說 1 卻多給了第二標題就清掉——回一組自相矛盾的值，前端的指示器會跟欄位打架。
    topics: int = 1


def _digest_chips(value, *, limit: int, chars: int) -> str:
    """把消化回來的籤陣列變成欄位字串（空白分隔），順便把長度與筆數修剪掉。

    超長的**整個丟掉**，不截斷。使用者自己打的籤截斷沒關係（他看得到自己打了什麼），
    但 AI 產的籤截斷會變成假資訊：「病例超過三千二百人」砍成「病例超過三千二百」，
    數字就被改了，而封面上的數字沒人查得到出處。籤是選填的，丟掉一個不會怎樣。
    """
    if not isinstance(value, list):
        return ""
    out = []
    for item in value:
        text = str(item or "").strip().replace(" ", "")
        if text and len(text) <= chars:
            out.append(text)
        if len(out) >= limit:
            break
    return " ".join(out)


def _digest_chip_fields(data: dict) -> dict:
    """兩個籤欄位的上限直接跟 editor_formats 的常數走，手抄一份遲早對不上。"""
    return {
        "side_labels": _digest_chips(
            data.get("side_labels"),
            limit=editor_formats.COVER_SIDE_LABEL_MAX,
            chars=editor_formats.COVER_SIDE_LABEL_CHARS,
        ),
        "info_chips": _digest_chips(
            data.get("info_chips"),
            limit=editor_formats.COVER_INFO_CHIP_MAX,
            chars=editor_formats.COVER_INFO_CHIP_CHARS,
        ),
    }


def _clip_title(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text[:limit]


@app.post(
    "/api/editor/cover-titles",
    response_model=CoverTitleDigestResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
def editor_cover_titles(req: CoverTitleDigestRequest) -> CoverTitleDigestResponse:
    """貼新聞內文 → 文字模型消化出封面標題 → 回填前端欄位；不接生圖，編輯確認後自己按。

    2026-09-06 使用者裁決：封面類版型也要能自動消化，但回填後停下來讓編輯看過。

    2026-09-20（B72／F31）：跟 generate()／hybrid_digest 同一個根因——這支端點
    以前完全沒有落檔，502（模型消化失敗／格式錯／缺標題）在後台一筆都查不到。
    這支有 4 個成功出口（雙切／十點滿版／YT 直標／YT 整點雙則／預設），用內層
    `_logged` 收斂成一個記錄點，不必在每個 return 前面各補一次。
    """
    request_id = request_log.new_request_id()
    started = _generation_clock()
    _reset_generation_retries()
    news_text = req.news_text.strip()

    def _logged(result: CoverTitleDigestResponse) -> CoverTitleDigestResponse:
        meta = _outcome_meta(started, image_model="")
        # B109：雙切右標題／hourly 第二題也是消化輸出的正式內容，稽核不能只留第一題。
        variable = "\n".join(filter(None, (
            result.title_left, result.title_right,
        ))) or "\n".join(filter(None, (
            result.title, result.title_second,
        )))
        request_log.log_generation(
            request_id=request_id, source="cover-titles", news_text=news_text,
            variable=variable, type_label=req.target,
            digest_model=meta["digest_model"],
        )
        _archive_generation(
            request_id=request_id, source="cover-titles", news_text=news_text,
            variable=variable, type_label=req.target, **meta,
        )
        return result

    try:
        return _editor_cover_titles_impl(req, _logged)
    except BaseException as exc:
        _record_generation_failure(
            request_id, started, exc,
            source="cover-titles", news_text=news_text, type_label=req.target,
        )
        raise


def _editor_cover_titles_impl(
    req: CoverTitleDigestRequest, _logged
) -> CoverTitleDigestResponse:
    ten = req.target == "ten_cover"
    hourly = req.target == "yt_hourly"
    vstrip = req.target == "yt_vstrip"
    if vstrip:
        base_prompt = editor_formats.vstrip_title_digest_system(
            compose.VSTRIP_MAIN_MAX_CELLS, compose.VSTRIP_SUB_MAX_CELLS
        )
        schema = editor_formats.VSTRIP_TITLE_DIGEST_SCHEMA
    elif ten:
        base_prompt = editor_formats.COVER_TITLE_DIGEST_SYSTEM_TEN
        schema = editor_formats.COVER_TITLE_DIGEST_SCHEMA_TEN
    elif req.target == "ten_cover_full":
        base_prompt = editor_formats.COVER_TITLE_DIGEST_SYSTEM_TEN_FULL
        schema = editor_formats.COVER_TITLE_DIGEST_SCHEMA_TEN_FULL
    elif hourly:
        base_prompt = editor_formats.COVER_TITLE_DIGEST_SYSTEM_YT_HOURLY
        schema = editor_formats.COVER_TITLE_DIGEST_SCHEMA_YT_HOURLY
    else:
        base_prompt = editor_formats.COVER_TITLE_DIGEST_SYSTEM_YT
        schema = editor_formats.COVER_TITLE_DIGEST_SCHEMA_YT
    system_prompt = base_prompt + CONTENT_FIDELITY_RULES
    model = resolve_digest_model()
    ten_family = ten or req.target == "ten_cover_full"
    data = None
    # 十點的三段字數（每段 4–7、全篇 12–18）模型常不守（2026-09-08 晚使用者：字太少撐不出三段、
    # 或一段 11 字把字級拖垮），所以驗一次，不合格就帶著違規原因重問一次；再不合格就照收。
    for attempt in range(TEN_DIGEST_MAX_ATTEMPTS if ten_family else 1):
        prompt = system_prompt
        if attempt:
            prompt += "\n" + editor_formats.ten_digest_retry_note(data)
        try:
            response = _cover_title_completion(
                model=model,
                system_prompt=prompt,
                news_text=req.news_text.strip(),
                max_output_tokens=COVER_TITLE_DIGEST_MAX_TOKENS,
                schema_name="cover_titles",
                schema=schema,
                site="cover",
            )
            data = parse_digest_json(response.choices[0].message.content or "")
        except Exception as exc:  # noqa: BLE001
            print(f"[cover-titles] 消化標題失敗：{type(exc).__name__}: {exc}", flush=True)
            raise HTTPException(status_code=502, detail=f"消化標題失敗：{type(exc).__name__}") from exc
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="消化標題失敗：回傳格式不對")
        if not ten_family or not editor_formats.ten_digest_violations(data):
            break
        print(f"[cover-titles] 十點標題不合三段規格，重問（第 {attempt + 1} 次）："
              f"{editor_formats.ten_digest_violations(data)}", flush=True)
    if ten:
        left = _clip_title(data.get("title_left"), 40)
        right = _clip_title(data.get("title_right"), 40)
        if not left:
            raise HTTPException(status_code=502, detail="消化標題失敗：模型沒給第一標題")
        # 2026-09-08 WP1：單主題是合法結果（回填後前端判定成滿版），所以只驗左標。
        # topics 一律由實際有沒有第二標題決定，模型自己說的只當參考。
        if data.get("topics") == 1:
            right = ""
        return _logged(CoverTitleDigestResponse(
            title_left=left, title_right=right, topics=2 if right else 1,
            **_digest_chip_fields(data),
        ))
    title = _clip_title(data.get("title"), 60)
    if not title:
        raise HTTPException(status_code=502, detail="消化標題失敗：模型沒給標題")
    if req.target == "ten_cover_full":
        return _logged(CoverTitleDigestResponse(title=title, **_digest_chip_fields(data)))
    if vstrip:
        # 格數超標不在這裡擋：回填後編輯自己看得到格數指示器，也還沒生圖。
        # 真正的硬上限在 compose.yt_vertical_layout（超過就 400，訊息指名哪一個標題）。
        return _logged(CoverTitleDigestResponse(
            title=title,
            title_second=_clip_title(data.get("title_second"), 60),
            source_text=_clip_title(data.get("source"), 40),
        ))
    if hourly:
        # 整點雙則（2026-09-08 WP2）：判定規則與十點同一套，只是欄位叫 title／title_second
        second = _clip_title(data.get("title_second"), 60)
        if data.get("topics") == 1:
            second = ""
        return _logged(CoverTitleDigestResponse(title=title, title_second=second, topics=2 if second else 1))
    return _logged(CoverTitleDigestResponse(title=title))


def cover_portrait_log_fields(visuals) -> dict:
    """把兩格的具名真人與照片出處攤平成落檔欄位（欄位名同主流程 log_generation）。

    出處逐位對齊人名，查不到的位子記「（查無）」——只記查到的那幾張會讓事後回查
    對不上是哪一位（多人時尤其），與主流程「每一張出處都記下來」同一個理由。
    """
    subjects: list[str] = []
    sources: list[str] = []
    for side in (0, 1):
        names, _ = cover_portraits(visuals, side)
        found = cover_portrait_photos(visuals, side)
        for name in names:
            if name in subjects:
                continue
            subjects.append(name)
            photo = found.get(name)
            sources.append(photo.source_page if photo is not None else "（查無）")
    return {
        "portrait_subject": "、".join(subjects),
        "portrait_photo_source": "、".join(sources),
    }


def _editor_cover_full(req: TenCoverRequest, date_text: str) -> TenCoverResponse:
    """十點不一樣（滿版）：一張圖、一個標題。附圖有就放、沒有就生一張。"""
    # 舊共用清單（LINE 等呼叫端）也套「混了 AI改圖 就整版 AI改圖」；附圖位那份在 slot_refs 裡套
    req = req.model_copy(update={"reference_images": merge_mixed_slot_to_aiedit(req.reference_images, "cover")})
    has_asis = bool(req.slot_placements()[0]) or any(
        ref.purpose == "asis" for ref in req.reference_images
    )
    # 2026-09-13 使用者裁決：原圖放置＋AI 標題不再強制程式壓字——原圖裁滿版（N 張切格）
    # 後當唯一附圖送進模型，由模型在上面畫標題（見 _cover_ai 的 base）。
    ai_over_base = has_asis and req.mode == editor_formats.COVER_MODE_AI and not req.background_image_base64
    ai_overlay = req.mode == editor_formats.COVER_MODE_AI and bool(req.background_image_base64)
    # B55 診斷（2026-09-21）：本次請求的四道閘量測從乾淨的狀態開始記。
    reset_title_layer_diags()
    # 「只改文字」（2026-09-08）：合成版帶回壓字前底圖＝底圖不重生，跟 ai_overlay 一樣零 API
    recomposite = req.mode == editor_formats.COVER_MODE_COMPOSITE and bool(req.background_image_base64)
    if has_asis or ai_overlay or recomposite:
        # ai_overlay＝追加修改後回來只重貼固定元素，底圖不重生，所以一次文字模型都不打
        # （比照 YT 封面 resolve_yt_cover_plan 的 need_visual）
        visual = req.visual_left.strip() or req.title_left.strip()
    else:
        # 借雙切的補描述流程：右欄填成跟左欄一樣，只取左邊；一次文字模型。
        # 描述有填也要打——沒打就沒有肖像名單，具名真人會被畫成背影（2026-09-07）。
        resolved = resolve_cover_visuals(req.model_copy(update={"title_right": req.title_left, "visual_right": req.visual_left}))
        visual = CoverVisuals(
            req.visual_left.strip() or resolved[0], "",
            (cover_portraits(resolved, 0)[0], []), (cover_portraits(resolved, 0)[1], []),
            (cover_portrait_photos(resolved, 0), {}),
        )
        visual.excluded = (cover_excluded(resolved, 0), [])
    is_ai = True
    source_raw, source_mime = b"", ""
    background_raw, background_mime = b"", ""
    request_id = request_log.new_request_id()
    started = _generation_clock()
    _reset_generation_retries()
    portrait_fields = cover_portrait_log_fields(visual)
    fail_fields = {
        "source": "editor-cover-full",
        "news_text": req.title_left,
        "prompt": f"FULL: {visual}",
        "role": "編輯",
        "provider": req.provider,
        "type_label": f"{COVER_TYPE_LABEL_TEN}（滿版）",
    }
    try:
        if req.mode == editor_formats.COVER_MODE_AI:
            asis_images = ten_cover_full_asis_images(req) if ai_over_base else []
            base = _cover_full_base(asis_images) if ai_over_base else None
            # B55：只有 1 張原圖放置時才鎖「照片不准動」——≥2 張是切格後交給 AI 融合，
            # 使用者尚未裁決要不要也鎖到逐像素不動（見 _cover_ai 的 protect_base 說明）。
            protect_base = ai_over_base and len(asis_images) == 1
            visual_arg = visual if isinstance(visual, CoverVisuals) else CoverVisuals(visual, visual)
            # 沒 base 就照舊呼叫（既有測試的假 _cover_ai 不收 base）
            # B107：base 存在代表本次底圖完全由 asis 原圖拼成；AI 只畫標題，不標
            # AI示意圖。沒有 base（缺圖／aiedit），或 background overlay（refine）仍標。
            is_ai = not ai_over_base
            cover, image_model, source_raw, source_mime = (
                _cover_ai(
                    req, date_text, visual_arg, base=base, protect_base=protect_base,
                    ai_sides=(is_ai, False),
                ) if base is not None
                else _cover_ai(req, date_text, visual_arg)
            )
        else:
            cover, is_ai, image_model, background_raw, background_mime = _cover_full_composite(req, date_text, visual)
    except compose.ComposeError as exc:
        print(f"[compose] 封面失敗：{exc}", flush=True)
        http_exc = HTTPException(status_code=_compose_error_status(exc), detail=f"封面生成失敗：{exc}")
        _record_generation_failure(request_id, started, http_exc, **fail_fields)
        raise http_exc from exc
    except Exception as exc:
        # 生圖端的失敗（安全過濾、比例降級、逾時）以前只會 print，事後查不到是哪一則
        # 標題觸發的。比照 /api/images/generate：記一筆再原樣往外丟。
        _record_generation_failure(request_id, started, exc, **fail_fields)
        raise
    meta = _outcome_meta(started, provider=req.provider, image_model=image_model)
    request_log.log_generation(
        request_id=request_id,
        source="editor-cover-full",
        news_text=req.title_left,
        variable=req.title_left,
        prompt=f"FULL: {visual}",
        role="編輯",
        provider=req.provider,
        image_model=image_model,
        digest_model=meta["digest_model"],
        **portrait_fields,
    )
    final_lines = "\n".join(compose.cover_title_lines(req.title_left.strip(), full_width=True))
    _archive_generation(
        request_id=request_id,
        image_base64=base64.b64encode(cover).decode("ascii"),
        mime_type="image/png",
        source="editor-cover-full",
        seed=req.seed,
        type_label=f"{COVER_TYPE_LABEL_TEN}（滿版）",
        news_text=req.title_left,
        variable=final_lines if req.mode == editor_formats.COVER_MODE_AI else req.title_left,
        prompt=(collected_cover_image_prompt() if req.mode == editor_formats.COVER_MODE_AI
                else f"FULL: {visual}"),
        role="編輯",
        # B55 診斷（2026-09-21）：同 YT 封面，見 _title_layer_archive_fields。
        **_title_layer_archive_fields(),
        **portrait_fields,
        **meta,
    )
    return TenCoverResponse(
        image_data_base64=base64.b64encode(cover).decode("ascii"),
        mime_type="image/png",
        model="ten-cover-full:recomposite" if recomposite
              else f"ten-cover-full:{req.mode}" + ("-asis" if has_asis else ""),
        # 追加修改的源圖＝後貼前的模型原圖（只有 AI 版有；合成版是程式拼的，沒有源圖）
        source_image_base64=base64.b64encode(source_raw).decode("ascii") if source_raw else "",
        source_mime_type=source_mime,
        # 「只改文字」用的壓字前底圖（合成版才有）：前端存起來，下次改標題原樣帶回來零 API 重壓
        background_image_base64=base64.b64encode(background_raw).decode("ascii") if background_raw else "",
        background_mime_type=background_mime if background_raw else "",
        background_is_ai=is_ai if background_raw else False,
        visual_left=(visual[0] if isinstance(visual, CoverVisuals) else visual),
        visual_right="",
        left_is_ai=is_ai,
        right_is_ai=False,
        # B107 只翻 AI 標籤判定；AI 標題路徑仍不新增／啟用畫面來源標籤。
        source_left=req.source_left.strip() if req.mode == editor_formats.COVER_MODE_COMPOSITE and not is_ai else "",
        source_right="",
        mode=req.mode,
        seed=req.seed,
        notices=collected_portrait_notices(),
    )


@app.post(
    "/api/editor/cover",
    response_model=TenCoverResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
def editor_cover(req: TenCoverRequest) -> TenCoverResponse:
    reset_portrait_notices()
    reset_cover_image_prompt()
    if req.badge not in compose.COVER_BADGES:
        _abort_generation(
            HTTPException(
                status_code=400,
                detail=f"未知的標籤：{req.badge}（可用：{list(compose.COVER_BADGES)}）",
            ),
            source="editor-cover",
            news_text=req.title_left,
            role="編輯",
            provider=req.provider,
            type_label=COVER_TYPE_LABEL_TEN,
        )
    date_text = req.date_text.strip() or datetime.date.today().strftime("%Y/%m/%d")
    # F0：seed 在入口定一次，滿版／雙切／只改文字每條路徑共用同一顆，回應才報得出
    # 實際採用的值。沒帶就現抽——舊呼叫端（LINE 等）因此也拿得到可回查的 seed。
    if req.seed is None:
        req = req.model_copy(update={"seed": next_generation_seed()})
    # 版面在入口就正規化成 split／full 一次（2026-09-08 WP1）：下游那一票
    # `req.layout == "full"` 的判斷因此完全不用動，也不會有人再看到 None。
    req = req.model_copy(
        update={"layout": editor_formats.resolve_cover_layout(req.layout, req.title_right)}
    )
    caps = editor_formats.capability_for("ten_cover")   # 版型能力矩陣（2026-09-14 模組化第 1 步）
    # 標題模式定案（2026-09-14，理由見 editor_formats.title_mode_for_creativity）：呼叫端明送就照辦，
    # 省略才依創意等級挑預設（0 級 → 程式壓字）。**一定要跑**，下游全部假設 mode 已經是字串。
    # 放在所有 ai_over_base／只改文字 判斷之前；回應也回定案後的值，前端靠 data.mode 決定
    # 「只改文字」要不要露出。
    resolved_mode = editor_formats.title_mode_for_creativity(
        req.creativity_level(), req.mode, bool(req.background_image_base64),
        zero_program_text=caps.zero_program_text,
    )
    if resolved_mode != req.mode:
        print(f"[cover] 標題模式未指定 → 依創意等級取 {resolved_mode}", flush=True)
        req = req.model_copy(update={"mode": resolved_mode})
    if req.layout == "full":
        # 滿版原圖放置最多 N 張（2026-09-14；N 看能力矩陣），擋在下面的斷句模型之前
        try:
            reject_excess_asis(req.slot_refs(0) or req.reference_images, where="滿版", limit=caps.asis_max)
        except HTTPException as exc:
            _abort_generation(
                exc,
                source="editor-cover",
                news_text=req.title_left,
                role="編輯",
                provider=req.provider,
                type_label=f"{COVER_TYPE_LABEL_TEN}（滿版）",
            )
    if req.background_image_base64 and req.background_layout and req.background_layout != req.layout:
        # 滿版底圖是一張整圖、雙切底圖是拼好的兩格，bytes 分不出來；改了第二標題版面就換了，
        # 明講回 400 比默默把雙切標題壓在整圖上（或反過來）好（2026-09-14）。
        _abort_generation(
            HTTPException(status_code=400, detail="版面變了（滿版↔雙切），上一次的底圖對不上，請重新生成"),
            source="editor-cover",
            news_text=req.title_left,
            role="編輯",
            provider=req.provider,
            type_label=COVER_TYPE_LABEL_TEN,
        )
    # B109（2026-09-26 使用者裁決）：AI prompt 也寫入程式預切的最終列，因此與
    # composite 共用 B108 詞組邊界；撤回 B75 的 AI 模式跳過守衛。
    apply_title_break_hints(req.title_left, req.title_right)
    if req.layout == "full":
        full_result = _editor_cover_full(req, date_text)
        notices = collected_portrait_notices()
        if notices:
            full_result = full_result.model_copy(update={"notices": notices})
        return full_result
    if not req.title_right.strip():
        _abort_generation(
            HTTPException(status_code=400, detail="雙切版型左右標題都要填"),
            source="editor-cover",
            news_text=req.title_left,
            role="編輯",
            provider=req.provider,
            type_label=f"{COVER_TYPE_LABEL_TEN}（雙切）",
        )

    # slots＝哪一格有「直接上版」的圖。只放了 AI改圖／參考的格子不算數：那格照樣生底圖，
    # 也就不該把整個封面拉去強制合成版（2026-09-13 使用者裁決之三）。
    slots = tuple(bool(url) for url in req.slot_placements())
    if ten_cover_uses_slots(req):
        asis_count = sum(slots)
        asis_label = "-asis" + ("L" if slots[0] else "") + ("R" if slots[1] else "")
    else:
        asis_count = sum(1 for ref in req.reference_images if ref.purpose == "asis")
        asis_label = f"-asis{min(asis_count, 2)}" if asis_count else ""
    # 2026-09-13 使用者裁決：雙切有附圖（原圖放置或附圖位裡的 AI改圖）＋AI 標題 → 兩段生圖：
    # 第一段每格各自取得（原圖直接用、AI改圖 各自重繪）拼成無字底圖，第二段整張送模型畫字。
    # 以前有原圖就強制程式壓字；AI改圖 則被整張 AI 版把兩格的參考混進同一張圖（雙切各自
    # AI改圖 失效的真因）。追加修改回來（帶 background）不算：底圖已經有了。
    ai_over_base = (
        req.mode == editor_formats.COVER_MODE_AI
        and not req.background_image_base64
        and (asis_count > 0 or ten_cover_uses_slots(req))
    )

    recomposite = req.mode == editor_formats.COVER_MODE_COMPOSITE and bool(req.background_image_base64)
    if req.background_image_base64:
        # 帶底圖回來＝AI 版的追加修改後重貼固定元素，或合成版的「只改文字」（2026-09-14 雙切也有）：
        # 底圖不重生，所以一次文字模型都不打（比照 YT 封面 resolve_yt_cover_plan 的 need_visual）
        visuals = (req.visual_left.strip() or req.title_left.strip(), req.visual_right.strip() or req.title_right.strip())
    elif all(slots):
        # 兩格都有圖：什麼都不生，一次文字模型都不打
        visuals = (req.visual_left.strip() or req.title_left.strip(), req.visual_right.strip() or req.title_right.strip())
    elif any(slots):
        # 有一格要生底圖，所以照樣打一次文字模型補描述。
        # 2026-09-08 WP1：原本這裡會把「有附圖那格」的描述先用標題填好回填給前端，
        # 但畫面描述欄已從 UI 移除（改成共用的指令欄），回填無處可去，所以拿掉。
        visuals = resolve_cover_visuals(req)
    elif asis_count >= 1:
        # 舊路徑：有原圖放置（1 張全版或 2 張雙格）就不需要畫面描述，一次文字模型都不打
        visuals = (req.visual_left.strip() or req.title_left.strip(), req.visual_right.strip() or req.title_right.strip())
    else:
        visuals = resolve_cover_visuals(req)
    panel_is_ai = (True, True)
    source_raw, source_mime = b"", ""
    background_raw = b""
    request_id = request_log.new_request_id()
    started = _generation_clock()
    _reset_generation_retries()
    log_prompt = f"L: {visuals[0]}\nR: {visuals[1]}"
    portrait_fields = cover_portrait_log_fields(visuals)
    fail_fields = {
        "source": "editor-cover",
        "news_text": f"{req.title_left} ｜ {req.title_right}",
        "prompt": log_prompt,
        "role": "編輯",
        "provider": req.provider,
        "type_label": f"{COVER_TYPE_LABEL_TEN}（雙切）",
    }
    try:
        if req.mode == editor_formats.COVER_MODE_AI:
            base, panel_is_ai, base_models = (
                _cover_split_base(req, visuals) if ai_over_base
                else (None, (True, True), [])
            )
            cover, image_model, source_raw, source_mime = (
                _cover_ai(req, date_text, visuals, base=base, ai_sides=panel_is_ai) if base is not None
                else _cover_ai(req, date_text, visuals)
            )
            if base_models:
                image_model = "、".join([*base_models, image_model])
        else:
            cover, panel_is_ai, image_model, background_raw = _cover_composite(req, date_text, visuals)
    except compose.ComposeError as exc:
        print(f"[compose] 封面失敗：{exc}", flush=True)
        http_exc = HTTPException(status_code=_compose_error_status(exc), detail=f"封面生成失敗：{exc}")
        _record_generation_failure(request_id, started, http_exc, **fail_fields)
        raise http_exc from exc
    except Exception as exc:
        # 生圖端的失敗（安全過濾、比例降級、逾時）比照 /api/images/generate 記一筆再原樣往外丟
        _record_generation_failure(request_id, started, exc, **fail_fields)
        raise

    meta = _outcome_meta(started, provider=req.provider, image_model=image_model)
    request_log.log_generation(
        request_id=request_id,
        source="editor-cover",
        news_text=f"{req.title_left} ｜ {req.title_right}",
        variable=f"{req.title_left}\n{req.title_right}",
        prompt=log_prompt,
        role="編輯",
        provider=req.provider,
        image_model=image_model,
        digest_model=meta["digest_model"],
        **portrait_fields,
    )
    final_lines = "\n\n".join((
        "\n".join(compose.cover_title_lines(req.title_left.strip(), full_width=False)),
        "\n".join(compose.cover_title_lines(req.title_right.strip(), full_width=False)),
    ))
    _archive_generation(
        request_id=request_id,
        image_base64=base64.b64encode(cover).decode("ascii"),
        mime_type="image/png",
        source="editor-cover",
        seed=req.seed,
        type_label=f"{COVER_TYPE_LABEL_TEN}（雙切）",
        news_text=f"{req.title_left} ｜ {req.title_right}",
        variable=(final_lines if req.mode == editor_formats.COVER_MODE_AI
                  else f"{req.title_left}\n{req.title_right}"),
        prompt=(collected_cover_image_prompt() if req.mode == editor_formats.COVER_MODE_AI
                else log_prompt),
        role="編輯",
        **portrait_fields,
        **meta,
    )
    return TenCoverResponse(
        image_data_base64=base64.b64encode(cover).decode("ascii"),
        mime_type="image/png",
        model="ten-cover:recomposite" if recomposite else f"ten-cover:{req.mode}{asis_label}",
        # 追加修改的源圖＝後貼前的模型原圖（只有 AI 版有；合成版是程式拼的，沒有源圖）
        source_image_base64=base64.b64encode(source_raw).decode("ascii") if source_raw else "",
        source_mime_type=source_mime,
        # 「只改文字」用的壓字前底圖（合成版才有）：拼好的兩格，前端存起來、改標題原樣帶回來零 API 重壓
        background_image_base64=base64.b64encode(background_raw).decode("ascii") if background_raw else "",
        background_mime_type="image/png" if background_raw else "",
        background_is_ai=panel_is_ai[0] if background_raw else False,
        visual_left=visuals[0],
        visual_right=visuals[1],
        left_is_ai=panel_is_ai[0],
        right_is_ai=panel_is_ai[1],
        # B107 只翻 AI 標籤判定；AI 標題路徑仍不新增／啟用畫面來源標籤。
        source_left=req.source_left.strip() if req.mode == editor_formats.COVER_MODE_COMPOSITE and not panel_is_ai[0] else "",
        source_right=req.source_right.strip() if req.mode == editor_formats.COVER_MODE_COMPOSITE and not panel_is_ai[1] else "",
        mode=req.mode,
        seed=req.seed,
        notices=collected_portrait_notices(),
    )


# ============================================================
# 編輯專屬版型 C：YT 直播封面（2026-09-05）
#
# 「一句標題（半形空格分兩段）＋副標＋可選附圖 → 一張直播封面」。
# 跟十點不一樣一樣不經消化；跟它不同的是**所有文字都由程式疊**（compose.compose_yt_cover），
# 生圖模型只負責一張無文字底圖，甚至有附圖時連生圖都不打。
#
# 追加修改：回應的 source_image_base64 帶的是**無文字底圖**，前端拿它走
# /api/images/refine（text_free=True）改底圖，改完再帶 background_image_base64
# 回來這條重疊一次文字。改標題不重生底圖也是同一條路。
# ============================================================


class YtCoverRequest(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    # 第二則新聞的標題（2026-09-08 WP2）。整點直播＋這一欄有值＝「雙則」：第一行（白）
    # ＝title 整句不拆、第二行（黃）＝title_second，底圖由左右兩張羽化拼成一張。
    # 空＝現行單則流程（title 用半形空格拆兩行）一字不變。國內外新聞直播與今日熱搜
    # 沒有雙則版面，帶了也忽略。判定在 editor_formats.yt_cover_is_dual。
    title_second: str = Field(default="", max_length=60)
    # news＝國內外新聞直播；hourly＝整點直播；hot＝今日熱搜（見 editor_formats.YT_COVER_LAYOUTS）
    layout: Literal["news", "hourly", "hot", "live24"] = "news"
    # live24 的底圖模式（2026-09-13）。只有 live24 看這一欄，其他版型帶了也忽略。
    # blend 是預設＝接線當天的行為（兩格都有圖就羽化拼接）。
    # full／blend／inset 三者都需要左格的圖；blend 與 inset 還需要右格也有圖，
    # 只有一格時一律退回滿版——半塊空白的雙切不是使用者要的東西。
    live24_bg: Literal["full", "blend", "inset"] = "blend"
    # ai＝整張連標題字交給生圖模型畫，程式只後貼固定元素（2026-09-06 使用者裁決）；
    # composite＝模型只生無文字底圖，標題由程式壓字（零錯字）。
    # 省略（None）＝依創意等級挑預設，見 editor_formats.title_mode_for_creativity。
    title_mode: Literal["ai", "composite"] | None = None
    # 國內外新聞直播的兩個獨立標示（頻道實際版面可並存）；整點直播忽略
    original_audio: bool = False     # LIVE 章上方「原音呈現」
    ai_translation: bool = False     # 日期下方「AI即時翻譯」
    # 底部壓色框（2026-09-08 使用者裁決，預設 OFF）：關＝完全不畫，標題靠描邊立在照片上；
    # 開＝畫，且只有 60% 不透明（compose.YT_BAND_ALPHA）。整點直播沒有底帶，後端直接忽略。
    # 2026-09-08 晚使用者：藍／紅底色框預設改 ON；2026-09-11 再改回 OFF。
    # 創意階梯上線後標題本身就有底板與描邊，再疊一條整幅底帶會互相打架。
    bottom_band: bool = False
    date_text: str = Field(default="", max_length=20)
    # 整點直播專用：整點時間（如 20:00），選填，有填才掛在 LIVE 章下
    time_text: str = Field(default="", max_length=10)
    # 創意階梯（2026-09-11）。目前**只管日期牌**：0＝程式畫牌、程式壓字、位置固定；
    # 1–4＝整個牌交給生圖模型——紅框、風格、位置、連日期數字都是它畫的，程式一筆不碰。
    # 等級只決定牌的造型有多放（見 editor_formats._DATE_PLATE_STYLES）。
    # 使用者裁決，且知道代價：日期畫錯一碼在成品上看起來完全正常，驗收要逐張對。
    # 前端還沒有拉桿——那是「把創意階梯導入其他封面」那件事的一部分，等要做時再接。
    # 預設 0 ＝ 現行行為一個像素都沒變。
    creativity: int = Field(default=0, ge=0, le=4)
    # 給 AI 的指令（2026-09-08 WP1：封面／YT 版型重新顯示這一欄）。餵給
    # derive_yt_cover_plan 的推導步驟當畫面提示，底圖 prompt 因此照著它走。
    # 不直接拼進生圖 prompt：那條線一個字都不准畫，指令會被模型畫上去。
    # 有 asis 附圖或帶了現成底圖時根本不打推導，指令自然不生效。
    instruction: str = Field(default="", max_length=500)
    # 新聞原文（B53，2026-09-16）：選填，有預設值不影響舊呼叫端。理由同 TenCoverRequest。
    news_text: str = Field(default="", max_length=20_000)
    provider: Literal["gemini", "gpt"] = "gpt"
    image_size: str = "1K"
    # 與主流程共用同一組附圖欄位與用途：asis＝直接當底圖（不生圖）；
    # scene／portrait／map＝生圖時當參考，用途規則由 apply_user_references_to_image_request 注入。
    reference_images: list[UserReferenceImage] = Field(
        default_factory=list, max_length=MAX_INPUT_REFERENCES
    )
    # 整點直播的「一標一附圖」欄位（2026-09-10，對齊十點不一樣）。
    # 在此之前整點只能靠共用附圖區的**上傳順序**決定哪張進哪格，使用者看不出來也指不了；
    # 現在第一／第二標題底下各有自己的附圖位，前端也把共用區收起來（hides.refUpload）。
    # 空字串＝那一格沒附圖＝那一格由 AI 生底圖。單則只有 asis_left（＝整版鋪滿）。
    # 舊呼叫端（LINE、國內外新聞直播、今日熱搜）不送這兩欄，仍走 reference_images 的
    # 原圖放置清單，1 張整版／2 張左右雙切／3 張三切一字不變。
    asis_left: str = Field(default="", max_length=2_800_000)
    asis_right: str = Field(default="", max_length=2_800_000)
    # 2026-09-13：每一格改收一份清單，每張各有自己的用途（讀法同十點，見 slot_reference_list）。
    slot_left: list[UserReferenceImage] = Field(
        default_factory=list, max_length=MAX_INPUT_REFERENCES
    )
    slot_right: list[UserReferenceImage] = Field(
        default_factory=list, max_length=MAX_INPUT_REFERENCES
    )
    # 已有底圖時只重疊文字（追加修改後、或只改標題／副標／日期）。base64，不是 data URL。
    background_image_base64: str = Field(default="", max_length=28_000_000)
    background_mime_type: str = "image/png"
    # 那張底圖是不是 AI 生的——決定要不要疊「AI示意圖」。前端原樣帶回上一次的回應值。
    background_is_ai: bool = False
    # 「畫面來源」（F43，2026-09-20）：只在底圖是原圖放置（is_ai=False）時才會顯示，
    # 與「AI示意圖」互斥、AI 標籤贏（見 compose 各 compose_yt_*cover 的 ai_note 分支）。
    # 只有單一欄位：YT 的規則是任一側有 AI 素材就標整張；雙則即使兩側全 asis 也只需
    # 一份全域來源文字／AI 判定，不需要左右各一份（B107，2026-09-26）。
    source_text: str = Field(default="", max_length=40)
    # 變化池的 seed（F0／D1）。None＝後端現抽一顆並在回應裡回報。取代原本
    # seed=f"{title}|{date}" 的寫法——那種 seed 只要標題與日期沒變就永遠同一種長相，
    # 使用者按幾次「重新生成」都拿到同一張。
    seed: int | None = Field(default=None, ge=0, lt=SEED_MAX)

    def slot_refs(self, side: int) -> list[UserReferenceImage]:
        """第 side 格（0＝第一則／單則、1＝第二則）的附圖清單。"""
        return slot_reference_list(
            self.slot_left if side == 0 else self.slot_right,
            self.asis_left if side == 0 else self.asis_right,
        )

    def asis_slots(self) -> tuple[str, str]:
        """兩個附圖位**直接上版**的那張圖（沒有就是空字串）。

        注意這裡只回原圖放置那張：一格裡的 AI改圖／實景／肖像／地圖不是版位圖，
        它們走 slot_generation_refs 進那一格的生圖參考。
        """
        return (
            slot_placement_url(self.slot_refs(0), "yt-cover"),
            slot_placement_url(self.slot_refs(1), "yt-cover"),
        )

    def uses_asis_slots(self) -> bool:
        """有沒有用新的一標一附圖欄位——沒有就走舊的 reference_images 清單。

        只要格子裡有東西就算數，即使那一格全是 AI改圖／參考、沒有版位圖：
        那些圖仍然是**指定給那一格**的，不能退回共用清單被兩格一起吃掉。
        """
        return any(self.slot_refs(0)) or any(self.slot_refs(1))


class YtCoverResponse(ImageGenerateResponse):
    # source_image_base64（繼承欄位）＝追加修改的源圖：composite 模式是無文字底圖，
    # ai 模式是模型畫好含標題、但還沒貼固定元素的整張圖。雙則的底圖是拼好的那一張，
    # 所以追加修改與「只改文字」跟單則走同一條路，不需要多餘欄位。
    line1: str = ""
    line2: str = ""
    visual: str = ""
    background_is_ai: bool = False
    # 那一格實際貼了「畫面來源」（F43）。空字串＝這格沒有標——不論是因為底圖是
    # AI 生的（background_is_ai=True）還是使用者沒填來源名。
    source_text: str = ""
    title_mode: str = "ai"
    # 整點雙則（2026-09-08 WP2）：前端據此顯示版面與對應的下載短名
    dual: bool = False
    # 這次實際採用的 seed（F0）。前端拿它當「重新生成」的遞增起點。
    seed: int = 0


def derive_yt_cover_plan(
    title: str,
    preset_lines: tuple[str, str] | None,
    instruction: str = "",
    news_text: str = "",
) -> dict:
    """請文字模型補畫面描述（＋分段、＋具名真人）。失敗回空 dict，呼叫端自己退路。

    instruction＝使用者指令欄（2026-09-08 WP1），只當畫面提示：底圖 prompt 用的是
    這一步推導出來的 visual，所以指令走這裡才不會變成畫在圖上的字。

    news_text＝新聞原文（B53，2026-09-16），選填。只有帶了才附加，留空時 material
    與改動前逐字相同。理由與用法同 resolve_cover_visuals：標題與原文都只是
    **來源素材**，只餵給推導步驟認人與畫面依據，不得逐字畫上圖。
    """
    if preset_lines:
        split_note = (
            "The split is ALREADY DECIDED — copy these two lines back exactly:\n"
            f"line1: {preset_lines[0]}\nline2: {preset_lines[1]}"
        )
    else:
        split_note = "The split is NOT decided — split the headline into two lines yourself."
    material = f"Headline: {title.strip()}\n\n{split_note}"
    if news_text.strip():
        material += (
            "\n\nNews article source material (background only, for identifying the correct "
            "named people and an accurate scene — do not copy its wording verbatim into your "
            "output, and the headline above is source material under the same rule): "
            + news_text.strip()
        )
    # 簡稱對照（B82，2026-09-21）：同 resolve_cover_visuals 的理由與位置。
    material += name_aliases.alias_hint_block(title, news_text)
    if instruction.strip():
        material += (
            "\n\nExtra instruction from the editor about how the photograph should look "
            "(guidance for the scene, never text to render): " + instruction.strip()
        )
    model = resolve_digest_model()
    try:
        response = digest_completion(
            model=model,
            system_prompt=editor_formats.YT_COVER_DERIVE_SYSTEM,
            news_text=material,
            max_output_tokens=2000,
            schema_name="yt_cover_plan",
            schema=editor_formats.YT_COVER_DERIVE_SCHEMA,
            site="cover",
        )
        data = parse_digest_json(response.choices[0].message.content or "")
    except Exception as exc:  # noqa: BLE001
        print(f"[yt-cover] 補畫面描述失敗，改用退路：{type(exc).__name__}: {exc}", flush=True)
        return {}
    return data if isinstance(data, dict) else {}


class YtCoverPlan(tuple):
    """(兩行標題, 畫面描述, 具名真人, 英文名) 再多帶查到的參考照（2026-09-07）。

    做成 tuple 子類別的理由同 `CoverVisuals`：既有呼叫端與測試都是四元解包，
    mock 回傳純 tuple 也照樣能用。`.photos` 只用來落檔記照片出處。
    """

    photos: dict = {}
    excluded: list[str] = []

    def __new__(cls, lines, visual, subjects, english, photos=None, excluded=None):
        self = super().__new__(cls, (lines, visual, subjects, english))
        self.photos = dict(photos or {})
        self.excluded = list(excluded or [])
        return self


def yt_cover_plan_photos(plan) -> dict:
    return dict(getattr(plan, "photos", {}))


def resolve_yt_cover_plan(
    req: "YtCoverRequest",
) -> "YtCoverPlan":
    """決定 (兩行標題, 畫面描述, 具名真人, 英文名)。

    只有真的需要才打文字模型：標題已用一個空格分好、且底圖不用生（有 asis 附圖
    或前端帶了現成底圖）時，**這一支**一次 API 都不打。

    ⚠ B33／B75（2026-09-16 更正）：原文寫的是「一次 API 都不打」，容易被讀成
    「整條請求零成本」，**那是錯的**——端點入口的 `apply_title_break_hints` 排在
    這支之前，仍然會打一次斷句。**而且那一次是必要的**：走到這裡的 composite 模式
    正是用 Pillow 壓字的路，斷句邊界會被 `compose._split_line_near_middle` 讀走，
    拿掉會讓斷行品質變差。所以 B33 原本提的「把斷句移到零 API 分支之後」**不採納**。
    真正白打的是 AI 標題模式那條，已由 B75 的 `composite=` 守衛擋掉。
    """
    title = req.title.strip()
    lines = editor_formats.split_live_title(title)
    has_asis = any(ref.purpose == "asis" for ref in req.reference_images)
    # AI 標題模式一定要生圖（附圖只是參考），所以只要沒帶現成圖就需要畫面描述
    need_visual = not req.background_image_base64 and (
        req.title_mode == editor_formats.YT_COVER_TITLE_MODE_AI or not has_asis
    )
    if lines and not need_visual:
        return lines, "", [], []

    data = derive_yt_cover_plan(title, lines, req.instruction, req.news_text)
    if not lines:
        line1 = str(data.get("line1") or "").strip()
        line2 = str(data.get("line2") or "").strip()
        if editor_formats.title_split_is_faithful(title, line1, line2):
            candidate = editor_formats.realign_split_to_title(title, line1)
            if compose.title_split_respects_hints(title, candidate[0]):
                lines = candidate
            else:
                print(
                    f"[yt-cover] AI 分段踩進不可拆詞，不採用：{candidate[0]!r} / {candidate[1]!r}",
                    flush=True,
                )
                lines = editor_formats.fallback_split_title(title)
        else:
            if data:
                print(f"[yt-cover] AI 分段改了字，不採用：{line1!r} / {line2!r}", flush=True)
            lines = editor_formats.fallback_split_title(title)
    if not need_visual:
        return lines, "", [], []

    visual = str(data.get("visual") or "").strip() or title
    subjects = clean_portrait_subjects(data.get("portrait_subjects"))
    english = align_english_names(
        subjects,
        [str(x) for x in (data.get("portrait_subjects_en") or [])],
        [str(x) for x in (data.get("portrait_subjects") or [])],
    )
    guessed = align_english_names(
        subjects,
        [str(x) for x in (data.get("portrait_subjects_en_guess") or [])],
        [str(x) for x in (data.get("portrait_subjects") or [])],
    )
    # 查不到參考照的人先移除，剩下的人照樣畫臉（見 keep_subjects_with_photos）
    uploaded = sum(1 for ref in req.reference_images if ref.purpose == "portrait")
    subjects, english, photos, dropped = keep_subjects_with_photos(
        subjects, english, guessed_english=guessed,
        source_context="\n".join((title, req.news_text, req.instruction)),
        uploaded_portraits=uploaded, tag="yt-cover"
    )
    return YtCoverPlan(lines, visual, subjects, english, photos, dropped)


def _yt_cover_asis_list(req: "YtCoverRequest") -> list[UserReferenceImage]:
    """原圖放置清單：有附圖位就讀格子，否則讀共用區。"""
    if req.uses_asis_slots():
        return [ref for ref in (req.slot_refs(0) + req.slot_refs(1)) if ref.purpose == "asis"]
    return [ref for ref in req.reference_images if ref.purpose == "asis"]


def _yt_cover_gen_refs(req: "YtCoverRequest") -> list[UserReferenceImage]:
    """生底圖時要附的參考圖（原圖放置以外）。有附圖位就把兩格的非 asis 一併帶上。"""
    if req.uses_asis_slots():
        return (
            [ref for ref in req.reference_images if ref.purpose != "asis"]
            + slot_generation_refs(req.slot_refs(0))
            + slot_generation_refs(req.slot_refs(1))
        )
    return [ref for ref in req.reference_images if ref.purpose != "asis"]


def _yt_cover_all_refs(req: "YtCoverRequest") -> list[UserReferenceImage]:
    """AI 整張版：共用區非 asis ＋兩格全部附圖。有底圖（base）時不走這裡。"""
    if req.uses_asis_slots():
        return (
            [ref for ref in req.reference_images if ref.purpose != "asis"]
            + list(req.slot_refs(0))
            + list(req.slot_refs(1))
        )
    return list(req.reference_images)


def _yt_cover_apply_slot_placement(
    req: "YtCoverRequest", image_req: ImageGenerateRequest
) -> ImageGenerateRequest:
    """兩格都有圖時，把左右身分寫進 prompt（D4）。單格或攤平後格子已空＝不注入。"""
    left = req.slot_refs(0)
    right = req.slot_refs(1)
    if not left or not right:
        return image_req
    block = USER_REFERENCE_YT_SLOT_PLACEMENT_TEMPLATE.format(
        left_count=len(left),
        right_count=len(right),
    )
    if block in image_req.prompt:
        return image_req
    return image_req.model_copy(
        update={"prompt": f"{image_req.prompt.rstrip()}\n\n{block}"}
    )


def _yt_cover_background(
    req: "YtCoverRequest", visual: str, subjects: list[str], english: list[str], *, excluded: list[str] | None = None
) -> tuple[bytes, str, bool, str]:
    """取得無文字底圖，回 (bytes, mime, 是否 AI 生的, 模型名)。"""
    if req.background_image_base64:
        return (
            base64.b64decode(req.background_image_base64),
            req.background_mime_type or "image/png",
            req.background_is_ai,
            "yt-cover:recomposite",
        )
    asis = _yt_cover_asis_list(req)
    if asis:
        raws = []
        for ref in asis[: compose.YT_SPLIT_MAX_PANELS]:
            raws.append(decode_attached_image(ref.data_url))
        if len(asis) > compose.YT_SPLIT_MAX_PANELS:
            print(f"[yt-cover] 原圖放置附圖 {len(asis)} 張，只取前 {compose.YT_SPLIT_MAX_PANELS} 張分切", flush=True)
        if len(raws) == 1:
            return compose.crop_background_16x9(raws[0]), "image/png", False, "yt-cover:asis"
        # 防呆：2 張＝左右雙切、3 張＝三切（2026-09-06 使用者裁決），不打生圖模型
        return compose.split_backgrounds(raws), "image/png", False, f"yt-cover:asis-split{len(raws)}"

    image_req = ImageGenerateRequest(
        prompt=editor_formats.YT_COVER_VISUAL_PROMPT_TEMPLATE.format(
            visual=visual.strip(),
            # 2026-09-13：合成版底圖也吃創意階梯。在此之前拉桿只接在 AI 標題那條路，
            # live24 這種純合成版的版型等於完全沒作用。
            creativity=editor_formats.yt_background_creativity(req.creativity),
            headline_note=(
                editor_formats.YT_COVER_HEADLINE_NOTE_ONE
                if req.layout == editor_formats.YT_COVER_LAYOUT_LIVE24
                else editor_formats.YT_COVER_HEADLINE_NOTE_TWO
            ),
        ),
        provider=req.provider,
        aspect_ratio="16:9",
        image_size=req.image_size,
        safe_frame=False,
        reference_images=_yt_cover_gen_refs(req),
        portrait_subjects=subjects,
        portrait_subjects_en=english,
        editor_instruction=req.instruction,
    )
    # 順序：肖像規則 → 附圖用途規則 → 最後壓上「無文字」override（前兩段都提到
    # 示意圖標籤要保持可見，不壓掉模型會自己畫一個「示意圖」字樣）。
    image_req = apply_portrait_to_image_request(image_req)
    block = excluded_people_block(list(excluded or []))
    if block:
        image_req = image_req.model_copy(update={"prompt": f"{image_req.prompt.rstrip()}{block}"})
    # 留證據：肖像這段靠 prompt 端列人名，會飄。沒這行分不出「附了維基照畫本人」
    # 與「模型憑空捏一張臉掛真名」——後者是這個專案定義的最糟組合。
    attached = len(image_req.portrait_reference_data_urls) + (1 if image_req.reference_image_data_url else 0)
    print(
        f"[yt-cover] portrait_subjects={subjects} en={english} 參考照={attached} 張",
        flush=True,
    )
    image_req = apply_user_references_to_image_request(image_req)
    image_req = _yt_cover_apply_slot_placement(req, image_req)
    image_req = image_req.model_copy(
        update={"prompt": f"{image_req.prompt.rstrip()}\n\n{editor_formats.YT_COVER_TEXT_FREE_OVERRIDE}"}
    )
    result = generate_image_raw(image_req)
    verify_output_aspect_ratio(result, image_req.aspect_ratio)
    return base64.b64decode(result.image_data_base64), result.mime_type, True, result.model


def _yt_cover_full_image(
    req: "YtCoverRequest",
    lines: tuple[str, str],
    visual: str,
    subjects: list[str],
    english: list[str],
    *, excluded: list[str] | None = None, base: bytes | None = None,
    protect_base: bool = False,
) -> tuple[bytes, str, str]:
    """AI 標題模式：整張封面（含兩行標題與底帶）交給生圖模型，回 (bytes, mime, model)。

    附圖全數當參考（asis 也照主流程規則原圖放置）；肖像走主流程查參考照。
    不壓 TEXT_FREE override——這條線就是要模型畫字。

    base（2026-09-13 使用者裁決）＝程式已拼好的無字底圖（原圖放置裁滿版／多圖分切／
    雙則兩格各自取得後拼起來）。有 base 時它是**唯一**附圖、不查肖像，模型只在上面畫字
    ——比照十點 _cover_ai 的 base。

    protect_base（B55 修法甲，2026-09-20）＝呼叫端已判定「單則、剛好 1 張原圖放置、
    provider=gpt」時為 True：改注入 with_title_layer_note、設
    ImageGenerateRequest.transparent_background=True，要模型只回透明底標題圖層。
    呼叫端（editor_yt_cover_generate）在拿到回傳後自行決定要用
    compose.overlay_title_layer_over_yt_cover 疊圖還是（provider=gemini 時）沿用
    compose.restore_yt_cover_photo 的差異遮罩——這支函式本身不碰疊圖，只負責組對
    的 prompt 與旗標。
    """
    template = {
        editor_formats.YT_COVER_LAYOUT_HOURLY: editor_formats.YT_COVER_FULL_PROMPT_HOURLY,
        editor_formats.YT_COVER_LAYOUT_HOT: editor_formats.YT_COVER_FULL_PROMPT_HOT,
        editor_formats.YT_COVER_LAYOUT_LIVE24: editor_formats.YT_COVER_FULL_PROMPT_LIVE24,
    }.get(req.layout, editor_formats.YT_COVER_FULL_PROMPT_NEWS)
    live24 = req.layout == editor_formats.YT_COVER_LAYOUT_LIVE24
    # 日期條那一條由 compose 的 box 產生（2026-09-11 創意階梯）——prompt 與程式貼附
    # 用的是同一個座標，不會再有「兩邊各寫各的百分比」那種對不上的 bug。
    # 整點以外的版型模板沒有 date_clause／date_text_line／date_ban／logo_keep_out／
    # badge_keep_out 這幾個佔位，多給的欄位 format 會忽略。title_top 是例外
    # （2026-09-11 第十批起）：news／hot 補了跟 hourly 同源的「標題落到底部邊緣」
    # 那句，也吃這個值，所以下面這行本來就對三個版型都傳，不用另外接線。
    # 跟 5144 那處算法一致——模型畫的日期與程式後貼的必須是同一天
    date_text = req.date_text.strip() or datetime.date.today().strftime("%Y/%m/%d")
    image_req = ImageGenerateRequest(
        prompt=template.format(
            # live24 是**單行**版型：lines 是依空格拆出來的兩段，模板只列 line1 的話
            # 後半段整段消失（2026-09-13 實拍抓到：「東北季風剩1天 假日回溫」四級全被
            # 畫成「東北季風剩1天」）。所以那個版型傳整句，不傳拆過的前半段。
            line1=req.title.strip() if live24 else lines[0],
            line2=lines[1], visual=visual.strip() or req.title.strip(),
            # 兩級都用同一個框：0 級是程式實際貼牌的位置（模型只要留白），
            # 1 級起模型自己畫牌、跟著標題走，這個框只當護欄（見
            # compose.YT_HOURLY_DATE_TAB_BOX 上方的註解）。
            date_clause=editor_formats.yt_hourly_date_clause(
                req.creativity, compose.YT_HOURLY_DATE_TAB_BOX, date_text
            ),
            # 左上角保留區由**程式實際貼上的 Logo 尺寸**算出來（2026-09-11 抓到的
            # 碰撞：手打的 14%×14% 比實際的 14.4%×16.1% 小，日期牌會疊上去）。
            # 右上角維持手打的 27%×32%：實測 LIVE 章只佔 25.1%×18.9%，宣告值比實際
            # **大**＝過度保留，不會撞；收緊會放出右上那塊現在空著的區域，
            # 等於改掉已驗收的構圖，不值得。
            # live24 是 hourly 的鏡像：角標在左上、Logo 在右上，兩個保留區也跟著換邊。
            # 角標的宣告值直接由程式實際貼上的比例算（LIVE24_BADGE_WIDTH_RATIO 是寬，
            # 高度由素材長寬比推）——手打的數字比實際小時，標題會爬上去撞（2026-09-11
            # 在 hourly 踩過一模一樣的坑）。
            logo_keep_out=(
                "about {:.0%} wide and {:.0%} tall".format(
                    compose.LIVE24_LOGO_WIDTH_RATIO + 0.04,
                    compose.LIVE24_LOGO_TOP_RATIO + compose.LIVE24_LOGO_WIDTH_RATIO,
                ) if live24 else "about {:.0%} wide and {:.0%} tall".format(
                    *compose.yt_hourly_logo_keep_out()
                )
            ),
            badge_keep_out=(
                "about {:.0%} wide and {:.0%} tall".format(
                    compose.LIVE24_BADGE_LEFT_RATIO + compose.LIVE24_BADGE_WIDTH_RATIO + 0.02,
                    compose.live24_badge_keep_out_height(),
                ) if live24 else "about 27% wide and 32% tall"
            ),
            date_text_line=editor_formats.yt_hourly_date_text_line(req.creativity, date_text),
            date_ban=editor_formats.yt_hourly_date_ban(req.creativity),
            # 創意階梯（2026-09-11）：brief 釘在 CANVAS 正後方（鐵律一——數字寫在
            # 條文區等於不存在）；LAYOUT 段裡跟它打架的兩條由 layout_rules
            # **拆掉**而不是覆蓋；fixed_block 是 YT 在此之前完全沒有的東西。
            # 三個版型共用同一套（2026-09-11 第二輪）：同一張塊高表、同一批變化池、
            # 同一段 FIXED。差別只有靠左／置中，以及日期牌——只有整點把牌交給模型，
            # news 的日期由程式貼在左上角，hot 根本沒有日期。
            design_brief=editor_formats.yt_design_brief(
                req.creativity, lines=lines, seed=req.seed,
                layout=req.layout,
                # 底帶開著時，整幅底帶與「每行各自一塊底板」是兩個打架的指示——
                # brief 要知道，才能明講兩者關係而不是讓模型自己挑一個遵守。
                bottom_band=req.bottom_band,
                # visual=（2026-09-11 第十批）：只為了讓招式段判斷這張照片裡有沒有
                # 旗子可用（見 editor_formats.cover_accessories）。
                visual=visual,
                # 透明標題圖層那條路不畫招式（2026-09-21 使用者裁決）。條件跟下面
                # transparent_background 與 with_title_layer_note 完全一致，
                # 三處分岔同一個條件——有測試釘住不准各寫各的。
                layer_mode=protect_base and base is not None,
            ),
            layout_rules=editor_formats.yt_layout_rules(req.creativity, req.layout),
            title_top=editor_formats.yt_title_top(req.creativity),
            fixed_block=editor_formats.yt_fixed_block(req.creativity, req.layout),
            # 雙則才講兩景分割；單則是一個場景，講了反而會逼它硬切成兩半。
            # 分割位置一定要講：不講的話模型自己切，實拍落在 59%／64%，都偏右
            # 又互不一致（2026-09-10 使用者指出）。
            split_note=(
                editor_formats.YT_COVER_DUAL_SPLIT_NOTE
                if editor_formats.yt_cover_is_dual(req.layout, req.title_second)
                else ""
            ),
            # 整點版模板沒有底帶佔位（版面本來就沒有底帶），多給的欄位 format 會忽略
            **(editor_formats.yt_cover_band_fields(req.layout, req.bottom_band)
               if req.layout != editor_formats.YT_COVER_LAYOUT_HOURLY else {}),
        ),
        provider=req.provider,
        aspect_ratio="16:9",
        image_size=req.image_size,
        safe_frame=False,
        # 用途跟著 protect_base 走（2026-09-20 獨立複查補，同 _cover_ai 的理由）：
        # 透明圖層那條路的底圖只當位置／配色參考，不能叫模型重畫它。
        reference_images=(
            [UserReferenceImage(
                data_url=_base_data_url(base),
                purpose="titlelayer" if protect_base else "aiedit",
            )]
            if base is not None else _yt_cover_all_refs(req)
        ),
        portrait_subjects=[] if base is not None else subjects,
        portrait_subjects_en=[] if base is not None else english,
        editor_instruction="" if base is not None else req.instruction,
        transparent_background=protect_base and base is not None,
    )
    # B55 修法甲：protect_base 時（呼叫端已限定 provider=="gpt"）改注入透明底圖層
    # 的專用 note，跟 with_base_image_note 互斥（見 main._cover_ai 同款分岔的理由）。
    image_req = image_req.model_copy(
        update={"prompt": (
            editor_formats.with_title_layer_note(
                # 塊高數字跟 yt_design_brief 取自同一張表，不手打（2026-09-21）。
                image_req.prompt,
                block_height=editor_formats.yt_title_block_height(req.creativity),
            )
            if protect_base and base is not None
            else editor_formats.with_base_image_note(image_req.prompt, base is not None)
        )}
    )
    if base is None:
        image_req = apply_portrait_to_image_request(image_req)
        block = excluded_people_block(list(excluded or []))
        if block:
            image_req = image_req.model_copy(update={"prompt": f"{image_req.prompt.rstrip()}{block}"})
    attached = len(image_req.portrait_reference_data_urls) + (1 if image_req.reference_image_data_url else 0)
    print(
        f"[yt-cover:ai-title] portrait_subjects={subjects} en={english} 參考照={attached} 張 "
        f"附圖={len(image_req.reference_images)}{' 底圖=程式拼好' if base is not None else ''}",
        flush=True,
    )
    image_req = apply_user_references_to_image_request(image_req)
    if base is None:
        image_req = _yt_cover_apply_slot_placement(req, image_req)
    _record_cover_image_prompt(ensure_final_image_baseline(image_req.prompt))
    result = generate_image_raw(image_req)
    verify_output_aspect_ratio(result, image_req.aspect_ratio)
    return base64.b64decode(result.image_data_base64), result.mime_type, result.model


def yt_cover_asis_count(req: "YtCoverRequest") -> int:
    if req.uses_asis_slots():
        # 用附圖位時，共用清單裡的原圖放置不算數（前端已把那一區收起來）
        return sum(1 for slot in req.asis_slots() if slot)
    return sum(1 for ref in req.reference_images if ref.purpose == "asis")




# ---- 整點「雙則」（2026-09-08 WP2）----
#
# 兩則新聞一張封面：上白＝第一則、下黃＝第二則，兩行各是一則的完整標題（不拆段）。
# 底圖是左右兩張羽化拼成的**一張**——標題橫跨全寬，中間若有硬邊會從字中間穿過去。
# 拼完就是一張普通底圖，所以追加修改與「只改文字」照舊走既有那條路。


def yt_dual_panel_requests(req: "YtCoverRequest") -> tuple["YtCoverRequest", "YtCoverRequest"]:
    """把雙則請求拆成左右兩個單格請求：標題與原圖放置附圖各歸各格。

    原圖放置 1 張＝左格（第一則）、2 張＝左右各一（超過只取前 2 張）。非 asis 的附圖
    （實景／肖像／地圖）兩格共用，那是生圖參考不是版位。

    **附圖一定要先拆**：resolve_yt_cover_plan 的 has_asis 看的是整份清單，
    不拆的話左格附了一張圖會讓右格也以為自己有底圖，右格的畫面推導就被跳過。
    """
    others = [ref for ref in req.reference_images if ref.purpose != "asis"]
    if req.uses_asis_slots():
        # 一標一附圖（2026-09-10）：哪張進哪格是使用者指定的，不再靠上傳順序猜。
        # 只填右邊那格也不會被誤送到左格——這正是舊寫法會出的錯。
        # 2026-09-13：一格改收一份清單，所以整份清單直接歸那一格——版位圖與那一格
        # 專屬的 AI改圖／實景／肖像一起過去，不再只搬一張 asis。
        # 雙則的格子是半版：>1 張時原圖放置轉 AI改圖（2026-09-13 使用者裁決）
        asis_left, asis_right = (
            lock_half_slot_asis(req.slot_refs(0), "yt-cover:dual"),
            lock_half_slot_asis(req.slot_refs(1), "yt-cover:dual"),
        )
    else:
        asis = [ref for ref in req.reference_images if ref.purpose == "asis"]
        if len(asis) > 2:
            print(f"[yt-cover:dual] 原圖放置附圖 {len(asis)} 張，雙則只有兩格，只取前 2 張", flush=True)
        asis_left, asis_right = asis[:1], asis[1:2]
    left = req.model_copy(update={
        "title": req.title.strip(), "title_second": "",
        "reference_images": others + asis_left,
        "asis_left": "", "asis_right": "", "slot_left": [], "slot_right": [],
        "background_image_base64": "",
    })
    right = req.model_copy(update={
        # live24 只有一行標題，兩格共用同一句——拿空的 title_second 當右格標題的話，
        # 右格的畫面推導會拿到空字串，底圖就變成模型自由發揮。
        "title": (
            req.title if req.layout == editor_formats.YT_COVER_LAYOUT_LIVE24
            else req.title_second
        ).strip(),
        "title_second": "",
        "reference_images": others + asis_right,
        "asis_left": "", "asis_right": "", "slot_left": [], "slot_right": [],
        "background_image_base64": "",
    })
    return left, right


def yt_dual_panel_plan(panel_req: "YtCoverRequest") -> "YtCoverPlan":
    """雙則某一格的畫面描述（＋這一格的具名真人）。

    不走 resolve_yt_cover_plan（它會把拆行結果寫回請求），改直接呼叫 derive_yt_cover_plan
    只取畫面描述與具名真人；模型順便回的分行結果在雙則裡沒有意義，直接丟掉。
    附圖那格不打——它的底圖就是那張照片。
    """
    if any(ref.purpose == "asis" for ref in panel_req.reference_images):
        return YtCoverPlan(("", ""), "", [], [])
    title = panel_req.title.strip()
    data = derive_yt_cover_plan(title, None, panel_req.instruction, panel_req.news_text)
    visual = str(data.get("visual") or "").strip() or title
    subjects = clean_portrait_subjects(data.get("portrait_subjects"))
    english = align_english_names(
        subjects,
        [str(x) for x in (data.get("portrait_subjects_en") or [])],
        [str(x) for x in (data.get("portrait_subjects") or [])],
    )
    guessed = align_english_names(
        subjects,
        [str(x) for x in (data.get("portrait_subjects_en_guess") or [])],
        [str(x) for x in (data.get("portrait_subjects") or [])],
    )
    uploaded = sum(1 for ref in panel_req.reference_images if ref.purpose == "portrait")
    subjects, english, photos, dropped = keep_subjects_with_photos(
        subjects, english, guessed_english=guessed,
        source_context="\n".join((title, panel_req.news_text, panel_req.instruction)),
        uploaded_portraits=uploaded, tag="yt-cover:dual"
    )
    return YtCoverPlan(("", ""), visual, subjects, english, photos, dropped)


def yt_dual_background(
    panel_reqs: tuple["YtCoverRequest", "YtCoverRequest"], plans: list,
    mode: str = editor_formats.LIVE24_BG_BLEND,
) -> tuple[bytes, bool, str]:
    """雙則的底圖：左右兩格各自取得後羽化拼成一張，回 (PNG bytes, 有沒有 AI 生的格, 模型名)。

    沒附圖的格生 **1:1** 方圖（走十點那條 `_cover_panel_image`）：一格只佔半個畫面多一點，
    生 16:9 塞進去會被裁掉左右兩側。要生的格平行生——序列跑等待時間直接加倍。
    附圖那格**不先裁 16:9**：裁過再交給拼接又裁一次，同一張圖被裁兩次主體會被切掉。
    """
    panels: list[bytes | None] = [None, None]
    models: list[str] = []
    todo: list[int] = []
    for i, panel_req in enumerate(panel_reqs):
        asis = [ref for ref in panel_req.reference_images if ref.purpose == "asis"]
        if not asis:
            todo.append(i)
            continue
        panels[i] = decode_attached_image(asis[0].data_url)
        if "yt-cover:asis" not in models:
            models.append("yt-cover:asis")
    # 疊圖：兩張都是 16:9——大的鋪滿整個畫面，小的是右側那塊白框斜照片，兩者都不是
    # 半個畫面的方格。用 1:1 生會被拉扁（2026-09-13）。
    panel_maker = (
        _cover_full_image if mode == editor_formats.LIVE24_BG_INSET else _cover_panel_image
    )
    if todo:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                i: pool.submit(
                    panel_maker,
                    plans[i][1] or panel_reqs[i].title.strip(),
                    panel_reqs[i].provider,
                    [ref for ref in panel_reqs[i].reference_images if ref.purpose != "asis"],
                    plans[i][2], plans[i][3],
                    getattr(plans[i], "excluded", []),
                )
                for i in todo
            }
            for i, future in futures.items():
                panels[i], model = future.result()
                if model not in models:
                    models.append(model)
    if mode == editor_formats.LIVE24_BG_INSET:
        return (
            compose.compose_live24_inset_background(panels[0], panels[1]),
            bool(todo), "、".join(models),
        )
    return compose.blend_backgrounds_lr(panels[0], panels[1]), bool(todo), "、".join(models)


@app.post(
    "/api/editor/yt-cover",
    response_model=YtCoverResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
def editor_yt_cover(req: YtCoverRequest) -> YtCoverResponse:
    reset_portrait_notices()
    reset_cover_image_prompt()
    # F0：seed 在入口定一次。取代舊的 seed=f"{title}|{date}"——那種 seed 綁在內容上，
    # 標題與日期沒改就永遠同一種長相，使用者按「重新生成」拿到的是同一張。
    if req.seed is None:
        req = req.model_copy(update={"seed": next_generation_seed()})
    live24 = req.layout == editor_formats.YT_COVER_LAYOUT_LIVE24
    caps = editor_formats.capability_for(editor_formats.yt_format_key(req.layout))   # 版型能力矩陣
    # 標題模式定案（2026-09-14，理由見 editor_formats.title_mode_for_creativity）：明送照辦、省略才取預設
    #（0 級 → 程式壓字）。四個版型一體適用；live24 原本自己那條 creativity<1 與整點極短標題那條
    # 都被這裡涵蓋。1 級起交給模型（2026-09-13 使用者裁決：「標題完全沒有被創意階梯影響 這是錯的」）。
    resolved_mode = editor_formats.title_mode_for_creativity(
        req.creativity, req.title_mode, bool(req.background_image_base64),
        zero_program_text=caps.zero_program_text,
    )
    if resolved_mode != req.title_mode:
        print(f"[yt-cover] 標題模式未指定 → 依創意等級取 {resolved_mode}", flush=True)
        req = req.model_copy(update={"title_mode": resolved_mode})
    # live24 只有一個標題，hourly 那條「有第二標題＝雙則」的規則用不上。
    # 2026-09-13 使用者裁決：**兩個附圖位都有東西**才雙切，只放一格或都沒放＝滿版。
    dual = (
        req.live24_bg != editor_formats.LIVE24_BG_FULL
        and bool(req.slot_refs(0)) and bool(req.slot_refs(1)) if live24
        else editor_formats.yt_cover_is_dual(req.layout, req.title_second)
    )
    if not dual:
        # 單則整版原圖放置最多 4 張（2026-09-14），擋在下面的斷句模型之前
        reject_excess_asis(req.slot_refs(0) + req.slot_refs(1) + req.reference_images, where="單則", limit=caps.asis_max)
    # B109（2026-09-26）：news／hourly 單題／hot 的 AI prompt 會寫入預切 line1/line2，
    # 所以也要 B108 詞組邊界。hourly 雙題每題本來就是一整列，AI 模式不需另切；
    # live24 固定單行，維持不打斷句模型。composite 行為維持原樣。
    if not live24 and (
        resolved_mode == editor_formats.YT_COVER_TITLE_MODE_COMPOSITE or not dual
    ):
        apply_title_break_hints(req.title, req.title_second)
    if not dual and req.uses_asis_slots():
        # 單則只有一格，附圖位裡的東西就是整版那一格的：整份清單併進共用清單，
        # 下游 1 張＝整版鋪滿那條路完全不用改。雙則不走這裡——它要保留左右格身分，
        # 由 yt_dual_panel_requests 各歸各格。
        # 2026-09-13：清單化後那一格可能只有 AI改圖、沒有版位圖，所以先取版位圖再
        # 補上其餘用途；原本 `next(s for s in ... if s)` 在那種情況會直接 StopIteration。
        # 2026-09-13 實拍抓到：這裡原本只搬**一張**版位圖（slot_placement_url），單則放
        # 2–4 張原圖永遠只出第 1 張、切格從來沒觸發。整份原圖清單一起搬，下游
        # 1 張整版／2 張雙切／3 張三切／4 張四切那條路本來就在。
        slot_all = req.slot_refs(0) + req.slot_refs(1)
        placements = [ref for ref in slot_all if ref.purpose == "asis"]
        extras = slot_generation_refs(slot_all)
        req = req.model_copy(update={
            "reference_images": [
                ref for ref in req.reference_images if ref.purpose != "asis"
            ] + extras + placements,
            "asis_left": "", "asis_right": "",
            "slot_left": [], "slot_right": [],
        })
    if not dual:
        # 單則＝一格：混了 AI改圖 就整版 AI改圖（2026-09-13 使用者裁決），與十點滿版同一條
        req = req.model_copy(update={"reference_images": merge_mixed_slot_to_aiedit(req.reference_images, "yt-cover")})
    # 2026-09-13 使用者裁決：原圖放置＋AI 標題不再強制程式壓字（2026-09-07 的舊裁決作廢）。
    # 底圖照舊由程式取得（單則：裁滿版／多圖分切；雙則：兩格各自原圖或 AI改圖 後拼起來），
    # 再當唯一附圖送進模型畫標題（見 _yt_cover_full_image 的 base）。
    # 雙則只要附圖位有東西就走這條——整張 AI 版沒有「格」的概念，以前雙則各自 AI改圖
    # 的附圖在這裡被整個丟掉（附圖=0）。追加修改回來（帶 background）不算。
    ai_over_base = (
        req.title_mode == editor_formats.YT_COVER_TITLE_MODE_AI
        and not req.background_image_base64
        and (yt_cover_asis_count(req) >= 1 or (dual and req.uses_asis_slots()))
    )
    if ai_over_base:
        print("[yt-cover] 附圖＋AI 標題 → 程式先拼底圖，再交給模型畫字（兩段）", flush=True)
    hourly = req.layout == editor_formats.YT_COVER_LAYOUT_HOURLY
    hot = req.layout == editor_formats.YT_COVER_LAYOUT_HOT
    if dual and req.title_mode == editor_formats.YT_COVER_TITLE_MODE_COMPOSITE:
        # 雙則每行 YT_HOURLY_LINE_MAX_CHARS 個全形字寬的上限要在生底圖之前擋（審查必修 2026-09-08）：
        # 放到 compose 才擋，等於燒完兩次生圖才回錯。AI 整張版不套字數擋（字是模型畫的）。
        for label, text in (("第一標題", req.title), ("第二標題", req.title_second)):
            if compose.title_display_width(text.strip()) > compose.YT_HOURLY_LINE_MAX_CHARS:
                _abort_generation(
                    HTTPException(
                        status_code=400,
                        detail=f"{label}超過 {compose.YT_HOURLY_LINE_MAX_CHARS} 字：「{text.strip()}」（請縮短這一行）",
                    ),
                    source="editor-yt-cover",
                    news_text=req.title,
                    role="編輯",
                    provider=req.provider,
                    type_label=COVER_TYPE_LABEL_YT.get(req.layout, "YT封面"),
                )
    # 整點直播與今日熱搜沒有原音呈現／AI即時翻譯（2026-09-06 使用者裁決），後端直接忽略
    original_audio = bool(req.original_audio) and not (hourly or hot or live24)
    ai_translation = bool(req.ai_translation) and not (hourly or hot or live24)
    # 整點直播的版面本來就沒有底帶（compose_yt_hourly_cover 不畫、AI 模板也明文 no band），
    # 這個開關對它沒有意義，直接忽略——比照原音呈現／AI即時翻譯。
    bottom_band = bool(req.bottom_band) and not (hourly or live24)
    # live24 的日期是 YYYY.MM.DD（點），不是 hourly 的斜線——實際播出用的是點。
    date_text = req.date_text.strip() or datetime.date.today().strftime(
        compose.LIVE24_DATE_FORMAT if live24 else "%Y/%m/%d"
    )

    if dual:
        # 雙則：兩行各是一則新聞的完整標題，**不拆段**——所以不走 split_live_title，
        # 也不問文字模型怎麼分行。畫面描述仍要一則一個（兩格底圖各畫各的），
        # 所以拆成兩個單格請求各推導一次；帶了現成底圖（追加修改／只改文字）時一次都不打。
        panel_reqs = yt_dual_panel_requests(req)
        need_panels = not req.background_image_base64
        plans = [
            yt_dual_panel_plan(panel_req) if need_panels else YtCoverPlan(("", ""), "", [], [])
            for panel_req in panel_reqs
        ]
        lines = (req.title.strip(), req.title_second.strip())
        visual = "｜".join(filter(None, (plans[0][1], plans[1][1])))
        subjects = list(plans[0][2]) + list(plans[1][2])
        english = list(plans[0][3]) + list(plans[1][3])
        photos = {**yt_cover_plan_photos(plans[0]), **yt_cover_plan_photos(plans[1])}
        excluded = list(getattr(plans[0], "excluded", [])) + list(getattr(plans[1], "excluded", []))
    else:
        plan = resolve_yt_cover_plan(req)
        lines, visual, subjects, english = plan
        photos = yt_cover_plan_photos(plan)
        excluded = list(getattr(plan, "excluded", []))
    request_id = request_log.new_request_id()
    started = _generation_clock()
    _reset_generation_retries()
    log_source = f"editor-yt-cover-{req.layout}{'-dual' if dual else ''}-{req.title_mode}"
    log_prompt = visual or "（附圖／既有底圖）"
    # 雙則的兩則標題都要記，只記第一則的話事後查不出是哪一組組合出的問題
    log_title = f"{req.title.strip()}／{req.title_second.strip()}" if dual else req.title
    type_label = COVER_TYPE_LABEL_YT.get(req.layout, "YT封面") + ("（雙則）" if dual else "")

    def _log_failure(exc: Exception) -> None:
        # 生圖與合成的失敗以前只會 print，事後查不到是哪一則標題觸發的。
        # 比照 /api/images/generate：記一筆再原樣往外丟。
        _record_generation_failure(
            request_id, started, exc,
            source=log_source, news_text=log_title, prompt=log_prompt,
            role="編輯", provider=req.provider, type_label=type_label,
        )

    ai_title = req.title_mode == editor_formats.YT_COVER_TITLE_MODE_AI
    # B55 閘門沒過退回程式壓字時翻成 True（2026-09-20 使用者裁定），見下面的
    # overlay_title_layer_over_yt_cover 呼叫處；決定 is_ai 與回應裡的 title_mode。
    title_layer_fallback = False
    # B55 診斷（2026-09-21）：四道閘量到的數字，以及被擋下時模型回傳的那張原始圖層。
    # 兩者都要進稽核歸檔——成功筆也要記，只記失敗筆拿到的是被截斷的分布，
    # 永遠不知道「正常的標題圖層畫多少比例」，也就訂不出正確的門檻。
    title_layer_diag: dict = {}
    reset_title_layer_diags()
    # F43 信任邊界（2026-09-20 獨立複查 gpt-5.6-sol 第一項）：`background_is_ai` 是
    # 前端把上一輪回應原樣帶回來的值，後端沒有從位元組重算。以前帶錯只會讓
    # 「AI示意圖」漏標（消極遺漏）；F43 之後同一個值還決定要不要貼「畫面來源：○○○」
    # ——那是對觀眾的**正面宣稱**（這張畫面沒被動過），帶錯就是說謊。
    # 最容易踩到的不是惡意，是「前端漏帶這個欄位」：Pydantic 預設 False，於是
    # 一張 AI 生的底圖被重新送回來就會掛上來源標示（sol 逐步重現過這個序列）。
    # 因此：自己帶底圖進來、又要標來源時，`background_is_ai` 必須**明確**出現在
    # 請求裡，不接受預設值。明確送 False 仍然照信（那是既有的信任模型，
    # 要不要改成後端自行判定是待裁事項，見 docs/f43-source-label-inventory.md）。
    if (
        req.source_text.strip()
        and req.background_image_base64
        and "background_is_ai" not in req.model_fields_set
    ):
        raise HTTPException(
            status_code=400,
            detail="這次請求自己帶了底圖又要標「畫面來源」，但沒有一併帶 background_is_ai——"
            "後端無法自行確認那張底圖是不是 AI 生的，不能替它宣稱畫面未經修改。"
            "請把上一次回應的 background_is_ai 原樣帶回來。",
        )
    try:
        if ai_title and req.background_image_base64:
            # 追加修改後回來：模型圖已含標題，只補貼固定元素
            background = base64.b64decode(req.background_image_base64)
            # AI 標題模式沒有「只改文字」overlay；帶底圖回來必是 refine 的 AI 修改結果。
            bg_mime, is_ai, image_model = req.background_mime_type or "image/png", True, "yt-cover:overlay"
        elif ai_title:
            base = None
            base_models: list[str] = []
            base_is_ai = True
            if ai_over_base:
                # 第一段：底圖由程式取得（與 composite 同一條路），不打第二次文字模型
                if dual:
                    base, base_is_ai, base_model = yt_dual_background(
                        panel_reqs, plans,
                        mode=req.live24_bg if live24 else editor_formats.LIVE24_BG_BLEND,
                    )
                else:
                    base, _, base_is_ai, base_model = _yt_cover_background(
                        req, visual, subjects, english, excluded=excluded
                    )
                base_models = [base_model] if base_model else []
            # B55 YT 擴充（2026-09-16 使用者裁決；2026-09-20 修法甲加 provider 分岔）：
            # 單則、剛好 1 張原圖放置時（與十點滿版同一個判準）鎖住照片本身，只讓標題
            # 設計層可以變。dual（雙則，兩格各自一張）不受影響——待裁決，見
            # compose.restore_yt_cover_photo／overlay_title_layer_over_yt_cover 的
            # 呼叫端只在這裡接。base_model == "yt-cover:asis" 是 _yt_cover_background
            # 對「剛好 1 張」的唯一回傳值（2 張以上是 "...asis-split{N}"），不是另外猜的
            # 判斷。provider=="gpt" 才走透明底圖層（transparent_mode），要在呼叫
            # _yt_cover_full_image 之前就決定，才能把對的 note 與旗標組進 prompt。
            transparent_mode = (
                base is not None and not dual and base_model == "yt-cover:asis"
                and req.provider == "gpt"
            )
            # 雙則的 AI 整張版照走同一條：兩行標題原樣進模板，模型自己畫底圖與字
            background, bg_mime, image_model = (
                _yt_cover_full_image(
                    req, lines, visual, subjects, english, excluded=excluded,
                    base=base, protect_base=transparent_mode,
                )
                if base is not None else
                _yt_cover_full_image(req, lines, visual, subjects, english, excluded=excluded)
            )
            if base is not None and not dual and base_model == "yt-cover:asis":
                if transparent_mode:
                    # B55 診斷（2026-09-21）：模型回的那張圖層先留起來，閘門擋下時要
                    # 連同量到的數字一起進稽核歸檔——0921 四次全擋、四張成品位元組
                    # 相同，但模型到底畫了什麼完全沒留下來，只能猜。
                    title_layer_raw = background
                    try:
                        background = compose.overlay_title_layer_over_yt_cover(
                            base, background, layout=req.layout,
                            original_audio=original_audio, ai_translation=ai_translation, ai_note=False,
                            # 日期牌只有程式自己畫時才要保護。這個條件必須跟下面
                            # compose_yt_hourly_cover 的 draw_date 逐字相同——一邊叫模型
                            # 畫牌、一邊把那塊列為禁畫區，正是 0921 使用者三次全被擋在
                            # 第 b 道閘的原因（2026-09-21 使用者裁決）。
                            protect_date_tab=not (req.creativity >= 1 and ai_title),
                            # 高度上限依創意等級（B55，2026-09-22 使用者裁定
                            # 44/46/48/50%），跟十點滿版共用同一張表——使用者是拿
                            # 兩邊的成品一起驗收訂出這組數字的。
                            max_height_ratio=compose.title_layer_max_height_ratio(
                                req.creativity
                            ),
                            diagnostics=title_layer_diag,
                        )
                        _record_title_layer_diag(title_layer_diag, creativity=req.creativity)
                    except compose.ComposeError as exc:
                        # 2026-09-20 使用者裁定：閘門沒過退回程式壓字，但要明講。
                        # 底圖換回未經模型的 base，並把 ai_title 關掉——下面那組
                        # compose_yt_*_cover 的 `draw_titles=not ai_title` 就會改成
                        # 由 Pillow 壓標題（＝title_mode="composite" 的那條路）。
                        print(f"[yt-cover:title-layer] 閘門沒過，退回程式壓字：{exc}"
                              f" ｜{title_layer_diag}", flush=True)
                        _record_portrait_notice(
                            f"AI 標題圖層沒通過檢查（{exc}）。這張已改用程式壓字的標題，"
                            "版面與字體會跟 AI 標題不一樣；想要 AI 標題請重新生成一次。"
                            + compose.format_title_layer_diagnostics(title_layer_diag)
                        )
                        _record_title_layer_diag(
                            title_layer_diag, title_layer_raw, creativity=req.creativity,
                        )
                        background, ai_title = base, False
                        image_model = f"{image_model}＋yt-cover:title-layer-fallback"
                        title_layer_fallback = True
                        # B109：非 live24 的 AI 路徑入口已完成斷句，fallback 直接沿用，
                        # 不再重複呼叫斷句模型。
                else:
                    background = compose.restore_yt_cover_photo(
                        base, background, layout=req.layout,
                        original_audio=original_audio, ai_translation=ai_translation, ai_note=False,
                        # 跟上面 overlay_title_layer_over_yt_cover 傳的條件逐字相同，
                        # 也跟下面 compose_yt_hourly_cover 的 draw_date 逐字相同
                        # （2026-09-21 使用者裁決）。這條是 provider=gemini 的差異遮罩
                        # 路徑，原本漏了沒接：創意 ≥1 時模型奉命畫日期牌，這裡卻把那塊
                        # 還原成 base，牌會整個消失——跟 gpt 那條被擋下是同一個矛盾的
                        # 另一種症狀（那邊擋、這邊默默抹掉，這邊更難發現）。
                        protect_date_tab=not (req.creativity >= 1 and ai_title),
                    )
            if base_models:
                image_model = "、".join([*base_models, image_model])
            # B107（2026-09-26）：AI 標題本身不決定標籤；只沿用底圖素材 provenance。
            # 全 asis 的 base_is_ai=False，即使 title_mode=ai／創意度>0 也不標；缺圖生背景
            # 或 aiedit 會由取得底圖的函式回 True。fallback 不再另改這個判定。
            is_ai = base_is_ai
        elif dual and not req.background_image_base64:
            background, is_ai, image_model = yt_dual_background(
                panel_reqs, plans,
                mode=req.live24_bg if live24 else editor_formats.LIVE24_BG_BLEND,
            )
            bg_mime = "image/png"
        else:
            background, bg_mime, is_ai, image_model = _yt_cover_background(
                req, visual, subjects, english, excluded=excluded
            )
    except compose.ComposeError as exc:
        # B55 YT 擴充：restore_yt_cover_photo 的面積防呆丟在這個區塊裡（跟底圖取得同一段），
        # 不在下面那個原本只包 compose_yt_*_cover 的 try/except 範圍內。這裡以前沒有任何
        # 呼叫端會丟 ComposeError，所以原本沒特別轉——沒轉會被 FastAPI 當未知例外回泛用
        # 500，使用者看不到清楚訊息。比照下面那段的轉法：使用者能自己修的回 400。
        print(f"[compose] YT 直播封面失敗：{exc}", flush=True)
        _log_failure(exc)
        raise HTTPException(status_code=_compose_error_status(exc), detail=f"封面生成失敗：{exc}") from exc
    except Exception as exc:
        _log_failure(exc)
        raise
    try:
        # F43（2026-09-20）：畫面來源與 AI示意圖互斥，is_ai=True 時 compose 端會自己
        # 忽略這個參數（AI 標籤贏），這裡不用再判斷一次。B107 起 dual 也以實際兩側
        # 素材判定，不再因為是雙則就一律 is_ai=True。
        # B107 只翻 AI 標籤 gate；成功的 AI 標題路徑仍不新增畫面來源標籤。
        # 若標題圖層閘門失敗、ai_title 已退回 False，則沿用既有 composite 行為。
        source_text = req.source_text.strip() if not ai_title else ""
        if live24:
            # 單行標題：這個版型不拆段，req.title 整句就是那一行。
            cover = compose.compose_yt_live24_cover(
                background, title=req.title.strip(), date_text=date_text, ai_note=is_ai,
                source_text=source_text,
                # AI 標題模式下標題已經畫在底圖上了，再壓一次會疊成兩層
                draw_title=not ai_title,
            )
        elif hot:
            cover = compose.compose_yt_hot_cover(
                background,
                line1=lines[0],
                line2=lines[1],
                ai_note=is_ai,
                source_text=source_text,
                draw_titles=not ai_title,
                bottom_band=bottom_band,
            )
        elif hourly:
            cover = compose.compose_yt_hourly_cover(
                background,
                line1=lines[0],
                line2=lines[1],
                date_text=date_text,
                time_text=req.time_text.strip(),
                ai_note=is_ai,
                source_text=source_text,
                draw_titles=not ai_title,
                # 雙則的每一行是一則新聞的完整標題，長度沒有天然上限，要有一條硬線；
                # 單則是同一句拆兩段，長度受原標題限制，不套用（維持原行為）。
                line_max_chars=compose.YT_HOURLY_LINE_MAX_CHARS if dual else None,
                # 整個日期牌交給模型，只在「創意 ≥1 且真的是模型畫整張」時才成立。
                # composite（程式壓標題）那條路底圖是無文字的，沒有人畫牌，程式得自己畫。
                draw_date=not (req.creativity >= 1 and ai_title),
            )
        else:
            cover = compose.compose_yt_cover(
                background,
                line1=lines[0],
                line2=lines[1],
                date_text=date_text,
                original_audio=original_audio,
                ai_translation=ai_translation,
                ai_note=is_ai,
                source_text=source_text,
                draw_titles=not ai_title,
                bottom_band=bottom_band,
            )
    except compose.ComposeError as exc:
        print(f"[compose] YT 直播封面失敗：{exc}", flush=True)
        _log_failure(exc)
        # 2026-09-14 抓 bug 輪：標題太長是使用者改得掉的輸入問題，比照十點回 400，不是 500
        raise HTTPException(status_code=_compose_error_status(exc), detail=f"封面生成失敗：{exc}") from exc

    meta = _outcome_meta(started, provider=req.provider, image_model=image_model)
    request_log.log_generation(
        request_id=request_id,
        source=log_source,
        news_text=log_title,
        variable="\n".join(filter(None, [
            lines[0], lines[1],
            editor_formats.YT_COVER_ORIGINAL_AUDIO_LABEL if original_audio else "",
            editor_formats.YT_COVER_AI_TRANSLATION_LABEL if ai_translation else "",
            req.time_text.strip() if hourly else "",
        ])),
        prompt=log_prompt,
        role="編輯",
        provider=req.provider,
        image_model=image_model,
        digest_model=meta["digest_model"],
        # 具名真人與照片出處：肖像這段靠 prompt 端列人名，會飄，事後要能一位一位對
        portrait_subject="、".join(subjects),
        portrait_photo_source="、".join(
            photos[name].source_page if name in photos else "（查無）" for name in subjects
        ),
    )
    _archive_generation(
        request_id=request_id,
        image_base64=base64.b64encode(cover).decode("ascii"),
        mime_type="image/png",
        source=log_source,
        seed=req.seed,
        type_label=type_label,
        news_text=log_title,
        variable="\n".join(filter(None, [lines[0], lines[1]])),
        prompt=(collected_cover_image_prompt() if ai_title else log_prompt),
        role="編輯",
        portrait_subject="、".join(subjects),
        # B55 診斷（2026-09-21）：量到的數字進 JSON，被擋下的那張原始圖層另存一個
        # 檔（後台那一列會多一個「標題圖層」連結）。看一眼那張圖就能分辨模型是
        # 畫了深色底板、畫了漸層、還是根本沒理會 background=transparent。
        **_title_layer_archive_fields(),
        **meta,
    )
    return YtCoverResponse(
        image_data_base64=base64.b64encode(cover).decode("ascii"),
        mime_type="image/png",
        model=image_model,
        source_image_base64=base64.b64encode(background).decode("ascii"),
        source_mime_type=bg_mime,
        line1=lines[0],
        line2=lines[1],
        visual=visual,
        background_is_ai=is_ai,
        source_text="" if is_ai else source_text,
        # 退回程式壓字時照實回報成品的模式（2026-09-20）：畫面上的標題確實是 Pillow 畫的，
        # 回 "ai" 會讓前端以為拿到的是 AI 標題版，下一次「只改文字」也會用錯的假設。
        title_mode=(
            editor_formats.YT_COVER_TITLE_MODE_COMPOSITE if title_layer_fallback
            else req.title_mode
        ),
        dual=dual,
        seed=req.seed,
        notices=collected_portrait_notices(),
    )


# ============================================================
# YT 直播「直標」（2026-09-08 WP3）
#
# 跟三種 YT 封面最大的不同：**不生圖、不打任何模型、沒有底圖**。
# 收到欄位就直接請 compose.compose_yt_overlay 畫一張 1920×1080 的透明底 PNG，
# 給導播疊在直播訊號上。所以這支沒有 provider／reference_images／background_*，
# 也沒有「只改文字」與追加修改——那兩件事的前提都是有一張底圖。
# ============================================================


class YtOverlayRequest(BaseModel):
    # 上限刻意留寬（比照 YtCoverRequest 的 60）：真正的長度規則是「格數」不是字元數，
    # 由 compose._vertical_cells 數出來、超過就丟 ComposeError→400，訊息會指名是哪一個
    # 標題。這裡收緊成 12 只會變成 422，前端就拿不到那句話。
    title: str = Field(min_length=1, max_length=60)
    title_second: str = Field(default="", max_length=60)
    source_text: str = Field(default="", max_length=40)
    # 小標三選一：normal＝不掛小標；另兩者在 LIVE 章下方多一枚白底紅字小標
    variant: Literal["normal", "original_audio", "ai_translation"] = "normal"
    # 直標貼在畫面哪一側
    title_side: Literal["left", "right"] = "left"
    # Logo 角落；跟直標同一側會被 compose 擋掉（400）
    logo_corner: Literal["tr", "br", "tl", "bl"] = "tr"
    # 來源句跟著 Logo 走（False＝貼在 LIVE 章旁邊）。2026-09-09 起被 source_corner
    # 取代，留著給舊呼叫端；source_corner 有值時完全不看它。
    source_follow_logo: bool = False
    # 來源句落在哪一角（2026-09-09 使用者要求四角可選）。空字串＝舊行為，
    # 由 source_follow_logo 決定。同一角有 Logo 或 LIVE 章時 compose 自動讓開。
    source_corner: Literal["", "tl", "tr", "bl", "br"] = ""
    # LIVE 章可取消（有些直播不掛 LIVE）
    live: bool = True


class YtOverlayResponse(BaseModel):
    image_base64: str
    mime_type: str = "image/png"
    width: int
    height: int
    # 前端顯示「第一標題 9 格／第二標題 12 格」，以及各區塊的矩形（除錯用）
    layout: dict


def _yt_overlay_layout_payload(layout: dict) -> dict:
    """把 yt_vertical_layout 的結果整理成前端吃得下的 JSON。

    格數單獨拉成整數欄位——讓前端自己數陣列長度，遲早有一處數錯。
    """
    return {
        "main_cells": list(layout["main_cells"]),
        "sub_cells": list(layout["sub_cells"]),
        "main_cells_count": len(layout["main_cells"]),
        "sub_cells_count": len(layout["sub_cells"]),
        "main_max_cells": compose.VSTRIP_MAIN_MAX_CELLS,
        "sub_max_cells": compose.VSTRIP_SUB_MAX_CELLS,
        "column_height": layout["column_height"],
        "pitch": round(float(layout["pitch"]), 2),
        "box": list(layout["box"]),
        "live": list(layout["live"]),
        "label": list(layout["label"]),
        "logo": list(layout["logo"]),
        "source": list(layout["source"]),
        "source_corner": layout["source_corner"],
        "cell_size": layout["cell_size"],
    }


@app.post(
    "/api/editor/yt-overlay",
    response_model=YtOverlayResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
def editor_yt_overlay(req: YtOverlayRequest) -> YtOverlayResponse:
    request_id = request_log.new_request_id()
    started = _generation_clock()
    _reset_generation_retries()
    title = req.title.strip()
    second = req.title_second.strip()
    try:
        # 先畫再算幾何：Logo 同側那道擋法只寫在 compose_yt_overlay 裡，
        # 先呼叫 yt_vertical_layout 的話那一條會漏掉（它不檢查 Logo）。
        png = compose.compose_yt_overlay(
            main_title=title,
            sub_title=second,
            source_text=req.source_text.strip(),
            variant=req.variant,
            logo_corner=req.logo_corner,
            title_side=req.title_side,
            source_follow_logo=req.source_follow_logo,
            source_corner=req.source_corner,
            live=req.live,
        )
        layout = compose.yt_vertical_layout(
            main_title=title,
            sub_title=second,
            title_side=req.title_side,
            variant=req.variant,
            logo_corner=req.logo_corner,
            source_text=req.source_text.strip(),
            source_follow_logo=req.source_follow_logo,
            source_corner=req.source_corner,
        )
    except compose.ComposeError as exc:
        # 直標的失敗全部是使用者自己改得掉的（字太多、Logo 放錯邊），一律 400，
        # 並把 compose 的訊息原樣往前端送——它已經寫明是哪一個標題、幾格。
        print(f"[yt-overlay] 直標合成失敗：{exc}", flush=True)
        http_exc = HTTPException(status_code=400, detail=str(exc))
        _record_generation_failure(
            request_id, started, http_exc,
            source="editor-yt-overlay", news_text=title,
            prompt="（直標，不生圖）", role="編輯", provider="",
            type_label=COVER_TYPE_LABEL_VSTRIP,
        )
        raise http_exc from exc

    meta = _outcome_meta(started, image_model="yt-overlay:compose")
    request_log.log_generation(
        request_id=request_id,
        source=f"editor-yt-overlay-{req.variant}-{req.title_side}",
        news_text=title,
        variable="｜".join(filter(None, [second, req.source_text.strip(),
                                        "" if req.live else "無LIVE章"])),
        prompt="（直標，不生圖）",
        role="編輯",
        image_model="yt-overlay:compose",
        digest_model=meta["digest_model"],
    )
    _archive_generation(
        request_id=request_id,
        image_base64=base64.b64encode(png).decode("ascii"),
        mime_type="image/png",
        source=f"editor-yt-overlay-{req.variant}-{req.title_side}",
        type_label=COVER_TYPE_LABEL_VSTRIP,
        news_text=title,
        variable="｜".join(filter(None, [second, req.source_text.strip()])),
        prompt="（直標，不生圖）",
        role="編輯",
        **meta,
    )
    width, height = compose.YT_CANVAS
    return YtOverlayResponse(
        image_base64=base64.b64encode(png).decode("ascii"),
        mime_type="image/png",
        width=width,
        height=height,
        layout=_yt_overlay_layout_payload(layout),
    )


# 遠端／隧道測試：前端與 API 同一 origin，瀏覽器才打得到後端。
# 本機 :3000 預覽仍走 127.0.0.1:8787（見 app.js API_BASE）。
_REPO_ROOT = pathlib.Path(__file__).resolve().parent


def _frontend_file(name: str, media_type: str) -> FileResponse:
    return FileResponse(
        _REPO_ROOT / name,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/")
def serve_index():
    return _frontend_file("index.html", "text/html; charset=utf-8")


@app.get("/api/editor/formats")
def editor_formats_catalogue() -> list[dict]:
    """版型能力矩陣（2026-09-14 模組化第 1 步）。免 key：內容跟 app.js 靜態表一樣是公開的
    版型名稱與功能開關，沒有機密。前台目前仍用自己的靜態表（由 parity 測試釘住一致），
    改成讀這支是模組化第 5 步。"""
    return editor_formats.format_catalogue()


@app.get("/auth-config.json")
def auth_config() -> dict:
    """前端用來判斷「這個部署有沒有開登入」，以及要用哪個 Clerk 實例。

    publishable key 依 Clerk 的設計本來就是公開值（會出現在任何前端原始碼裡），
    放在這個免登入端點沒有外洩問題；真正的機密是 CLERK_SECRET_KEY，只留在後端。
    不寫死在 index.html 是為了讓同一份前端能跑在不同環境（本機、box、東京）。
    """
    return {
        "enabled": clerk_auth.ENABLED,
        "publishableKey": clerk_auth.PUBLISHABLE_KEY,
        "frontendApi": clerk_auth.FRONTEND_API,
    }


# app.js／hybrid.js 進 git 時 _INTERNAL_API_KEY 只是占位符，容器啟動時由
# entrypoint.sh sed 換成真實值。本機直跑 uvicorn 沒有那一步，瀏覽器會拿著
# 占位符打 API 吃 401——所以 serve 時做同一件事：占位符還在且環境有金鑰就換掉。
# 容器內檔案已被 sed 過，這裡的 replace 是 no-op，兩條路徑行為一致。
def _serve_js_with_key(name: str) -> PlainTextResponse:
    text = (_REPO_ROOT / name).read_text(encoding="utf-8")
    key = os.getenv("NEWS_IMAGE_API_KEY", "").strip()
    # 啟用 Clerk 時**不烙金鑰**：這兩支檔案是公開的（不公開就載不進來，見
    # CLERK_PUBLIC_PATHS 的說明），烙進去等於把金鑰送給任何訪客。
    # 改由 Clerk 權杖認身分，verify_internal_api_key 兩種都收。
    if key and not clerk_auth.ENABLED:
        text = text.replace("__NEWS_IMAGE_API_KEY__", key)
    return PlainTextResponse(
        text,
        media_type="text/javascript; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/app.js")
def serve_app_js():
    return _serve_js_with_key("app.js")


@app.get("/hybrid.html")
def serve_hybrid():
    return _frontend_file("hybrid.html", "text/html; charset=utf-8")


@app.get("/hybrid.js")
def serve_hybrid_js():
    return _serve_js_with_key("hybrid.js")


# LINE Bot：webhook 與生成圖的靜態出口。
# 放在檔案最後掛載，確保 line_bot 延後匯入 main 時本模組已完成定義。
from fastapi.staticfiles import StaticFiles  # noqa: E402
from line_bot import GENERATED_DIR, STATIC_ROOT, router as line_router  # noqa: E402

GENERATED_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
app.include_router(line_router)

# 生成紀錄後台。沒設 ADMIN_PASSWORD 就完全不掛載（/admin 會是 404）。
admin_console.register(app)


def main():
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8787, reload=True)


if __name__ == "__main__":
    main()
