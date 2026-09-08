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

## 標題兩種模式（2026-09-06 使用者試做後裁決：兩種並存、**預設 AI 生成**）

| 模式 | `title_mode` | 做法 | 追加修改 | 只改文字 |
|---|---|---|---|---|
| 標題由 AI 生成（預設、勾選框打開） | `ai` | 整張連兩行標題、底帶交給生圖模型（`YT_COVER_FULL_PROMPT_NEWS`／`_HOURLY`，左上右上留空；底帶畫不畫 2026-09-08 起由 `bottom_band` 決定，預設不畫），程式只後貼 LIVE 章／日期／原音呈現／AI即時翻譯／藍標籤／AI示意圖。附圖全當參考（asis 照主流程原圖放置）。一律標 AI示意圖。 | 一般 refine 規則（字要保留），改完帶 `background_image_base64` 回來只補貼固定元素 | 沒有這回事，改字＝整張重生 |
| 程式壓字（勾選框關閉） | `composite` | 下面「底圖三條路」；零錯字、有附圖時零 API | `text_free` refine 改底圖再重疊 | 8 秒重疊 |

試做紀錄：挪威國王／C 肝／美伊油價（含追加修改改夜景）／整點版車禍，5 張全對字，
每張 34 到 51 秒；樣張 `D:\Downloads\aicg_yt_cover_20260905\G_fullgen_*.png`、`H_*.png`。
AI 模式的字級行距每張略有差異，錯字率要累積更多樣本才知道。

## 底圖三條路（壓字模式）

1. 有 asis 附圖 → `compose.crop_background_16x9` 裁滿 16:9。不標 AI示意圖。
2. 有其他用途附圖 → `generate_image_raw` 帶附圖生無文字底圖。標 AI示意圖。
3. 沒附圖 → 文字模型（`YT_COVER_DERIVE_SYSTEM`）依標題補畫面描述＋列出具名真人 →
   `apply_portrait_to_image_request` 走主流程查參考照（最多三張臉，與網站規則一致）
   → 生無文字底圖。標 AI示意圖。

生圖 prompt 最後固定壓 `YT_COVER_TEXT_FREE_OVERRIDE`：肖像與附圖規則都寫著「示意圖
標籤要保持可見」，不壓掉模型會自己畫一個「示意圖」字樣。

## 固定元素：國內外新聞直播（`compose.compose_yt_cover`，零錯字）

量自頻道 maxresdefault 1280×720，常數 `compose.py` `YT_*`：

- 底部深藍科技底帶（0.60 起漸入，半透明，撒固定序列的淡藍方塊模擬電路紋）——**2026-09-08 起是開關且預設關**，見文末「底部壓色框改成開關」
- 兩行標題**置中**壓在底帶上：第一行白、第二行黃，黑描邊，字級依寬度自動縮。
  **2026-09-08 使用者回饋「字體再粗一點、行距略縮」**：加粗用同色描邊做假粗體
  （`YT_TITLE_BOLD_RATIO`＝**1.5%**，台北黑體只有 Bold 一個字重，沒有更粗的檔可換；
  同日第二輪回報 3.5% 太重——第二行黃字筆畫互相黏住、字腔被吃掉，「關閉社群媒體」糊成一團），
  深色描邊先補上假粗體吃掉的寬度（`_draw_yt_title_line`），不然加粗完外框只剩一兩個像素、
  底色框又預設關，字就立不住；行距 0.194→0.180（第二行貼底不動、第一行往下靠）。
  同時補一層**陰影**（`YT_TITLE_SHADOW_RATIO`＝2%，比照十點封面的標題）：底色框預設關之後
  字直接壓在照片上，光靠描邊在亮背景仍然糊；YT 封面以前沒有陰影，這是新加的。
  今日熱搜共用同一組常數與同一支畫法，整點直播版面不同、這次不動。
  AI 版兩個模板同步改成「heavy black weight ... TIGHT LEADING」，並明文要求字腔保持開著。
  假粗體與陰影**刻意不設像素下限**：設了 `max(2, …)` 會讓 1.5% 與完全不加粗在常見字級（157px）下
  畫出一模一樣的字，測不出差別；0 就整層不畫。
  字腔用連通區域數（`tests/test_yt_title_weight.py` 的 `_enclosed_counters`，不必猜某個字的洞在哪）：
  12 字的長行在最小字級下，1.5% 留 10 個封閉字腔（最大 419px），3.5% 只剩 6 個（最大 229px）。
  測試：`tests/test_yt_title_weight.py`。
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
- 測試：`tests/test_yt_cover.py` 37 個；全套 706 綠（2026-09-06 AI 標題模式後）。
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

## 2026-09-06 補充：頂端藍線與多圖分切

- **頂端藍線**：新聞直播版畫面最頂端一道橫貫全寬的窄藍色漸層線（上深下淺，高約 2.2% 畫面高），
  與右上藍色 TVBS 標籤同色系，標籤壓在線上。頻道實際版每張都有，對照型錄補上。
- **日期白框紅邊**：新聞版日期白框外圈一道紅邊（與 LIVE 章同紅，寬約 4/1080）。
- **多圖分切（防呆）**：用途為「原圖放置」的附圖 1 張＝單圖、2 張＝左右雙切、3 張＝三切，
  超過 3 張只取前 3 張並記 log。每格各自 COVER 裁切置中不變形；分隔線斜切（頂端偏右、底端偏左，
  斜量 5% 畫面寬）＋白色細線（6/1080）。分切一律由程式拼、標題一律程式壓字：
  AI 標題模式遇到 ≥2 張原圖放置會自動改 composite，回應的 title_mode 也是 composite。
  兩版型（news／hourly）共用。

## 2026-09-06 補充：今日熱搜版型（型錄 H 類）

`compose.compose_yt_hot_cover`，layout `hot`，版型鍵 `yt_hot_cover`（YT今日熱搜）。議題型版面，
**沒有日期、沒有 LIVE、沒有原音呈現／AI即時翻譯**（後端直接忽略、前端隱藏）。
- 頂端一條紅色細條（上深下淺，3% 高）。
- 左上「今日｜熱搜🔍」（2026-09-07 起貼模板 `static/brand/hot-search-tag.png`，gpt-image-2 依型錄原版重繪、透明底，高 13% 畫面等比縮放（依 YouTube 實際縮圖量測，型錄截圖偏大）；不再用程式畫方框與放大鏡）標籤：今日＝紅底白字、熱搜＝白底紅字、放大鏡由程式畫（`_draw_hot_magnifier`）。
- 右上紅色 TVBS 斜標（`_draw_logo_tab` 加顏色參數，藍→紅）。
- 底部深紅底帶（`_draw_title_band` 加顏色參數）＋兩行置中標題白／黃，幾何同新聞版。底帶**2026-09-08 起是開關且預設關**（與新聞版同一個 `bottom_band`），見文末。
- AI 標題模式用 `YT_COVER_FULL_PROMPT_HOT`；底圖／附圖／分切規則與新聞版完全相同。
對照圖：`D:\Downloads\aicg_font_20260906\catalog_hot\hot_01~08.png`，樣張 `yt_hot.png`。

## 2026-09-07 補充：成圖比例驗證

`_yt_cover_background`（無文字底圖）與 `_yt_cover_full_image`（AI 標題整張）都直呼
`generate_image_raw`，繞過 `finalize_image_result`，以前生成端間歇性降級（要 16:9 回 3:2）
不會被發現，圖照樣合成上鏡。兩條線拿到 result 後都補 `verify_output_aspect_ratio`，
降級當場變成 502 而不是一張裁壞的封面。既有底圖（`background_image_base64`）不驗——
那張不是這次生的。

## 2026-09-08：news 與 hot 標題字級的對齊調查（結論：本來就一致，不改碼）

使用者回報「國內外新聞直播的標題字級比今日熱搜大」。查證結果：

- **合成版本來就同一套。** `compose_yt_cover` 與 `compose_yt_hot_cover` 讀同一組
  `YT_TITLE_SIZE_RATIO`（0.145）／`YT_TITLE_MIN_SIZE_RATIO`／`YT_LINE1_BASELINE_RATIO`／
  `YT_LINE2_BASELINE_RATIO`，`max_w` 也都是 `width - margin * 2`。同一組標題丟進去，
  兩張圖的標題像素外框逐點相同（實測 `(258, 690, 1658, 838)`）。hot 沒有自己的
  `YT_HOT_TITLE_*` 覆寫。
- **AI 版兩個模板描述字級的措辭一字不差**：`YT_COVER_FULL_PROMPT_NEWS` 與 `_HOT` 都寫
  「huge and heavy Chinese display type filling almost the full width」、
  「Line 1: solid white. Line 2: bright golden yellow.」。
- 所以沒有可以對齊的差值，**不動任何常數與措辭**——硬造一個差異只會把現在對齊的兩條線弄歪。
  唯一會出現差別的是 AI 標題模式：字級由模型決定，同一段措辭每張略有差異（見上面「試做紀錄」）。
  真要讓 AI 模式的字級穩定，得改成「兩行都必須佔滿可用寬度的 N%」這種可量化的指令，
  兩個版型一起改，屬另一件事。
- 釘住現況的測試：`tests/test_yt_title_parity.py`（合成版逐像素相同、常數只有一處定義、
  兩個模板措辭相同）。以後任何一邊調字級都會被擋下來。

## 2026-09-08：底部壓色框改成開關（預設 OFF，開的時候半透明）

使用者裁決：底帶不要一直壓在那裡，改成自己開；開了也要透得出照片。

- `YtCoverRequest.bottom_band: bool = False`。合成版由 `compose_yt_cover`／`compose_yt_hot_cover`
  的同名參數決定要不要呼叫 `_draw_title_band`（關＝**完全不畫**，標題靠自己的粗黑描邊立在照片上）。
- `YT_BAND_ALPHA` 205 → **153**（60%）。原本 80% 幾乎把照片下半整片吃掉；「開」不是回到舊行為。
- AI 標題模式只能靠 prompt，所以 `YT_COVER_FULL_PROMPT_NEWS`／`_HOT` 的 LAYOUT 第一條與 IMAGERY
  結尾都換成佔位 `{band_clause}`／`{band_imagery_tail}`，由 `editor_formats.yt_cover_band_fields()` 給：
  ON＝「semi-transparent (about 60% opaque) …band…」＋「filling the frame behind the band」；
  OFF＝「There is NO solid colour band…readability comes from its thick outline and drop shadow alone」
  ＋「filling the frame」。**IMAGERY 那句一定要一起改**：留著「behind the band」模型還是會畫一條出來。
- **整點直播（hourly）不適用**：`compose_yt_hourly_cover` 本來就不畫底帶，AI 模板也明文
  「No band behind them」。後端 `bottom_band = bool(req.bottom_band) and not hourly`、
  模板 format 不帶那兩個欄位，前端在該版型不顯示按鈕。
- 前端：`state.ytBottomBand`（預設 false）＋ `#ytBottomBandBtn`（琥珀色，比照蓋章開關）。
  欄位加在 `ytCoverFields()`，所以生成與「只改文字」／追加修改回貼走的是同一個值。
- 測試：`tests/test_yt_bottom_band.py`（OFF 時底帶區＝底圖原色、ON 時逐通道落在底圖色與帶色之間、
  兩種 prompt 措辭、hourly 不受影響、前端 state 與按鈕）。`test_yt_cover` 原本那題看底帶顏色的
  要自己 `bottom_band=True` 才看得到。

## 2026-09-08：Logo 模板修正

`static/brand/tvbs-logo-white.png` 抹掉 V 上方誤加的小點（使用者回饋 #2），備份在
`D:\Downloadsicg_font_20260906\`。這個檔十點封面與 YT 封面共用（`compose.TVBS_LOGO_WHITE`）。

## 2026-09-08：整點直播「雙切」（WP2）

使用者裁決：整點對齊十點不一樣的滿版／雙切，**不做** ON AIR／精華那類標籤。
判定只有一條規則——整點版型＋第二標題有值＝雙切（`editor_formats.yt_cover_is_split`）。
國內外新聞直播與今日熱搜沒有雙切版面，帶了第二標題也忽略。

### 版面（`compose.compose_yt_hourly_split_cover`）

- 兩張底圖各佔左右半格，各自 COVER 裁切、不變形；中線一條白色細線（沿用 `YT_SPLIT_LINE_*`）。
  **直切不是斜切**：斜線在標題那一帶會壓到某一格的字，而兩則不同新聞的界線要一眼看得出來。
- 四行標題（每格白／黃兩行）**同一字級**：各自算出塞得下的最大字級後取四者最小值。
  使用者對「兩邊字不一樣大」零容忍（同十點雙切的裁決）。縮到最小字級仍塞不下就丟
  `ComposeError`，不會默默伸進另一格。
- 最小字級 `YT_HOURLY_SPLIT_MIN_SIZE_RATIO = 0.075`（滿版仍 0.085）。半格可用寬 881px，
  實測每行最多 **10 個中文字**，11 字報錯。
- 行距 `YT_HOURLY_SPLIT_LINE_GAP = 1.24` **倍字級**（第二行貼底不動、第一行往下靠）。
  滿版是兩個固定基線（相差 0.165 畫面高），雙切字級小很多，照抄絕對比例會讓兩行散開。
  1.24 取自國內外新聞直播調過的行距換算：0.180 畫面高 ÷ 0.145 起始字級。
- LIVE 章（含整點時間帶）與左上 Logo 位置沿用整點滿版。日期紅條**只畫一次、擺左半格**，
  位置跟著第一行標題的字頂走（滿版那個 0.52 是照滿版字級量的，雙切沿用會浮在半空中）。
- 「AI示意圖」兩格各判各的；`_draw_ai_note` 加了選填 `x1`（小標右緣），左格那個才收得進左半格。
- 兩處與滿版不同，是刻意的：標題用 `_draw_yt_title_line`（陰影＋描邊＋同色假粗體），
  滿版是單層描邊；兩格都**不做**底部漸暗（滿版本來就不做）。

### 端點（`/api/editor/yt-cover`）

- `YtCoverRequest.title_second`（≤60）。有值＋整點＝雙切，空＝現行滿版流程一字不變。
- 做法是「把一個雙切請求拆成兩個單格請求」（`yt_split_panel_requests`），每格再走既有那一套。
  **附圖一定要先拆**：`resolve_yt_cover_plan` 的 `has_asis` 看的是整份清單，不拆的話左格附了
  一張圖會讓右格也以為自己有底圖、跳過畫面推導。原圖放置 1 張＝左格、2 張＝左右各一；
  非 asis 的附圖（實景／肖像／地圖）兩格共用，那是生圖參考不是版位。
- 沒附圖的格生 **1:1** 方圖（走十點那條 `_cover_panel_image`）：這一格只佔半個畫面，
  生 16:9 再塞進半格會被裁掉左右兩側。附圖那格**不先裁 16:9**，裁過再交給 compose 裁一次
  等於同一張圖被裁兩次。要生的格平行生。
- **AI 整張版不支援雙切**：那條線是「一張圖畫完含標題」，雙切的版面是程式拼的。收到雙切＋
  `title_mode=ai` 一律強制 composite，回應 `notice` 說明，前端會 toast 出來。
- **雙切沒有追加修改**：`source_image_base64` 留空。成品是兩張圖拼的，餵回生圖模型會把中線
  與另一格一起重畫。兩格的壓字前底圖改走 `background_image_base64` 與 `background_second_base64`
  回來，「只改文字」把兩格一起帶回去重壓。

### 消化（`/api/editor/cover-titles` target `yt_hourly`）

與十點同款「先判 topics 1／2」：1 個主題只回 `title`、`title_second` 留空（回填後即為滿版）；
2 個依內文順序填。一致性以「第二標題實際有沒有值」為準，模型說 1 卻多給就清掉、說 2 卻只給
一個就退回 1。每個標題仍是兩段（半形空格）；兩則並排時每段上限 9 字，單則維持 5–12 字。

### 前端

整點版型多一欄「第二標題（選填，填了就雙切）」與滿版／雙切指示器（`ytLayoutNow()`／
`updateYtLayoutIndicator()`，做法與十點逐字對齊——指示器是判定結果不是輸入，點「雙切」只把
游標移到第二標題）。消化按鈕的 target 由 `ytCoverDigestTarget()` 決定。下載短名雙切時
「YT整點雙切」。「只改文字」雙切也能用，兩格底圖收在 `state.ytSplitBackgrounds`。

測試：`tests/test_yt_hourly_split.py`（compose 18 題）、`tests/test_yt_hourly_split_api.py`
（端點／消化／前端接線 29 題）。全套 1041 綠。
