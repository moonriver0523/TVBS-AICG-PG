"""十點 AI 整張版的「設計標題」開關（2026-09-08 使用者要求：標題要設計感＋滿框）。

守的紅線：
1. **預設 plain。** 不帶 `title_style` 時 prompt 不得出現 designed 那一段——designed 讓模型
   大改版面，錯字與版面走鐘的風險比較高，要使用者自己開。
2. **designed 只改排版、不改字。** 那一段自己要明文重申「照給定的行逐字印、不得增減」，
   否則模型會為了版面好看自己加字或砍字。
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
    def test_designed_clause_demands_full_width_and_mixed_sizes(self):
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        self.assertIn("FILLS THE FULL WIDTH", clause)
        self.assertIn("EMPHASIS IS BY SIZE ONLY", clause)
        self.assertIn("Do NOT add a highlight colour of your own", clause)

    def test_designed_clause_does_not_override_the_line_and_colour_rules(self):
        """設計標題只能改字級／字重／位置——行數、斷行、顏色仍由清單標記說了算。"""
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        self.assertIn("does NOT change the line count", clause)
        self.assertIn("each in its labelled colour", clause)

    def test_designed_clause_repeats_the_verbatim_rule(self):
        clause = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE
        self.assertIn("character for character", clause)
        self.assertIn("never add, drop, reorder or re-split", clause)

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
