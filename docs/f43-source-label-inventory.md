# F43「畫面來源」標籤——各版型像素保證盤點（2026-09-20）

## 為什麼要有這份文件

F43 的規則很簡單：「圖是 AI 生成／被 AI 改過 → 標『示意圖』；圖是使用者原圖且
**程式保證**未被動過 → 標『畫面來源：○○○』。兩者互斥。」難的不是規則，是逐一
確認每個版型「程式保證」這句話是不是真的成立——掛錯了等於對觀眾說謊（宣稱一張
被模型重畫過的圖沒有被動過）。

這份文件記錄 2026-09-20 晚間盤點的結論：哪些版型已經接、哪些故意不接、為什麼。
下次要接其他版型時，先讀這裡，不用重新查一遍程式碼。

## 判準

**只有一種情況算「程式保證」**：那塊畫面內容從「使用者上傳」到「成品 PNG」全程
只經過裁切／縮放／貼合（Pillow 操作），完全沒有經過任何生圖模型。凡是被送進
`images.generate`／`images.edit`（不論是「當唯一輸入」還是「當參考圖附帶」）的
畫面，即使模型宣稱「只是參考」，**都不算保證**——本 repo 自己的教訓（B55）已經
證明「附了原圖當參考，模型還是會整張重畫」是實測會發生的事，不是理論上的風險。

## 已接（本批，commit 見 F43 接線 commit）

| 版型 | 條件 | 保證來源 | 狀態 |
|---|---|---|---|
| 十點不一樣（滿版） | `mode="composite"` 且該格是原圖放置（`left_is_ai=False`） | `_cover_full_composite`：`background_image_base64`／`asis_left` 直接進 `compose.compose_ten_cover`，`is_ai=False` 那個分支完全不呼叫任何生圖函式（`_cover_full_image` 只在 `slot is None` 才叫） | ✅ 已接：`TenCoverRequest.source_left`，`compose_ten_cover(left_source_text=...)` |
| 十點不一樣（雙切） | `mode="composite"` 且該格是原圖放置（`left_is_ai`／`right_is_ai=False`） | `_cover_composite`：`_cover_panels` 對已有附圖的格直接回傳原始 bytes，不進 `_cover_panel_image` | ✅ 已接：`source_left`／`source_right`，各自獨立互斥 |
| 十點不一樣（雙切「只改文字」recompose） | 同上，`background_is_ai`／`background_right_is_ai` 帶回 False | `background_image_base64` 是「拼好但沒壓字」的底圖，重壓文字不重拼、不重生 | ✅ 已接：`source_left`／`source_right` 由前端原樣重送（純使用者輸入欄位，不像 `background_is_ai` 需要另開 carry-forward 欄位） |
| YT 直播直標（`/api/editor/yt-overlay`） | 全部 | **不生圖、不打任何模型、沒有底圖**——透明 PNG 疊在直播訊號上，畫面內容不是這支端點管的 | ✅ 既有功能（`YtOverlayRequest.source_text`，2026-09-09 上線），F43 這批沒有新動它，列在這裡只為了盤點完整 |

## 故意不接（本批），與原因

| 版型 | 為什麼不接 | 依賴 |
|---|---|---|
| 十點不一樣，`mode="ai"`（含附了原圖當參考） | `COVER_AI_PROMPT_TEMPLATE`／`COVER_AI_FULL_PROMPT_TEMPLATE` 要求模型畫「整張」照片，即使附了 asis 參考圖，那張圖也只是生圖的輸入之一，成品像素是模型重繪的。B55 已經加了逐通道差異防呆（`compose.restore_photo_outside_title_band`／`PHOTO_PROTECT_MAX_CHANGE_RATIO`），但 **狀態是「已實作待實拍驗收」，門檻值還沒實拍調過**（見 MASTER-列管清單.md B55）。這批選擇不依賴一個自己都還沒驗收過的保證。 | **B55**（`ladder` 代理同批在動，見下方「與 ladder 的關係」） |
| YT 封面（news／hourly／hot／live24），所有 layout | `_yt_cover_background` 對 asis 圖（`compose.crop_background_16x9`／`compose.split_backgrounds`）回傳 `is_ai=False`，理論上跟十點不一樣同一等級的保證，**技術上可以比照十點不一樣的做法接**。這批沒接純粹是時間分配：先把十點不一樣一種版型做完整、測完整，比兩種版型都做一半更安全。函式與參數名稱見下方「下次要接的話」。 | 無（跟 B55／B78／B79 無關，純粹沒排進這批） |
| YT 封面 `title_mode="ai"` | 同「十點不一樣 mode=ai」，整張交給模型畫，即使有 asis 附圖也不保證。 | 同上，B55 的保護目前只包在十點不一樣，YT 封面這條路完全沒有保護機制。 |
| 一般新聞圖／播出鏡面（`/api/images/generate`、`/api/news-image`） | 這條線本來就沒有「原圖直接上版」的概念——每一張都是生圖模型畫出來的，沒有 asis 這種東西可言。不適用 F43，維持只有 B70 的「AI示意圖」邏輯。 | 無 |

## 與 `ladder` 代理的關係

`ladder` 這批同時在動 B55（原圖保護）、B78（無字檔創意階梯的框線）、B79（十點
標題行數）。B55 跟這份盤點的「`mode="ai"` 不接」判斷直接相關；B78／B79 動的是
創意階梯的版面設計與框線，跟這批實際改到的程式碼（`compose_ten_cover` 裡
`if left_is_ai: ... elif left_source_text: ...` 那兩行、`_draw_cover_ai_note`
多一個可選 `text` 參數）沒有交集——`ladder` 沒有理由去動 `is_ai` 這個 gate 本身
或 `_draw_cover_ai_note` 這支函式。**如果之後合併時真的在這幾個符號上撞車，
表示 `ladder` 那批也動到了 AI 標籤的貼字邏輯，屬於「合併順序」問題，不是我這批
的責任範圍，由 team-lead 判斷先後。**

## 下次要接 YT 封面的話，改哪裡

比照十點不一樣這批的做法：

1. `main.py` `YtCoverRequest` 加 `source_text: str = Field(default="", max_length=40)`
   （dual 模式的 `background_is_ai` 是單一 bool——`yt_dual_background` 一律
   `is_ai=True`，dual 模式本來就不會 asis，不用另外處理 `source_text_second`）。
2. `compose.py` `_draw_ai_note` 已比照 `_draw_cover_ai_note` 的模式加一個
   `text: str = YT_AI_NOTE` 參數了嗎？**還沒**——這是下次要做的第一步，做法完全
   一樣（見 `_draw_cover_ai_note` 的 diff）。
3. `compose_yt_cover`（news layout）、以及 hourly／hot／live24 各自的合成函式
   （`_draw_ai_note` 目前有 5 個呼叫點，見 `compose.py:1853/2064/2596/3436/3475`），
   每一個都要加 `source_text` 參數並比照 `if ai_note: ... elif source_text: ...`
   的互斥寫法。
4. `main.py` `_yt_cover_background` 已經回傳 `is_ai` 了，不用改；改的是拿到
   `is_ai=False` 之後把 `req.source_text` 往下傳給 `compose_yt_cover(...)`
   的呼叫端（`editor_yt_cover` 端點函式本體）。
5. 同樣要在 `YtCoverResponse` 加 `source_text: str = ""` 回顯。
6. 測試比照 `tests/test_f43_source_label.py` 的三段式寫法：compose 單元測試
   （互斥、正規化）＋端到端（asis 有/無來源名、AI 生底圖時忽略）。
