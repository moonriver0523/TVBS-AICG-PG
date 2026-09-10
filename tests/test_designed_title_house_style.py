"""設計標題「更奔放」（2026-09-09 第七批）。

使用者附兩張現行 YouTube 封面截圖說「可以更奔放 參考我們現行的AI設計版標題」。
對照當時的成品：模型只換了填色材質，版面仍是兩行等大、齊左的堆疊。

根因不在模型不聽話，在條文的**語氣**：上一版整段寫成「你可以…」「不再受限」，
而它前面的 TYPOGRAPHY 全是命令句。許可推不動模型——模型會走阻力最小的路。
所以這一批守的紅線是：那個 house style 要用**命令句逐項描述**，而且是必做，不是可選。

同時守住反向的兩件事：
- 放大是給「短促的鉤子＋解釋句」用的；兩行是同一個名詞被拆開時不准放大其中一行。
- 截圖裡的國旗小標／地圖地名／問號徽章是**清單外文字**，這批不開（撞硬規則 (e)，
  而且國旗那個位置正是 compose.paste_cover_ai_note 要貼的角落）。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-internal-key")

import editor_formats  # noqa: E402

CLAUSE = editor_formats.COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE


class HouseStyleTests(unittest.TestCase):
    def test_size_hierarchy_is_an_order_not_an_option(self):
        """截圖裡最明顯的落差：短鉤子比解釋句大一大截。
        寫成「你可以放大某一行」等於沒寫——上一版就是這樣寫的，成品兩行照樣等大。"""
        self.assertIn("SIZE HIERARCHY IS REQUIRED", CLAUSE)
        self.assertIn("The lines are not the same size", CLAUSE)
        self.assertIn("one and a half to two times", CLAUSE)

    def test_a_key_word_gets_pulled_out_inside_the_line(self):
        """「街道成河」、"致命漏洞"、名古屋、東京——關鍵詞在同一行裡換色／進紅框。
        沒有這一條，模型只會做「整行一個顏色」的老排版。"""
        self.assertIn("PULL A KEY WORD OUT INSIDE A LINE", CLAUSE)
        self.assertIn("Every line must not be one flat colour", CLAUSE)
        self.assertIn("「」", CLAUSE)

    def test_the_palette_describes_the_reference_not_the_last_output(self):
        """上一版成品是整排金屬金。基準圖是飽和平塗黃／白／紅＋粗黑描邊＋硬投影，
        所以要明文否定「整排同一種金屬填色」，不然模型會繼續交同一張。"""
        self.assertIn("saturated FLAT golden yellow", CLAUSE)
        self.assertIn("hard offset drop shadow", CLAUSE)
        self.assertIn("not one uniform polished metallic fill", CLAUSE)

    def test_pictograms_are_allowed_but_carry_no_writing(self):
        """基準圖上有⚡🔥☔⚠。圖示不是文字，可以開；但圖示裡一旦有字就繞過了硬規則 (e)。"""
        self.assertIn("ONE OR TWO small flat pictograms", CLAUSE)
        self.assertIn("never covering a character", CLAUSE)
        self.assertIn("wordless symbols only", CLAUSE)

    def test_a_name_split_across_rows_is_not_blown_up_by_half(self):
        """「古羅馬圖／拉真浴場」是一個名詞被拆成兩行。照「鉤子放大」辦會把它拆散。"""
        self.assertIn("ONE EXCEPTION TO THE SIZE HIERARCHY", CLAUSE)
        self.assertIn("one continuous phrase, sentence or proper name", CLAUSE)
        self.assertIn("keep them at ONE size", CLAUSE)

    def test_flags_and_map_labels_stay_shut(self):
        """基準圖右上那些國旗小標帶著國名，是清單外文字，而且壓在 AI示意圖 那個角落。
        要開是另一件事，不能靠「更奔放」順手夾帶進來。"""
        for banned in ("no country names", "no place labels", "no flag chips", "no map insets"):
            with self.subTest(banned=banned):
                self.assertIn(banned, CLAUSE)

    def test_freeing_the_shape_does_not_free_the_line_count(self):
        """版面解放最危險的副作用：模型為了排得好看把兩行併成一行。"""
        self.assertIn("no longer binds as a SHAPE", CLAUSE)
        self.assertIn("how many there are, are still fixed", CLAUSE)


if __name__ == "__main__":
    unittest.main()
