# 使用者回饋處理計畫（2026-09-08）

來源：使用者回饋文件（Google Doc「AICG 回饋」）6 項＋主管當日裁決。狀態欄：✅ 已上線／🔧 進行中／📋 待做／🏗 架構級（先計畫後動工）。

| # | 項目 | 裁決 | 狀態 |
|---|---|---|---|
| 1 | 下載檔名欄位（全站：記者／編輯所有版型） | 做 | ✅ A（commit `3e530d7`＋`cb87d7b`） |
| 2 | TVBS Logo「V 上方多一點」 | 修模板（非重生） | ✅ 已抹掉（commit 520053f 帶入；備份 `D:\Downloads\aicg_font_20260906\tvbs-logo-white_v_dot_backup.png`） |
| 2b | 承上：抹點後 V 左筆畫仍少一截（09-09 回報） | 補回上半截，與 T 直劃頂列切齊 | ✅ 兩檔都修（見 `docs/yt-live-cover-spec.md`「2026-09-09」段） |
| 3 | 整點新聞直播封面兩則合一 | 另開「整點雙切版」，架構比照十點雙切 | 🏗 B |
| 4a | 播出鏡面開框跑掉 | 09-07 已修（壓框開關＋標題規則） | ✅ |
| 4b | HTTP 524 無法產出 | 改非同步試試 | 🏗 C |
| 4c | 播出鏡面標題單薄、字多不豐富 | 照建議改 | ✅ D（commit `76debd4`） |
| 5 | YT 直播 PNG 壓標（透明 PNG 疊直播畫面） | 架構級，先寫 PLAN 列 TODO | 🏗 E |
| 6 | YT 熱搜／國內外直播封面標題再粗、行距略縮 | 做 | 🔧 併入 09-08 封面批次第 6 項 |

---

## A. 下載檔名欄位（全站）✅ commit `3e530d7`＋`cb87d7b`

實作與計畫的差異三處：副檔名跟著 mime 走（JPEG 仍叫 .jpg，命名成 .png 是錯的）；
第二頁另有 `#downloadNameAdvanced`（同一份 DOM 裡 ID 不能重複，值也不該互相汙染）；
`hybrid.js` 的下載在自己的 IIFE 裡、不共用結果區，這次沒動。

- 前端：在生成結果區加一個選填輸入框「檔名」（`#downloadName`），所有版型共用（記者／編輯／封面／YT）。
- 命名規則：留空 → `YYYYMMDD_<版型短名>_<標題前 8 字>`（例 `20260908_十點雙切_澳洲擬立新法`）；有填 → 使用者字串，去掉檔名非法字元，副檔名固定 `.png`。
- 影響點：`app.js` 各 `download.download = ...` 賦值處（一鍵、兩段式、十點、YT、refine 後），統一走 `downloadFileName()` 一個函式。
- 測試：JS 字串測試（每個 download 賦值都走同一函式）＋函式規則測試（Python 讀 app.js 抽 regex 驗證非法字元）。
- 估時：0.5 天。

## B. 整點新聞直播「雙切版」🏗

**目標**：整點封面常常兩則新聞合一。新增版型 `yt_hourly_split`（整點雙切），輸入新聞文字（可含兩則）→ AI 自動判定兩個標題（或手動填兩個）→ 左右各一格底圖＋各自標題，架構與十點雙切相同。

**設計**
1. `editor_formats.EDITOR_FORMATS["yt_hourly_split"]`：`inputs: "cover"`（沿用十點雙切的欄位：左右標題、左右畫面描述、左右附圖位）、`cover_layout: "split"`、`ytLayout: "hourly"`。
2. 標題消化：`/api/editor/cover-titles` 新 target `yt_hourly_split`，system prompt 由 `COVER_TITLE_DIGEST_SYSTEM_TEN` 衍生：**兩則不同新聞各一標題**（不是同一則的兩個切面），每標題 2 段（整點版型固定兩行，白／黃），無紅字。內文若只有一則，回 `title_right` 空並在回應標記 `single_story: true`，前端提示改用單則版型。
3. 底圖：沿用 `_cover_composite`（每格 1:1 生圖或附圖）；固定元素改用整點版的標頭（`YT_COVER_*_HOURLY` 那套：LIVE 標籤、日期、右上 Logo），底部標題改「兩格各自兩行」＝十點雙切的 `_draw_cover_title` 換整點配色與字級常數。
4. AI 整張版：沿用 `COVER_AI_PROMPT_TEMPLATE` 的雙切結構，換整點標頭描述。
5. 十點雙切對齊：**十點雙切的「AI 消化標題」按鈕與流程要先確認在 UI 上可用**（後端 target `ten_cover` 已存在）；兩個版型共用 `handleCoverTitleDigest`。
6. 只改文字：雙切維持不互通（使用者已知）。

**待裁決**：整點雙切要不要「精華／ON AIR」那類標籤（整點版現有 LIVE 標籤即可？）；兩則新聞左右順序是否依內文順序。

**估時**：2 天（含測試與規格文件）。

## C. 524：生圖改非同步 🏗

**現象**：公司部署走 Clerk 網域、前面有 Cloudflare，100 秒切斷回 524；播出鏡面／封面生圖常 100–200 秒。個人 Cloud Run 逾時 300 秒、09-08 早上無任何 5xx，故只在公司端發生。

**設計（送出→輪詢）**
1. 新端點 `POST /api/jobs/images/generate`（與 `/api/jobs/editor/cover`、`/api/jobs/editor/yt-cover`）：驗完請求後立刻回 `{job_id}`，工作丟到背景執行（`ThreadPoolExecutor`，單一 worker 池 + 佇列上限）。
2. `GET /api/jobs/{job_id}`：`queued／running／done／failed` ＋ 完成時的原回應 JSON；結果保存在記憶體 dict（TTL 30 分鐘）；Cloud Run 多執行個體時要改用 GCS 存結果（`gcs_archive` 已有 bucket），第一版先限 `max-instances=1`。
3. 前端：所有生圖呼叫改走 job（同一個 `postJob(url, body)` helper：送出→每 3 秒輪詢→done 取結果），舊同步端點保留給 LINE／WorkCord。
4. 風險：Cloud Run 在沒有請求時會凍結 CPU——輪詢請求本身會維持喚醒，但要把 `--no-cpu-throttling` 打開或設 `min-instances=1`，否則背景工作會被暫停。
5. 測試：job 生命週期、TTL、失敗回傳、前端 helper 字串測試。

**估時**：1.5 天。是否要做取決於公司端能否改 Cloudflare 逾時（若能改到 300 秒，此項可免）。

## D. 播出鏡面字多不豐富 ✅ commit `76debd4`＋第 7 條同步（本 commit）

第 7 條原本仍寫「每個 [內文小標] 是一句短事實」，跟字多檔位第 6 條要求的兩段
「｜」結構互相衝突。現在第 7 條吃同一套換檔機制（`{point_rules}` 佔位）：standard
改成「短標｜補充細節」兩段、角括號強調放短標那段；simplified／verbatim 維持原句
逐字不變。

- 現況 `_BROADCAST_RULES_TEMPLATE` 第 6 條固定「三張卡、每卡一句」，字多檔位無處發揮。
- 改法：`density == "standard"`（字多）時，第 6 條改成「三張卡，每卡兩行：第一行短標、第二行補充數據／細節」，`variable` 允許每個 `[內文小標]` 帶一行子句（用「｜」分隔），compose 不受影響（版面由模型畫）。標題單薄：第 3 條補「標題要含關鍵數字或結果，不得只是主題名」。
- 測試：density=standard 的規則含兩行卡片措辭；simplified 不變。
- 估時：0.5 天。

## E. YT 直播 PNG 壓標 🏗

**目標**：同一個標題，除了封面圖，再輸出一張**透明底 PNG**（1920×1080）疊在直播畫面上：只有標題條、LOGO、版型標籤與畫面來源字，沒有底圖、不生圖。

**規格（待與使用者確認）**
1. 版型三選一：一般國內直播／原音呈現／AI 即時翻譯（後兩者的左上標籤沿用 YT 封面既有元素）。
2. 「畫面來源」文字欄（例：畫面來源：路透社／CNN），位置跟著 LOGO 走（LOGO 在右上→來源字在 LOGO 下方；LOGO 在下方→來源字在 LOGO 上方）。
3. LOGO 位置四選一：右上／右下／左上／左下。
4. 標題條位置二選一：左側／右側（避免遮到外電原素材的 logo）；標題條寬度約畫面 55%，兩行（白／黃），底色框沿用 `bottom_band` 開關與透明度。
5. 輸出：`image/png` 透明底；另附「疊在示意畫面上的預覽」（灰底或使用者上傳的截圖）讓使用者確認位置。
6. 端點：`POST /api/editor/yt-overlay`，請求＝標題（或沿用 yt-cover 的 line1/line2）＋上述四個選項；compose 新增 `compose_yt_overlay()`，重用 `_draw_yt_title` 與標籤／LOGO 貼圖，但畫布 RGBA 全透明。
7. 前端：YT 三個版型的結果區加「產生直播 PNG 壓標」按鈕，展開四個選項；下載檔名依 A 的規則加 `_壓標`。

**TODO**
- [ ] 取得使用者兩張示意圖的元素清單與尺寸（標題條高度、LOGO 大小、來源字字級）。
- [ ] 確認「原音呈現」版的來源字要不要跟 LOGO 綁位置（使用者建議跟著 LOGO）。
- [ ] 確認是否要支援 4K（3840×2160）輸出。
- [ ] compose_yt_overlay＋端點＋前端＋測試。

**估時**：2 天（規格確認後）。

---

## 建議排程
1. 09-08 封面批次（進行中）→ 部署。
2. A（檔名）＋ D（播出鏡面字多）一起，半天。
3. B（整點雙切）。
4. E（PNG 壓標）規格確認後開工。
5. C（非同步）視公司端 Cloudflare 能否調整再決定。

---

## F. 2026-09-08 下午使用者裁決：編輯格式精簡（🏗 進行中）

裁決原文重點：
1. 【播出鏡面】左切／右切改為同一個格式，格式內用按鈕選左／右。
2. 【十點不一樣】滿版／雙切合併為一個格式；「左半標題」→「第一標題」、「右半標題」→「第二標題」；左右「畫面描述」欄刪除（跟其他版型對齊）；只填第一標題＝滿版，兩個都填＝雙切（自動判定）。
3. 新聞內文自動消化：AI 判定內文是 1 個還是 2 個主題；1 個只填第一標題（滿版），2 個填兩個（雙切），左右順序依內文順序。
4. 【YT整點直播】對齊十點的滿版／雙切新模式（填第二標題就雙切），不需要 ON AIR／精華。→ 取代原本 B「另開整點雙切版」。
5. 紅／藍底色框（預設 OFF）位置往下調，不超過第二行標題。→ 先出三個位置樣張給使用者挑。
6. YT 直播 PNG 壓標（E）：先做範例樣張（元素底圖、標題字、來源句，全部腳本壓）定版，再做端點與 UI。

### WP1 格式精簡（editor_formats／main／app.js／index.html）
- 新 key：`broadcast`（欄位 `hole_side` left/right，前端按鈕，預設 left）、`ten_cover`（layout 由 title_right 是否有值自動判定；請求若明示 layout 仍以請求為準）。舊 key `broadcast_left`／`broadcast_right`／`ten_cover_full` 後端保留為別名（LINE／WorkCord／舊紀錄／測試相容），前端下拉不再列出。
- 十點欄位：第一標題／第二標題；`visual_left`／`visual_right` 請求欄位保留相容但 UI 移除；封面／YT 版型重新顯示「給 AI 的指令」欄（09-08 早上「隱藏」裁決作廢），內容餵給畫面推導當提示。
- 消化：`/api/editor/cover-titles` target `ten_cover` 回 `title_left`／`title_right`（單主題時空）＋`topics`（1／2）；順序依內文。
- 下載檔名版型短名改依判定後的 layout。
- 前端十點的「滿版／雙切」按鈕是判定結果指示器，不是輸入（點「雙切」只把游標移到第二標題）。

### WP2 YT整點「雙則」✅（2026-09-08 晚定案，取代原「雙切」）
- 使用者更正：整點的雙標題不是左右各一格，而是**同一張 16:9 底圖、上白下黃兩行**（第一標題一整行、第二標題一整行），底圖仍由左右兩張拼成但**接縫用正中間的柔和漸層**（`blend_backgrounds_lr`，兩側各 7% smoothstep＋22% 深色暈，`seam_ratio` 0.35–0.65 只留在 compose 層）。
- `YtCoverRequest.title_second`（選填）；有值→雙則，空→現行單則。每行上限 18 個全形字寬（2026-09-08 晚由 14 放寬）（半形算 0.5）。消化 target `yt_hourly`：topics 1／2，2 個各出一整行。前端「第二標題」欄＋單則／雙則指示器；下載短名「YT整點雙則」。
- 雙則沒有 AI 整張版的字數擋；畫面描述兩格各自推導後以「｜」串給模板。

### WP3 底色框位置樣張＋PNG 壓標原型（compose.py＋scratch，不接端點／UI）
- ✅ 底色框（2026-09-08 晚定版）：使用者從三張位置樣張挑「3 第二行」，並要求**框上緣漸層羽化**。`YT_BAND_TOP_RATIO` 0.60→**0.778**（第一行基線）、`YT_BAND_FADE_RATIO` 0.06→**0.0365**（到 0.8145 全濃度，壓在第二行墨水上緣之上），羽化改 smoothstep；三變體字典 `YT_BAND_VARIANTS` 移除。仍是開關、預設 OFF、60% 半透明；整點直播不適用。
- `compose_yt_overlay()` 原型：1920×1080 透明 RGBA、**直排**標題條（照使用者 Google 文件第 5 項截圖）、兩欄直排標題、來源句跟著 LIVE 章或 Logo、LIVE 章；每個組合各出透明 PNG＋疊在參考畫面的預覽。
- 2026-09-08 晚使用者對直標的第一輪裁決：**兩欄字級一樣大、底色一致、同一個色框不拆開**（`VSTRIP_SEAM_RATIO`＝0、兩欄同寬同格距、`compose_yt_overlay(fill=…)` 一個顏色畫整塊；`yt_vertical_layout` 多回 `box`／`pitch`）。副標深紅樣張作廢。仍未接端點／UI，LIVE 章樣式待裁。

### 之後
- 手冊（八種→六種、欄位改名、畫面描述列刪除、十點表重排）、`docs/ten-cover-spec.md`、`docs/yt-live-cover-spec.md` 在 WP1＋WP2 落地後一次更新。
- 不部署，等使用者下令。

### H. 標題字級／字重／字數（2026-09-08 晚第三輪回饋）✅
- 十點雙切合成版字級不夠大：`COVER_TITLE_SIZE_RATIO` 0.11→0.135、`COVER_TITLE_WIDTH_RATIO` 0.90→0.94。字級仍由最長一行決定，所以消化標題每段字數是關鍵。
- 十點消化「字太少撐不出三段」：prompt 改每段 4–7 字、全篇 12–18 字、明講超過 7 字會把字級拖垮；後端 `editor_formats.ten_digest_violations()` 驗一次，不合格帶違規原因重問一次（`TEN_DIGEST_MAX_ATTEMPTS`＝2），再不合格照收。
- YT 國內外／熱搜「太粗、複雜字分不出來」、整點「太細」：描邊 `YT_TITLE_STROKE_RATIO` 0.05→0.04、假粗體 `YT_TITLE_BOLD_RATIO` 0.015→0.008，整點改走同一支 `_draw_yt_title_line`（原本無假粗體無陰影），三種封面字重對齊。
- 整點雙則每行上限 14→18（`YT_HOURLY_LINE_MAX_CHARS`、前端常數、消化 prompt、手冊）。其他版型沒有硬性字數上限（只有塞不進版面才報錯）。

### I. 第四輪（2026-09-08 晚）✅
- 整點兩行行距略縮：`YT_HOURLY_LINE1_BASELINE_RATIO` 0.80→0.815。
- 十點雙切字再粗一點點：`COVER_TITLE_BOLD_RATIO`＝1.2% 假粗體（做法同 YT，描邊先加回吃掉的寬）。
- 藍／紅底色框預設改 **ON**（`YtCoverRequest.bottom_band`、`state.ytBottomBand`、compose 兩函式預設值；手冊已改）。

### G. 標題各行同字級（2026-09-08 晚）
- ✅ YT 三種封面（國內外／整點／熱搜）：兩行標題取全域最小字級，短行跟著長行縮（`_yt_shared_title_font`）。
- 📋 TODO（使用者保留）：十點滿版目前逐行各自撐滿、每行字級可不同；要不要改成同字級牽涉「設計標題」AI 版的排法，待使用者決定後再動。十點雙切已是同字級。
