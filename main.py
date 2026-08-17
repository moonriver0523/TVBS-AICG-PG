import base64
import contextvars
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
from fastapi.responses import FileResponse
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
    build_prompt,
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
elif _openrouter_key:
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


DigestDensity = Literal["standard", "simplified"]


class GenerateRequest(BaseModel):
    news_text: str
    type_label: str
    role: str = "記者"
    density: DigestDensity = "standard"
    # True＝留白改由後端 safe_frame 置框，消化階段要出滿版版面而非縮小置中
    safe_frame: bool = False


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


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    provider: Literal["gemini", "gpt"] = "gemini"
    aspect_ratio: str = "16:9"
    image_size: str = "1K"
    # True＝生成後用 safe_frame 把整張圖置入 TVBS 安全框並補背景
    safe_frame: bool = False
    # 記者＝官方 Locked-Frame（底部較深）；編輯＝對位框（四邊接近均匀）
    safe_frame_profile: str = "記者"
    # 真人肖像的參考照片（data URL）。空字串＝這次不附參考圖。
    reference_image_data_url: str = ""
    # 網頁版消化後回傳的具名真人名單。後端據此查參考照並注入肖像規則。
    # LINE／generate_news_image 已在組 prompt 時處理過，不要再傳，以免規則灌兩次。
    portrait_subjects: list[str] = Field(default_factory=list)


class ImageGenerateResponse(BaseModel):
    image_data_base64: str
    mime_type: str
    model: str


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
    },
    "required": ["style", "structure", "variable", "chart_type", "portrait_subjects"],
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
2. "style": 根據新聞調性（財經、災難、溫馨、政治）選擇主色調與畫面風格（例如：深藍色科技感、紅白色警戒感），written in professional English.
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
# 座標／距離／方位角只做定位資料、永不印在畫面上，畫布幾何禁數字仍全面生效。
# 座標來自模型記憶、冷門地點可能錯（沖之鳥島案例）——沒把握就改用座標網格；
# 真正的解法是以圖生圖落地後改走 GIS 底圖路線（見 TODO.md）。
# 措辭沿用 docs/error-cases/2026-07-23-沖之鳥島-位置偏移-分析.md 的通則化版本。
MAP_ACCURACY_RULES = """

MAP ACCURACY RULES (apply ONLY when the graphic you are specifying is a 地圖／位置 map graphic; if it is not, ignore this whole block):
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
11. ONE SUBJECT PLACE IN THE HEADLINE. Decide which place the incident actually happened in, and let only that place be the subject of the 標題 line in "variable". Other countries that merely reacted, commented, protested or announced a response are secondary: put them in a 內文小標 or a callout, never in the headline as the acting subject. A headline that names a reacting country beside the incident location reads as if the incident happened there, and the renderer will place that country's callout on the incident itself. Name the reacting country inside its own callout wording so the two can never be confused.
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


def build_digest_instructions(
    role: str,
    density: DigestDensity,
    type_label: str,
    full_bleed: bool = False,
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
    instructions += DIRECTIONAL_COLOR_RULES
    # 自動判斷模式組 prompt 時還不知道 AI 會選哪一類，也要注入；
    # 區塊開頭自我限縮「非地圖類整段忽略」。明確指定非地圖類型時完全不注入。
    if type_label in (MAP_TYPE_LABEL, AUTO_TYPE_LABEL):
        instructions += MAP_ACCURACY_RULES
    if density == "simplified":
        instructions += SIMPLIFIED_DENSITY_RULES
    # 固定放最後：逐字模式必須壓過 SIMPLIFIED_DENSITY_RULES（位置＋明文 OVERRIDE 同向）
    instructions += USER_INSTRUCTION_RULES
    return instructions


# generate_news_image() 會自己記一筆含最終 prompt 的完整紀錄，它內部呼叫的
# generate() 就不該再記一次半套的。用 contextvar 而不是函式參數，免得這個純內部
# 的旗標變成 /api/generate 對外可見的欄位。
_inside_pipeline = contextvars.ContextVar("inside_pipeline", default=False)


def digest_completion(
    *,
    model: str,
    system_prompt: str,
    news_text: str,
    max_output_tokens: int,
    schema_name: str,
    schema: dict,
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
        return openai_client.chat.completions.create(
            **payload, max_tokens=max_output_tokens
        )
    except BadRequestError as exc:
        if "max_completion_tokens" not in str(exc):
            raise
        return openai_client.chat.completions.create(
            **payload, max_completion_tokens=max_output_tokens
        )


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
DIGEST_MAX_LATIN_RATIO = 0.35
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


def digest_quality_problem(data: dict, finish_reason: str) -> str:
    """檢查消化結果是否可用，通過回傳空字串，否則回傳給 log 用的問題描述。

    語法合法不等於內容可用。截斷（finish_reason=length）與字元污染都會產生
    「能解析但不能用」的結果，必須跟解析失敗一樣走重試，不能直接送去生圖。
    """
    if finish_reason == "length":
        return "輸出被截斷（finish_reason=length）"

    for field in ("style", "structure", "variable"):
        value = data.get(field) or ""
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
        full_bleed=req.safe_frame,
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
    # 地圖類（含自動判斷，因為 AI 可能選地圖）要寫雙層地圖與多組座標，字數本來就多，
    # 用一般預算幾乎必定截斷，見 MAP_DIGEST_MAX_TOKENS 的說明。
    max_output_tokens = (
        MAP_DIGEST_MAX_TOKENS
        if req.type_label in (MAP_TYPE_LABEL, AUTO_TYPE_LABEL)
        else DIGEST_MAX_TOKENS
    )
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
            time.sleep(1.5)
            continue

        # 能解析不代表能用：截斷與字元污染都要跟解析失敗一樣重試，不能送去生圖
        problem = digest_quality_problem(data, finish_reason)
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
            variable=data.get("variable", ""),
            chart_type=chart_type,
            portrait_subjects=clean_portrait_subjects(data.get("portrait_subjects")),
        )
        # 網頁版走這個端點後自己在前端組生圖 prompt，後端看不到最終 prompt，
        # 因此這裡只記到消化為止——有輸入與消化結果，事後仍可重跑重現。
        if not _inside_pipeline.get():
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
    request_id = request_log.new_request_id()
    try:
        result = generate_image_raw(req)
        verify_output_aspect_ratio(result, req.aspect_ratio)
        if req.safe_frame:
            result = frame_image_response(result, req.safe_frame_profile)
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
    if req.reference_image_data_url:
        payload["input_references"] = [
            {"type": "image_url", "image_url": {"url": req.reference_image_data_url}}
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


class NewsImageGenerateResponse(BaseModel):
    image_data_base64: str
    mime_type: str
    model: str
    title: str = ""
    prompt_version: str = PROMPT_VERSION
    # 回查用：對應 logs/generations-*.jsonl 裡的那一筆
    request_id: str = ""


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


def resolve_portrait(
    portrait_subjects: list[str], provider: str
) -> tuple[str, photo_lookup.ReferencePhoto | None]:
    """決定這次的肖像處理方式，回傳 (portrait_mode, 參考照片或 None)。

    三種結果：
    - 不是真人肖像題 → ("none", None)，沿用一般規則
    - 查到照片且後端送得出去 → ("reference", 照片)，走插畫化肖像
    - 查不到照片、後端送不出參考圖、或畫面上有兩位以上具名真人
      → ("no_reference", None)，一律不生成臉孔

    **兩人以上一律不畫臉**（2026-08-05 事故後加）：參考圖通道一次只能對應一個人，
    附一張照片卻要模型畫兩張臉時，它會把沒有照片的那格自己編出來，而且照樣掛上
    真名姓名條——掛著真名的假臉比畫得醜嚴重得多。真正的多人支援要能逐格對應
    參考圖，還沒做到之前，寧可整張退回不畫臉。

    查圖失敗（網路、逾時、查無此人）不讓整條請求失敗：新聞生產不能因為維基
    查不到人就整張圖生不出來，退回不畫臉仍是可播的結果。
    """
    if not portrait_subjects:
        return "none", None
    if len(portrait_subjects) > 1:
        print(
            f"[portrait] 畫面有 {len(portrait_subjects)} 位具名真人"
            f"（{'、'.join(portrait_subjects)}），一律不生成臉孔",
            flush=True,
        )
        return "no_reference", None
    if not supports_reference_image(provider):
        return "no_reference", None
    subject = portrait_subjects[0]
    try:
        photo = photo_lookup.find_reference_photo(subject)
    except Exception as exc:  # noqa: BLE001 — 查圖是加分項，不該拖垮生圖
        print(f"[portrait] 查參考照片失敗（{subject}）：{exc}", flush=True)
        return "no_reference", None
    if photo is None:
        return "no_reference", None
    return "reference", photo


def apply_portrait_to_image_request(req: ImageGenerateRequest) -> ImageGenerateRequest:
    """網頁版生圖路徑：依 portrait_subjects 注入規則並附上參考照。

    LINE／generate_news_image 已在 build_prompt 處理過，不會傳 portrait_subjects。
    規則字串若已在 prompt 裡，不再灌第二次。
    """
    subjects = clean_portrait_subjects(req.portrait_subjects)
    if not subjects:
        return req
    mode, photo = resolve_portrait(subjects, req.provider)
    block = PORTRAIT_MODES.get(mode, "")
    prompt = req.prompt
    if block and block not in prompt:
        prompt = f"{prompt.rstrip()}\n\n{block}"
    reference = req.reference_image_data_url
    if photo is not None and not reference:
        reference = photo.data_url()
    if prompt == req.prompt and reference == req.reference_image_data_url:
        return req
    return req.model_copy(update={"prompt": prompt, "reference_image_data_url": reference})


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
    frame_profile = (
        req.role if req.role in safe_area_spec.PROFILES else safe_area_spec.REPORTER_PROFILE
    )
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
            )
        )
        portrait_mode, reference_photo = resolve_portrait(
            digest.portrait_subjects, provider
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
                    aspect_ratio=aspect_ratio,
                    image_size=req.image_size,
                    safe_frame=req.safe_frame,
                    safe_frame_profile=frame_profile,
                    reference_image_data_url=(
                        reference_photo.data_url() if reference_photo is not None else ""
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
            portrait_photo_source=(
                reference_photo.source_page if reference_photo is not None else ""
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


@app.get("/app.js")
def serve_app_js():
    return _frontend_file("app.js", "text/javascript; charset=utf-8")


@app.get("/hybrid.html")
def serve_hybrid():
    return _frontend_file("hybrid.html", "text/html; charset=utf-8")


@app.get("/hybrid.js")
def serve_hybrid_js():
    return _frontend_file("hybrid.js", "text/javascript; charset=utf-8")


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
