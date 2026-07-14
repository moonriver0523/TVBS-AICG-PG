import json
import os
import ssl
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

openai_client = OpenAI()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    news_text: str
    type_label: str
    role: str = "記者"


class GenerateResponse(BaseModel):
    style: str
    structure: str
    variable: str


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    provider: Literal["gemini", "gpt"] = "gemini"
    aspect_ratio: str = "16:9"
    image_size: str = "2K"


class ImageGenerateResponse(BaseModel):
    image_data_base64: str
    mime_type: str
    model: str


DIGEST_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "style": {"type": "string"},
        "structure": {"type": "string"},
        "variable": {"type": "string"},
    },
    "required": ["style", "structure", "variable"],
    "additionalProperties": False,
}


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
2. "style": Choose a professional visual style appropriate for a "{type_label}", written in professional English.
3. "structure": Design the most readable, intuitive layout for a "{type_label}".
   - Propose concrete spatial arrangement and add instructions for relevant icons, technical illustrations, 3D diagrams, maps, or scene depictions that aid comprehension.
   - Written in professional English.
   - BROADCAST SAFE AREA (NON-NEGOTIABLE): the structure description MUST begin with this exact sentence: "All content — including the title, icon cards, and side panels — is inset by a fixed 15% empty margin from the top, left, and right edges; the bottom 15-18% of the frame is a completely empty, seamless extension of the background (broadcast-safe zone)." After that sentence, every element you place (headline, stat cards, indicators, icons) MUST be described with an explicit inset/gutter from its nearest edge — never described as spanning, flush, or edge-to-edge. The words "footer", "bottom edge", "anchored at bottom", "full-screen", "full-bleed", "full-width", "edge-to-edge", "flush left", "flush right", "spans the entire width", "corner-to-corner" and "bleed" are FORBIDDEN. Any closing banner or data-source line is the LOWEST ROW OF THE CONTENT AREA, sitting well above the reserved bottom margin, never at the frame bottom or against any edge."""


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
   - variable 格式範例（示意，內容依實際新聞）：
     "[標題] 聯準會三度降息\\n利率降至<4.25%>\\n[內文小標] 通膨降溫 就業穩健\\n[內文小標] 市場預期 明年再降<兩次>\\n[內文小標] 道瓊應聲<上漲350點>\\n<蓋章> 降息循環正式啟動"
2. "style": 根據新聞調性（財經、災難、溫馨、政治）選擇主色調與畫面風格（例如：深藍色科技感、紅白色警戒感），written in professional English.
3. "structure": Design the most readable anchor-wall CG layout for a "{type_label}", with concrete spatial arrangement and instructions for flat icons or 3D data charts that aid comprehension. Written in professional English.
   - BROADCAST SAFE AREA (NON-NEGOTIABLE): the structure description MUST begin with this exact sentence: "All content — including the title, icon cards, and data charts — is inset by a fixed 15% empty margin on all four sides, completely empty and seamless extensions of the background (broadcast-safe zone)." After that sentence, every element you place MUST be described with an explicit inset/gutter from its nearest edge — never described as spanning, flush, or edge-to-edge. The words "footer", "bottom edge", "anchored at bottom", "full-screen", "full-bleed", "full-width", "edge-to-edge", "flush left", "flush right", "flush top", "flush bottom", "spans the entire width", "corner-to-corner" and "bleed" are FORBIDDEN. The <蓋章> stamp banner and any data-source line are the LOWEST ROW OF THE CONTENT AREA, sitting well above the reserved bottom margin, never at the frame bottom or against any edge."""


@app.post("/api/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    template = (
        EDITOR_SYSTEM_PROMPT_TEMPLATE if req.role == "編輯" else SYSTEM_PROMPT_TEMPLATE
    )
    system_prompt = template.format(type_label=req.type_label)

    model = os.getenv("OPENAI_DIGEST_MODEL", "gpt-5.6-terra")
    try:
        response = openai_client.responses.create(
            model=model,
            instructions=system_prompt,
            input=f'News Source Material:\n"{req.news_text}"',
            max_output_tokens=1500,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "news_cg_digest",
                    "strict": True,
                    "schema": DIGEST_OUTPUT_SCHEMA,
                }
            },
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API 金鑰無效或尚未啟用 API 計費",
        ) from exc
    except RateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail="OpenAI API 用量已達限制，請稍後再試",
        ) from exc
    except APIConnectionError as exc:
        raise HTTPException(
            status_code=502,
            detail="無法連線至 OpenAI API，請稍後再試",
        ) from exc
    except APIError as exc:
        raise HTTPException(
            status_code=502,
            detail="OpenAI API 處理失敗，請確認模型權限或稍後重試",
        ) from exc

    try:
        data = json.loads(response.output_text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI 回傳格式無法解析")

    return GenerateResponse(
        style=data.get("style", ""),
        structure=data.get("structure", ""),
        variable=data.get("variable", ""),
    )


@app.post("/api/images/generate", response_model=ImageGenerateResponse)
def generate_image(req: ImageGenerateRequest):
    """Generate one news CG image without exposing provider API keys."""
    if req.provider == "gpt":
        return generate_gpt_image(req)

    return generate_gemini_image(req)


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
        raise HTTPException(
            status_code=502,
            detail="GPT 圖片生成失敗，請確認 API 額度、組織驗證或模型權限",
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
        raise HTTPException(
            status_code=502,
            detail="Gemini 圖片生成失敗，請確認金鑰、模型權限或稍後重試",
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
