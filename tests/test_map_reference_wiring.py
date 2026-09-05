"""真實地圖底圖串進生圖流程。

為什麼要串（2026-09-04 量出來的）：消化端寫的經緯度來自模型記憶，實查比對後
「基隆廟口」差 107 公尺、「西定路」差 1,470 公尺、「大武崙」差 2,296 公尺——
市區圖上已經標到別的行政區。所以改成：消化端只負責「列出要標哪些地名」，
座標由程式查 Nominatim，底圖由程式拼、標點由程式畫在真實座標上，再當參考圖附上去。

這一串的紅線全是「不要把加分項變成故障」：
1. 非地圖類的 schema 必須與過去逐位元組相同（記者 frozen 快照＋既有行為）。
2. 查不到座標、圖磚抓不到、範圍太大——一律安靜退回原本的純 prompt 路徑。
3. 送不出參考圖的後端（原生 OpenAI）絕不可以因為自動底圖而丟 400：
   那是使用者什麼都沒做錯卻收到的錯誤。
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main  # noqa: E402
from main import (  # noqa: E402
    AUTO_TYPE_LABEL,
    DIGEST_OUTPUT_SCHEMA,
    MAX_INPUT_REFERENCES,
    MIN_MAP_POINTS,
    ImageGenerateRequest,
    MapPoint,
    UserReferenceImage,
    apply_map_reference_to_image_request,
    digest_schema,
    resolve_map_points,
)
from news_prompt import MAP_TYPE_LABEL, USER_REFERENCE_MAP_RULES  # noqa: E402

KEELUNG = [
    MapPoint(name="基隆廟口", lat=25.1290607, lon=121.74391),
    MapPoint(name="西定路", lat=25.1368202, lon=121.7324353),
]


def _req(**kwargs) -> ImageGenerateRequest:
    base = {"prompt": "p", "provider": "gpt", "map_points": KEELUNG}
    base.update(kwargs)
    return ImageGenerateRequest(**base)


class SchemaVariantTests(unittest.TestCase):
    def test_non_map_types_get_the_untouched_schema_object(self):
        for label in ("資料圖表", "情境示意圖", "3D示意／流程"):
            with self.subTest(label=label):
                self.assertIs(digest_schema(label), DIGEST_OUTPUT_SCHEMA)

    def test_map_and_auto_gain_the_field(self):
        for label in (MAP_TYPE_LABEL, AUTO_TYPE_LABEL):
            with self.subTest(label=label):
                schema = digest_schema(label)
                self.assertIn("map_places", schema["properties"])
                self.assertIn("map_places", schema["required"])

    def test_the_shared_constant_is_never_mutated(self):
        digest_schema(MAP_TYPE_LABEL)
        digest_schema(AUTO_TYPE_LABEL)
        self.assertNotIn("map_places", DIGEST_OUTPUT_SCHEMA["properties"])
        self.assertNotIn("map_places", DIGEST_OUTPUT_SCHEMA["required"])

    def test_digest_rule_asks_for_lookup_queries_not_captions(self):
        # 「西定路」全臺一堆，查詢字串一定要帶行政區
        text = main.build_digest_instructions("編輯", "standard", MAP_TYPE_LABEL)
        self.assertIn('"map_places"', text)
        self.assertIn("基隆市 西定路", text)


class ResolveMapPointsTests(unittest.TestCase):
    def _geocode(self, mapping):
        return mock.patch.object(
            main.map_lookup, "geocode", side_effect=lambda n, **k: mapping.get(n)
        )

    def test_non_map_chart_types_never_hit_the_network(self):
        with mock.patch.object(main.map_lookup, "geocode") as geocode:
            self.assertEqual(resolve_map_points("資料圖表", ["基隆市 西定路"]), [])
            geocode.assert_not_called()

    def test_resolved_points_carry_the_display_name_not_the_query(self):
        # 查詢要「基隆市 西定路」才找得到，但畫面上不該出現查詢用的寫法
        with self._geocode({"基隆市 西定路": (25.13, 121.73), "基隆市 大武崙": (25.14, 121.70)}):
            points = resolve_map_points(MAP_TYPE_LABEL, ["基隆市 西定路", "基隆市 大武崙"])
        self.assertEqual([p.name for p in points], ["西定路", "大武崙"])

    def test_a_place_that_cannot_be_found_is_skipped_not_guessed(self):
        with self._geocode({"基隆市 西定路": (25.13, 121.73), "基隆市 大武崙": (25.14, 121.70)}):
            points = resolve_map_points(
                MAP_TYPE_LABEL, ["基隆市 西定路", "查無此地", "基隆市 大武崙"]
            )
        self.assertEqual([p.name for p in points], ["西定路", "大武崙"])

    def test_one_point_is_not_a_map(self):
        # 單點沒有「相對位置」可言，而相對位置正是地圖類存在的理由
        with self._geocode({"基隆市 西定路": (25.13, 121.73)}):
            self.assertEqual(resolve_map_points(MAP_TYPE_LABEL, ["基隆市 西定路"]), [])
        self.assertEqual(MIN_MAP_POINTS, 2)

    def test_geocode_exception_never_escapes(self):
        with mock.patch.object(main.map_lookup, "geocode", side_effect=OSError("boom")):
            self.assertEqual(resolve_map_points(MAP_TYPE_LABEL, ["甲", "乙"]), [])

    def test_place_count_is_capped(self):
        names = [f"地點{i}" for i in range(10)]
        with mock.patch.object(main.map_lookup, "geocode", return_value=(25.0, 121.0)) as geocode:
            resolve_map_points(MAP_TYPE_LABEL, names)
        self.assertLessEqual(geocode.call_count, main.MAX_MAP_PLACES)

    def test_empty_place_list_is_fine(self):
        self.assertEqual(resolve_map_points(MAP_TYPE_LABEL, None), [])
        self.assertEqual(resolve_map_points(MAP_TYPE_LABEL, []), [])


class AttachBasemapTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(
            main.map_lookup, "render_basemap", return_value=b"\x89PNG-fake"
        )
        self.render = patcher.start()
        self.addCleanup(patcher.stop)
        multi = mock.patch.object(main, "supports_multiple_reference_images", return_value=True)
        multi.start()
        self.addCleanup(multi.stop)

    def test_basemap_is_attached_as_a_map_reference(self):
        out = apply_map_reference_to_image_request(_req())
        self.assertEqual(len(out.reference_images), 1)
        self.assertEqual(out.reference_images[0].purpose, "map")
        self.assertTrue(out.reference_images[0].data_url.startswith("data:image/png;base64,"))

    def test_markers_are_drawn_by_the_program(self):
        apply_map_reference_to_image_request(_req())
        self.assertTrue(self.render.call_args.kwargs["mark"])
        self.assertEqual(
            self.render.call_args.args[0],
            [(p.lat, p.lon) for p in KEELUNG],
        )

    def test_no_points_means_no_change(self):
        req = _req(map_points=[])
        self.assertIs(apply_map_reference_to_image_request(req), req)
        self.render.assert_not_called()

    def test_render_failure_still_returns_a_usable_request(self):
        # 底圖是加分項：抓不到圖磚不可以讓一則出得了圖的新聞變成錯誤
        self.render.side_effect = main.map_lookup.MapLookupError("範圍太大")
        out = apply_map_reference_to_image_request(_req())
        self.assertEqual(out.reference_images, [])

    def test_user_supplied_map_wins(self):
        own = UserReferenceImage(data_url="data:image/png;base64,AAA", purpose="map")
        out = apply_map_reference_to_image_request(_req(reference_images=[own]))
        self.assertEqual(out.reference_images, [own])
        self.render.assert_not_called()

    def test_other_purposes_are_preserved_and_not_replaced(self):
        scene = UserReferenceImage(data_url="data:image/png;base64,AAA", purpose="scene")
        out = apply_map_reference_to_image_request(_req(reference_images=[scene]))
        self.assertEqual([r.purpose for r in out.reference_images], ["scene", "map"])

    def test_reference_slots_full_means_skip(self):
        full = [
            UserReferenceImage(data_url="data:image/png;base64,AAA", purpose="scene")
            for _ in range(MAX_INPUT_REFERENCES)
        ]
        out = apply_map_reference_to_image_request(_req(reference_images=full))
        self.assertEqual(len(out.reference_images), MAX_INPUT_REFERENCES)
        self.render.assert_not_called()


class BackendGuardTests(unittest.TestCase):
    """送不出參考圖的後端不可以因為自動底圖而丟 400。"""

    def test_native_backend_skips_silently(self):
        with mock.patch.object(main, "supports_multiple_reference_images", return_value=False):
            with mock.patch.object(main.map_lookup, "render_basemap") as render:
                out = apply_map_reference_to_image_request(_req())
        self.assertEqual(out.reference_images, [])
        render.assert_not_called()

    def test_the_attached_map_block_tells_the_model_not_to_move_the_dots(self):
        # 實測：底圖沒有標點時模型自己猜位置，西定路被放到廟口南邊（實際在西北西）
        self.assertIn("ROUND MARKER DOTS", USER_REFERENCE_MAP_RULES)
        self.assertIn("Keep every marker at its dot", USER_REFERENCE_MAP_RULES)

    def test_the_pin_tip_must_land_on_the_dot(self):
        # 2026-09-04 實測（基隆淹水圖）：模型把底圖圓點畫成地面漣漪、pin 浮在漣漪上方，
        # 等於一個地點出現兩個位置，真正的座標落在下方那圈。錨點必須講明是尖端。
        self.assertIn("MUST RESOLVE TO ONE POINT", USER_REFERENCE_MAP_RULES)
        self.assertIn("tip exactly on the dot's centre", USER_REFERENCE_MAP_RULES)
        self.assertIn("ripple", USER_REFERENCE_MAP_RULES)

    def test_the_attached_map_outranks_coordinates_in_structure(self):
        # STRUCTURE 裡仍會有模型寫的經緯度，兩者衝突時附圖要贏
        self.assertIn("secondary to the attached map", USER_REFERENCE_MAP_RULES)


if __name__ == "__main__":
    unittest.main()


class MissingDotTests(unittest.TestCase):
    """底圖上沒有點的地方，不准自己補一支 pin 在猜的位置。

    2026-09-05 實測（SOT2 第三輪）：國道 1 號三起車禍那則，消化寫的
    「國道1號中壢交流道」查無座標被略過，底圖只有楊梅與湖口兩個點，
    但 STRUCTURE 仍要求標出中壢——生圖模型就自己補了一支，還把它畫在
    湖口與楊梅中間。國 1 由北往南是中壢→楊梅→湖口，中壢應該在最北，
    也就是那支自補的 pin 位置是錯的。
    """

    def test_a_place_without_a_dot_gets_no_pin(self):
        rules = USER_REFERENCE_MAP_RULES
        self.assertIn("no dot for it", rules)
        self.assertIn("put nothing on the map for it", rules)
        self.assertIn("the position is what you are inventing", rules)
