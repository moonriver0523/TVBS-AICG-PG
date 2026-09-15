# 2026-09-09 使用者回饋批次

延續 `docs/plan-20260908-user-feedback.md`。這批來自使用者當天上午的六點回報，
附了三張成品截圖（兩張 YT 封面：今日熱搜／國內外新聞直播；一張播出鏡面）。

---

## 0. 先結案：正臉規則**沒有**失效（不需修）

使用者問「這兩張不知為何也沒畫正臉，之前修過的正臉規則可能有失效？」

查 Cloud Run 記錄（`gcloud logging read`，2026-09-08T18:11～18:15Z，即 9/9 凌晨 02:11 台北時間）：

```
[yt-cover] 查不到任何一位的參考照（李柏毅），保留名單走「不生成臉孔」規則
[yt-cover:ai-title] portrait_subjects=['李柏毅'] en=['Li Po-yi'] 參考照=0 張 附圖=0
```

判定：流程完全照 2026-09-07 定的規則走——消化端**有**認出具名真人（李柏毅），
後端**有**去查參考照，但高雄市議員在維基百科沒有可用照片，`resolve_portraits`
於是退回 `PORTRAIT_NO_REFERENCE_RULES`（「不准畫任何具名真人的臉，畫背影或剪影」）。
背影正是這條規則要的結果，不是缺陷。

同一段記錄還顯示 `[yt-cover] AI 分段改了字，不採用` ——分段防呆也正常運作。

**使用者的解法**：想要正臉就自己附一張那個人的照片，用途選「肖像照片」。
（要不要改成「查不到照片時前端主動提示可附照」列為後續待議，本批不做。）

---

## 1. AI 生成字時的底色框要對齊合成版

**現象**：合成版（程式畫字）的底色框已經修過——高度不超過標題第二行、且半透明；
AI 生成字那條線的底色框還是又高又不透明（見附圖一、二）。

**根因**：合成版的框由 `compose._draw_title_band` 畫，
上緣 `YT_BAND_TOP_RATIO=0.778`（＝第一行基線）、羽化 0.0365 到全濃度、
`YT_BAND_ALPHA=153`（60%）。AI 版沒有程式可畫，只能靠 prompt，
而 `editor_formats.YT_COVER_BAND_CLAUSE_{NEWS,HOT}_ON` 寫的是
「the lower **40%** of the frame」——比合成版的 22% 高了將近一倍。

**做法**：把兩條 clause 改寫成**關係式**描述（模型跟得動「在第二行字後面」，
跟不動百分比）：框只在下方標題那一行後面，上緣從第一行的**基線**開始淡入，
到第二行字的上緣才到全濃度；半透明、照片透得出來。百分比保留但改成正確的值。

**檔案**：`editor_formats.py`；測試 `tests/test_yt_band_variants_and_overlay.py`、
`tests/test_yt_bottom_band.py`。

---

## 2. 直標（YT直播直標）縮短

**使用者要求**：
1. 整體長度太長，上下都太接近邊界；要**整體置中偏上**。
2. 字級再縮小、整體長度縮短。
3. 兩行直字之間的**行距**縮小。
4. 因為變短了，TVBS Logo 的**左下／右下**要同時開放選擇；左上／右上維持現行
   （不得與直標同側，會重疊）。

**現況**（`compose.yt_vertical_layout`）：
- `VSTRIP_TOP_RATIO=0.166` 起，`VSTRIP_BOTTOM_MAX_RATIO=0.90` 止，**上緣固定**、
  往下長。12 格主標時 `wanted = 12 × 0.080 = 0.96h` 被夾到 0.734h，
  於是從 0.166 一路長到 0.90——上下都貼邊，就是使用者說的「太長」。
- 兩欄各寬 `0.0445w ≈ 85px`，`VSTRIP_SEAM_RATIO=0` 不留縫。字級卻是由格距算的
  （`pitch × 0.92`），**跟欄寬脫鉤**——所以字級一縮，欄寬不動，兩行之間的空白反而變大。

**做法（已實作，2026-09-09）**：
- `VSTRIP_MAIN_PITCH_RATIO` 0.080 → 0.070（字級與長度一起縮）。
- **新增 `VSTRIP_COLUMN_MAX_RATIO = 0.64`**：色框總長度的硬上限。這一條才是關鍵——
  光縮格距擋不住最長的標題（14 格 × 0.070 = 0.98h），一定會被可用範圍夾成
  「從上緣長到下緣」，也就是使用者說的上下貼邊。封住總長度，格距與字級再由它反推。
- `VSTRIP_MIN_PITCH_RATIO` 0.045 → 0.040（隨總長度上限一起下修，14 格才過得了）。
- `VSTRIP_BOTTOM_MAX_RATIO` 0.90 → 0.94（這是**可用範圍**上限，不是實際長度）；
  新增 `VSTRIP_VERTICAL_ANCHOR = 0.38`：色框在可用範圍內置中偏上，不再固定貼上緣。
- 欄寬改成**由字級推導**：`VSTRIP_COLUMN_WIDTH_EM = 1.12`，
  `col_w = round(cell_size × 1.12)`。字級縮 → 欄寬跟著縮 → 行距自動變窄。
  字級 `cell_size` 一併回傳給 `compose_yt_overlay` 用，兩邊不會再各算一次。
- Logo：把「同側一律擋掉」放寬成「同側的**上**角擋掉」。同側下角允許，
  色框底緣夾在 `logo_y0 − gap` 以上；夾完格距低於 `VSTRIP_MIN_PITCH_RATIO`
  仍然丟 `ComposeError`（不默默畫壞），訊息會註明是 Logo 壓縮了高度。

**實測數值**（1920×1080，主標 9 格／副標 14 格）：
| 情境 | 色框上緣 | 下緣 | 長度 | 字級 | 欄寬 |
|---|---|---|---|---|---|
| 舊版 | 0.181 | 0.940 | 0.759 | 54px | 85px |
| 新版 | 0.227 | 0.867 | 0.640 | 45px | 50px |
| 新版＋Logo 左下同側 | 0.199 | 0.839 | 0.640 | 45px | 50px |
| 新版／短標題 6 格 | 0.310 | 0.731 | 0.420 | 70px | 78px |

**檔案**：`compose.py`、`main.py`（錯誤訊息不變）、`index.html`／`app.js`
（Logo 角落按鈕的 disabled 條件）；測試 `tests/test_yt_vstrip_ui.py`、
`tests/test_yt_band_variants_and_overlay.py`。

**先定版、可回頭調**：錨點取 0.38（置中偏上），LIVE 章與小標維持釘在原位不跟著浮動——
它們是「頻道固定元素」，跟著標題長短上下跑會很怪。副作用是**短標題**時色框離 LIVE 章
比舊版遠。樣張：`D:\Downloads\AICG_直標_前後對照_20260909.png`（長短各一，左前右後）與
`D:\Downloads\AICG_直標_新版四種_20260909.png`（四種選項組合）。
使用者若覺得短標題離 LIVE 章太遠，把 `VSTRIP_VERTICAL_ANCHOR` 調小即可（0＝貼著章底）。

---

## 3. 「畫面來源：」自動補字＋四角可選

**使用者要求**：使用者只填「美聯社」，上字時自動變成「畫面來源：美聯社」；
位置開放左上／右上／左下／右下四選一，但都要避開 TVBS Logo 以免打架。

**做法（已實作，2026-09-09）**：
- `compose.VSTRIP_SOURCE_PREFIX = "畫面來源："`，正規化函式 `compose.vstrip_source_text`（冪等）。合成前正規化：字串非空、
  且**不是**以「畫面來源」開頭時才補前綴（使用者習慣整句貼上，補兩次很醜）。
- `source_follow_logo: bool` → `source_corner: "" | tl | tr | bl | br`（`compose.vstrip_source_corner`）。
  空字串＝維持舊行為（由 `source_follow_logo` 決定），舊呼叫端逐字元不變。
  `source_follow_logo=True` 等價於 `source_corner = logo_corner`。
- 避讓規則：來源句貼在指定角落的內縮位置；若該角落**就是 Logo 的角落**，
  改成貼在 Logo 的另一邊（Logo 在上→句子在下、在下→句子在上，沿用
  `_vstrip_source_box_follow_logo`）；若該角落是 LIVE 章那一角，沿用
  `_vstrip_source_box`（貼在章旁邊）。
- 前端：來源句 placeholder 改成「美聯社」，位置那一列從兩顆按鈕改成四顆角落按鈕。

**檔案**：`compose.py`、`main.py`（`YtOverlayRequest`）、`index.html`、`app.js`；
測試 `tests/test_yt_vstrip_ui.py`。

---

## 4.「字多」要真的比較多（記者／編輯共通）

**現象**：字多消化後資訊量還是太少。

**根因**：三檔裡只有 `simplified` 與 `verbatim` 有 override 區塊，
`standard`（字多）**什麼都不注入**——它就是樣板本身。而編輯版樣板寫死
「總字數嚴禁超過 150-180 個字」「每行不超過 15 字」「條列重點」，
記者版樣板則只有「Concise phrases」沒有量的指示。於是「字多」＝樣板預設，
跟沒選一樣。

**做法**：新增 `STANDARD_DENSITY_RULES`，`density == "standard"` 時注入，
放在 `SIMPLIFIED_DENSITY_RULES` 的同一個位置（三檔互斥）。內容：
- 明文 OVERRIDE 上面的 150-180 字與每行 15 字：總量放寬、每行放寬。
- 資訊卡數量放寬（不再是固定三點）。
- 密度放寬：允許每張卡帶一行補充。
- 記者版沒有數字上限可蓋，改成正向指示：多列幾張卡、每張卡帶得動補充細節。

**播出鏡面**：`_BROADCAST_STAMP_{ON,OFF}` 第 6 條寫死「exactly three [內文小標]」，
字多時放寬到四張（`_BROADCAST_DENSITY_STANDARD` 已經讓每卡兩行，這次再加卡數）。

**⚠️ 會動到記者的 prompt**：`tests/test_reporter_prompt_frozen.py` 是「記者 prompt
一個字都不准變」的快照測試，`standard` 那一組必紅。這一批是使用者**明確要求**
記者也要跟著放寬，屬於該檔註解說的「真的要動記者 prompt 時，才連同快照一起更新」，
所以連同 `tests/fixtures/reporter-digest-standard-*.txt` 一起更新，並在此記錄原因。

**檔案**：`main.py`、`editor_formats.py`、`tests/fixtures/`；
測試 `tests/test_density_and_stamp.py`、`tests/test_broadcast_density.py`、
`tests/test_digest_prompts.py`。

---

## 5. 播出鏡面：留白側的最底下要能放資訊

**現象**（附圖三）：挖空框是 16:9，垂直置中貼在留白半邊，
於是那半邊的**最下方**留了一條完全空白的橫帶，看起來很怪。

**幾何**（`compose.broadcast_hole_rect`，安全區 1634×751）：
框寬 `1634 × 0.45 = 735 → 720`（對齊 16 的倍數），高 `720 × 9 ÷ 16 = 405`；
可用帶 `751 − 24 × 2 = 703`，垂直置中 → 框上緣距安全區頂 `24 + 149 = 173`，
框底距安全區底也是 `173`。**下方那條空白帶約 173px（安全區高的 23%）**，
放一行結論綽綽有餘。

**做法**：把 `_BROADCAST_STAMP_ON` 第 5 條反過來——蓋章橫幅改成
**橫跨全寬、貼在挖空框底下的那條低帶**，不再縮在內容半邊。
標題（跨全寬、在上）與蓋章（跨全寬、在下）於是上下對稱夾住挖空框。

**兩個要注意的**：
- `apply_broadcast_hole` 的「示意圖」浮水印永遠畫在安全區的右下角，
  會壓到跨全寬的蓋章條。所以 prompt 要加一句「最右下角留空，之後會蓋一個小標記」
  （沿用封面那套「留角落給程式貼」的寫法）。
- 這段文字裡**不得出現任何數字**（既有鐵律），位置一律用方位詞。
- ~~蓋章 OFF 時那條帶仍然空著~~ → **2026-09-09 第三批已補**：使用者裁決
  「沒有開蓋章，其他資訊還是可以放底下」，`_BROADCAST_STAMP_OFF` 改成把最後一張
  [內文小標] 下移到底帶跨全寬（仍是一般卡片、不是收尾標語，右下角一樣留給浮水印）。
  實測樣張 `D:\Downloads\20260909-171257-C-*.png` 與 `-D-*.png`，左右兩側都驗過。

**檔案**：`editor_formats.py`；測試 `tests/test_broadcast_hole_switch.py`、
`tests/test_stamp_off_guard.py`、`tests/test_editor_formats.py`。

---

## 執行順序與驗收

1. 第 1、4、5 項純 prompt 字串，先做，跑全套測試補快照。
2. 第 2、3 項動幾何與 API，後做，出樣張給使用者挑錨點。
3. 全套測試綠 → 落 docs（docs 進 main worktree）→ **等使用者下令才部署 Cloud Run**。
   上一批 Logo 修正線上也還沒部署（線上仍是 `00064-mdv`），這兩件事要一起問。
