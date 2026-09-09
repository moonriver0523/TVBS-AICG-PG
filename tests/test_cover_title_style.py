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
        """
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        for freed in ("typeface", "colours", "decorative frames", "emphasis",
                      "where on the frame the block sits"):
            with self.subTest(freed=freed):
                self.assertIn(freed, clause)

    def test_designed_clause_cancels_the_white_yellow_red_rule_explicitly(self):
        """本 repo 的慣例：位置在後**加上**明文 OVERRIDE 才壓得過前面的規則。
        前面那三條（逐行配色、鎖在左下、一行一列）都要被點名取消，含糊帶過沒有用。"""
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        self.assertIn("OVERRIDE EVERY TYPOGRAPHY INSTRUCTION ABOVE", clause)
        self.assertIn("per-line colour labels (white / yellow / red) are only a hint", clause)
        self.assertIn("no longer binds", clause)

    def test_designed_clause_still_locks_the_areas_the_program_pastes_into(self):
        """解放的是設計，不是版面規約：標頭帶／底部飾帶不准被字蓋掉，
        標頭帶左半與 AI示意圖 那個角落要留空（compose 後貼 Logo／節目標籤／小標）。"""
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        self.assertIn("NO part of the headline may sit inside them or overlap them", clause)
        self.assertIn("LEFT HALF of the header band", clause)
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
        """設計標題不得取代逐行給定的機制——兩者要同時在 prompt 裡。"""
        prompt = self._prompt(self._split_body(title_style="designed"))
        self.assertIn("Line 1 (white): 尼泊爾災區", prompt)
        self.assertIn("do NOT re-split, merge or reorder", prompt)


class FrontendTests(unittest.TestCase):
    def test_state_defaults_to_plain(self):
        self.assertRegex(APP_JS, r"coverTitleStyle:\s*'plain'")

    def test_payload_carries_title_style_on_both_paths(self):
        # 生成本體與 tenCoverFields（追加修改／只改文字）各一處
        self.assertEqual(len(re.findall(r"title_style:\s*state\.coverTitleStyle", APP_JS)), 2)

    def test_button_exists_and_is_wired(self):
        self.assertIn('id="coverTitleStyleBtn"', INDEX_HTML)
        self.assertIn("toggleCoverTitleStyle()", INDEX_HTML)
        self.assertIn("updateCoverTitleStyleButton()", INDEX_HTML)
        self.assertIn("function toggleCoverTitleStyle()", APP_JS)

    def test_button_only_shows_for_cover_layout_in_ai_mode(self):
        self.assertIn("editorFormat().inputs !== 'cover' || !aiMode", APP_JS)


if __name__ == "__main__":
    unittest.main()
