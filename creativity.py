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

  2026-09-11 第十批（國旗）：「no flag chips」原本是全面禁令，這裡**就地改寫**成
  同時帶禁令與界線的一句，不在別處加例外——這個 repo 記過三次「矛盾靠後面覆蓋、
  模型挑最寬鬆那句遵守」的病灶（見 commit 73ae198 等）。保留的判準跟 (g) 的地圖
  禁令同一個道理：AI 憑記憶重畫一面旗，條紋比例／色帶順序／徽記畫錯是事實錯誤，
  不是風格問題。放開的只有「照片裡本來就有的那面旗」——那不是模型畫的，是它本來
  就在畫面裡的東西，裁下來當設計元素不會有畫錯的風險。真的要用這面旗當招式時，
  走的是 COVER_ACCESSORY_POOL 的 flag 條目（見下方），不是靠這裡鬆綁就自動生效——
  那個招式池條目是**確定性換入**，不進隨機抽籤，見 editor_formats.cover_accessories
  的 visuals 參數與註解。

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
import random
from dataclasses import dataclass, field

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
# 變化池與抽籤：十點不一樣／YT 三版型共用（P3，2026-09-11）
# ============================================================
# 池子與抽籤原本各寫在 editor_formats.cover_design_brief／yt_design_brief 裡，
# 兩邊各自 `random.Random(seed)` 依固定順序抽——十點抽 6 顆（多一顆 anchor），
# YT 抽 5 顆。這裡把池子本身、跟兩邊共用的那段抽籤順序收進來，YT 這一輪
# 仍然不接（見下方 draw() 說明），只是先把介面留對。
#
# 池子每一池都只描述**形狀或做法**，不帶數字（延續「招式不宣稱數字」那條），
# 而且每一條都是命令句：模型讀到的是「就是這個」，不是「你可以選」。
# 幅度（塊高％／落差倍數／招式件數／反白字數）不在池子裡——那是各拉桿自己的
# 梯子，數字留在 editor_formats（風險 3：這支模組原始碼不准出現版面尺寸數字，
# 見 tests/test_creativity_module_20260911.py 的 NoLayoutNumbersInSharedModuleTests）。

# 底板形狀。原本只有「每行各自一塊板」，形狀交給模型 → 每次都是同一種圓角矩形。
COVER_PLATE_SHAPES: tuple[str, ...] = (
    "square-cut, hard right angles",
    "fully rounded, pill-ended",
    "clipped across one corner",
    "slanted into parallelograms",
    "torn-edged, like strips ripped out of paper",
    "painted brush strokes with ragged ends",
    "ribbons with folded-back ends",
    "open bracket frames, outline only, the photograph showing through",
)

# 錯位方式。原本只寫「錯開」，模型一律交同一種左階梯。
COVER_STAGGER_PATTERNS: tuple[str, ...] = (
    "each row stepped further right than the one above",
    "each row stepped further left than the one above",
    "alternating left and right, a zig-zag down the block",
    "the middle row pushed out well past the others",
    "a short row set beside the end of a long one",
)

# 字體個性。只描述字形骨架，不給字體名——給名字模型會拿英文字體來套。
# 每一條都要能用中文黑體體系畫得出來，而且可讀性是硬底線。
COVER_TYPEFACES: tuple[str, ...] = (
    "a heavy rounded gothic, thick strokes with softened corners",
    "a tall condensed gothic, narrow and vertical",
    "a wide poster gothic, squat and square-shouldered",
    "a heavy Ming with thick slab serifs and sharp entry strokes",
    "an angular technical cut, corners sliced off on the diagonal",
    "a heavy brush-written hand, strokes tapering as they lift off",
)

# 配色。四個位置＝主色／次色／重點色／備用色，全部是播出安全的高彩度色。
# 「哪個字拿重點色」仍然由呼叫端自己的 COLOUR FOLLOWS MEANING 那句決定——
# 池子決定用哪幾色，意義決定落在誰身上。這樣才不會回到白→黃→紅的行序配色。
COVER_PALETTES: tuple[tuple[str, str, str, str], ...] = (
    ("white", "deep navy", "vivid red", "bright golden yellow"),
    ("white", "black", "bright golden yellow", "vivid red"),
    ("bright golden yellow", "white", "vivid red", "deep navy"),
    ("icy white-blue", "deep teal", "hot orange", "white"),
    ("white", "electric cyan", "magenta", "black"),
    ("black", "white", "lime green", "electric cyan"),
    ("white", "royal purple", "bright golden yellow", "hot orange"),
    ("pale gold", "deep crimson", "white", "black"),
    ("white", "hot orange", "electric cyan", "deep navy"),
)

# 標題區落點（十點 3 級起才解放）。全部限中段以下：上緣是 compose 後貼
# 示意圖的位置。YT 的標題固定在左下，這一池不歸它用（見 draw() 的 anchor 參數）。
COVER_ANCHORS: tuple[str, ...] = (
    "low in its own panel, hard against the left edge",
    "low in its own panel, hard against the right edge",
    "across the middle band of its own panel",
    "low and centred in its own panel",
)

COVER_TILT_DIRECTIONS: tuple[str, ...] = ("clockwise", "anticlockwise")

# 招式池。每一條都是**無字**的，而且都是命令句。件數由等級決定，抽哪幾件由
# 程式抽——交給模型自己選，四級會塌回同一種（許可句推不動模型，第七批已
# 證明）。件數表（COVER_ACCESSORY_COUNTS）與抽哪幾件、怎麼拼幾何提示的邏輯
# 是十點專屬（跟 titles／full_width 耦合），留在 editor_formats.cover_accessories；
# 這裡只搬池子本身。

# 小配件的外框形狀。2026-09-11 使用者：「不一定只有圓形可以用吧。」
# 跟招式用同一個 seeded RNG 抽，所以同一級重生換招式時形狀也跟著換。
# 一律只描述輪廓，不給數字——延續「招式不宣稱數字」那條。
COVER_ACCESSORY_SHAPES: tuple[str, ...] = (
    "circular",
    "rounded-square",
    "hexagonal",
    "diamond-shaped (stood on its corner)",
    "shield-shaped",
    "torn-edged",
    "pentagonal",
    "capsule-shaped",
    "starburst-edged",
)

# 2026-09-11 第十批（配件不看題材）：icon 條目原本帶著
# "(raincloud, flame, siren, warning triangle, syringe)" 這份災難／氣象例子清單，
# 條目裡明明已經寫了「taken from the subject」，卻被這份清單當成錨點蓋過去——
# 實拍國王逝世的封面，L4 抽到的圖示是一朵雨雲，掛在「辭世」旁邊。清單拿掉，正面
# 方法與語氣（「讀這一則故事，不要讀清單」＋死亡配雨雲的反例）改成共通指示，見
# editor_formats.cover_accessories() 的 _ICON_SUBJECT_GUIDANCE，一次管住 icon／
# bubbles／iconrow 三條（都是「畫一個圖示」的招式，不能各自在池子文字裡各寫一次，
# 那樣下次漏改一條又是同一個坑）。
COVER_ACCESSORY_POOL: tuple[tuple[str, str], ...] = (
    ("icon", "A flat WORDLESS PICTOGRAM taken from the subject, hung at one row's start or end at that row's cap height, never covering a stroke."),
    ("magnifier", "A {shape} MAGNIFIER INSET: a clean window cut from the photograph enlarging one telling detail, ringed in a bright colour, with a short heavy arrow pointing back to where it came from."),
    ("bubbles", "A CLUSTER OF SMALL {shape} INSETS arcing along one side of the HEADLINE BLOCK (never up beside the main subject, which often sits high in the frame), each holding one wordless pictogram or tiny photographic detail, shrinking as they trail away."),
    ("brush", "A ROUGH BRUSH-STROKE OR TORN BAR of flat saturated colour behind or directly under ONE row — painted edges, not a neat rectangle."),
    ("material", "ONE WORD FILLED WITH A MATERIAL FROM THE STORY instead of flat colour (molten metal, cracked stone, ice, banknote paper), the rest of that row staying flat."),
    ("cutout", "THE MAIN SUBJECT CUT OUT of its background and stood beside or in front of the headline block, rim-lit or thinly outlined so it reads as a separate layer."),
    ("burst", "A WORDLESS BURST behind the block: radiating speed lines, sparks, shards or a torn splash of saturated colour."),
    ("arrow", "ONE HEAVY WORDLESS ARROW in a saturated colour, thick and slightly angled, driving from the photograph towards the headline."),
    ("iconrow", "A SHORT ROW OF SMALL {shape} WORDLESS ICON CHIPS along the lower edge, just ABOVE the navy bottom strip and never inside it, evenly spaced and equal in size, each holding one flat pictogram from the story."),
)

# 國旗招式（2026-09-11 第十批）。**不進上面那個 tuple**，不跟其他九件一起被
# rng.shuffle：那九件是「模型自己挑不出花樣，交給程式亂數抽」的東西，這一件不是
# ——它成不成立取決於照片裡有沒有旗子，是個確定性判斷，不是隨機的。放進池子讓
# rng 隨機決定「這次要不要用國旗」會有兩個問題：(1) 沒有旗子的照片也可能抽到它，
# 條文只好又寫一句「不成立時忽略」，模型讀不讀得到全看運氣；(2) 全池子多一顆會
# 讓 rng.shuffle(pool) 的消耗量變、所有既有 seed 的長相跟著全換，這正是本檔案
# 開頭「風險 2」要擋的事。改成確定性換入（見 editor_formats.cover_accessories 的
# visuals 參數）：偵測到旗子才把抽到的最後一件換成這個，沒偵測到就完全不進場、
# 既有 seed 的長相不變。
COVER_FLAG_ACCESSORY: tuple[str, str] = (
    "flag",
    "THE FLAG ALREADY VISIBLE IN THIS PHOTOGRAPH, cut out at its own stripes,"
    " proportions and emblem exactly as photographed and enlarged as a backdrop"
    " panel behind one row — never redrawn from memory, never swapped for a"
    " different country's flag, and never labelled with a name.",
)


@dataclass(frozen=True)
class Draw:
    """一輪抽籤的結果。

    `rng` 是抽完這一輪之後的同一顆 `random.Random`——呼叫端（十點的
    `cover_accessories`）要接著同一串亂數繼續抽招式，不能另外開一顆
    `random.Random(seed)`：那樣抽到的是另一串序列，同一顆 seed 卻會抽出
    不一樣的招式。`repr`／`==` 都跳過它：兩個 `Random` 物件天生不相等，
    比較兩個 Draw 是不是同一種長相時只該看抽到的值。
    """

    plate: str
    stagger: str
    typeface: str
    palette: tuple[str, str, str, str]
    tilt_dir: str
    anchor: str | None
    rng: random.Random = field(repr=False, compare=False)


def draw(seed, *, anchor: bool = True) -> Draw:
    """依固定順序抽一輪變化池：plate → stagger → typeface → palette →
    （anchor＝True 才抽這一顆）→ tilt_dir。

    **抽籤順序寫死，不准改**：動了順序（多抽一次、少抽一次、換位置）就會
    把所有既有 seed 的長相全部換掉，而現存測試沒有一條看得出來——見
    docs/plan-20260911-創意拉桿模組化.md 風險 2。

    `anchor=False` 時**連抽都不抽這一顆**，不是抽了不用：YT 的序列裡本來
    就沒有這一格（標題固定左下，落點放開會拆散日期牌），少抽一顆會讓後面
    的 tilt_dir 往前遞補一位——這正是十點與 YT 共用同一批池子、卻各自序列
    長度不同的地方，兩邊都不准把對方的長度套到自己頭上。這一輪 YT 仍然
    不接這支函式（沿用它自己 editor_formats.yt_design_brief 裡的舊寫法），
    這個參數是為下一步先把介面留對。
    """
    rng = random.Random(seed)
    plate = rng.choice(COVER_PLATE_SHAPES)
    stagger = rng.choice(COVER_STAGGER_PATTERNS)
    typeface = rng.choice(COVER_TYPEFACES)
    palette = rng.choice(COVER_PALETTES)
    picked_anchor = rng.choice(COVER_ANCHORS) if anchor else None
    tilt_dir = rng.choice(COVER_TILT_DIRECTIONS)
    return Draw(
        plate=plate,
        stagger=stagger,
        typeface=typeface,
        palette=palette,
        tilt_dir=tilt_dir,
        anchor=picked_anchor,
        rng=rng,
    )


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
    " letters, no digits, no country names, no place labels, no flag"
    " redrawn from memory, no map insets, no extra badges or callouts.\n"
    # 例外句另起一行，不擠進上面那串 no-X 清單——這個 repo 記過的病灶：排除條文
    # 埋在一長串否定句中間，模型讀到前面幾個 no 就停了，後面的界線讀不到（見
    # commit 73ae198）。原本 60 字的括號夾在七個 no 中間正好犯了同一個病；拆開後
    # 清單裡的那一項維持精確界定（redrawn from memory），例外是另一件事（照片裡
    # 既有的旗），兩句不衝突，不是「靠後面覆蓋」。
    "ONE NAMED EXCEPTION TO THAT: a flag ALREADY VISIBLE IN THE PHOTOGRAPH is not"
    " something you draw — it may be cut out at its own stripes, proportions and"
    " emblem exactly as photographed and reused as-is, never redrawn, never"
    " swapped for a different country's, and never labelled with a name."
    " Redrawing a flag from memory gets the stripes, the proportions or the"
    " emblem wrong, which is a factual error on air, the same problem as a"
    " hand-drawn map.\n"
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
