# 十點不一樣封面規格（2026-09-06 斜切全幅版）

依 TVBS NEWS 頻道實際上線的十點不一樣封面重畫（型錄 `D:\Downloads\aicg_font_20260906\catalog\15.png`），
取代 2026-09-03 的「標頭帶＋兩圖並排＋圖下標題帶」版。

## 版面（compose.compose_ten_cover，畫布 1920×1080）

- **底圖**：兩張圖斜切鋪滿整個畫面，格間一道白色細斜線（與 YT 直播封面多圖分切共用
  `compose.split_canvas`，斜度 `YT_SPLIT_SLANT_RATIO`）。每格各自 COVER 裁切不變形。
- **下半壓暗**：每格自 42% 高度往下漸暗（`COVER_SHADE_*`），標題才壓得住亮照片。
- **標頭帶**：畫面頂端 10.5% 高的深藍帶，底緣一條亮藍細線。由左至右：正版白色 Logo、
  「十點不一樣」藍色小標籤、日期（白字）、ON AIR／精華紅色標籤（前有白點）。
- **AI示意圖**：標頭帶下方、各格外側角落的半透明黑底小標，**只有 AI 底圖那格才印**。
- **標題**：各格下緣，左格靠左、右格靠右，最多 3 行由下往上堆，全格同一字級（以最寬行決定）。
  逐行配色：第 1 行白、第 2 行黃、第 3 行紅（紅字白描邊，其餘深色描邊），外加陰影。
  這張配色表 `COVER_TITLE_LINE_COLOURS` 同時是純 AI 版 prompt 描述的配色規則。
- **底部波紋**：5% 高的藍色飾條，兩條淺藍波紋線。

## 標題分行（editor_formats.split_cover_title）

- 使用者用半形／全形空白、換行、｜、/ 自己分，最多 3 行，多的併進最後一行。
- 沒分且超過 7 字：對切兩行。
- **只切不改字**：分行接回去必須等於原標題去掉分隔符。

## 原圖放置（TenCoverRequest.reference_images）

- 用途 `asis` 依上傳順序：第 1 張＝左格、第 2 張＝右格；只有 1 張時右格照常 AI 生；
  超過 2 張只取前 2 張並記 log。
- 有任何 asis 一律強制合成版（`mode` 改 `composite`），真照不進生圖模型；回應 `mode`
  會反映實際採用的模式，`left_is_ai`／`right_is_ai` 說明哪格是 AI 底圖。
- 兩格都 asis 時不打文字模型補畫面描述，一次 API 都不打。
- 其他用途（實景／肖像／地圖）當要生的那格的生圖參考（`apply_user_references_to_image_request`）。

## 純 AI 版（COVER_AI_PROMPT_TEMPLATE）

prompt 的版面描述已同步成斜切全幅＋薄標頭帶＋白／黃／紅逐行；「十點不一樣」是帶內小標籤
而非大標題。Logo 仍由程式後貼（`paste_cover_logo`）。

## 測試

`tests/test_ten_cover.py`：分行規則、斜切像素、標頭與波紋、AI示意圖只印 AI 格、
三色標題、端點（雙 asis 零 API、單 asis 左格、無 asis 維持 ai 模式）、prompt 同步。
