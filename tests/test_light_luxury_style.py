import datetime
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "app.js"
INDEX_HTML = ROOT / "index.html"


class LightLuxuryStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_JS.read_text(encoding="utf-8")

    def test_shared_style_is_registered_for_all_four_chart_types(self):
        self.assertIn("const LIGHT_LUXURY_TECH_STYLE = {", self.source)
        self.assertEqual(
            self.source.count("'淺色風格': [LIGHT_LUXURY_TECH_STYLE]"),
            4,
        )

    def test_style_keeps_the_verified_palette_and_material_contract(self):
        for token in (
            "銀藍香檳金",
            "#B4C7D5",
            "#D1DADB",
            "#A3B8CA",
            "#CBA352",
            "#D6CDAF",
            "#966F30",
            "brushed metal",
            "high-key studio lighting",
            "large dark-blue or black background",
            "rise and increase use red",
            "fall and decrease use green",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_cache_buster_moves_forward(self):
        """本地 script 的 ?v= 只能往前走，不能停在過期日期。

        2026-09-20：這支測試原本寫死 `assertIn('app.js?v=20260820a', html)`——名字叫
        「moves_forward」，做的卻是把快取字串**釘死在 08-20**。結果 app.js 一路改到
        09-16、hybrid.js 改到 09-06，`?v=` 卻動不了（一動這題就紅），老使用者的瀏覽器
        因此一直拿舊檔，正是 B81「正式站前端看起來落後」的真正來源——伺服器上的檔
        其實是新的（curl 驗過與 exp HEAD 逐位元組相同）。

        改成只檢查「格式合法且不早於最後一次確認的日期」：之後把 ?v= 往後調不用回來
        改測試（日期更大就過），但忘記調、或不小心往回調就會紅。
        """
        html = INDEX_HTML.read_text(encoding="utf-8")
        # 最後一次人工確認快取字串與實際檔案同步的日期（2026-09-20）。
        # 要往後調這個下限時，請先確認當下 index.html 裡的 ?v= 真的也跟著調了。
        floor = 20260920
        for script in ("app.js", "hybrid.js"):
            with self.subTest(script=script):
                match = re.search(
                    re.escape(script) + r"\?v=(\d{8})([a-z]?)\"", html
                )
                self.assertIsNotNone(
                    match, f"{script} 的 <script> 少了 ?v= 快取字串"
                )
                stamp = int(match.group(1))
                datetime.datetime.strptime(match.group(1), "%Y%m%d")
                self.assertGreaterEqual(
                    stamp,
                    floor,
                    f"{script} 的 ?v={match.group(1)} 比下限 {floor} 還舊——"
                    "改過這支 js 就要把 ?v= 一起往後調，否則使用者拿到的是快取的舊檔",
                )


if __name__ == "__main__":
    unittest.main()
