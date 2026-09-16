"""Stage 5b 前端接線：新聞原文、具名換臉欄位與 nonfatal notices。"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def _extract_function(source: str, name: str) -> str:
    """從 app.js 撈出一支獨立函式的原始碼，給 node 實際執行用。

    比對字串會漏掉「寫了但邏輯是錯的」，所以換臉語意判斷這支要真的跑起來。
    """
    start = source.index(f"function {name}(")
    depth = 0
    for index in range(source.index("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"app.js 裡找不到完整的 {name}()")


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


class NamedFaceReplacementDetectorTests(unittest.TestCase):
    """換臉語意判斷要真的跑起來，不是比對字串。

    2026-09-16 監督驗收抓到的漏洞：只看「臉＋換掉」會把**刪臉**也判成換臉。
    刪臉那條路徑本來就會成功（MASTER B63「刪得掉、換不掉」，曹雪卿 0915 實例），
    被擋下來要求填「換臉對象」等於整條路堵死——她根本沒有要換成誰。
    """

    CASES = [
        # (指令, 是否該判定為「要求具名換臉」)
        ("人頭要換成新的FED主席華許", True),   # 0916 王結玲原話
        # 「換掉」在中文裡本來就偏向「換成別的」，句子裡沒有任何移除語意時**仍然要擋**，
        # 提示使用者填欄位。真的只是想拿掉的人會寫「不要」「刪掉」「移除」，那幾種在下面。
        ("把左邊那張臉換掉", True),
        ("左邊的鮑爾不要!!!!", False),          # 0915 曹雪卿原話，刪臉
        ("把中間那張臉刪掉", False),
        ("這個人的臉移除", False),
        ("換臉", True),
        ("replace the face with someone else", True),
        ("remove the face on the left", False),
        ("背景改成藍色", False),                # 完全無關的一般 refine
        ("標題字再大一點", False),
    ]

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("本機沒有 node，跳過前端行為測試")
        cls.fn = _extract_function(APP_JS, "requestsNamedFaceReplacement")

    def test_removal_wording_is_not_treated_as_named_replacement(self):
        script = (
            self.fn
            + "\nconst cases = "
            + json.dumps([text for text, _ in self.CASES], ensure_ascii=False)
            + ";\nconsole.log(JSON.stringify(cases.map(requestsNamedFaceReplacement)));"
        )
        proc = subprocess.run(
            [self.node, "-e", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = json.loads(proc.stdout.strip().splitlines()[-1])
        for (text, expected), actual in zip(self.CASES, got):
            with self.subTest(instruction=text):
                self.assertEqual(actual, expected)

    def test_the_detector_never_tries_to_extract_a_name(self):
        """F41「只抽取、不推斷」：這支只准回 true/false，不准去切姓名出來。"""
        self.assertNotIn("match(", self.fn)
        self.assertNotIn("RegExp", self.fn)
        self.assertNotIn("split(", self.fn)
        self.assertTrue(re.search(r"return\s+(true|false|\w+Terms)", self.fn))


if __name__ == "__main__":
    unittest.main()
