import pathlib
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
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('app.js?v=20260820a', html)


if __name__ == "__main__":
    unittest.main()
