"""封面／YT 封面的參考照可用性（2026-09-07）。

主流程在消化階段用 apply_photo_availability 把查不到照片的人排出版面。封面這兩條線
沒有消化階段，名單是補畫面描述時一併產生的，所以在同一個地方做。

守的紅線：
1. **兩人一人查不到，查得到的那位仍要畫臉。** resolve_portraits 是全有或全無，
   不先剔除就會連查得到的那位一起變背影。
2. **全部查不到時不清空名單。** 名單一空就沒有任何肖像規則，模型會替真名捏一張臉；
   保留名單才會走「不生成臉孔」。這裡刻意與主流程不同——主流程會重新消化，
   封面不會，畫面描述仍寫著那個人。
"""
import base64
import io
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import main  # noqa: E402
import photo_lookup  # noqa: E402
from test_ten_cover import _headers, client  # noqa: E402

MERZ_PHOTO = photo_lookup.ReferencePhoto(
    image_base64="cGhvdG8=", mime_type="image/jpeg",
    image_url="https://upload.wikimedia.org/merz.jpg",
    source_page="https://zh.wikipedia.org/wiki/梅爾茨", lang="zh",
)

# 梅爾茨查得到、蕭茲查不到——這一格兩個人
TWO_PEOPLE = {
    "visual_left": "梅爾茨與蕭茲同框，正面半身", "visual_right": "柏林街頭",
    "portrait_subjects_left": ["梅爾茨", "蕭茲"], "portrait_subjects_left_en": ["Friedrich Merz", "Olaf Scholz"],
    "portrait_subjects_right": [], "portrait_subjects_right_en": [],
}


def _completion(payload):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))])


def _png_for(aspect_ratio: str) -> bytes:
    ratio = main.parse_aspect_ratio(aspect_ratio) or 1.0
    buffer = io.BytesIO()
    Image.new("RGB", (round(720 * ratio), 720), (30, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def _only_merz(subjects, english=None):
    """逐人查：梅爾茨有照片、其他人沒有。"""
    found = {name: MERZ_PHOTO for name in subjects if name == "梅爾茨"}
    return found, [name for name in subjects if name not in found]


class CoverPhotoAvailabilityTests(unittest.TestCase):
    def _run(self, body, derive=TWO_PEOPLE, lookup=_only_merz):
        seen = []

        def fake_raw(image_req):
            seen.append(image_req)
            return main.ImageGenerateResponse(
                image_data_base64=base64.b64encode(_png_for(image_req.aspect_ratio)).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        with patch.object(main, "digest_completion", return_value=_completion(derive)), \
             patch.object(main, "lookup_portrait_photos", side_effect=lookup), \
             patch.object(main, "supports_reference_image", return_value=True), \
             patch.object(main, "generate_image_raw", side_effect=fake_raw):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return res.json(), seen

    def test_one_of_two_missing_keeps_the_one_that_was_found(self):
        _, seen = self._run({"title_left": "梅爾茨 蕭茲 同框", "layout": "full", "mode": "composite"})
        req = seen[0]
        self.assertEqual(req.portrait_subjects, ["梅爾茨"])
        self.assertEqual(req.portrait_subjects_en, ["Friedrich Merz"])
        # 一個人＝單張參考照通道
        self.assertEqual(req.reference_image_data_url, MERZ_PHOTO.data_url())
        self.assertIn(main.PORTRAIT_MODES["reference"].strip()[:60], req.prompt)

    def test_everyone_missing_keeps_the_list_and_the_no_face_rules(self):
        _, seen = self._run(
            {"title_left": "梅爾茨 蕭茲 同框", "layout": "full", "mode": "composite"},
            lookup=lambda subjects, english=None: ({}, list(subjects)),
        )
        req = seen[0]
        self.assertEqual(req.portrait_subjects, ["梅爾茨", "蕭茲"])
        self.assertEqual(req.reference_image_data_url, "")
        self.assertIn(main.PORTRAIT_MODES["no_reference"].strip()[:60], req.prompt)

    def test_uploaded_portrait_keeps_the_person_wikipedia_cannot_find(self):
        # 會自己上傳照片，通常正是因為那個人維基查不到（假設同 apply_photo_availability）
        photo_url = "data:image/png;base64," + base64.b64encode(_png_for("1:1")).decode("ascii")
        body = {
            "title_left": "梅爾茨 蕭茲 同框", "layout": "full", "mode": "composite",
            "reference_images": [{"data_url": photo_url, "purpose": "portrait"}],
        }
        _, seen = self._run(body)
        self.assertEqual(seen[0].portrait_subjects, ["梅爾茨", "蕭茲"])


class YtCoverPhotoAvailabilityTests(unittest.TestCase):
    def test_yt_plan_drops_the_person_without_a_photo(self):
        derived = {
            "line1": "梅爾茨蕭茲", "line2": "同框會談", "visual": "兩人正面半身",
            "portrait_subjects": ["梅爾茨", "蕭茲"], "portrait_subjects_en": ["Friedrich Merz", "Olaf Scholz"],
        }
        req = main.YtCoverRequest(title="梅爾茨蕭茲 同框會談", title_mode="composite")
        with patch.object(main, "digest_completion", return_value=_completion(derived)), \
             patch.object(main, "lookup_portrait_photos", side_effect=_only_merz):
            _, _, subjects, english = main.resolve_yt_cover_plan(req)
        self.assertEqual(subjects, ["梅爾茨"])
        self.assertEqual(english, ["Friedrich Merz"])


if __name__ == "__main__":
    unittest.main()
