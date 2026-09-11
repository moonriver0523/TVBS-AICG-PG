"""YT 封面底部壓色框改成開關、開的時候半透明（2026-09-08 使用者裁決；同日晚改預設開）。

守的紅線：
1. **預設開。** 不帶 `bottom_band` 時底帶區要看得到半透明的帶；明確傳 False 才是底圖原色。
2. **開的時候不是不透明。** 帶色壓上去後介於底圖色與帶色之間，照片仍透得出來。
3. **AI 版兩種措辭都要有。** 合成版靠 compose，AI 版只能靠 prompt——OFF 時模板必須明文
   「沒有色框」，否則模型看到「filling the frame behind the band」還是會畫一條出來。
4. **整點直播不適用。** 它的版面本來就沒有底帶，後端忽略、前端不顯示按鈕。
"""
import base64
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import compose  # noqa: E402
import editor_formats  # noqa: E402
import main  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402

MAIN_PY = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
APP_JS = (Path(__file__).resolve().parent.parent / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (Path(__file__).resolve().parent.parent / "index.html").read_text(encoding="utf-8")
BASE = (20, 120, 20)
# 底帶區、但遠離置中標題的筆畫：最左緣、最底一列
PROBE = (12, 1074)


def _png(size=(1920, 1080), colour=BASE) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _news(**kw) -> Image.Image:
    out = compose.compose_yt_cover(_png(), line1="大象來了", line2="10萬人塞爆士林",
                                   date_text="2026/09/08", **kw)
    return Image.open(io.BytesIO(out)).convert("RGB")


def _hot(**kw) -> Image.Image:
    out = compose.compose_yt_hot_cover(_png(), line1="大象來了", line2="10萬人塞爆士林", **kw)
    return Image.open(io.BytesIO(out)).convert("RGB")


class CompositeBandTests(unittest.TestCase):
    def test_on_is_the_default_and_off_leaves_the_photo_untouched(self):
        """2026-09-08 晚使用者：所有藍紅底套色預設改 ON。"""
        for name, fn in (("news", _news), ("hot", _hot)):
            with self.subTest(layout=name):
                self.assertNotEqual(fn().getpixel(PROBE), BASE, "預設沒畫帶")
                self.assertEqual(fn(bottom_band=False).getpixel(PROBE), BASE)
                self.assertEqual(fn(), fn(bottom_band=True))

    def test_on_is_semi_transparent_not_a_flat_colour(self):
        for name, img, fill in (("news", _news(bottom_band=True), compose.YT_BAND_FILL),
                                ("hot", _hot(bottom_band=True), compose.YT_HOT_BAND_FILL)):
            with self.subTest(layout=name):
                pixel = img.getpixel(PROBE)
                self.assertNotEqual(pixel, BASE, "開了就要看得到帶")
                self.assertNotEqual(pixel, fill, "不能是 100% 不透明")
                # 每個通道都落在底圖色與帶色之間（半透明混色的定義）
                for channel, (got, base, band) in enumerate(zip(pixel, BASE, fill)):
                    self.assertGreaterEqual(got, min(base, band), channel)
                    self.assertLessEqual(got, max(base, band), channel)

    def test_alpha_is_about_sixty_percent(self):
        self.assertEqual(compose.YT_BAND_ALPHA, 153)


class AiPromptTests(unittest.TestCase):
    def _prompt(self, body):
        seen = {}

        def fake_raw(image_req):
            seen["prompt"] = image_req.prompt
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png()).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        # 補畫面描述會真的打文字模型，這裡只驗 prompt 的底帶措辭，擋掉那一次呼叫
        with patch.object(main, "derive_yt_cover_plan", return_value={}):
            with patch.object(main, "generate_image_raw", side_effect=fake_raw):
                res = client.post("/api/editor/yt-cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return seen["prompt"]

    def _body(self, **kw):
        body = {"title": "大象來了 10萬人塞爆士林", "title_mode": "ai", "visual": ""}
        body.update(kw)
        return body

    def test_off_tells_the_model_there_is_no_band(self):
        """2026-09-08 晚預設改 ON，所以「關」要明確傳 False。"""
        for layout in ("news", "hot"):
            with self.subTest(layout=layout):
                prompt = self._prompt(self._body(layout=layout, bottom_band=False))
                self.assertIn("There is NO solid colour band", prompt)
                self.assertNotIn("behind the band", prompt)

    def test_on_asks_for_a_semi_transparent_band(self):
        for layout, colour in (("news", "deep-navy"), ("hot", "DEEP CRIMSON")):
            with self.subTest(layout=layout):
                prompt = self._prompt(self._body(layout=layout, bottom_band=True))
                self.assertIn("about 60% opaque", prompt)
                self.assertIn(colour, prompt)
                self.assertIn("behind the band", prompt)

    def test_hourly_prompt_still_renders_and_never_mentions_a_band(self):
        """整點版模板沒有底帶佔位；帶了開關也不能讓 format 炸掉或冒出帶子。"""
        prompt = self._prompt(self._body(layout="hourly", bottom_band=True, date_text="2026/09/08"))
        self.assertIn("No band behind them", prompt)
        self.assertNotIn("about 60% opaque", prompt)


class HourlyCompositeTests(unittest.TestCase):
    def test_hourly_compose_has_no_band_parameter_at_all(self):
        """整點版的合成函式本來就不畫底帶，沒有這個開關可調。"""
        import inspect
        self.assertNotIn("bottom_band", inspect.signature(compose.compose_yt_hourly_cover).parameters)


class FrontendTests(unittest.TestCase):
    def test_state_defaults_to_off(self):
        """2026-09-08 晚預設改 ON；2026-09-11 使用者再改回 OFF。

        理由：創意階梯上線後標題本身就有底板與描邊，再疊一條整幅底帶會互相打架。
        後端 YtCoverRequest.bottom_band 也是 False，兩邊必須一致。
        """
        self.assertRegex(APP_JS, r"ytBottomBand:\s*false")
        self.assertIn("bottom_band: bool = False", MAIN_PY)

    def test_field_is_sent_once_and_covers_the_recompose_path(self):
        # ytCoverFields() 同時餵生成與 recomposeYtCover，所以一處就夠
        self.assertIn("bottom_band: layout !== 'hourly' && state.ytBottomBand", APP_JS)

    def test_button_exists_and_hides_on_hourly(self):
        self.assertIn('id="ytBottomBandBtn"', INDEX_HTML)
        self.assertIn("toggleYtBottomBand()", INDEX_HTML)
        self.assertIn("layout !== 'hourly'", APP_JS)


class BandFieldHelperTests(unittest.TestCase):
    def test_hot_gets_the_crimson_clause_news_gets_navy(self):
        self.assertEqual(
            editor_formats.yt_cover_band_fields("hot", True)["band_clause"],
            editor_formats.YT_COVER_BAND_CLAUSE_HOT_ON,
        )
        self.assertEqual(
            editor_formats.yt_cover_band_fields("news", True)["band_clause"],
            editor_formats.YT_COVER_BAND_CLAUSE_NEWS_ON,
        )

    def test_off_is_the_same_clause_for_both(self):
        for layout in ("news", "hot"):
            with self.subTest(layout=layout):
                fields = editor_formats.yt_cover_band_fields(layout, False)
                self.assertEqual(fields["band_clause"], editor_formats.YT_COVER_BAND_CLAUSE_OFF)
                self.assertEqual(fields["band_imagery_tail"], "")


if __name__ == "__main__":
    unittest.main()
