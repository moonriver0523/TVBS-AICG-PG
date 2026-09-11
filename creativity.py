"""三處創意拉桿共用的「拉桿不准碰的東西」（FIXED 段）。

網站上有三處創意拉桿，各自帶一段這種條文：
- CG（main.cg_creativity_rules）：記者／編輯播出鏡面，注入消化 prompt。
- 十點不一樣（editor_formats.cover_ai_title_style_clause）：注入生圖 prompt。
- YT 三版型（editor_formats.yt_fixed_block）：注入生圖 prompt，2026-09-11 才長出來，
  措辭是從十點那套手動抄改的——抄漏、抄歪都不會報錯，只會讓某個版型悄悄鬆綁。

這支模組把持有權收進來，用 target 分兩種：

- target="digest"：CG 那一段，(a)–(i) 九條。**逐字元原封不動**地從 main.py
  搬過來，不做任何拆解或重寫。理由：tests/test_reporter_prompt_frozen.py
  把記者 prompt 的位元組釘死，(a)(d)(e)(f) 這些項次字母本身就是位元組的
  一部分，抽走幾條再重新編號就會紅。（現況記者用 visual_creativity=0，這段
  其實進不了凍結快照，但仍然照「搬家不拆解」的約束處理，不因為測試沒蓋到
  就放寬。）
- target="image"：十點與 YT 共用的那幾條——字句逐字、繁體臺灣用字、不准
  生新字、不准觸邊。以十點的措辭為準（十點先上線、經過 2026-09-10 實拍
  調校；YT 那套是照抄改寫的，沒驗證過）。版型專屬的條目（十點的標頭帶／
  雙欄縫線，YT 的日期牌／保留角落）留在各自呼叫端自己接的字串上，不搬
  進這裡——跨 target 共用的是「結構」（兩個 target 各自組出一段完整條文），
  target 內共用的才是「文字」。

  「不准生新字」這一條，兩邊的既有測試各自釘死不同大小寫的措辭：
  tests/test_cover_title_creativity.py 釘 "No text of any kind other than
  the listed strings"，tests/test_yt_hourly_creativity_20260911.py 釘
  "NO NEW TEXT OF ANY KIND"。兩份測試都不歸這次重構動，所以共用文字兩句
  都留——多一句不影響語意，卻讓兩邊的字面釘死同時滿足，出處仍然只有一份。

  這段**刻意不編號**（不寫 (a)(b)(c)…）。第一版寫過編號，結果 YT hourly 版
  出現兩個 (b)：yt_fixed_block 依 layout 會整條抽掉日期那句（news／hot 沒有
  日期牌），但日期句留在呼叫端自己的字串裡、編號卻是共用段接續下來的，
  一抽就對不上——標號在「其中一條會被版型抽掉」的情境下本來就無法跨版型
  穩定，維持編號等於維持一個註定會歪掉的東西。改成連續句子後，各呼叫端
  接自己的版型專屬句子時也不用煩惱編號銜接。

風險提醒（見 docs/plan-20260911-創意拉桿模組化.md 風險 3）：這支檔案只管
「拉桿不准碰的東西」，不管拉桿本身要調的版面尺寸——不准在這裡出現任何
百分比或像素數字，那些數字屬於各自呼叫端的 DESIGN BRIEF，抽走會連號碼
一起被抽掉。
"""

# ============================================================
# 等級名稱：CG／十點共用（main.CG_CREATIVITY_LEVEL_NAMES、
# editor_formats.COVER_AI_TITLE_LEVEL_NAMES 兩份手寫字典，值逐字相同，
# P2 收進這裡當單一真相源；YT 那條拉桿沒有中文名稱、不歸這裡管）。
# 兩邊呼叫端改成指向本字典的別名，不改呼叫端寫法，避免動到既有引用點。
# ============================================================
LEVEL_MIN = 0
LEVEL_MAX = 4
LEVEL_NAMES = {
    0: "規矩",
    1: "微設計",
    2: "有設計",
    3: "奔放",
    4: "最狂",
}


# ============================================================
# target="digest"（main.cg_creativity_rules，CG 播出鏡面／記者版）
# ============================================================
_DIGEST_FIXED = """
WHAT THE CREATIVITY SETTING NEVER CHANGES — THIS PARAGRAPH OUTRANKS THE ONE ABOVE IT:
(a) THE WORDS. The creativity setting styles the text; it never rewrites it. Do not add, drop, translate, shorten or reorder a single character to make a design work, and never invent a figure, a label, a caption, a unit or a source line for the sake of the layout.
(b) THE POINT COUNT AND THE LINE STRUCTURE stay exactly as the blocks above set them. If a block above fixes an exact number of [內文小標] lines, that number still holds. Design freedom is not permission to add a card, drop a card or merge two points.
(c) THE BROADCAST SAFE AREA stays exactly as instructed above, including the sentence the structure description must begin with, the ban on expressing any position or size as a number, and the ban on anything spanning or touching an edge.
(d) NO NEW TEXT OF ANY KIND. Decorative marks are wordless: no letters, no digits, no invented badges, no watermark, no signature, no extra labels. Icons carry no writing.
(e) EVERY CHARACTER STAYS COMPLETE, UNOBSTRUCTED AND LEGIBLE at broadcast distance. A decoration that crosses a stroke, a shadow that swallows a stroke, or type squeezed until the counters close, is a defect — not a style.
(f) Traditional Chinese, Taiwan forms throughout.
(g) A HERO ELEMENT IS NEVER A MAP OF REAL GEOGRAPHY UNLESS THE CHART TYPE IS THE MAP TYPE. The levels above invite you to pick one dominant subject image; a map is not available for that job here. Do not ask for a national or regional outline with internal county, state or district boundaries, and do not ask for one place to be highlighted inside another — the renderer draws those borders from memory and gets them wrong, which is a factual error on air, not a styling flaw. Where the story is about places, a wordless silhouette with no internal divisions, or a schematic locator described plainly as schematic, is the most this setting allows.
(h) THESE LEVERS ADAPT TO THE POINT COUNT THE BLOCKS ABOVE SET — THEY NEVER CREATE MATERIAL TO FEED THEMSELVES. If a block above fixed the graphic at ONE point, the hero element simply IS the graphic: every instruction here about supporting cards, stepped rows, a grid to break, or material on the other side of a dividing edge does not apply, and the empty space stays empty. If a block above raised the count to six or more, grouping and legibility outrank the arrangement instructions here: keep the groups or columns that block asked for, and apply the slant, the stagger or the overlap only as far as every line still reads at broadcast distance.
(i) IF A LEVER CANNOT BE SATISFIED WITHOUT ADDING WORDS, THE LEVER LOSES. Never invent a banner line, a warning strip, a slogan, a caption or a repeated phrase to fill a zone, balance a composition or complete a shape — an empty area is always the correct answer, and a design that needs new text to work is the wrong design.
"""

# ============================================================
# target="image"（十點不一樣 / YT 三版型共用）
# ============================================================
# 四條語意完全重疊的條文，以十點的措辭為準；YT 的既有測試釘住的兩句大小寫
# 不同的「不准生新字」措辭都保留，見檔頭說明。不編號（理由同上），但四條
# 之間用換行分隔——(a)(b)(c)(d) 這種標號原本兼職分隔符，拿掉標號時如果連
# 換行一起拿掉，四條會糊成一段沒有分界的長句，正好撞上這個 repo 記過的病灶：
# 「排除條文埋在一長串否定句中間，模型會照樣犯」（見 commit 73ae198）。
# 換行不是編號，不會在 yt_fixed_block 依 layout 抽掉某一條時留下編號斷層。
_IMAGE_FIXED = (
    "THE CHARACTERS. Render the listed strings character for character in"
    " the listed order — never add, drop, translate, abbreviate, reorder or"
    " substitute a single character to make a layout work, and never break a"
    " listed line in the middle: a listed line is one unbroken unit, so a date"
    " or score written with a slash such as 9/12 stays whole on one row.\n"
    "Traditional Chinese, Taiwan forms, every character correctly formed"
    " and legible — no Simplified or Japanese forms, no invented strokes.\n"
    "NO NEW TEXT OF ANY KIND. No text of any kind other than the listed"
    " strings: decorative marks you add are wordless symbols only — no"
    " letters, no digits, no country names, no place labels, no flag chips,"
    " no map insets, no extra badges or callouts.\n"
    "Nothing touches or is clipped by the frame edge."
)


def fixed_block(*, target: str) -> str:
    """回傳指定 target 的共用 FIXED 條文。

    target="digest"：CG 播出鏡面／記者版，九條，逐字元原封不動。
    target="image"：十點／YT 共用的那四條；版型專屬的條目不在這裡，
    由呼叫端自己接在前後（見 editor_formats._TITLE_FIXED_BLOCK /
    _YT_FIXED_BLOCK 怎麼拼）。
    """
    if target == "digest":
        return _DIGEST_FIXED
    if target == "image":
        return _IMAGE_FIXED
    raise ValueError(f"creativity.fixed_block: 未知的 target {target!r}")
