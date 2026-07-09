import json

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

client = anthropic.Anthropic()

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


class GenerateResponse(BaseModel):
    style: str
    structure: str
    variable: str


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
   - Written in professional English."""


@app.post("/api/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(type_label=req.type_label)

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1500,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f'News Source Material:\n"{req.news_text}"'}
        ],
    )

    raw = "\n".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    clean = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI 回傳格式無法解析")

    return GenerateResponse(
        style=data.get("style", ""),
        structure=data.get("structure", ""),
        variable=data.get("variable", ""),
    )


def main():
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8787, reload=True)


if __name__ == "__main__":
    main()
