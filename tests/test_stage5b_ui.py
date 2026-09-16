"""Stage 5b 前端接線：新聞原文、具名換臉欄位與 nonfatal notices。"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage5bUiTests(unittest.TestCase):
    def test_cover_fields_send_news_text_verbatim(self):
        self.assertIn(
            "news_text: document.getElementById('coverNewsText')?.value || ''",
            APP_JS,
        )
        self.assertIn(
            "news_text: document.getElementById('ytCoverNewsText')?.value || ''",
            APP_JS,
        )

    def test_refine_has_structured_replacement_field(self):
        self.assertIn('id="replacementPerson"', INDEX_HTML)
        self.assertIn("換臉對象（具名時必填）", INDEX_HTML)
        self.assertIn("replacement_person: replacementPerson", APP_JS)
        self.assertIn("requestsNamedFaceReplacement(instruction)", APP_JS)
        self.assertIn("系統不會從自由文字猜姓名", APP_JS)

    def test_success_notice_survives_normal_hide_until_next_request(self):
        self.assertIn("function showGenerateNoticeBanner(notices)", APP_JS)
        self.assertIn("banner.dataset.notice = '1'", APP_JS)
        self.assertIn("if (banner && banner.dataset.notice === '1' && !force) return;", APP_JS)
        self.assertIn("function clearGenerateBannerForNewRequest()", APP_JS)
        self.assertIn("clearGenerateBannerForNewRequest();\n    if (editorFormat()", APP_JS)

    def test_notices_are_rendered_in_banner_not_prompt_or_image(self):
        self.assertIn("showGenerateNoticeBanner(data.notices)", APP_JS)
        self.assertIn("document.getElementById('oneClickErrorMsg').innerText = messages.join", APP_JS)
        self.assertNotIn("notices.join", APP_JS.split("function showRefinedImage", 1)[-1].split("function handleRefine", 1)[0])


if __name__ == "__main__":
    unittest.main()
