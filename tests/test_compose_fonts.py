"""中文字型探測。

存在理由（2026-09-04 部署前抓到）：`_font()` 原本寫死四個路徑，前兩個是
Windows 字型、後兩個是猜的 Debian Noto 檔名。開發機是 Windows 所以永遠命中第一個，
本機測試與瀏覽器驗收全綠；但正式環境是 python:3.14-slim，四個路徑一個都不存在，
「播出鏡面」只要畫浮水印就會 ComposeError → 500。這種差異只有容器環境才看得到，
所以改成掃目錄，並在這裡把「找得到／找不到」兩種結果都釘住。
"""

import pathlib
import unittest

import compose


class DiscoverFontTests(unittest.TestCase):
    def test_windows_candidate_wins_when_present(self):
        found = compose.discover_font(
            windows_candidates=(pathlib.Path(__file__),),
            linux_roots=(),
            linux_globs=(),
        )
        self.assertEqual(found, pathlib.Path(__file__))

    def test_returns_none_when_nothing_exists(self):
        self.assertIsNone(
            compose.discover_font(
                windows_candidates=(pathlib.Path("C:/nope/none.ttf"),),
                linux_roots=(pathlib.Path("/nope-does-not-exist"),),
                linux_globs=("**/NotoSansCJK*",),
            )
        )

    def test_linux_glob_finds_font_by_pattern_not_by_exact_name(self):
        # Debian 各版檔名／目錄都不一樣，寫死等於賭檔名
        root = pathlib.Path(self.tmp)
        target = root / "opentype" / "noto" / "NotoSansCJK-Regular.ttc"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x")
        self.assertEqual(
            compose.discover_font(
                windows_candidates=(),
                linux_roots=(root,),
                linux_globs=("**/NotoSansCJK*",),
            ),
            target,
        )

    def test_bold_pattern_beats_a_later_generic_pattern(self):
        # 這些字要壓在圖上，Regular 會糊掉，粗體必須優先
        root = pathlib.Path(self.tmp)
        noto = root / "opentype" / "noto"
        noto.mkdir(parents=True)
        (noto / "NotoSansCJK-Regular.ttc").write_bytes(b"x")
        bold = noto / "NotoSansCJK-Bold.ttc"
        bold.write_bytes(b"x")
        self.assertEqual(
            compose.discover_font(
                windows_candidates=(),
                linux_roots=(root,),
                linux_globs=("**/NotoSansCJK*Bold*", "**/NotoSansCJK*"),
            ),
            bold,
        )

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = self._tmpdir.name
        self.addCleanup(self._tmpdir.cleanup)


class FontActuallyLoadsTests(unittest.TestCase):
    def test_this_machine_can_draw_chinese(self):
        font = compose._font(48)
        self.assertGreater(font.getbbox("播出鏡面")[2], 0)


class DockerfileTests(unittest.TestCase):
    """Linux 那條路徑只有在容器真的裝了字型時才成立，所以把它釘在測試裡。"""

    def test_dockerfile_installs_cjk_fonts(self):
        text = (pathlib.Path(compose.__file__).parent / "Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn("fonts-noto-cjk", text)


if __name__ == "__main__":
    unittest.main()
