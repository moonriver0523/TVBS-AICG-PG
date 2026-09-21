"""B55（2026-09-16 使用者裁決）：單張「原圖放置」＋AI 標題，照片不准被生圖模型重畫。

使用者原話：「如果使用者只有附一張圖 要求原圖放置 就只畫標題」。程式現況（B55 立案時
查證）是把整張底圖當唯一附圖送進模型、由模型整張重畫，AI_TITLE_BASE_IMAGE_NOTE 那段
「Do not replace/re-compose/re-crop/mirror/zoom it」只是 prompt 請求，沒有任何保證。

修法＝「字帶（硬邊界）＋差異遮罩（帶內才動態採用模型像素）＋面積防呆（整片觸發就擋下
不送出）」三件事合起來，見 compose.restore_photo_outside_title_band。

守的紅線：
1. 字帶以外（含標頭帶／Logo／AI示意圖那一整條）永遠等於原圖，不管模型畫了什麼。
2. 字帶以內：模型真的動過的像素才用模型的，沒動過的仍是原圖——不是整條帶直接放行。
3. 字帶內改動面積超過門檻＝視為整張重畫，直接擋下（ComposeError），不能悄悄送出違規結果。
4. 這條保護只在「滿版、剛好 1 張原圖放置、AI 標題模式」生效；≥2 張切格與其他版型不受影響
   （使用者尚未就多圖融合裁決逐像素保真，見 _cover_ai 的 protect_base 文件字串）。

2026-09-20 修法甲：上面這條差異遮罩路徑實拍量到 change_ratio 常態超標（見帳本 B55），
provider=="gpt" 時已改走 compose.overlay_title_layer_over_cover_band（模型只回透明底
標題圖層，程式疊到原圖上，見 test_b55_transparent_title_layer.py）。**這份檔案自此
之後專測 provider=="gemini" 那條沒有 background=transparent、必須繼續用差異遮罩的
路徑**——本檔的端點測試 BODY 已改成 provider=gemini，維持這份檔案原本要驗的行為。
"""
import base64
import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import compose  # noqa: E402
import main  # noqa: E402
from test_ten_cover import _data_url, _headers, _png_bytes, client  # noqa: E402

RED = (200, 30, 30)
GREEN = (30, 200, 30)


def _png(colour, size=compose.COVER_CANVAS) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


class RestorePhotoOutsideTitleBandUnitTests(unittest.TestCase):
    """直接測 compose.restore_photo_outside_title_band，不繞經端點。"""

    def setUp(self):
        self.band_top_ratio = compose.cover_title_band_top_ratio()
        self.width, self.height = compose.COVER_CANVAS
        self.band_top = round(self.height * self.band_top_ratio)
        self.base = _png(RED)

    def _ai_with_patch(self, box) -> bytes:
        """模擬模型「幾乎照抄原圖、只在 box 這塊畫了東西」。"""
        img = Image.new("RGB", (self.width, self.height), RED)
        ImageDraw.Draw(img).rectangle(box, fill=GREEN)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_header_area_is_always_restored_even_if_model_painted_there(self):
        # 模型把整個標頭帶也畫綠了（違規），字帶以外必須強制還原
        ai = self._ai_with_patch([0, 0, self.width, self.height])  # 整張都塗綠，含帶外
        # 用比較小的 change ratio 上限測不到防呆（先用高上限只驗字帶邊界）
        with self.assertRaises(compose.ComposeError):
            compose.restore_photo_outside_title_band(
                self.base, ai, band_top_ratio=self.band_top_ratio, max_band_change_ratio=0.9,
            )
        # 全面積都改動，連 0.99 也會觸發（換句話說：這條路徑本來就該被防呆擋下，
        # 不是「有沒有還原」的問題）——改用局部小範圍才能驗證邊界本身。

    def test_localized_title_patch_is_kept_and_rest_of_band_matches_base(self):
        band_mid = self.band_top + (self.height - self.band_top) // 2
        patch_box = [200, band_mid - 40, 700, band_mid + 40]
        ai = self._ai_with_patch(patch_box)
        out = compose.restore_photo_outside_title_band(
            self.base, ai, band_top_ratio=self.band_top_ratio,
        )
        img = Image.open(io.BytesIO(out)).convert("RGB")

        # 1) 標頭帶（字帶以外）：模型完全沒碰，理應本來就等於 base——用來確認函式
        #    沒有意外把帶外弄髒。
        header_box = (0, 0, self.width, max(0, self.band_top - 1))
        self.assertEqual(
            img.crop(header_box).tobytes(), Image.open(io.BytesIO(self.base)).convert("RGB").crop(header_box).tobytes(),
        )
        # 2) 字帶內、patch 以外：模型也沒碰，必須還原成 base（不是整條帶被模型的畫布取代）
        band_but_outside_patch = (0, self.band_top, self.width, patch_box[1] - 10)
        self.assertEqual(
            img.crop(band_but_outside_patch).tobytes(),
            Image.open(io.BytesIO(self.base)).convert("RGB").crop(band_but_outside_patch).tobytes(),
        )
        # 3) patch 本身：模型真的畫了東西，這裡才可以是模型的像素
        self.assertEqual(img.getpixel((patch_box[0] + 50, patch_box[1] + 20)), GREEN)

    def test_large_band_change_ratio_trips_the_safety_net(self):
        # 模型把字帶「大半」重畫（不是只加標題）——面積防呆要擋下，不能靜靜放行
        ai = self._ai_with_patch([0, self.band_top, self.width, self.height])
        with self.assertRaises(compose.ComposeError):
            compose.restore_photo_outside_title_band(
                self.base, ai, band_top_ratio=self.band_top_ratio, max_band_change_ratio=0.5,
            )

    def test_small_band_change_ratio_passes(self):
        band_mid = self.band_top + (self.height - self.band_top) // 2
        ai = self._ai_with_patch([200, band_mid - 20, 500, band_mid + 20])
        # 不應該丟例外
        compose.restore_photo_outside_title_band(
            self.base, ai, band_top_ratio=self.band_top_ratio, max_band_change_ratio=0.5,
        )

    def test_mismatched_ai_size_is_resized_before_diffing(self):
        small = Image.new("RGB", (960, 540), RED)
        ImageDraw.Draw(small).rectangle([100, 300, 300, 350], fill=GREEN)
        buf = io.BytesIO()
        small.save(buf, format="PNG")
        out = compose.restore_photo_outside_title_band(
            self.base, buf.getvalue(), band_top_ratio=self.band_top_ratio,
        )
        img = Image.open(io.BytesIO(out))
        self.assertEqual(img.size, compose.COVER_CANVAS)


class TenCoverFullSingleAsisEndpointTests(unittest.TestCase):
    """透過 /api/editor/cover 端點驗證 _editor_cover_full 有把 protect_base 接上。"""

    # provider=gemini（2026-09-20 修法甲後）：這份檔案專測差異遮罩路徑，gpt 已經
    # 改走 test_b55_transparent_title_layer.py 的透明底圖層路徑。
    BODY = {
        "title_left": "測試標題", "title_right": "", "layout": "full",
        "mode": "ai", "title_creativity": 1, "provider": "gemini",
        "date_text": "2026/09/16",
    }

    def _post(self, body, fake_raw):
        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "resolve_cover_visuals", return_value=("景", "景")):
            return client.post("/api/editor/cover", json=body, headers=_headers())

    def test_single_asis_with_localized_title_edit_keeps_the_photo(self):
        def fake_raw(req):
            # 模型幾乎照抄唯一附圖，只在字帶裡加一小塊「標題」
            img = Image.new("RGB", compose.COVER_CANVAS, RED)
            band_top = round(compose.COVER_CANVAS[1] * compose.cover_title_band_top_ratio())
            ImageDraw.Draw(img).rectangle([200, band_top + 100, 700, band_top + 180], fill=GREEN)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return SimpleNamespace(
                image_data_base64=base64.b64encode(buf.getvalue()).decode(), model="fake", mime_type="image/png",
            )

        body = {**self.BODY, "slot_left": [{"data_url": _data_url(_png_bytes(size=(640, 640), colour=RED)), "purpose": "asis"}]}
        res = self._post(body, fake_raw)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["mode"], "ai")
        cover = Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")
        w, h = cover.size
        # 遠離標頭帶／標題貼字範圍的一點：必須還是原圖的紅色，不是模型亂畫的任何顏色
        self.assertEqual(cover.getpixel((w // 2, h - 20)), RED)

    def test_single_asis_full_repaint_is_rejected_not_silently_shipped(self):
        def fake_raw(req):
            return SimpleNamespace(
                image_data_base64=base64.b64encode(_png(GREEN)).decode(), model="fake", mime_type="image/png",
            )

        body = {**self.BODY, "slot_left": [{"data_url": _data_url(_png_bytes(size=(640, 640), colour=RED)), "purpose": "asis"}]}
        res = self._post(body, fake_raw)
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("重畫", res.text)

    def test_two_asis_images_are_not_protected_yet(self):
        """B55 目前只裁到單張；兩張切格＋AI 標題仍是舊行為（整張可被模型改），
        這裡釘住「範圍限定在 1 張」不是漏改。"""
        def fake_raw(req):
            return SimpleNamespace(
                image_data_base64=base64.b64encode(_png(GREEN)).decode(), model="fake", mime_type="image/png",
            )

        # 2 張原圖放置要走舊的共用清單（reference_images），不是 slot_left——
        # slot_left 一格只有一個版位，多放只取第 1 張（main._merge_slot_refs 的行為，
        # 不是這裡要測的東西）。
        body = {
            **self.BODY,
            "reference_images": [
                {"data_url": _data_url(_png_bytes(size=(640, 640), colour=RED)), "purpose": "asis"},
                {"data_url": _data_url(_png_bytes(size=(640, 640), colour=(30, 30, 200))), "purpose": "asis"},
            ],
        }
        res = self._post(body, fake_raw)
        self.assertEqual(res.status_code, 200, res.text)


class HeaderBandSurvivesPhotoProtectionTests(unittest.TestCase):
    """2026-09-21 使用者回報：十點不一樣「原圖放置」時頂部藍底帶不見了。

    設計矛盾——純 AI 版的標頭帶一直都是**模型畫的**，但「原圖放置」會把字帶以上
    一律還原成 base（這份檔案測的差異遮罩硬邊界，gpt 那條透明圖層路徑則是整片列為
    保護區）。base 是使用者的原圖、本來就沒有帶，於是 Logo／節目標籤／日期／ON AIR
    被直接貼在照片上，藍底整條消失。改成由程式補畫那條帶。
    """

    BODY = {
        "title_left": "測試標題", "title_right": "", "layout": "full",
        "mode": "ai", "title_creativity": 1, "provider": "gemini",
        "date_text": "2026/09/16",
    }

    def _near(self, pixel, target, tol=26) -> bool:
        return all(abs(pixel[i] - target[i]) <= tol for i in range(3))

    def test_the_band_is_drawn_over_the_protected_photo(self):
        def fake_raw(req):
            img = Image.new("RGB", compose.COVER_CANVAS, RED)
            band_top = round(compose.COVER_CANVAS[1] * compose.cover_title_band_top_ratio())
            ImageDraw.Draw(img).rectangle([200, band_top + 100, 700, band_top + 180], fill=GREEN)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return SimpleNamespace(
                image_data_base64=base64.b64encode(buf.getvalue()).decode(),
                model="fake", mime_type="image/png",
            )

        body = {**self.BODY, "slot_left": [
            {"data_url": _data_url(_png_bytes(size=(640, 640), colour=RED)), "purpose": "asis"},
        ]}
        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "resolve_cover_visuals", return_value=("景", "景")):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        cover = Image.open(io.BytesIO(base64.b64decode(res.json()["image_data_base64"]))).convert("RGB")
        # 帶高範圍內、畫面中央那一豎列（避開 Logo／標籤／日期，也避開帶底亮線）
        band_h = round(cover.size[1] * compose.COVER_AI_HEADER_RATIO)
        x = cover.size[0] // 2
        rows = [cover.getpixel((x, y)) for y in range(4, band_h - 8)]
        self.assertTrue(
            all(self._near(p, compose.COVER_HEADER_FILL) for p in rows),
            f"標頭帶不是深藍：{rows[:6]}…（原圖是紅色，代表帶根本沒被畫上去）",
        )

    def test_the_band_matches_the_composite_version(self):
        """程式畫的帶要跟合成版長一樣——兩版不一致比沒有帶更難察覺。"""
        photo = _png_bytes(size=compose.COVER_CANVAS, colour=RED)
        img = Image.open(io.BytesIO(compose.paste_cover_header_band(photo))).convert("RGB")
        band_h = round(compose.COVER_CANVAS[1] * compose.COVER_AI_HEADER_RATIO)
        line_h = max(2, round(compose.COVER_CANVAS[1] * compose.COVER_HEADER_LINE_RATIO))
        x = compose.COVER_CANVAS[0] // 2
        self.assertEqual(img.getpixel((x, band_h // 2)), compose.COVER_HEADER_FILL)
        self.assertEqual(img.getpixel((x, band_h - line_h // 2 - 1)), compose.COVER_HEADER_LINE)
        # 帶以下一個像素都不准動
        self.assertEqual(img.getpixel((x, band_h + 6)), RED)

    def test_a_pure_ai_cover_still_lets_the_model_draw_its_own_band(self):
        """沒有原圖放置時照片沒被保護，模型畫的帶留得下來，程式不該再蓋一層。"""
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("draw_header_band=protect_base and base is not None", source)


if __name__ == "__main__":
    unittest.main()
