import json
import os
import ssl
import time
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import APIConnectionError, APIError, AuthenticationError, OpenAI, RateLimitError
from pydantic import BaseModel, Field

load_dotenv()

# Digest（生成 Prompt）預設走 OpenRouter，與生圖共用同一把 OPENROUTER_API_KEY；
# 未設定 OPENROUTER_API_KEY 時退回 OpenAI 原生直連。
_openrouter_key = os.getenv("OPENROUTER_API_KEY")
if _openrouter_key:
    openai_client = OpenAI(
        base_url="https://openrouter.ai/api/v1", api_key=_openrouter_key
    )
    DEFAULT_DIGEST_MODEL = "anthropic/claude-sonnet-5"
else:
    openai_client = OpenAI()
    DEFAULT_DIGEST_MODEL = "gpt-5.6-terra"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)


DigestDensity = Literal["standard", "simplified"]


class GenerateRequest(BaseModel):
    news_text: str
    type_label: str
    role: str = "記者"
    density: DigestDensity = "standard"


class GenerateResponse(BaseModel):
    style: str
    structure: str
    variable: str
    # 這次實際採用的圖表類型（自動判斷模式下為 AI 所選）
    chart_type: str = ""


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    provider: Literal["gemini", "gpt"] = "gemini"
    aspect_ratio: str = "16:9"
    image_size: str = "1K"


class ImageGenerateResponse(BaseModel):
    image_data_base64: str
    mime_type: str
    model: str


# 第一頁「懶人機制」：type_label 傳這個值代表由 AI 自行判斷最適合的圖表類型
AUTO_TYPE_LABEL = "自動判斷"

# AI 可自行選擇的四大類型，需與 app.js 的 CHART_TYPES label 完全一致
CHART_TYPE_CHOICES = ["資料圖表", "情境示意圖", "地圖／位置", "3D示意／流程"]

DIGEST_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "style": {"type": "string"},
        "structure": {"type": "string"},
        "variable": {"type": "string"},
        # 回報這次實際採用的圖表類型；自動判斷模式下前端用它顯示 AI 選了什麼
        "chart_type": {"type": "string", "enum": CHART_TYPE_CHOICES},
    },
    "required": ["style", "structure", "variable", "chart_type"],
    "additionalProperties": False,
}


AUTO_TYPE_SELECTION_RULES = """

CHART TYPE AUTO-SELECTION (do this first):
No chart type was specified. Read the news material and choose the ONE most suitable type:
- "資料圖表": the story's core is numbers to compare or track (markets, prices, polls, statistics).
- "情境示意圖": the story's core is what a scene or incident looked like (accidents, disasters,人物場景).
- "地圖／位置": the story's core is where something is — location, route, territory, or geographic relationship.
- "3D示意／流程": the story's core is how something happened step by step, or how a mechanism works.
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
   - BROADCAST SAFE AREA (NON-NEGOTIABLE): the structure description MUST begin with this exact sentence: "The entire infographic — including the title, icon cards, and side panels — is treated as one group and scaled down so it occupies only the central region of the frame, surrounded by a thick, clearly visible empty margin of unchanged background on the top, left and right, and an even deeper empty band along the bottom; every element stays well inside this central zone and nothing reaches into the surrounding empty border." After that sentence, every element you place (headline, stat cards, indicators, icons) MUST be positioned using ONLY qualitative spatial words (e.g. "in the upper-left area", "centred", "along the right side well clear of the edge", "with generous empty space around it"). NEVER express any position, inset, gutter, margin, or size as a percentage, pixel, ratio, or number of any kind — those figures get drawn as visible text labels in the final image. Never describe anything as spanning, flush, or edge-to-edge. The words "footer", "bottom edge", "anchored at bottom", "full-screen", "full-bleed", "full-width", "edge-to-edge", "flush left", "flush right", "spans the entire width", "corner-to-corner" and "bleed" are FORBIDDEN. Any closing banner or data-source line is the LOWEST ROW OF THE CONTENT AREA, sitting well above the reserved bottom margin, never at the frame bottom or against any edge."""


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
2. "style": 根據新聞調性（財經、災難、溫馨、政治）選擇主色調與畫面風格（例如：深藍色科技感、紅白色警戒感），written in professional English.
3. "structure": Design the most readable anchor-wall CG layout for a "{type_label}", with concrete spatial arrangement and instructions for flat icons or 3D data charts that aid comprehension. Written in professional English.
   - BROADCAST SAFE AREA (NON-NEGOTIABLE): the structure description MUST begin with this exact sentence: "The entire infographic — including the title, icon cards, and data charts — is treated as one group and scaled down so it occupies only the central region of the frame, surrounded by a thick, clearly visible empty margin of unchanged background on the top, left and right, and an even deeper empty band along the bottom; every element stays well inside this central zone and nothing reaches into the surrounding empty border." After that sentence, every element you place MUST be positioned using ONLY qualitative spatial words (e.g. "in the upper-left area", "centred", "along the right side well clear of the edge", "with generous empty space around it"). NEVER express any position, inset, gutter, margin, or size as a percentage, pixel, ratio, or number of any kind — those figures get drawn as visible text labels in the final image. Never describe anything as spanning, flush, or edge-to-edge. The words "footer", "bottom edge", "anchored at bottom", "full-screen", "full-bleed", "full-width", "edge-to-edge", "flush left", "flush right", "flush top", "flush bottom", "spans the entire width", "corner-to-corner" and "bleed" are FORBIDDEN. The <蓋章> stamp banner and any data-source line are the LOWEST ROW OF THE CONTENT AREA, sitting well above the reserved bottom margin, never at the frame bottom or against any edge."""


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


def build_digest_instructions(
    role: str,
    density: DigestDensity,
    type_label: str,
) -> str:
    template = (
        EDITOR_SYSTEM_PROMPT_TEMPLATE if role == "編輯" else SYSTEM_PROMPT_TEMPLATE
    )
    # 自動判斷模式下，樣板裡的類型描述改為由 AI 自選（實際選型規則見下方 directive）
    rendered_label = (
        "the chart type you select below"
        if type_label == AUTO_TYPE_LABEL
        else type_label
    )
    instructions = template.format(type_label=rendered_label)
    instructions += chart_type_directive(type_label)
    if density == "simplified":
        instructions += SIMPLIFIED_DENSITY_RULES
    return instructions


@app.post("/api/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    system_prompt = build_digest_instructions(
        role=req.role,
        density=req.density,
        type_label=req.type_label,
    )

    # DIGEST_MODEL 可覆寫；沿用舊環境變數 OPENAI_DIGEST_MODEL 作為次要相容
    model = (
        os.getenv("DIGEST_MODEL")
        or os.getenv("OPENAI_DIGEST_MODEL")
        or DEFAULT_DIGEST_MODEL
    )
    try:
        # Chat Completions 介面 OpenRouter 與 OpenAI 原生皆通用
        response = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f'News Source Material:\n"{req.news_text}"',
                },
            ],
            max_tokens=1500,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "news_cg_digest",
                    "strict": True,
                    "schema": DIGEST_OUTPUT_SCHEMA,
                },
            },
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
    except APIConnectionError as exc:
        raise HTTPException(
            status_code=502,
            detail="無法連線至 AI 服務，請稍後再試",
        ) from exc
    except APIError as exc:
        raise HTTPException(
            status_code=502,
            detail="AI 服務處理失敗，請確認模型權限或稍後重試",
        ) from exc

    try:
        data = json.loads(response.choices[0].message.content or "")
    except (json.JSONDecodeError, IndexError):
        raise HTTPException(status_code=502, detail="AI 回傳格式無法解析")

    chart_type = data.get("chart_type", "")
    if chart_type not in CHART_TYPE_CHOICES:
        # AI 未回報或回報不在清單內；指定類型時退回原值，自動判斷時留空由前端處理
        chart_type = "" if req.type_label == AUTO_TYPE_LABEL else req.type_label

    return GenerateResponse(
        style=data.get("style", ""),
        structure=data.get("structure", ""),
        variable=data.get("variable", ""),
        chart_type=chart_type,
    )


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
    subtitle: str
    items: list[HybridItem]
    source: str
    visual_subject: str


HYBRID_DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
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
    "required": ["title", "subtitle", "items", "source", "visual_subject"],
    "additionalProperties": False,
}

HYBRID_SYSTEM_PROMPT = """You are a Taiwanese TV news graphics editor. Digest the news material into structured data for a fixed-layout 3-column comparison news card. The APP renders all text itself, so your output IS the on-screen text — accuracy is everything.

Rules:
- All text in Traditional Chinese (Taiwan standard, 台灣慣用語). NEVER Simplified Chinese. Keep proper nouns customarily shown in original language as-is (e.g. NASDAQ, S&P 500, B-1).
- title: 電視新聞主標題, punchy, at most 12 full-width characters, no punctuation.
- subtitle: 補充副標（時間、範圍等）, at most 12 full-width characters; empty string if nothing suitable.
- items: EXACTLY 3 key data points, the most newsworthy numbers in the material.
  - label: at most 6 full-width characters.
  - value: the number with its unit (e.g. 44,023.29 / 3.2萬人 / 24枚). Numbers must come from the source material — NEVER invent or estimate missing figures.
  - change: magnitude of change without any arrow symbol (e.g. 0.98% / 267點); empty string when not applicable.
  - direction: up = 上漲/上升/增加, down = 下跌/下降/減少, flat = 持平或無漲跌方向.
- Convert units for Taiwan audience when needed: currency to 新台幣或美元, °F to °C, miles to 公里.
- source: data source line formatted like 資料來源：Reuters, from the material; empty string if unknown.
- visual_subject: one Traditional Chinese sentence describing a TEXT-FREE background scene for the card (place, mood, lighting; dark navy broadcast tone preferred). Describe imagery only — never mention any text, numbers or logos."""


@app.post("/api/hybrid/digest", response_model=HybridDigestResponse)
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
            response = openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": HYBRID_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f'News Source Material:\n"{req.news_text}"',
                    },
                ],
                max_tokens=1200,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "hybrid_card_digest",
                        "strict": True,
                        "schema": HYBRID_DIGEST_SCHEMA,
                    },
                },
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
            data = json.loads(raw_content)
            items = data.get("items") or []
            if len(items) > 3:
                items = items[:3]
            while len(items) < 3:
                items.append(
                    {"label": "", "value": "", "change": "", "direction": "flat"}
                )
            data["items"] = items
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


@app.post("/api/images/generate", response_model=ImageGenerateResponse)
def generate_image(req: ImageGenerateRequest):
    """Generate one news CG image without exposing provider API keys.

    IMAGE_BACKEND=openrouter（預設）時，兩家都改走 OpenRouter：
    GPT 用 OPENROUTER_GPT_MODEL、Gemini 用 OPENROUTER_GEMINI_MODEL。
    設 IMAGE_BACKEND=native 可切回原生 OpenAI / Gemini 直連。
    """
    backend = os.getenv("IMAGE_BACKEND", "openrouter")
    if backend == "openrouter" and os.getenv("OPENROUTER_API_KEY"):
        if req.provider == "gpt":
            model = os.getenv("OPENROUTER_GPT_MODEL", "openai/gpt-5.4-image-2")
        else:
            model = os.getenv("OPENROUTER_GEMINI_MODEL", "google/gemini-3-pro-image")
        return generate_via_openrouter(model, req)

    if req.provider == "gpt":
        return generate_gpt_image(req)

    return generate_gemini_image(req)


def generate_via_openrouter(model: str, req: ImageGenerateRequest) -> ImageGenerateResponse:
    """透過 OpenRouter 統一圖片端點生成，一把 OPENROUTER_API_KEY 涵蓋多家模型。"""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="尚未設定 OPENROUTER_API_KEY，無法生成圖片",
        )

    payload = {
        "model": model,
        "prompt": req.prompt,
        "aspect_ratio": req.aspect_ratio,
    }
    # 只有支援 resolution enum 的模型才帶 resolution（Gemini / Seedream / Riverflow）；
    # GPT 系列不吃 resolution，帶了會 400。
    if any(tag in model for tag in ("gemini", "seedream", "riverflow")):
        payload["resolution"] = req.image_size

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


def generate_gpt_image(req: ImageGenerateRequest) -> ImageGenerateResponse:
    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
    quality = os.getenv("OPENAI_IMAGE_QUALITY", "medium")

    try:
        result = openai_client.images.generate(
            model=model,
            prompt=req.prompt,
            size="1280x720",
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

    model = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3-pro-image")
    payload = {
        "model": model,
        "input": [{"type": "text", "text": req.prompt}],
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


def main():
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8787, reload=True)


if __name__ == "__main__":
    main()
