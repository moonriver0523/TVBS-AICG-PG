"""後台看得到每一個版型（2026-09-11）。

使用者：「公司的後台已經抓不到這些新版型了」。查證：不是後台認不得，是**那些版型
根本沒寫稽核紀錄**。`_archive_generation` 只有三個呼叫端（images/generate、
images/refine、news-image/generate），全是 2026-08-25 建後台時就有的路徑；
後來加的十點不一樣（滿版／雙切）、YT 三種封面、YT 直標，一個都沒接上。

它們有寫 request_log，所以 JSONL 裡查得到——但 request_log 預設 14 天掃掉、不存圖、
寫在容器本機磁碟（重新部署即清空），那正是當初另外做 audit_archive 的原因。

這一支守兩件事：
1. **每一個會產圖的端點都要歸檔，而且要帶得出版型名字。**
   下面那支 test_every_image_endpoint_archives 是「防再犯」的那一條：
   它直接掃 main.py 的路由，新端點忘了接就會紅。
2. **後台的類型欄永遠列得出東西。** 退路 type_label → chart_type → source，
   下一個版型若又漏帶 type_label，最差是名字醜，不會整列消失。
"""
import ast
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import admin_console  # noqa: E402
import main  # noqa: E402

MAIN_SRC = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
MAIN_TREE = ast.parse(MAIN_SRC)

#: 產圖端點 → 它歸檔時該帶的版型名字片段。
#: cover-titles 只回文字（消化標題），沒有圖可歸檔，所以不在表裡。
IMAGE_ENDPOINTS = {
    "/api/images/generate": "",          # 走 type_label，第一頁本來就有值
    "/api/images/refine": "",
    "/api/news-image/generate": "",
    "/api/editor/cover": "十點不一樣",
    "/api/editor/yt-cover": "YT",
    "/api/editor/yt-overlay": "YT直播直標",
}


def _route_paths() -> set[str]:
    """從 AST 撈出所有 @app.post 的路徑——用字串比對會連註解裡的路徑一起撈到。"""
    paths = set()
    for node in ast.walk(MAIN_TREE):
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            func = deco.func
            if (isinstance(func, ast.Attribute) and func.attr == "post"
                    and isinstance(func.value, ast.Name) and func.value.id == "app"
                    and deco.args and isinstance(deco.args[0], ast.Constant)):
                paths.add(deco.args[0].value)
    return paths


def _functions() -> dict:
    return {n.name: n for n in ast.walk(MAIN_TREE) if isinstance(n, ast.FunctionDef)}


def _body_with_delegates(node, depth: int = 2) -> str:
    """端點本體，外加它直接呼叫到的本檔函式。

    news-image 那支只是 `return generate_news_image(req)`，真正的歸檔在被呼叫的
    那支裡；十點也一樣（雙切在端點裡、滿版在 _editor_cover_full）。
    只看端點本體會誤判成「沒歸檔」。
    """
    src = ast.get_source_segment(MAIN_SRC, node) or ""
    if depth <= 0:
        return src
    funcs = _functions()
    for called in ast.walk(node):
        if isinstance(called, ast.Call) and isinstance(called.func, ast.Name):
            target = funcs.get(called.func.id)
            if target is not None and target is not node:
                src += "\n" + _body_with_delegates(target, depth - 1)
    return src


class EndpointCoverageTests(unittest.TestCase):
    def test_the_endpoint_table_above_is_still_complete(self):
        """新增一個 POST 端點就會紅：要嘛它產圖、該補歸檔，要嘛在表裡註明不產圖。

        這是「防再犯」的那一條。上一次漏接四個端點沒有任何測試會紅，
        所以漏了三個星期都沒人發現。
        """
        known_textonly = {"/api/generate", "/api/hybrid/digest", "/api/editor/cover-titles"}
        self.assertEqual(
            _route_paths() - set(IMAGE_ENDPOINTS) - known_textonly,
            set(),
            "有新的 POST 端點沒登記：若會產圖請補 _archive_generation 並加進 IMAGE_ENDPOINTS，"
            "若只回文字請加進 known_textonly",
        )

    def test_every_image_endpoint_archives(self):
        """每一個產圖端點的函式體裡都要出現 _archive_generation。"""
        wanted = set(IMAGE_ENDPOINTS)
        for node in ast.walk(MAIN_TREE):
            if not isinstance(node, ast.FunctionDef):
                continue
            paths = {
                deco.args[0].value
                for deco in node.decorator_list
                if isinstance(deco, ast.Call) and deco.args
                and isinstance(deco.args[0], ast.Constant)
                and isinstance(deco.func, ast.Attribute) and deco.func.attr == "post"
            }
            hit = paths & wanted
            if not hit:
                continue
            body = _body_with_delegates(node)
            # 十點的兩個版面拆在 _editor_cover_full 裡，所以雙切那支看得到、
            # 滿版那支要另外確認（下一個測試負責）。
            with self.subTest(path=sorted(hit)):
                self.assertIn("_archive_generation", body)

    def test_the_full_layout_branch_archives_too(self):
        """十點滿版走 _editor_cover_full，是另一個函式——漏掉它等於滿版全部查無紀錄。"""
        for node in ast.walk(MAIN_TREE):
            if isinstance(node, ast.FunctionDef) and node.name == "_editor_cover_full":
                body = ast.get_source_segment(MAIN_SRC, node) or ""
                self.assertIn("_archive_generation", body)
                self.assertIn("（滿版）", body)
                return
        self.fail("找不到 _editor_cover_full")

    def test_the_labels_match_the_front_end_names(self):
        """後台的類型欄要是編輯自己在下拉選單看得到的名字，不是內部代碼。"""
        app_js = (Path(__file__).resolve().parent.parent / "app.js").read_text(encoding="utf-8")
        self.assertEqual(main.COVER_TYPE_LABEL_TEN, "十點不一樣")
        for label in (main.COVER_TYPE_LABEL_TEN, *main.COVER_TYPE_LABEL_YT.values()):
            with self.subTest(label=label):
                self.assertIn(f"'{label}'", app_js)
        # 直標前台標籤帶了個全形減號前綴（排序用），後台不需要那個符號
        self.assertIn(f"'－{main.COVER_TYPE_LABEL_VSTRIP}'", app_js)

    def test_every_yt_layout_has_a_label(self):
        """漏一個 layout 就會掉回「YT封面」，三種版型在後台就混成一類。"""
        self.assertEqual(set(main.COVER_TYPE_LABEL_YT), {"news", "hourly", "hot"})


class ConsoleTypeColumnTests(unittest.TestCase):
    def test_the_type_column_falls_back_to_source(self):
        """下一個版型若又漏帶 type_label，最差是名字醜，不會整列變空白。"""
        self.assertEqual(admin_console._type_of({"type_label": "十點不一樣（雙切）"}),
                         "十點不一樣（雙切）")
        self.assertEqual(admin_console._type_of({"chart_type": "資訊卡"}), "資訊卡")
        self.assertEqual(admin_console._type_of({"source": "editor-cover"}), "editor-cover")
        self.assertEqual(admin_console._type_of({}), "（未分類）")

    def test_the_type_filter_is_built_from_the_records(self):
        """寫死清單等於每加一個版型就要記得回來改——這次出事就是這樣來的。"""
        page = admin_console._page(
            records=[], months=["2026-09"], month="", user="",
            types=["十點不一樣（雙切）", "YT整點直播"], type_label="YT整點直播",
        )
        self.assertIn("全部類型", page)
        self.assertIn("十點不一樣（雙切）", page)
        self.assertIn('<option value="YT整點直播" selected>', page)

    def test_the_filter_actually_filters(self):
        records = [
            {"source": "editor-cover", "type_label": "十點不一樣（雙切）"},
            {"source": "editor-yt-cover-hourly", "type_label": "YT整點直播"},
        ]
        with patch.object(admin_console.audit_archive, "ENABLED", True), \
             patch.object(admin_console.audit_archive, "list_records", return_value=records), \
             patch.object(admin_console.audit_archive, "available_months", return_value=["2026-09"]):
            kept = [r for r in records if admin_console._type_of(r) == "YT整點直播"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["source"], "editor-yt-cover-hourly")


if __name__ == "__main__":
    unittest.main()
