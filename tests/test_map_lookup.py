"""真實地圖底圖：投影數學、圖磚上限、授權標註。

存在理由（2026-09-04 實測，數字是量出來的不是估的）：消化端照規則寫出了經緯度，
但那些座標來自模型記憶——拿 Nominatim 的實際座標比對，「基隆廟口」只差 107 公尺，
「西定路」差 1,470 公尺，「大武崙」差 2,296 公尺。地標名氣越小越不可靠，而
1.5 公里在市區地圖上就是標到別的行政區去。地理是可查的事實，不該讓模型憑印象。

網路一律不碰：geocode 與圖磚都靠注入替身，測試不能依賴外部服務的可用性。
"""

import io
import math
import unittest
from unittest import mock

import map_lookup

# 三個地點的實際座標（Nominatim 2026-09-04 查得），拿來當投影計算的基準
MIAOKOU = (25.1290607, 121.74391)
XIDING = (25.1368202, 121.7324353)
DAWULUN = (25.1421993, 121.7034773)
KEELUNG = [MIAOKOU, XIDING, DAWULUN]


def _blank_tile() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (map_lookup.TILE_SIZE, map_lookup.TILE_SIZE), (200, 220, 200)).save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


class ProjectionTests(unittest.TestCase):
    def test_more_easterly_point_lands_further_right(self):
        centre = XIDING
        east = map_lookup.project(MIAOKOU, centre, 13, 1024, 576)
        west = map_lookup.project(DAWULUN, centre, 13, 1024, 576)
        self.assertGreater(east[0], west[0])

    def test_more_northerly_point_lands_higher(self):
        centre = XIDING
        north = map_lookup.project(DAWULUN, centre, 13, 1024, 576)
        south = map_lookup.project(MIAOKOU, centre, 13, 1024, 576)
        self.assertLess(north[1], south[1])

    def test_the_centre_lands_in_the_middle(self):
        px, py = map_lookup.project(XIDING, XIDING, 13, 1024, 576)
        self.assertEqual((px, py), (512, 288))

    def test_zooming_in_spreads_the_points_apart(self):
        near = map_lookup.project(MIAOKOU, XIDING, 15, 1024, 576)
        far = map_lookup.project(MIAOKOU, XIDING, 12, 1024, 576)
        self.assertGreater(abs(near[0] - 512), abs(far[0] - 512))


class ZoomChoiceTests(unittest.TestCase):
    def test_tight_cluster_gets_a_closer_zoom_than_a_wide_one(self):
        tight = map_lookup.choose_zoom([MIAOKOU, XIDING], 1024, 576)
        wide = map_lookup.choose_zoom([(25.0, 121.5), (35.6, 139.7)], 1024, 576)
        self.assertGreater(tight, wide)

    def test_every_point_fits_inside_the_canvas(self):
        width, height = 1024, 576
        zoom = map_lookup.choose_zoom(KEELUNG, width, height)
        centre = (
            (max(p[0] for p in KEELUNG) + min(p[0] for p in KEELUNG)) / 2,
            (max(p[1] for p in KEELUNG) + min(p[1] for p in KEELUNG)) / 2,
        )
        for point in KEELUNG:
            px, py = map_lookup.project(point, centre, zoom, width, height)
            with self.subTest(point=point):
                self.assertTrue(0 <= px <= width, f"{px} 超出畫面寬")
                self.assertTrue(0 <= py <= height, f"{py} 超出畫面高")

    def test_single_point_gets_a_street_level_zoom(self):
        self.assertGreaterEqual(map_lookup.choose_zoom([MIAOKOU], 1024, 576), 13)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tile = _blank_tile()
        patcher = mock.patch.object(map_lookup, "_tile_bytes", return_value=self.tile)
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)

    def _render(self, **kwargs):
        from PIL import Image

        png = map_lookup.render_basemap(KEELUNG, width=512, height=288, **kwargs)
        return Image.open(io.BytesIO(png))

    def test_output_matches_the_requested_size(self):
        self.assertEqual(self._render().size, (512, 288))

    def test_empty_points_is_an_error_not_a_blank_map(self):
        # 沒有座標卻回一張空白地圖，等於默默送出一張錯的圖
        with self.assertRaises(map_lookup.MapLookupError):
            map_lookup.render_basemap([])

    def test_tile_budget_is_enforced(self):
        # 上限的理由是使用條款，不是效能——超過就該改用小比例尺，不是掃更多圖磚
        with self.assertRaises(map_lookup.MapLookupError):
            map_lookup.render_basemap(KEELUNG, width=4096, height=4096, zoom=16)

    def test_markers_are_drawn_by_the_program(self):
        marked = self._render(mark=True)
        plain = self._render(mark=False)
        self.assertNotEqual(marked.tobytes(), plain.tobytes())

    def test_marker_colour_appears_at_the_projected_pixel(self):
        image = self._render(mark=True).convert("RGB")
        zoom = map_lookup.choose_zoom(KEELUNG, 512, 288)
        centre = (
            (max(p[0] for p in KEELUNG) + min(p[0] for p in KEELUNG)) / 2,
            (max(p[1] for p in KEELUNG) + min(p[1] for p in KEELUNG)) / 2,
        )
        px, py = map_lookup.project(MIAOKOU, centre, zoom, 512, 288)
        self.assertEqual(image.getpixel((px, py)), (255, 138, 0))

    def test_attribution_is_always_burned_in(self):
        # ODbL 要求標註出處，所以沒有關掉它的參數；這裡確認它真的畫上去了
        image = self._render(mark=False).convert("RGB")
        corner = image.crop((image.width - 200, image.height - 30, image.width, image.height))
        self.assertIn((255, 255, 255), corner.getdata(), "右下角應有出處字樣的白底")

    def test_tile_url_is_overridable_for_paid_providers(self):
        map_lookup.render_basemap(KEELUNG, width=512, height=288, tile_url="https://x/{z}/{x}/{y}.png")
        self.assertTrue(
            any("https://x/" in call.args[0] for call in self.fetch.call_args_list)
        )


class GeocodeTests(unittest.TestCase):
    def _patch(self, payload):
        return mock.patch.object(map_lookup, "_get", return_value=payload)

    def test_returns_the_first_hit(self):
        with self._patch(b'[{"lat": "25.129", "lon": "121.744"}]'):
            self.assertEqual(map_lookup.geocode("基隆廟口"), (25.129, 121.744))

    def test_no_hit_returns_none_rather_than_a_guess(self):
        # 標錯地點在新聞畫面上就是播出事故，猜比查不到糟
        with self._patch(b"[]"):
            self.assertIsNone(map_lookup.geocode("不存在的地方"))

    def test_network_failure_is_swallowed_as_a_miss(self):
        with mock.patch.object(map_lookup, "_get", side_effect=OSError("boom")):
            self.assertIsNone(map_lookup.geocode("基隆廟口"))

    def test_malformed_payload_is_a_miss(self):
        with self._patch(b'[{"nope": 1}]'):
            self.assertIsNone(map_lookup.geocode("基隆廟口"))

    def test_blank_name_never_hits_the_network(self):
        with mock.patch.object(map_lookup, "_get") as get:
            self.assertIsNone(map_lookup.geocode("  "))
            get.assert_not_called()


class ModelCoordinateDriftTests(unittest.TestCase):
    """把 2026-09-04 量到的偏差釘住，說明這個模組為什麼存在。"""

    MODEL_SAID = {
        "基隆廟口": ((25.1282, 121.7444), MIAOKOU, 200),
        "西定路": ((25.1260, 121.7240), XIDING, 1000),
        "大武崙": ((25.1597, 121.6913), DAWULUN, 1000),
    }

    @staticmethod
    def _metres(a, b):
        dy = (a[0] - b[0]) * 111_000
        dx = (a[1] - b[1]) * 111_000 * math.cos(math.radians(a[0]))
        return math.hypot(dx, dy)

    def test_famous_landmark_was_close_enough(self):
        said, real, _ = self.MODEL_SAID["基隆廟口"]
        self.assertLess(self._metres(said, real), 200)

    def test_minor_places_drifted_past_a_city_block(self):
        for name in ("西定路", "大武崙"):
            said, real, threshold = self.MODEL_SAID[name]
            with self.subTest(name=name):
                self.assertGreater(
                    self._metres(said, real), threshold,
                    "這個案例若不再偏移，代表可以重新評估是否還需要實查座標",
                )


if __name__ == "__main__":
    unittest.main()
