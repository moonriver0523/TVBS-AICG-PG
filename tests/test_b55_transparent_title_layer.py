"""B55 修法甲（2026-09-20 使用者裁決，帳本「0917 積壓」批次）：單張「原圖放置」＋
AI 標題＋provider=="gpt" 時，不再靠差異遮罩回貼（見 test_b55_photo_placement_protection.py／
test_b55_yt_cover_photo_protection.py，兩者從這次起改成專測 provider=="gemini" 那條路），
改請模型只回一張**透明底的標題圖層**，程式疊到未經觸碰的原圖上。

為什麼要換做法：2026-09-16 實拍量到差異遮罩那條路的 change_ratio 在十點滿版創意 0 級
就有 68.1%（見 MASTER-列管清單.md 的 B55 那列），遠超門檻 0.5——「請模型不要重畫」這件事
prompt 語氣再重都沒用，模型的生成方式本來就是整張重新畫一遍。透明底圖層讓模型完全不用
碰照片本身，保證來自 alpha 通道而不是事後比對，理論上不會有這個問題。

⚠️ 這個結論**還沒有付費實測驗證**：google/gemini-3-pro-image 沒有 background 參數
（本 session 查 OpenRouter /api/v1/images/models 得到），openai/gpt-image 系列公告
支援 background: transparent/opaque/auto。所以只在 provider=="gpt" 時使用；
provider=="gemini" 維持原本的差異遮罩回貼（哪怕那條路本來就常態超標）。
模型是否真的會吐出乾淨的透明底（alpha 通道乾淨、沒有半透明的背景色塊、文字品質不因為
沒有背景參照而變差）**沒有打過任何一次真正的付費生圖驗證**——這裡測的是三道閘本身的
邏輯與資料流接線是否正確，不是模型行為本身。

四道閘（見 compose._overlay_title_layer_core）：
(a) 模型必須真的回透明底——alpha 全不透明視為模型忽略了 background=transparent。
(b) 保護區（頁首帶／Logo／角標）內 alpha 必須全為 0——那些位置由程式後貼，模型碰了就擋。
(c) 面積防呆：可疊區域裡非透明像素比例超過門檻＝模型畫的是整片背景不是標題。
(d) 空圖層防呆：可疊區域裡一個像素都沒畫＝疊出來會是一張沒有標題的原圖。
任何一道沒過就丟 ComposeError，經 main._compose_error_status 轉成 400（使用者能自己
重試，不是程式錯誤）。

(d) 與「疊圖前先把低於門檻的 alpha 歸零」都是 2026-09-20 獨立複查（gpt-5.6-sol）之後
補的——原本只有 (a)(b)(c) 三道，而那三道全是「畫太多／畫錯地方」的上限，放行之後疊出來
的東西對不對完全沒有人驗。見 OverlayTitleLayerIndependentReviewTests 的兩支說明。
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
os.environ.setdefault("NEWS_IMAGE_API_KEY", "b55-layer-test-key")

import compose  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)

RED = (200, 30, 30)


def _headers() -> dict:
    return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}


def _data_url(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _rgb_png(colour, size) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


def _rgba_layer_png(size, *, opaque_box=None, opaque_colour=(255, 255, 255, 255)) -> bytes:
    """做一張透明底的標題圖層：全透明，只在 opaque_box 那塊畫實心色（模擬標題）。"""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    if opaque_box is not None:
        ImageDraw.Draw(img).rectangle(opaque_box, fill=opaque_colour)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class OverlayTitleLayerCoreUnitTests(unittest.TestCase):
    """直接測 compose._overlay_title_layer_core／overlay_title_layer_over_cover_band，
    不繞經任何端點——三道閘與疊圖結果的最小驗證。"""

    def setUp(self):
        self.band_top_ratio = compose.cover_title_band_top_ratio()
        self.width, self.height = compose.COVER_CANVAS
        self.band_top = round(self.height * self.band_top_ratio)
        self.base = _rgb_png(RED, (self.width, self.height))

    def test_pixels_outside_the_layer_are_bit_exact_with_base(self):
        """alpha=0 的地方保證是逐位元原圖，不是「很像」——這是這條路跟差異遮罩
        最本質的差別，直接斷言像素值而不是「看起來對不對」。"""
        band_mid = self.band_top + (self.height - self.band_top) // 2
        box = [200, band_mid - 20, 500, band_mid + 20]
        layer = _rgba_layer_png((self.width, self.height), opaque_box=box)
        out = compose.overlay_title_layer_over_cover_band(
            self.base, layer, band_top_ratio=self.band_top_ratio,
        )
        img = Image.open(io.BytesIO(out)).convert("RGB")
        base_img = Image.open(io.BytesIO(self.base)).convert("RGB")
        # 遠離 box 的一點，包含字帶內、字帶外，都必須跟 base 逐位元相同
        for point in ((10, 10), (self.width - 10, self.height - 10), (10, band_mid)):
            with self.subTest(point=point):
                self.assertEqual(img.getpixel(point), base_img.getpixel(point))
        # box 內：疊上去的是圖層的實心色
        self.assertEqual(img.getpixel((box[0] + 10, box[1] + 10)), (255, 255, 255))

    def test_fully_opaque_layer_is_rejected_as_ignoring_transparent_background(self):
        """(a) 模型忽略了 background=transparent、整張畫實心——擋下，不悄悄疊上去。"""
        layer = _rgb_png((10, 10, 10), (self.width, self.height))  # 沒有 alpha，convert 後全不透明
        with self.assertRaises(compose.ComposeError) as ctx:
            compose.overlay_title_layer_over_cover_band(
                self.base, layer, band_top_ratio=self.band_top_ratio,
            )
        self.assertIn("沒有回傳透明底的標題圖層", str(ctx.exception))

    def test_painting_inside_the_protected_header_band_is_rejected(self):
        """(b) 保護區內一個像素都不准畫——不是面積門檻，畫了就擋。"""
        layer = _rgba_layer_png(
            (self.width, self.height), opaque_box=[0, 0, self.width, self.band_top],
        )
        with self.assertRaises(compose.ComposeError) as ctx:
            compose.overlay_title_layer_over_cover_band(
                self.base, layer, band_top_ratio=self.band_top_ratio,
            )
        self.assertIn("保留給程式後貼元素", str(ctx.exception))

    def test_painting_too_much_of_the_editable_area_is_rejected(self):
        """(c) 面積防呆：字帶以下大半都不透明＝模型畫的是背景不是標題。"""
        # box 的上緣刻意離開 band_top 幾個像素，避免跟保護框共用邊界那一列像素
        # 同時觸發 (b)（那條規則本來就是只要有一個像素重疊就擋，不是這裡要驗的）。
        layer = _rgba_layer_png(
            (self.width, self.height),
            opaque_box=[0, self.band_top + 4, self.width, self.height],
        )
        with self.assertRaises(compose.ComposeError) as ctx:
            compose.overlay_title_layer_over_cover_band(
                self.base, layer, band_top_ratio=self.band_top_ratio, max_paint_ratio=0.5,
            )
        self.assertIn("標題圖層畫的範圍過大", str(ctx.exception))

    def test_small_localized_paint_passes_under_the_ratio_cap(self):
        band_mid = self.band_top + (self.height - self.band_top) // 2
        layer = _rgba_layer_png(
            (self.width, self.height), opaque_box=[200, band_mid - 20, 500, band_mid + 20],
        )
        # 不應該丟例外
        compose.overlay_title_layer_over_cover_band(
            self.base, layer, band_top_ratio=self.band_top_ratio, max_paint_ratio=0.5,
        )

    def test_mismatched_layer_size_is_resized_before_compositing(self):
        small_layer = _rgba_layer_png((960, 540), opaque_box=[100, 300, 300, 350])
        out = compose.overlay_title_layer_over_cover_band(
            self.base, small_layer, band_top_ratio=self.band_top_ratio,
        )
        img = Image.open(io.BytesIO(out))
        self.assertEqual(img.size, compose.COVER_CANVAS)

    def test_output_has_no_alpha_channel_left_over(self):
        """回傳一律是 RGB PNG——疊完就是成品，不該把透明通道漏給下游的置框／貼 Logo。"""
        band_mid = self.band_top + (self.height - self.band_top) // 2
        layer = _rgba_layer_png(
            (self.width, self.height), opaque_box=[200, band_mid - 20, 500, band_mid + 20],
        )
        out = compose.overlay_title_layer_over_cover_band(
            self.base, layer, band_top_ratio=self.band_top_ratio,
        )
        self.assertEqual(Image.open(io.BytesIO(out)).mode, "RGB")


class OverlayTitleLayerIndependentReviewTests(unittest.TestCase):
    """2026-09-20 獨立複查（gpt-5.6-sol）抓到、team-lead 實測重現後補的兩個洞。

    這兩個都是「三道閘全過、程式回傳成功」，所以原本的測試一題都不會紅——它們全部
    在驗「該擋的有沒有擋」，沒有一題在驗「放行之後疊出來的東西對不對」。
    """

    def setUp(self):
        self.band_top_ratio = compose.cover_title_band_top_ratio()
        self.width, self.height = compose.COVER_CANVAS
        self.band_top = round(self.height * self.band_top_ratio)
        self.base = _rgb_png(RED, (self.width, self.height))

    def _layer(self, img):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_a_uniform_sub_threshold_alpha_wash_cannot_tint_the_photo(self):
        """洞一：判定門檻與疊圖用的 alpha 必須是同一套標準。

        三道閘一律用 `alpha > TITLE_LAYER_ALPHA_THRESHOLD` 判定「模型有沒有畫」，
        但 alpha_composite 吃原始 alpha。修正前，一張全畫布 alpha=16 的薄層三道閘
        全過（處處算「沒畫」），疊圖時卻以 16/255 把整張照片染色——實測紅底
        (255,0,0) 變成 (239,0,16)，**連保護區都染**。這直接打破這條路唯一的賣點
        「alpha=0 的像素定義上就是模型沒動過」。

        低 alpha 不是只有惡意情境才有：layer 尺寸與 base 不符時的 LANCZOS 縮放，
        本來就會在字的邊緣內插出一圈 1~15 的殘值。
        """
        threshold = compose.TITLE_LAYER_ALPHA_THRESHOLD
        layer = Image.new("RGBA", (self.width, self.height), (0, 0, 255, threshold))
        # 可疊區放一塊真正的標題，否則會先被「空圖層」那道擋下，測不到這一項。
        title_box = [200, self.band_top + 50, 800, self.band_top + 150]
        ImageDraw.Draw(layer).rectangle(title_box, fill=(255, 255, 255, 255))

        out = compose.overlay_title_layer_over_cover_band(
            self.base, self._layer(layer), band_top_ratio=self.band_top_ratio,
        )
        img = Image.open(io.BytesIO(out)).convert("RGB")
        self.assertEqual(
            img.getpixel((10, 10)), RED,
            "保護區被低 alpha 薄霧染色了——判定門檻與疊圖標準沒有對齊",
        )
        self.assertEqual(
            img.getpixel((self.width - 20, self.height - 20)), RED,
            "可疊區裡『沒畫到』的地方也被染色了，原圖不再是逐位元保留",
        )
        self.assertEqual(
            img.getpixel((300, self.band_top + 100)), (255, 255, 255),
            "真正畫上去的標題反而不見了——歸零歸過頭",
        )

    def test_a_fully_transparent_layer_is_rejected_instead_of_silently_returning_the_photo(self):
        """洞二：前三道閘全是「畫太多／畫錯地方」的上限，沒有一道管「畫太少」。

        模型回一張完全透明的圖時：(a) alpha 最小值 0、(b) 沒有畫過的像素、
        (c) 比例 0——三道全過，程式**成功回傳一張跟原圖一模一樣、一個字都沒有的
        成品**。那比 400 更糟：400 使用者看得見，靜默的無字成品會被當成品拿去上鏡。
        """
        layer = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        with self.assertRaises(compose.ComposeError) as ctx:
            compose.overlay_title_layer_over_cover_band(
                self.base, self._layer(layer), band_top_ratio=self.band_top_ratio,
            )
        self.assertIn("空的", str(ctx.exception))

    def test_a_layer_painted_only_inside_the_protected_band_is_still_rejected(self):
        """補洞二時要小心別把 (b) 弄鬆：只在保護區畫東西仍然必須被 (b) 擋下，
        不能因為「可疊區是空的」就改由新的那道回報、更不能放行。"""
        layer = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        ImageDraw.Draw(layer).rectangle(
            [100, 10, 400, self.band_top - 10], fill=(255, 255, 255, 255),
        )
        with self.assertRaises(compose.ComposeError) as ctx:
            compose.overlay_title_layer_over_cover_band(
                self.base, self._layer(layer), band_top_ratio=self.band_top_ratio,
            )
        self.assertIn("保留給程式後貼元素", str(ctx.exception))

    def test_the_empty_layer_guard_reaches_the_endpoint_as_400(self):
        """空圖層也要跟其他三道一樣經 _compose_error_status 轉成 400，不是 500。"""
        self.assertEqual(
            main._compose_error_status(
                compose.ComposeError("生圖模型回傳的標題圖層是空的（整張完全透明，沒有畫任何標題）")
            ),
            400,
        )


class OverlayTitleLayerYtCoverUnitTests(unittest.TestCase):
    """YT 版本的三道閘沿用同一支核心，這裡只驗保護區換成 yt_cover_protect_boxes 有正確接上。"""

    def setUp(self):
        self.width, self.height = compose.YT_CANVAS
        self.base = _rgb_png(RED, (self.width, self.height))

    def test_painting_inside_the_top_cluster_is_rejected(self):
        boxes = compose.yt_cover_protect_boxes("news")
        x0, y0, x1, y1 = boxes[0]
        layer = _rgba_layer_png((self.width, self.height), opaque_box=[x0, y0, x1, y1])
        with self.assertRaises(compose.ComposeError):
            compose.overlay_title_layer_over_yt_cover(self.base, layer, layout="news")

    def test_localized_title_area_paint_succeeds(self):
        layer = _rgba_layer_png(
            (self.width, self.height),
            opaque_box=[round(self.width * 0.3), round(self.height * 0.82),
                        round(self.width * 0.6), round(self.height * 0.88)],
        )
        out = compose.overlay_title_layer_over_yt_cover(self.base, layer, layout="news")
        img = Image.open(io.BytesIO(out)).convert("RGB")
        base_img = Image.open(io.BytesIO(self.base)).convert("RGB")
        self.assertEqual(img.getpixel((10, self.height - 10)), base_img.getpixel((10, self.height - 10)))


class TenCoverEndpointWiringTests(unittest.TestCase):
    """透過 /api/editor/cover 端點驗證 provider=="gpt" 時真的走上透明底圖層這條路
    （note 換了、transparent_background 旗標設了、失敗會被轉成 400）。"""

    BODY = {
        "title_left": "測試標題", "title_right": "", "layout": "full",
        "mode": "ai", "title_creativity": 1, "provider": "gpt",
        "date_text": "2026/09/16",
    }

    def _post(self, body, fake_raw):
        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "resolve_cover_visuals", return_value=("景", "景")):
            return client.post("/api/editor/cover", json=body, headers=_headers())

    def test_the_request_asks_for_a_transparent_background_and_the_layer_only_note(self):
        captured = {}

        def fake_raw(req):
            captured["req"] = req
            band_top = round(compose.COVER_CANVAS[1] * compose.cover_title_band_top_ratio())
            band_mid = band_top + (compose.COVER_CANVAS[1] - band_top) // 2
            layer = _rgba_layer_png(
                compose.COVER_CANVAS, opaque_box=[200, band_mid - 20, 700, band_mid + 20],
            )
            return SimpleNamespace(
                image_data_base64=base64.b64encode(layer).decode(), model="fake", mime_type="image/png",
            )

        body = {**self.BODY, "slot_left": [{"data_url": _data_url(_rgb_png(RED, (640, 640))), "purpose": "asis"}]}
        res = self._post(body, fake_raw)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(captured["req"].transparent_background)
        self.assertIn("TRANSPARENT OVERLAY", captured["req"].prompt)
        # 兩份 note 互斥：矛盾的「重現整張照片」措辭不該同時出現
        self.assertNotIn("THE ATTACHED IMAGE IS THE FINISHED PICTURE", captured["req"].prompt)

    def test_a_fully_opaque_response_is_rejected_with_400(self):
        def fake_raw(req):
            return SimpleNamespace(
                image_data_base64=base64.b64encode(_rgb_png((10, 10, 10), compose.COVER_CANVAS)).decode(),
                model="fake", mime_type="image/png",
            )

        body = {**self.BODY, "slot_left": [{"data_url": _data_url(_rgb_png(RED, (640, 640))), "purpose": "asis"}]}
        res = self._post(body, fake_raw)
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("透明", res.text)

    def test_photo_pixels_outside_the_title_area_survive_bit_exact(self):
        def fake_raw(req):
            band_top = round(compose.COVER_CANVAS[1] * compose.cover_title_band_top_ratio())
            band_mid = band_top + (compose.COVER_CANVAS[1] - band_top) // 2
            layer = _rgba_layer_png(
                compose.COVER_CANVAS, opaque_box=[200, band_mid - 20, 700, band_mid + 20],
            )
            return SimpleNamespace(
                image_data_base64=base64.b64encode(layer).decode(), model="fake", mime_type="image/png",
            )

        body = {**self.BODY, "slot_left": [{"data_url": _data_url(_rgb_png(RED, (640, 640))), "purpose": "asis"}]}
        res = self._post(body, fake_raw)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        cover = Image.open(io.BytesIO(base64.b64decode(data["image_data_base64"]))).convert("RGB")
        w, h = cover.size
        self.assertEqual(cover.getpixel((w // 2, h - 20)), RED)


class YtCoverEndpointWiringTests(unittest.TestCase):
    """/api/editor/yt-cover：provider=="gpt" 時單則、剛好 1 張原圖放置也走透明底圖層。"""

    def _post(self, body, fake_raw):
        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "derive_yt_cover_plan", return_value={"visual": "景"}):
            return client.post("/api/editor/yt-cover", json=body, headers=_headers())

    def test_single_asis_gpt_uses_the_transparent_layer_path(self):
        """四個 YT 版型都要真的送出旗標與專用 note，不是只回 200。

        2026-09-20 獨立複查（gpt-5.6-sol）點名：這支原本只斷言 status_code == 200，
        fake_raw 完全不看 req——YT／gpt 這條路就算漏設 transparent_background、
        漏換 with_title_layer_note，測試照樣全綠。而 5 支既有測試又剛好在同一次改動裡
        被切到 provider=="gemini"，等於**新的預設路徑（YtCoverRequest.provider 預設
        就是 gpt）失去端對端覆蓋**。改成逐版型檢查 request 本身。
        """
        for layout in ("news", "hourly", "hot", "live24"):
            with self.subTest(layout=layout):
                seen = []

                def fake_raw(req):
                    seen.append(req)
                    w, h = compose.YT_CANVAS
                    layer = _rgba_layer_png(
                        (w, h),
                        opaque_box=[round(w * 0.3), round(h * 0.82), round(w * 0.6), round(h * 0.88)],
                    )
                    return SimpleNamespace(
                        image_data_base64=base64.b64encode(layer).decode(),
                        model="fake", mime_type="image/png",
                    )

                body = {
                    "layout": layout, "title_mode": "ai", "creativity": 1, "provider": "gpt",
                    "date_text": "2026/09/16", "title": "前段 後段",
                    "reference_images": [
                        {"data_url": _data_url(_rgb_png(RED, (640, 640))), "purpose": "asis"}
                    ],
                }
                res = self._post(body, fake_raw)
                self.assertEqual(res.status_code, 200, res.text)
                self.assertTrue(seen, f"{layout}：根本沒有打到生圖端")
                req = seen[-1]
                self.assertTrue(
                    req.transparent_background,
                    f"{layout}：transparent_background 沒有設，模型不會回透明底",
                )
                self.assertIn(
                    "TRANSPARENT OVERLAY", req.prompt,
                    f"{layout}：沒有換成 with_title_layer_note 的專用 note",
                )
                self.assertNotIn(
                    "Reproduce it as the picture", req.prompt,
                    f"{layout}：舊的 AI_TITLE_BASE_IMAGE_NOTE 還在，兩句話互相矛盾",
                )

    def test_single_asis_gpt_full_opaque_response_is_rejected(self):
        def fake_raw(req):
            return SimpleNamespace(
                image_data_base64=base64.b64encode(_rgb_png((10, 10, 10), compose.YT_CANVAS)).decode(),
                model="fake", mime_type="image/png",
            )

        body = {
            "layout": "news", "title_mode": "ai", "creativity": 1, "provider": "gpt",
            "date_text": "2026/09/16", "title": "前段 後段",
            "reference_images": [{"data_url": _data_url(_rgb_png(RED, (640, 640))), "purpose": "asis"}],
        }
        res = self._post(body, fake_raw)
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("透明", res.text)


class TransportWiringTests(unittest.TestCase):
    """再往下一層：transparent_background 旗標真的有送進 OpenRouter payload／原生 SDK kwargs。"""

    def test_openrouter_payload_carries_background_for_gpt_image_models(self):
        req = main.ImageGenerateRequest(
            prompt="x", provider="gpt", aspect_ratio="16:9", transparent_background=True,
        )
        captured = {}

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                import json
                return json.dumps(
                    {"data": [{"b64_json": base64.b64encode(_rgb_png(RED, (100, 100))).decode(), "media_type": "image/png"}]}
                ).encode("utf-8")

        def fake_urlopen(request, **_kwargs):
            import json
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _FakeResponse()

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), \
             patch.object(main, "urlopen", side_effect=fake_urlopen):
            main.generate_via_openrouter("openai/gpt-image-2.5-sunburst", req)
        self.assertEqual(captured["payload"].get("background"), "transparent")

    def test_openrouter_payload_omits_background_for_non_gpt_models_even_if_flagged(self):
        """呼叫端理論上不會對 gemini 設這個旗標，但傳輸層自己也該多一層防呆，
        不要把只有 gpt-image 支援的參數送給不支援的模型換來一個 400。"""
        req = main.ImageGenerateRequest(
            prompt="x", provider="gemini", aspect_ratio="16:9", transparent_background=True,
        )
        captured = {}

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                import json
                return json.dumps(
                    {"data": [{"b64_json": base64.b64encode(_rgb_png(RED, (100, 100))).decode(), "media_type": "image/png"}]}
                ).encode("utf-8")

        def fake_urlopen(request, **_kwargs):
            import json
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _FakeResponse()

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), \
             patch.object(main, "urlopen", side_effect=fake_urlopen):
            main.generate_via_openrouter("google/gemini-3-pro-image", req)
        self.assertNotIn("background", captured["payload"])

    def test_native_gpt_image_generate_receives_background_kwarg(self):
        req = main.ImageGenerateRequest(
            prompt="x", provider="gpt", aspect_ratio="16:9", transparent_background=True,
        )
        captured = {}

        class _FakeResult:
            data = [SimpleNamespace(b64_json=base64.b64encode(_rgb_png(RED, (100, 100))).decode())]

        def fake_generate(**kwargs):
            captured.update(kwargs)
            return _FakeResult()

        with patch.object(main.openai_client.images, "generate", side_effect=fake_generate):
            main.generate_gpt_image(req, resolved_size="1280x720")
        self.assertEqual(captured.get("background"), "transparent")

    def test_native_gpt_image_generate_omits_background_kwarg_when_flag_is_off(self):
        req = main.ImageGenerateRequest(
            prompt="x", provider="gpt", aspect_ratio="16:9", transparent_background=False,
        )
        captured = {}

        class _FakeResult:
            data = [SimpleNamespace(b64_json=base64.b64encode(_rgb_png(RED, (100, 100))).decode())]

        def fake_generate(**kwargs):
            captured.update(kwargs)
            return _FakeResult()

        with patch.object(main.openai_client.images, "generate", side_effect=fake_generate):
            main.generate_gpt_image(req, resolved_size="1280x720")
        self.assertNotIn("background", captured)


class NoteHelperUnitTests(unittest.TestCase):
    """editor_formats.with_title_layer_note 本身：注入位置、與 with_base_image_note 互斥。"""

    def test_injects_before_text_to_render_marker(self):
        import editor_formats

        prompt = "前段\n=== TEXT TO RENDER ===\n後段"
        out = editor_formats.with_title_layer_note(prompt)
        self.assertLess(out.index("TRANSPARENT OVERLAY"), out.index("=== TEXT TO RENDER"))

    def test_falls_back_to_prepending_when_marker_missing(self):
        import editor_formats

        out = editor_formats.with_title_layer_note("沒有標記的內容")
        self.assertTrue(out.startswith("=== YOU ARE DRAWING A TRANSPARENT OVERLAY"))

    def test_the_note_never_asks_the_model_to_reproduce_the_photo(self):
        import editor_formats

        self.assertNotIn("Reproduce it as the picture", editor_formats.AI_TITLE_LAYER_ONLY_NOTE)
        self.assertIn("Do NOT reproduce", editor_formats.AI_TITLE_LAYER_ONLY_NOTE)


if __name__ == "__main__":
    unittest.main()
