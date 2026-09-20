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

## 已接

| 版型 | 條件 | 保證來源 | 狀態 |
|---|---|---|---|
| 十點不一樣（滿版） | `mode="composite"` 且該格是原圖放置（`left_is_ai=False`） | `_cover_full_composite`：`background_image_base64`／`asis_left` 直接進 `compose.compose_ten_cover`，`is_ai=False` 那個分支完全不呼叫任何生圖函式（`_cover_full_image` 只在 `slot is None` 才叫） | ✅ 已接：`TenCoverRequest.source_left`，`compose_ten_cover(left_source_text=...)` |
| 十點不一樣（雙切） | `mode="composite"` 且該格是原圖放置（`left_is_ai`／`right_is_ai=False`） | `_cover_composite`：`_cover_panels` 對已有附圖的格直接回傳原始 bytes，不進 `_cover_panel_image` | ✅ 已接：`source_left`／`source_right`，各自獨立互斥 |
| 十點不一樣（雙切「只改文字」recompose） | 同上，`background_is_ai`／`background_right_is_ai` 帶回 False | `background_image_base64` 是「拼好但沒壓字」的底圖，重壓文字不重拼、不重生 | ✅ 已接：`source_left`／`source_right` 由前端原樣重送（純使用者輸入欄位，不像 `background_is_ai` 需要另開 carry-forward 欄位） |
| YT 封面 `title_mode="composite"`，四個 layout（news／hourly／hot／live24） | 該次生成是原圖放置（`is_ai=False`） | `_yt_cover_background` 對 asis 圖（`compose.crop_background_16x9`／`compose.split_backgrounds`）走純裁切／貼合，完全不經過生圖模型，回傳 `is_ai=False`；跟十點不一樣 composite 模式同一等級的保證 | ✅ 已接（2026-09-20 補接）：`YtCoverRequest.source_text`／`YtCoverResponse.source_text`；`compose.py` 的 `_draw_ai_note`／`_draw_live24_ai_note` 各加 `text` 參數，`compose_yt_cover`／`compose_yt_hourly_cover`／`compose_yt_hot_cover`／`compose_yt_live24_cover` 各加 `source_text` 參數＋互斥判定。dual（雙則）模式的底圖一律 `is_ai=True`（`yt_dual_background` 寫死），`source_text` 對它自動被忽略，不需要左右各一份 |
| YT 直播直標（`/api/editor/yt-overlay`） | 全部 | **不生圖、不打任何模型、沒有底圖**——透明 PNG 疊在直播訊號上，畫面內容不是這支端點管的 | ✅ 既有功能（`YtOverlayRequest.source_text`，2026-09-09 上線），F43 這批沒有新動它，列在這裡只為了盤點完整 |

⚠**已知限制（自己盤點時發現，未修，先寫清楚）：「只改文字」recompose 路徑的
`is_ai` 是前端回傳值，後端沒有重算。** 十點不一樣的 `background_is_ai`／
`background_right_is_ai`、YT 封面 `editor_yt_cover` 裡 `if ai_title and
req.background_image_base64:` 那支的 `is_ai = req.background_is_ai`，兩者都是
「前端把上一輪回應原樣帶回來」，不是後端從實際圖檔重新判定的。這個信任模型
**不是 F43 新引入的**——「AI示意圖」標籤在 F43 之前就已經靠這個值決定要不要畫；
F43 讓同一個值多背了一個更重的責任：以前值錯只會讓「AI示意圖」漏標（消極的
遺漏），現在值錯還會讓「畫面來源：○○○」被貼上去（積極宣稱這張圖沒被動過，
等於對觀眾說謊）。**沒有修**，原因：這是後端內部編輯工具（`verify_internal_
api_key` 認證），這個值在正常操作下永遠是「前端原樣回傳後端自己在上一輪算出的
真值」，只有前端本身有 bug 或有人手動兜出不一致的請求序列才會觸發；修法（後端
從實際位元組重新判定，或改用簽章/不透明 token 取代讓前端自己報）是比這批大的
改動，不在這次盤點與接線的範圍內，留給下一輪處理 recompose 信任模型時一併看。

## 故意不接（本批），與原因

⚠**2026-09-20 補充：`mode="ai"`／`title_mode="ai"` 的保證強度現在依 provider 分岔
（B55 修法甲），不是單一結論，兩條 provider 分開講：**

- **`provider=="gemini"`**：走舊的差異遮罩（`compose.restore_photo_outside_title_band`／
  `restore_yt_cover_photo`），模型仍整張重畫，只是事後用逐通道差異把字帶以外的
  像素「盡量」還原成原圖——這是機率性的補救，不是保證。2026-09-16 實拍量到這條路
  `change_ratio` 常態超標（見帳本 B55），**功能等同不可用**，不構成任何保證。
- **`provider=="gpt"`**：走透明底標題圖層（`transparent_mode`）——模型只回一張透明底
  的標題圖層，再用 `compose.overlay_title_layer_over_cover_band`／
  `overlay_title_layer_over_yt_cover` **逐像素**疊到 base 上，base 本身完全不經過
  模型。這條路架構上**確實可以做到跟 composite 模式同一等級的像素保證**——但
  **現在還不能依賴**：team-lead 複查點名（獨立複查 gpt-5.6-sol 發現、team-lead
  實測重現）三道閘有兩個活著的漏洞（alpha≤16 的薄層可以穿過去染到保護區；
  全透明輸入會三道全過、回傳一張沒有標題的原圖），team-lead 正在修
  `compose.py`（已改成四道閘）。**等這兩個漏洞修好且驗收過，`provider=="gpt"`
  的 `mode="ai"`／`title_mode="ai"`＋單張原圖放置這條路就有機會納入 F43**，
  是本批之後最有機會「原來不能接、變成能接」的一條路，不是要重新盤點整個判準。

| 版型 | 為什麼不接 | 依賴 |
|---|---|---|
| 十點不一樣，`mode="ai"`（含附了原圖當參考） | 見上方 provider 分岔說明；`provider="gemini"` 是機率性補救、`provider="gpt"` 架構上可行但閘門有已知活漏洞，兩者都不到「程式保證」的門檻。 | **B55**（`ladder` 代理同批在動，見下方「與 ladder 的關係」） |
| YT 封面 `title_mode="ai"` | 同「十點不一樣 mode=ai」——B55 YT 擴充也是同一套 provider 分岔（`main.py:7958` 附近的 `transparent_mode`），結論同上一列。 | 同上，B55 的兩個閘門漏洞。 |
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

## YT 封面 composite 補接紀錄（2026-09-20）

上一版這裡列的六個步驟已經照做完畢：

1. `main.py` `YtCoverRequest` 加了 `source_text: str = Field(default="", max_length=40)`；
   dual 模式的底圖一律 `is_ai=True`（`yt_dual_background` 寫死），不需要
   `source_text_second`。
2. `compose.py` `_draw_ai_note`／`_draw_live24_ai_note` 都加了 `text` 參數
   （預設值不變，既有呼叫端零行為改變）。
3. 四個合成函式（`compose_yt_cover`／`compose_yt_hourly_cover`／
   `compose_yt_hot_cover`／`compose_yt_live24_cover`）都加了 `source_text` 參數，
   `if ai_note: ... elif source_text.strip(): ...` 的互斥寫法。
   `_yt_news_or_hot_fixed_boxes`／`_yt_hourly_fixed_boxes`／`_yt_live24_fixed_boxes`
   這三支不算「呼叫點」——那是 B55 量測固定元素外框用的輔助函式，只在
   `provider="gemini"` 的差異遮罩路徑才用得到，跟 composite 模式的 F43 無關，
   沒有改動。
4. `editor_yt_cover` 端點在四個 layout 分支都把 `req.source_text.strip()` 傳給
   對應的合成函式。
5. `YtCoverResponse` 加了 `source_text: str = ""`，`is_ai=True` 時一律回空字串。
6. 測試見 `tests/test_f43_yt_cover_source_label.py`（13 題）：compose 層四個函式
   的互斥判定（6 題）＋端到端四種 layout（7 題，含 AI 生底圖時忽略、來源前綴
   正規化）。

`title_mode="ai"` 那條路維持不接，理由同上表。
