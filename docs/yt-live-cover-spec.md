# YT 直播封面（編輯版型 `yt_live_cover`／`yt_hourly_cover`）規格

2026-09-05 依使用者範例（`Claude共用/YT直播封面範例.docx`：整點直播截圖、外電直播×2、
國內新聞事件直播×2）定案。2026-09-06 使用者更正：整點直播是**另一個版型**，原版型更名
「YT國內外新聞直播」（`yt_live_cover`，layout=news），新增「YT整點直播」（`yt_hourly_cover`，
layout=hourly）。兩者共用同一條端點、同一套底圖流程與前端欄位，只有合成版面不同。

**2026-09-06 版面依據改為 TVBS NEWS 頻道實際直播封面**（使用者裁決）：掃了頻道「直播」
分頁 86 支縮圖（排除自動截圖），發現 docx 範例與上線版面不同，改照頻道版。對照圖存
`D:\Downloads\aicg_yt_cover_20260905\channel_survey\`。

## 使用情境

編輯給一句直播標題，選副標，可附圖；出一張 1920×1080 的 YouTube 直播封面。

| 輸入 | 規則 |
|---|---|
| 標題 | **恰好一個半形空格**分兩段就直接切；零個或兩個以上空格交給文字模型判斷。AI 只決定分段點，字元從原標題切（保留原有空格）；AI 若改了任何字就不採用，退回「第一個空格／對半切」。 |
| 原音呈現／AI即時翻譯 | 兩個**獨立勾選、可並存**（`original_audio`／`ai_translation`）。頻道用字是「原音**呈**現」不是「重現」。整點直播沒有這兩個（使用者裁決），前端藏、後端忽略 |
| 整點時間 | 整點直播專用，選填（如 `20:00`）；有填才掛在 LIVE 章下方 |
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

## 固定元素：國內外新聞直播（`compose.compose_yt_cover`，零錯字）

量自頻道 maxresdefault 1280×720，常數 `compose.py` `YT_*`：

- 底部深藍科技底帶（0.60 起漸入，半透明，撒固定序列的淡藍方塊模擬電路紋）
- 兩行標題**置中**壓在底帶上：第一行白、第二行黃，黑描邊，字級依寬度自動縮
- 左上 LIVE 章（`static/brand/live-badge.png`，生圖模型重製的高清去背版）；
  勾「原音呈現」時章往下讓位，上方壓白字紅邊「原音呈現」
- LIVE 章下方白色日期條、紅字；勾「AI即時翻譯」時日期條下方小白字黑邊
- 右上藍色漸層小標籤（左斜切、左下圓角，貼右上角）＋白色 TVBS Logo，程式畫
- AI 底圖時標籤下方小字「AI示意圖」（半透明黑底）
- 部分外電另有「圖片來源:AP」小字，**未做**（待裁決要不要加欄位）

## 固定元素：整點直播（`compose.compose_yt_hourly_cover`）

量自範例 YT 截圖去掉介面後的縮圖區（約 415×220），常數 `compose.py` `YT_HOURLY_*`：

- 左上小 Logo（寬 0.118）
- 右上 LIVE 章（寬 0.25）；有整點時間時章下接白底時間帶、紅字（頻道實際）
- 日期紅底白字圓角條，貼在第一行標題正上方（上緣 0.52）
- AI 底圖時「AI示意圖」小標放 LIVE 章（含時間帶）下方
- 兩行標題白／黃、黑描邊，左緣貼邊距，字級依寬自動縮
- 範例四周的青→桃紅漸層框是 YouTube 介面，不畫（使用者裁決）

## 追加修改（使用者裁決：只改底圖，文字重疊）

- 回應的 `source_image_base64` 是**無文字底圖**，前端 `refineSource` 直接接上。
- 追加修改送 `/api/images/refine` 帶 `text_free=True`（`news_prompt.TEXT_FREE_REFINE_RULES`，
  不用帶文字 CG 的那套規則），改完再打 `/api/editor/yt-cover` 帶
  `background_image_base64` 重疊一次文字。
- 「只改文字」按鈕：底圖不重生，只用目前標題／副標／日期重疊。

## 端點

`POST /api/editor/yt-cover`（`YtCoverRequest` → `YtCoverResponse`），`layout` 選 news／hourly，
hourly 另收 `time_text`。前端 `EDITOR_FORMATS[*].ytLayout` 帶到 `ytCoverFields()`。
能不打 API 就不打：標題已分好＋底圖不用生時零 API 呼叫。

## 已驗證（2026-09-05 本機 8790）

- 無附圖（挪威國王，`gpt-image-2`）31 秒；asis 附圖 14 秒（含一次分段呼叫）。
- 瀏覽器：切版型→生成→只改文字（8 秒）→追加修改「改成夜晚」（34 秒）→退回上一版可用。
- 測試：`tests/test_yt_cover.py` 32 個；全套 701 綠（2026-09-06 頻道版面後）。
- 頻道版面樣張：`D:\Downloads\aicg_yt_cover_20260905\F_news_channel_layout.png`（兩個標示都勾）、`F_news_plain.png`。
- 整點版本機合成樣張：`D:\Downloads\aicg_yt_cover_20260905\E_hourly_sample.png`。
- 2026-09-06 修正：切到 YT 版型時附圖上傳區留在角色鈕正下方、看起來像消失，
  現由 `applyEditorFormatInputs` 把它搬到 YT 欄位下面，切回主流程再搬回。

## 未做／待裁決

- 頻道另有兩種設計版型「氣象站」（主播去背＋雨量圖）、「國會風雲」（LIVE＋時間、雙主播去背、
  「主播+立委線上聊」），使用者裁決列入待辦之後再做（見 TODO.md）。
- 「圖片來源:AP」小字（外電 asis 附圖時），待裁決。

- 範例「男護理師」那張（Logo／LIVE 互換、第三行警語、漸層字）不在規格內。
- 整點直播的 Logo 用現有 `tvbs-logo-white.png`；範例是「TVBS NEWS」上下疊的版本，官方素材到手再換。
