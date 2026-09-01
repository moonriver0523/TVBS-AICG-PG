"""第一頁「最終 Prompt」的組裝邏輯（Python 版）。

原始實作在前端 `app.js` 的 buildPrompt()／文字規則／安全區常數；
LINE Bot 是純後端流程、沒有瀏覽器，因此在這裡有一份對應版本。

⚠️ 這裡的規則字串與 app.js 是「兩份來源」：改其中一邊必須同步另一邊，
否則 LINE 出的圖會跟網頁版不一致。日後若要收斂，正解是把規則集中到後端
並讓前端改用 API 取得。
"""

# 供外部整合（如 /api/news-image/generate 的呼叫端）追蹤這批規則的版本；
# 這裡或對應的 app.js 常數只要有實質修改，就手動遞增這個字串。
PROMPT_VERSION = "v6-2026-08-17"

# 地圖類型的標籤字面值。定義在本模組（而非 main.py）是因為匯入方向是
# main → news_prompt：build_prompt() 要用它決定是否注入地圖規則，
# main.py 的 CHART_TYPE_CHOICES 與消化端條件注入則 import 這裡的定義。
# app.js 端的 '地圖／位置' 字面值由 tests/test_prompt_parity.py 釘住一致。
MAP_TYPE_LABEL = "地圖／位置"

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


# ============================================================
# 滿版模式（safe_frame=True）：留白改由後端 safe_frame.py 用數學置框，
# 不再要求模型自己留邊。
#
# 為什麼要有這個模式：四輪實驗（像素／百分比／純文字／參考圖與遮罩）證實模型
# 量不出比例，底部安全區 0 次合格；但「把畫面畫滿」它做得非常好。因此把要求
# 從「精準留 10/7.3/7.6/20.4%」（做不到）換成「別把自己的內容切掉」（很容易），
# 精準度交給程式。詳見 docs/error-cases/。
# ============================================================

CANVAS_MARGIN_LINE = "- Scale the whole design down so it fills only the central region, surrounded by a thick empty margin on every side (deeper at the bottom); when unsure, make the margin bigger, never smaller"

CANVAS_FULL_BLEED_LINE = "- Use the whole frame: the design fills the canvas completely, with only a slim even breathing space inside the frame edge so that no element is clipped"

FULL_BLEED_RULES = """==================================================
FULL-FRAME RULES (CRITICAL — MUST PRESERVE)
==================================================
- Use the entire canvas. The design fills the frame; there is no reserved margin, no empty band, and no letterboxing anywhere.
- Leave only a slim, even breathing space just inside the frame edge, enough that no letter, icon, card border, or chart element is cut off by the edge. Do not turn that breathing space into a thick border.
- Keep the breathing space roughly even on all four sides. Do NOT make the bottom deeper than the other sides.
- These full-frame rules OVERRIDE any conflicting instruction in STYLE, STRUCTURE, or VARIABLE FIELDS. If a layout instruction asks you to scale the design down, centre it in a smaller region, or reserve an empty margin or band, ignore that instruction and use the whole frame instead.
- The background is ONE single continuous image covering the whole canvas. Do NOT render any frame, rectangle, outline, border line, guide line, crop mark, corner bracket, or dimmed / tinted / shaded band anywhere.
- Every element must be fully inside the canvas: nothing may run off the edge or be sliced by it.
- SELF-CHECK before finalizing: if any element is clipped by the frame edge, nudge it inward; if a wide empty band has appeared along any edge, enlarge the design to fill it."""


# 只給編輯：對位框比 16:9 寬，差額由後端水平拉伸補（safe_frame.STRETCH_PROFILES）。
# 拉伸幅度會扣掉模型自己留的純背景，所以請模型上下各留一條背景帶就能少失真。
#
# ⚠️ 這是**取代** FULL_BLEED_RULES，不是附加。2026-08-17 兩種都實測過：
# 附加版（FULL_BLEED_RULES + 呼吸邊）只留 0–8px，因為 FULL_BLEED_RULES 開頭就寫
# 「there is no reserved margin, no empty band」還聲明自己 OVERRIDE 衝突指令，
# 模型聽前面那條。取代版留 21–23px，殘餘失真降到 0.75–1.24%。
#
# 「約一個標題字高」是刻意用具體視覺參照而非百分比——四輪實驗證實模型量不出
# 比例（見 safe_area_spec 的說明），但看得懂「跟標題的字一樣高」。
EDITOR_FULL_BLEED_RULES = """==================================================
EDGE-SAFE FULL-FRAME RULES (CRITICAL — MUST PRESERVE)
==================================================
- The background artwork is ONE single continuous image running right to all four edges of the canvas. Do NOT render any frame, rectangle, outline, border line, guide line, crop mark, corner bracket, dimmed / tinted / shaded band, or letterbox anywhere.
- Across the very TOP of the canvas and across the very BOTTOM of the canvas, leave a clear horizontal strip where ONLY the background artwork appears. Each strip is about as tall as one character of the main headline. No headline, card, chart, icon, banner, arrow, source line or border may enter either strip.
- The closing banner must sit fully above the bottom strip, with an obvious run of plain background visible beneath it all the way to the bottom edge.
- Left and right: keep a similar clear gap of background between the outermost element and the side edge.
- Do NOT shrink the design into a small central box and do NOT draw a visible border. These strips are plain continuous background, not a frame.
- These rules OVERRIDE any conflicting instruction in STYLE, STRUCTURE, or VARIABLE FIELDS. If a layout instruction asks you to run the design edge to edge, ignore that instruction and keep the strips clear.
- Nothing may touch, run off, or be sliced by any edge.
- SELF-CHECK before finalizing: look at the topmost and bottommost pixels of the design. If any element reaches into the top or bottom strip, move the whole design inward until both strips are clear."""


# ============================================================
# 視覺忠實度區塊（2026-07-31）。與 app.js 逐字同步（tests/test_prompt_parity.py）。
# 插在 margin_rules 與 FINAL OUTPUT RULE 之間——放在該標頭之後會汙染
# test_content_fidelity 的雙源逐字比對。
# ============================================================

REAL_WORLD_RENDERING_RULES = """==================================================
REAL-WORLD ACCURACY (CRITICAL)
==================================================
- Real, verifiable places and objects (skylines, specific buildings, highways and interchanges, airports, facilities, and specific models of aircraft, ship, vehicle or equipment) must look like the real thing: correct shape, layout, proportions and distinguishing features as far as they are known. Faithful, realistic rendering is welcome — do not distort reality for style.
- Do not fabricate identifying detail you do not know and present it as real. If the rendering is a generic stand-in or a reconstruction rather than the real thing, the 示意圖 label supplied in VARIABLE FIELDS must be clearly visible — never drop or hide it.
- NO UNSOURCED BRANDS: every sign, storefront, banner, package, product body, vehicle livery, screen, badge and building facade must be blank or carry a generic non-readable mark. Do NOT draw any real company logo, wordmark, trademark, ticker symbol, exchange name or brand text — not even a small, faint, distant or background one. A brand name may appear only if that exact text is supplied in VARIABLE FIELDS, and then only as plain typeset text, never as a reproduced logotype.
- NAMED REAL PEOPLE: how to depict a named real person is governed by the NAMED REAL PERSON block below whenever one is present — follow that block, not your own judgement. If no such block is present, do NOT draw a recognisable face for a named real person: use a back view or a plain silhouette and keep the 示意圖 label visible. Never show the person in a scene, action or context that STRUCTURE does not describe.
- SELF-CHECK before finalizing: look at every surface in the image for text or marks you added yourself. If any sign, screen, package or vehicle carries readable branding, blank it."""

TW_DIRECTIONAL_COLOR_RULES = """==================================================
DIRECTIONAL COLOUR CONVENTION (TAIWAN)
==================================================
- Rise, gain, increase, positive = RED. Fall, loss, decrease, negative = GREEN. This is the Taiwanese market convention and it is the opposite of the Western one. Never render a rise in green or a fall in red.
- Apply the same pairing to every arrow, triangle, bar, line, highlight block and emphasised figure in the graphic, including when one graphic shows a riser and a faller side by side.
- An up arrow means up and a down arrow means down: match every arrow to the direction stated in VARIABLE FIELDS.
- Do not use red and green decoratively for unrelated purposes in a graphic that shows a rise or a fall."""

# 真人肖像的處理方式不交給模型判斷：後端查得到參考照片就走插畫化肖像，
# 查不到就退回不生成臉孔。兩種情況各有一個區塊，由 build_prompt 依
# portrait_mode 注入；兩者都沒注入時，REAL_WORLD_RENDERING_RULES 的預設
# 條款仍然擋著（不畫臉），所以漏傳參數不會變成「放行寫實肖像」。
#
# 措辭沿用 2026-08-01 實驗的 v1：加強版（v2，明列筆觸／禁照片特徵）實測筆觸
# 過度刻意、顯得造作，v1 已足以讓觀眾辨識為插畫，使用者拍板採 v1。
#
# ⚠️ 這三個常數**刻意不同步到 app.js**，是本檔頂端「兩份來源」規則的明列例外。
# 網頁版自己組 prompt 直打 /api/images/generate，沒有消化端填的 portrait_subjects、
# 也沒有後端的參考照查圖，同步過去只會得到一個永遠注入不了的區塊。網頁版因此
# 停在 REAL_WORLD_RENDERING_RULES 的預設（不畫臉），那也是尚未裁決前的安全值。
# 記載於 TODO.md「真實人物圖須參考真實樣貌」一節，前例同 2026-07-31 的
# resolve_aspect_ratio（同樣只動後端、沒動網頁版）。
PORTRAIT_WITH_REFERENCE_RULES = """==================================================
NAMED REAL PERSON — PORTRAIT TREATMENT (CRITICAL)
==================================================
- A reference photograph of the named real person is attached to this request. Base the portrait on that photograph.
- Render the portrait as a hand-painted editorial portrait illustration rather than a photograph, while preserving the recognisable likeness of the reference photograph: the same facial structure, hairstyle, glasses and build, so that viewers identify the same individual.
- The illustration must be readable as an illustration. Do not aim for a photographic reproduction of the reference image.
- Take only the person's likeness from the reference photograph. Pose, attire, framing and surroundings follow STRUCTURE, not the photograph's own background or occasion.
- The 示意圖 label supplied in VARIABLE FIELDS sits beside the portrait and must stay clearly visible: this is an illustrated depiction, not a photograph of the person.
- Never place the person in a scene, action or context that STRUCTURE does not describe."""

PORTRAIT_NO_REFERENCE_RULES = """==================================================
NAMED REAL PEOPLE — NO REFERENCE AVAILABLE (CRITICAL)
==================================================
- No reference photograph is available, so you MUST NOT draw the face of ANY named real person in this graphic. This applies to every such figure, including when the layout calls for two or more portraits side by side.
- Depict each figure as a back view or a plain silhouette wearing the attire STRUCTURE describes. Never invent, guess or approximate anyone's facial features, and never substitute a generic face in their place — a fabricated face sitting under a real person's name label is the single most serious failure this rule exists to prevent.
- Name labels may stay, but each must sit beside a faceless figure, never beside an invented face.
- The 示意圖 label supplied in VARIABLE FIELDS must stay clearly visible.
- Never place a person in a scene, action or context that STRUCTURE does not describe."""

# 2-3 位具名真人、且**每一位都查到參考照**時用這段（2026-08-18 使用者裁定放寬）。
#
# 與 USER_REFERENCE_PORTRAIT_RULES 措辭相近但刻意分成兩段常數，差別是這段
# **保留「示意圖」標籤**：那條「不標示意圖」的 override 語意是「照著使用者親自提供
# 的素材生成」，套到後端自動查來的維基照片上並不成立——寫實照片感＋真名＋沒有
# 示意圖標籤是最糟的組合。
#
# 「全有或全無」由後端保證（見 main.resolve_portraits）：只要有一人沒照片，整張
# 退回 PORTRAIT_NO_REFERENCE_RULES。這裡刻意**不寫**「沒附照片的人畫剪影」那種
# 逐人區分的條款——2026-08-18 實測 2/2 證明生圖模型辦不到，寫了只會給人一種
# 有防護的錯覺（證據見 docs/error-cases/2026-08-18-多人肖像放寬到3人-實驗-分析.md）。
PORTRAIT_MULTI_WITH_REFERENCE_RULES = """==================================================
NAMED REAL PEOPLE — MULTIPLE PORTRAITS (CRITICAL)
==================================================
- A reference photograph is attached for EVERY named real person whose face this graphic shows. Base each portrait on its own attached photograph.
- Match each face to the correct person: use the resemblance between the attached photographs and the name labels, and NEVER swap likenesses between people. A face sitting under the wrong person's name is the single most serious failure this rule exists to prevent.
- Render each portrait as a hand-painted editorial portrait illustration rather than a photograph, while preserving the recognisable likeness of its reference photograph: the same facial structure, hairstyle, glasses and build, so that viewers identify the same individual.
- Take only each person's likeness from the photographs. Pose, attire, framing and surroundings follow STRUCTURE, not the photographs' own backgrounds or occasions.
- An attached photograph may happen to show more than one person. Use only the person the name label refers to; never carry a bystander from a photograph into the graphic.
- Other real people may be named in the text of this graphic without a photograph. That is intended: render their names as text only, never as a face, and never place such a name beside a depicted figure.
- The 示意圖 label supplied in VARIABLE FIELDS must stay clearly visible: these are illustrated depictions, not photographs of the people.
- Never place a person in a scene, action or context that STRUCTURE does not describe."""

PORTRAIT_MODES = {
    "reference": PORTRAIT_WITH_REFERENCE_RULES,
    "reference_multi": PORTRAIT_MULTI_WITH_REFERENCE_RULES,
    "no_reference": PORTRAIT_NO_REFERENCE_RULES,
    "none": "",
}

# ============================================================
# 使用者上傳參考圖的用途區塊（2026-08-17，PLAN.md ②）。
#
# ⚠️ 這些常數**刻意不同步到 app.js**，理由與 PORTRAIT_* 相同（本檔頂端
# 「兩份來源」規則的明列例外）：上傳的圖一定經過後端 /api/images/generate
# 才送得進 input_references，由後端在同一處依 purpose 注入區塊，規則就只有
# 一份來源；同步到前端只會多一份要對齊的拷貝。
#
# 措辭要點：附圖不是要重現的成品，是「依據」。地圖類與 MAP_ACCURACY_IMAGE_RULES
# 同向（地理正確壓過構圖），不衝突——附圖只是把「正確」的來源從模型記憶換成附圖。
# ============================================================

USER_REFERENCE_MAP_RULES = """==================================================
ATTACHED MAP REFERENCE (CRITICAL)
==================================================
- One of the attached images is a map supplied by the user. Treat it as the geographic ground truth for this graphic.
- The relative positions, coastlines, routes and boundaries shown in that attached map override your own geographic memory. Do not move, rotate, mirror, compress or "improve" any of them.
- Re-draw the geography in the graphic's own visual style; do not paste or photographically reproduce the attached map itself.
- Labels and callout text still come ONLY from VARIABLE FIELDS, never from text visible inside the attached map."""

USER_REFERENCE_SCENE_RULES = """==================================================
ATTACHED SCENE REFERENCE (CRITICAL)
==================================================
- One of the attached images is a real-scene photograph supplied by the user. The appearance of the scene, buildings, vehicles or equipment in the graphic must follow that attached image: same shape, layout, proportions and distinguishing features.
- Re-draw it in the graphic's own visual style; do not paste or photographically reproduce the attached image itself.
- Do not copy any readable text, logo or brand mark visible inside the attached image; the NO UNSOURCED BRANDS rule above still applies in full.
- Do not copy any recognisable human face from the attached image; how to depict named real people is governed solely by the NAMED REAL PERSON rules."""

# 使用者上傳肖像照（2026-08-17 使用者裁決開放）。
# 標題刻意含「NAMED REAL PERSON」：REAL_WORLD_RENDERING_RULES 的預設條款寫著
# 「有 NAMED REAL PERSON 區塊時聽它的」，這段就是那個區塊的使用者上傳版。
# 「兩位以上具名真人不畫臉」鐵律在**使用者親自上傳照片**時解除——鐵律的成因是
# 參考圖通道一次只能對應一人（2026-08-05 事故），多圖支援＋使用者明示提供照片
# 後成因不存在；但**沒有附照片的那位仍然不畫臉**，鐵律只對有照片的人解除。
USER_REFERENCE_PORTRAIT_RULES = """==================================================
NAMED REAL PERSON — USER-SUPPLIED PORTRAIT REFERENCE (CRITICAL)
==================================================
- The user has attached portrait photograph(s) of the named real person(s) in this graphic. Base each portrait on its attached photograph.
- Render each portrait as a hand-painted editorial portrait illustration rather than a photograph, while preserving the recognisable likeness of its reference photograph: the same facial structure, hairstyle, glasses and build, so that viewers identify the same individual.
- When the layout shows more than one named person, match each face to the correct person: use the resemblance between the attached photographs and the name labels, and never swap likenesses between people.
- Draw a recognisable face ONLY for a person whose photograph is attached. Any named real person WITHOUT an attached photograph must still be shown as a back view or a plain silhouette — never invent or approximate a face for them.
- Take only each person's likeness from the photographs. Pose, attire, framing and surroundings follow STRUCTURE, not the photographs' own backgrounds or occasions.
- Never place a person in a scene, action or context that STRUCTURE does not describe."""

USER_REFERENCE_ASIS_RULES = """==================================================
ATTACHED IMAGE — PLACE AS-IS, DO NOT REDRAW (CRITICAL)
==================================================
- One of the attached images must be placed into the graphic exactly as supplied: unchanged pixels, colours, proportions and content. Do NOT re-draw, re-style, repaint, colour-grade, stylise or reinterpret it in the graphic's own illustration style.
- Do not crop, stretch, rotate, mirror or otherwise distort the attached image; if it must be resized to fit the layout, scale it uniformly (preserve aspect ratio) only.
- This attached image is exempt from the "re-draw in the graphic's own visual style" instruction that applies to other attached reference images; place it as its own distinct element in the composition (e.g. an inset panel or designated area), not blended or repainted into the surrounding artwork.
- Any brand marks, logos, readable text or real human faces already present in this attached image may remain exactly as supplied — the NO UNSOURCED BRANDS rule and the face-rendering rules above govern what you generate elsewhere in the graphic, not this attached image's own untouched content."""

USER_REFERENCE_MODES = {
    "map": USER_REFERENCE_MAP_RULES,
    "scene": USER_REFERENCE_SCENE_RULES,
    "portrait": USER_REFERENCE_PORTRAIT_RULES,
    "asis": USER_REFERENCE_ASIS_RULES,
}

# 消化階段（build_digest_instructions）專用，與上面 USER_REFERENCE_ASIS_RULES
# 是兩個不同階段：消化端寫 STRUCTURE 時完全不知道使用者附了 asis 圖，隨手寫成
# 「插畫式描繪」是常態機率事件，寫出來的措辭又比生圖端後注入的 ASIS 規則更具體、
# 更晚不了——生圖模型會照著 STRUCTURE 的具體描述憑空畫，等於蓋掉 ASIS 規則
# （2026-08-23 記者/編輯版各出過一次「附圖被忽略、模型自己畫一張替代圖」）。
# 這段是消化端專屬的措辭護欄，只在使用者有上傳 asis 圖時注入。
USER_REFERENCE_ASIS_DIGEST_RULES = """

ATTACHED IMAGE TO BE PLACED AS-IS (STRUCTURE MUST MATCH THIS):
The user has attached at least one image that a later stage will place into the graphic exactly as supplied, completely unaltered. Wherever "structure" describes the visual area that will hold this image, describe it ONLY as the user's original supplied photograph placed unaltered.
NEVER use wording such as "depiction", "illustration", "portrait-style", "artistic rendering", "reinterpreted", or any phrase that asks for that area to be redrawn or reimagined — that wording gets carried into the image-generation step and causes it to fabricate a replacement image instead of using the real supplied photograph.
Do not invent an alternative scene, outfit, setting or pose for this image area; simply reserve its position, size and framing in the layout."""

# 使用者有上傳參考圖時一律注入（2026-08-17 使用者裁決）：既然是照著使用者
# 提供的實景實物生成，就不再標「示意圖」。REAL_WORLD_RENDERING_RULES 寫著
# 標籤 never drop or hide，所以這裡必須位置在後＋明文 OVERRIDE（repo 慣例
# 「位置＋明文 OVERRIDE 雙重表達」）才壓得過去；其餘條款（禁品牌、肖像對應、
# 地理正確）全部原樣生效。
USER_REFERENCE_NO_DISCLAIMER_RULES = """==================================================
USER REFERENCE SUPPLIED — NO 示意圖 LABEL (OVERRIDE)
==================================================
- The user has supplied reference image(s) for this graphic, so the depiction is based on real supplied material rather than a generic stand-in.
- Do NOT render any 示意圖 label anywhere in the image. If the text 示意圖 appears in VARIABLE FIELDS, omit that text and render everything else exactly as supplied.
- This rule OVERRIDES every earlier instruction that asks for a 示意圖 label to be present or kept visible, including the REAL-WORLD ACCURACY and NAMED REAL PERSON blocks.
- Every other rule in those blocks still binds in full: the brand bans, likeness and face rules, and geographic accuracy are unchanged."""


# ============================================================
# 追加指令改圖（2026-08-17，PLAN.md ③）。
#
# ⚠️ 同上，**刻意不同步到 app.js**：refine 一律走後端 /api/images/refine，
# prompt 只在這裡組，前端沒有任何一條路徑需要自己組 refine prompt。
#
# 附圖是「上次的成品（置框前原圖）」，措辭核心是：只改指令指定的部分，
# 其餘逐像素保持。FINAL OUTPUT RULE 的括號禁令與繁中要求仍要帶著，
# 免得修改輪把原本守住的規則丟掉。
# ============================================================

IMAGE_REFINE_RULES = """==================================================
IMAGE REFINE RULES (CRITICAL)
==================================================
- The attached image is YOUR OWN previous output for this news graphic. It is the base image.
- Apply ONLY the change requested in USER CHANGE REQUEST below. Everything else — layout, composition, colours, typography, spelling, every other element — must remain exactly as in the attached image.
- Do not redesign, re-balance, restyle or "improve" anything that the request did not mention.
- Keep the exact same aspect ratio and framing as the attached image. Do not crop, letterbox, zoom or shift the composition.
- Use only Traditional Chinese (Taiwan standard) for any text you add or change, with correct stroke forms.
- The final image must NOT contain any "[" "]" or "<" ">" characters.
- Never add new facts, figures, sources, logos or captions that the request did not supply."""


def build_refine_prompt(instruction: str) -> str:
    """組追加修改（refine）的生圖 prompt。附圖＝上次置框前原圖，經 input_references 送出。"""
    return (
        "Modify the attached news infographic image according to the change "
        "request below. This is an edit of an existing image, not a new design.\n\n"
        f"{IMAGE_REFINE_RULES}\n\n"
        "==================================================\n"
        "USER CHANGE REQUEST\n"
        "==================================================\n"
        f"{instruction}"
    )

MAP_ACCURACY_IMAGE_RULES = """==================================================
MAP ACCURACY RULES (CRITICAL)
==================================================
- Geographic accuracy overrides visual balance. Do not relocate, compress, distort, rotate or rearrange any coastline, island, border, city or marker to improve the composition.
- North is up, east is right, west is left, south is at the bottom. Include a north arrow and a scale bar.
- Coordinates, degree values and bearings given in STRUCTURE are positioning instructions: put the markers at those positions. You are not asked to print them as labels; place-name text and supplied callout wording are the labels that matter.
- Distances stated in STRUCTURE must be drawn proportionally to the map scale and along the stated bearing.
- Simplify coastline styling only. Never simplify or alter geographic positions, distances, bearings or relative scale.
- Do not invent islands, coastlines, landmasses or maritime boundaries. If an accurate coastline cannot be maintained, draw a clean ocean coordinate grid with accurate point markers rather than fabricated geography.
- Claimed or disputed zones must read as schematic and carry only the label supplied in VARIABLE FIELDS, never as a settled international border."""


def build_prompt(
    *,
    role: str,
    engine: str,
    type_label: str,
    style: str,
    structure: str,
    variable: str,
    safe_frame: bool = False,
    aspect_ratio: str = "16:9",
    portrait_mode: str = "none",
) -> str:
    """對應 app.js 的 buildPrompt()。role: 記者／編輯，engine: gemini／gpt。

    safe_frame=True 時輸出滿版指示（留白由後端 safe_frame.py 置框處理）。
    """
    text_rules = EDITOR_TEXT_RULES if role == "編輯" else REPORTER_TEXT_RULES
    # 分流的依據是「後端會不會水平拉伸」，不是安全框開關本身：
    #   編輯 OFF → 拉伸填滿對位框，要上下背景帶把拉伸失真吃掉
    #   編輯 ON  → 2% 薄框走 FIT 不拉伸，再留背景帶會讓實際邊界遠超過 2%
    #   記者 ON  → 21:9 FIT，同理不留帶
    # 編輯版自 2026-08-19 起兩檔都是滿版生成，沒有「叫模型自己縮小置中」那條路。
    if role == "編輯" and not safe_frame:
        margin_rules = EDITOR_FULL_BLEED_RULES
        canvas_line = CANVAS_FULL_BLEED_LINE
    elif role == "編輯" or safe_frame:
        margin_rules = FULL_BLEED_RULES
        canvas_line = CANVAS_FULL_BLEED_LINE
    else:
        margin_rules = REPORTER_SAFE_AREA
        canvas_line = CANVAS_MARGIN_LINE

    # 視覺忠實度區塊：地圖規則只在已解析的類型是地圖時注入
    # （這裡的 type_label 已是 digest 解析後的具體類型，非「自動判斷」sentinel）
    extra_blocks = [REAL_WORLD_RENDERING_RULES, TW_DIRECTIONAL_COLOR_RULES]
    if type_label == MAP_TYPE_LABEL:
        extra_blocks.append(MAP_ACCURACY_IMAGE_RULES)
    # 真人肖像區塊：未知的 portrait_mode 一律當成沒有區塊，讓預設的
    # 「不畫臉」條款接手，而不是靜靜放行。
    portrait_block = PORTRAIT_MODES.get(portrait_mode, "")
    if portrait_block:
        extra_blocks.append(portrait_block)
    extras = "\n\n".join(extra_blocks)

    body = f"""==================================================
CANVAS
==================================================
- Aspect ratio: {aspect_ratio}
- Centred composition, single continuous full-frame background
{canvas_line}

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

{margin_rules}

{extras}

==================================================
FINAL OUTPUT RULE
==================================================
- The final generated image must NOT contain any "[" "]" or "<" ">" characters.
- All bracketed variable fields are instructions only.
- Use only Traditional Chinese (Taiwan standard).
- Ensure all characters are correct with proper stroke forms.
- CONTENT FIDELITY (NON-NEGOTIABLE): render ONLY the words, figures and facts supplied in VARIABLE FIELDS. You are a renderer, not an author.
  -> NEVER invent additional numbers, percentages, dates, quarters, years, axis values, data points, or trend series that are not written in VARIABLE FIELDS.
  -> If a chart or graph is called for but no series of values was supplied, draw it as a plain schematic shape (a simple rising or falling line, an arrow, a bar silhouette) with NO numeric labels and NO axis tick values.
  -> NEVER add a data-source line, organisation name, agency, publisher, wire service, logo, watermark, URL, timestamp, or "updated on" note unless that exact text appears in VARIABLE FIELDS.
  -> NEVER add extra captions, bullet points, sub-headings, or explanatory sentences of your own.
  -> Empty space is correct and acceptable. If the layout looks sparse, enlarge or space out the supplied elements — do NOT fill the gap with invented content."""

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
