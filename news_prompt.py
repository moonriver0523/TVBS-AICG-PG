"""第一頁「最終 Prompt」的組裝邏輯（Python 版）。

原始實作在前端 `app.js` 的 buildPrompt()／文字規則／安全區常數；
LINE Bot 是純後端流程、沒有瀏覽器，因此在這裡有一份對應版本。

⚠️ 這裡的規則字串與 app.js 是「兩份來源」：改其中一邊必須同步另一邊，
否則 LINE 出的圖會跟網頁版不一致。日後若要收斂，正解是把規則集中到後端
並讓前端改用 API 取得。
"""

SYSTEM_DISCLAIMER = '"< >" "[ ]" 是給你的指令 不要生成在結果上'

REPORTER_TEXT_RULES = """==================================================
Text Rules
==================================================
Main Title:
- Positioned at the very top of the frame
- Rendered in bold 3D extruded typography with strong depth and lighting

Body Text:
- Clean and highly legible
- Do NOT use any commas or periods
- Use spaces only to separate phrases

Subtitles ([內文小標]):
- If the text length is fewer than 6 full-width characters (中文字), use a "Tag" (Label) visual representation (e.g., pill-shaped background, high-contrast block).

Text Styling Rules:
- Any text written as [text] or <text>:
  -> Remove brackets or symbols
  -> Apply highlight color such as yellow gold or cyan
  -> Optional glow effect for emphasis
- Any <蓋章> marker:
  -> Apply strong full-box highlight style to the following text
  -> Use solid background color (e.g. red background with white text)"""

EDITOR_TEXT_RULES = """==================================================
Text Rules
==================================================
Main Title:
- Positioned at the very top of the frame
- Must be split into exactly two lines
- Font size is 2x larger than body text
- Rendered in bold 3D extruded typography with strong depth and lighting

Body Text:
- Clean and highly legible
- Do NOT use any commas or periods
- Use spaces only to separate phrases

Subtitles ([內文小標]):
- If the text length is fewer than 6 full-width characters (中文字), use a "Tag" (Label) visual representation.

Text Styling Rules:
- Any text written as [text] or <text>:
  -> Remove brackets or symbols
  -> Apply highlight color such as yellow gold or cyan
  -> Optional glow effect for emphasis
- Any <蓋章> marker:
  -> Apply strong full-box highlight style to the following text
  -> Use solid background color (e.g. red background with white text)

Visual Elements:
- Include high-quality flat icons or 3D data charts relevant to the content
- Background: professional broadcast news style, subtle glow / tech lines, strictly NO plain gradients"""

REPORTER_SAFE_AREA = """==================================================
EMPTY MARGIN RULES (CRITICAL — MUST PRESERVE)
==================================================
- These are layout guides only. The final image is ONE single continuous background with the subject centred; the margins are visually identical to the centre — same colour, tone and brightness everywhere. Do NOT render any frame, rectangle, outline, border line, guide line, crop mark, corner bracket, or dimmed / tinted / shaded band to mark the empty area. The empty margin must be completely invisible.
- SCALE THE WHOLE LAYOUT INWARD: treat the entire infographic as one group and shrink it so it is clearly smaller than the frame, leaving a thick empty border of plain background on all sides (deeper at the bottom). The content group must NOT fill the frame. When in doubt, make the margin bigger, never smaller.
- These empty-margin rules OVERRIDE any conflicting instruction in STYLE, STRUCTURE, or VARIABLE FIELDS. If a layout instruction places content in a reserved margin, ignore that placement and keep the margin empty.
- All core text, logos, icons, and charts must stay inside the central area, leaving a wide, even empty margin on the top, left, and right sides; that margin must be COMPLETELY EMPTY on all three sides — not a thin border, not a partial inset.
- The top margin must contain: NO title text, NO headline, NO icons, NO logos, NO decorative elements.
- The left margin must contain: NO stat cards, NO numerical modules, NO icons, NO borders, NO text.
- The right margin must contain: NO indicators, NO boxes, NO icons, NO leader lines, NO text.
- The bottom margin, kept noticeably deeper than the side margins, must contain:
  - NO text
  - NO logos
  - NO icons
  - NO charts
  - NO divider lines
  - NO decorative elements
  - NO data-source line
- This bottom strip simply stays empty so on-air lower-third graphics never cover any content.
- The background color or background image from the active content area above MUST extend seamlessly into all four reserved margins — no change in color, texture, brightness, or visual tone; no hard edges, no visual breaks, no overlays, no gradients.
- FORBIDDEN terms/effects in the final composition: full-width, edge-to-edge, flush left, flush right, flush top, spans the entire width, corner-to-corner, bleed, touching the frame boundary.
- SELF-CHECK before finalizing: if any text block, card, icon, or box touches or comes close to any frame edge, you MUST redesign the layout to add visible gutter space before output."""

EDITOR_SAFE_AREA = """==================================================
EMPTY MARGIN RULES (CRITICAL — MUST PRESERVE)
==================================================
- These are layout guides only. The final image is ONE single continuous background with the subject centred; the margins are visually identical to the centre — same colour, tone and brightness everywhere. Do NOT render any frame, rectangle, outline, border line, guide line, crop mark, corner bracket, or dimmed / tinted / shaded band to mark the empty area. The empty margin must be completely invisible.
- SCALE THE WHOLE LAYOUT INWARD: treat the entire infographic as one group and shrink it so it is clearly smaller than the frame, leaving a thick empty border of plain background on all sides (deeper at the bottom). The content group must NOT fill the frame. When in doubt, make the margin bigger, never smaller.
- These empty-margin rules OVERRIDE any conflicting instruction in STYLE, STRUCTURE, or VARIABLE FIELDS. If a layout instruction places content in a reserved margin, ignore that placement and keep the margin empty.
- All core text, logos, icons, and charts must stay inside the central area, leaving a wide, even empty margin on all four sides (with the bottom margin kept a little deeper), and every one of those four margins must be COMPLETELY EMPTY — not a thin border, not a partial inset.
- Every reserved margin (top, bottom, left, right) must contain:
  - NO text
  - NO logos
  - NO icons
  - NO charts
  - NO divider lines
  - NO decorative elements
  - NO data-source line
  - NO <蓋章> stamp banner
- The background color or background image MUST extend seamlessly into all reserved margins — no change in color, texture, brightness, or visual tone; no hard edges, no visual breaks, no overlays, no gradients.
- FORBIDDEN terms/effects in the final composition: full-width, edge-to-edge, flush left, flush right, flush top, flush bottom, spans the entire width, corner-to-corner, bleed, touching the frame boundary.
- SELF-CHECK before finalizing: if any text block, card, icon, or box touches or comes close to any frame edge, you MUST redesign the layout to add visible gutter space before output."""


def build_prompt(
    *,
    role: str,
    engine: str,
    type_label: str,
    style: str,
    structure: str,
    variable: str,
) -> str:
    """對應 app.js 的 buildPrompt()。role: 記者／編輯，engine: gemini／gpt。"""
    text_rules = EDITOR_TEXT_RULES if role == "編輯" else REPORTER_TEXT_RULES
    safe_area = EDITOR_SAFE_AREA if role == "編輯" else REPORTER_SAFE_AREA

    body = f"""==================================================
CANVAS
==================================================
- Aspect ratio: 16:9
- Centred composition, single continuous full-frame background
- Scale the whole design down so it fills only the central region, surrounded by a thick empty margin on every side (deeper at the bottom); when unsure, make the margin bigger, never smaller

{text_rules}

==================================================
STYLE (VISUAL LANGUAGE ONLY)
==================================================
{style}

==================================================
STRUCTURE (LAYOUT RULES)
==================================================
{structure}

==================================================
VARIABLE FIELDS (USER INPUT)
==================================================
{variable}

{safe_area}

==================================================
FINAL OUTPUT RULE
==================================================
- The final generated image must NOT contain any "[" "]" or "<" ">" characters.
- All bracketed variable fields are instructions only.
- Use only Traditional Chinese (Taiwan standard).
- Ensure all characters are correct with proper stroke forms."""

    if engine == "gpt":
        return (
            f"Generate an image: a professional international TV news infographic "
            f"({type_label}) for broadcast and digital editorial use. Follow the "
            f"specification below exactly. Do not redesign or reinterpret the layout "
            f"logic. Current Operating Context: {role} Workflow.\n\n{body}"
        )

    return (
        f"Create a professional international TV news infographic ({type_label}) "
        f"designed for broadcast and digital editorial use.\n"
        f"The output must strictly follow the style, structure, and data logic "
        f"defined below.\n"
        f"Do not redesign, reinterpret, or alter the layout logic.\n"
        f"Current Operating Context: {role} Workflow.\n\n{body}"
    )


def compose_variable(variable: str) -> str:
    """對應 app.js：變量區前面固定加上「括號是指令」的免責句。"""
    return f"{SYSTEM_DISCLAIMER}\n{variable}" if variable else "[No Variables Defined]"
