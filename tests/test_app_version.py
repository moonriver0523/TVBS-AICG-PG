"""版本號機制（2026-09-09 使用者：V8.2 從來沒動過，要有真的會跟著改動走的版本號）。

規格：YYMMDD-XX，YY 取年份後兩碼，XX 從 01 起、換一天重新開始。
VERSION 檔是唯一真相源，index.html 上顯示的字串必須跟它一致——不然畫面上的
版本號又會變成一個沒人維護的常數，回到這次要修的問題。
"""

import datetime
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import bump_version  # noqa: E402


class AppVersionTest(unittest.TestCase):
    def setUp(self):
        self.version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_version_file_matches_the_required_format(self):
        self.assertRegex(self.version, r"^\d{6}-\d{2}$")

    def test_the_masthead_shows_exactly_the_version_file(self):
        match = re.search(r'<span id="appVersion"[^>]*>([^<]*)</span>', self.html)
        self.assertIsNotNone(match, "index.html 少了 id=appVersion 的版本標籤")
        self.assertEqual(match.group(1), self.version)

    def test_the_old_hardcoded_v8_2_is_gone(self):
        self.assertNotIn(">V8.2<", self.html)

    def test_a_new_day_restarts_the_counter(self):
        day = datetime.date(2026, 9, 10)
        self.assertEqual(bump_version.next_version("260909-07", day), "260910-01")

    def test_the_same_day_increments_and_stays_two_digits(self):
        day = datetime.date(2026, 9, 9)
        self.assertEqual(bump_version.next_version("260909-01", day), "260909-02")
        self.assertEqual(bump_version.next_version("260909-09", day), "260909-10")


if __name__ == "__main__":
    unittest.main()
