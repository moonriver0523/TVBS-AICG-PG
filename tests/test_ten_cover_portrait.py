"""十點封面接上肖像流程（2026-09-07 使用者回報：德國總理梅爾茨被畫成背影）。

根因：這條線從沒接 apply_portrait_to_image_request，且補畫面描述的 prompt 明文禁止具名真人的臉。
現在：補描述時一併列出每格的具名真人（中文＋英文名），生圖前查參考照；查得到才畫臉，
查不到照舊背影（與其他版型同一套規則）。
"""
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import editor_formats  # noqa: E402
import main  # noqa: E402
import photo_lookup  # noqa: E402
from test_ten_cover import _headers, _png_bytes, client  # noqa: E402

PHOTO = photo_lookup.ReferencePhoto(
    image_base64="cGhvdG8=", mime_type="image/jpeg",
    image_url="https://upload.wikimedia.org/merz.jpg", source_page="https://zh.wikipedia.org/wiki/梅爾茨", lang="zh",
)


def _derive(payload):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))])


MERZ = {
    "visual_left": "德國總理梅爾茨站在國會大廈前講台，正面半身，陰天", "visual_right": "柏林街頭選舉海報",
    "portrait_subjects_left": ["梅爾茨"], "portrait_subjects_left_en": ["Friedrich Merz"],
    "portrait_subjects_right": [], "portrait_subjects_right_en": [],
}


class DerivePromptTests(unittest.TestCase):
    def test_prompt_allows_named_person_portrait_and_asks_for_names(self):
        text = editor_formats.COVER_VISUAL_DERIVE_SYSTEM
        self.assertNotIn("no identifiable faces", text)
        self.assertIn("portrait-style shot of that person", text)
        self.assertIn("portrait_subjects_left", text)
        self.assertIn("portrait_subjects_right_en", text)
        for key in ("portrait_subjects_left", "portrait_subjects_left_en", "portrait_subjects_right", "portrait_subjects_right_en"):
            self.assertIn(key, editor_formats.COVER_VISUAL_SCHEMA["required"])


class PortraitWiringTests(unittest.TestCase):
    def _run(self, body, derive=MERZ, found=True):
        seen = []

        def fake_raw(image_req):
            seen.append(image_req)
            return main.ImageGenerateResponse(
                image_data_base64=__import__("base64").b64encode(_png_bytes(size=(1536, 864))).decode("ascii"),
                mime_type="image/png", model="fake",
            )

        def fake_lookup(subjects, english=None):
            if not found:
                return {}, list(subjects)
            return {name: PHOTO for name in subjects}, []

        with patch.object(main, "digest_completion", return_value=_derive(derive)), \
             patch.object(main, "lookup_portrait_photos", side_effect=fake_lookup), \
             patch.object(main, "supports_reference_image", return_value=True), \
             patch.object(main, "generate_image_raw", side_effect=fake_raw):
            res = client.post("/api/editor/cover", json=body, headers=_headers())
        self.assertEqual(res.status_code, 200, res.text)
        return res.json(), seen

    def test_full_composite_attaches_wiki_photo_and_portrait_rules(self):
        data, seen = self._run({"title_left": "地方選舉慘敗 德國總理梅爾茨深感震驚 誓言改革", "layout": "full", "mode": "composite"})
        self.assertEqual(len(seen), 1)
        req = seen[0]
        self.assertEqual(req.portrait_subjects, ["梅爾茨"])
        self.assertEqual(req.portrait_subjects_en, ["Friedrich Merz"])
        self.assertEqual(req.reference_image_data_url, PHOTO.data_url())
        self.assertIn(main.PORTRAIT_MODES["reference"].strip()[:60], req.prompt)
        self.assertIn("梅爾茨", data["visual_left"])

    def test_full_composite_with_supplied_visual_still_gets_portrait(self):
        data, seen = self._run({"title_left": "梅爾茨 深感震驚", "layout": "full", "mode": "composite", "visual_left": "梅爾茨在講台前正面半身"})
        self.assertEqual(seen[0].portrait_subjects, ["梅爾茨"])
        self.assertEqual(seen[0].reference_image_data_url, PHOTO.data_url())
        self.assertEqual(data["visual_left"], "梅爾茨在講台前正面半身")

    def test_split_composite_gives_each_panel_its_own_subjects(self):
        _, seen = self._run({"title_left": "梅爾茨 深感震驚", "title_right": "柏林街頭 選舉海報", "layout": "split", "mode": "composite"})
        self.assertEqual(len(seen), 2)
        by_prompt = {("梅爾茨" in r.prompt): r for r in seen}
        self.assertEqual(by_prompt[True].portrait_subjects, ["梅爾茨"])
        self.assertEqual(by_prompt[True].reference_image_data_url, PHOTO.data_url())
        self.assertEqual(by_prompt[False].portrait_subjects, [])
        self.assertEqual(by_prompt[False].reference_image_data_url, "")

    def test_ai_mode_merges_both_panels_subjects(self):
        both = dict(MERZ, portrait_subjects_right=["梅爾茨", "蕭茲"], portrait_subjects_right_en=["Friedrich Merz", "Olaf Scholz"])
        _, seen = self._run({"title_left": "梅爾茨 深感震驚", "title_right": "蕭茲 冷眼旁觀", "layout": "split", "mode": "ai"}, derive=both)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].portrait_subjects, ["梅爾茨", "蕭茲"])
        self.assertEqual(seen[0].portrait_subjects_en, ["Friedrich Merz", "Olaf Scholz"])

    def test_not_found_falls_back_to_no_face_rules(self):
        _, seen = self._run({"title_left": "梅爾茨 深感震驚", "layout": "full", "mode": "composite"}, found=False)
        req = seen[0]
        self.assertEqual(req.reference_image_data_url, "")
        self.assertIn(main.PORTRAIT_MODES["no_reference"].strip()[:60], req.prompt)


if __name__ == "__main__":
    unittest.main()
