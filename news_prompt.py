"""第一頁「最終 Prompt」的組裝邏輯（Python 版）。

原始實作在前端 `app.js` 的 buildPrompt()／文字規則／安全區常數；
LINE Bot 是純後端流程、沒有瀏覽器，因此在這裡有一份對應版本。

⚠️ 這裡的規則字串與 app.js 是「兩份來源」：改其中一邊必須同步另一邊，
否則 LINE 出的圖會跟網頁版不一致。日後若要收斂，正解是把規則集中到後端
並讓前端改用 API 取得。
"""

# 供外部整合（如 /api/news-image/generate 的呼叫端）追蹤這批規則的版本；
# 這裡或對應的 app.js 常數只要有實質修改，就手動遞增這個字串。
PROMPT_VERSION = "v7-2026-09-16"

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
- Any <底帶> marker:
  -> Remove the marker and set the text as an ordinary information bar, NOT a coloured stamp
  -> Place it as a single bar along the very bottom of the design, spanning the full width

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

# 品牌那一條抽成共用常數：追加修改（refine）也要帶著同一條，措辭必須逐字相同，
# 否則兩條線對「什麼算品牌」的定義會慢慢分岔。REAL_WORLD_RENDERING_RULES 由它拼回去
# （test_prompt_parity 會對 app.js 逐字比對，改這裡一定要同步 app.js）。
#
# 2026-09-07 使用者裁決：**新聞素材提到的品牌就畫出真實 LOGO**，取代 2026-08-xx 的
# 「只能純文字、不得重現 logotype」。理由是新聞本來就在講那個品牌，把它的招牌塗白
# 反而是失真。**沒提到的品牌仍然一律去識別化**——那半段是多輪實驗磨出來的，措辭
# 原文強度保留，不要放寬：模型只要覺得「畫個 logo 比較像真的」就會替沒提到的店家
# 捏一個牌子出來。
SOURCE_BRANDS_RULE = "- BRANDS: ONLY THOSE IN THE SOURCE. A brand that VARIABLE FIELDS or STRUCTURE names may be shown with its real logo, wordmark or brand text, rendered as faithfully to the real mark as your knowledge allows, and plain typeset text is equally acceptable. Place it ONLY on the objects that belong to that brand — its own signage, packaging, product body, vehicle livery, screen or jersey — and never put one brand's mark on another brand's object. Every OTHER sign, storefront, banner, package, product body, vehicle livery, screen, badge and building facade must be blank or carry a generic non-readable mark: do NOT draw any real company logo, wordmark, trademark, ticker symbol, exchange name or brand text for a brand the source material does not name — not even a small, faint, distant or background one, and never invent one."

REAL_WORLD_RENDERING_RULES = """==================================================
REAL-WORLD ACCURACY (CRITICAL)
==================================================
- Real, verifiable places and objects (skylines, specific buildings, highways and interchanges, airports, facilities, and specific models of aircraft, ship, vehicle or equipment) must look like the real thing: correct shape, layout, proportions and distinguishing features as far as they are known. Faithful, realistic rendering is welcome — do not distort reality for style.
- Do not fabricate identifying detail you do not know and present it as real. If the rendering is a generic stand-in or a reconstruction rather than the real thing, the 示意圖 label supplied in VARIABLE FIELDS must be clearly visible — never drop or hide it.
""" + SOURCE_BRANDS_RULE + """
- NAMED REAL PEOPLE: how to depict a named real person is governed by the NAMED REAL PERSON block below whenever one is present — follow that block, not your own judgement. If no such block is present, do NOT draw a recognisable face for a named real person: use a back view or a plain silhouette and keep the 示意圖 label visible. Never show the person in a scene, action or context that STRUCTURE does not describe.
- A STATED QUANTITY IS A NUMBER, NOT A HEADCOUNT TO DRAW. Where you do draw the individual items, the count on the canvas must equal the stated figure exactly, background and secondary items included — a graphic saying 4車追撞 with five vehicles in it is wrong. Only draw them individually while the figure is small enough to take in at a glance, up to about four. Beyond that do not attempt the instances at all: 12箱走私菸 is one representative crate with the figure 12 set beside it, never a heap the viewer would count as twenty, and 10部機組 is a figure rather than a row you would miscount.
- SELF-CHECK before finalizing: look at every surface in the image for text or marks you added yourself. If any sign, screen, package or vehicle carries readable branding for a brand the source material does not name, blank it."""

TW_DIRECTIONAL_COLOR_RULES = """==================================================
DIRECTIONAL COLOUR CONVENTION (TAIWAN)
==================================================
- Rise, gain, increase, positive = RED. Fall, loss, decrease, negative = GREEN. This is the Taiwanese market convention and it is the opposite of the Western one. Never render a rise in green or a fall in red.
- Apply the same pairing to every arrow, triangle, bar, line, highlight block and emphasised figure in the graphic, including when one graphic shows a riser and a faller side by side.
- An up arrow means up and a down arrow means down: match every arrow to the direction stated in VARIABLE FIELDS.
- Do not use red and green decoratively for unrelated purposes in a graphic that shows a rise or a fall."""

# 真人肖像的處理方式不交給模型判斷：後端查得到參考照片就走肖像規則，查不到
# 再分「有維基條目」「連條目都沒有」兩種（F40，2026-09-16 四層分流）。四種情況
# 各有一個區塊，由 build_prompt 依 portrait_mode 注入；都沒注入時，
# REAL_WORLD_RENDERING_RULES 的預設條款仍然擋著（不畫臉），所以漏傳參數不會
# 變成「放行寫實肖像」。
#
# 措辭沿用 2026-08-01 實驗的 v1，2026-09-16（B66）改寫成「寫實為主、帶一點點
# 插畫筆觸感」——使用者實拍發現 v1「插畫化」措辭畫出來其實是寫實照片感，
# 裁定與其再加強插畫化措辭把畫面拉醜，不如承認寫實化就是想要的結果，
# 把條文改成與行為一致，並靠加強「AI示意圖」標示合規。
#
# ⚠️ 這幾個常數**刻意不同步到 app.js**，是本檔頂端「兩份來源」規則的明列例外。
# 網頁版自己組 prompt 直打 /api/images/generate，沒有消化端填的 portrait_subjects、
# 也沒有後端的參考照查圖，同步過去只會得到一個永遠注入不了的區塊。網頁版因此
# 停在 REAL_WORLD_RENDERING_RULES 的預設（不畫臉），那也是尚未裁決前的安全值。
# 記載於 TODO.md「真實人物圖須參考真實樣貌」一節，前例同 2026-07-31 的
# resolve_aspect_ratio（同樣只動後端、沒動網頁版）。
PORTRAIT_WITH_REFERENCE_RULES = """==================================================
NAMED REAL PERSON — PORTRAIT TREATMENT (CRITICAL)
==================================================
- A reference photograph of the named real person is attached to this request. Base the portrait on that photograph.
- Render the portrait as a realistic editorial news portrait: the primary impression is a faithful likeness of the reference photograph — the same facial structure, hairstyle, glasses and build, so that viewers recognise the same individual at a glance. Keep only a light illustrative touch on top of that realism, such as a subtle painterly texture or brushwork in the finish.
- Do not aim for a flat photographic reproduction of the reference image, and do not push the treatment into an overtly hand-drawn or cartoon style either — realism must dominate, the illustrative touch stays understated.
- Take only the person's likeness from the reference photograph. Pose, attire, framing and surroundings follow STRUCTURE, not the photograph's own background or occasion.
- The 示意圖 label supplied in VARIABLE FIELDS sits beside the portrait and must stay clearly visible: this is a depiction, not an actual photograph of the person. If VARIABLE FIELDS supplies no such label, do not add one yourself.
- Never place the person in a scene, action or context that STRUCTURE does not describe."""

PORTRAIT_NO_REFERENCE_RULES = """==================================================
NAMED REAL PEOPLE — NO PERSON IN THIS SCENE (CRITICAL)
==================================================
- No named real person in this graphic can be safely depicted, so the scene must be designed WITHOUT that person as a figure at all. This applies to every such person, including when the source material would suggest two or more of them side by side.
- Do not draw ANY human figure to stand in for them — not facing the camera, not turned away, not a plain shape wearing their attire, not a faceless placeholder body. A drawn figure of any kind sitting where a real person's name is mentioned is the exact failure this rule exists to prevent.
- Redesign the scene around buildings, venues, logos, signage, objects, documents, charts, maps or other non-person elements that the source material supports. Their name may still appear as plain text (a caption, a label, a quote panel) if VARIABLE FIELDS supplies it, but no figure of any kind represents them visually.
- The 示意圖 label supplied in VARIABLE FIELDS must stay clearly visible when the scene is a generic stand-in rather than a real, verifiable place or object. If VARIABLE FIELDS supplies no such label, do not add one yourself.
- Never place a person in a scene, action or context that STRUCTURE does not describe."""

# F40 第 3 層（2026-09-16 使用者裁決）：維基查得到這個人的條目、但條目沒有合格
# 首圖時，允許模型依新聞語境自畫，不強制退回無人場景。⚠使用者明確裁定「不要
# 在圖上標『長相為 AI 推測』」——那句免責文字改成不畫進圖裡，由後端在 API
# response 另外回一則 notice 給前端訊息欄（main.ENTRY_ONLY_PORTRAIT_NOTICE）。
# 這裡的措辭因此只管「怎麼畫」，不提免責聲明；示意圖標籤仍照一般規則保留。
PORTRAIT_ENTRY_ONLY_RULES = """==================================================
NAMED REAL PERSON — NO VERIFIED PHOTOGRAPH, DRAW FROM CONTEXT (CRITICAL)
==================================================
- No reference photograph is attached for this named real person, but the news context (their role, nationality, age, setting and any description the source material gives) is enough to depict them as a specific identifiable individual rather than a generic figure.
- Draw a plausible likeness consistent with that context. Do not claim or imply pinpoint accuracy of their actual face — this is a contextual depiction, not a verified portrait.
- Render it in the same realistic-editorial-with-a-light-illustrative-touch treatment as a reference-photo portrait: realism dominates, any illustrative texture stays understated.
- The 示意圖 label supplied in VARIABLE FIELDS must stay clearly visible. If VARIABLE FIELDS supplies no such label, do not add one yourself.
- Never place the person in a scene, action or context that STRUCTURE does not describe."""

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
- Render each portrait as a realistic editorial news portrait: the primary impression is a faithful likeness of its reference photograph — the same facial structure, hairstyle, glasses and build, so that viewers recognise the same individual at a glance. Keep only a light illustrative touch on top of that realism, such as a subtle painterly texture or brushwork in the finish; do not push any portrait into an overtly hand-drawn or cartoon style.
- Take only each person's likeness from the photographs. Pose, attire, framing and surroundings follow STRUCTURE, not the photographs' own backgrounds or occasions.
- An attached photograph may happen to show more than one person. Use only the person the name label refers to; never carry a bystander from a photograph into the graphic.
- Other real people may be named in the text of this graphic without a photograph. That is intended: render their names as text only, never as a face, and never place such a name beside a depicted figure.
- The 示意圖 label supplied in VARIABLE FIELDS must stay clearly visible: these are illustrated depictions, not photographs of the people. If VARIABLE FIELDS supplies no such label, do not add one yourself.
- Never place a person in a scene, action or context that STRUCTURE does not describe."""

PORTRAIT_MODES = {
    "reference": PORTRAIT_WITH_REFERENCE_RULES,
    "reference_multi": PORTRAIT_MULTI_WITH_REFERENCE_RULES,
    "entry_only": PORTRAIT_ENTRY_ONLY_RULES,
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
- Labels and callout text still come ONLY from VARIABLE FIELDS, never from text visible inside the attached map.
- IF THE ATTACHED MAP CARRIES ROUND MARKER DOTS, those dots are already at the true real-world positions of the places this story is about. Keep every marker at its dot: do not move it, do not re-space the markers to balance the composition, do not add a marker where there is no dot, and do not drop one. Restyle the dot into the graphic's own pin design and attach the place name beside it — the dot's position is the one thing you may not change.
- THE PIN AND THE DOT MUST RESOLVE TO ONE POINT. A teardrop pin points at a location with its TIP, so put the tip exactly on the dot's centre — do not centre the pin's round head on the dot, and do not float the pin above it. Never leave the original dot behind as a separate ring, ripple, halo or glow sitting under a pin that hovers somewhere else: that reads as two different positions for one place, and the lower one is the true one.
- THE NAME PRINTED BESIDE A DOT IS THAT DOT'S IDENTITY. Each dot on the attached map carries its place name printed next to it by the program. That pairing is verified and it is not yours to rearrange: the pin you draw on a dot takes the name printed beside THAT dot, and any callout, icon or figure about that place attaches to that pin and no other. Never assign the names by reading them off the map in the order they appear in STRUCTURE or in VARIABLE FIELDS, and never swap two names because the composition reads better. This is the one exception to the rule above that text inside the attached map is never used: those printed dot names exist precisely to tell you which dot is which, and you match them against the place names in VARIABLE FIELDS (which supply the on-screen wording).
- A PLACE WITH NO DOT FOR IT GETS NO MARKER OF ANY KIND. STRUCTURE may name a place the attached map carries no dot for. That means the program could not verify where it is — not that you should supply the position from memory. Where there is no dot for it, put nothing on the map for it: no pin, and no marker, icon, arrow, triangle, leader line, highlighted segment, ring or shaded patch either. Naming one shape does not make the others allowed — whatever shape you reach for, if it points at a spot on the basemap it is banned, because the position is what you are inventing, not the pin. NEITHER END OF A LEADER LINE MAY LAND ON THE MAP EITHER: a line running from a text box out onto the basemap picks a spot just as surely as a pin does, whether or not anything is drawn where it stops. Leader lines may connect a text box to an illustration, never to the basemap. Name that place instead in a text line or in a callout that touches no part of the map. A marker you placed yourself sits among verified ones and looks exactly as authoritative, so one guess discredits every marker on the graphic.
- Any coordinates written in STRUCTURE are secondary to the attached map. Where the two disagree, the attached map wins; never nudge a marker to match a coordinate."""

USER_REFERENCE_SCENE_RULES = """==================================================
ATTACHED SCENE REFERENCE (CRITICAL)
==================================================
- One of the attached images is a real-scene photograph supplied by the user. The appearance of the scene, buildings, vehicles or equipment in the graphic must follow that attached image: same shape, layout, proportions and distinguishing features.
- Re-draw it in the graphic's own visual style; do not paste or photographically reproduce the attached image itself.
- Do not copy readable text or brand marks visible inside the attached image, except a brand the source material names — that one may be reproduced on its own objects; the BRANDS rule above still applies in full.
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
- Render each portrait as a realistic editorial news portrait: the primary impression is a faithful likeness of its attached photograph — the same facial structure, hairstyle, glasses and build, so that viewers recognise the same individual at a glance. Keep only a light illustrative touch on top of that realism, such as a subtle painterly texture or brushwork in the finish; do not push any portrait into an overtly hand-drawn or cartoon style.
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
- Any brand marks, logos, readable text or real human faces already present in this attached image may remain exactly as supplied — the BRANDS rule and the face-rendering rules above govern what you generate elsewhere in the graphic, not this attached image's own untouched content.
- If an attached image already contains on-air chrome (a date stamp, LIVE or 24H LIVE badge, channel logo, or a 示意圖 / AI示意圖 label), do not draw another copy of those marks."""

# AI改圖（2026-09-13 使用者裁決）：介於 asis 與 scene 之間的第三種用途。
# * asis  ＝原圖原封不動貼進去，完全不經過生圖模型
# * scene ＝只拿來參考外觀，成品畫的是 STRUCTURE 描述的另一個畫面
# * aiedit＝**這張圖就是成品那塊畫面**，但由模型照版型風格重畫一次
# 措辭核心因此是「同一個畫面重畫一次」，而不是「參考它去畫別的」——沒有這句，
# 模型會把它當成 scene，畫出一個構圖完全不同、只有器材外觀像的畫面。
USER_REFERENCE_AIEDIT_RULES = """==================================================
ATTACHED IMAGE — REDRAW THIS SAME PICTURE (CRITICAL)
==================================================
- One of the attached images is the picture this graphic's main visual is to BE. Re-draw that same picture in the graphic's own visual style: the same subject, the same framing, the same camera angle, the same arrangement of what is near and far.
- This is NOT a loose style reference. Someone who saw the attached image must recognise your output as the same moment redrawn, not as a different picture of a similar topic. Except where an editor's instruction below asks for a change, do not substitute another scene, another angle, another action or another setting for it.
- Do redraw it: repaint, restyle and colour-grade it into this graphic's illustration style, and extend or crop the edges as the layout needs. Apart from whatever an editor's instruction below asks you to change, the treatment changes and the content does not.
- PRESERVE-EXISTING: Text already present in the attached reference image is requested content — keep it as supplied. Preserve every readable word, number and existing brand mark already present in the image; do not erase it, rewrite it, replace it with fake text, garbled text or altered branding.
- DO-NOT-INVENT OR REUSE: Do not add any text or brand that is not already present in the attached reference image or explicitly requested elsewhere in this prompt. Do not move, copy or reuse text or brand marks from the attached reference image onto a different object.
- EXPLICIT-REMOVAL ONLY: Remove existing text or brand marks only when the editor's instruction explicitly asks for that specific text or mark to be removed; otherwise preserve them.
- People in the attached image stay who they are: reproduce every face in it as it appears, recognisable, in the redrawn style. The NAMED REAL PERSON rules below govern only people who are NOT in the attached image — they do not restrict, blur, hide or replace a face that the editor supplied here.
- If an attached image already contains on-air chrome (a date stamp, LIVE or 24H LIVE badge, channel logo, or a 示意圖 / AI示意圖 label), do not draw another copy of those marks."""

# 同一格放 2 張以上 AI改圖（2026-09-14 使用者：「使用者就是希望單槽多圖 AI 融合啊」）。
# 上面單張版開頭是「One of the attached images is the picture…」——多張一起送時這句
# 等於授權模型挑一張畫，實拍（測試 session 第四輪 A2）4 張參考只剩 1 張。融合版
# 把張數寫死、要求每一張都認得出來，其餘（重畫、商標、人臉）與單張版同一套。
# 只在 aiedit 張數 ≥2 時取代單張版注入（apply_user_references_to_image_request）。
USER_REFERENCE_AIEDIT_FUSION_RULES_TEMPLATE = """==================================================
ATTACHED IMAGES — FUSE ALL {count} OF THEM INTO ONE PICTURE (CRITICAL)
==================================================
- {count} attached images together ARE the picture this graphic's main visual is to BE. Compose them into ONE coherent scene redrawn in the graphic's own visual style. Every one of the {count} images must be recognisably present in the output — its subject, its key objects and its people — none may be dropped, merged away or reduced to a vague background hint. Someone who saw all {count} images must be able to point to each of them inside your output.
- Give each image its own clear share of the frame — side by side, foreground and background, or a natural blend — keeping each image's subject, framing and camera angle recognisable. Do not pick one image and discard the rest; a picture that shows only some of the {count} images is wrong.
- Do redraw them: repaint, restyle and colour-grade them into this graphic's illustration style, and extend or crop the edges as the layout needs. Apart from whatever an editor's instruction below asks you to change, the treatment changes and the content does not.
- PRESERVE-EXISTING: Text already present in any attached reference image is requested content for that image — keep it as supplied. Preserve every readable word, number and existing brand mark already present in each image; do not erase it, rewrite it, replace it with fake text, garbled text or altered branding.
- DO-NOT-INVENT OR REUSE: Do not add any text or brand that is not already present in an attached reference image or explicitly requested elsewhere in this prompt. In a fusion, do not move, copy or reuse text or brand marks from one attached image onto an object from another attached image.
- EXPLICIT-REMOVAL ONLY: Remove existing text or brand marks only when the editor's instruction explicitly asks for that specific text or mark to be removed; otherwise preserve them.
- People in the attached images stay who they are: reproduce every face in every attached image as it appears, recognisable, in the redrawn style. The NAMED REAL PERSON rules below govern only people who are NOT in the attached images — they do not restrict, blur, hide or replace a face that the editor supplied here.
- If an attached image already contains on-air chrome (a date stamp, LIVE or 24H LIVE badge, channel logo, or a 示意圖 / AI示意圖 label), do not draw another copy of those marks."""

# 同一請求 ≥2 張原圖放置（2026-09-14 B26＋D9）：單張版開頭「One of the attached images」
# 等於授權模型挑一張放。多張版把張數寫死、依上傳順序由左到右，並避開編號陷阱——
# `_native_reference_files` 會把肖像／地圖底圖排在使用者上傳之前，「attached image 1」
# 不是使用者的第一張。只在 asis 張數 ≥2 時取代單張版注入。
USER_REFERENCE_ASIS_MULTI_RULES_TEMPLATE = """==================================================
ATTACHED IMAGES — PLACE ALL {count} AS-IS, DO NOT REDRAW (CRITICAL)
==================================================
- The user supplied {count} images that must each be placed into the graphic exactly as supplied: unchanged pixels, colours, proportions and content. Do NOT re-draw, re-style, repaint, colour-grade, stylise or reinterpret them in the graphic's own illustration style. Every one of the {count} images must be recognisably present — none may be dropped, merged away or reduced to a vague background hint.
- Place them in the user's upload order: the first user-supplied as-is image occupies the leftmost / first reading position; subsequent images follow in that same order; the last occupies the rightmost / last reading position. Do not reorder or swap them.
- These {count} images are the USER-SUPPLIED uploads. Auto-attached portrait photographs or map basemaps may precede them in the whole request's file list — do NOT number them by the whole request's attached-file index ("attached image 1" is not necessarily the user's first upload).
- Do not crop, stretch, rotate, mirror or otherwise distort the attached images; if they must be resized to fit the layout, scale them uniformly (preserve aspect ratio) only.
- These attached images are exempt from the "re-draw in the graphic's own visual style" instruction that applies to other attached reference images; place each as its own distinct element in the composition (e.g. an inset panel or designated area), not blended or repainted into the surrounding artwork.
- Any brand marks, logos, readable text or real human faces already present in the attached images may remain exactly as supplied — the BRANDS rule and the face-rendering rules above govern what you generate elsewhere in the graphic, not these attached images' own untouched content.
- If an attached image already contains on-air chrome (a date stamp, LIVE or 24H LIVE badge, channel logo, or a 示意圖 / AI示意圖 label), do not draw another copy of those marks."""

# YT 雙格生圖（2026-09-14 D4）：左右身分寫進 prompt。編號陷阱同上——只數使用者上傳。
USER_REFERENCE_YT_SLOT_PLACEMENT_TEMPLATE = """==================================================
USER-SUPPLIED SLOT PLACEMENT (CRITICAL)
==================================================
- These instructions refer to the USER-SUPPLIED uploads only. Auto-attached portrait photographs or map basemaps may precede them in the whole request's file list — do NOT number them by the whole request's attached-file index ("attached image 1" is not necessarily the user's first upload).
- The first {left_count} user-supplied image(s) belong to the LEFT half (first title / first story). Place them on the LEFT.
- The next {right_count} user-supplied image(s) belong to the RIGHT half (second title / second story). Place them on the RIGHT.
- Do not swap the two sides."""

# 使用者在指令欄寫的需求（2026-09-13 使用者裁決：「AI改圖 如果使用者在給 AI 指令欄
# 寫需求 會吃到嗎? 應該要吃到」，權限＝**可以改內容**）。
#
# 為什麼要獨立一段、而不是沿用既有的那條路：指令欄本來只送給推導「畫面描述」的
# 文字模型，推出來的句子最後變成生圖 prompt 裡的一行 `The photograph: ...`。
# 2026-09-13 實拍證明那條路在 AI改圖 下會被蓋掉——推導出的描述寫「工人正在架設
# 遮陽棚」，成品卻是照片原本那群站在已搭好棚下的遊客，一個工人都沒有。上面的
# REDRAW 區塊贏了畫面描述，指令欄走同一條路自然也贏不了。
#
# 這一段的權限：凌駕上面「內容不變」那句（該句已同步改寫，不是疊 override），
# 但**不**凌駕同區塊的商標、人臉與 NAMED REAL PERSON 規則。
# 措辭沿用 resolve_cover_visuals 的框法，明講它是「要改畫面哪裡」而不是要畫的字
# ——不講的話「改成夜晚」會被模型當成字幕畫上去。
USER_REFERENCE_AIEDIT_INSTRUCTION_TEMPLATE = """

THE EDITOR'S INSTRUCTION FOR THIS REDRAW (OUTRANKS "the content does not change"):
The editor has asked for the following change to the attached picture(s). It is a direction about what to change in the picture, never words to render — do not write any of it, or any translation of it, anywhere in the image. Carry it out, and leave everything it does not mention exactly as it is in the attached image. It does not relax the brand-mark, human-face or NAMED REAL PERSON rules above; satisfy the rest of the instruction within those.
{instruction}"""

USER_REFERENCE_MODES = {
    "map": USER_REFERENCE_MAP_RULES,
    "scene": USER_REFERENCE_SCENE_RULES,
    "portrait": USER_REFERENCE_PORTRAIT_RULES,
    "asis": USER_REFERENCE_ASIS_RULES,
    "aiedit": USER_REFERENCE_AIEDIT_RULES,
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
- Every other rule in those blocks still binds in full: the brand rules, likeness and face rules, and geographic accuracy are unchanged."""


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


# 無文字底圖的追加修改（YT 直播封面）：附圖是一張純照片底圖，文字全由程式疊。
# IMAGE_REFINE_RULES 是替「帶文字的 CG」寫的（保留標題、不動版面文字），照用會讓
# 模型以為該有文字而自己補一段上去，程式疊的標題蓋不掉它。
TEXT_FREE_REFINE_RULES = """==================================================
TEXT-FREE BACKGROUND REFINE RULES (CRITICAL)
==================================================
- The attached image is a text-free photographic background. Software adds every headline, badge and logo afterwards.
- Apply ONLY the change requested below. Keep everything else — subject, composition, framing, lighting, colour — as it is.
- The result must remain completely free of text: no letters, no numbers, no captions, no logos, no watermarks, no signage, no readable writing of any kind. If the request asks to add words, leave the background unchanged in that respect — words are added by software, not by you.
- Keep the lower third free of essential detail and keep the extreme corners clear, so the overlaid headline and badges do not cover anything important."""


# 追加修改也要守品牌與具名真人（2026-09-07）。
#
# 為什麼要補：refine 是一次獨立的生圖呼叫，模型只看得到這支 prompt。原本這裡只寫
# 「不要新增事實與 logo」，沒有主流程那兩條硬規則——一句「把背景弄熱鬧一點」就足以
# 讓它在店面招牌上補真實品牌，或替一張本來是背影的具名真人補一張憑空捏的臉。後者
# 正是這個專案定義最糟的組合（真名＋假臉）。
#
# 品牌條款逐字沿用 SOURCE_BRANDS_RULE，不另寫一套。具名真人這條刻意寫成精簡版：
# 主流程那幾段（PORTRAIT_*_RULES）都以 STRUCTURE／VARIABLE FIELDS 為前提，refine 沒有
# 那兩個區塊，照搬會叫模型去對照不存在的欄位。
REFINE_REAL_WORLD_RULES = (
    SOURCE_BRANDS_RULE
    + "\n- NAMED REAL PEOPLE: no reference photograph is attached to this edit, so you MUST NOT draw or complete the face of any named real person that is not already a face in the attached image. Faces already present stay exactly as they are — do not restyle, replace, age, beautify or re-render them. Where the attached image shows a figure as a back view or a silhouette, it stays a back view or a silhouette."
)


REFINE_REPLACEMENT_COMMON_RULES = """==================================================
NAMED FACE REPLACEMENT SCOPE (CRITICAL)
==================================================
- The named replacement target is: {person}.
- Replace ONLY the face of that one target person. The replacement scope is exactly that one face.
- Keep every other person's face exactly as it is. Do not restyle, replace, age, beautify, complete or re-render any other face.
- Preserve the existing composition, framing, layout, colours, lighting, typography, every existing word, every logo and badge, and every other image element exactly as they are.
- Do not add, remove or move any person, object, text or logo. Do not change the target's body, pose, clothing or position except for the target face itself."""

REFINE_REPLACEMENT_USER_PHOTO_RULES = (
    SOURCE_BRANDS_RULE
    + "\n"
    + REFINE_REPLACEMENT_COMMON_RULES
    + "\n- A qualifying portrait photograph supplied by the user for the target is attached. Use that photograph as the target face reference; do not invent a different identity."
)

REFINE_REPLACEMENT_WIKIPEDIA_PHOTO_RULES = (
    SOURCE_BRANDS_RULE
    + "\n"
    + REFINE_REPLACEMENT_COMMON_RULES
    + "\n- A qualifying Wikipedia portrait photograph of the target is attached. Use that photograph as the target face reference; do not invent a different identity."
)

REFINE_REPLACEMENT_ENTRY_ONLY_RULES = (
    SOURCE_BRANDS_RULE
    + "\n"
    + REFINE_REPLACEMENT_COMMON_RULES
    + "\n- A Wikipedia entry exists for the target, but no qualifying portrait photograph is attached. You may draw a plausible face for the target from the news context, but do not claim or imply that the result is a verified or pinpoint-accurate likeness."
)

# 「查無維基條目」刻意**沒有**對應的 rules 常數：那一種結果在 `refine_image()` 就直接
# 回 400 擋掉，根本走不到組 prompt 這一步。寫一條規則請模型「不要捏臉」是錯的防線——
# 0916 王結玲那次換出第三張誰都不是的臉，正是因為把這件事交給模型自律（見 MASTER B63）。
# 唯一可靠的擋法是程式端不把它送出去。


def build_refine_prompt(
    instruction: str,
    *,
    text_free: bool = False,
    replacement_person: str = "",
    replacement_mode: str = "",
) -> str:
    """組追加修改（refine）的生圖 prompt。附圖＝上次置框前原圖，經 input_references 送出。

    text_free：附圖是無文字底圖（YT 直播封面那條線），改用 TEXT_FREE_REFINE_RULES。
    兩條線都帶 REFINE_REAL_WORLD_RULES（禁品牌＋具名真人），理由見該常數。
    """
    if replacement_person and replacement_mode:
        replacement_rules = {
            "user_uploaded": REFINE_REPLACEMENT_USER_PHOTO_RULES,
            "wikipedia_photo": REFINE_REPLACEMENT_WIKIPEDIA_PHOTO_RULES,
            "entry_only": REFINE_REPLACEMENT_ENTRY_ONLY_RULES,
        }.get(replacement_mode)
        if replacement_rules is None:
            raise ValueError(f"unknown replacement mode: {replacement_mode}")
        base_rules = replacement_rules.format(person=replacement_person)
    else:
        base_rules = REFINE_REAL_WORLD_RULES
    if text_free:
        return (
            "Modify the attached text-free background photograph according to the change "
            "request below. This is an edit of an existing image, not a new design.\n\n"
            f"{TEXT_FREE_REFINE_RULES}\n"
            f"{base_rules}\n\n"
            "==================================================\n"
            "USER CHANGE REQUEST\n"
            "==================================================\n"
            f"{instruction}"
        )
    return (
        "Modify the attached news infographic image according to the change "
        "request below. This is an edit of an existing image, not a new design.\n\n"
        f"{IMAGE_REFINE_RULES}\n"
        f"{base_rules}\n\n"
        "==================================================\n"
        "USER CHANGE REQUEST\n"
        "==================================================\n"
        f"{instruction}"
    )

# 每一段文字只畫一次。2026-09-05 第六輪連抓到兩種重複：同一個文字框在右上與
# 右下各畫一次；蓋章那句被多畫成一列內文小標，蓋章條再出現一次同句（variable
# 裡根本沒有那一行）。兩種都是圖面端自己複製的，消化端的規則管不到，所以要有
# 一塊給兩個角色、所有類型都注入的文字擺放規則。
TEXT_PLACEMENT_RULES = """==================================================
TEXT PLACEMENT (CRITICAL)
==================================================
- EVERY LINE OF VARIABLE FIELDS IS RENDERED EXACTLY ONCE. One line, one place on the canvas. Do not repeat a headline, a subhead or a callout in a second card, a second column, a corner block or a summary strip, and do not restate it in different words elsewhere. An empty region is not a reason to duplicate: leave it to the background rather than fill it with a copy.
- THE <蓋章> LINE BELONGS TO THE STAMP BAR AND NOWHERE ELSE — never also as a body line, a subhead row, a card or a callout. It is the closing conclusion, so seeing it twice on one graphic reads as two separate statements of the same fact.
- Add no text of your own. Every word on the canvas comes from VARIABLE FIELDS; if a layout region has nothing assigned to it, it carries no text."""


MAP_ACCURACY_IMAGE_RULES = """==================================================
MAP ACCURACY RULES (CRITICAL)
==================================================
- Geographic accuracy overrides visual balance. Do not relocate, compress, distort, rotate or rearrange any coastline, island, border, city or marker to improve the composition.
- North is up, east is right, west is left, south is at the bottom. Include a north arrow and a scale bar.
- Coordinates, degree values and bearings given in STRUCTURE are positioning instructions: put the markers at those positions. You are not asked to print them as labels; place-name text and supplied callout wording are the labels that matter.
- Distances stated in STRUCTURE must be drawn proportionally to the map scale and along the stated bearing.
- Simplify coastline styling only. Never simplify or alter geographic positions, distances, bearings or relative scale.
- Do not invent islands, coastlines, landmasses or maritime boundaries. If an accurate coastline cannot be maintained, draw a clean ocean coordinate grid with accurate point markers rather than fabricated geography.
- EVERY MARKER CARRIES ITS OWN PLACE NAME, AND EVERY CALLOUT GOES TO THE MARKER THAT NAMES THE SAME PLACE. Set the place name beside its own marker, close enough that no reader has to guess which marker it belongs to. When a callout box names a place, its leader line must end at the marker for that place and no other; never let two leader lines cross each other on their way to markers whose names they do not match. A marker drawn in exactly the right spot still misreports the story if the box wired to it describes what happened somewhere else, and with no name on the marker itself the viewer has no way to catch it.
- A FACT THAT NAMES NO PLACE BELONGS TO NONE OF THEM. Only wording that itself names a place may go into that place's marker label or callout. When a VARIABLE line does not itself name a place — 「最深積水40公分 多輛機車熄火」 sitting on its own line — do not attach it to one marker and do not spread it across several: deciding which of the marked places is the deepest, or which had the stalled scooters, is a claim the source never made, and on a map it reads as reported fact. Put such a line where it belongs to the whole graphic: a shared strip, a summary block, or a caption that points at nothing.
- Claimed or disputed zones must read as schematic and carry only the label supplied in VARIABLE FIELDS, never as a settled international border."""


# 無字檔（2026-09-14 D14／F20）的生圖端覆蓋，釘在整份 prompt 最後面。
#
# 光靠消化端產出空的 variable 不夠：這份 prompt 從 TEXT RULES 一路到 FINAL OUTPUT
# RULE 都在講「怎麼把 VARIABLE FIELDS 的字畫上去」，而空欄位會被 compose_variable
# 換成 "[No Variables Defined]"——留著不管，模型有機會把那串字面畫進畫面，或者
# 自己補一個標題來滿足前面那些條款。位置在後＋明文 OVERRIDE 才壓得住，這是本 repo
# 的既有慣例（同 editor_formats.YT_COVER_TEXT_FREE_OVERRIDE 的做法）。
NO_TEXT_IMAGE_OVERRIDE = """
==================================================
NO TEXT AT ALL (OVERRIDES EVERY EARLIER RULE ABOUT RENDERING WORDS)
==================================================
- The user asked for a picture with no writing on it. Render NO text of any kind: no headline, no label, no caption, no legend, no axis value, no date, no place name, no source line, no badge, no logo, no watermark, no signature — not a single letter or digit anywhere in the frame.
- VARIABLE FIELDS is empty on purpose. Every earlier instruction about rendering the words, figures or markers supplied there does not apply, and any placeholder standing in for those fields is not something to draw.
- Everything else still binds in full: the reserved margin, likeness and scene fidelity, the use of any attached references, and the ban on inventing content.
- The empty area where a headline would have gone is the correct result. Do not fill it with words."""


# 全路徑最終生圖鐵律（B61／B62，2026-09-16）。ownership 只在後端：
# generate_image_raw() 在 provider dispatch 正前方冪等注入一次。
# 不要同步到 app.js／hybrid.js——新版型漏帶這段必須是紅燈，不是再複製一份。
#
# 冪等判斷只用下面這個 marker，不准拿條文裡某一句去 substring 比對。
FINAL_IMAGE_BASELINE_MARKER = "=== FINAL IMAGE POLICY BASELINE ==="

FINAL_IMAGE_BASELINE = f"""==================================================
{FINAL_IMAGE_BASELINE_MARKER}
==================================================
This block is mandatory on every image this system generates. Portrait-mode blocks elsewhere in this prompt (NAMED REAL PERSON and related) still govern how an explicitly requested person is depicted; this block only forbids adding people, faces, marks or words that the rest of the prompt did not ask for. When an explicit portrait-mode fallback is present, follow that fallback.

- NAMED PEOPLE: do not introduce a named real person who is not already named in this prompt.
- FACES: do not invent an identifiable face for anyone who was not explicitly requested and who has no qualified reference image attached. If this prompt names a person and attaches a qualified reference, depict that person as the portrait-mode block directs.
- TEXT / LOGOS / BRANDS: do not draw text, logos, wordmarks, trademarks or brand marks that this prompt did not request. If this prompt explicitly asks you to render specific words, titles, logos or brands (including an AI-title / TEXT TO RENDER block), draw those as requested and do not add extra readable lettering, logos or brands beyond that request.
- PORTRAIT FALLBACK: back views, silhouettes, no-person scenes, illustrated likenesses and similar fallbacks are governed only by the explicit portrait-mode rules in this prompt. If none are present, do not add a named real person of your own."""


def ensure_final_image_baseline(prompt: str) -> str:
    """若 prompt 尚無鐵律 marker 就附加一次；已有則原樣回傳。"""
    if FINAL_IMAGE_BASELINE_MARKER in (prompt or ""):
        return prompt
    stripped = (prompt or "").rstrip()
    if not stripped:
        return FINAL_IMAGE_BASELINE
    return f"{stripped}\n\n{FINAL_IMAGE_BASELINE}"


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
    no_text: bool = False,
) -> str:
    """對應 app.js 的 buildPrompt()。role: 記者／編輯，engine: gemini／gpt。

    safe_frame=True 時輸出滿版指示（留白由後端 safe_frame.py 置框處理）。
    no_text=True 時在最後追加 NO_TEXT_IMAGE_OVERRIDE（消化程度＝無字）。
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
    extra_blocks = [
        REAL_WORLD_RENDERING_RULES,
        TW_DIRECTIONAL_COLOR_RULES,
        TEXT_PLACEMENT_RULES,
    ]
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

    if no_text:
        body += "\n" + NO_TEXT_IMAGE_OVERRIDE

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
