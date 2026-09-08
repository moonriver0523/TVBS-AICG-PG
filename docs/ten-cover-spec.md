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
- **精華**：標頭照樣是 ON AIR，另在**標頭帶中段**貼一枚「精華」標籤模板
  `static/brand/ten-highlight-tag.png`（**紅色刷筆底＋白字「精華」，左右邊緣有刷痕**，1466×506 透明底）。
  幾何比照 Logo 與節目標籤：高度佔標頭帶高 80%（`COVER_STAMP_BAND_RATIO`），水平置中、垂直置中於帶內。
  2026-09-07 起取代原本標頭紅字「精華」；**2026-09-08 兩次裁決**：先是使用者實測回報原本的深藍圓章
  跨在底部標題區上（`COVER_STAMP_TOP_RATIO`=0.67）會壓到標題，接著把樣式整個換成紅色刷筆橫式標籤。
  標頭帶只有左半（Logo＋節目標籤）與右端（日期＋ON AIR）有東西，中段本來就空；兩個 AI 模板的
  HARD CONSTRAINTS 也明文「只有日期與紅標在標頭帶、位置在右端」，不會跟標籤搶位。
  合成版與 AI 版共用 `_draw_cover_highlight_stamp`。舊圓章 `ten-highlight-stamp.png` **檔案保留但已無引用**。
  不越界由 `test_highlight_tag_clears_the_title_area_and_the_header_contents` 守著。
- **AI示意圖**：標頭帶下方、各格外側角落的半透明黑底小標，**只有 AI 底圖那格才印**。
- **標題（雙切，2026-09-08 大改）**：各格下緣，左格靠左、右格靠右，最多 **3 行**
  （`COVER_MAX_TITLE_LINES_SPLIT`）由下往上堆，**兩格同一字級**。
  - 為什麼放棄「逐行各自撐滿」：使用者看了正式站成品後裁決「兩邊字不一樣大」不行。
    左格三行 6 字全是最大字級、右格第三行 11 字被壓小，看起來像兩張不同的圖拼的。
    現在每格先各自算出逐行都塞得進的字級（`cover_panel_title_size`），再取**兩格的最小值**
    當兩格所有行的字級。`COVER_TITLE_LINE_SIZE_SPREAD` 退場。
  - 拆行：寬度規則（`_wrap_pairs`，起始字級塞不進格寬就從中間拆）之外再加字數規則
    （`_fill_pairs`，一行超過 `COVER_TITLE_FILL_MIN_CHARS`＝7 字就再拆），最長的先拆，**上限 3 行**。
    行數一度放寬到 4，同日使用者看了樣張後改回 3——白黃紅只有三個顏色，第四行沒有顏色可配。
  - 垂直：3 行 × 字級 × 行距 1.06 必須落在標頭帶以下（`_cover_title_vertical_cap`），
    塞不下就兩格一起縮。拆完縮到最小字級仍超出寬度就 `ComposeError`→400。
  - **配色依行序**：第 1 行白、第 2 行黃、第 3 行紅（紅字白描邊，其餘深色描邊），外加陰影。
    2026-09-08 一度改成依段落（空格分段），同日使用者裁決改回依行——要的是「白黃紅三行」
    的固定視覺，兩段標題被拆成 3 行時第 3 行也要紅。段索引仍跟著行走
    （`cover_title_line_pairs` 回 `list[tuple[str, int]]`），但**只記錄出處、不決定顏色**。
  - 例：左「澳洲擬立新法 民眾可關閉社群媒體演算法」→「澳洲擬立新法／民眾可關閉社／群媒體演算法」，
    右「菲律賓前眾議長涉貪被捕 與總統小馬可仕為表兄弟」→「菲律賓前眾／議長涉貪被捕／與總統小馬可仕為表兄弟」；
    右格第 3 行 11 字算出 71px，兩格就一起用 71px，兩邊都是白黃紅。
- **標題（滿版）**：橫跨整寬置中、**逐行各自撐滿**（字級上限 `COVER_FULL_TITLE_SIZE_RATIO`=15%、
  寬 90%），上限仍是 3 行，不套雙切的字數拆行與共同字級——它沒有另一格要遷就。
  這張配色表 `COVER_TITLE_LINE_COLOURS` 同時是純 AI 版 prompt 的配色規則。
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

### 被剔除者禁畫（2026-09-08 審查必修）
`keep_subjects_with_photos` 回第 4 個元素＝查不到參考照而被剔除的人；`CoverVisuals.excluded`／`YtCoverPlan.excluded`
帶到生圖端，`_cover_apply_portraits`（十點）與 YT 兩條生圖在肖像規則之後接 `excluded_people_block`
（「這些人沒有可用參考照，不得畫出可辨識的臉；畫面描述提到就背影／剪影或不入鏡」）。否則剩一人時走的
單人肖像規則沒有「其他人不畫臉」條款，被剔除的那位會被模型憑空捏臉。

## 兩個獨立版型：滿版／雙切（2026-09-07 使用者裁決）

- `ten_cover`＝**十點不一樣（雙切）**：左右兩格各一個標題、各一個附圖位（下節）。`layout="split"`。
- `ten_cover_full`＝**十點不一樣（滿版）**：一張圖鋪滿、**一個標題**（`title_left`，`title_right` 留空）。
  附圖位（`asis_left`）有圖就直接鋪滿（強制合成版、零 API）；沒圖就生一張 16:9
  （`COVER_VISUAL_FULL_PROMPT_TEMPLATE`）。標題**橫跨整寬置中**、逐行各自撐滿（比照今日熱搜，字級上限
  `COVER_FULL_TITLE_SIZE_RATIO`=15%、寬 90%，最多 3 行，白／黃／紅）。AI 整張版用 `COVER_AI_FULL_PROMPT_TEMPLATE`
  （單張照片、單一標題、無斜線）。`model` 記 `ten-cover-full:<mode>[-asis]`。
- 「AI 消化標題」對滿版送 `target="ten_cover_full"`，回單一 `title`（一律 3 段，白／黃／紅；2026-09-08 起）。
- 前端同一組欄位：滿版隱藏右半標題／右半附圖（`.cover-split-only`），左標籤改「標題」。

### 滿版合成版的「只改文字」（2026-09-08）

合成版的成品＝一張底圖＋Pillow 壓上去的標題／日期／Logo，所以**改標題不必重生底圖**：

- **回應**帶 `background_image_base64`／`background_mime_type`／`background_is_ai`＝壓字前的底圖
  （`_cover_full_composite` 裡的 `slot`）。只有 `layout=full` ＋ `mode=composite` 會帶，AI 整張版留空。
  刻意**不塞進 `source_image_base64`**——那格的語意是「餵回 `/api/images/refine` 的原圖」，合成版
  一律留空（`tests/test_cover_refine.py` 的紅線 1）。混用會讓前端的「修改」鈕誤以為合成版能 refine。
- **請求**把那三個欄位原樣送回來（`mode=composite`），後端跳過生底圖與文字模型（`recomposite` 旗標
  併進 `has_asis or ai_overlay` 那條），直接走 `compose.compose_ten_cover`，`left_is_ai` 沿用
  `background_is_ai`（決定要不要壓「AI示意圖」）。一次 API 都不打，`model` 記
  `ten-cover-full:recomposite`（比照 YT 的 `yt-cover:recomposite`）。同時掛著附圖時**以底圖為準**：
  使用者按的是「只改文字」。
- **雙切合成版不支援**：成品是左右兩張底圖拼的，拼完分不回去。`layout=split` ＋ `mode=composite`
  ＋ 帶 `background_image_base64` 回 **400**（不默默忽略——那會把一個零 API 的請求變成重生兩張底圖）。
  雙切 AI 版的後貼路徑（`ten-cover:overlay`）不受影響。
- 前端：`state.tenCoverBackground` 存底圖（不共用 `refineSource`），`#coverRecomposeBtn`
  →`handleTenCoverGenerate(true)`；切版型就清掉並把按鈕收起來。測試在
  `tests/test_cover_full_recompose.py`。

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

**「AI示意圖」小標也改由程式壓（2026-09-07 裁決）**：兩個 AI 模板不再要模型畫這個標籤，
改成明文「不要畫任何示意圖標籤、把外側角落留乾淨，之後由程式加」。根因是只要使用者附了
實景參考圖，`apply_user_references_to_image_request` 就會追加「Do NOT render any 示意圖
label」——位置在後、又是明文 OVERRIDE，模型照做，標籤整個消失。做法比照 YT ai-title：
文字類固定元素一律後貼，標籤在不在不再取決於模型聽不聽話。
`compose.paste_cover_ai_note(image_bytes, split=...)` 在 `paste_cover_logo` 之後壓：
雙切左右格外側各一枚、滿版只有左上一枚，位置同合成版（標頭帶下方 2.5% 畫面高）。
幾何一律以**模型回來那張圖的解析度**為準——AI 版不是固定 1920×1080。

## 測試

`tests/test_ten_cover.py`：分行規則、斜切像素、標頭與底部飾帶、AI示意圖只印 AI 格、
三色標題、端點（雙 asis 零 API、單 asis 左格、無 asis 維持 ai 模式）、prompt 同步。

2026-09-07 的路徑對齊另有七支：`test_cover_text_free.py`（合成版底圖的無文字覆寫）、
`test_cover_aspect_guard.py`（五條線的成圖比例驗證）、`test_cover_photo_availability.py`
（查不到參考照的人先排除）、`test_cover_request_log.py`（落檔欄位與失敗記錄）、
`test_cover_ai_note.py`（AI示意圖小標由程式壓）、`test_cover_ai_title_lines.py`
（AI 版標題分行）、`test_cover_refine.py`（AI 版追加修改）；refine 規則在
`tests/test_refine_rules.py`。

**已知缺口**：兩個 AI 模板的「不要畫示意圖標籤」寫在 HARD CONSTRAINTS，而肖像規則
（`PORTRAIT_*_RULES`，內含「示意圖標籤要保持可見」）由 `_cover_apply_portraits` 加在
**後面**。依 repo 的「位置＋明文 OVERRIDE」慣例，有具名真人時後到的那段可能贏——模型
自己畫一個標籤、程式再壓一個。YT ai-title（`YT_COVER_FULL_PROMPT_*`）有完全相同的
狀態，這裡刻意維持一致，未一併加尾端 override。

## AI 消化標題（/api/editor/cover-titles）

十點與 YT 封面欄位各有「新聞內文」textarea＋「AI 消化標題」鈕。貼內文 → 文字模型
（system prompt 接 `CONTENT_FIDELITY_RULES`）出十點兩標題（各一律 3 段，空格分行，2026-09-08 起）或 YT 單標題
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

## 追加修改的品牌與具名真人條款（2026-09-07）

`news_prompt.build_refine_prompt` 兩條分支（一般 CG 與 YT 封面的無文字底圖）都加上
`REFINE_REAL_WORLD_RULES`：品牌條款逐字沿用主流程抽出的 `SOURCE_BRANDS_RULE`
（2026-09-07 起是「素材提到就可畫真實 LOGO、沒提到一律去識別化」），具名真人是精簡版
（沒有參考照就不得新畫任何具名真人的臉、既有的臉逐像素不動、背影仍是背影）。
理由：refine 是一次獨立的生圖呼叫，模型只看得到那支 prompt，原本只寫「不要新增事實與
logo」，一句「背景弄熱鬧一點」就能替沒提到的店家捏一個牌子，或補一張假臉。

## 參考照可用性：查不到的人先排除（2026-09-07）

`main.keep_subjects_with_photos`，封面與 YT 封面共用，是主流程 `apply_photo_availability`
在這兩條線上的等價物（它們沒有消化階段，名單是補畫面描述時一併產生的）。

- `resolve_cover_visuals` 每格拿到名單後先查一次照片，查不到的人從該格名單移除。
  不做會怎樣：`resolve_portraits` 是全有或全無，兩人裡一人查不到就整格退回不畫臉，
  連查得到的那位也變背影。
- 使用者上傳的肖像照（用途 `portrait`）視為對應「系統查不到的人」、依序保留幾位，
  假設與理由同 `apply_photo_availability`。附圖清單不分左右，兩格各以同一張數計。
- **全部都查不到時不清空名單**（刻意與主流程不同）：主流程清掉後會重新消化、
  版面描述也不再提那個人；封面沒有第二次消化，描述仍寫著「梅爾茨站在講台前正面半身」。
  名單一空就不注入任何肖像規則，模型會替真名捏一張臉。保留名單才會走 `no_reference`
  （明文禁止畫臉、改背影）。
- **已知缺口**：被移除的那位仍留在畫面描述裡，模型可能照樣把他畫進去（只是沒有名字
  標籤、也沒有參考照）。要補得靠第二次消化，成本是多一次文字模型呼叫，暫不做。
- 回傳的照片只用來落檔記出處；生圖端會再查一次（`apply_portrait_to_image_request`
  沒有收現成照片的參數，查圖有快取層，重查很便宜）。

## 落檔欄位（2026-09-07）

`/api/editor/cover`（雙切與滿版）與 `/api/editor/yt-cover` 的 `log_generation` 補上：

- `image_model`：三支生圖函式（`_cover_panel_image`／`_cover_full_image`／`_cover_ai`）
  改回 `(bytes, 生圖模型名)`，合成版兩支再往上回傳給端點。一次 API 都不打的附圖路徑
  記 `ten-cover:asis`／`ten-cover-full:asis`（比照 YT 的 `yt-cover:asis`）。
- `portrait_subject`／`portrait_photo_source`：由 `cover_portrait_log_fields` 從
  `CoverVisuals.photos` 攤平（YT 走 `YtCoverPlan.photos`）。出處**逐位對齊人名**，
  查不到的位子記「（查無）」——只記查到的幾張，多人時事後對不出是哪一位。
- `log_failure`：三條端點都補上，比照 `/api/images/generate`——生圖端的失敗
  （安全過濾、比例降級、逾時）以前只會 print，事後查不到是哪一則標題觸發的。
  記完原樣往外丟，不吞例外。

## 純 AI 版的標題分行（2026-09-07）

以前合成版走 `split_cover_title`、AI 版讓模型自己拆（模板寫 split ... yourself），
同一個標題在兩種模式下斷句不一樣，使用者切模式比對時看到的是兩張不同版面的圖。
現在兩邊共用 `compose.cover_title_lines`：使用者自己分的行優先，超寬再由
`wrap_cover_title_lines` 防呆拆（版位寬由 `cover_title_panel_width` 給，
滿版＝整寬、雙切＝左格安全內框扣邊界；字級推導抽成 `_cover_title_metrics`，
與 `_draw_cover_title` 同一支）。兩個 AI 模板改收 `{title_left_lines}`／
`{title_right_lines}`（每行一條 `Line N: …`），並明文「照給定的行印、不得重拆或重排」，
比照 YT ai-title 的 line1／line2。

## 純 AI 版的追加修改（2026-09-07）

比照 YT 直播封面 ai-title 那條路，完全同一套欄位與流程：

- 回應帶 `source_image_base64`／`source_mime_type`＝**後貼 Logo 前的模型原圖**。
  把貼過 Logo 的成品餵回生圖模型，模型會把 Logo 與節目標籤一起重畫，那是播出事故
  （與主流程「refine 送置框前原圖」同一個道理）。合成版兩個欄位留空——成品是程式用
  Pillow 拼的，沒有可以餵回模型的原圖，前端在合成版也不開放追加修改。
- `TenCoverRequest.background_image_base64`／`background_mime_type`：改完的模型圖送回
  `/api/editor/cover`，`mode=ai` 時跳過生圖與補描述（一次 API 都不打），只重跑
  `paste_cover_logo` ＋ `paste_cover_ai_note`，`model` 記 `ten-cover:overlay`。
- 前端：`handleTenCoverGenerate` 只在 `data.mode === 'ai'` 時設 refine 源；refine 送出
  時十點封面比照 YT（16:9、不置框、不挖洞、`text_free:false`），回來再走
  `recomposeTenCover`。欄位取現況，所以順便改標題也會生效。

## 設計標題開關（2026-09-08，只有 AI 整張版）

使用者要求 AI 整張版的標題要「設計感＋滿框」（範例：兩行極粗黑體撐滿格寬、關鍵字放大並改黃／紅、
緊密堆疊、白描邊＋陰影，像節目片頭字卡）。做成開關而不是直接改，因為 designed 讓模型大改版面，
錯字與版面走鐘的風險比較高。

- `TenCoverRequest.title_style`：`plain`（預設）／`designed`。只影響 `mode=ai`；合成版的字是
  Pillow 畫的，排版由 compose 的常數決定，這個欄位用不到。
- 兩個 AI 模板（雙切 `COVER_AI_PROMPT_TEMPLATE`、滿版 `COVER_AI_FULL_PROMPT_TEMPLATE`）的
  TYPOGRAPHY 段尾多一個 `{title_style_clause}`。`designed` 填
  `COVER_AI_TITLE_STYLE_DESIGNED_CLAUSE`，`plain` 填空字串——所以 plain 的 prompt 與 0907 版一字不差。
- 那一段只寫「怎麼排」，並自己重申一次「照給定的行逐字印、不得增減／重排／重拆」。
  **設計感只用字級表現**（使用者 2026-09-08 裁決）：關鍵數字／關鍵詞放大、緊密堆疊、陰影；
  明文禁止模型自己加黃紅強調色——顏色一律照逐行標記（依行序：白／黃／紅）走。
  這一段**不得自己指定描邊**（審查必修）：基礎規則是白／黃行深色描邊、只有紅行白描邊，
  原本那句「加一圈白色描邊」會把三行全變成白描邊，改成「維持上面指定的描邊」。
  字重也不寫成 `heavy black display type`——black 會被讀成填色，改用
  `heavy black-weight (weight, not colour)`，與 YT 兩個模板同一組措辭。
  逐行標記用 `(white)`／`(yellow)`／`(red)`，與模板圖例**逐字相同**，模型不必猜
  `red, white outline` 是不是圖例裡那個 `(red)`。
  逐行給定的機制（`{title_left_lines}`）不變，兩者同時在 prompt 裡。
- 前端 `#coverTitleStyleBtn`（紫色，比照蓋章／壓框的寫法：state 布林式字串、按鈕、payload 欄位）。
  只有十點版型＋「標題由 AI 生成」勾著才顯示，預設 OFF；生成本體與 `tenCoverFields()`
  （追加修改／只改文字）兩條 payload 都帶。
- 測試：`tests/test_cover_title_style.py`。既有直接 `.format()` 兩個模板的測試要補
  `title_style_clause=""`（`test_editor_formats`、`test_ten_cover_full`）。

## 2026-09-08 下午：格式合併與自動判定（WP1）

使用者裁決把編輯的版型下拉從八種砍到六種。兩件事一起做：播出鏡面的左切／右切合併成
一個版型，十點不一樣的滿版／雙切合併成一個版型。共通原則是「版型只回答**做哪一種圖**，
方向與版面這種每一則都會變的東西，交給版型裡的欄位」。

### 十點不一樣：版面由第二標題判定

- `editor_formats.EDITOR_FORMATS["ten_cover"]` 一個 key，label「十點不一樣」，
  `cover_layout` 從 `split` 改成 `auto`——那個值現在只是個標記，實際版面一律問
  `editor_formats.resolve_cover_layout()`（後端）或 `coverLayoutNow()`（前端）。
- `TenCoverRequest.layout` 改成可省略：沒帶時第二標題有值＝`split`、空＝`full`；
  有帶就以請求為準（舊呼叫端與 `ten_cover_full` 別名靠這條保持原行為）。
  版面在 `/api/editor/cover` 入口就 `model_copy` 正規化成 split／full 一次，
  下游那一票 `req.layout == "full"` 完全不用動。
- 「雙切左右標題都要填」的 400 只剩**明示** `layout="split"` 又沒有第二標題會踩到。
- 前端欄位改名「第一標題」「第二標題」。第二標題**永遠顯示**：它就是判定那一欄，
  被 `.cover-split-only` 藏起來就永遠填不進去，版面也就永遠切不到雙切。
  跟著判定顯隱的是第二附圖位與「只改文字」鈕（只有滿版合成版有）。
- 「滿版／雙切」那兩顆是**判定結果指示器**，不是輸入。點「雙切」只把游標移到第二標題——
  真正要做的就是去填那一欄；點「滿版」也不會幫使用者清掉第二標題，那是他自己的決定。

### 播出鏡面：方向由請求欄位決定

- `EDITOR_FORMATS["broadcast"]`，label「播出鏡面」。表裡的 `hole_side` 是**預設值**（左），
  `hole_side_from_request: True` 才是「這個版型允許請求覆寫方向」的開關。
- 請求欄位 `hole_side`（left／right）加在 `NewsImageGenerateRequest` **與** `GenerateRequest`
  兩處。後者是必要的：消化階段就要知道方向，內容得趕到影片那半邊的對面，只在生圖端
  決定的話，圖的重點會剛好被後製的影片蓋掉。
- 同一側算出來的消化規則與舊 key 逐字元相同（`test_format_consolidation` 有守）。

### 舊 key 留成別名

`broadcast_left`／`broadcast_right`／`ten_cover_full` 移到 `EDITOR_FORMAT_ALIASES`，
`editor_formats.get()` 兩層查得到，前端下拉不再列出。LINE／WorkCord、舊請求紀錄與既有
測試照樣打得進來。**別名刻意不吃請求的 `hole_side`**：舊呼叫端不會帶這個欄位，而欄位
預設是 left，別名若吃它，`broadcast_right` 會被默默翻成左切。

### 消化自動判定主題數

`/api/editor/cover-titles` 的 `ten_cover`：system prompt 先要模型判定內文是 1 個還是 2 個
主題（不同事件＝2；同一事件的兩個面向＝1），1 個只回 `title_left`、`title_right` 留空，
2 個依內文出現順序填左右。每個標題仍固定 3 段。回應加 `topics`（1／2）。
一致性以「`title_right` 實際有沒有值」為準：模型說 1 卻多給右標就清掉、說 2 卻只給一個
就退回 1——回一組自相矛盾的值，前端的版面指示器會跟欄位打架。
`ten_cover_full` 這個 target 仍然收，走原本的單標題 prompt，回應 `topics=1`。

### 指令欄

09-08 早上「封面／YT 隱藏指令欄」的裁決作廢。指令欄那一組（`#instructionRow`）搬出
`newsInputs`——封面版型會把整個 `newsInputs` 藏掉，留在裡面的話欄位再怎麼「顯示」都
看不到；`applyEditorFormatInputs` 會把它搬到當前那組欄位底下。

內容送 `TenCoverRequest.instruction`／`YtCoverRequest.instruction`（≤500 字，前端先截斷，
指令欄本身允許 2000 字，直接送會被擋成 422）。兩條線都餵**畫面推導那一步**
（`resolve_cover_visuals`／`derive_yt_cover_plan`）當提示，不直接拼進生圖 prompt：
底圖那條線明令一個字都不准畫，指令直餵過去會被模型畫在圖上。
所以走附圖直接上版、追加修改後重貼、只改文字這三條沒有推導的路徑時，指令不生效。

同時移除左右「畫面描述」欄（`visual_left`／`visual_right` 請求欄位保留相容，前端不再送），
`/api/editor/cover` 裡「有附圖那格用標題預填畫面描述」的回填也一併拿掉——那是為了回填
一個已經不存在的欄位。

### 下載檔名

`DOWNLOAD_FORMAT_NAMES` 的十點與播出鏡面兩筆改成巢狀：十點依判定後的版面（十點滿版／
十點雙切），播出鏡面依挖空側（播出鏡面左／播出鏡面右）。

### 測試

`tests/test_format_consolidation.py`（新增）：方向覆寫、別名不吃覆寫、版面自動判定與
明示優先、消化 1／2 主題、指令欄餵入位置，以及前端字串（指示器、挖空側按鈕、指令欄
搬家、短名巢狀）。
