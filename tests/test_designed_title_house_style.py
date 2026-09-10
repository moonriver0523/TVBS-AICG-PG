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
# 2026-09-11 第二輪：數字與配色鐵則搬到 CANVAS 正後方的設計綱要（模型讀得到的位置），
# 條文區只留質感與做法。所以這一支同時看兩塊。
BRIEF = editor_formats.cover_design_brief(
    editor_formats.COVER_AI_TITLE_LEVEL_MAX, titles=("胰臟癌6大 前兆",), seed=0)


class HouseStyleTests(unittest.TestCase):
    def test_size_hierarchy_is_an_order_not_an_option(self):
        """截圖裡最明顯的落差：短鉤子比解釋句大一大截。
        寫成「你可以放大某一行」等於沒寫——上一版就是這樣寫的，成品兩行照樣等大。"""
        self.assertIn("Row sizes differ", BRIEF)
        # 2026-09-11 第三輪：沒有鉤子行的標題改走「由上往下遞增」（範本 03／06 那招），
        # 有鉤子行才是「鉤子最大」。BRIEF 這條標題沒有 ！／？，所以是遞增那句。
        self.assertIn("GROW FROM TOP TO BOTTOM", BRIEF)
        hook = editor_formats.cover_design_brief(
            editor_formats.COVER_AI_TITLE_LEVEL_MAX, titles=("不放棄！ 數百人困隧道",), seed=0)
        self.assertIn("times the height of the smallest row", hook)
        self.assertNotIn("GROW FROM TOP TO BOTTOM", hook)

    def test_a_key_word_gets_pulled_out_inside_the_line(self):
        """「街道成河」、"致命漏洞"、名古屋、東京——關鍵詞在同一行裡換色／進紅框。
        沒有這一條，模型只會做「整行一個顏色」的老排版。

        2026-09-11 起這件事**釘在資料行上**（cover_line_annotation），不再只寫在條文區：
        條文區離行清單太遠，模型讀行清單時看不到（反色底字那次的教訓）。
        """
        self.assertIn("A colour switch may happen part-way through a row", BRIEF)
        annotated = editor_formats.cover_line_annotation("致命「都市型水患」", 4)
        self.assertIn("takes its own colour", annotated)
        self.assertIn("「都市型水患」", annotated)

    def test_the_palette_describes_the_reference_not_the_last_output(self):
        """上一版成品是整排金屬金。基準圖是飽和平塗＋粗黑描邊＋硬投影，
        所以要明文否定「整排同一種金屬填色」，不然模型會繼續交同一張。
        2026-09-11：顏色本身解放（不再釘白／黃／紅），但平塗＋硬投影的質感留著。"""
        self.assertIn("saturated FLAT poster colour", CLAUSE)
        self.assertIn("hard offset drop shadow", CLAUSE)
        self.assertIn("not one uniform polished metallic fill", CLAUSE)

    def test_pictograms_are_allowed_but_carry_no_writing(self):
        """基準圖上有⚡🔥☔⚠。圖示不是文字，可以開；但圖示裡一旦有字就繞過了硬規則 (e)。
        2026-09-11 起圖示是招式池的一員（由程式抽），所以在池子與硬規則兩邊各驗一次。"""
        pool = dict(editor_formats.COVER_ACCESSORY_POOL)
        self.assertIn("WORDLESS PICTOGRAM", pool["icon"])
        self.assertIn("never covering a stroke", pool["icon"])
        self.assertIn("wordless symbols only", CLAUSE)
        self.assertIn("never captions", BRIEF)

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
