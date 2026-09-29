"""2026-09-30 全站總體檢的跨路徑回歸測試。"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")


class ManualImageGenerationParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start = APP_JS.index("async function handleImageGeneration()")
        end = APP_JS.index(
            "/* ============================================================\n   ① 專用指令欄位",
            start,
        )
        cls.handler = APP_JS[start:end]

    def test_manual_path_sends_reference_images_and_editor_instruction(self):
        self.assertIn("reference_images: userRefImagesPayload()", self.handler)
        self.assertIn("editor_instruction: currentUserInstruction()", self.handler)

    def test_manual_path_uses_shared_error_and_notice_handling(self):
        self.assertIn("clearGenerateBannerForNewRequest()", self.handler)
        self.assertIn("response.json().catch(() => ({}))", self.handler)
        self.assertIn("_apiError(data, response.status)", self.handler)
        self.assertIn("showGenerateNoticeBanner(data.notices)", self.handler)


if __name__ == "__main__":
    unittest.main()
