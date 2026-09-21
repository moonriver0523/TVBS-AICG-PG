"""B55 擴充到 YT 四種封面（2026-09-16 使用者裁決）：news／hourly／hot／live24 單則、
剛好 1 張原圖放置＋AI 標題時，照片不准被生圖模型整張重畫，機制與十點滿版
（見 tests/test_b55_photo_placement_protection.py）同一條規則，差別只在保護區怎麼算：

- 十點：一條簡單的水平字帶（COVER_HEADER_RATIO 以上）。
- YT 四版型：固定元素幾何差很多（news/hot 是頂端一叢＋右側 AI 標；hourly 多一塊卡在
  畫面中段的日期紅牌；live24 是左上角標＋右上兩層 Logo），所以改成「直接把真正的
  固定元素繪製函式在透明畫布上跑一次、量出實際碰到的像素外框」（見
  compose._render_fixed_elements_bbox），不是拿比例常數湊出來的猜測，更不是十點那組
  常數的複用。

面積防呆門檻沿用 compose.PHOTO_PROTECT_MAX_CHANGE_RATIO，四版型與十點共用同一個值，
不在這裡另外調。

守的紅線：
1. 四個版型各自的固定元素保護區都要落在該版型量出來的 bbox 聯集內，不是共用一條線。
2. 保護區以外：模型真的畫了東西才用模型像素，沒動過的仍是 base。
3. 可編輯區域改動面積超過門檻＝整張重畫，擋下（ComposeError），不能靜靜送出。
4. 這條保護只在「單則、剛好 1 張原圖放置」生效；雙則（兩格各自一張）與多圖切格不受影響。

2026-09-20 修法甲：provider=="gpt" 已改走 compose.overlay_title_layer_over_yt_cover
（透明底標題圖層），這份檔案的端點測試 BODY 已改成 provider=gemini，繼續驗差異遮罩
那條路徑；gpt 的透明底圖層改在 test_b55_transparent_title_layer.py 測。
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
os.environ.setdefault("NEWS_IMAGE_API_KEY", "yt-b55-test-key")

import compose  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def _headers() -> dict:
    # 整包跑時其他測試模組會在 import 期改寫 NEWS_IMAGE_API_KEY，執行時再讀才對得上
    # （同 tests/test_ten_cover.py 的 _headers()）。
    return {"X-API-Key": os.environ["NEWS_IMAGE_API_KEY"]}

RED = (200, 30, 30)
GREEN = (30, 200, 30)
LAYOUTS = ("news", "hourly", "hot", "live24")


def _png(colour, size=compose.YT_CANVAS) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


def _data_url(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


class ProtectBoxesUnitTests(unittest.TestCase):
    """protect_boxes 本身的幾何合理性：量得到、在畫布內、不會離譜地吃掉整個版面。"""

    def test_every_layout_has_at_least_one_box_within_canvas(self):
        w, h = compose.YT_CANVAS
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                boxes = compose.yt_cover_protect_boxes(
                    layout, original_audio=True, ai_translation=True, ai_note=True,
                )
                self.assertTrue(boxes)
                for x0, y0, x1, y1 in boxes:
                    self.assertGreaterEqual(x0, 0)
                    self.assertGreaterEqual(y0, 0)
                    self.assertLessEqual(x1, w)
                    self.assertLessEqual(y1, h)
                    self.assertLess(x0, x1)
                    self.assertLess(y0, y1)

    def test_hourly_has_a_separate_mid_screen_date_box_not_merged_into_top(self):
        """hourly 的日期紅牌卡在畫面中段，跟頂端 Logo/LIVE 章叢中間隔了一大段照片——
        必須是獨立一個 box，不能為了保這塊牌把中間整條都鎖住（那樣會鎖到不該鎖的照片）。

        2026-09-21 改寫：頂端原本量成**一個** union 框，這題就靠 `tops[0]`／`tops[1]`
        的順序假設抓間隙。現在左上 Logo 與右上 LIVE 章各自量框（見
        `compose._fixed_element_boxes`），頂端變成兩個框，順序假設不再成立。
        題目本身（日期牌獨立、中段照片沒被鎖）沒變，改成直接認出日期牌那一框。
        """
        boxes = compose.yt_cover_protect_boxes("hourly", ai_note=False)
        self.assertGreaterEqual(len(boxes), 3, "hourly 應該有左上 Logo、右上 LIVE 章、中段日期牌")
        h = compose.YT_CANVAS[1]
        # 日期牌是唯一落在畫面中段的那一框；其餘都貼在頂端。
        mid = [b for b in boxes if b[1] > h * 0.35]
        top = [b for b in boxes if b[1] <= h * 0.35]
        self.assertEqual(len(mid), 1, f"中段應該只有日期牌一框，實得 {mid}")
        self.assertTrue(top, "頂端應該還有 Logo 與 LIVE 章")
        self.assertGreater(
            mid[0][1] - max(b[3] for b in top), 0,
            "頂端元件與日期牌之間應該留有未保護的照片區域",
        )

    def test_the_top_elements_do_not_lock_the_photo_between_them(self):
        """B55 誤判真因（2026-09-21）：左右兩件量成一個 union 框，中間那一整條照片
        跟著被鎖，模型只要在那裡畫到標題上緣就被判成竄改、整張退回程式壓字。

        三個版型的頂端都是「一左一右」，中間必須留白。
        """
        h = compose.YT_CANVAS[1]
        for layout in ("news", "live24", "hourly"):
            with self.subTest(layout=layout):
                top = [
                    b for b in compose.yt_cover_protect_boxes(layout, ai_note=False)
                    if b[1] <= h * 0.35
                ]
                self.assertGreaterEqual(
                    len(top), 2, f"{layout} 頂端應該至少左右兩個獨立框，實得 {top}",
                )
                # 除了橫跨全幅的頂線（news 有一條）以外，左右兩件之間要有未保護的間隙
                gap_candidates = [b for b in top if b[2] - b[0] < compose.YT_CANVAS[0] * 0.9]
                self.assertGreaterEqual(len(gap_candidates), 2, f"{layout} 找不到左右兩件")
                left = min(gap_candidates, key=lambda b: b[0])
                right = max(gap_candidates, key=lambda b: b[0])
                self.assertGreater(
                    right[0] - left[2], 0,
                    f"{layout} 左右兩件之間應該留有未保護的照片（實得 {left} / {right}）",
                )

    def test_the_three_real_world_false_positives_are_now_outside_every_box(self):
        """2026-09-21 dev 後台三張被第 b 道閘擋下、整張退回程式壓字的圖層。

        三處違規外接框都是逐像素量出來的實際座標（73~82% 是 alpha 201 以上的實心
        筆畫，不是縮放毛邊）。它們畫的是標題自己的上緣，沒有壓到任何固定元素——
        舊的 union 框把元件之間的空白也鎖住，才會被判成竄改。

        這題釘的是「這三個座標不可以再落進任何保護框」。框如果哪天又被合併回去，
        這題會先紅。
        """
        cases = [
            ("live24", (1715, 298, 1767, 322), "右上 Logo 下方（Logo 底部只到 y=202）"),
            ("news", (1648, 320, 1884, 351), "右上斜標籤下方（斜標籤底部只到 y=165）"),
            ("news", (1223, 342, 1398, 351), "LIVE 章與斜標籤之間（486 ↔ 1554）"),
        ]
        for layout, (vx0, vy0, vx1, vy1), where in cases:
            with self.subTest(layout=layout, viol=(vx0, vy0, vx1, vy1)):
                for bx0, by0, bx1, by1 in compose.yt_cover_protect_boxes(layout, ai_note=False):
                    overlaps = vx0 < bx1 and bx0 < vx1 and vy0 < by1 and by0 < vy1
                    self.assertFalse(
                        overlaps,
                        f"{layout} {where}：違規框 {(vx0, vy0, vx1, vy1)} 又被 "
                        f"{(bx0, by0, bx1, by1)} 鎖住了",
                    )

    def test_protect_boxes_do_not_reach_into_the_title_zone(self):
        """title 固定畫在畫面下半（各版型 baseline 都在 0.79 以後），保護區不能誤伸進去，
        否則標題創意階梯會被鎖死。用一個保守下限（0.6）卡：任何 box 的底不該超過它。"""
        h = compose.YT_CANVAS[1]
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                boxes = compose.yt_cover_protect_boxes(
                    layout, original_audio=True, ai_translation=True, ai_note=True,
                )
                for box in boxes:
                    self.assertLess(box[3] / h, 0.6, f"{layout} 的保護框伸進了標題可能出現的下半版面：{box}")


class RestoreYtCoverPhotoUnitTests(unittest.TestCase):
    """直接測 compose.restore_yt_cover_photo，四個版型各跑一次。"""

    def _base(self):
        return _png(RED)

    def _ai_with_patch(self, box):
        img = Image.new("RGB", compose.YT_CANVAS, RED)
        ImageDraw.Draw(img).rectangle(box, fill=GREEN)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_localized_edit_outside_protect_boxes_is_kept_protected_area_untouched(self):
        w, h = compose.YT_CANVAS
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                base = self._base()
                protect_boxes = compose.yt_cover_protect_boxes(layout)
                # 挑一塊遠離所有保護框、落在畫面下半（標題可能落腳處）的 patch
                patch_box = [round(w * 0.3), round(h * 0.78), round(w * 0.6), round(h * 0.85)]
                ai = self._ai_with_patch(patch_box)
                out = compose.restore_yt_cover_photo(base, ai, layout=layout)
                img = Image.open(io.BytesIO(out)).convert("RGB")
                base_img = Image.open(io.BytesIO(base)).convert("RGB")

                # 保護框內：不管模型畫了什麼（這裡其實沒有動保護框，屬於自我一致性檢查），
                # 必須跟 base 一致
                for x0, y0, x1, y1 in protect_boxes:
                    if x1 - x0 <= 0 or y1 - y0 <= 0:
                        continue
                    self.assertEqual(
                        img.crop((x0, y0, x1, y1)).tobytes(),
                        base_img.crop((x0, y0, x1, y1)).tobytes(),
                        f"{layout} 保護框內的像素被動到了",
                    )
                # patch 本身：模型真的畫了東西，這裡才可以是模型的像素
                self.assertEqual(
                    img.getpixel((patch_box[0] + 20, patch_box[1] + 5)), GREEN,
                    f"{layout} patch 區域理應保留模型畫的內容",
                )

    def test_full_repaint_trips_the_safety_net_for_every_layout(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                base = self._base()
                ai = _png(GREEN)
                with self.assertRaises(compose.ComposeError):
                    compose.restore_yt_cover_photo(base, ai, layout=layout)

    def test_mismatched_ai_size_is_resized_before_diffing(self):
        base = self._base()
        small = Image.new("RGB", (960, 540), RED)
        ImageDraw.Draw(small).rectangle([100, 700 // 2, 300, 700 // 2 + 40], fill=GREEN)
        buf = io.BytesIO()
        small.save(buf, format="PNG")
        out = compose.restore_yt_cover_photo(base, buf.getvalue(), layout="news")
        img = Image.open(io.BytesIO(out))
        self.assertEqual(img.size, compose.YT_CANVAS)


class EndpointWiringTests(unittest.TestCase):
    """透過 /api/editor/yt-cover 端點確認 protect_base 判準（單則、剛好 1 張、非 dual）
    有正確接上，四版型各驗一輪成功案例＋一輪整張重畫被擋下；另外釘住雙則與多圖不受影響。
    """

    def _post(self, body, fake_raw):
        with patch.object(main, "generate_image_raw", side_effect=fake_raw), \
             patch.object(main, "derive_yt_cover_plan", return_value={"visual": "景"}):
            return client.post("/api/editor/yt-cover", json=body, headers=_headers())

    def _localized_fake_raw(self, layout):
        def fake_raw(req):
            img = Image.new("RGB", compose.YT_CANVAS, RED)
            w, h = compose.YT_CANVAS
            ImageDraw.Draw(img).rectangle(
                [round(w * 0.3), round(h * 0.8), round(w * 0.6), round(h * 0.86)], fill=GREEN,
            )
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return SimpleNamespace(
                image_data_base64=base64.b64encode(buf.getvalue()).decode(), model="fake", mime_type="image/png",
            )
        return fake_raw

    def _full_repaint_fake_raw(self):
        def fake_raw(req):
            return SimpleNamespace(
                image_data_base64=base64.b64encode(_png(GREEN)).decode(), model="fake", mime_type="image/png",
            )
        return fake_raw

    def _base_body(self, layout):
        # provider=gemini（2026-09-20 修法甲後）：gpt 已改走透明底圖層，這份檔案
        # 專測差異遮罩路徑，見檔頭說明。
        common = {
            "layout": layout, "title_mode": "ai", "creativity": 1, "provider": "gemini",
            "date_text": "2026/09/16",
        }
        if layout == "live24":
            common["title"] = "測試單行標題"
        else:
            common["title"] = "前段 後段"
        return common

    def test_single_asis_localized_edit_succeeds_for_every_layout(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                body = {
                    **self._base_body(layout),
                    "reference_images": [{"data_url": _data_url(_png(RED, size=(640, 640))), "purpose": "asis"}],
                }
                res = self._post(body, self._localized_fake_raw(layout))
                self.assertEqual(res.status_code, 200, res.text)

    def test_single_asis_full_repaint_is_rejected_for_every_layout(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                body = {
                    **self._base_body(layout),
                    "reference_images": [{"data_url": _data_url(_png(RED, size=(640, 640))), "purpose": "asis"}],
                }
                res = self._post(body, self._full_repaint_fake_raw())
                self.assertEqual(res.status_code, 400, res.text)
                self.assertIn("重畫", res.text)

    def test_two_asis_images_are_not_protected(self):
        """B55 只裁到「剛好 1 張」；2 張切格仍是舊行為（整張可被模型改），這裡釘住範圍。"""
        body = {
            **self._base_body("news"),
            "reference_images": [
                {"data_url": _data_url(_png(RED, size=(640, 640))), "purpose": "asis"},
                {"data_url": _data_url(_png((30, 30, 200), size=(640, 640))), "purpose": "asis"},
            ],
        }
        res = self._post(body, self._full_repaint_fake_raw())
        self.assertEqual(res.status_code, 200, res.text)


if __name__ == "__main__":
    unittest.main()
