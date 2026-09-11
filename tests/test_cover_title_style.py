"""十點 AI 整張版的「設計標題」開關（2026-09-08 使用者要求：標題要設計感＋滿框）。

守的紅線：
1. **預設 plain。** 不帶 `title_style` 時 prompt 不得出現 designed 那一段——designed 讓模型
   大改版面，錯字與版面走鐘的風險比較高，要使用者自己開。
2. **designed 解放的是設計，不是內容。** 2026-09-09 使用者裁決把配色、版位、字體、
   邊框、強調全部放給模型（白／黃／紅三段規則對它不再適用），但那一段自己要明文
   重申「照給定的行逐字印、不得增減、不得中途斷行」，否則模型會為了版面好看
   自己加字或砍字——9/12 這種斜線被拆成兩行就是最典型的一種。
   另外三個「程式後貼」的區域（標頭帶左半、AI示意圖角落、上下兩條深藍帶）也不解放。
3. **雙切與滿版兩個模板都吃。**
"""
import base64
import io
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import editor_formats  # noqa: E402
import main  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402

APP_JS = (Path(__file__).resolve().parent.parent / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
MARKER = "DESIGNED TITLE"


def _png_for(aspect_ratio: str) -> bytes:
    ratio = main.parse_aspect_ratio(aspect_ratio) or 1.0
    buffer = io.BytesIO()
    Image.new("RGB", (round(720 * ratio), 720), (30, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


class ClauseTests(unittest.TestCase):
    def test_designed_clause_hands_the_design_over(self):
        """2026-09-09 使用者：「設計規則與放置位置完全解放，交由 AI 大膽設計。」

        字體、顏色、邊框、強調、版位五樣都要明文交出去——只寫「你可以設計」而不
        逐項點名，模型會照前面那幾條保守規則辦，等於沒解放。

        2026-09-11 第四輪改了「交給誰」：字體、配色、版位三樣改由**程式每次抽**
        （COVER_TYPEFACES／COVER_PALETTES／COVER_ANCHORS），寫進 CANVAS 後面的綱要。
        因為「你自己決定」這種許可句實測推不動模型——七批下來成品永遠同一種黑體、
        同一個左下角。解放的意思沒變（不再綁死那幾條保守規則），變的是由誰下決定。
        邊框與強調仍然留給模型。
        """
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        # 仍然留給模型的兩樣
        for freed in ("decorative frames", "emphasis"):
            with self.subTest(freed=freed):
                self.assertIn(freed, clause)
        # 改由綱要下令的三樣：條文區要明講「照綱要辦、不要自己另外挑」，
        # 否則就是今天踩過的孤兒規則——模型會挑最寬鬆的那句遵守。
        self.assertIn("ALREADY FIXES", clause)
        for pinned in ("letterforms", "the colours", "where the block sits"):
            with self.subTest(pinned=pinned):
                self.assertIn(pinned, clause)
        self.assertIn("do not substitute your own", clause)
        self.assertNotIn("You choose the typeface", clause)
        # 而綱要真的每次都給不一樣的命令
        briefs = {editor_formats.cover_design_brief(4, seed=s) for s in range(8)}
        self.assertGreater(len(briefs), 1)

    def test_designed_clause_cancels_the_white_yellow_red_rule_explicitly(self):
        """本 repo 的慣例：位置在後**加上**明文 OVERRIDE 才壓得過前面的規則。
        前面那三條（逐行配色、鎖在左下、一行一列）都要被點名取消，含糊帶過沒有用。

        2026-09-11：配色從「白黃紅只是提示、可以忽略」（許可句，實拍照樣白黃紅）
        改成命令句＋明文禁止那個順序；顏色標記本身也不再輸出（見 main._lines_block）。
        """
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        self.assertIn("OVERRIDE EVERY TYPOGRAPHY INSTRUCTION ABOVE", clause)
        self.assertIn("no longer binds", clause)
        # 配色鐵則住在 CANVAS 正後方的 DESIGN BRIEF（第二輪搬過去的，見那支測試），
        # 模板裡原本那條逐行配色也在 1 級起被換掉，不是靠 OVERRIDE 壓。
        brief = editor_formats.cover_design_brief(
            editor_formats.COVER_AI_TITLE_LEVEL_MAX, titles=("尼泊爾災區 無人機空拍",), seed=0)
        self.assertIn("COLOUR FOLLOWS MEANING, NEVER ROW ORDER", brief)
        self.assertIn("row 1 white, row 2 yellow and row 3 red is BANNED", brief)
        self.assertNotIn("(yellow)", editor_formats.cover_title_colour_rule(
            editor_formats.COVER_AI_TITLE_LEVEL_MAX))

    def test_designed_clause_still_locks_the_areas_the_program_pastes_into(self):
        """解放的是設計，不是版面規約：標頭帶／底部飾帶不准被字蓋掉，
        標頭帶左半與 AI示意圖 那個角落要留空（compose 後貼 Logo／節目標籤／小標）。"""
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        self.assertIn("NO part of the headline may sit inside them or overlap them", clause)
        self.assertIn("WHOLE header band", clause)
        self.assertIn("示意圖", clause)

    def test_designed_clause_keeps_each_headline_in_its_own_panel(self):
        """雙切版：解放版位放的是「在自己那格裡的哪個位置」，不是「哪一格」。
        沒有這一條，模型遲早把左格的標題排過斜切線。"""
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        self.assertIn("ENTIRELY INSIDE ITS OWN PANEL", clause)
        self.assertIn("never crosses the diagonal seam", clause)

    def test_designed_clause_repeats_the_verbatim_rule(self):
        """最重要的一條：解放版位以後，模型最容易做的事就是為了版面好看動字。"""
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        self.assertIn("character for character", clause)
        self.assertIn("never add, drop, translate, abbreviate, reorder or substitute", clause)
        # 斷行也是設計的一部分，但「一行的中間」不准斷——9/12 會被拆成兩行
        self.assertIn("never break a listed line in the middle", clause)
        self.assertIn("9/12", clause)

    def test_both_templates_have_the_slot(self):
        for name in ("COVER_AI_PROMPT_TEMPLATE", "COVER_AI_FULL_PROMPT_TEMPLATE"):
            with self.subTest(template=name):
                self.assertIn("{title_style_clause}", getattr(editor_formats, name))
                self.assertNotIn(MARKER, getattr(editor_formats, name))


class PromptTests(unittest.TestCase):
    def _prompt(self, body):
        seen = {}

        def fake_raw(image_req):
            seen["prompt"] = image_req.prompt
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_for(image_req.aspect_ratio)).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "resolve_cover_visuals", return_value=("左場景", "右場景")), \
             patch.object(main, "generate_image_raw", side_effect=fake_raw):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return seen["prompt"]

    def _split_body(self, **kw):
        body = {"title_left": "尼泊爾災區 無人機空拍", "title_right": "台南易淹水 成氣候衝擊區",
                "layout": "split", "mode": "ai"}
        body.update(kw)
        return body

    def test_default_is_plain_and_omits_the_clause(self):
        self.assertNotIn(MARKER, self._prompt(self._split_body()))

    def test_designed_adds_the_clause_on_split(self):
        self.assertIn(MARKER, self._prompt(self._split_body(title_style="designed")))

    def test_designed_adds_the_clause_on_full(self):
        prompt = self._prompt({"title_left": "全球3100條 躍動冰川", "layout": "full",
                               "mode": "ai", "title_style": "designed"})
        self.assertIn(MARKER, prompt)

    def test_explicit_plain_omits_the_clause(self):
        self.assertNotIn(MARKER, self._prompt(self._split_body(title_style="plain")))

    def test_unknown_style_is_rejected(self):
        res = client.post("/api/editor/cover", json=self._split_body(title_style="fancy"), headers=_headers())
        self.assertEqual(res.status_code, 422)

    def test_designed_keeps_the_pre_split_lines(self):
        """設計標題不得取代逐行給定的機制——兩者要同時在 prompt 裡。
        2026-09-11：1 級起行後面不再是顏色標記，而是該行的處理指示（配色已解放）。"""
        prompt = self._prompt(self._split_body(title_style="designed"))
        self.assertIn("Line 1: 尼泊爾災區", prompt)
        self.assertNotIn("Line 1 (white)", prompt)
        self.assertIn("do NOT re-split, merge or reorder", prompt)


class FrontendTests(unittest.TestCase):
    """2026-09-09 第八批：ON/OFF 按鈕改成 0–4 拉桿（使用者指定仿 AI effort 那一條）。

    2026-09-11 P5：拉桿的 HTML 從 index.html 手寫改成 app.js 的
    renderCreativityBar() 共用元件在 window.onload 時灌進空殼容器——
    range/label 的 id、oninput 呼叫式因此不再是 INDEX_HTML 裡的字面文字，
    改成 renderCreativityBar('coverTitleStyleBar', {...}) 呼叫式裡的參數。
    這裡的測試跟著改成檢查那個呼叫式，而不是找 INDEX_HTML 裡一段不存在的
    HTML。容器本身（id="coverTitleStyleBar"）仍然是 index.html 的一部分，
    這一半沒變。
    """

    def test_state_defaults_to_the_lowest_level(self):
        """預設仍是最左＝現行排版。設計標題會大改版面，錯字風險較高，要使用者自己拉。"""
        self.assertRegex(APP_JS, r"coverTitleCreativity:\s*0")

    def test_payload_carries_the_level_on_both_paths(self):
        # 生成本體與 tenCoverFields（追加修改／只改文字）各一處
        self.assertEqual(len(re.findall(r"title_creativity:\s*state\.coverTitleCreativity", APP_JS)), 2)

    def _cover_title_style_render_call(self) -> str:
        match = re.search(
            r"renderCreativityBar\('coverTitleStyleBar',\s*\{(.*?)\}\);", APP_JS, re.S
        )
        self.assertIsNotNone(match, "app.js 裡找不到 coverTitleStyleBar 的 renderCreativityBar 呼叫式")
        return match.group(1)

    def test_the_slider_exists_and_is_wired(self):
        self.assertIn('id="coverTitleStyleBar"', INDEX_HTML)
        self.assertIn("function renderCreativityBar(", APP_JS)
        call = self._cover_title_style_render_call()
        self.assertIn("rangeId: 'coverTitleStyleRange'", call)
        self.assertIn("oninput: 'setCoverTitleCreativity'", call)
        self.assertIn("function setCoverTitleCreativity(", APP_JS)
        # renderCreativityBar 內部組出來的 <input> 一定是 0–4 五段，跟舊的手寫標記同義
        self.assertIn('type="range" min="0" max="4" step="1" value="0"', APP_JS)

    def test_the_slider_shows_the_level_name_like_the_effort_bar(self):
        """使用者要的是 effort 那條的樣子：兩端標示＋當前檔位的名字。

        右端刻度是「最狂」。搬家前手寫的 HTML 寫的是「奔放」（等級 3 的名字），
        但拉桿實際拉得到等級 4，刻度與行為對不上——2026-09-11 使用者裁決改掉。
        修法是拿掉覆寫、讓它照 pairs 最後一格，所以這裡連帶釘住「不准再出現
        端點覆寫」，避免哪天又被加回去。比對的是鍵語法 `maxLabel:` 而不是裸字
        ——呼叫端的中文註解會提到這個名字，用裸字會被自己的註解誤判。
        """
        call = self._cover_title_style_render_call()
        self.assertIn("labelId: 'coverTitleStyleLabel'", call)
        self.assertIn("pairs: COVER_TITLE_CREATIVITY", call)
        self.assertNotIn("maxLabel:", call)
        block = APP_JS.split("COVER_TITLE_CREATIVITY = [")[1].split("];")[0]
        pairs = re.findall(r"\['([^']+)',\s*'[^']+'\]", block)
        self.assertEqual(len(pairs), 5)
        self.assertEqual(pairs[0], "規矩")
        self.assertEqual(pairs[-1], "最狂")

    def test_the_old_toggle_is_gone(self):
        """留著舊按鈕會有兩個真相源：按鈕設 title_style、拉桿設 title_creativity。"""
        self.assertNotIn("coverTitleStyleBtn", INDEX_HTML)
        self.assertNotIn("toggleCoverTitleStyle", APP_JS)

    def test_slider_only_shows_for_cover_layout_in_ai_mode(self):
        self.assertIn("editorFormat().inputs !== 'cover' || !aiMode", APP_JS)


if __name__ == "__main__":
    unittest.main()
