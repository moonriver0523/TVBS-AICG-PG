"""編輯專屬版型的定義表（2026-09-03 使用者需求）。

記者沒有這些需求，這是編輯專有的。三層防呆讓記者不可能誤用：
  1. 前端：角色不是編輯時，這個下拉根本不顯示
  2. 前端：切回記者時把選擇重置成 default
  3. 後端：`role != "編輯"` 時直接忽略這個欄位（見 main.build_digest_instructions）

為什麼不併進現有的「版面形式」下拉：那組（資料圖表／情境示意圖／地圖／3D）在後端是
一組 strict JSON schema enum，而「AI 自動判斷」就是叫模型**從那組裡自己挑**。把編輯
專屬項目加進去，等於模型會主動挑給記者——UI 藏得掉，模型挑不掉。

為什麼不另開分頁：編輯的工作流是連貫的（同一則新聞可能先出鏡面、再做封面），
切分頁很怪；而且新聞原文、指令欄、參考圖、產出區、追加修改全部共用，複製一份
分頁等於每次改都要改兩處。改成「同一頁、選了格式就換裝輸入區」。

這張表刻意只留後端真正需要的三件事：標籤、走哪條管線、注入哪塊消化規則。
「鎖哪些開關、顯示哪些輸入欄」純屬介面行為，放在 app.js 的同名表裡。
"""

import re

DEFAULT_FORMAT = "default"

# 走一般 /api/generate + /api/images/generate；ten_cover 走 /api/editor/cover；
# yt_live_cover 走 /api/editor/yt-cover
PIPELINE_GENERATE = "generate"
PIPELINE_COVER = "cover"
PIPELINE_YT_COVER = "yt_cover"

# 封面的兩種做法。ai＝整張交給生圖模型（只有 Logo 後製）；
# composite＝AI 只出兩張無文字底圖、文字全部由 Pillow 畫（見 compose.compose_ten_cover）。
COVER_MODE_AI = "ai"
COVER_MODE_COMPOSITE = "composite"


# 播出鏡面：畫面裡要留一塊給後製合成影片。那塊由 compose.apply_broadcast_hole
# 在置框後**數學貼上**，不靠模型自律（五輪實驗證實模型做不到，見 compose.py 開頭）。
# 消化端要做的只有一件事：把所有內容趕到另外半邊，別讓模型把重點畫在會被蓋掉的地方。
#
# ⚠️ 這段文字裡永遠不得出現任何數字或比例——模型會把數字當文字畫進圖裡
# （見 docs/error-cases/2026-07-23-像素安全框-分析.md）。位置一律用方位詞描述。
_BROADCAST_RULES_TEMPLATE = """

BROADCAST INSERT LAYOUT ({side_zh}側留給後製) — OVERRIDES THE LAYOUT SENTENCE ABOVE WHERE THEY CONFLICT:
1. A large rectangular area filling most of the {side_en} half of the frame, centred vertically, is reserved for a video window that is composited in after this image is made. Treat that whole half as if it were already occupied.
2. Put NOTHING there: no text, no headline, no icon, no chart, no figure, no logo, no callout, no decorative element. Whatever you place there will be covered and lost.
3. The layout sentence above asks for the design to be centred. FOR THIS FORMAT IT IS NOT CENTRED: write into "structure" that the headline spans the upper band above the reserved area, and that every content block — every card, figure, icon and label — sits in the {opposite_en} half, stacked from top to bottom, entirely clear of the {side_en} half.
4. Keep the reserved area visually calm — plain continuous background, no busy texture, no bright focal point, no face. Say so in "structure".
5. THE CLOSING <蓋章> BANNER IS NOT FULL WIDTH IN THIS FORMAT. Every earlier rule that calls it "the lowest row of the content area" or "the lowest row of the design" refers to the content half only. Write into "structure" that the stamp banner sits inside the {opposite_en} half, directly under the last card, and does NOT span the frame or reach across into the reserved {side_en} half. The same goes for the headline: it may run across the upper band, but nothing may hang down into the reserved area.
6. "variable" must be exactly one [標題] line, then exactly three [內文小標] lines, then one <蓋章> line. Three points, no more and no fewer: this format's card stack has three rows.
7. Each [內文小標] line is one short scannable fact. Wrap the figure or the key phrase of each line in angle brackets so it can be highlighted.
8. Describe positions with direction words only (upper, lower, {side_en}, {opposite_en}, alongside, stacked). NEVER express any position or size as a percentage, pixel count, ratio or number of any kind.
"""


def _broadcast_rules(side: str) -> str:
    left = side == "left"
    return _BROADCAST_RULES_TEMPLATE.format(
        side_zh="左" if left else "右",
        side_en="left" if left else "right",
        opposite_en="right" if left else "left",
    )


# 十點不一樣封面：AI 只出**無文字**底圖，節目名／Logo／日期／標籤／兩邊標題全部
# 由 compose.compose_ten_cover 畫。所以這裡完全不經過消化——使用者直接給兩個標題。
COVER_VISUAL_PROMPT_TEMPLATE = """Generate a text-free broadcast news cover background photo.

Subject:
{visual}

Requirements:
- Square 1:1 framing, photographic, broadcast news quality, dramatic lighting.
- ABSOLUTELY NO text, no numbers, no letters, no captions, no logos, no watermarks, no signage, no readable writing of any kind anywhere in the image.
- No borders, no frames, no split-screen, no collage: one single continuous scene.
- Keep the composition readable when cropped to a wide rectangle: keep the subject centred and leave the extreme top and bottom free of essential detail.
"""


# ---- 十點不一樣封面：純 prompt 版（2026-09-03 使用者裁決，取代合成版當預設）----
#
# 為什麼改：合成版的字是 Pillow 用系統字型畫的，零錯字，但也零設計感——
# 參考圖那種金屬立體、雙色描邊、隨內容變化的美術字，程式畫不出來。使用者要的是
# 「除了 Logo 之外所有文字都要有設計感」，所以整張交給生圖模型，一次成形。
#
# 唯一的後製只剩 Logo：正版 Logo 讓模型畫必定變形，那是播出事故，不能賭。
# 所以 prompt 明令不准畫任何電視台標誌，並在左上角留一塊乾淨的位置給程式貼。
#
# 代價講在前面：模型畫中文有機率出錯字，而封面上的錯字是對外事故。合成版仍留在
# EDITOR_FORMATS 裡（ten_cover_composite）當備援與對照，隨時可以切回去比。
COVER_AI_PROMPT_TEMPLATE = """Design a complete, broadcast-quality Chinese-language news programme cover image (YouTube thumbnail style) for a Taiwanese prime-time news show.

=== CANVAS ===
16:9 horizontal. Two photographs fill the ENTIRE frame edge to edge, split by ONE thin white DIAGONAL seam (slightly leaning: its top end sits a little right of centre, its bottom end a little left of centre) into a LEFT panel and a RIGHT panel. No borders, no gutters, no letterboxing. Across the very top runs a THIN deep-navy header band (about one tenth of the frame height) with a bright blue hairline along its bottom edge; along the very bottom runs a slim blue decorative wave strip. Everything else is photograph.

=== TEXT TO RENDER (Traditional Chinese, Taiwan) ===
Render EXACTLY these strings, character for character. Do not translate them, do not rewrite them, do not shorten them, and do not add any other words, letters or numbers anywhere in the image.
- Programme name, as a SMALL blue rounded tag inside the header band, to the right of the empty logo area: 十點不一樣
- Small red rounded tag at the RIGHT end of the header band: {badge_text}
- Date, in the header band immediately to the left of that tag: {date_text}
- Headline of the LEFT panel, LEFT-aligned in its lower-left area, over the photograph: {title_left}
- Headline of the RIGHT panel, RIGHT-aligned in its lower-right area, over the photograph: {title_right}
- A small unobtrusive label just below the header band, at the outer top corner of each panel: AI示意圖

=== TYPOGRAPHY (this is the point of the image) ===
- Programme name 十點不一樣: FLAT, SOLID WHITE, bold sans-serif, small, sitting on a small blue rounded tag inside the header band. Absolutely NO metallic, chrome, silver, gold, gradient, glossy, bevelled, embossed or 3-D extruded treatment — it is plain white type on a blue tag, clean and quiet; it is NOT a large title.
- The two headlines are the loudest thing in the frame: very heavy condensed Chinese display type, BROKEN INTO TWO OR THREE STACKED LINES each (split each headline at a natural phrase boundary yourself), tightly leaded, with a thick dark outline and a strong drop shadow so they read over photography. The lower part of each photograph darkens gently so the headline stays readable.
- COLOUR EACH LINE DIFFERENTLY within a headline — that variation is required, not optional. Follow this order: the FIRST line solid white, the SECOND line bright golden yellow, the THIRD line (if any) vivid red with a white outline. Never render a whole headline in one flat colour.
- The small red tag is a neat rounded rectangle in bold white characters with a small white dot before the text, like an on-air light.
- The date is a clean, light, small white sans-serif, no effects, inside the header band.
- The AI示意圖 label is small, plain white, deliberately understated, on a faint dark plate so it stays readable.
- Every Chinese character must be correctly formed, complete and legible. No garbled strokes, no invented characters, no Japanese or Simplified forms.

=== IMAGERY ===
- LEFT half photograph: {visual_left}
- RIGHT half photograph: {visual_right}
- Both are photographic, dramatically lit, news-documentary quality, filling their panel edge to edge behind the headline, meeting at the diagonal seam.

=== HARD CONSTRAINTS ===
- NO television channel logo, NO station identity mark, NO broadcaster wordmark, NO dot-pattern emblem, NO watermark of any kind. The upper-LEFT corner of the header band (the left-most fifth of the band) must be left as clean empty navy background — a real logo is placed there afterwards, so keep that corner free of text, graphics and busy detail.
- No text other than the strings listed above. No captions, no subtitles, no tickers, no lower thirds, no URLs, no social handles.
- Keep every piece of text well inside the frame with clear breathing space; nothing may touch or be clipped by any edge.
"""


# 畫面描述留空時由 AI 依標題補（2026-09-03 使用者要求：兩欄改選填）。
# 為什麼要補而不是直接把標題丟給生圖模型：標題是新聞語彙（「重創水電產能」），
# 不是畫面語彙。直接餵過去，模型只能猜，而且很容易把標題的字又畫進圖裡一次。
# 先請文字模型翻成「鏡頭前看得到什麼」，生圖端才有具體的東西可以畫。
COVER_VISUAL_DERIVE_SYSTEM = """You turn Taiwanese TV news headlines into shot descriptions for a news cover photograph.

For each headline you are given, describe the single photograph that should sit behind it. Return one description per side.

Rules for every description:
- Describe only what a camera would see: place, subject, action, weather, light, lens feel. Concrete and photographable.
- Traditional Chinese (Taiwan), one sentence, roughly twenty to forty characters. No bullet points.
- NEVER mention text, captions, headlines, numbers, charts, logos or watermarks — the photograph carries no writing at all.
- Do not restate the headline. Turn its meaning into a scene.
- No named real people and no identifiable faces: use anonymous figures, back views, crowds, or objects and places instead.
- If a headline is about data, money or policy, choose a real-world scene that stands for it (a building, a counter, hands, equipment), never a graph.
- If a side's description is already supplied, repeat it back unchanged.
"""

COVER_VISUAL_SCHEMA = {
    "type": "object",
    "properties": {
        "visual_left": {"type": "string"},
        "visual_right": {"type": "string"},
    },
    "required": ["visual_left", "visual_right"],
    "additionalProperties": False,
}


# ============================================================
# YT 直播封面（2026-09-05 使用者需求）
#
# 使用情境：直播開播前要一張 YouTube 封面。使用者只給一句標題（半形空格分兩段）、
# 選一個副標、要不要附圖；LIVE 章、日期、Logo、白／黃兩色描邊標題全部由
# compose.compose_yt_cover 用字型與正版素材疊上去——封面上的錯字或變形 Logo
# 是對外事故，這條線上沒有任何文字交給生圖模型。
#
# 底圖三條路（依附圖決定，見 main.editor_yt_cover）：
#   有 asis 附圖 → 程式直接裁 16:9 當底圖，不打生圖模型（範例：C 肝針筒、引擎蓋）
#   有 scene／portrait／map 附圖 → 生圖模型帶附圖生無文字底圖
#   沒附圖 → 文字模型先依標題補畫面描述（可含具名真人，走主流程肖像查照），再生底圖
#
# 一套版型（使用者裁決 2026-09-05：不拆三種子規格）。範例裡男護理師那張 Logo 與
# LIVE 左右互換、第三行警語、漸層字都不納入。
# ============================================================

# 兩個獨立開關（頻道實際版面：原音呈現在 LIVE 章上方、AI即時翻譯在日期下方，可並存）
YT_COVER_ORIGINAL_AUDIO_LABEL = "原音呈現"
YT_COVER_AI_TRANSLATION_LABEL = "AI即時翻譯"

# 兩種 YT 直播版面，同一條 /api/editor/yt-cover：news＝國內外新聞直播（LIVE 章左上、副標）；
# hourly＝整點直播（Logo 左上、LIVE 章右上＋選填整點時間、紅底日期、無副標）
YT_COVER_LAYOUT_NEWS = "news"
YT_COVER_LAYOUT_HOURLY = "hourly"
YT_COVER_LAYOUTS = (YT_COVER_LAYOUT_NEWS, YT_COVER_LAYOUT_HOURLY)

# 標題分段：使用者用**恰好一個**半形空格分兩段就直接切；零個或兩個以上空格
# 交給文字模型判斷（範例 C 肝那張第二行本身就含空格「11人確診 疾管署說明」，
# 所以「遇到空格就切」不成立）。AI 的切法必須用原字元重組回原標題，否則不採用。
_YT_TITLE_SPLIT_RE = re.compile(r" +")


def split_live_title(title: str) -> tuple[str, str] | None:
    """恰好一個半形空格 → (第一行, 第二行)；其餘回 None 交給 AI。"""
    text = title.strip()
    parts = [p for p in _YT_TITLE_SPLIT_RE.split(text) if p]
    if len(parts) == 2:
        return parts[0], parts[1]
    return None


def title_split_is_faithful(title: str, line1: str, line2: str) -> bool:
    """AI 切出的兩行去掉所有空白後必須等於原標題去掉所有空白——改字就不採用。"""
    squash = lambda s: re.sub(r"\s+", "", s)  # noqa: E731
    return bool(squash(line1)) and bool(squash(line2)) and (
        squash(line1) + squash(line2) == squash(title)
    )


def realign_split_to_title(title: str, line1: str) -> tuple[str, str]:
    """把 AI 的分段點套回**原標題**，保留原有空格。

    AI 常把「11人確診 疾管署說明」回成「11人確診疾管署說明」——字沒改、空格掉了，
    faithful 檢查會過，但範例上那個空格是編輯刻意留的。所以只取 AI 的分段位置，
    兩行的字元從原標題切，不用 AI 回傳的字串。
    """
    text = title.strip()
    target = len(re.sub(r"\s+", "", line1))
    seen = 0
    for index, char in enumerate(text):
        if not char.isspace():
            seen += 1
            if seen == target:
                return text[: index + 1].strip(), text[index + 1 :].strip()
    return fallback_split_title(text)


def fallback_split_title(title: str) -> tuple[str, str]:
    """AI 也切不出合法結果時的最後退路：先用第一個空格，沒有空格就對半切。

    對半切一定能出圖但不一定通順；寧可出一張要人工改行的圖，也不要整個 500。
    """
    text = title.strip()
    if " " in text:
        head, _, tail = text.partition(" ")
        if head.strip() and tail.strip():
            return head.strip(), tail.strip()
    mid = max(1, len(text) // 2)
    return text[:mid], text[mid:]


# 十點不一樣封面（合成版）的標題分行：使用者用空白（半形／全形）或換行自己分，
# 最多 3 行；沒分且超過 COVER_TITLE_AUTO_SPLIT_LEN 個字就對切成兩行。
# 紅線同 YT：只切、不改字——去掉分隔符後必須等於原標題。
COVER_TITLE_AUTO_SPLIT_LEN = 7
COVER_TITLE_MAX_LINES = 3
_COVER_TITLE_SPLIT_RE = re.compile(r"[ \u3000\n\r｜|/]+")


def split_cover_title(title: str) -> list[str]:
    text = (title or "").strip()
    if not text:
        return []
    parts = [p for p in _COVER_TITLE_SPLIT_RE.split(text) if p]
    if len(parts) > COVER_TITLE_MAX_LINES:
        parts = parts[: COVER_TITLE_MAX_LINES - 1] + ["".join(parts[COVER_TITLE_MAX_LINES - 1 :])]
    if len(parts) == 1 and len(parts[0]) > COVER_TITLE_AUTO_SPLIT_LEN:
        whole = parts[0]
        mid = (len(whole) + 1) // 2
        parts = [whole[:mid], whole[mid:]]
    return parts


# ---- 封面標題自動消化（2026-09-06 使用者裁決：貼新聞內文 → AI 出標題 → 回填欄位，
# 編輯看過再自己按生成，不直接接生圖）----
#
# 十點不一樣：兩個標題（左格、右格）各自是同一則新聞的兩個切面，每個標題用半形空格
# 分成 2–3 段（每段就是封面上的一行）。YT 直播：一句標題用一個半形空格分兩段。
# 忠實度規則由 main.CONTENT_FIDELITY_RULES 接在後面（同主流程），標題只能用原文有的事實。
COVER_TITLE_DIGEST_SYSTEM_TEN = """You write the two headlines for a Taiwanese prime-time news programme cover (十點不一樣) from one news article.

Return JSON with "title_left" and "title_right".
- Each is a punchy Traditional Chinese (Taiwan) headline for one facet of the story; the two must cover DIFFERENT facets (e.g. what happened / the impact, the scene / the numbers, the cause / the response). Never repeat the same facts in both.
- Each headline is 2 or 3 segments separated by ONE half-width space; each segment 3–7 characters; whole headline at most 18 characters excluding spaces. Each segment becomes one printed line.
- No punctuation, no quotation marks, no emoji, no English unless it is a proper name in the source.
- Traditional Chinese only (Taiwan usage). Never Simplified forms.
"""

COVER_TITLE_DIGEST_SYSTEM_YT = """You write the headline for a Taiwanese TV news live-stream thumbnail from one news article.

Return JSON with "title".
- One Traditional Chinese (Taiwan) headline made of exactly TWO segments separated by ONE half-width space; each segment 5–12 characters. The two segments are printed as two lines: the first states the event, the second the key detail or consequence.
- No punctuation, no quotation marks, no emoji, no English unless it is a proper name in the source.
- Traditional Chinese only (Taiwan usage). Never Simplified forms.
"""

COVER_TITLE_DIGEST_SCHEMA_TEN = {
    "type": "object",
    "properties": {"title_left": {"type": "string"}, "title_right": {"type": "string"}},
    "required": ["title_left", "title_right"],
    "additionalProperties": False,
}
COVER_TITLE_DIGEST_SCHEMA_YT = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}


YT_COVER_VISUAL_PROMPT_TEMPLATE = """Generate a text-free photographic background for a live-stream news thumbnail.

Subject:
{visual}

Requirements:
- 16:9 horizontal, photographic, broadcast news quality, dramatic lighting, high contrast.
- ABSOLUTELY NO text, no numbers, no letters, no captions, no logos, no watermarks, no signage, no readable writing of any kind anywhere in the image.
- No borders, no frames, no split-screen, no collage: one single continuous scene.
- COMPOSITION FOR OVERLAYS: two lines of large headline type will be placed across the lower part of the frame afterwards, and a badge will sit in each upper corner. Keep the main subject in the upper-middle of the frame, keep the lower third free of essential detail (a plain or darker area there is ideal), and keep the extreme corners free of faces and key objects.
"""

# 標題由 AI 生成模式（2026-09-06 使用者試做後裁決：兩種並存、預設 AI 生成）。
# 整張封面連標題字、底帶都交給生圖模型；程式只後貼 LIVE 章／日期／標示／Logo。
# 左上、右上（整點版還有左中日期位）要留空，貼上去的固定元素才不會壓到模型畫的東西。
YT_COVER_TITLE_MODE_AI = "ai"
YT_COVER_TITLE_MODE_COMPOSITE = "composite"
YT_COVER_TITLE_MODES = (YT_COVER_TITLE_MODE_AI, YT_COVER_TITLE_MODE_COMPOSITE)

YT_COVER_FULL_PROMPT_NEWS = """Design a complete Taiwanese TV news LIVE-stream thumbnail (YouTube cover), 16:9.

=== TEXT TO RENDER (Traditional Chinese, Taiwan) ===
Render EXACTLY these strings, character for character, nothing else:
- Headline line 1 (upper line): {line1}
- Headline line 2 (lower line): {line2}

=== LAYOUT ===
- The lower 40% of the frame is a semi-transparent deep-navy band with a subtle circuit-board / tech-block texture, fading in at its top edge.
- Both headline lines are CENTRED horizontally on that band, stacked, each on one line, huge and heavy Chinese display type filling almost the full width.
- Line 1: solid white. Line 2: bright golden yellow. Both with a thick black outline. Flat type: no gradient, no metallic, no 3-D.
- Keep the UPPER-LEFT corner (a block about 24% wide and 40% tall) completely free of text or busy detail: a red LIVE badge and a date tab are pasted there afterwards.
- Keep the UPPER-RIGHT corner (a block about 20% wide and 16% tall) completely free: a channel logo tab is pasted there afterwards.

=== IMAGERY ===
{visual}
Photographic, dramatically lit, news-documentary quality, filling the frame behind the band.

=== HARD CONSTRAINTS ===
- Every Chinese character must be correctly formed, complete and legible. No garbled strokes, no invented characters, no Japanese or Simplified forms.
- No other text anywhere: no captions, no dates, no LIVE word, no logos, no watermark, no tickers, no 示意圖 label.
- Nothing may touch or be clipped by any edge.
"""

YT_COVER_FULL_PROMPT_HOURLY = """Design a complete Taiwanese TV news LIVE-stream thumbnail (YouTube cover) for an on-the-hour news bulletin, 16:9.

=== TEXT TO RENDER (Traditional Chinese, Taiwan) ===
Render EXACTLY these strings, character for character, nothing else:
- Headline line 1 (upper line): {line1}
- Headline line 2 (lower line): {line2}

=== LAYOUT ===
- Both headline lines sit in the lower third, LEFT-ALIGNED near the left edge, stacked, each on one line, huge and heavy Chinese display type spanning almost the full width. No band behind them: the type sits directly on the photograph.
- Line 1: solid white. Line 2: bright golden yellow. Both with a thick black outline. Flat type: no gradient, no metallic, no 3-D.
- Keep the UPPER-LEFT corner (about 14% wide and 14% tall) free: a small channel logo is pasted there afterwards.
- Keep the UPPER-RIGHT corner (about 27% wide and 32% tall) free: a red LIVE badge with the broadcast time is pasted there afterwards.
- Keep a strip on the LEFT directly above headline line 1 (about 32% wide and 10% tall) free of detail: a red date tab is pasted there afterwards.

=== IMAGERY ===
{visual}
Photographic, news-documentary quality, filling the frame.

=== HARD CONSTRAINTS ===
- Every Chinese character must be correctly formed, complete and legible. No garbled strokes, no invented characters, no Japanese or Simplified forms.
- No other text anywhere: no captions, no dates, no times, no LIVE word, no logos, no watermark, no tickers, no 示意圖 label.
- Nothing may touch or be clipped by any edge.
"""

# 生圖 prompt 最後一段。肖像規則（PORTRAIT_MODES）與附圖規則（USER_REFERENCE_MODES）
# 都寫著「VARIABLE FIELDS 裡的示意圖標籤要保持可見」——這條線根本沒有 VARIABLE
# FIELDS，模型看到那句會自己畫一個「示意圖」字樣上去。所以固定在**最後**加這段
# override：標籤由程式疊，底圖一個字都不准有。
YT_COVER_TEXT_FREE_OVERRIDE = """==================================================
TEXT-FREE BACKGROUND (OVERRIDES EVERY EARLIER RULE ABOUT LABELS)
==================================================
- This image is a text-free background. Software adds every headline, badge and label afterwards.
- Render NO text of any kind: no 示意圖 label, no caption, no name, no date, no logo, no watermark. Any earlier instruction that asks for a 示意圖 label or for text from VARIABLE FIELDS does not apply here — there are no variable fields.
- Everything else in the earlier blocks (likeness, pose, scene fidelity, use of the attached references) still binds in full."""

# 標題 → 畫面描述（＋分段、＋具名真人）。與十點不一樣的 COVER_VISUAL_DERIVE_SYSTEM
# 最大的差別：**允許具名真人**——網站主流程本來就允許最多三張具名真人臉（後端
# 查參考照），直播封面照範例（挪威國王）也要畫本人。人名交給 portrait_subjects，
# 由 main.apply_portrait_to_image_request 走主流程查照，不在這裡決定怎麼畫臉。
YT_COVER_DERIVE_SYSTEM = """You prepare a Taiwanese TV news live-stream thumbnail from one headline.

You are given the headline, and told whether it is already split into two lines.

1. "line1" / "line2" — the headline broken into TWO display lines.
   - If the input says the split is already decided, copy the two given lines back EXACTLY.
   - Otherwise split the headline at the most natural phrase boundary so the two lines are roughly balanced. Use ONLY the original characters in the original order: never add, drop, reorder or rewrite a single character, never translate. Removing all spaces from line1+line2 must give back the headline with its spaces removed.

2. "visual" — the single photograph that sits behind the headline.
   - Describe only what a camera would see: place, subject, action, weather, light, lens feel. Concrete and photographable.
   - Traditional Chinese (Taiwan), one sentence, roughly twenty to forty characters. No bullet points.
   - NEVER mention text, captions, headlines, numbers, charts, logos or watermarks — the photograph carries no writing at all.
   - Do not restate the headline. Turn its meaning into a scene.
   - If the headline is about a specific named real person (a head of state, a politician, a celebrity), the photograph should be a portrait-style shot of that person as its subject. Otherwise use anonymous figures, back views, crowds, objects or places.
   - If the headline is about data, money or policy, choose a real-world scene that stands for it, never a graph.

3. "portrait_subjects" — every specific named real person whose face the photograph would show, names exactly as the headline writes them (no title, no organisation), at most three. Empty array when the scene shows no named real person. "portrait_subjects_en" — the same people, same order, same length, each as the person's English or original-Latin-alphabet name (e.g. 川普 → "Donald Trump"); empty string only when you genuinely do not know it.
"""

YT_COVER_DERIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "line1": {"type": "string"},
        "line2": {"type": "string"},
        "visual": {"type": "string"},
        "portrait_subjects": {"type": "array", "items": {"type": "string"}},
        "portrait_subjects_en": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["line1", "line2", "visual", "portrait_subjects", "portrait_subjects_en"],
    "additionalProperties": False,
}


EDITOR_FORMATS = {
    DEFAULT_FORMAT: {
        "label": "預設（現行）",
        "pipeline": PIPELINE_GENERATE,
        "digest_rules": "",
        "hole_side": None,
    },
    "broadcast_left": {
        "label": "播出鏡面（左側挖空）",
        "pipeline": PIPELINE_GENERATE,
        "digest_rules": _broadcast_rules("left"),
        "hole_side": "left",
    },
    "broadcast_right": {
        "label": "播出鏡面（右側挖空）",
        "pipeline": PIPELINE_GENERATE,
        "digest_rules": _broadcast_rules("right"),
        "hole_side": "right",
    },
    # 十點不一樣封面：ai／composite 兩種模式並存，由前端「標題由 AI 生成」勾選框切換
    # （2026-09-06 使用者裁決比照 YT 直播封面，不再拆成兩個下拉項目）。
    # cover_mode 是預設值；實際模式由 TenCoverRequest.mode 決定。
    "ten_cover": {
        "label": "十點不一樣封面",
        "pipeline": PIPELINE_COVER,
        "cover_mode": COVER_MODE_AI,
        "digest_rules": "",
        "hole_side": None,
    },
    # YT 直播封面：底圖來自附圖或 AI，所有文字與 Logo／LIVE 章由 compose.compose_yt_cover 疊
    "yt_live_cover": {
        "label": "YT國內外新聞直播",
        "pipeline": PIPELINE_YT_COVER,
        "yt_layout": YT_COVER_LAYOUT_NEWS,
        "digest_rules": "",
        "hole_side": None,
    },
    # YT 整點直播：同一條底圖流程，版面換成 compose.compose_yt_hourly_cover（整點時間選填）
    "yt_hourly_cover": {
        "label": "YT整點直播",
        "pipeline": PIPELINE_YT_COVER,
        "yt_layout": YT_COVER_LAYOUT_HOURLY,
        "digest_rules": "",
        "hole_side": None,
    },
}

EDITOR_FORMAT_KEYS = tuple(EDITOR_FORMATS)


def get(key: str | None) -> dict:
    """取版型定義；未知或空值一律退回 default（呼叫端不用自己判空）。"""
    return EDITOR_FORMATS.get(key or DEFAULT_FORMAT, EDITOR_FORMATS[DEFAULT_FORMAT])


def digest_rules(key: str | None, role: str) -> str:
    """消化階段要注入的規則。非編輯角色一律空字串——第三層防呆。"""
    if role != "編輯":
        return ""
    return get(key)["digest_rules"]


def cover_mode(key: str | None) -> str:
    """封面走哪一種做法；不是封面版型時回空字串。"""
    return get(key).get("cover_mode", "")


def hole_side(key: str | None, role: str) -> str | None:
    if role != "編輯":
        return None
    return get(key)["hole_side"]
