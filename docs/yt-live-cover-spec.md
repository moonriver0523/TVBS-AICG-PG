# YT 直播封面（編輯版型 `yt_live_cover`）規格

2026-09-05 依使用者範例（`Claude共用/YT直播封面範例.docx`：整點直播截圖、外電直播×2、
國內新聞事件直播×2）定案。**一套版型**，不拆子規格（使用者裁決）。

## 使用情境

編輯給一句直播標題，選副標，可附圖；出一張 1920×1080 的 YouTube 直播封面。

| 輸入 | 規則 |
|---|---|
| 標題 | **恰好一個半形空格**分兩段就直接切；零個或兩個以上空格交給文字模型判斷。AI 只決定分段點，字元從原標題切（保留原有空格）；AI 若改了任何字就不採用，退回「第一個空格／對半切」。 |
| 副標 | 無／原音重現／AI即時翻譯（`editor_formats.YT_COVER_SUBTITLES`，前端下拉與後端 enum 由測試對齊） |
| 日期 | 預設當天 `YYYY/MM/DD`，前端可改 |
| 附圖 | 沿用主流程上傳區與四種用途。**原圖放置（asis）＝直接當底圖，不打生圖模型**；scene／portrait／map＝生圖時當參考，用途規則照主流程注入 |

## 底圖三條路

1. 有 asis 附圖 → `compose.crop_background_16x9` 裁滿 16:9。不標 AI示意圖。
2. 有其他用途附圖 → `generate_image_raw` 帶附圖生無文字底圖。標 AI示意圖。
3. 沒附圖 → 文字模型（`YT_COVER_DERIVE_SYSTEM`）依標題補畫面描述＋列出具名真人 →
   `apply_portrait_to_image_request` 走主流程查參考照（最多三張臉，與網站規則一致）
   → 生無文字底圖。標 AI示意圖。

生圖 prompt 最後固定壓 `YT_COVER_TEXT_FREE_OVERRIDE`：肖像與附圖規則都寫著「示意圖
標籤要保持可見」，不壓掉模型會自己畫一個「示意圖」字樣。

## 固定元素（全部由 `compose.compose_yt_cover` 疊，零錯字）

- 左上 LIVE 章：`static/brand/live-badge.png`（從範例截下、放大 2 倍、圓角遮罩；
  官方去背檔到手直接換檔，位置尺寸不用動）
- LIVE 章下方白色日期條：程式畫，紅字
- 右上正版 TVBS Logo；副標在 Logo 下方（白字黑描邊）
- AI 底圖時副標下方小字「AI示意圖」（半透明黑底）
- 底部兩行標題：第一行白、第二行黃，黑描邊，字級依寬度自動縮
- 幾何全以畫布比例計（量自範例 1376×768），常數在 `compose.py` `YT_*`

## 追加修改（使用者裁決：只改底圖，文字重疊）

- 回應的 `source_image_base64` 是**無文字底圖**，前端 `refineSource` 直接接上。
- 追加修改送 `/api/images/refine` 帶 `text_free=True`（`news_prompt.TEXT_FREE_REFINE_RULES`，
  不用帶文字 CG 的那套規則），改完再打 `/api/editor/yt-cover` 帶
  `background_image_base64` 重疊一次文字。
- 「只改文字」按鈕：底圖不重生，只用目前標題／副標／日期重疊。

## 端點

`POST /api/editor/yt-cover`（`YtCoverRequest` → `YtCoverResponse`）。
能不打 API 就不打：標題已分好＋底圖不用生時零 API 呼叫。

## 已驗證（2026-09-05 本機 8790）

- 無附圖（挪威國王，`gpt-image-2`）31 秒；asis 附圖 14 秒（含一次分段呼叫）。
- 瀏覽器：切版型→生成→只改文字（8 秒）→追加修改「改成夜晚」（34 秒）→退回上一版可用。
- 測試：`tests/test_yt_cover.py` 24 個；全套 693 綠。

## 未做／待裁決

- 範例「男護理師」那張（Logo／LIVE 互換、第三行警語、漸層字）不在規格內。
- 「整點直播」只有 YT 截圖沒有成品範例，未獨立處理。
- LIVE 章目前是範例截圖放大，官方素材到手再換。
