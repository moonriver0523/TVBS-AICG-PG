"""2026-09-08 審查必修與後續：被剔除者禁畫、地圖查不到地名回前端、封面隱藏指令欄。"""
import base64
import json
import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import main  # noqa: E402
import photo_lookup  # noqa: E402
from test_ten_cover import _headers, _png_bytes, client  # noqa: E402

PHOTO = photo_lookup.ReferencePhoto(image_base64="cGhvdG8=", mime_type="image/jpeg", image_url="u", source_page="p", lang="zh")


def _completion(payload):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))])


def _fake_raw(image_req):
    ratio = main.parse_aspect_ratio(image_req.aspect_ratio) or 1.0
    return main.ImageGenerateResponse(
        image_data_base64=base64.b64encode(_png_bytes(size=(round(864 * ratio), 864))).decode("ascii"),
        mime_type="image/png", model="fake",
    )


def _lookup_only_merz(subjects, english=None):
    found = {n: PHOTO for n in subjects if n == "梅爾茨"}
    return found, [n for n in subjects if n not in found]


class ExcludedPeopleTests(unittest.TestCase):
    def test_keep_subjects_returns_dropped_names(self):
        with patch.object(main, "lookup_portrait_photos", side_effect=_lookup_only_merz):
            kept, en, photos, dropped = main.keep_subjects_with_photos(["梅爾茨", "蕭茲"], ["Friedrich Merz", "Olaf Scholz"], tag="t")
        self.assertEqual((kept, en, dropped), (["梅爾茨"], ["Friedrich Merz"], ["蕭茲"]))
        self.assertIn("梅爾茨", photos)

    def test_ten_cover_prompt_forbids_the_dropped_person(self):
        derive = {"visual_left": "梅爾茨與蕭茲同框正面半身", "visual_right": "柏林街頭",
                  "portrait_subjects_left": ["梅爾茨", "蕭茲"], "portrait_subjects_left_en": ["Friedrich Merz", "Olaf Scholz"],
                  "portrait_subjects_right": [], "portrait_subjects_right_en": []}
        seen = []
        with patch.object(main, "digest_completion", return_value=_completion(derive)), \
             patch.object(main, "lookup_portrait_photos", side_effect=_lookup_only_merz), \
             patch.object(main, "supports_reference_image", return_value=True), \
             patch.object(main, "generate_image_raw", side_effect=lambda r: (seen.append(r), _fake_raw(r))[1]):
            res = client.post("/api/editor/cover", json={"title_left": "梅爾茨 蕭茲 同框", "layout": "full", "mode": "composite"}, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        req = seen[0]
        self.assertEqual(req.portrait_subjects, ["梅爾茨"])
        self.assertIn("PEOPLE WHO MUST NOT BE DRAWN", req.prompt)
        self.assertIn("No usable reference photograph exists for: 蕭茲", req.prompt)
        # 禁畫區塊要在肖像規則之後（後到者贏）
        self.assertGreater(req.prompt.index("PEOPLE WHO MUST NOT BE DRAWN"), req.prompt.index(main.PORTRAIT_MODES["reference"].strip()[:40]))

    def test_no_block_when_everyone_found(self):
        derive = {"visual_left": "梅爾茨", "visual_right": "x",
                  "portrait_subjects_left": ["梅爾茨"], "portrait_subjects_left_en": ["Friedrich Merz"],
                  "portrait_subjects_right": [], "portrait_subjects_right_en": []}
        seen = []
        with patch.object(main, "digest_completion", return_value=_completion(derive)), \
             patch.object(main, "lookup_portrait_photos", side_effect=_lookup_only_merz), \
             patch.object(main, "supports_reference_image", return_value=True), \
             patch.object(main, "generate_image_raw", side_effect=lambda r: (seen.append(r), _fake_raw(r))[1]):
            res = client.post("/api/editor/cover", json={"title_left": "梅爾茨 震驚 改革", "layout": "full", "mode": "composite"}, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertNotIn("PEOPLE WHO MUST NOT BE DRAWN", seen[0].prompt)

    def test_yt_cover_prompt_forbids_the_dropped_person(self):
        seen = []
        plan = main.YtCoverPlan(("梅爾茨蕭茲", "同框"), "兩人同框正面", ["梅爾茨"], ["Friedrich Merz"], {}, ["蕭茲"])
        with patch.object(main, "resolve_yt_cover_plan", return_value=plan), \
             patch.object(main, "lookup_portrait_photos", side_effect=_lookup_only_merz), \
             patch.object(main, "supports_reference_image", return_value=True), \
             patch.object(main, "generate_image_raw", side_effect=lambda r: (seen.append(r), _fake_raw(r))[1]):
            res = client.post("/api/editor/yt-cover", json={"title": "梅爾茨蕭茲 同框", "provider": "gpt"}, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(seen), 1)
        self.assertIn("No usable reference photograph exists for: 蕭茲", seen[0].prompt)


class MapMissingTests(unittest.TestCase):
    def test_resolve_map_points_records_missing_names(self):
        def geocode(name):
            return (22.79, 120.29) if "岡山" in name else None

        with patch.object(main.map_lookup, "geocode", side_effect=geocode):
            points = main.resolve_map_points(main.MAP_TYPE_LABEL, ["高雄市 岡山區", "高雄市 路竹車站"])
        self.assertEqual(points, [])
        self.assertEqual(main.map_missing_places(), ["高雄市 路竹車站"])

    def test_generate_response_carries_map_missing(self):
        self.assertIn("map_missing", main.GenerateResponse.model_fields)
        self.assertEqual(main.GenerateResponse.model_fields["map_missing"].default_factory(), [])


class FrontendTests(unittest.TestCase):
    js = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_instruction_field_hidden_for_cover_formats(self):
        self.assertIn("_hide(document.getElementById('aiInstruction'), format.inputs === 'cover' || format.inputs === 'yt_cover');", self.js)

    def test_map_missing_toast_wired(self):
        self.assertRegex(self.js, r"data\.map_missing[\s\S]{0,400}showToast")


if __name__ == "__main__":
    unittest.main()
