# 十點不一樣封面規格（2026-09-06 斜切全幅版）

依 TVBS NEWS 頻道實際上線的十點不一樣封面重畫（型錄 `D:\Downloads\aicg_font_20260906\catalog\15.png`），
取代 2026-09-03 的「標頭帶＋兩圖並排＋圖下標題帶」版。

## 版面（compose.compose_ten_cover，畫布 1920×1080）

- **底圖**：兩張圖斜切鋪滿整個畫面，格間一道白色細斜線（與 YT 直播封面多圖分切共用
  `compose.split_canvas`，斜度 `YT_SPLIT_SLANT_RATIO`）。每格各自 COVER 裁切不變形。
- **下半壓暗**：每格自 42% 高度往下漸暗（`COVER_SHADE_*`），標題才壓得住亮照片。
- **標頭帶**：畫面頂端 10.5% 高的深藍帶，底緣一條亮藍細線。由左至右：正版白色 Logo、
  「十點不一樣」節目標籤（**貼模板** `static/brand/ten-show-tag.png`：2026-09-07 使用者給的正版樣式——藍色斜切、
  金色「十」＋白字「點不一樣」、下行 NEWS NIGHT，gpt-image-2 重繪、透明底，高度佔帶高 80%；不再用程式畫）、日期（白字）、ON AIR 紅色標籤（前有白點）。
- **精華**：標頭照樣是 ON AIR，另在畫面水平正中、頂端 67% 高處貼一枚圓章模板
  `static/brand/ten-highlight-stamp.png`（深藍圓＋藍色光環＋「十點不一樣／精華」黃字，直徑佔畫布高 23%，
  gpt-image-2 依型錄 0819 原版重繪）。2026-09-07 起取代原本標頭紅字「精華」，位置照原版跨在底部標題區上。
- **AI示意圖**：標頭帶下方、各格外側角落的半透明黑底小標，**只有 AI 底圖那格才印**。
- **標題**：各格下緣，左格靠左、右格靠右，最多 3 行由下往上堆，**逐行各自撐滿格寬**（短行大、長行小，
  字級上限佔畫布高 11%，短行最多比最寬行大 1.35 倍 `COVER_TITLE_LINE_SIZE_SPREAD`，2026-09-07 起；
  原本全格同字級 8.5% 被使用者判定太小）。行距以當前行字級計算，逐行不同字級不重疊。
  超寬防呆：在起始字級塞不進格寬的行由 `wrap_cover_title_lines` 從中間拆成兩行（不切在數字中間，
  總行數仍 ≤ 3），拆完縮到最小字級仍超出就 `ComposeError`→400，不出超線的圖。
  逐行配色：第 1 行白、第 2 行黃、第 3 行紅（紅字白描邊，其餘深色描邊），外加陰影。
  這張配色表 `COVER_TITLE_LINE_COLOURS` 同時是純 AI 版 prompt 描述的配色規則。
- **底部飾帶**：貼模板 `static/brand/ten-bottom-line.png`（深藍帶＋一道發光藍色直線，寬撐滿、約 4% 高）。
  2026-09-07 起取代波紋：查 YouTube 18 張原版，波紋只出現 1 張；不帶警語的底部是 0901／0902 的直線光。

## 標題分行（editor_formats.split_cover_title）

- 使用者用半形／全形空白、換行、｜、/ 自己分，最多 3 行，多的併進最後一行。
- 沒分且超過 7 字：對切兩行。
- **只切不改字**：分行接回去必須等於原標題去掉分隔符。

## 具名真人肖像（2026-09-07 使用者回報：梅爾茨被畫成背影）

- 根因：這條線從沒接 `apply_portrait_to_image_request`，且補畫面描述的 prompt 明文禁止具名真人的臉。
- 現在 `COVER_VISUAL_DERIVE_SYSTEM` 比照 YT 封面：標題主角是具名真人就描述成正面肖像鏡頭，並回
  `portrait_subjects_left/right`（＋`_en` 英文維基名，例：梅爾茨 → Friedrich Merz；中文名單獨查不到）。
- `resolve_cover_visuals` 回 `CoverVisuals`（tuple 子類別，多帶 `.subjects`／`.english`），**描述有填也照打
  一次文字模型**——不打就沒有名單，具名真人一律背影。附圖格（asis）不打。
- 三條生圖路徑（雙切每格 `_cover_panel_image`、滿版 `_cover_full_image`、AI 整張 `_cover_ai`）都走
  `_cover_apply_portraits`：肖像規則＋維基參考照 → 附圖用途規則，與其他版型同一套（查不到照舊背影）。
- 本機 native 模式（`IMAGE_BACKEND=native` + gpt）送不出參考圖，會走 no_reference；正式站 OpenRouter 才會畫臉。

## 合成版底圖的無文字覆寫（2026-09-07）

- 合成版的兩條生圖路徑（雙切每格 1:1 `_cover_panel_image`、滿版 16:9 `_cover_full_image`）產的是
  **無文字底圖**，文字全部由 Pillow 疊。但肖像規則與附圖用途規則都寫著「示意圖標籤要保持可見」，
  不壓掉模型會自己在底圖上畫一個「示意圖」字樣，程式疊的字蓋不掉。
- 所以 `_cover_apply_portraits(..., text_free=True)` 在肖像規則＋附圖用途規則**之後**追加
  `editor_formats.YT_COVER_TEXT_FREE_OVERRIDE`——與 YT 直播封面 `_yt_cover_background` 同一段，
  不另開一套措辭。AI 整張版（`_cover_ai`）就是要模型畫字，**不加**。

## 兩個獨立版型：滿版／雙切（2026-09-07 使用者裁決）

- `ten_cover`＝**十點不一樣（雙切）**：左右兩格各一個標題、各一個附圖位（下節）。`layout="split"`。
- `ten_cover_full`＝**十點不一樣（滿版）**：一張圖鋪滿、**一個標題**（`title_left`，`title_right` 留空）。
  附圖位（`asis_left`）有圖就直接鋪滿（強制合成版、零 API）；沒圖就生一張 16:9
  （`COVER_VISUAL_FULL_PROMPT_TEMPLATE`）。標題**橫跨整寬置中**、逐行各自撐滿（比照今日熱搜，字級上限
  `COVER_FULL_TITLE_SIZE_RATIO`=15%、寬 90%，最多 3 行，白／黃／紅）。AI 整張版用 `COVER_AI_FULL_PROMPT_TEMPLATE`
  （單張照片、單一標題、無斜線）。`model` 記 `ten-cover-full:<mode>[-asis]`。
- 「AI 消化標題」對滿版送 `target="ten_cover_full"`，回單一 `title`（2–3 段）。
- 前端同一組欄位：滿版隱藏右半標題／右半附圖（`.cover-split-only`），左標籤改「標題」。

## 左右附圖位（TenCoverRequest.asis_left／asis_right，2026-09-07，雙切）

- 使用者裁決：左右格各自一個上傳位（data URL），才不會分不清哪張是左、哪張是右。
- **有圖的格直接上版，沒圖的格生底圖**：左有右無＝只生右格（`model` 記 `-asisL`／`-asisR`／`-asisLR`），
  `left_is_ai`／`right_is_ai` 反映哪格是生的。只有一格有圖時**不做全版**。
- 兩格都有圖：零 API。一格有圖：有圖那格的畫面描述用標題佔位，只有要生的那格留空時才打一次文字模型補。
- 任一附圖位有圖就強制合成版（`mode` 改 `composite`），真照不進生圖模型。
- 前端（index.html `coverAsisLeft*`／`coverAsisRight*`）在十點版型下，通用「附參考圖」清單不再提供「原圖放置」用途。

## 舊路徑：原圖放置（TenCoverRequest.reference_images，附圖位都空時才生效）

- 用途 `asis` 依上傳順序：**1 張＝整版鋪滿**（不切格、不生另一格，兩標題壓左下／右下）、
  2 張＝左格＋右格；超過 2 張只取前 2 張並記 log。舊呼叫端相容用，新前端不會走到。
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

## AI 整張版的後貼（2026-09-07）

純 prompt 版現在也由 `compose.paste_cover_logo` 貼 Logo＋節目標籤：prompt 要求模型把標頭帶**左半整個留空**、
不得寫節目名；貼圖幾何與合成版一致（以帶高 `COVER_AI_HEADER_RATIO`=10% 為準，Logo 佔 70%、標籤 80%，垂直置中）。
舊版 Logo 寬佔畫面 18.5%（量自 2026-09-03 的舊範例），在一成高的標頭帶裡整個爆出來壓到照片，已廢除。

## 成圖比例驗證（2026-09-07）

`_cover_panel_image`（1:1）、`_cover_full_image`（16:9）、`_cover_ai`（16:9）三條線都直呼
`generate_image_raw`，繞過 `finalize_image_result`。生成端間歇性降級（宣告支援卻回別的尺寸，
見 `verify_output_aspect_ratio` 的說明）以前不會被發現：1:1 的格子拿到 16:9，
`split_canvas` 會把它裁掉一半照樣合成。三條線拿到 result 後都補驗一次，降級當場 502。
`_cover_ai` 在 `paste_cover_logo` **之前**驗，貼完 Logo 才發現不對等於白貼。
