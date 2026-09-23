"""簡稱對照表（B82，2026-09-21 使用者裁決）。

## 這張表要解決什麼

正式站 11:01:35 那筆（`50d0f78baccd`，十點不一樣雙切）標題寫「全球矚目　本周**川習會**」，
成品把兩位領導人畫成不認識的人。查出來的因果鏈是：

  `editor_formats.COVER_VISUAL_DERIVE_SYSTEM` 規定人名必須**逐字**出現在素材裡，
  而且明禁「Never infer a name from a title, event, organisation or common knowledge」
  → 「川習會」是**事件簡稱**，「川普」「習近平」五個字一個都沒出現
  → 推導模型照規則不准認出他們，`portrait_subjects` 交白卷
  → 畫面描述退成「兩位領導人握手致意」
  → 沒有逐字人名就查不到照片（`main.py` 具名真人規則講得很白：
     「the person cannot be looked up and no face can be drawn」）
  → 零張參考照，生圖模型手上沒有任何臉可以對照，只能自己編。

那道 VERBATIM 規則**本身沒有錯**——它擋的是模型從「總統」「執行長」這種頭銜自己
腦補出一個人名、然後畫一張錯的臉上去。問題是台灣新聞標題慣用簡稱，這個護欄
會把整類報導打成畫不出人。

## 為什麼用查表，不是放寬護欄

護欄擋的是**模型腦補**，不是**程式查表**。這張表是人工維護的封閉集合：出錯就是
表寫錯，翻開就看得到，不會這次對下次錯。放寬 VERBATIM 讓模型自由聯想則是另一
回事——那等於直接打開幻覺閘門，會畫出新聞根本沒提到的人。

所以展開發生在**呼叫模型之前**，由下面的 `alias_hint_block()` 把對照結果當成
**已知事實**附進素材；模型讀到的是「素材裡本來就有這兩個名字」，不是「你去猜」。

## 刻意不做的事

- **不做單字展開。**「川」單字有真實碰撞——「川普」這兩個字本身也是「四川腔國語」
  的意思，「習」更是常用字（學習、習慣）。拆到單字會製造新的誤判，而且是比原本
  更難查的那種。只收**複合事件詞**。
- **不從表裡推衍新組合。** 表上沒有的就是沒有，不做「X習會 → X＋習近平」這種
  模式比對——那又變成推論了。

## 2026-09-22 兩項修正

- **接上一般 CG（B88）。** 原本這裡寫「不碰一般 CG 那條路，要開另案評估」，
  結果 B82 的因果鏈在記者／編輯CG 上原封不動重演一次，只是終點從「編臉」
  變成「背影」。現在 `main.generate()` 也吃這張表。
- **收了兩個字的「川習」。** 使用者指定。它違反上面「只收複合事件詞」的精神，
  因為標題常寫「川習通話」「川習互動」，三個字的「川習會」比對不到。代價是
  跨詞邊界的碰撞（「四川習俗」「四川習近平視察」），所以配一張
  `BLOCKING_PREFIXES` 把已知的前綴擋掉——那仍然是查表，不是推論。

## 要加新條目時

直接加進 `NAME_ALIASES`，值用**臺灣譯名**（川普／普欽，不是特朗普／普丁）。
加完跑 `tests/test_b82_name_aliases.py`——那裡有一道測試會檢查表裡每個人名都沒有
夾帶頭銜或組織名，以免把「美國總統川普」整串塞進 portrait_subjects。
"""

from __future__ import annotations

# 簡稱 → 該簡稱指涉的人（依出場順序）。
#
# 第一批（2026-09-21 使用者指定）：川習會、拜習會、普習會。
# 值一律用臺灣譯名，且只放人名本身——不含頭銜、不含國名、不含組織。
#
# 第二批（2026-09-22 使用者指定）：「川習」。標題常寫「川習通話」「川習互動」
# 「川習登場」，三個字的「川習會」比對不到，B88 接好了照樣落空。
# ⚠ 這一條比第一批脆弱：「川習」兩個字會出現在**跨詞邊界**上，最現實的是
# 「四川習俗」「四川習近平視察」——前一個字是「四川」的川。所以它配一張
# `BLOCKING_PREFIXES`（見下），那仍然是查表、不是推論。
NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "川習會": ("川普", "習近平"),
    "拜習會": ("拜登", "習近平"),
    "普習會": ("普欽", "習近平"),
    "川習": ("川普", "習近平"),
}

# 簡稱前面出現這些字時，那一次出現不算命中——它是跨詞邊界的巧合。
# 只收「以『川』結尾的地名／姓氏」這一類確定會碰撞的字，同樣是人工維護的封閉集合，
# 不做任何模式推衍。key 是簡稱，value 是「前一個字」的集合。
#
# 為什麼不乾脆不收「川習」：使用者 2026-09-22 明確要求列入。折衷是「收，但把已知
# 的碰撞擋掉」——漏擋的代價是把川普畫進一則四川新聞裡，比畫成背影嚴重得多。
BLOCKING_PREFIXES: dict[str, frozenset[str]] = {
    "川習": frozenset("四銀品香德市河旭湯"),
}

# 兩字簡稱的末字若同時是常見詞首，還要看後一字，避免跨詞邊界誤命中。
# key 是簡稱末字，value 是緊接在簡稱後、會把末字組成一般詞的字。
TWO_CHAR_BLOCKING_SUFFIXES: dict[str, frozenset[str]] = {
    "習": frozenset("俗性慣氣題作字藝得"),
}


def _really_appears(alias: str, blob: str) -> bool:
    """這個簡稱在素材裡有沒有**至少一次**不是跨詞巧合的出現。

    沒有登記阻擋字的簡稱就是單純的 `in`（第一批三條全都是這種）。
    有登記的，逐一檢查每次出現的前一個字：只要有一次不被擋，就算命中。
    """
    blocked_before = BLOCKING_PREFIXES.get(alias, frozenset())
    blocked_after = TWO_CHAR_BLOCKING_SUFFIXES.get(alias[-1], frozenset()) if len(alias) == 2 else frozenset()
    if not blocked_before and not blocked_after:
        return alias in blob
    start = blob.find(alias)
    while start != -1:
        before_ok = start == 0 or blob[start - 1] not in blocked_before
        end = start + len(alias)
        after_ok = end == len(blob) or blob[end] not in blocked_after
        if before_ok and after_ok:
            return True
        start = blob.find(alias, start + 1)
    return False


def find_aliases(*texts: str) -> list[tuple[str, tuple[str, ...]]]:
    """挑出這些素材裡**真的出現過**的簡稱，依表的順序回傳，不重複。

    只做字面比對（`in`）＋一張人工維護的阻擋字表（`BLOCKING_PREFIXES`），
    不做正規化、不做模糊比對——比對規則一旦帶推測，這張表就失去
    「確定性」這個唯一的正當性。

    ⚠ 長短簡稱會同時命中（「川習會」的素材也含「川習」），兩條都指向同一組人，
    所以只保留**先命中的那一條**，避免同一組名字在素材裡出現兩次。
    表的順序＝長的在前，所以留下的一定是講得比較具體的那一條。
    """
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return []
    hits: list[tuple[str, tuple[str, ...]]] = []
    seen: set[tuple[str, ...]] = set()
    for alias, names in NAME_ALIASES.items():
        if names in seen or not _really_appears(alias, blob):
            continue
        hits.append((alias, names))
        seen.add(names)
    return hits


def alias_hint_block(*texts: str) -> str:
    """給推導步驟附加的簡稱對照段；沒有命中就回空字串。

    回空字串這件事是硬要求：沒命中時素材必須與加這張表之前**逐字相同**，
    否則既有的 rng_pins fixture 與各版型的 prompt 比對測試會整批失效。
    """
    hits = find_aliases(*texts)
    if not hits:
        return ""
    lines = "\n".join(
        f"- 「{alias}」 refers to these people, in this order: "
        + "、".join(names)
        for alias, names in hits
    )
    return (
        "\n\nAbbreviation glossary supplied by the newsroom. This is a fixed, "
        "human-maintained lookup table, not a guess and not something you inferred — "
        "the expansions below are given to you as established fact:\n"
        f"{lines}\n"
        # B88（2026-09-22）：措辭從「the side whose headline」改成中性講法。
        # 原本是照十點雙切寫的，一般 CG 沒有「side」也沒有「headline」，照搬過去
        # 模型會讀不出這段在講哪一塊。
        "Treat every personal name listed here exactly as if it were written out in full "
        "in the material above, at the place where the abbreviation appears: you MAY name "
        "these people in the description and you MUST list them as named real people for "
        "that part of the graphic. This applies ONLY to the names in this glossary — for everyone else "
        "the verbatim rule stands unchanged, so never expand an abbreviation, a title or an "
        "organisation that is not listed here."
    )
