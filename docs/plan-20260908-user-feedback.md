# 使用者回饋處理計畫（2026-09-08）

來源：使用者回饋文件（Google Doc「AICG 回饋」）6 項＋主管當日裁決。狀態欄：✅ 已上線／🔧 進行中／📋 待做／🏗 架構級（先計畫後動工）。

| # | 項目 | 裁決 | 狀態 |
|---|---|---|---|
| 1 | 下載檔名欄位（全站：記者／編輯所有版型） | 做 | ✅ A（commit `3e530d7`＋`cb87d7b`） |
| 2 | TVBS Logo「V 上方多一點」 | 修模板（非重生） | ✅ 已抹掉（commit 520053f 帶入；備份 `D:\Downloads\aicg_font_20260906\tvbs-logo-white_v_dot_backup.png`） |
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

## D. 播出鏡面字多不豐富 ✅ commit `76debd4`

待追蹤：第 7 條仍寫「每個 [內文小標] 是一句短事實」，字多檔位的第 6 條要求兩段用
「｜」分隔，兩條措辭有機會被模型讀成互相衝突，實測後再決定要不要一併改第 7 條。

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
