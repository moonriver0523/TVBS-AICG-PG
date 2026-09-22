# AICG 進度存檔（2026-09-22）

## 分支狀態
- `exp/redesign-20260903`，VERSION `260922-04`
- 全量 **2303 題綠**（0 失敗 0 錯誤，1 expected failure）
- 公司 `aicg-champion/main`：**這一波還沒開 PR**

## 這一波（0922 使用者回報四件事）

| 項目 | 結果 |
|---|---|
| **B83** 追加修改後標籤消失 | 🟢 已修。`ImageRefineRequest` 補 `disclaimer_*` 三欄，`refine_image()` 補呼叫 `apply_image_disclaimer` |
| **B84** F38 的 2K 兩條路失效 | 🟢 已修。第二／三頁生圖與 refine 都補送 `density` |
| **F47** 標籤事後改角落 | 🟢 已上線。新端點 `POST /api/images/restamp-disclaimer`，零生圖呼叫 |
| **B85** 編輯CG 原圖放置被重畫 | ⬜ 已診斷，**不動工**——是 D25 待裁 |
| **B86** 未置框那條路會被貼第二枚標籤 | 🟢 已修。顧問複查抓到，測試全綠時沒人看得見 |

**全部都還沒實機驗證**，等使用者實拍。

## B86（自己做出來的新缺陷，沒上線就攔下了）
記者＋安全框 OFF 時 `finalize_image_result` 提早 return，`source_image_base64` 留空，
前端 `refineSourceFromResponse()` 就退而取**成品本身**——而成品已經有一枚標籤。
那張再送進 refine／restamp 會被貼上第二枚（舊角落一枚、新角落一枚）。
`ImageRestampRequest` 的 docstring 自己就寫了「再貼會變兩枚」，卻沒有東西擋住它；
我原本的測試餵的是乾淨圖，看不到。修法：`apply_image_disclaimer` 在
`source_image_base64` 為空時把「貼標籤之前」那張補進去（置框那條路已有值就不動）。
編輯身分一律置框，所以使用者那條路碰不到——**會中彈的是記者**。

## B83 的兩個要點（改到這塊的人一定要讀）
1. **「示意圖」也一起中彈**，不只使用者看到的「畫面來源」。refine 直呼
   `generate_image_raw`，整條路從來沒經過 `apply_image_disclaimer`。
2. **不准重判**。refine 不送 `portrait_subjects`，讓後端重判會把一張本來標
   「示意圖」的具名肖像，因為來源名還留在輸入框而降級成「畫面來源」——那是對觀眾
   說謊。所以 `ImageGenerateResponse` 新增三格記下**實際貼上**的那一組，前端
   `appliedDisclaimer()` 讀的是**回應**不是輸入框。具名換臉（`replacement_person`）
   強制 `ai` 並清掉來源名。

## 1748×924 不是 bug（使用者原報的那半）
編輯對位框（安全框 OFF）的成品**本來就是** 1748×924——2026-08-19 裁決，
`safe_frame.apply_safe_frame` docstring 寫明「輸出就是拉伸後的安全區本身」。
使用者該次用的是「字少／不改字」檔，屬設計如此。要改成整張輸出＝推翻 08-19 裁決，
已立 **D24** 待裁（選項二會把 2026-08-17 編輯抱怨過的那兩條漸層色帶帶回來）。

查這件事**連帶**抓到 B84：兩條路漏送 `density`，F38 的 2K 從沒在那兩條路成立過。

## B85：編輯CG 原圖放置——不是回歸，是從來沒接
`main.py:999` 白紙黑字：asis「是 prompt 層級要求，模型仍可能有壓縮/色偏等落差，
**不保證像素級一致**」。`apply_user_references_to_image_request()` 對 asis 只注入
一段文字規則，沒有任何閘門或程式疊圖。B55 的四刀（透明底標題圖層＋四道閘＋逐像素
疊圖）**只做在十點不一樣與 YT 封面**（`_cover_ai`／`protect_base`），編輯CG 完全沒接。
而 B55 自己已實測證明 prompt 擋不住（創意 0 級 change_ratio 68.1%）。
→ **D25 待裁**：移植 B55 整套／改程式壓字／維持現狀但把前台說明改對。

## 下次開工順序建議
1. **實機驗 B83／B84／F47**（三件都沒實拍過，這波最大的未知）
2. **D24／D25 兩題裁決**
3. 排 sol 獨立複查，範圍限「新接的東西＋刪掉的行」（0921 的結論仍有效：
   這個專案的測試擋不住「東西是壞的但全綠」）
4. 公司 PR
5. 0920 那批新列管：F44／B78／B79／B80（素材與幾何都齊了）／B81
6. B73 的 20 道守門測試（一直被擱置）

## 0921 那條結論仍然有效
gpt-5.6-sol 三輪複查抓到 9 個真缺陷，**全都是在測試全綠的狀態下抓到的**，
其中 4 個會讓標籤整個消失。B83 又是同一種（refine 那條路測試甚至把缺陷寫成了規格：
`test_the_refine_path_does_not_send_them`）。**每一波都該排獨立複查。**

## 踩到的坑（別再踩）
- **worktree 沒有自己的 `.venv`**，要借主 repo 的：
  `/e/GitHub/TVBS-AICG-PG/.venv/Scripts/python.exe -X utf8 "<run_tests.py>" "<worktree 絕對路徑>"`
- repo **沒有 pytest**，一律用 scratchpad 的 `run_tests.py`；`loader.discover` 要用
  `pattern="test*.py"`，給 `top_level_dir=repo` 會 `ImportError: Start directory is not importable`
- 跑單一模組要 `cd tests` 再 `python -m unittest <模組名>`
- 全量輸出很長，**只 grep 摘要行**（`^Ran |^OK|^FAILED|^=== 合計`），不要整段讀進 context
- **測試裡用 `split()` 錨字串前先確認它在檔案裡唯一**——F47 的 `restampDisclaimer()`
  和 refine 都有 `source_image_base64: state.refineSource.base64`，且前者排在前面，
  害 B83 的測試抓錯段落。錨 `fetch(XXX_BACKEND_URL` 才穩
- 新增任何 `@app.post` 端點，`tests/test_admin_console_formats.py` 會紅：要嘛補
  `_archive_generation` **和** `_record_generation_failure` 並加進 `IMAGE_ENDPOINTS`，
  要嘛加進 `known_textonly`
- `MASTER-列管清單.md` 每一列是一行超長文字，**不要整份 Read**，用 `grep -n`／`awk -F'|'`
  （`$2`=ID、`$5`=狀態、`$6`=說明）
- **子代理很會只改說明欄、不改狀態欄**，驗收時一定要單獨看 `$5`
- **子代理會捏造「使用者裁示」**，合併前 `grep -n "裁示\|裁定\|team-lead"` 掃一遍
- `git add -A` 會把未追蹤檔一起提交——**一律列明路徑**
- **版本號要手動跳，每次改動都要**（曾連 14 個 commit 忘記）
