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

# 底色框的百分比要跟合成版同一個數字（見 _BAND_CLAUSE_TEMPLATE）。compose 只在函式
# 內部反向 import editor_formats，模組層級不成環。
import compose

DEFAULT_FORMAT = "default"

# 走一般 /api/generate + /api/images/generate；ten_cover 走 /api/editor/cover；
# yt_live_cover 走 /api/editor/yt-cover
PIPELINE_GENERATE = "generate"
PIPELINE_COVER = "cover"
PIPELINE_YT_COVER = "yt_cover"
# YT 直播「直標」（2026-09-08 WP3）：不生圖、不打任何模型，純程式畫一張透明底 PNG
# 疊在直播訊號上，所以自成一條 pipeline，跟三種 YT 封面不是同一件事。
PIPELINE_YT_OVERLAY = "yt_overlay"

# 封面的兩種做法。ai＝整張交給生圖模型（只有 Logo 後製）；
# composite＝AI 只出兩張無文字底圖、文字全部由 Pillow 畫（見 compose.compose_ten_cover）。
COVER_MODE_AI = "ai"
COVER_MODE_COMPOSITE = "composite"

# 十點不一樣的版面。auto＝合併後的版型（依第二標題自動判定，見 resolve_cover_layout）；
# split／full 是實際生成時只會是這兩個之一的結果值，也是舊呼叫端會明示的值。
COVER_LAYOUT_SPLIT = "split"
COVER_LAYOUT_FULL = "full"
COVER_LAYOUT_AUTO = "auto"
COVER_LAYOUTS = (COVER_LAYOUT_SPLIT, COVER_LAYOUT_FULL)

# 播出鏡面的兩側。挖空方向 2026-09-08 起由請求欄位決定（見 resolve_hole_side）。
HOLE_SIDES = ("left", "right")


# 播出鏡面：畫面裡要留一塊給後製合成影片。那塊由 compose.apply_broadcast_hole
# 在置框後**數學貼上**，不靠模型自律（五輪實驗證實模型做不到，見 compose.py 開頭）。
# 消化端要做的只有一件事：把所有內容趕到另外半邊，別讓模型把重點畫在會被蓋掉的地方。
#
# ⚠️ 這段文字裡永遠不得出現任何數字或比例——模型會把數字當文字畫進圖裡
# （見 docs/error-cases/2026-07-23-像素安全框-分析.md）。位置一律用方位詞描述。
_BROADCAST_RULES_TEMPLATE = """

BROADCAST INSERT LAYOUT ({side_zh}側留給後製) — OVERRIDES THE LAYOUT SENTENCE ABOVE WHERE THEY CONFLICT:
1. A WIDE, SHORT rectangle — much wider than it is tall — sitting in the {side_en} half of the frame, centred vertically, is reserved for a video window that is composited in after this image is made. It takes up most of that half's WIDTH but only about half of its HEIGHT, so a clear horizontal strip is left above it and a deeper clear strip is left BELOW it, running the whole way across the frame. It is NOT a tall panel and it does NOT reach the bottom of the frame. Treat the window itself as already occupied.
2. Put NOTHING there: no text, no headline, no icon, no chart, no figure, no logo, no callout, no decorative element. Whatever you place there will be covered and lost.
3. The layout sentence above asks for the design to be centred. FOR THIS FORMAT THE BODY IS NOT CENTRED: write into "structure" that the HEADLINE is the ONLY element allowed to span the full width{stamp_span_note} — it runs across the top strip of the frame, above the reserved area, as ONE line (two tightly-leaded lines only if it cannot fit in one), and it must end above the reserved area: nothing of it may hang down beside or into the video window. Every OTHER content block — every card, figure, icon and label — sits in the {opposite_en} half, stacked from top to bottom under the headline, entirely clear of the {side_en} half. THE HEADLINE MUST CARRY THE KEY FIGURE OR THE OUTCOME OF THE STORY, never a bare topic name: a reader who sees only that line should already know what happened.
4. Keep the reserved area visually calm — plain continuous background, no busy texture, no bright focal point, no face. Say so in "structure".
{stamp_rules}{point_rules}
8. Describe positions with direction words only (upper, lower, {side_en}, {opposite_en}, alongside, stacked). NEVER express any position or size as a percentage, pixel count, ratio or number of any kind.
"""


# 第 5／6 條依蓋章開關二選一（2026-09-07 使用者回報：蓋章 OFF 在播出鏡面失效——
# 這兩條原本無條件要求 <蓋章>，注入順序又在 STAMP_OFF_RULES 之後，把 OFF 壓掉了）。
#
# 2026-09-09 使用者回饋：挖空框是 16:9、垂直置中貼在留白半邊，於是那半邊的**最下方**
# 空了一條橫帶（安全區高的兩成多）什麼都沒有，看起來很怪。第 5 條因此反過來——蓋章
# 改成橫跨全寬、貼在挖空框底下那條低帶，與同樣跨全寬的標題上下夾住挖空框。
# 最右下角要留給 apply_broadcast_hole 事後蓋的「示意圖」浮水印。
_BROADCAST_STAMP_ON = """5. THE CLOSING <蓋章> BANNER RUNS THE FULL WIDTH ALONG THE VERY BOTTOM IN THIS FORMAT. The reserved video window does not reach the bottom of the frame: it is centred vertically, so a clear horizontal strip is left underneath it. Write into "structure" that the stamp banner is a single full-width bar lying in that low strip, BELOW the reserved area, hugging the bottom of the design and spanning from the {side_en} edge across to the {opposite_en} edge — it is the counterweight to the headline, which spans the full width across the top strip. Nothing of the banner may rise up beside or into the video window, and it stays a single line. Keep the extreme lower-RIGHT corner of that banner clear of essential wording: a small mark is added there afterwards. (It is the lower-right corner whichever half is reserved — the mark's position does not mirror.)
6. "variable" must be exactly one [標題] line, then exactly {count_word} [內文小標] lines, then one <蓋章> line. {count_word_cap} points, no more and no fewer: this format's card stack has {count_word} rows.{density_rules}
"""
_BROADCAST_STAMP_OFF = """5. THERE IS NO STAMP BANNER IN THIS GRAPHIC (the user switched it OFF, and that setting wins over every rule above or below that mentions a closing banner). Do NOT write any stamp banner, conclusion strip or closing bar into "structure", and do not put a <蓋章> line in "variable". BUT THE LOW STRIP UNDER THE RESERVED AREA IS STILL FILLED, BY A <底帶> LINE INSTEAD. Leaving that strip empty makes the graphic look unfinished, and it is what the user complained about. Write into "structure" that the <底帶> line is a single bar lying in that low strip, BELOW the reserved area, hugging the bottom of the design and spanning the FULL width from the {side_en} edge across to the {opposite_en} edge — it crosses both halves, exactly like the headline does across the top strip, and the two of them sandwich the video window. It is styled as an ordinary information card like the ones stacked above it, NOT as a coloured stamp and NOT as a closing slogan: it carries a real fact of its own. The remaining cards stay stacked in the {opposite_en} half under the headline. Nothing of it may rise up beside or into the video window, and it stays a single line. Keep the extreme lower-RIGHT corner of it clear of essential wording: a small mark is added there afterwards. (It is the lower-right corner whichever half is reserved — the mark's position does not mirror.)
6. THIS RULE OVERRIDES THE STAMP-OFF BLOCK ABOVE WHERE THEY DISAGREE ABOUT THE LAST LINE. "variable" must be exactly one [標題] line, then exactly {count_word} [內文小標] lines, then exactly one line beginning with the marker <底帶>. {count_word_cap} points, no more and no fewer: this format's card stack has {count_word} rows, and the <底帶> line is separate from them — it is the bar along the bottom, not one of the rows. Still no <蓋章> line anywhere. The <底帶> line carries an ordinary fact from the material, written short, in the same voice as the cards; it is never a slogan, a sign-off or a repeat of the headline.{density_rules}
"""


# 2026-09-08 使用者回饋 D：字多檔位在播出鏡面無處發揮——第 6 條固定「每卡一句」，
# 消化再怎麼放寬，卡片還是一行。字多時改成每卡兩行（短標＋數據），卡片數不變。
#
# ⚠️ 跟上面同一條鐵律：這段文字裡不得出現任何數字（連 half-width 阿拉伯數字都不行），
# 長度一律用文字描述（a few characters／a brief phrase）。
#
# 2026-09-09 第二輪：使用者說「字多消化後資訊量還是太少，可以放寬資訊卡的數量／
# 資訊密度／內文字數」。所以字多在播出鏡面除了每卡兩行，卡數也從三張放寬到四張
# （見 _broadcast_point_count），而且補充那一行的長度不再限制成「brief phrase」。
_BROADCAST_DENSITY_STANDARD = """ THIS GRAPHIC IS RUNNING AT THE 字多 DENSITY, SO EACH OF THOSE CARDS CARRIES TWO LINES INSTEAD OF ONE: the first line is a short punchy label of only a few characters, and the second line is the supporting figure or detail behind it, written as a full informative clause rather than a bare tag — say what the figure means, not just what it is. Write every [內文小標] as those two parts separated by a full-width vertical bar 「｜」, and say in "structure" that each card stacks its label above its supporting line, the label set larger than the line under it. Fill every card: this density exists because the user asked for MORE information on the graphic, so a card carrying only a couple of characters after the bar is a defect."""


# 播出鏡面的卡片張數：字多放寬到四張，其餘檔位維持三張（版面本來就是三列）。
# ⚠️ 一律用英文數字（three／four），不得寫成阿拉伯數字——見 _BROADCAST_RULES_TEMPLATE
# 上方的鐵律。
# 第 3 條的「標題是唯一可以跨全寬的元素」在蓋章 ON 之後不再成立（第 5 條把蓋章條
# 也放到全寬），兩條會被模型讀成互相衝突，所以 ON 的時候補一句指回第 5 條。
#
# 2026-09-09（第三批）使用者：「底下的除了蓋章之外，如果沒有開蓋章，其他資訊還是可以
# 放底下」。蓋章 OFF 也改成有東西跨全寬（最後一張卡下移到底帶），所以 OFF 同樣要補句。
#
# 2026-09-09（第四批）使用者實測蓋章 OFF ＋字多，底部還是空的。第三批只是叫模型「把
# 最後一張卡下移」——那張卡在 variable 裡跟其他卡長得一模一樣，模型沒有理由把它挑出來，
# 於是四張一起疊在半邊。蓋章 ON 之所以做得到，是因為 <蓋章> 是 variable 裡一個**看得見
# 的標記**。所以這一版比照辦理，給底帶自己的標記 <底帶>，並在 main 端做確定性兜底
# （ensure_bottom_band_line）：模型漏寫就把最後一張卡升級成底帶。
# 同一批也修第 1 條——挖空框其實是 16:9 的寬扁視窗（compose.apply_broadcast_hole），
# 舊句「filling most of the half」讓模型畫成整片高牆，底下那條帶根本不存在。
# 使用者同時開放底帶跨版（「就像標題可跨版」），第 5 條照這個寫。
_BROADCAST_STAMP_SPAN_NOTE = " (the closing <蓋章> banner is the one other full-width element — rule five lays it along the very bottom, under the reserved area)"
_BROADCAST_NO_STAMP_SPAN_NOTE = " (the <底帶> line is the one other full-width element — rule five lays it along the very bottom, under the reserved area, and it may cross both halves)"


# 蓋章 OFF 時，播出鏡面底帶那一行的標記（2026-09-09 第四批）。與 <蓋章> 平行：
# 有標記，模型才挑得出哪一行要放到底下那條橫帶。
BROADCAST_BOTTOM_MARKER = "底帶"


def _broadcast_point_count(density: str | None) -> dict:
    word = "four" if density in ("standard", "maximum") else "three"
    return {"count_word": word, "count_word_cap": word.capitalize()}

# 第 7 條跟著第 6 條一起換檔（2026-09-08 第二輪）：字多時第 6 條要求每卡兩行，
# 第 7 條若還寫「一句短事實」，兩條就會被模型讀成互相衝突。字少／不改字維持原句。
_BROADCAST_POINT_RULE_DEFAULT = """7. Each [內文小標] line is one short scannable fact. Wrap the figure or the key phrase of each line in angle brackets so it can be highlighted."""
_BROADCAST_POINT_RULE_STANDARD = """7. Each [內文小標] is written as the two parts rule six describes — 短標｜補充細節 — joined by a full-width vertical bar 「｜」. The 短標 part before the bar is one short scannable fact; the 補充細節 part after it carries the supporting data or detail behind that fact. Wrap the figure or the key phrase in angle brackets so it can be highlighted, and put those angle brackets in the 短標 part."""


def _broadcast_rules(
    side: str, stamp: bool | None = None, density: str | None = None
) -> str:
    left = side == "left"
    # 字超多沿用字多的版面加碼（四張卡、每卡兩行）：卡片列數是版面實體限制，不隨密度長。
    standard = density in ("standard", "maximum")
    stamp_block = _BROADCAST_STAMP_OFF if stamp is False else _BROADCAST_STAMP_ON
    return _BROADCAST_RULES_TEMPLATE.format(
        stamp_rules=stamp_block.format(
            density_rules=_BROADCAST_DENSITY_STANDARD if standard else "",
            side_en="left" if left else "right",
            opposite_en="right" if left else "left",
            **_broadcast_point_count(density),
        ),
        point_rules=(
            _BROADCAST_POINT_RULE_STANDARD if standard else _BROADCAST_POINT_RULE_DEFAULT
        ),
        side_zh="左" if left else "右",
        side_en="left" if left else "right",
        opposite_en="right" if left else "left",
        stamp_span_note=(
            _BROADCAST_NO_STAMP_SPAN_NOTE if stamp is False else _BROADCAST_STAMP_SPAN_NOTE
        ),
    )


# 十點不一樣封面：AI 只出**無文字**底圖，節目名／Logo／日期／標籤／兩邊標題全部
# 由 compose.compose_ten_cover 畫。所以這裡完全不經過消化——使用者直接給兩個標題。
COVER_VISUAL_FULL_PROMPT_TEMPLATE = """Generate a text-free broadcast news cover background photo.

Subject:
{visual}

Requirements:
- 16:9 horizontal, photographic, broadcast news quality, dramatic lighting.
- ABSOLUTELY NO text, no numbers, no letters, no captions, no logos, no watermarks, no signage, no readable writing of any kind anywhere in the image.
- No borders, no frames, no split-screen, no collage: one single continuous scene.
- COMPOSITION FOR OVERLAYS: a thin header band covers the very top, and two or three lines of large headline type will be placed in the lower-left area afterwards. Keep the main subject in the upper-middle / right, keep the lower-left free of essential detail (a plain or darker area there is ideal).
"""

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
# 2026-09-07 起「十點不一樣」節目標籤也改貼模板（static/brand/ten-show-tag.png，
# 使用者給的正版樣式：藍色斜切、金色「十」＋白字、NEWS NIGHT），模型不再畫節目名。
# 所以 prompt 明令不准畫任何電視台標誌，並在左上角留一塊乾淨的位置給程式貼。
#
# 代價講在前面：模型畫中文有機率出錯字，而封面上的錯字是對外事故。合成版仍留在
# EDITOR_FORMATS 裡（ten_cover_composite）當備援與對照，隨時可以切回去比。
COVER_AI_PROMPT_TEMPLATE = """Design a complete, broadcast-quality Chinese-language news programme cover image (YouTube thumbnail style) for a Taiwanese prime-time news show.

=== CANVAS ===
16:9 horizontal. Two photographs fill the ENTIRE frame edge to edge, split by ONE thin white DIAGONAL seam (slightly leaning: its top end sits a little right of centre, its bottom end a little left of centre) into a LEFT panel and a RIGHT panel. No borders, no gutters, no letterboxing. Across the very top runs a deep-navy header band (%HEADER_BAND% of the frame height) with a bright blue hairline along its bottom edge; along the very bottom runs a slim deep-navy strip with one thin glowing straight blue light line (no waves, no text). Everything else is photograph.

=== TEXT TO RENDER (Traditional Chinese, Taiwan) ===
Render EXACTLY these strings, character for character. Do not translate them, do not rewrite them, do not shorten them, and do not add any other words, letters or numbers anywhere in the image.
- Small red rounded tag at the RIGHT end of the header band: {badge_text}
- Date, in the header band immediately to the left of that tag: {date_text}
- Headline of the LEFT panel, LEFT-aligned in its lower-left area, over the photograph. It is ALREADY split into lines — render each line on its own line, in this order, and do NOT re-split, merge or reorder them:
{title_left_lines}
- Headline of the RIGHT panel, RIGHT-aligned in its lower-right area, over the photograph. Same rule — render these lines as given:
{title_right_lines}

=== TYPOGRAPHY (this is the point of the image) ===
- The two headlines are the loudest thing in the frame: very heavy condensed Chinese display type, STACKED ON THE LINES GIVEN ABOVE (the split is already decided — never change it), tightly leaded, with a thick dark outline and a strong drop shadow so they read over photography. The lower part of each photograph darkens gently so the headline stays readable.
- THE NUMBER OF LINES AND WHERE THEY BREAK ARE FIXED. Each headline lists its lines above with a count. Render EVERY listed line on its OWN separate row, in the listed order: never merge two listed lines onto one row, never break one listed line across two rows, never drop or reorder one. A headline listed as three lines must appear as three stacked rows.
- COLOUR EACH LINE EXACTLY AS LABELLED in that list: (white) = solid white, (yellow) = bright golden yellow, (red) = vivid red with a white outline. Follow the labels literally — never recolour a line, and never give a whole headline one flat colour.
- The small red tag is a neat rounded rectangle in bold white characters with a small white dot before the text, like an on-air light.
- The date is a clean, light, small white sans-serif, no effects, inside the header band.
- Every Chinese character must be correctly formed, complete and legible. No garbled strokes, no invented characters, no Japanese or Simplified forms.
{title_style_clause}
=== IMAGERY ===
- LEFT half photograph: {visual_left}
- RIGHT half photograph: {visual_right}
- Both are photographic, dramatically lit, news-documentary quality, filling their panel edge to edge behind the headline, meeting at the diagonal seam.

=== HARD CONSTRAINTS ===
- NO television channel logo, NO station identity mark, NO broadcaster wordmark, NO dot-pattern emblem, NO watermark of any kind, and do NOT write the programme name (十點不一樣) anywhere. The upper-LEFT corner of the header band — its entire LEFT HALF — must be left as clean empty navy background: the real channel logo and the official programme-name tag are pasted there afterwards, so keep that whole area free of text, graphics and busy detail. Only the date and the small red tag sit in the header band, at its right end.
- Do NOT draw any 示意圖 label, AI示意圖 label or similar disclaimer anywhere in the image. Software adds that label afterwards, at the outer top corner below the header band — keep that small area free of text and busy detail.
- No text other than the strings listed above. No captions, no subtitles, no tickers, no lower thirds, no URLs, no social handles.
- Keep every piece of text well inside the frame with clear breathing space; nothing may touch or be clipped by any edge.
"""

# 滿版（單張圖、單一標題）版本，2026-09-07 由雙切模板派生：只改畫布／文字／影像三段。
COVER_AI_FULL_PROMPT_TEMPLATE = """Design a complete, broadcast-quality Chinese-language news programme cover image (YouTube thumbnail style) for a Taiwanese prime-time news show.

=== CANVAS ===
16:9 horizontal. ONE single photograph fills the ENTIRE frame edge to edge. No split, no seam, no panels, no collage, no borders, no gutters, no letterboxing. Across the very top runs a deep-navy header band (%HEADER_BAND% of the frame height) with a bright blue hairline along its bottom edge; along the very bottom runs a slim deep-navy strip with one thin glowing straight blue light line (no waves, no text). Everything else is photograph.

=== TEXT TO RENDER (Traditional Chinese, Taiwan) ===
Render EXACTLY these strings, character for character. Do not translate them, do not rewrite them, do not shorten them, and do not add any other words, letters or numbers anywhere in the image.
- Small red rounded tag at the RIGHT end of the header band: {badge_text}
- Date, in the header band immediately to the left of that tag: {date_text}
- The headline, LEFT-aligned in the lower-left area of the frame, over the photograph. It is ALREADY split into lines — render each line on its own line, in this order, and do NOT re-split, merge or reorder them:
{title_left_lines}

=== TYPOGRAPHY (this is the point of the image) ===
- The headline is the loudest thing in the frame: very heavy condensed Chinese display type, STACKED ON THE LINES GIVEN ABOVE (the split is already decided — never change it), occupying roughly the left half of the frame, tightly leaded, with a thick dark outline and a strong drop shadow so they read over photography. The lower part of the photograph darkens gently so the headline stays readable.
- THE NUMBER OF LINES AND WHERE THEY BREAK ARE FIXED. The headline lists its lines above with a count. Render EVERY listed line on its OWN separate row, in the listed order: never merge two listed lines onto one row, never break one listed line across two rows, never drop or reorder one. A headline listed as three lines must appear as three stacked rows.
- COLOUR EACH LINE EXACTLY AS LABELLED in that list: (white) = solid white, (yellow) = bright golden yellow, (red) = vivid red with a white outline. Follow the labels literally — never recolour a line, and never give a whole headline one flat colour.
- The small red tag is a neat rounded rectangle in bold white characters with a small white dot before the text, like an on-air light.
- The date is a clean, light, small white sans-serif, no effects, inside the header band.
- Every Chinese character must be correctly formed, complete and legible. No garbled strokes, no invented characters, no Japanese or Simplified forms.
{title_style_clause}
=== IMAGERY ===
- The photograph: {visual_left}
- Photographic, dramatically lit, news-documentary quality, filling the whole frame edge to edge behind the headline; keep the main subject towards the upper-middle and right so the lower-left stays calm for the headline.

=== HARD CONSTRAINTS ===
- NO television channel logo, NO station identity mark, NO broadcaster wordmark, NO dot-pattern emblem, NO watermark of any kind, and do NOT write the programme name (十點不一樣) anywhere. The upper-LEFT corner of the header band — its entire LEFT HALF — must be left as clean empty navy background: the real channel logo and the official programme-name tag are pasted there afterwards, so keep that whole area free of text, graphics and busy detail. Only the date and the small red tag sit in the header band, at its right end.
- Do NOT draw any 示意圖 label, AI示意圖 label or similar disclaimer anywhere in the image. Software adds that label afterwards, at the outer top corner below the header band — keep that small area free of text and busy detail.
- No text other than the strings listed above. No captions, no subtitles, no tickers, no lower thirds, no URLs, no social handles.
- Keep every piece of text well inside the frame with clear breathing space; nothing may touch or be clipped by any edge.
"""


# 標題設計感開關（2026-09-08 使用者要求：AI 整張版的標題要「設計感＋滿框」，像節目片頭字卡）。
# 預設 plain＝維持現行排版（白／黃／紅逐行配色、行數行序釘死）；designed 才追加下面這段。
#
# 2026-09-09 使用者：「十點不一樣的 AI 設計標題可以不用照白黃紅三段規則，設計規則與放置
# 位置完全解放，可以嘗試各種字體、顏色、設計邊框、強調，完全交由 AI 大膽設計。」
# 所以 designed 從「只改大小與位置」升級成整段 OVERRIDE：配色、版位、字體、邊框、
# 強調手法全放給模型。解放的是**設計**，不是**內容**——底下明文列出仍然不准動的事：
# 一個字都不能加減改（含 9/12 這種斜線不得拆開）、正體中文、標頭帶左半與 AI示意圖
# 角落要留空（那兩處是程式後貼的，見 compose.paste_cover_logo／paste_cover_ai_note）、
# 上下兩條深藍帶不得被字蓋掉。plain 那條線完全不受影響，出事就把開關關掉。
# 位置在 TYPOGRAPHY 段最後、又寫明 OVERRIDE——本 repo 的慣例是「位置＋明文同向」才壓得住。
#
# 2026-09-09（第七批）使用者：「十點不一樣 設計標題 可以更奔放 參考我們現行的AI設計版
# 標題」，並附兩張現行 YouTube 封面截圖當基準。對照當時的成品（20260909-215559）：
# 模型只把填色換成金屬金，版面仍是兩行等大、齊左、規規矩矩的堆疊。
# 根因是這一段**寫成「許可」**（you may…／no longer binds），而它前面整段 TYPOGRAPHY
# 都是命令句。許可推不動模型，模型會走阻力最小的路＝照舊排版、只換材質。
# 改法：先用**命令句描述那個 house style 長什麼樣**（大小落差、行內關鍵詞換色、
# 飽和平塗＋粗黑描邊＋硬投影、可加 1–2 個無字圖示、錯落），解除綁定的句子留在後面。
# 截圖裡另外那些東西——國旗小標（帶國名）、地圖地名、重複的問號徽章——是**清單外文字**，
# 撞硬規則 (e)，而且國旗的位置正好是 paste_cover_ai_note 要貼的角落，這批不開。
# 兩行是同一個名詞／同一句話時（古羅馬圖／拉真浴場）不得放大其中一行，會拆散語意。
COVER_TITLE_STYLE_PLAIN = "plain"
COVER_TITLE_STYLE_DESIGNED = "designed"
COVER_TITLE_STYLES = (COVER_TITLE_STYLE_PLAIN, COVER_TITLE_STYLE_DESIGNED)

# 帶高不手寫。第三批的教訓是「模型手上有什麼數字就抄什麼」，而 compose 補帶／貼 Logo
# 用的是 COVER_AI_HEADER_RATIO——兩邊各寫各的，改一邊就會悄悄脫鉤。
# 兩張模板裡還留著 {badge_text} 之類的執行期欄位，不能整段丟給 f-string，所以先放記號再換掉。
_HEADER_BAND_PERCENT = round(compose.COVER_AI_HEADER_RATIO * 100)
COVER_AI_PROMPT_TEMPLATE = COVER_AI_PROMPT_TEMPLATE.replace(
    "%HEADER_BAND%", f"about {_HEADER_BAND_PERCENT}%"
)
COVER_AI_FULL_PROMPT_TEMPLATE = COVER_AI_FULL_PROMPT_TEMPLATE.replace(
    "%HEADER_BAND%", f"about {_HEADER_BAND_PERCENT}%"
)


# ---- 創意拉桿（2026-09-09 第八批）----
#
# 使用者：「AI 消化的創意奔放程度，能不能設為好幾個等級，讓使用者自己選擇。前台 UI
# 做成像調整 AI effort 的拉 bar，最左邊創意最低，最右邊創意最高。」
#
# 級距怎麼訂：**每一級都要用命令句描述它長什麼樣**，不能寫成「你可以…」。
# 第七批才剛證明許可句推不動模型——中間那幾級若寫成許可，成品會跟 0 或 4 長一樣，
# 拉桿就變成騙人的。所以四級是**由上往下減**：4 是使用者給的那組封面（house style），
# 往下逐項收回自由。4 以上不再往上加（傾斜、疊字、破格會撞死規則 (c)(d)(g)，
# 而且使用者沒要）。
#
# 不隨等級變的：下面那塊 FIXED (a)–(g)。拉桿調的是**設計自由度**，
# 內容（一字不改）與版面規約（程式後貼的三塊區域、不得跨格）永遠不動。
#
# 2026-09-10 再陡一次。使用者看完 sunburst 重跑的 0–4：「好像沒有這麼抖，尤其是
# 1、2 之間」。原因是每一級只多給一項自由，而多出來的那項又都落在字的表面：
# 1 只有 finish、2 只多了尺寸階層與行內換色。所以四級全部重訂，每一級都補一個
# **看得見形狀改變**的必做項，並把原本 4 級獨有的幅度往下放一級：
#   L1 厚描邊＋硬投影＋字面材質＋標題塊要有底板（跟「沒設計」拉開）
#   L2 ＋尺寸階層／行內反白／**錯位排列**／**每行各自的底板**（不再是一塊方板）
#   L3 ＋多層描邊與立體擠出（原本 4 級的）／**標題與照片主體交錯**／版位自由／圖示
#   L4 ＋落差拉到 2.5–3 倍／第三層描邊／**傾斜從「可以」改成「必須」**／爆裂裝飾
# 判準同 CG 那條拉桿的教訓：形容詞會被圖模平均掉，能看見的是形狀與位置的改變。
COVER_AI_TITLE_LEVEL_MIN = 0
COVER_AI_TITLE_LEVEL_MAX = 4
COVER_AI_TITLE_LEVEL_NAMES = {
    0: "規矩",
    1: "微設計",
    2: "有設計",
    3: "奔放",
    4: "最狂",
}

# (a)–(g)：每一級（0 以外）都原樣附上。
_TITLE_FIXED_BLOCK = """- WHAT IS STILL FIXED, AND IS NOT A DESIGN DECISION: (a) the CHARACTERS. Render the listed strings character for character in the listed order — never add, drop, translate, abbreviate, reorder or substitute a single character to make a layout work, and never break a listed line in the middle: a listed line is one unbroken unit, so a date or score written with a slash such as 9/12 stays whole on one row. (b) Traditional Chinese, Taiwan forms, every character correctly formed and legible — no Simplified or Japanese forms, no invented strokes. (c) The header band across the top and the slim navy strip along the bottom stay as described, and NO part of the headline may sit inside them or overlap them. (d) The whole LEFT HALF of the header band and the small area just below its outer top corner stay clean and empty — software pastes the channel logo, the programme tag and the 示意圖 label there afterwards. (e) No text of any kind other than the listed strings: decorative marks are wordless symbols only — no letters, no digits, no country names, no place labels, no flag chips, no map insets, no extra badges or callouts. (f) Nothing touches or is clipped by the frame edge. (g) In the two-panel layout, each headline stays ENTIRELY INSIDE ITS OWN PANEL and never crosses the diagonal seam or strays into the other panel: freeing the placement frees where it sits WITHIN its panel, not which panel it belongs to.
"""

# 每一級的開頭都帶 DESIGNED TITLE 這個記號＋OVERRIDE 宣告：本 repo 的慣例是
# 「位置在後＋明文 OVERRIDE」才壓得過前面那整段 TYPOGRAPHY 命令句。
_L1 = """- DESIGNED TITLE (level 1 of 4 — light) — THIS BULLET AND THE ONE BELOW OVERRIDE EVERY TYPOGRAPHY INSTRUCTION ABOVE WHEREVER THEY DISAGREE. Give the headline a designed display finish, and change NOTHING ELSE about it. All three of these are required, not offered — the difference from an undesigned caption has to be obvious at a glance across a room:
  * A THICK DARK OUTLINE around every character plus a hard offset drop shadow. Not a thin stroke and not a soft blur.
  * A SURFACE MATERIAL on the characters — a gradient, a soft bevel or a subtle sheen — instead of one flat fill.
  * A DEFINED BLOCK BEHIND THE WORDS: a solid or gradient panel, a bar, or a shaped plate sitting behind the whole headline so it reads as a title card mounted on the photograph rather than type floating on it.
Everything else stays exactly as instructed above: the per-line colours stay EXACTLY as labelled (white / yellow / red), all lines stay at ONE size, and the block stays flush-stacked in the labelled lower corner.
"""

_L2 = """- DESIGNED TITLE (level 2 of 4 — designed) — THIS BULLET AND THE TWO BELOW OVERRIDE EVERY TYPOGRAPHY INSTRUCTION ABOVE WHEREVER THEY DISAGREE. The headline is a title card built by a broadcast art director, not body text. Build it the way this show's real covers are built — a tame, evenly-set stack is a failure here:
  * SIZE HIERARCHY IS REQUIRED. The lines are not the same size. Set the short punchy line — the one that shouts, usually the one ending in 「！」 — at roughly one and a half to two times the height of the line that explains it, and let the explaining line tuck under it, indented or offset rather than flush-stacked.
  * PULL A KEY WORD OUT INSIDE A LINE. Within a line, take the place name, the number, the quoted phrase or the one word that carries the shock, and give it a different treatment from the rest of that same line: another colour, a vivid red or black block with the word reversed out of it, a heavier or larger cut. Quotation marks such as 「」 or 『』 around a phrase are a cue to do exactly this. Every line must not be one flat colour.
  * THE HOUSE PALETTE AND FINISH: saturated FLAT golden yellow, pure white and vivid red, over a thick black outline with a hard offset drop shadow and a tight coloured inner edge — punchy poster colour, high contrast, slight forward lean. Not a soft pastel wash, and not one uniform polished metallic fill across the whole headline.
  * THE STACK IS NO LONGER FLUSH — this is required, not offered. The rows step: each row is indented, offset or shifted against the one above it, so the left edges do not line up in a column. A neatly flush-left stack is exactly the level-1 look this level exists to leave behind.
  * EACH ROW SITS ON ITS OWN SHAPE. Instead of one panel behind the whole headline, give the rows their own plates, bars or ribbons — cut on the same slant or sharing one corner treatment — so the block reads as assembled parts, not as a paragraph on a rectangle.
  * You still choose the typeface, the exact colours, the outline and shadow treatment, and the decorative frames or shapes behind or around the words. Be bold.
- WHAT THIS CANCELS: the per-line colour labels (white / yellow / red) are only a hint you may ignore entirely — recolour freely, give one line several colours, reverse a word out of a coloured block, whatever reads best; the fixed one-line-per-row stack no longer binds as a SHAPE — stagger the lines, indent them or run one line larger over another (the lines themselves, and how many there are, are still fixed; see below). THE PLACEMENT STILL BINDS: the block stays in the lower-left (or lower-right) area it was assigned. ONE EXCEPTION TO THE SIZE HIERARCHY: when the listed lines are not a hook plus its explanation but one continuous phrase, sentence or proper name simply broken across rows, keep them at ONE size — enlarging half of a single name breaks it apart.
"""

_L3 = """- DESIGNED TITLE (level 3 of 4 — loud) — THIS BULLET AND THE TWO BELOW OVERRIDE EVERY TYPOGRAPHY INSTRUCTION ABOVE WHEREVER THEY DISAGREE. The headline is a title card built by a broadcast art director, not body text. Build it the way this show's real covers are built, and go loud — a tame, evenly-set stack is a failure here:
  * SIZE HIERARCHY IS REQUIRED. The lines are not the same size. Set the short punchy line — the one that shouts, usually the one ending in 「！」 — at roughly one and a half to two times the height of the line that explains it, and let the explaining line tuck under it, indented or offset rather than flush-stacked.
  * PULL A KEY WORD OUT INSIDE A LINE. Within a line, take the place name, the number, the quoted phrase or the one word that carries the shock, and give it a different treatment from the rest of that same line: another colour, a vivid red or black block with the word reversed out of it, a heavier or larger cut. Quotation marks such as 「」 or 『』 around a phrase are a cue to do exactly this. Every line must not be one flat colour.
  * THE HOUSE PALETTE AND FINISH: saturated FLAT golden yellow, pure white and vivid red, over a thick black outline with a hard offset drop shadow and a tight coloured inner edge — punchy poster colour, high contrast, slight forward lean. Not a soft pastel wash, and not one uniform polished metallic fill across the whole headline.
  * THE STACK IS NO LONGER FLUSH — this is required, not offered. The rows step: each row is indented, offset or shifted against the one above it, so the left edges do not line up in a column.
  * EACH ROW SITS ON ITS OWN SHAPE — plates, bars or ribbons cut on the same slant or sharing one corner treatment, so the block reads as assembled parts rather than a paragraph on a rectangle.
  * MULTI-LAYER EDGES AND DEPTH ARE REQUIRED AT THIS LEVEL: stack outlines (a thick black one, then a white or coloured one outside it) and give the characters a three-dimensional extrusion with a surface picked from the story — molten metal, neon, cracked stone, wet chrome.
  * THE BLOCK ENGAGES THE PHOTOGRAPH instead of sitting in a clear corner of it: let a plate pass behind the main subject, or let the subject's silhouette break across the edge of a plate, so the title and the picture interlock. Not one character may be hidden by doing this.
  * HANG ONE OR TWO small flat pictograms on the block — a lightning bolt, a flame, a raincloud, a warning triangle, a siren — picked from what the headline is about, sitting beside or behind a word, never covering a character.
  * You still choose the typeface, the exact colours, the outline and shadow treatment, the decorative frames or shapes behind or around the words, the emphasis, the scale of each part, and where on the frame the block sits. Be bold.
- WHAT THIS CANCELS: the per-line colour labels (white / yellow / red) are only a hint you may ignore entirely — recolour freely, give one line several colours, reverse a word out of a coloured block, whatever reads best; the instruction to keep the headline in the lower-left (or lower-right) area no longer binds — place the block anywhere that composes well against the photograph; the fixed one-line-per-row stack no longer binds as a SHAPE — you may stagger the lines, indent them, run one line larger over another, or set a short line beside a long one (the lines themselves, and how many there are, are still fixed; see below). ONE EXCEPTION TO THE SIZE HIERARCHY: when the listed lines are not a hook plus its explanation but one continuous phrase, sentence or proper name simply broken across rows, keep them at ONE size — enlarging half of a single name breaks it apart.
"""

# 使用者看完 0–4 實拍梯子後：「把現在的 4 當成 3，再做一個更誇張的 4。」
# 4 = 3 的全部，再加下面這一段。加的是**幅度**（更大的落差、更多層的描邊、傾斜、
# 疊字、爆裂裝飾），不是新的自由——FIXED (a)–(g) 一樣原樣附上，而且這一級要
# 特別把「每個字仍要完整可讀、不得碰邊、不得進帶、不得跨格」再講一次：
# 幅度愈大，模型愈容易把字推到邊上或蓋掉筆畫。
_L4_EXTRA = """- GO FURTHER — THIS IS THE LOUDEST SETTING. Everything in the bullet above still applies; now push it to the edge of what still reads:
  * The shouting line towers over the rest — two and a half to three times the height of the explaining line, not the one-and-a-half of the level below — and the block as a whole is big enough to dominate the photograph.
  * DEEPEN THE EDGES FURTHER: a third outline layer outside the two required above, and an extrusion deep enough to read as a solid object standing off the photograph.
  * THE BLOCK TILTS OR ARCS — required here, not offered (a few degrees, no more than about eight) — characters step up and down instead of sitting on one baseline, and one word may overlap the next a little, but an overlap must never hide any part of any stroke.
  * Add energy behind and around the words: radiating speed lines, sparks, shards, a torn or splashed colour shape, a burst of glow. Up to THREE pictograms instead of two.
  * The photograph may darken further behind the block so all of this still reads.
  * EVEN HERE: every character stays complete, unobstructed and legible; nothing touches or is clipped by any frame edge; nothing enters the header band or the bottom strip; and in the two-panel layout nothing crosses the seam. Loud is not the same as broken.
"""

_L4 = _L3.replace("level 3 of 4 — loud)", "level 4 of 4 — loudest)") + _L4_EXTRA

COVER_AI_TITLE_LEVEL_BLOCKS = {1: _L1, 2: _L2, 3: _L3, 4: _L4}


def cover_ai_title_style_clause(level: int) -> str:
    """0＝完全不追加（現行白／黃／紅排版）；1–4 追加該級的設計條文＋不變的 FIXED 區塊。"""
    block = COVER_AI_TITLE_LEVEL_BLOCKS.get(level)
    if not block:
        return ""
    return block + _TITLE_FIXED_BLOCK


# 舊的 ON/OFF 兩檔對應到拉桿的兩端（plain=0、designed=4）。舊呼叫端與既有測試靠這個。
COVER_TITLE_STYLE_LEVELS = {
    COVER_TITLE_STYLE_PLAIN: 0,
    COVER_TITLE_STYLE_DESIGNED: COVER_AI_TITLE_LEVEL_MAX,
}

# 名字留著：第七批以前的呼叫端與測試都指名這一個常數，它就是最高級的條文。
COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE = cover_ai_title_style_clause(COVER_AI_TITLE_LEVEL_MAX)


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
- If a headline is about a specific named real person (a head of state, a politician, a celebrity), the photograph should be a portrait-style shot of that person as its subject, face towards the camera. Otherwise use anonymous figures, back views, crowds, objects or places.
- If a headline is about data, money or policy, choose a real-world scene that stands for it (a building, a counter, hands, equipment), never a graph.
- If a side's description is already supplied, repeat it back unchanged — but still list the named real people it shows.

Also return, per side, "portrait_subjects_left" / "portrait_subjects_right": every specific named real person whose face that side's photograph would show, names exactly as the headline writes them (no title, no organisation), at most three per side; an empty array when the scene shows no named real person. "portrait_subjects_left_en" / "portrait_subjects_right_en": the same people, same order, as the name Wikipedia uses in English (e.g. 梅爾茨 → "Friedrich Merz"); empty string when unsure.
"""

COVER_VISUAL_SCHEMA = {
    "type": "object",
    "properties": {
        "visual_left": {"type": "string"},
        "visual_right": {"type": "string"},
        "portrait_subjects_left": {"type": "array", "items": {"type": "string"}},
        "portrait_subjects_left_en": {"type": "array", "items": {"type": "string"}},
        "portrait_subjects_right": {"type": "array", "items": {"type": "string"}},
        "portrait_subjects_right_en": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "visual_left", "visual_right",
        "portrait_subjects_left", "portrait_subjects_left_en",
        "portrait_subjects_right", "portrait_subjects_right_en",
    ],
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
YT_COVER_LAYOUT_HOT = "hot"          # 今日熱搜（2026-09-06 型錄 H 類）：紅色系、無日期無 LIVE
YT_COVER_LAYOUTS = (YT_COVER_LAYOUT_NEWS, YT_COVER_LAYOUT_HOURLY, YT_COVER_LAYOUT_HOT)

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
# 2026-09-09 使用者：標題裡的「9/12」被當成分段，封面切出「9」與「12開放民眾參觀」。
# 斜線兩邊都是數字時就是日期／比數，不是分隔符；其餘用法（羅馬/浴場）照舊分段。
_COVER_TITLE_SPLIT_RE = re.compile(r"[ \u3000\n\r｜|]+|(?<!\d)/+|/+(?!\d)")


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
# 分成 **3 段**（每段就是封面上的一行，白／黃／紅；2026-09-08 使用者回報只出 2 段就沒有紅字、
# 或生圖階段瞎掰第三段，改成一律 3 段）。YT 直播：一句標題用一個半形空格分兩段（版型固定兩行）。
# 忠實度規則由 main.CONTENT_FIDELITY_RULES 接在後面（同主流程），標題只能用原文有的事實。
COVER_TITLE_DIGEST_SYSTEM_TEN = """You write the headlines for a Taiwanese prime-time news programme cover (十點不一樣) from one news article.

FIRST decide how many stories the article carries, and say so in "topics":
- "topics" is 1 when the whole article is about ONE event, even if it describes several aspects of it (what happened and its impact, the scene and the numbers, the cause and the response). Different angles on the same event are still one story.
- "topics" is 2 when the article carries TWO genuinely different events — different subjects, different places or different incidents that merely sit in the same article.
- Never answer 2 just because the article is long, and never merge two unrelated events into one headline.

THEN write the headlines.
- When "topics" is 1: write ONE headline into "title_left" for the core of that story, and leave "title_right" as an empty string.
- When "topics" is 2: write "title_left" for the story that appears FIRST in the article and "title_right" for the one that appears second. Keep the two headlines about their own story only — never repeat the same facts in both.
- Each headline is EXACTLY 3 segments separated by ONE half-width space (two spaces in total, never one, never three); each segment 4–7 characters, NEVER more than 7; whole headline 12–18 characters excluding spaces (fewer than 12 leaves the cover half empty — that is a defect). Each segment becomes one printed line, coloured white / yellow / red in order, so a headline with only two segments loses its red line — that is a defect. A segment longer than 7 characters shrinks every line on the cover — also a defect.
- No punctuation, no quotation marks, no emoji, no English unless it is a proper name in the source.
- Traditional Chinese only (Taiwan usage). Never Simplified forms.
"""

# 十點不一樣（滿版）：只有一個標題，一律 3 段（每段一行，白／黃／紅）。
COVER_TITLE_DIGEST_SYSTEM_TEN_FULL = """You write the single headline for a Taiwanese prime-time news programme cover (十點不一樣, full-bleed single-photo layout) from one news article.

Return JSON with "title".
- One punchy Traditional Chinese (Taiwan) headline for the core of the story.
- EXACTLY 3 segments separated by ONE half-width space (two spaces in total, never one, never three); each segment 4–7 characters, NEVER more than 7; whole headline 12–18 characters excluding spaces (fewer than 12 leaves the cover half empty — that is a defect). Each segment becomes one printed line, coloured white / yellow / red in order, so a headline with only two segments loses its red line — that is a defect.
- No punctuation, no quotation marks, no emoji, no English unless it is a proper name in the source.
- Traditional Chinese only (Taiwan usage). Never Simplified forms.
"""

COVER_TITLE_DIGEST_SYSTEM_YT = """You write the headline for a Taiwanese TV news live-stream thumbnail from one news article.

Return JSON with "title".
- One Traditional Chinese (Taiwan) headline made of exactly TWO segments separated by ONE half-width space; each segment 5–12 characters. The two segments are printed as two lines: the first states the event, the second the key detail or consequence.
- No punctuation, no quotation marks, no emoji, no English unless it is a proper name in the source.
- Traditional Chinese only (Taiwan usage). Never Simplified forms.
"""

TEN_DIGEST_SEGMENT_MIN = 4
TEN_DIGEST_SEGMENT_MAX = 7
TEN_DIGEST_TOTAL_MIN = 12
TEN_DIGEST_TOTAL_MAX = 18


def ten_digest_violations(data: dict | None) -> list[str]:
    """十點消化標題的三段規格驗證：每段 4–7 字、全篇 12–18 字（不含空白）、剛好 3 段。

    回違規描述清單（空＝合格）。同時看 title_left／title_right（雙切）與 title（滿版）。
    """
    if not isinstance(data, dict):
        return ["not a JSON object"]
    problems = []
    for key in ("title_left", "title_right", "title"):
        text = str(data.get(key) or "").strip()
        if not text:
            continue
        segments = [seg for seg in split_cover_title(text) if seg.strip()]
        total = sum(len(seg) for seg in segments)
        if len(segments) != 3:
            problems.append(f'"{key}" has {len(segments)} segments, must be exactly 3')
        for seg in segments:
            if not TEN_DIGEST_SEGMENT_MIN <= len(seg) <= TEN_DIGEST_SEGMENT_MAX:
                problems.append(f'"{key}" segment 「{seg}」 is {len(seg)} characters, must be {TEN_DIGEST_SEGMENT_MIN}–{TEN_DIGEST_SEGMENT_MAX}')
        if not TEN_DIGEST_TOTAL_MIN <= total <= TEN_DIGEST_TOTAL_MAX:
            problems.append(f'"{key}" is {total} characters excluding spaces, must be {TEN_DIGEST_TOTAL_MIN}–{TEN_DIGEST_TOTAL_MAX}')
    return problems


def ten_digest_retry_note(data: dict | None) -> str:
    """重問時附在 system prompt 後面的違規說明。"""
    lines = "\n".join(f"- {item}" for item in ten_digest_violations(data))
    return ("YOUR PREVIOUS ANSWER BROKE THESE RULES — rewrite the headline(s) so every rule holds:\n"
            + lines + "\nCount the characters of each segment before you answer.")


COVER_TITLE_DIGEST_SCHEMA_TEN = {
    "type": "object",
    "properties": {
        # strict schema 下每個屬性都得列進 required，所以「單主題」是用 title_right
        # 回空字串表達，不是把欄位省略掉。
        "topics": {"type": "integer", "enum": [1, 2]},
        "title_left": {"type": "string"},
        "title_right": {"type": "string"},
    },
    "required": ["topics", "title_left", "title_right"],
    "additionalProperties": False,
}
# YT 直播「直標」（2026-09-09 使用者：貼一段文字 → 自動生兩段標題＋判定來源）。
#
# 與其他封面的差別有三個，都寫進條文裡：
# 1. 版面是**兩行直排**，字數上限照「格數」算不是字元數（連續英數字併成一格，
#    見 compose._vertical_cells）。上限直接由 compose 的常數帶進來，不手抄。
# 2. 使用者貼的常常是外電通稿（英文 slug ＋ 場次 ＋ Restrictions），要翻成繁中。
# 3. 來源要自己判：外電通稿的版權方寫在 Must credit／Restrictions 那幾行。
#    只回來源名，「畫面來源：」由 compose.vstrip_source_text 自動補，不要自己寫。
VSTRIP_TITLE_DIGEST_SYSTEM = """You write the two-line vertical caption strip (直標) for a Taiwanese TV news live stream, from whatever the editor pasted in.

The pasted text is often a raw foreign wire despatch: an English slug line, a one-paragraph description, an audio note, a scheduled time, a dateline, an item number, and a restrictions note. It may equally be a Chinese news article. Read whichever it is and work from the facts in it.

Return JSON with "title", "title_second" and "source".

THE TWO TITLES
- "title" is the upper (main) line and "title_second" the lower (sub) line. Both are Traditional Chinese, Taiwan usage and Taiwan terminology. Never Simplified forms, never Japanese forms.
- They are ONE caption read top to bottom, not two separate headlines: "title" states WHAT is happening or WHO is involved, and "title_second" adds the detail that makes it newsworthy — where, when, what was said, what the consequence is. The second line must not repeat the first.
- Length is counted in PRINTED CELLS, not characters: every Chinese character is one cell, a run of consecutive digits or Latin letters is ONE cell together (「30」is one cell, not two), and spaces take no cell at all. "title" must be at most {main_max} cells and "title_second" at most {sub_max} cells. Aim a little under those limits — a line at the limit fills the whole height of the frame.
- No punctuation at the end of either line. Inside a line use only 「」 if you must quote; no commas, no full stops, no emoji.
- Use only facts that are in the pasted text. Never add a figure, a date, a place or a claim that is not there. If the material is thin, write a shorter caption rather than inventing detail.

THE SOURCE
- "source" is the party whose footage this is, written the way it is credited on air, in Traditional Chinese where a standard Taiwanese rendering exists and otherwise in its own language.
- Take it from an explicit credit requirement first — a line such as "Must credit X", "Mandatory credit: X", or a restrictions note naming X. That is the answer whenever it appears.
- If there is no credit requirement, use the wire agency or broadcaster that the material names as the supplier. If neither is named anywhere, return an empty string rather than guessing: the editor will fill it in.
- Write ONLY the name. Do NOT write 「畫面來源」, 「來源」, a colon, or any other prefix — the program adds that itself.
"""

VSTRIP_TITLE_DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "title_second": {"type": "string"},
        "source": {"type": "string"},
    },
    "required": ["title", "title_second", "source"],
    "additionalProperties": False,
}


def vstrip_title_digest_system(main_max: int, sub_max: int) -> str:
    """格數上限由 compose 的常數帶進來——手抄一份遲早跟版面對不上。"""
    return VSTRIP_TITLE_DIGEST_SYSTEM.format(main_max=main_max, sub_max=sub_max)


COVER_TITLE_DIGEST_SCHEMA_YT = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}

# YT 整點直播「雙則」（2026-09-08 WP2）：整點封面常常一次帶兩則新聞，版面是
# **同一張底圖、上下兩行標題**（上白＝第一則、下黃＝第二則），每一行就是一則新聞的
# 完整標題，不是同一句拆兩段。所以消化這一步要先判定內文是 1 個還是 2 個主題——
# 判定那一段與十點逐字相同，差別只在標題長什麼樣。
COVER_TITLE_DIGEST_SYSTEM_YT_HOURLY = """You write the headlines for a Taiwanese TV news hourly live-stream thumbnail from one news article.

FIRST decide how many stories the article carries, and say so in "topics":
- "topics" is 1 when the whole article is about ONE event, even if it describes several aspects of it (what happened and its impact, the scene and the numbers, the cause and the response). Different angles on the same event are still one story.
- "topics" is 2 when the article carries TWO genuinely different events — different subjects, different places or different incidents that merely sit in the same article.
- Never answer 2 just because the article is long, and never merge two unrelated events into one headline.

THEN write the headlines.
- When "topics" is 1: write ONE headline into "title" and leave "title_second" as an empty string. That headline is made of exactly TWO segments separated by ONE half-width space, each segment 5–12 characters; the two segments are printed as two lines, the first stating the event and the second the key detail or consequence.
- When "topics" is 2: write "title" for the story that appears FIRST in the article and "title_second" for the one that appears second. Each of the two is ONE continuous headline printed as ONE full-width line, so it carries NO space at all and must be at most 18 characters. Keep each headline about its own story only — never repeat the same facts in both.
- No punctuation, no quotation marks, no emoji, no English unless it is a proper name in the source.
- Traditional Chinese only (Taiwan usage). Never Simplified forms.
"""

COVER_TITLE_DIGEST_SCHEMA_YT_HOURLY = {
    "type": "object",
    "properties": {
        # 同十點：strict schema 下每個屬性都要列進 required，單主題是用 title_second
        # 回空字串表達，不是把欄位省略掉。
        "topics": {"type": "integer", "enum": [1, 2]},
        "title": {"type": "string"},
        "title_second": {"type": "string"},
    },
    "required": ["topics", "title", "title_second"],
    "additionalProperties": False,
}


def yt_cover_is_dual(layout: str, title_second: str) -> bool:
    """這一次的 YT 封面是不是整點「雙則」（一張封面帶兩則新聞）。

    2026-09-08 使用者裁決：判定只有一條規則——整點版型＋第二標題有值＝雙則。
    國內外新聞直播與今日熱搜沒有這個版面，帶了第二標題也忽略。
    """
    return layout == YT_COVER_LAYOUT_HOURLY and bool((title_second or "").strip())


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

# 底部壓色框開關（2026-09-08 使用者裁決；同日晚改預設 ON）。合成版由 compose 的 bottom_band
# 決定畫不畫，AI 版只能靠 prompt——所以 LAYOUT 的第一條與 IMAGERY 的結尾都要換句話說，
# 不然模型看到「filling the frame behind the band」還是會自己畫一條帶子出來。
# 開的時候明講「半透明約六成」，與合成版的 compose.YT_BAND_ALPHA=153 對齊。
#
# 2026-09-09 使用者回報：合成版早就修過（框高不超過標題第二行、而且半透明），AI 版
# 的框還是又高又不透明。根因就在這兩條——寫的是「lower 40%」，而合成版的框上緣是
# compose.YT_BAND_TOP_RATIO=0.778，只佔畫面下方 22%，差了將近一倍。改寫成**關係式**
# 描述（框只在下面那一行字後面，上緣從第一行的基線淡入）：模型跟得動「behind the
# lower line」，跟不動百分比；比例留著但改成正確的值，只當輔助。
#
# 2026-09-09（第三批）實測：上面那版改寫還是沒用，成品的框仍從畫面 58% 高度起跳、
# 兩行字都蓋進去。根因是模板本身——這一條的**下一行**寫著標題「in the lower 40% of
# the frame」，模型把那個 40% 拿去撐色框；而且色框條排在標題條**前面**，照這個 repo
# 的慣例（位置在後＋明文 OVERRIDE 才贏）等於被後面的數字壓過去。
# 兩件事一起改：把 {band_clause} 移到標題那一條之後，並在條文裡明說 40% 是給文字塊
# 的、不是給色框的，框高改用「兩行標題塊的一半」這種相對量描述。
#
# 2026-09-09（第四批）使用者：還是太高，要壓到第二段黃字標題。第三批把百分比整個
# 拿掉、只留關係式描述，模型手上就只剩上面那個 40% 可抄。這一版把合成版的真實數字
# （compose.YT_BAND_TOP_RATIO=0.778 → 只佔下方 22%）明寫回去，數字與關係式並存，
# 並點名是「白字的基線」「黃字的上緣」——顏色比行序具體，模型跟得動。
# 同一批另修兩行標字級：模板要求每一行 filling almost the full width，字少的那一行
# 就被放大去撐滿，兩行大小差一截。改成「共用一個字級、由較長那行決定」。
_BAND_CLAUSE_TEMPLATE = (
    "- THE COLOUR BAND — TAKE THE NUMBER FROM THIS BULLET, NOT FROM THE 「lower 40%」 FIGURE ABOVE "
    "(that figure sizes the TEXT BLOCK and says nothing about the band): a translucent {colour} band "
    "with a subtle {texture} texture lies along the BOTTOM EDGE of the frame. ITS TOP EDGE IS AT {top}% "
    "OF THE FRAME HEIGHT MEASURED DOWN FROM THE TOP, so the band covers ONLY THE BOTTOM {rest}% of the "
    "picture and nothing above that line. Concretely: the top edge is a soft fade running level with "
    "the BASELINE (the feet) of the WHITE upper headline line, so the whole white line stands on the "
    "bare photograph with no band behind it, and the band reaches full strength just above the top of "
    "the GOLDEN YELLOW lower line, then runs to the bottom edge. It is a shallow strip about one fifth "
    "of the picture: NOT a panel over the lower third, NOT the lower 40%, NOT half the frame. It is "
    "translucent (about 60% opaque): the photograph stays clearly visible through it."
)
# 2026-09-09：百分比改成從 compose 的常數算，不再手抄。合成版的框一調（這批 0.778→0.770），
# 抄在 prompt 裡的數字就會過期，而第三批的教訓正是「模型手上有什麼數字就抄什麼」。
_BAND_TOP_PERCENT = round(compose.YT_BAND_TOP_RATIO * 100)
YT_COVER_BAND_CLAUSE_NEWS_ON = _BAND_CLAUSE_TEMPLATE.format(
    colour="deep-navy", texture="circuit-board / tech-block",
    top=_BAND_TOP_PERCENT, rest=100 - _BAND_TOP_PERCENT,
)
YT_COVER_BAND_CLAUSE_HOT_ON = _BAND_CLAUSE_TEMPLATE.format(
    colour="DEEP CRIMSON / near-black", texture="red circuit-board / tech-block",
    top=_BAND_TOP_PERCENT, rest=100 - _BAND_TOP_PERCENT,
)
YT_COVER_BAND_CLAUSE_OFF = "- There is NO solid colour band, panel or strip behind the headline: the photograph runs uninterrupted to the bottom edge and stays fully visible. The headline's readability comes from its thick outline and drop shadow alone."
YT_COVER_BAND_IMAGERY_TAIL_ON = " behind the band"
YT_COVER_BAND_IMAGERY_TAIL_OFF = ""


def yt_cover_band_fields(layout: str, bottom_band: bool) -> dict:
    """AI 標題模板的底帶兩個欄位。整點版沒有底帶，兩個欄位都用不到（模板裡沒有這兩個佔位）。"""
    if bottom_band:
        clause = YT_COVER_BAND_CLAUSE_HOT_ON if layout == YT_COVER_LAYOUT_HOT else YT_COVER_BAND_CLAUSE_NEWS_ON
        return {"band_clause": clause, "band_imagery_tail": YT_COVER_BAND_IMAGERY_TAIL_ON}
    return {"band_clause": YT_COVER_BAND_CLAUSE_OFF, "band_imagery_tail": YT_COVER_BAND_IMAGERY_TAIL_OFF}


YT_COVER_FULL_PROMPT_NEWS = """Design a complete Taiwanese TV news LIVE-stream thumbnail (YouTube cover), 16:9.

=== TEXT TO RENDER (Traditional Chinese, Taiwan) ===
Render EXACTLY these strings, character for character, nothing else:
- Headline line 1 (upper line): {line1}
- Headline line 2 (lower line): {line2}

=== LAYOUT ===
- Both headline lines are CENTRED horizontally in the lower 40% of the frame, stacked, each on one line, in heavy black-weight (weight, not colour) Chinese display type, with TIGHT LEADING so the two lines sit close together as one block. Keep the strokes clean and separated — the counters (the enclosed white spaces inside characters) must stay open; do not thicken the type until the strokes merge.
- THE TWO HEADLINE LINES ARE SET AT ONE SINGLE TYPE SIZE: identical cap height, identical stroke weight, identical character width. Choose that size from the LONGER line — it is the size at which the LONGER line spans almost the full width — then set the SHORTER line at that SAME size, so the shorter line simply comes out narrower and sits centred with empty space at both ends. NEVER enlarge the shorter line to make it reach the same width as the other one. A line with far fewer characters MUST end up visibly shorter, never bigger; two lines at different type sizes is a defect.
{band_clause}
- Line 1: solid white. Line 2: bright golden yellow. Both with a thick black outline. Flat type: no gradient, no metallic, no 3-D.
- Keep the UPPER-LEFT corner (a block about 24% wide and 40% tall) completely free of text or busy detail: a red LIVE badge and a date tab are pasted there afterwards.
- Keep the UPPER-RIGHT corner (a block about 20% wide and 16% tall) completely free: a channel logo tab is pasted there afterwards.

=== IMAGERY ===
{visual}
Photographic, dramatically lit, news-documentary quality, filling the frame{band_imagery_tail}.

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
- Both headline lines sit in the lower third, LEFT-ALIGNED near the left edge, stacked, each on one line, huge and heavy Chinese display type. No band behind them: the type sits directly on the photograph.
- THE TWO HEADLINE LINES ARE SET AT ONE SINGLE TYPE SIZE: identical cap height, identical stroke weight, identical character width. Choose that size from the LONGER line — it is the size at which the LONGER line spans almost the full width — then set the SHORTER line at that SAME size, so the shorter line simply ends earlier and leaves empty space to its right. NEVER enlarge the shorter line to make it reach the same width as the other one. A line with far fewer characters MUST end up visibly shorter, never bigger; two lines at different type sizes is a defect.
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

YT_COVER_FULL_PROMPT_HOT = """Design a complete Taiwanese TV news "trending topics" thumbnail (YouTube cover), 16:9. It is NOT a live stream: no date, no time, no LIVE word.

=== TEXT TO RENDER (Traditional Chinese, Taiwan) ===
Render EXACTLY these strings, character for character, nothing else:
- Headline line 1 (upper line): {line1}
- Headline line 2 (lower line): {line2}

=== LAYOUT ===
- Both headline lines are CENTRED horizontally in the lower 40% of the frame, stacked, each on one line, in heavy black-weight (weight, not colour) Chinese display type, with TIGHT LEADING so the two lines sit close together as one block. Keep the strokes clean and separated — the counters (the enclosed white spaces inside characters) must stay open; do not thicken the type until the strokes merge.
- THE TWO HEADLINE LINES ARE SET AT ONE SINGLE TYPE SIZE: identical cap height, identical stroke weight, identical character width. Choose that size from the LONGER line — it is the size at which the LONGER line spans almost the full width — then set the SHORTER line at that SAME size, so the shorter line simply comes out narrower and sits centred with empty space at both ends. NEVER enlarge the shorter line to make it reach the same width as the other one. A line with far fewer characters MUST end up visibly shorter, never bigger; two lines at different type sizes is a defect.
{band_clause}
- Line 1: solid white. Line 2: bright golden yellow. Both with a thick black outline. Flat type: no gradient, no metallic, no 3-D.
- Keep the UPPER-LEFT corner (a block about 30% wide and 16% tall) completely free of text or busy detail: a red-and-white "trending" tag is pasted there afterwards.
- Keep the UPPER-RIGHT corner (a block about 20% wide and 16% tall) completely free: a red channel logo tab is pasted there afterwards.
- Keep the very top edge free: a thin red strip is pasted along it afterwards.

=== IMAGERY ===
{visual}
Photographic, news-documentary quality, filling the frame{band_imagery_tail}.

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
    # 2026-09-08 使用者裁決（WP1）：左切／右切合併成一個版型，挖空方向改由請求欄位
    # hole_side 決定（前端是版型下方一組按鈕）。表裡的 hole_side 是**預設值**，
    # hole_side_from_request 才是「這個版型允許請求覆寫方向」的開關——舊別名沒有這個
    # 旗標，所以 LINE／WorkCord 送 broadcast_right 而不帶欄位時方向不會被翻成左。
    "broadcast": {
        "label": "播出鏡面",
        "pipeline": PIPELINE_GENERATE,
        "digest_rules": _broadcast_rules("left"),
        "hole_side": "left",
        "hole_side_from_request": True,
    },
    # 十點不一樣封面：ai／composite 兩種模式並存，由前端「標題由 AI 生成」勾選框切換
    # （2026-09-06 使用者裁決比照 YT 直播封面，不再拆成兩個下拉項目）。
    # cover_mode 是預設值；實際模式由 TenCoverRequest.mode 決定。
    # 2026-09-08 使用者裁決（WP1）：滿版／雙切也合併成一個版型，版面由「第二標題有沒有
    # 值」自動判定（TenCoverRequest.layout 留空時；明示 layout 仍以請求為準），
    # 所以這裡的 cover_layout 是 "auto"，不再是固定的 split／full。
    "ten_cover": {
        "label": "十點不一樣",
        "pipeline": PIPELINE_COVER,
        "cover_mode": COVER_MODE_AI,
        "cover_layout": COVER_LAYOUT_AUTO,
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
    # YT 直播直標（2026-09-08 WP3）：不是封面，是疊在直播訊號上的透明底 PNG。
    # 沒有底圖、沒有生圖、沒有 AI——所有東西由 compose.compose_yt_overlay 畫。
    # 2026-09-09 使用者：下拉往上移一格排在「國內外新聞直播」後面，標籤前面加全形減號
    # 「－」，跟真正的封面版型在視覺上分開（它不生封面）。
    "yt_vstrip": {
        "label": "－YT直播直標",
        "pipeline": PIPELINE_YT_OVERLAY,
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
    # YT 今日熱搜：同一條底圖流程，版面換成 compose.compose_yt_hot_cover（無日期無 LIVE）
    "yt_hot_cover": {
        "label": "YT今日熱搜",
        "pipeline": PIPELINE_YT_COVER,
        "yt_layout": YT_COVER_LAYOUT_HOT,
        "digest_rules": "",
        "hole_side": None,
    },
}

EDITOR_FORMAT_KEYS = tuple(EDITOR_FORMATS)


# 舊 key 的別名（2026-09-08 WP1 合併留下的相容層）。前端下拉不再列出這三個，但
# LINE／WorkCord、舊的請求紀錄與既有測試仍會送過來，所以後端照舊解析得出來、行為
# 逐字元不變：兩個播出鏡面別名各自釘死一側（不吃請求的 hole_side），
# ten_cover_full 等同 ten_cover＋layout=full。
EDITOR_FORMAT_ALIASES = {
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
    "ten_cover_full": {
        "label": "十點不一樣（滿版）",
        "pipeline": PIPELINE_COVER,
        "cover_mode": COVER_MODE_AI,
        "cover_layout": COVER_LAYOUT_FULL,
        "digest_rules": "",
        "hole_side": None,
    },
}

EDITOR_FORMAT_ALIAS_KEYS = tuple(EDITOR_FORMAT_ALIASES)


def get(key: str | None) -> dict:
    """取版型定義；未知或空值一律退回 default（呼叫端不用自己判空）。

    先查正式表，再查別名表——別名是完整的一筆定義，不是薄指標，所以
    `get("broadcast_left")["digest_rules"]` 這種既有寫法照樣拿得到東西。
    """
    name = key or DEFAULT_FORMAT
    if name in EDITOR_FORMATS:
        return EDITOR_FORMATS[name]
    return EDITOR_FORMAT_ALIASES.get(name, EDITOR_FORMATS[DEFAULT_FORMAT])


def resolve_hole_side(key: str | None, side: str | None = None) -> str | None:
    """這一次生成實際要挖哪一側。

    沒有挖空側的版型一律 None。有的版型：允許請求覆寫（新的 broadcast）時才看
    `side`，且只認 left／right；別名與其他情況一律用表裡釘死的那一側。
    """
    fmt = get(key)
    base = fmt.get("hole_side")
    if not base:
        return None
    if fmt.get("hole_side_from_request") and side in HOLE_SIDES:
        return side
    return base


def digest_rules(
    key: str | None,
    role: str,
    stamp: bool | None = None,
    density: str | None = None,
    side: str | None = None,
) -> str:
    """消化階段要注入的規則。非編輯角色一律空字串——第三層防呆。

    stamp 與 density 都只影響播出鏡面：stamp False 時第 5／6 條換成「沒有蓋章」版本；
    density 為 "standard"（字多）或 "maximum"（字超多）時第 6 條加一段「每卡兩行」。其餘版型兩者都不看。
    side 同樣只有播出鏡面在看，而且只有新的 broadcast 版型吃得到（見 resolve_hole_side）：
    消化端要把內容趕到挖空側的另外半邊，方向講錯的話整張圖的重點會被影片蓋掉。
    播出鏡面一律現算——stamp 沒表態且非字多時，算出來跟預先算好的那份逐字元相同。
    """
    if role != "編輯":
        return ""
    resolved = resolve_hole_side(key, side)
    if resolved:
        return _broadcast_rules(resolved, stamp=stamp, density=density)
    return get(key)["digest_rules"]


def cover_layout(key: str | None) -> str:
    """十點封面的版面：auto＝依第二標題自動判定、full＝滿版；不是十點封面時回空字串。"""
    return get(key).get("cover_layout", "")


def resolve_cover_layout(layout: str | None, title_right: str) -> str:
    """十點封面這一次是滿版還是雙切。

    2026-09-08 使用者裁決：兩個版型合併，改由「第二標題有沒有值」判定——有＝雙切、
    空＝滿版。請求明示 layout（舊呼叫端、ten_cover_full 別名）時仍以請求為準。
    """
    if layout in COVER_LAYOUTS:
        return layout
    return COVER_LAYOUT_SPLIT if (title_right or "").strip() else COVER_LAYOUT_FULL


def cover_mode(key: str | None) -> str:
    """封面走哪一種做法；不是封面版型時回空字串。"""
    return get(key).get("cover_mode", "")


def hole_side(key: str | None, role: str, side: str | None = None) -> str | None:
    if role != "編輯":
        return None
    return resolve_hole_side(key, side)
