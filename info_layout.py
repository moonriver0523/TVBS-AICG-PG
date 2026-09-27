"""Deterministic information-presentation selection for news CG digests.

The selector in this module is deliberately conservative.  It chooses a non-card
layout only when the source text itself supplies enough structural evidence; the
safe fallback is the existing cards treatment.  No random state, model call, or
environment variable is consulted here, so a decision can be reproduced in an
audit or a test.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Literal


InfoLayoutMode = Literal[
    "timeline",
    "comparison",
    "hero_number",
    "annotated_subject",
    "icon_grid",
    "feature_spread",
    "cards",
]


@dataclass(frozen=True)
class InfoLayoutDecision:
    mode: InfoLayoutMode
    rule: str
    enabled: bool = True


_TEMPORAL_TOKEN_RE = re.compile(
    r"(?:\d{4}年\d{1,2}月(?:\d{1,2}日)?|\d{1,2}月\d{1,2}日|"
    r"(?:上午|中午|下午|晚間|晚上|凌晨)?\d{1,2}(?:時|點)(?:\d{1,2}分)?|"
    r"(?:週|星期)[一二三四五六日天]|今早|今晚|隔天|翌日)"
)
_SEQUENCE_TOKEN_RE = re.compile(
    r"(?:首先|先是|先|接著|隨後|再來|然後|之後|最終|最後|第一步|第二步|第三步|"
    r"步驟[一二三四五六123456])"
)
_COMPARISON_CUE_RE = re.compile(
    r"(?:相比|相較|對比|較去年|較今年|高於|低於|多於|少於|領先|落後|差距|分別|"
    r"勝過|不及|同比分|年增|年減|同期)"
)
_PAIR_RE = re.compile(
    r"(?P<a>今年|去年|前年|本期|上期|台灣|臺灣|中國|日本|美國|歐洲|亞洲|"
    r"[A-Za-z][A-Za-z0-9_-]{1,15}|[\u4e00-\u9fff]{2,8})"
    r"(?:與|和|及|對比|相比|相較於|對上| versus | vs\.? )"
    r"(?P<b>今年|去年|前年|本期|上期|台灣|臺灣|中國|日本|美國|歐洲|亞洲|"
    r"[A-Za-z][A-Za-z0-9_-]{1,15}|[\u4e00-\u9fff]{2,8})",
    re.IGNORECASE,
)
_THREE_WAY_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z]{2,10}[、,，]"
    r"[\u4e00-\u9fffA-Za-z]{2,10}[、,，]"
    r"[\u4e00-\u9fffA-Za-z]{2,10}"
)
_QUANTITY_RE = re.compile(
    r"(?<![\d.])(?P<value>\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(?P<unit>%|％|兆美元|億美元|萬美元|美元|兆日圓|億日圓|萬日圓|日圓|"
    r"兆元|億元|萬元|元|萬人|人|戶|件|席|點|公里|公尺|公斤|噸|家|名|"
    r"宗|起|度|倍|歲|天|項|縣市|國|架|艘|所|間|座|站|例|款|次|碼|級|百帕|"
    r"分鐘|小時)"
)
_HERO_CUE_RE = re.compile(
    r"(?:核心|主指標|關鍵|總計|總額|預算|規模|達到|達|增至|升至|降至|突破|"
    r"暴增|大減|成長|下滑|攀升|跌至|創下|最高|最低|最多|最少|超過|逾|"
    r"多達|高達|僅有|只剩|縮減|增加|減少|上漲|下跌|外洩|失蹤|受惠)"
)
_NON_HERO_UNIT_RE = re.compile(r"^(?:歲|天|項|國|分鐘|小時)$")
_DATE_CONTEXT_RE = re.compile(
    r"(?:19|20)\d{2}年|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2}|第?\d+條|\d+年次"
)
_ROLE_NAME_PATTERNS = (
    re.compile(
        r"(?:總統|副總統|行政院長|院長|首相|日相|總理|市長|縣長|部長|次長|署長|"
        r"局長|處長|執行長|董事長|總經理|總監|立委|議員|發言人|主任|校長|"
        r"教授|醫師|選手|教練|導演|律師|檢察官|法官|研究員|分析師|主席|"
        r"大臣|司令|隊長|理事長|創辦人|主持人|作家)"
        r"(?P<name>[\u4e00-\u9fff]{2,4}?)(?=[表示指出宣布主張呼籲提出率領推動完成])"
    ),
    re.compile(
        r"(?P<name>[\u4e00-\u9fff]{2,4})(?:（[^）]{1,14}）|，|,)?"
        r"(?:擔任|出任|是|身為)"
        r"(?:總統|副總統|行政院長|院長|首相|日相|總理|市長|縣長|部長|次長|署長|"
        r"局長|處長|執行長|董事長|總經理|總監|立委|議員|發言人|主任|校長|"
        r"教授|醫師|選手|教練|導演|律師|檢察官|法官|研究員|分析師|主席|"
        r"大臣|司令|隊長|理事長|創辦人|主持人|作家)"
    ),
)
_INSTITUTION_SUBJECT_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z .&-]{1,24}|[\u4e00-\u9fff]{2,26}"
    r"(?:署|部|局|院|會|公司|基金會|協會|銀行|大學|中心|政府|警方|地檢署|"
    r"法院|球團|系統|研究所|委員會|辦公室))"
    r"[）)]?(?:今天|今日|周[一二三四五六日]|日前)?(?:召開記者會)?"
    r"(?:表示|指出|宣布|說明|回應|預估|預測|公布|發布|警告|證實|呼籲|認為|決定)"
)
_ROLE_NAME_MENTION_RE = re.compile(
    r"(?:總統|副總統|行政院長|院長|首相|日相|總理|市長|縣長|部長|次長|署長|"
    r"局長|處長|執行長|董事長|總經理|總監|立委|議員|發言人|主任|校長|"
    r"教授|醫師|選手|教練|導演|律師|檢察官|法官|研究員|分析師|主席|"
    r"大臣|司令|隊長|理事長|創辦人|主持人|作家)"
    r"(?P<name>[\u4e00-\u9fff]{2,4})(?=今天|今日|日前|周[一二三四五六日]|"
    r"表示|指出|宣布|主張|呼籲|提出|率領|推動|完成|確定|曾|將|，|,|。)"
)
_NAMED_THING_RE = re.compile(
    r"[「『](?P<quoted>[^」』]{2,18})[」』]|"
    r"(?P<latin>[A-Za-z][A-Za-z0-9 +._-]{1,20}\s(?:手機|系統|方案|計畫|法案|颱風))"
)
_TOPIC_SUBJECT_RE = re.compile(
    r"^(?:【參考資料】\s*)?(?:標題[:：]?\s*)?"
    r"(?P<name>[^，。！？\n]{2,28}?(?:颱風|方案|法案|新規|系統|事件|洪災|火警|"
    r"油價|股市|公債|飛彈|住宅|民泊|幼兒園|商圈|球場|冰川|基金會|演習|"
    r"音樂節|發表會|調查|聲明|政策|計畫))"
)
_ATTRIBUTE_CATEGORIES = (
    re.compile(r"(?:主張|目標|承諾|計畫|表示|指出|認為|呼籲|說明|回應)"),
    re.compile(r"(?:行動|宣布|提出|推動|率領|執行|啟動|公布|發布|決定|禁止)"),
    re.compile(r"(?:結果|影響|完成|獲得|造成|帶來|導致|協助|外洩|受惠)"),
    re.compile(r"(?:原因|背景|爭議|風險|質疑|警告|困難|問題)"),
)
_FIELD_LABEL_RE = re.compile(
    r"(?:對象|資格|金額|日期|上路|影響|措施|服務|項目|類別|範圍|地點|時間|"
    r"申請|期限|方式|條件)[：:]"
)
_BULLET_RE = re.compile(r"(?m)^\s*(?:[-*•]|[一二三四五六123456][、.．])\s*\S+")
_ENUM_INTRO_RE = re.compile(r"(?:包括|分為|涵蓋|共有|項目為|對象為)[：:]?([^。\n]{3,120})")
_COUNTED_LIST_RE = re.compile(
    r"(?:[3-6]|三|四|五|六)\s*(?:大|項|種|類|個)(?:重點|方法|原因|困難|措施|"
    r"步驟|特色|服務|風險|問題|要點|指標|項目)?"
)
_INLINE_NUMBERED_RE = re.compile(r"(?:^|\s)[1-6][.、．]\s*\S+")
_PARALLEL_CUE_RE = re.compile(
    r"(?:包括|分為|涵蓋|分別是|分別為|主要有|項目為|對象為|可分成|可分為|"
    r"依序為|重點包括)"
)
_FEATURE_EVENT_RE = re.compile(
    r"(?:發生|爆發|發現|宣布|發布|公布|推出|上路|啟動|舉行|開賣|攻擊|襲擊|"
    r"逮捕|攔查|追緝|遭|受困|失蹤|外洩|起火|洪災|車禍|事故|爭議|控訴|"
    r"警告|證實|決定|禁止|回應|表示|指出|報導|調查|研究|統計|預估|預測|"
    r"升息|降息|上漲|下跌|反彈|改組|悼念|演習|救援|搜救|肇事|起疹)"
)
_FEATURE_UNSAFE_RE = re.compile(
    r"(?:第[一二三四五六]則|第[一二三四五六]章|您怎麼看|請幫我|幫我設計|"
    r"\[大標題|\[次標題|PPT流程圖|完整照原文|逐字保留|道路交通管理處罰條例|"
    r"第\s*\d+\s*條)"
)
_HERO_UNSAFE_RE = re.compile(
    r"(?:第[一二三四五六]則|第[一二三四五六]章|您怎麼看|PPT流程圖)"
)
_MULTI_ENTITY_CUE_RE = re.compile(
    r"(?:南韓|韓國|北韓|美國|日本|中國|台灣|臺灣|英國|法國|德國|俄羅斯|"
    r"烏克蘭|以色列|伊朗|葉門|歐洲|亞洲|[\u4e00-\u9fff]{1,4}國)"
    r"[、,，]\s*(?:南韓|韓國|北韓|美國|日本|中國|台灣|臺灣|英國|法國|德國|"
    r"俄羅斯|烏克蘭|以色列|伊朗|葉門|歐洲|亞洲|[\u4e00-\u9fff]{1,4}國)"
    r"(?:與|和|及)(?:南韓|韓國|北韓|美國|日本|中國|台灣|臺灣|英國|法國|德國|"
    r"俄羅斯|烏克蘭|以色列|伊朗|葉門|歐洲|亞洲|[\u4e00-\u9fff]{1,4}國)"
)
_VERBATIM_REQUEST_RE = re.compile(
    r"(?:逐字保留|完全依照文字|完全照原文|不要刪減|不要添加文字|這是完稿|不改字)"
)


def requests_verbatim(text: str) -> bool:
    """Whether an explicit newsroom instruction asks to preserve wording."""

    return bool(_VERBATIM_REQUEST_RE.search(text or ""))


def _timeline_evidence(text: str, type_label: str) -> str | None:
    temporal = _TEMPORAL_TOKEN_RE.findall(text)
    sequence = _SEQUENCE_TOKEN_RE.findall(text)
    if len(temporal) >= 2:
        return f"原文有 {len(temporal)} 個明示日期／時間節點，可按原文順序排列"
    if len(sequence) >= 2:
        return f"原文有 {len(sequence)} 個明示先後詞，可按原文順序排列"
    if "流程" in (type_label or "") and (len(temporal) + len(sequence)) >= 1:
        return "圖表類型是流程，且原文至少有一個明示步驟／時間訊號"
    return None


def _quantities(text: str) -> list[tuple[str, str, int]]:
    return [
        (m.group("value"), m.group("unit"), m.start())
        for m in _QUANTITY_RE.finditer(text)
    ]


def _comparison_evidence(text: str) -> str | None:
    pair = _PAIR_RE.search(text)
    if not pair or pair.group("a") == pair.group("b"):
        return None
    if _THREE_WAY_RE.search(text):
        return None
    if not _COMPARISON_CUE_RE.search(text):
        return None
    unit_counts = Counter(unit for _, unit, _ in _quantities(text))
    repeated_dimensions = [unit for unit, count in unit_counts.items() if count >= 2]
    if len(repeated_dimensions) < 2:
        return None
    return (
        f"原文明示兩個對象「{pair.group('a')}／{pair.group('b')}」及比較關係，"
        f"且至少兩個共同量綱重複出現（{'、'.join(repeated_dimensions[:3])}）"
    )


def _hero_number_evidence(text: str) -> str | None:
    if _HERO_UNSAFE_RE.search(text):
        return None
    quantities = _quantities(text)
    if not 1 <= len(quantities) <= 8:
        return None
    first_sentence_end = min(
        [p for p in (text.find("。"), text.find("！"), text.find("？")) if p >= 0]
        or [len(text)]
    )

    eligible: list[tuple[str, str, int]] = []
    for value, unit, pos in quantities:
        context = text[max(0, pos - 12) : pos + len(value) + len(unit) + 8]
        if _NON_HERO_UNIT_RE.match(unit) or _DATE_CONTEXT_RE.search(context):
            continue
        if unit in {"公里", "公尺"} and re.search(r"每小時\s*\d", context):
            continue
        eligible.append((value, unit, pos))
    if not eligible:
        return None

    main_value, main_unit, main_pos = eligible[0]
    cue_window = text[max(0, main_pos - 18) : main_pos + len(main_value) + len(main_unit) + 10]
    has_cue = bool(_HERO_CUE_RE.search(cue_window))
    is_lead_figure = main_pos <= min(first_sentence_end, 72)
    if "標題:" in text[:12] or "標題：" in text[:12]:
        title_end = min(
            [
                p
                for p in (text.find("\n"), text.find("內容:"), text.find("內容："))
                if p >= 0
            ]
            or [first_sentence_end]
        )
        if main_pos > title_end:
            return None
    if main_pos > 120:
        return None
    if re.search(r"\d+[、~～-]\d+\s*[%％]", cue_window):
        return None
    if not (has_cue or is_lead_figure):
        return None

    same_unit_count = sum(1 for _, unit, _ in eligible if unit == main_unit)
    # Repeated same-unit figures are acceptable when the lead sentence establishes the first
    # one as the current/headline figure.  A comparison cue without a hero cue remains unsafe:
    # it needs a true paired layout or cards, not a silently privileged side.
    if same_unit_count > 1 and re.search(r"分別.{0,40}(?:與|和|及)", text):
        return None
    if same_unit_count > 1 and re.search(r"\d[^。；\n]{0,24}以上[^。；\n]{0,24}\d[^。；\n]{0,12}以下", text):
        return None
    if same_unit_count > 1 and _COMPARISON_CUE_RE.search(text) and not has_cue:
        return None
    if same_unit_count >= 3 and not _HERO_CUE_RE.search(text[max(0, main_pos - 18) : main_pos]):
        return None
    if len(eligible) >= 5 and not has_cue:
        return None
    if _parallel_semantics(text) and not _HERO_CUE_RE.search(
        text[max(0, main_pos - 18) : main_pos]
    ):
        return None
    return (
        f"第一句／標題的「{main_value}{main_unit}」是主數字；另有 {len(eligible) - 1} 個"
        f"補充數字（同單位共 {same_unit_count} 個），可降為衛星資訊而不與主數字等大"
    )


def _named_subjects(text: str) -> list[str]:
    names: list[str] = []
    for pattern in _ROLE_NAME_PATTERNS:
        names.extend(match.group("name") for match in pattern.finditer(text))
    names.extend(match.group("name") for match in _ROLE_NAME_MENTION_RE.finditer(text))
    names.extend(match.group("name").strip() for match in _INSTITUTION_SUBJECT_RE.finditer(text))
    topic = _TOPIC_SUBJECT_RE.search(text)
    if topic:
        topic_name = topic.group("name").strip()
        if not re.search(r"[、，,]|(?:與|和|及)", topic_name):
            names.append(topic_name)
    first_sentence = re.split(r"[。！？\n]", text, maxsplit=1)[0]
    for match in _NAMED_THING_RE.finditer(first_sentence):
        name = (match.group("quoted") or match.group("latin") or "").strip()
        if name and text.count(name) >= 2:
            names.append(name)
    invalid_name = re.compile(r"(?:有望|續任|去留|確定|可能|已經|今天|目前|進行)")
    return list(dict.fromkeys(name for name in names if not invalid_name.search(name)))


def _annotated_subject_evidence(text: str, point_count: int | None) -> str | None:
    if _MULTI_ENTITY_CUE_RE.search(text[:120]):
        return None
    if len(set(re.findall(r"([\u4e00-\u9fff]{2,6})颱風", text[:240]))) >= 2:
        return None
    names = _named_subjects(text)
    if len(names) != 1:
        return None
    if text.find(names[0]) > 100:
        return None
    # 具名主體已由職務語法辨認，職務本身算一類；同一句裡「表示主張」這類近義詞
    # 只算一個屬性類別，避免字面重複把四點新聞誤判成五、六點。
    attribute_count = 1 + sum(bool(pattern.search(text)) for pattern in _ATTRIBUTE_CATEGORIES)
    if not 2 <= attribute_count <= 5:
        return None
    if point_count is not None and not 2 <= point_count <= 5:
        return None
    return f"原文只有一個中心主體「{names[0]}」，並有 {attribute_count} 個屬性／影響訊號"


def _parallel_item_count(text: str) -> int:
    field_count = len(_FIELD_LABEL_RE.findall(text))
    if 3 <= field_count <= 6:
        return field_count
    bullets = _BULLET_RE.findall(text)
    if 3 <= len(bullets) <= 6:
        return len(bullets)
    intro = _ENUM_INTRO_RE.search(text)
    if intro:
        items = [part.strip() for part in re.split(r"[、；;]", intro.group(1)) if part.strip()]
        if 3 <= len(items) <= 6:
            return len(items)
    inline_numbered = _INLINE_NUMBERED_RE.findall(text)
    if 3 <= len(inline_numbered) <= 6:
        return len(inline_numbered)
    if _COUNTED_LIST_RE.search(text):
        colon_count = len(re.findall(r"[^，。；;\n]{2,14}[：:]", text))
        if 3 <= colon_count <= 6:
            return colon_count
    return 0


def _parallel_semantics(text: str) -> bool:
    if _parallel_item_count(text):
        return True
    if not _PARALLEL_CUE_RE.search(text):
        return False
    clause = _PARALLEL_CUE_RE.split(text, maxsplit=1)[-1][:180]
    return len(re.findall(r"[、；;]", clause)) >= 2


def _feature_spread_evidence(text: str, point_count: int | None) -> str | None:
    if point_count is None or not 3 <= point_count <= 6:
        return None
    if len(text) < 80 or _FEATURE_UNSAFE_RE.search(text):
        return None
    if "行程" in text[:80] and len(re.findall(r"\d{1,2}:\d{2}", text)) >= 2:
        return None
    typhoons = set(re.findall(r"([\u4e00-\u9fff]{2,6})颱風", text[:240]))
    if len(typhoons) >= 2:
        return None
    if len({match.group("name") for match in _INSTITUTION_SUBJECT_RE.finditer(text)}) >= 2:
        return None
    if _PAIR_RE.search(text) and _COMPARISON_CUE_RE.search(text):
        return None
    first_two_sentences = "。".join(text.split("。")[:2])
    if not _FEATURE_EVENT_RE.search(first_two_sentences[:220]):
        return None
    # Long multi-section manuscripts need explicit grouping.  Feature spread is for one
    # scene/topic with a handful of digested labels, not a decorative name for many cards.
    if len(re.findall(r"(?:^|\n)\s*(?:第[一二三四五六]|[1-9][.、．])", text)) >= 2:
        return None
    return (
        f"前兩句建立單一新聞場景／議題，消化後為 {point_count} 個重點；"
        "沒有可靠時間軸、雙方比較、主數字或平行清單證據，改用一幅主視覺承載不等級標籤"
    )


def select_info_layout(
    news_text: str,
    type_label: str,
    density: str,
    role: str,
    editor_format: str | None = None,
    point_count: int | None = None,
) -> InfoLayoutDecision:
    """Choose one presentation mode in the fixed, audited priority order.

    ``role`` and ``editor_format`` are explicit inputs even where they do not
    change detection: the returned mode is therefore attributable to the whole
    request, and broadcast-specific geometry can be selected downstream without
    guessing request context.
    """

    text = (news_text or "").strip()
    if density == "verbatim":
        return InfoLayoutDecision(
            "cards", "不改字模式停用資訊呈現 selector，避免版面判斷改動完稿結構",
            enabled=False,
        )
    if density == "no_text":
        return InfoLayoutDecision(
            "cards", "無字模式沒有 [內文小標] 內容單位，維持既有安全版面",
            enabled=False,
        )
    if requests_verbatim(text):
        return InfoLayoutDecision(
            "cards", "原文明示逐字保留／完稿要求，停用資訊呈現 selector",
            enabled=False,
        )

    evidence = _timeline_evidence(text, type_label)
    if evidence:
        return InfoLayoutDecision("timeline", f"規則一（時間／步驟明確）：{evidence}")

    evidence = _comparison_evidence(text)
    if evidence:
        return InfoLayoutDecision("comparison", f"規則二（兩方且同維度）：{evidence}")

    evidence = _hero_number_evidence(text)
    if evidence:
        return InfoLayoutDecision("hero_number", f"規則三（單一主數字）：{evidence}")

    evidence = _annotated_subject_evidence(text, point_count)
    if evidence:
        return InfoLayoutDecision("annotated_subject", f"規則四（單一主體＋少量屬性）：{evidence}")

    parallel_count = _parallel_item_count(text)
    effective_count = parallel_count or point_count or 0
    if 3 <= effective_count <= 6 and _parallel_semantics(text):
        return InfoLayoutDecision(
            "icon_grid",
            f"規則五（平行項目）：原文有並列語意，配合消化後 {effective_count} 個重點，"
            "適合固定資料島幾何",
        )

    evidence = _feature_spread_evidence(text, point_count)
    if evidence:
        return InfoLayoutDecision(
            "feature_spread", f"規則六（單一場景＋散佈標籤）：{evidence}"
        )

    context = f"role={role or 'unknown'}, editor_format={editor_format or 'default'}"
    return InfoLayoutDecision(
        "cards", f"規則七（保守 fallback）：前六項證據不足（{context}），維持現行卡片版面",
    )


_COMMON_BLOCK = """
=== PROGRAM-SELECTED INFORMATION PRESENTATION MODE — OVERRIDES EARLIER ROW/CARD DEFAULTS ===
The program selected {mode}. Follow this geometry in "structure"; do not let an earlier mention of rows, cards, columns, stacks or panels change it.
- `[內文小標]` 是內容單位，不是卡片邊界。 Preserve every required content unit and the fixed point count, but never assume that one line must become one physical card, row, panel or box.
- Selection audit: {rule}
{geometry}
"""


_GEOMETRY = {
    "timeline": (
        "- TIMELINE: place the content units as ordered nodes on one clear event path, using only "
        "dates, times or step order explicitly stated by the source. Vary node emphasis by importance; "
        "do not turn the nodes into equal rectangular cards."
    ),
    "comparison": (
        "- COMPARISON: build exactly two opposing fields for the two named subjects. Align each shared "
        "dimension directly across the same visual level so the eye compares like with like; do not "
        "create two unrelated card columns."
    ),
    "hero_number": (
        "- HERO NUMBER: make the single selected main figure the dominant focal element. Place no more "
        "than three supporting facts as smaller labels or satellites around it, with clear hierarchy and "
        "without equal card boxes."
    ),
    "annotated_subject": (
        "- ANNOTATED SUBJECT: make the one subject the visual centre and place two to four short "
        "annotations around it, connected only where the relation is unambiguous. Avoid a separate "
        "card for each annotation and keep connector lines from crossing."
    ),
    "icon_grid": (
        "- ICON GRID / DATA ISLANDS: use the exact point count to choose a fixed geometry: three points "
        "form a triangle; four form a two-by-two grid; five form a two-over-three arrangement; six form "
        "a three-by-two grid. Islands may be unframed or use only local background colour; full borders "
        "around every item are optional and must not recreate a slide-like stack of cards."
    ),
    "feature_spread": (
        "- FEATURE SPREAD: use one dominant, concrete scene or subject as the visual field, taking "
        "roughly half to two-thirds of the usable canvas. Scatter the required facts around or partly "
        "over that field as short labels of visibly different scale and width, anchored near relevant "
        "details when the relation is clear. Keep the labels unframed or lightly backed; do not align "
        "them into equal columns, rows, tiles, panels or repeated card boxes. The scene is the shared "
        "visual anchor, so this must look like an editorial feature composition rather than a renamed "
        "card layout."
    ),
    "cards": (
        "- CARDS FALLBACK: retain the current safe row/card behaviour because the source did not meet a "
        "higher-confidence rule. Even here, `[內文小標]` is the content and validation unit rather than "
        "an instruction that every line must have its own visible border."
    ),
}


_BROADCAST_GEOMETRY = {
    "timeline": (
        "- BROADCAST VARIANT: use a narrow vertical timeline entirely in the half opposite the reserved "
        "video window. The headline remains above and the optional bottom band remains below; no node, "
        "line or decoration enters the reserved half."
    ),
    "comparison": (
        "- BROADCAST VARIANT: do not split the narrow content half into two columns. Put each shared "
        "dimension on one compact paired line, with subject A and subject B values adjacent on that same "
        "line; if a clean paired line is impossible, render that dimension with the cards fallback."
    ),
    "hero_number": (
        "- BROADCAST VARIANT: place one large main figure in the narrow content half, with the supporting "
        "labels tucked above and below it. Keep the reserved video window, headline strip and optional "
        "bottom band unchanged."
    ),
    "annotated_subject": (
        "- BROADCAST VARIANT: keep the subject and every annotation inside the narrow content half "
        "opposite the reserved window. Arrange annotations around the subject within that half; no leader "
        "line or decoration may cross into the reserved half."
    ),
    "icon_grid": (
        "- BROADCAST VARIANT: compress the points into small data islands in the narrow content half, "
        "using a vertical two-column cluster when it fits and a single staggered cluster otherwise. "
        "Islands may be unframed or locally coloured and must stay clear of the reserved window."
    ),
    "feature_spread": (
        "- BROADCAST VARIANT: crop one strong scene or subject into the narrow content half and let "
        "three or four unequal, mostly unframed labels occupy the remaining negative space around it. "
        "Keep every label and visual anchor out of the reserved window; never convert the labels into "
        "a vertical stack of equal cards."
    ),
    "cards": (
        "- BROADCAST VARIANT: retain the current narrow card stack in the half opposite the reserved "
        "video window. The reserved window, full-width headline, optional bottom band and exact point "
        "count stay unchanged."
    ),
}


def structure_instruction(
    decision: InfoLayoutDecision, *, editor_format: str | None = None
) -> str:
    """Return the late, mode-specific structure block for the digest prompt."""

    geometry = _GEOMETRY[decision.mode]
    if editor_format in {"broadcast", "broadcast_left", "broadcast_right"}:
        geometry += "\n" + _BROADCAST_GEOMETRY[decision.mode]
    return _COMMON_BLOCK.format(
        mode=decision.mode.upper(), rule=decision.rule, geometry=geometry
    )


def adapt_density_instructions(text: str) -> str:
    """Remove physical row/card implications while preserving point-count rules.

    Called only in INFO_LAYOUT_MODE=on.  Keeping this as an exact replacement
    layer lets the off path remain byte-for-byte identical to the pre-feature
    prompt while making the on path internally consistent before the late mode
    block is appended.
    """

    replacements = {
        "the card stack of that layout physically has that many rows": (
            "that layout requires exactly that many [內文小標] content units; it does not prescribe "
            "separate rows or cards"
        ),
        "Rules three, four and five still apply inside those rows.": (
            "Rules three, four and five still apply to those content units."
        ),
        'Design "structure" for that quantity: enough rows or cards for the points you wrote, sized so the longer lines stay legible on air rather than shrinking to fit.': (
            'Design "structure" for that quantity using the program-selected geometry below; keep every content unit legible on air without turning the point count into a required row/card count.'
        ),
        'Group the points: when you write more than five, say in "structure" that they are arranged in labelled groups or two columns rather than one long list, so the viewer can find the one that matters.': (
            'When you write more than five points, organise them within the program-selected geometry below rather than defaulting to one long list; visual grouping may help the viewer find the one that matters.'
        ),
        "those card stacks physically have that many rows": (
            "those layouts require that many content units without requiring one physical row or card per unit"
        ),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text
