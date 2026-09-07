# 十點不一樣封面規格（2026-09-06 斜切全幅版）

依 TVBS NEWS 頻道實際上線的十點不一樣封面重畫（型錄 `D:\Downloads\aicg_font_20260906\catalog\15.png`），
取代 2026-09-03 的「標頭帶＋兩圖並排＋圖下標題帶」版。

## 版面（compose.compose_ten_cover，畫布 1920×1080）

- **底圖**：兩張圖斜切鋪滿整個畫面，格間一道白色細斜線（與 YT 直播封面多圖分切共用
  `compose.split_canvas`，斜度 `YT_SPLIT_SLANT_RATIO`）。每格各自 COVER 裁切不變形。
- **下半壓暗**：每格自 42% 高度往下漸暗（`COVER_SHADE_*`），標題才壓得住亮照片。
- **標頭帶**：畫面頂端 10.5% 高的深藍帶，底緣一條亮藍細線。由左至右：正版白色 Logo、
  「十點不一樣」藍色斜切標籤（**貼模板** `static/brand/ten-show-tag.png`，gpt-image-2 依型錄原版重繪、
  透明底，高度佔帶高 80%；2026-09-07 起不再用程式畫）、日期（白字）、ON AIR 紅色標籤（前有白點）。
- **精華**：標頭照樣是 ON AIR，另在畫面水平正中、頂端 67% 高處貼一枚圓章模板
  `static/brand/ten-highlight-stamp.png`（深藍圓＋藍色光環＋「十點不一樣／精華」黃字，直徑佔畫布高 23%，
  gpt-image-2 依型錄 0819 原版重繪）。2026-09-07 起取代原本標頭紅字「精華」，位置照原版跨在底部標題區上。
- **AI示意圖**：標頭帶下方、各格外側角落的半透明黑底小標，**只有 AI 底圖那格才印**。
- **標題**：各格下緣，左格靠左、右格靠右，最多 3 行由下往上堆，全格同一字級（以最寬行決定）。
  逐行配色：第 1 行白、第 2 行黃、第 3 行紅（紅字白描邊，其餘深色描邊），外加陰影。
  這張配色表 `COVER_TITLE_LINE_COLOURS` 同時是純 AI 版 prompt 描述的配色規則。
- **底部飾帶**：貼模板 `static/brand/ten-bottom-line.png`（深藍帶＋一道發光藍色直線，寬撐滿、約 4% 高）。
  2026-09-07 起取代波紋：查 YouTube 18 張原版，波紋只出現 1 張；不帶警語的底部是 0901／0902 的直線光。

## 標題分行（editor_formats.split_cover_title）

- 使用者用半形／全形空白、換行、｜、/ 自己分，最多 3 行，多的併進最後一行。
- 沒分且超過 7 字：對切兩行。
- **只切不改字**：分行接回去必須等於原標題去掉分隔符。

## 原圖放置（TenCoverRequest.reference_images）

- 用途 `asis` 依上傳順序：**1 張＝整版鋪滿**（不切格、不生另一格，兩標題壓左下／右下）、
  2 張＝左格＋右格；超過 2 張只取前 2 張並記 log。
- 有任何 asis 一律強制合成版（`mode` 改 `composite`），真照不進生圖模型；回應 `mode`
  會反映實際採用的模式，`left_is_ai`／`right_is_ai` 說明哪格是 AI 底圖。
- 有 asis（1 張或 2 張）都不打文字模型補畫面描述，一次 API 都不打。
- 其他用途（實景／肖像／地圖）當要生的那格的生圖參考（`apply_user_references_to_image_request`）。

## 純 AI 版（COVER_AI_PROMPT_TEMPLATE）

prompt 的版面描述已同步成斜切全幅＋薄標頭帶＋白／黃／紅逐行；「十點不一樣」是帶內小標籤
而非大標題。Logo 仍由程式後貼（`paste_cover_logo`）。

## 測試

`tests/test_ten_cover.py`：分行規則、斜切像素、標頭與底部飾帶、AI示意圖只印 AI 格、
三色標題、端點（雙 asis 零 API、單 asis 左格、無 asis 維持 ai 模式）、prompt 同步。

## AI 消化標題（/api/editor/cover-titles）

十點與 YT 封面欄位各有「新聞內文」textarea＋「AI 消化標題」鈕。貼內文 → 文字模型
（system prompt 接 `CONTENT_FIDELITY_RULES`）出十點兩標題（各 2–3 段，空格分行）或 YT 單標題
（兩段）→ 回填標題欄位，**不接生圖**，編輯看過再自己按「生成」（2026-09-06 使用者裁決）。
裁切到欄位上限（40／60 字）；模型失敗回 502。每次多一次文字模型呼叫。
