"""下載檔名欄位（2026-09-08 使用者回饋 A）。

前端沒有 JS 測試環境，所以照本專案既有做法：用 Python 讀 app.js／index.html 的
原始碼，驗「規則有沒有寫在那裡」。重點是**每一個** download 賦值都走同一支函式——
只要有人日後又寫死一個 'tvbs-xxx.png'，這裡就會紅。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class DownloadAssignmentTests(unittest.TestCase):
    def test_every_download_assignment_goes_through_the_helper(self):
        assignments = re.findall(r"\.download\s*=\s*([^\n;]+)", APP_JS)
        self.assertGreaterEqual(len(assignments), 5, "app.js 應該至少有五處下載檔名賦值")
        for expr in assignments:
            with self.subTest(expr=expr.strip()):
                self.assertIn(
                    "downloadFileName(", expr,
                    "download 檔名一律走 downloadFileName()，不得寫死字串",
                )

    def test_no_hard_coded_legacy_file_names_remain(self):
        for dead in ("tvbs-ten-cover.png", "tvbs-yt-hourly-cover.png",
                     "tvbs-yt-hot-cover.png", "tvbs-yt-live-cover.png"):
            with self.subTest(dead=dead):
                self.assertNotIn(dead, APP_JS)

    def test_helper_is_defined_once(self):
        self.assertEqual(
            len(re.findall(r"function downloadFileName\(", APP_JS)), 1,
            "downloadFileName 只能有一份定義",
        )


class DownloadNameRuleTests(unittest.TestCase):
    def test_illegal_characters_are_stripped(self):
        pattern = re.search(r"const DOWNLOAD_NAME_ILLEGAL = (/.+/g);", APP_JS)
        self.assertIsNotNone(pattern, "找不到檔名非法字元的正規式")
        literal = pattern.group(1)
        # Windows 不接受的字元＋換行，一個都不能少
        for ch in ("\\\\", "/", ":", "*", "?", '"', "<", ">", "|", "\\r", "\\n"):
            with self.subTest(ch=ch):
                self.assertIn(ch, literal)

    def test_custom_name_wins_and_keeps_the_extension(self):
        body = _helper_body()
        self.assertIn("if (custom) return `${custom}.${extension}`;", body)

    def test_default_pattern_is_date_format_title(self):
        body = _helper_body()
        # YYYYMMDD_<版型短名>_<標題前 8 字>
        self.assertIn("const parts = [downloadDateStamp(), clean(downloadFormatName(kind))];", body)
        self.assertIn("parts.push(name)", body)
        self.assertIn("join('_')", body)
        self.assertIn("DOWNLOAD_TITLE_MAX", body)
        self.assertIn("const DOWNLOAD_TITLE_MAX = 8;", APP_JS)

    def test_extension_defaults_to_png(self):
        self.assertIn("const extension = clean(ext) || 'png';", _helper_body())

    def test_date_stamp_is_zero_padded_local_date(self):
        stamp = _function_body("downloadDateStamp")
        self.assertIn("getFullYear()", stamp)
        self.assertIn("getMonth() + 1", stamp)
        self.assertIn("getDate()", stamp)
        self.assertIn("padStart(2, '0')", stamp)

    def test_every_editor_format_has_a_short_name(self):
        names = _block("const DOWNLOAD_FORMAT_NAMES = {", "};")
        for key, short in (("default", "編輯CG"), ("broadcast_left", "播出鏡面左"),
                           ("broadcast_right", "播出鏡面右"), ("ten_cover", "十點雙切"),
                           ("ten_cover_full", "十點滿版"), ("yt_live_cover", "YT直播"),
                           ("yt_hourly_cover", "YT整點"), ("yt_hot_cover", "YT熱搜")):
            with self.subTest(key=key):
                self.assertIn(f"{key}: '{short}'", names)

    def test_reporter_default_format_is_plain_cg(self):
        body = _function_body("downloadFormatName")
        self.assertIn("state.currentRole !== '編輯'", body)
        self.assertIn("return 'CG'", body)

    def test_title_source_covers_cover_yt_and_general_cg(self):
        body = _function_body("downloadTitleSource")
        self.assertIn("coverTitleLeft", body)
        self.assertIn("ytCoverTitle", body)
        self.assertIn(r"\[標題\]", body)
        self.assertIn("field-variable", body)


class DownloadNameFieldTests(unittest.TestCase):
    def test_both_result_areas_have_an_optional_name_field(self):
        for element_id in ("downloadName", "downloadNameAdvanced"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', INDEX_HTML)
        self.assertEqual(INDEX_HTML.count('id="downloadName"'), 1)

    def test_helper_reads_the_field_of_the_current_page(self):
        body = _function_body("customDownloadName")
        self.assertIn("state.currentPage === 2", body)
        self.assertIn("downloadNameAdvanced", body)
        self.assertIn("downloadName", body)


def _block(start: str, end: str) -> str:
    head = APP_JS.index(start)
    return APP_JS[head:APP_JS.index(end, head) + len(end)]


def _function_body(name: str) -> str:
    return _block(f"function {name}(", "\n}")


def _helper_body() -> str:
    return _function_body("downloadFileName")


if __name__ == "__main__":
    unittest.main()
