import base64
import concurrent.futures
import contextvars
import datetime
import hmac
import io
import json
import os
import pathlib
import re
import ssl
import time
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from openai import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    RateLimitError,
)
from PIL import Image
from pydantic import BaseModel, Field

import compose
import editor_formats
import gcs_archive
import photo_lookup
import request_log
import safe_area_spec
import safe_frame
from input_filter import check_input, note_accepted
from news_prompt import (
    MAP_TYPE_LABEL,
    PORTRAIT_MODES,
    PROMPT_VERSION,
    USER_REFERENCE_ASIS_DIGEST_RULES,
    USER_REFERENCE_MODES,
    USER_REFERENCE_NO_DISCLAIMER_RULES,
    build_prompt,
    build_refine_prompt,
    compose_variable,
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

if DIGEST_BACKEND == "gemini":
    if not _gemini_key:
        raise RuntimeError("DIGEST_BACKEND=gemini 但未設定 GEMINI_API_KEY")
    openai_client = OpenAI(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=_gemini_key,
    )
    DEFAULT_DIGEST_MODEL = os.getenv("GEMINI_DIGEST_MODEL", "gemini-3.6-flash")
# 2026-09-03：這裡原本寫 `elif _openrouter_key:`，等於只要環境裡有一把
# OPENROUTER_API_KEY 就一定走 OpenRouter，DIGEST_BACKEND=native 完全沒有效果——
# 上面那段註解講的「設回 openrouter 即可切回」暗示這個變數是說了算的，實際上
# 切不回原生。使用者的 OPENROUTER_API_KEY 同時存在於 .env 與 Windows 使用者
# 環境變數，光在 .env 註解掉沒有用，因此改成 DIGEST_BACKEND 明說時聽它的。
elif DIGEST_BACKEND == "openrouter" and _openrouter_key:
    openai_client = OpenAI(
        base_url="https://openrouter.ai/api/v1", api_key=_openrouter_key
    )
    DEFAULT_DIGEST_MODEL = "anthropic/claude-sonnet-5"
else:
    openai_client = OpenAI()
    DEFAULT_DIGEST_MODEL = "gpt-5.6-terra"

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
DIGEST_MAX_TOKENS = 1500
MAP_DIGEST_MAX_TOKENS = 6000

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


@app.middleware("http")
async def site_password_gate(request, call_next):
    if not SITE_PASSWORD:
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


DigestDensity = Literal["standard", "simplified", "verbatim"]
# 色調。None＝呼叫端沒表態（LINE、舊呼叫端），完全不注入。
DigestTone = Literal["light", "dark"]


# 一張圖最多畫幾張具名真人的臉（2026-08-18 使用者裁定，從「兩人以上一律不畫臉」放寬）。
# 3 是保守值：2026-08-18 的實驗只驗到 3 人（9/9 張臉正確對應、0 交換、0 捏臉），
# 沒有 4 人以上的證據。消化端用同一個上限把版面壓在 3 人以內（見
# REAL_WORLD_FIDELITY_RULES 第 6 條），生圖端則絕不自行截斷（見 resolve_portraits）。
MAX_PORTRAIT_FACES = 3


class GenerateRequest(BaseModel):
    news_text: str
    type_label: str
    role: str = "記者"
    density: DigestDensity = "standard"
    # True＝留白改由後端 safe_frame 置框，消化階段要出滿版版面而非縮小置中
    safe_frame: bool = False
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


# input_references 的上限。模型端 gpt-image-2 收 0–16、Gemini 0–14（PLAN.md 查證），
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
# 像素級一致，見 USER_REFERENCE_ASIS_RULES）。
class UserReferenceImage(BaseModel):
    data_url: str = Field(min_length=1, max_length=2_800_000)  # 約 2MB base64
    purpose: Literal["map", "scene", "portrait", "asis"] = "scene"


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    provider: Literal["gemini", "gpt"] = "gemini"
    aspect_ratio: str = "16:9"
    image_size: str = "1K"
    # 使用者的安全框開關。⚠️ 不等於「要不要後製」——編輯版兩檔都會後製，
    # 這個旗標只決定用哪一種（見 resolve_frame_plan）。
    safe_frame: bool = False
    # 帶的是**角色**（記者／編輯），不是解析後的 profile 名稱。
    # 實際用哪個框由 resolve_frame_plan 依（角色, safe_frame）決定：
    #   記者      → 官方 Locked-Frame（底部較深）
    #   編輯 OFF  → 對位框，拉伸填滿
    #   編輯 ON   → 2% 薄框，等比例置中
    safe_frame_profile: str = "記者"
    # 播出鏡面的挖空側（'left'／'right'）。空字串＝不挖。挖空框在**置框之後**才貼，
    # 因為置框會縮放平移內容，在原圖座標算好的框置框後會跑掉（見 compose.py）。
    broadcast_hole: str = ""
    # 真人肖像的參考照片（data URL）。空字串＝這次不附參考圖。
    reference_image_data_url: str = ""
    # 使用者上傳的參考圖（地圖底稿／實景參考）。與肖像參考照分開兩個欄位：
    # 肖像那格語意寫死是「人臉參考照」且由後端自動填，混用會打架。
    # 上限在 request 層就擋（不是只在 OpenRouter 傳輸層），任何後端路徑都收不進超量。
    reference_images: list[UserReferenceImage] = Field(
        default_factory=list, max_length=MAX_INPUT_REFERENCES
    )
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


class ImageGenerateResponse(BaseModel):
    # image_data_base64：給人看的成品（已置框／拉伸），拿去顯示與下載。
    # source_image_base64：置框「前」的原始生成圖，**只**供追加修改（refine）再編輯用。
    # 兩者不可混用——把成品餵回去改圖會二次拉伸，失真 6.4%→13.2%→20.5% 疊上去，
    # 而且每輪只多一點、很難察覺（PLAN.md ③ 的失真疊加坑）。
    # 未置框（safe_frame=False）時 source_image_base64 為空字串，成品本身就是原圖。
    # source_mime_type＝原圖實際的 MIME（模型可能回 png 也可能回 jpeg），
    # 前端組 refine 請求時要用它，不能假設一律是 png。
    image_data_base64: str
    mime_type: str
    model: str
    source_image_base64: str = ""
    source_mime_type: str = ""


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
    },
    "required": [
        "style",
        "structure",
        "variable",
        "chart_type",
        "portrait_subjects",
        "portrait_subjects_en",
    ],
    "additionalProperties": False,
}


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
     [標題] 大標題強制拆分為兩行、不含標點
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


SIMPLIFIED_DENSITY_RULES = """

SIMPLIFIED MODE OVERRIDE — THESE RULES OVERRIDE ANY EARLIER STANDARD-MODE LENGTH OR FORMAT REQUIREMENT:
1. From the source material, dynamically select only 1 to 3 key points. Do not force three points when one or two are enough.
2. Each point must communicate one fact in a short, scan-friendly line. Do not repeat the same fact in the title, points, or conclusion.
3. Remove secondary background, side facts, repeated numbers, and details that do not improve immediate understanding.
4. Use ONE dominant visual focus and choose the best presentation for the material:
   A. one hero map/chart/person/scene/process with up to three short callouts;
   B. one dominant number or conclusion with one or two supporting labels;
   C. one large thematic image/map/scene with text confined to one compact area.
5. Do not add multiple secondary card groups, unnecessary decorative icons, competing focal points, or invented filler text.
6. For editor role, ignore the earlier 150-180 character target. <蓋章> is optional, must appear only when the source supports a clear conclusion or quote, and counts as one of the maximum three points.
"""


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
5. Do not upgrade hedged wording into certainty (e.g. "約"/"可能"/"預估" must not become a flat assertion), and do not sharpen a rounded figure into a precise one.
6. EXCEPTION — supplementation is allowed ONLY when the source material itself explicitly asks for it (e.g. it contains an instruction such as 「幫我補充」「請補充」「幫我加上」「請加入背景說明」). In that case you may add widely-established background, and only within the scope requested. Absent such an instruction, add nothing.
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
4. NO UNSOURCED BRANDS. Signage, storefronts, banners, packaging, product bodies, vehicle liveries, screens, jerseys, badges and building facades must be de-identified: blank surfaces or generic abstract marks, no readable brand text, no trademark, no ticker symbol, no exchange name. A brand may appear ONLY if its name is in the source material, and then only as plain typeset text, never as a reproduced logotype. Whenever the scene contains any object that would normally carry a brand, write this requirement into "structure" explicitly — do not assume the renderer will infer it.
5. NAMED REAL PEOPLE: you do NOT decide how the face is drawn. List in "portrait_subjects" EVERY specific named real person whose face the graphic would show — one entry per person, names exactly as the source material writes them, no title, no company. If the layout shows two people, list both; listing only the first is a defect. In "structure" describe only WHERE each figure sits and what it wears, never the rendering treatment (do not write "photorealistic", "faithful likeness", "back view", "silhouette", "illustration" or similar). The backend looks up reference photographs and appends the binding portrait rules itself. Leave "portrait_subjects" as an empty array for every other graphic, including crowds and unnamed or generic figures. Always plan the 示意圖 label into "variable" when a person is depicted. Never place a person in a scene, action or context the source material does not describe.
6. AT MOST THREE FACES: the layout you design may show identifiable faces for AT MOST THREE named real people. When the source material names more, choose the three most central to the story and design "structure" so that ONLY those three appear as identifiable individual figures. The other named people are NOT removed from the story — their names and what they said may still appear as TEXT (a quote panel, a caption, a list item, a label on a chart), and that text should carry their points. What they must not have is a face: do not draw them as an identifiable figure, and never place their name beside any depicted figure, because a name sitting next to a drawn face reads as that person. "portrait_subjects" must be a truthful mirror of the faces you designed: never design a layout with four faces and list only three — the unlisted face is the exact defect this rule exists to prevent.
7. NAMES IN ENGLISH TOO: fill "portrait_subjects_en" with the same people in the same order and the same length as "portrait_subjects" — each entry being that person's name in English or its original Latin spelling (e.g. 川普 → "Donald Trump", 瓦希迪 → "Ahmad Vahidi", 巴薩尼 → "Masoud Barzani"). Take it from the source material when it gives one, otherwise from your own knowledge of the person. Use an empty string ONLY when you genuinely do not know it; never guess a spelling you are unsure of, and never translate the meaning of a Chinese name into English words. This is how the backend finds the reference photograph: Taiwanese transliterations are frequently not the title of any Chinese encyclopedia article, so without the English name the person cannot be looked up and no face can be drawn.
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

MAP ACCURACY RULES (SCOPE IS SET BY WHAT YOU ASK FOR, NOT BY THE LABEL YOU REPORT): this block binds whenever the graphic you specify puts real, named places on a map or shows them in their true relative positions — a map, a locator, a coastline, a road or district layout, a route, or markers pinned to real geography. It binds even when you report "chart_type" as 情境示意圖, 資料圖表 or 3D示意／流程: writing "a faithful map of X" or "mark these places at their real locations" into "structure" while treating this block as inapplicable is the exact failure it exists to prevent. Ignore this block ONLY when nothing you ask for places a real location — if that is the case, ignore this whole block.
1. Geographic accuracy outranks visual balance. Never ask for a place, island, coastline, border, route or marker to be moved, compressed, rotated, enlarged or rearranged so the composition fits. If everything will not fit truthfully on one map, use two maps (rule 8), never a distorted one.
2. Require a north-up orientation: north at the top, east on the right, west on the left, south at the bottom. Ask for a north arrow and a scale bar.
3. SCOPED EXCEPTION TO THE NO-NUMBERS RULE ABOVE. That rule bans percentages, pixels, ratios and numbers used for LAYOUT geometry — positions, insets, gutters and sizes on the canvas — and it still binds in full; never describe canvas geometry with a number. It does NOT cover real-world geography. For a map you MUST write into "structure": the latitude and longitude of every named place you are confident about, the coverage window of each map in degrees, real distances in kilometres, and true bearings in degrees.
4. Those geographic figures are POSITIONING DATA first: their job is to put markers in the right spot. Do NOT ask the renderer to print coordinates, degree values or bearings as labels — printing them is neither required nor requested, and "structure" must not instruct the renderer to display them. (If the renderer happens to label a marker with its coordinates anyway, that is tolerated; accuracy matters more than suppressing the label.) The text you DO ask for on the map is place names and any callout wording that already appears in "variable".
5. SCOPED EXCEPTION TO CONTENT FIDELITY ABOVE. Rule 2 there bans inventing figures. The latitude and longitude of an existing named place are not invented figures — they are fixed properties of that place, like its name, and here they are used only to put a marker in the right spot. You may therefore supply coordinates from your own geographic knowledge for that purpose alone. Everything else in CONTENT FIDELITY still binds without exception: never invent casualty counts, distances, radii, dates, areas or any other quantity the source did not state, and never put a coordinate into "variable".
6. If you are not confident of a place's real coordinates, say so in "structure" and ask for a plain coordinate grid with a labelled point marker instead of drawn coastlines. Never invent islands, coastlines, landmasses or maritime boundaries.
7. Any distance the source states must be drawn to the same scale as the rest of the map and along a stated true bearing — not as an arbitrary line with a figure attached to it.
8. When the story spans a wide area, ask for two map levels: a small north-up locator overview showing the true relative positions of the places involved, and a larger detail map centred on the incident. One map rarely serves both, and forcing it is what makes models drag distant places closer together.
9. Disputed or claimed zones (EEZ, 主張海域, 爭議邊界) must be drawn as a thin schematic boundary, never as a settled international border, and must carry the label 主張範圍 示意. Because the renderer may only draw text that was supplied to it, write that label text into "variable" as well.
10. "Simplified" applies to line styling and visual detail ONLY. Never simplify geographic positions, distances, bearings or relative scale. Use the phrase "geographically accurate simplified cartography" in "style".
11. NEVER ASK FOR A FAITHFUL MAP YOU HAVE NOT SUPPLIED THE DATA FOR. If "structure" asks for a real place to be drawn, mapped or marked at its real location, then for EVERY place it names it must also carry the positioning data rule 3 requires. If you cannot supply that data for a place, you may not use "faithful", "accurate", "real" or "geographic" map wording for it: switch that graphic to the rule 6 fallback — a labelled coordinate grid or a schematic locator with the place names as labels, stated as such in "structure" — and say plainly there that the layout is schematic. Asking for a truthful map with no coordinates behind it is precisely what makes the renderer invent geography.
12. ONE SUBJECT PLACE IN THE HEADLINE. Decide which place the incident actually happened in, and let only that place be the subject of the 標題 line in "variable". Other countries that merely reacted, commented, protested or announced a response are secondary: put them in a 內文小標 or a callout, never in the headline as the acting subject. A headline that names a reacting country beside the incident location reads as if the incident happened there, and the renderer will place that country's callout on the incident itself. Name the reacting country inside its own callout wording so the two can never be confused.
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
It does NOT outrank, and can never relax: CONTENT FIDELITY (never invent facts, figures or sources), REAL-WORLD FIDELITY, the BROADCAST SAFE AREA / FULL-FRAME layout sentence together with its ban on expressing any position or size as a number, the reporter/editor role you were given, and the rule that instruction text never becomes content. Carry out a request that would break one of those only as far as those rules allow, and satisfy the rest of the instruction normally.
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
) -> str:
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
    # 自動判斷模式組 prompt 時還不知道 AI 會選哪一類，也要注入；
    # 區塊開頭自我限縮「非地圖類整段忽略」。明確指定非地圖類型時完全不注入。
    if type_label in (MAP_TYPE_LABEL, AUTO_TYPE_LABEL):
        instructions += MAP_ACCURACY_RULES
    if density == "simplified":
        instructions += SIMPLIFIED_DENSITY_RULES
    elif density == "verbatim":
        instructions += VERBATIM_DENSITY_RULES
    # 蓋章緊接在 density 之後：ON 的第 5 條要引用逐字模式，順序不能倒過來。
    # None＝呼叫端沒表態（LINE、舊呼叫端），完全不注入，維持既有行為。
    if stamp is True:
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
    instructions += editor_formats.digest_rules(editor_format, role)
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
    return instructions


# generate_news_image() 會自己記一筆含最終 prompt 的完整紀錄，它內部呼叫的
# generate() 就不該再記一次半套的。用 contextvar 而不是函式參數，免得這個純內部
# 的旗標變成 /api/generate 對外可見的欄位。
_inside_pipeline = contextvars.ContextVar("inside_pipeline", default=False)


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
        finish = response.choices[0].finish_reason if response.choices else "?"
        ratio = completion / budget if budget else 0.0
        flag = ""
        if finish == "length":
            flag = " TRUNCATED"
        elif ratio >= DIGEST_USAGE_WARN_RATIO:
            flag = " NEAR-LIMIT"
        print(
            f"[digest_usage] site={site} model={model} budget={budget} "
            f"completion_tokens={completion} ratio={ratio:.2f} "
            f"finish={finish}{flag}",
            flush=True,
        )
    except Exception as exc:  # 監控壞掉不可以拖垮消化
        print(f"[digest_usage] 記錄失敗（不影響本次消化）：{exc}", flush=True)


def digest_completion(
    *,
    model: str,
    system_prompt: str,
    news_text: str,
    max_output_tokens: int,
    schema_name: str,
    schema: dict,
    site: str = "digest",
):
    """呼叫 Chat Completions 取結構化消化結果。

    輸出長度上限的參數名兩邊不同：OpenRouter 吃 max_tokens，OpenAI 原生的新模型
    （如 gpt-5.6-terra）只吃 max_completion_tokens，送錯直接 400。因此先送
    max_tokens，被明確拒絕時再改用 max_completion_tokens——否則沒設
    OPENROUTER_API_KEY 時的原生退路等於是壞的（實測 2026-07-30 撞到）。

    走 Gemini 時把呼叫端要求的上限拉到 GEMINI_DIGEST_MIN_TOKENS 以上——Gemini
    的隱藏思考 token 用一般上限（1200-1500）幾乎必然截斷正文（同日實測撞到）。
    """
    if DIGEST_BACKEND == "gemini":
        max_output_tokens = max(max_output_tokens, GEMINI_DIGEST_MIN_TOKENS)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f'News Source Material:\n"{news_text}"'},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    try:
        response = openai_client.chat.completions.create(
            **payload, max_tokens=max_output_tokens
        )
    except BadRequestError as exc:
        if "max_completion_tokens" not in str(exc):
            raise
        response = openai_client.chat.completions.create(
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
# 只在「指令欄是空的」時才啟用：指令欄的優先序高於消化程度（使用者裁決），
# 「濃縮成三點」本來就該把逐字要求放掉，這時候拿原文去比對會把正確結果判成錯的。
_VERBATIM_MARKER_RE = re.compile(r"\[標題\]|\[內文小標\]|<蓋章>|[<>]")
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


def verbatim_fidelity_problem(variable: str, news_text: str) -> str:
    """不消化模式：variable 去掉標記與空白後必須與原文逐字相同。"""
    body = _VERBATIM_WS_RE.sub(
        "", _VERBATIM_MARKER_RE.sub("", strip_wrapping_quotes(variable))
    )
    source = _VERBATIM_WS_RE.sub("", news_text or "")
    if body == source:
        return ""
    missing = "".join(dict.fromkeys(ch for ch in source if ch not in body))
    extra = "".join(dict.fromkeys(ch for ch in body if ch not in source))
    return (
        f"不消化模式但 variable 與原文不符（原文 {len(source)} 字、輸出 {len(body)} 字；"
        f"缺 {ascii(missing[:20])}；多 {ascii(extra[:20])}）"
    )


def digest_quality_problem(data: dict, finish_reason: str) -> str:
    """檢查消化結果是否可用，通過回傳空字串，否則回傳給 log 用的問題描述。

    語法合法不等於內容可用。截斷（finish_reason=length）與字元污染都會產生
    「能解析但不能用」的結果，必須跟解析失敗一樣走重試，不能直接送去生圖。
    """
    if finish_reason == "length":
        return "輸出被截斷（finish_reason=length）"

    for field in ("style", "structure", "variable"):
        value = data.get(field) or ""
        # 模型偶爾無視 strict schema 把欄位回成巢狀物件／陣列（2026-08-17 實測：
        # 使用者帶指令＋參考圖時 variable 回成 dict，.strip() 直接 AttributeError
        # 炸 500）。型別不對與截斷同級：能解析不代表能用，走重試。
        if not isinstance(value, str):
            return f"{field} 不是字串（{type(value).__name__}）"
        if not value.strip():
            return f"{field} 為空"
        stray = DIGEST_ALLOWED_CHARS.sub("", value)
        if len(stray) >= DIGEST_MAX_STRAY_CHARS:
            # 用 ascii() 轉義：這些字元照原樣印會在 Windows cp950 主控台丟
            # UnicodeEncodeError，把診斷訊息本身變成當掉整條請求的新故障
            return f"{field} 含 {len(stray)} 個異常字元：{ascii(stray[:40])}"

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

    return ""


def verify_internal_api_key(x_api_key: str = Header(default="")) -> None:
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
    """網頁版：查不到參考照的人，重新消化一次把他們排出版面（2026-08-18 使用者裁決）。

    與 LINE 那條（resolve_digest_portraits）同一個道理，差別只在網頁版的消化與生圖
    是兩支獨立的 API，所以要在消化端就處理完——前端拿到的消化結果已經是「只剩畫得
    出臉的人」的版面，不需要多一次來回。

    使用者上傳的肖像照視為對應**系統查不到的人**、依序對應：會自己上傳照片，通常
    正是因為那個人維基查不到（吳軒彤那個原始情境）。這是一個假設，寫在這裡是為了
    日後有人覺得對應錯了時，知道該改哪裡。

    只重試一次，理由同 resolve_digest_portraits。
    """
    subjects = result.portrait_subjects
    if not subjects:
        return result
    _, missing = lookup_portrait_photos(subjects, result.portrait_subjects_en)
    if req.portrait_photo_count:
        missing = missing[req.portrait_photo_count :]
    if not missing:
        return result

    print(
        f"[portrait] 網頁版查不到參考照（{'、'.join(missing)}），"
        "重新消化一次把他們排出版面",
        flush=True,
    )
    # 設 _inside_pipeline 是為了讓第二次消化不要又跑一次可用性檢查（會無限遞迴），
    # 也不要重複落檔——最終結果由外層那筆記錄。
    token = _inside_pipeline.set(True)
    try:
        return generate(
            req.model_copy(update={"exclude_people": missing})
        )
    finally:
        _inside_pipeline.reset(token)


@app.post(
    "/api/generate",
    response_model=GenerateResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
def generate(req: GenerateRequest):
    system_prompt = build_digest_instructions(
        role=req.role,
        density=req.density,
        type_label=req.type_label,
        # 編輯版兩檔都要滿版版面，不能直接看 safe_frame（見 resolve_frame_plan）
        full_bleed=resolve_frame_plan(req.role, req.safe_frame)[0],
        user_instruction=req.user_instruction,
        exclude_people=req.exclude_people,
        asis_reference_count=req.asis_reference_count,
        stamp=req.stamp,
        tone=req.tone,
        editor_format=req.editor_format,
    )

    # DIGEST_MODEL 可覆寫；沿用舊環境變數 OPENAI_DIGEST_MODEL 作為次要相容
    model = (
        os.getenv("DIGEST_MODEL")
        or os.getenv("OPENAI_DIGEST_MODEL")
        or DEFAULT_DIGEST_MODEL
    )
    # 上游（OpenRouter 多 provider 輪替）偶發 502、輸出截斷或不合 schema 的回傳是常態，
    # 重試圈必須涵蓋「呼叫＋解析」全程——只重試呼叫，解析失敗一樣會把錯誤丟給使用者。
    # 作法比照 hybrid_digest：金鑰／用量問題不重試（重試也沒用），其餘 3 次 × 1.5 秒。
    # 輸出上限依類型與消化程度分開給，理由見 digest_token_budget。
    max_output_tokens = digest_token_budget(req.type_label, req.density, req.news_text)
    last_detail = "AI 服務處理失敗，請確認模型權限或稍後重試"
    for attempt in range(DIGEST_ATTEMPTS):
        try:
            response = digest_completion(
                model=model,
                system_prompt=system_prompt,
                news_text=req.news_text,
                max_output_tokens=max_output_tokens,
                schema_name="news_cg_digest",
                schema=DIGEST_OUTPUT_SCHEMA,
                site="generate",
            )
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=503,
                detail="AI 服務金鑰無效或尚未啟用計費",
            ) from exc
        except RateLimitError as exc:
            raise HTTPException(
                status_code=429,
                detail="AI 服務用量已達限制，請稍後再試",
            ) from exc
        except (APIConnectionError, APIError) as exc:
            last_detail = (
                "無法連線至 AI 服務，請稍後再試"
                if isinstance(exc, APIConnectionError)
                else "AI 服務處理失敗，請確認模型權限或稍後重試"
            )
            print(f"[generate] attempt {attempt + 1}/{DIGEST_ATTEMPTS} API error: {exc}", flush=True)
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
                f"[generate] raw content: {raw_content[:800]}",
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
            time.sleep(1.5)
            continue

        # 能解析不代表能用：截斷與字元污染都要跟解析失敗一樣重試，不能送去生圖
        problem = digest_quality_problem(data, finish_reason)
        # 不消化的逐字比對排在通用檢查之後：兩者都過不了時，先報通用的那個。
        # 最後一次刻意不擋——擋了就是整條 502，而這時手上的結果通常只是頭尾多了
        # 雜訊，仍比沒有圖好；改成印警告讓回查時看得到。
        if not problem and req.density == "verbatim" and not req.user_instruction.strip():
            verbatim_problem = verbatim_fidelity_problem(
                data.get("variable") or "", req.news_text
            )
            if verbatim_problem:
                if attempt < DIGEST_ATTEMPTS - 1:
                    problem = verbatim_problem
                else:
                    print(
                        f"[generate] 最後一次嘗試仍未逐字相符，放行：{verbatim_problem}",
                        flush=True,
                    )
        if problem:
            last_detail = "AI 回傳內容異常，請稍後重試"
            print(
                f"[generate] attempt {attempt + 1}/{DIGEST_ATTEMPTS} quality check failed: {problem}",
                flush=True,
            )
            time.sleep(1.5)
            continue

        chart_type = data.get("chart_type", "")
        if chart_type not in CHART_TYPE_CHOICES:
            # AI 未回報或回報不在清單內；指定類型時退回原值，自動判斷時留空由前端處理
            chart_type = "" if req.type_label == AUTO_TYPE_LABEL else req.type_label

        result = GenerateResponse(
            style=data.get("style", ""),
            structure=data.get("structure", ""),
            variable=strip_wrapping_quotes(data.get("variable", "")),
            chart_type=chart_type,
            portrait_subjects=clean_portrait_subjects(data.get("portrait_subjects")),
            portrait_subjects_en=align_english_names(
                clean_portrait_subjects(data.get("portrait_subjects")),
                data.get("portrait_subjects_en"),
                data.get("portrait_subjects"),
            ),
        )
        # 網頁版走這個端點後自己在前端組生圖 prompt，後端看不到最終 prompt，
        # 因此這裡只記到消化為止——有輸入與消化結果，事後仍可重跑重現。
        if not _inside_pipeline.get():
            # 網頁版的第二段消化在這裡做（LINE 走 generate_news_image 自己那條，
            # 兩邊都做會白查一次圖）。落檔放在後面，記的是最終採用的那份。
            result = apply_photo_availability(result, req)
            request_log.log_generation(
                request_id=request_log.new_request_id(),
                source="digest",
                news_text=req.news_text,
                style=result.style,
                structure=result.structure,
                variable=result.variable,
                chart_type=result.chart_type,
                type_label=req.type_label,
                role=req.role,
                density=req.density,
            )
        return result

    raise HTTPException(status_code=502, detail=last_detail)


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
    model = (
        os.getenv("DIGEST_MODEL")
        or os.getenv("OPENAI_DIGEST_MODEL")
        or DEFAULT_DIGEST_MODEL
    )
    # 一鍵成圖是無人值守流程：上游偶發失敗（provider 輪替錯誤、輸出截斷、
    # 不合 schema 的回傳）都必須在後端自動吸收重試，不能丟回給外勤記者
    last_detail = "AI 服務處理失敗，請確認模型權限或稍後重試"
    for attempt in range(3):
        try:
            response = digest_completion(
                model=model,
                system_prompt=HYBRID_SYSTEM_PROMPT,
                news_text=req.news_text,
                max_output_tokens=1200,
                schema_name="hybrid_card_digest",
                schema=HYBRID_DIGEST_SCHEMA,
                site="hybrid",
            )
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=503,
                detail="AI 服務金鑰無效或尚未啟用計費",
            ) from exc
        except RateLimitError as exc:
            raise HTTPException(
                status_code=429,
                detail="AI 服務用量已達限制，請稍後再試",
            ) from exc
        except (APIConnectionError, APIError) as exc:
            last_detail = (
                "無法連線至 AI 服務，請稍後再試"
                if isinstance(exc, APIConnectionError)
                else "AI 服務處理失敗，請確認模型權限或稍後重試"
            )
            print(f"[hybrid] attempt {attempt + 1}/3 API error: {exc}", flush=True)
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
            return HybridDigestResponse(**data)
        except (json.JSONDecodeError, IndexError, TypeError, ValueError) as exc:
            last_detail = "AI 回傳格式無法解析"
            print(
                f"[hybrid] attempt {attempt + 1}/3 parse failed "
                f"(finish_reason={finish_reason}): {exc}\n"
                f"[hybrid] raw content: {raw_content[:800]}",
                flush=True,
            )
            time.sleep(1.5)

    raise HTTPException(status_code=502, detail=last_detail)


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
    req = apply_portrait_to_image_request(req)
    req = apply_user_references_to_image_request(req)
    request_id = request_log.new_request_id()
    try:
        # safe_frame_profile 帶的是「角色」，實際要用哪個框在這裡才決定——
        # 全系統只有這一個解析點，pipeline 與網頁版直呼都會經過。
        _, needs_frame, frame_profile = resolve_frame_plan(
            req.safe_frame_profile, req.safe_frame
        )
        result = finalize_image_result(
            generate_image_raw(req),
            aspect_ratio=req.aspect_ratio,
            safe_frame=needs_frame,
            profile=frame_profile,
            broadcast_hole=req.broadcast_hole,
        )
    except Exception as exc:
        if not _inside_pipeline.get():
            request_log.log_failure(
                request_id=request_id,
                source="web-image",
                news_text="",
                error=str(exc),
                prompt=req.prompt,
                provider=req.provider,
            )
        raise
    if not _inside_pipeline.get():
        request_log.log_generation(
            request_id=request_id,
            source="web-image",
            news_text="",
            prompt=req.prompt,
            provider=req.provider,
            image_model=result.model,
        )
        gcs_archive.archive_generation(
            request_id=request_id,
            image_base64=result.image_data_base64,
            mime_type=result.mime_type,
            source="web-image",
            prompt=req.prompt,
            provider=req.provider,
            image_model=result.model,
        )
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


def supports_reference_image(provider: str) -> bool:
    """這次的生圖後端能不能真的把參考圖送出去。

    存在理由：附圖能力與 prompt 措辭必須一致。原生 OpenAI 的 images.generate
    沒有參考圖通道，若照樣叫模型「參考附圖」，模型只能憑印象捏一張臉——比不
    提附圖更糟。因此送不出去時，呼叫端要改用「不生成臉孔」的規則。
    """
    if os.getenv("IMAGE_BACKEND", "openrouter") == "openrouter" and os.getenv(
        "OPENROUTER_API_KEY"
    ):
        return True
    return provider != "gpt"


def supports_multiple_reference_images() -> bool:
    """多張參考圖（reference_images 陣列）只有 OpenRouter 路徑送得出去。

    存在理由：supports_reference_image() 對 native-gemini 回 True，但那條
    只送單張 reference_image_data_url——若拿它當放行條件，使用者上傳的
    reference_images 會被靜默丟掉、prompt 卻已寫著「依附圖」，正是
    「叫模型參考不存在的附圖」這個最糟情境。判斷必須用這支。
    """
    return os.getenv("IMAGE_BACKEND", "openrouter") == "openrouter" and bool(
        os.getenv("OPENROUTER_API_KEY")
    )


# 一家一個模型，OpenRouter 與原生兩條路徑共用同一個——否則切 IMAGE_BACKEND 會連模型一起
# 換掉，而兩個模型的能力並不相同（2026-08-01 清查：OpenRouter 那條原本是 gpt-5.4-image-2、
# 原生那條是 gpt-image-2，文件卻只寫後者）。
# GPT 選 gpt-image-2 的理由：OpenAI 家族只有它在 API 層支援安全框要的 21:9，
# gpt-5.4-image-2 / gpt-5-image 系列連 aspect_ratio 參數都沒有。
NATIVE_GPT_IMAGE_MODEL = "gpt-image-2"
NATIVE_GEMINI_IMAGE_MODEL = "gemini-3-pro-image"
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
    result: ImageGenerateResponse, profile: str = "記者"
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


def apply_broadcast_hole_response(
    result: ImageGenerateResponse, side: str, profile: str
) -> ImageGenerateResponse:
    """在置框後的成品上貼出播出鏡面的挖空框。

    與置框同一個原則：失敗就整支失敗。悄悄回傳一張沒有挖空框的圖，編輯會直接
    拿去給後製，那邊才發現沒有位置放影片。
    """
    try:
        holed = compose.apply_broadcast_hole(
            base64.b64decode(result.image_data_base64), side, profile=profile
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


def finalize_image_result(
    result: ImageGenerateResponse,
    *,
    aspect_ratio: str,
    safe_frame: bool,
    profile: str,
    broadcast_hole: str = "",
) -> ImageGenerateResponse:
    """生成後的共同收尾：驗比例，需要時置框並保留置框前原圖。

    generate_image 與 refine_image 共用。置框前的原圖（含實際 MIME）要留給
    追加修改（refine）用：把置框後成品餵回去改圖會二次拉伸
    （見 ImageGenerateResponse 的欄位說明）。
    """
    verify_output_aspect_ratio(result, aspect_ratio)
    if not safe_frame:
        # 沒有置框就沒有可靠的成品座標系，挖空框無處可貼。播出鏡面一律開安全框，
        # 走到這裡代表呼叫端組錯了，出聲比默默少一個框好。
        if broadcast_hole:
            print("[compose] safe_frame=False，跳過播出鏡面挖空框", flush=True)
        return result
    framed = frame_image_response(result, profile)
    if broadcast_hole:
        framed = apply_broadcast_hole_response(framed, broadcast_hole, profile)
    return framed.model_copy(
        update={
            # 追加修改要餵**置框前**原圖回去，不是挖過洞的成品（見欄位說明）
            "source_image_base64": result.image_data_base64,
            "source_mime_type": result.mime_type,
        }
    )


def generate_via_openrouter(model: str, req: ImageGenerateRequest) -> ImageGenerateResponse:
    """透過 OpenRouter 統一圖片端點生成，一把 OPENROUTER_API_KEY 涵蓋多家模型。"""
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
    # 參考圖兩個來源合併送出：肖像參考照（自動查圖）在前、使用者上傳在後。
    # gpt-image-2 支援 0–16 張、Gemini 0–14 張（PLAN.md 已向 models 端點查證），
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


# 原生 OpenAI 沒有 aspect_ratio，只吃 size。gpt-image-2 接受任意 16 的倍數
# （標準上限 2560×1440），這裡挑貼合比例、又不超過上限的尺寸。
# 2026-08-01 之前這裡寫死 1280x720，等於無視呼叫端要的比例——安全框開 21:9
# 也會靜靜拿回 16:9，是與 OpenRouter 那條同一類的靜默降級。
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


def generate_gpt_image(req: ImageGenerateRequest) -> ImageGenerateResponse:
    model = os.getenv("OPENAI_IMAGE_MODEL", NATIVE_GPT_IMAGE_MODEL)
    quality = os.getenv("OPENAI_IMAGE_QUALITY", "medium")

    size = NATIVE_GPT_IMAGE_SIZES.get(req.aspect_ratio)
    if size is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"原生 OpenAI 生圖沒有對應 aspect_ratio={req.aspect_ratio} 的尺寸，"
                f"可用比例：{'、'.join(NATIVE_GPT_IMAGE_SIZES)}。"
                "改走 OpenRouter（IMAGE_BACKEND=openrouter）可支援更多比例。"
            ),
        )

    try:
        result = openai_client.images.generate(
            model=model,
            prompt=req.prompt,
            size=size,
            quality=quality,
            output_format="png",
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


def resolve_frame_plan(role: str, safe_frame: bool) -> tuple[bool, bool, str]:
    """把（角色, 安全框開關）翻成（要滿版版面?, 要後製置框?, 置框 profile）。

    這是編輯版兩種模式的唯一決定點，三個呼叫端（消化、生圖、整條 pipeline）
    都問這裡，才不會有人漏接就悄悄退回舊行為。

    編輯版（2026-08-19 起）：**兩檔都是滿版生成＋後製**，開關只決定後製方式——
      OFF → 拉伸填滿對位框（即 2026-08-17～08-19 掛在 ON 的那個行為）
      ON  → 四周各壓 2% 薄框，輸出完整 1920×1080
    原本 OFF 那條「靠 prompt 叫模型自己縮小置中留厚邊、完全不後製」已依使用者
    2026-08-19 裁決廢除，編輯版不再有任何不後製的路徑。

    記者版不受影響：OFF 就是不出滿版版面、也不後製。
    """
    if role == safe_area_spec.EDITOR_PROFILE:
        profile = (
            safe_area_spec.EDITOR_FRAME_PROFILE
            if safe_frame
            else safe_area_spec.EDITOR_PROFILE
        )
        return True, True, profile
    return safe_frame, safe_frame, safe_area_spec.REPORTER_PROFILE


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


def resolve_portraits(
    portrait_subjects: list[str],
    provider: str,
    *,
    photos: dict[str, photo_lookup.ReferencePhoto] | None = None,
    english_names: list[str] | None = None,
) -> tuple[str, list[photo_lookup.ReferencePhoto]]:
    """決定這次的肖像處理方式，回傳 (portrait_mode, 參考照片清單)。

    四種結果：
    - 不是真人肖像題 → ("none", [])，沿用一般規則
    - 1 位且查到照片 → ("reference", [照片])，措辭與行為與放寬前逐字相同
    - 2-3 位且**每一位都查到照片** → ("reference_multi", [照片…])
    - 其餘（有人查不到、超過 3 位、後端送不出參考圖）→ ("no_reference", [])

    **全有或全無，後端絕不自行截斷**（2026-08-18 實驗結論）：只要有一位沒有照片，
    整張退回不畫臉。理由是實測 2/2 證明「有照片的畫、沒照片的畫剪影」這種逐人區分
    生圖模型辦不到，沒照片的那位會被憑空捏臉還掛真名。也不能把 4 人截成 3 人——
    版面是照 4 個人設計的，砍掉一個會留下一個沒人的空位。超過 3 人要在**消化階段**
    就壓下來（見 REAL_WORLD_FIDELITY_RULES 第 6 條與 EXCLUDED_PEOPLE_RULES_TEMPLATE）。

    `photos` 可由呼叫端先查好傳進來（兩段式消化流程會重複用到同一批查詢結果），
    沒傳就自己查。
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
    if len(portrait_subjects) > 1 and not supports_multiple_reference_images():
        print("[portrait] 目前後端送不出多張參考圖，多人肖像退回不生成臉孔", flush=True)
        return "no_reference", []
    if photos is None:
        photos, _ = lookup_portrait_photos(portrait_subjects, english_names)
    missing = [name for name in portrait_subjects if name not in photos]
    if missing:
        print(
            f"[portrait] 查不到參考照（{'、'.join(missing)}），整張退回不生成臉孔",
            flush=True,
        )
        return "no_reference", []
    ordered = [photos[name] for name in portrait_subjects]
    mode = "reference" if len(ordered) == 1 else "reference_multi"
    return mode, ordered


def resolve_portrait(
    portrait_subjects: list[str], provider: str
) -> tuple[str, photo_lookup.ReferencePhoto | None]:
    """單人版的舊介面：只回傳第一張照片。網頁版單人路徑仍在用。"""
    mode, photos = resolve_portraits(portrait_subjects, provider)
    return mode, (photos[0] if len(photos) == 1 else None)


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
        return req
    english = align_english_names(
        subjects, req.portrait_subjects_en, req.portrait_subjects
    )
    uploaded = [ref for ref in req.reference_images if ref.purpose == "portrait"]
    if not uploaded:
        mode, photos = resolve_portraits(
            subjects, req.provider, english_names=english
        )
        block = PORTRAIT_MODES.get(mode, "")
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
        ):
            return req
        return req.model_copy(
            update={
                "prompt": prompt,
                "reference_image_data_url": reference,
                "portrait_reference_data_urls": portrait_urls,
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
    if not photos or req.portrait_reference_data_urls:
        return req
    return req.model_copy(
        update={
            "portrait_reference_data_urls": [
                photos[name].data_url() for name in subjects if name in photos
            ]
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
    if not supports_multiple_reference_images():
        raise HTTPException(
            status_code=400,
            detail="目前的生圖後端無法附上上傳的參考圖（僅 OpenRouter 路徑支援多張參考圖），"
            "請移除上傳的參考圖，或改回 OpenRouter 生圖設定",
        )
    prompt = req.prompt
    for purpose in dict.fromkeys(ref.purpose for ref in req.reference_images):
        block = USER_REFERENCE_MODES.get(purpose, "")
        if block and block not in prompt:
            prompt = f"{prompt.rstrip()}\n\n{block}"
    # 有上傳就不標「示意圖」（2026-08-17 使用者裁決）；固定放最後才能 OVERRIDE
    # REAL_WORLD_RENDERING_RULES 的「標籤不得移除」條款。
    # 例外：這張圖裡混了後端自動查來的肖像照時仍要標（2026-08-18）——那個 override
    # 的語意是「照著使用者親自提供的素材生成」，維基照片沒有那個語意，而
    # 寫實照片感＋真名＋沒有示意圖標籤是最糟的組合。
    if req.portrait_reference_data_urls:
        return req.model_copy(update={"prompt": prompt}) if prompt != req.prompt else req
    if USER_REFERENCE_NO_DISCLAIMER_RULES not in prompt:
        prompt = f"{prompt.rstrip()}\n\n{USER_REFERENCE_NO_DISCLAIMER_RULES}"
    if prompt == req.prompt:
        return req
    return req.model_copy(update={"prompt": prompt})


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
    safe_frame_profile: str = "記者"
    # 追加修改要沿用同一個挖空側，否則改完圖那塊空位就不見了
    broadcast_hole: str = ""


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
    if not supports_reference_image(req.provider):
        raise HTTPException(
            status_code=400,
            detail="目前的生圖後端無法附上參考圖，無法以圖改圖；請整張重新生成",
        )
    image_req = ImageGenerateRequest(
        prompt=build_refine_prompt(req.instruction),
        provider=req.provider,
        aspect_ratio=req.aspect_ratio,
        image_size=req.image_size,
        safe_frame=req.safe_frame,
        safe_frame_profile=req.safe_frame_profile,
        broadcast_hole=req.broadcast_hole,
        reference_image_data_url=(
            f"data:{req.source_mime_type};base64,{req.source_image_base64}"
        ),
    )
    request_id = request_log.new_request_id()
    try:
        # 追加修改也要走同一個解析點，否則編輯 OFF 改完圖會整個跳過後製，
        # 出來一張沒置框的原始生成圖（尺寸與版面都不對，卻不會報錯）。
        _, needs_frame, frame_profile = resolve_frame_plan(
            req.safe_frame_profile, req.safe_frame
        )
        result = finalize_image_result(
            generate_image_raw(image_req),
            aspect_ratio=req.aspect_ratio,
            safe_frame=needs_frame,
            profile=frame_profile,
            broadcast_hole=req.broadcast_hole,
        )
    except Exception as exc:
        request_log.log_failure(
            request_id=request_id,
            source="web-refine",
            news_text="",
            error=str(exc),
            prompt=image_req.prompt,
            provider=req.provider,
        )
        raise
    request_log.log_generation(
        request_id=request_id,
        source="web-refine",
        news_text="",
        prompt=image_req.prompt,
        provider=req.provider,
        image_model=result.model,
    )
    gcs_archive.archive_generation(
        request_id=request_id,
        image_base64=result.image_data_base64,
        mime_type=result.mime_type,
        source="web-refine",
        prompt=image_req.prompt,
        provider=req.provider,
        image_model=result.model,
    )
    return result


def resolve_digest_portraits(
    digest: GenerateResponse, req: NewsImageGenerateRequest, provider: str
) -> tuple[GenerateResponse, dict[str, photo_lookup.ReferencePhoto]]:
    """查參考照；有人查不到就重新消化一次，把那些人排出版面。

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

    photos, missing = lookup_portrait_photos(subjects, digest.portrait_subjects_en)
    if not missing:
        return digest, photos

    print(
        f"[portrait] 查不到參考照（{'、'.join(missing)}），重新消化一次把他們排出版面",
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
            exclude_people=missing,
        )
    )
    if not retried.portrait_subjects:
        return retried, {}
    photos, missing = lookup_portrait_photos(
        retried.portrait_subjects, retried.portrait_subjects_en
    )
    if missing:
        print(
            f"[portrait] 重新消化後仍有人查不到照片（{'、'.join(missing)}），不再重試",
            flush=True,
        )
    return retried, photos


def generate_news_image(req: NewsImageGenerateRequest) -> NewsImageGenerateResponse:
    # 前置過濾（縱深防禦）：擋垃圾／亂碼／注入輸入，避免燒掉付費呼叫。
    # LINE 路徑在 line_bot 已含頻率限制地查過一次，這裡 client_id 為空時
    # 只做內容檢查、不重複觸發頻率限制。
    verdict = check_input(req.news_text, client_id=req.client_id)
    if not verdict.accepted:
        raise HTTPException(status_code=400, detail=verdict.user_message)
    if req.client_id:
        note_accepted(req.news_text, client_id=req.client_id)
    request_id = request_log.new_request_id()
    # 編輯固定 GPT＋16:9＋對位框；記者維持呼叫端 provider、safe_frame 時 21:9
    provider = "gpt" if req.role == "編輯" else req.provider
    aspect_ratio = resolve_aspect_ratio(req.aspect_ratio, req.safe_frame, req.role)
    token = _inside_pipeline.set(True)
    try:
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
            )
        )
        digest, portrait_photos = resolve_digest_portraits(digest, req, provider)
        portrait_mode, reference_photos = resolve_portraits(
            digest.portrait_subjects, provider, photos=portrait_photos
        )
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
        )
        try:
            image = generate_image(
                ImageGenerateRequest(
                    prompt=prompt,
                    provider=provider,
                    broadcast_hole=editor_formats.hole_side(req.editor_format, req.role) or "",
                    aspect_ratio=aspect_ratio,
                    image_size=req.image_size,
                    safe_frame=req.safe_frame,
                    # 傳角色而非解析後的 profile：generate_image 會解析一次，
                    # 這裡先解析會讓它拿「編輯安全框」當角色再解析一次而解錯。
                    safe_frame_profile=req.role,
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
                )
            )
        except Exception as exc:
            request_log.log_failure(
                request_id=request_id,
                source=req.source or "news-image",
                client_id=req.client_id,
                news_text=req.news_text,
                error=str(exc),
                style=digest.style,
                structure=digest.structure,
                variable=digest.variable,
                prompt=prompt,
                chart_type=digest.chart_type,
                type_label=req.type_label,
                role=req.role,
                density=req.density,
                provider=provider,
            )
            raise
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
        )
        # LINE 版圖檔已由 line_bot.py 存進 static/generated/，這裡只補網頁版的缺口
        if req.source != "line":
            gcs_archive.archive_generation(
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
                provider=provider,
                image_model=image.model,
                portrait_subject="、".join(digest.portrait_subjects),
            )
        return NewsImageGenerateResponse(
            image_data_base64=image.image_data_base64,
            mime_type=image.mime_type,
            model=image.model,
            title=_extract_title(digest.variable),
            request_id=request_id,
            source_image_base64=image.source_image_base64,
            source_mime_type=image.source_mime_type,
        )
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
    title_right: str = Field(min_length=1, max_length=40)
    # 給生圖模型的視覺描述（畫什麼場景），不會出現在成品文字上。
    # 2026-09-03 起改選填：留空時由 resolve_cover_visuals 依標題請文字模型補。
    visual_left: str = Field(default="", max_length=500)
    visual_right: str = Field(default="", max_length=500)
    date_text: str = Field(default="", max_length=20)
    badge: str = compose.COVER_DEFAULT_BADGE
    provider: Literal["gemini", "gpt"] = "gpt"
    # ai＝整張交給生圖模型畫（預設，2026-09-03 使用者裁決要設計感）
    # composite＝AI 只出兩張無文字底圖、文字由 Pillow 畫（零錯字但沒設計感，留作備援）
    mode: Literal["ai", "composite"] = editor_formats.COVER_MODE_AI


class TenCoverResponse(ImageGenerateResponse):
    # 這次實際採用的畫面描述（使用者留空時是 AI 補的）。前端會填回欄位——
    # 不回報的話使用者永遠不知道 AI 幫他決定了什麼，也沒辦法微調後重生。
    visual_left: str = ""
    visual_right: str = ""


def resolve_cover_visuals(req: "TenCoverRequest") -> tuple[str, str]:
    """畫面描述留空時依標題補齊；兩欄都有值就原樣回傳，不打 API。"""
    left, right = req.visual_left.strip(), req.visual_right.strip()
    if left and right:
        return left, right

    material = 'LEFT headline: {}\\nLEFT description already supplied: {}\\nRIGHT headline: {}\\nRIGHT description already supplied: {}'.format(
        req.title_left.strip(),
        left or "(none — write one)",
        req.title_right.strip(),
        right or "(none — write one)",
    )
    model = (
        os.getenv("DIGEST_MODEL")
        or os.getenv("OPENAI_DIGEST_MODEL")
        or DEFAULT_DIGEST_MODEL
    )
    try:
        response = digest_completion(
            model=model,
            system_prompt=editor_formats.COVER_VISUAL_DERIVE_SYSTEM,
            news_text=material,
            max_output_tokens=600,
            schema_name="cover_visuals",
            schema=editor_formats.COVER_VISUAL_SCHEMA,
            site="cover",
        )
        data = parse_digest_json(response.choices[0].message.content or "")
    except Exception as exc:  # noqa: BLE001
        # 補描述失敗不該讓整張封面失敗：退回用標題本身當畫面提示，
        # 畫出來會比較平淡但仍是一張可用的封面。
        print(f"[cover] 自動補畫面描述失敗，改用標題：{type(exc).__name__}: {exc}", flush=True)
        return left or req.title_left.strip(), right or req.title_right.strip()

    derived_left = (data.get("visual_left") or "").strip()
    derived_right = (data.get("visual_right") or "").strip()
    # 使用者填的永遠優先，AI 只補空的那一欄
    return (
        left or derived_left or req.title_left.strip(),
        right or derived_right or req.title_right.strip(),
    )


def _cover_panel_image(visual: str, provider: str) -> bytes:
    """生一張 1:1 的無文字底圖。"""
    result = generate_image_raw(
        ImageGenerateRequest(
            prompt=editor_formats.COVER_VISUAL_PROMPT_TEMPLATE.format(visual=visual.strip()),
            provider=provider,
            aspect_ratio="1:1",
            image_size="1K",
            safe_frame=False,
        )
    )
    return base64.b64decode(result.image_data_base64)


def _cover_ai(req: TenCoverRequest, date_text: str, visuals: tuple[str, str]) -> bytes:
    """純 prompt 版：整張封面由生圖模型畫，之後只補貼正版 Logo。"""
    badge_text = compose.COVER_BADGES[req.badge][0]
    prompt = editor_formats.COVER_AI_PROMPT_TEMPLATE.format(
        badge_text=badge_text,
        date_text=date_text,
        title_left=req.title_left.strip(),
        title_right=req.title_right.strip(),
        visual_left=visuals[0],
        visual_right=visuals[1],
    )
    result = generate_image_raw(
        ImageGenerateRequest(
            prompt=prompt,
            provider=req.provider,
            aspect_ratio="16:9",
            image_size="1K",
            safe_frame=False,
        )
    )
    return compose.paste_cover_logo(base64.b64decode(result.image_data_base64))


def _cover_composite(
    req: TenCoverRequest, date_text: str, visuals: tuple[str, str]
) -> bytes:
    """合成版（備援）：AI 只出兩張無文字底圖，文字全部由 Pillow 畫。"""
    # 兩張圖平行生。序列跑會讓等待時間直接加倍——單張本來就要 30–90 秒。
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_cover_panel_image, visual, req.provider)
            for visual in visuals
        ]
        left_image, right_image = (future.result() for future in futures)
    return compose.compose_ten_cover(
        left_image,
        right_image,
        title_left=req.title_left.strip(),
        title_right=req.title_right.strip(),
        date_text=date_text,
        badge=req.badge,
    )


@app.post(
    "/api/editor/cover",
    response_model=TenCoverResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
def editor_cover(req: TenCoverRequest) -> TenCoverResponse:
    if req.badge not in compose.COVER_BADGES:
        raise HTTPException(
            status_code=400,
            detail=f"未知的標籤：{req.badge}（可用：{list(compose.COVER_BADGES)}）",
        )
    date_text = req.date_text.strip() or datetime.date.today().strftime("%Y/%m/%d")

    visuals = resolve_cover_visuals(req)
    try:
        if req.mode == editor_formats.COVER_MODE_AI:
            cover = _cover_ai(req, date_text, visuals)
        else:
            cover = _cover_composite(req, date_text, visuals)
    except compose.ComposeError as exc:
        print(f"[compose] 封面失敗：{exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"封面生成失敗：{exc}") from exc

    request_log.log_generation(
        request_id=request_log.new_request_id(),
        source="editor-cover",
        news_text=f"{req.title_left} ｜ {req.title_right}",
        variable=f"{req.title_left}\n{req.title_right}",
        prompt=f"L: {visuals[0]}\nR: {visuals[1]}",
        role="編輯",
        provider=req.provider,
    )
    return TenCoverResponse(
        image_data_base64=base64.b64encode(cover).decode("ascii"),
        mime_type="image/png",
        model=f"ten-cover:{req.mode}",
        visual_left=visuals[0],
        visual_right=visuals[1],
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


# app.js／hybrid.js 進 git 時 _INTERNAL_API_KEY 只是占位符，容器啟動時由
# entrypoint.sh sed 換成真實值。本機直跑 uvicorn 沒有那一步，瀏覽器會拿著
# 占位符打 API 吃 401——所以 serve 時做同一件事：占位符還在且環境有金鑰就換掉。
# 容器內檔案已被 sed 過，這裡的 replace 是 no-op，兩條路徑行為一致。
def _serve_js_with_key(name: str) -> PlainTextResponse:
    text = (_REPO_ROOT / name).read_text(encoding="utf-8")
    key = os.getenv("NEWS_IMAGE_API_KEY", "").strip()
    if key:
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


def main():
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8787, reload=True)


if __name__ == "__main__":
    main()
