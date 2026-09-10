# 2026-09-09 第四批使用者回饋

版本號 **260909-01**（這一批建立的機制，見第 3 項）。

使用者八點，其中第 8 項的後半（「再稍微縮小一點點」）在同一輪中被撤回。

---

## 1. 角落選項排序統一

直標的「Logo 角落」與「來源句位置」兩列按鈕，順序一律 **左上／左下／右上／右下**。
以前 Logo 那列是 右上／右下／左上／左下，來源那列是 左上／右上／左下／右下，
兩列互不一致，選的時候要重新找。純 markup 改動，行為不變。

## 2. 直標新增 AI 自動消化

貼一段文字 → 兩段標題 ＋ 判定畫面來源，回填三個欄位；**不接生圖**，比照封面那條
（2026-09-06 使用者裁決：編輯看過再自己按生成）。

- 端點沿用 `/api/editor/cover-titles`，新增 `target="yt_vstrip"`；
  回應多一個 `source_text` 欄位。
- Prompt `editor_formats.VSTRIP_TITLE_DIGEST_SYSTEM`：
  - 字數上限講的是**格數**不是字元數（連續英數字併一格，`compose._vertical_cells`），
    上限直接由 `compose.VSTRIP_MAIN_MAX_CELLS`／`VSTRIP_SUB_MAX_CELLS` 帶進去，不手抄。
  - 明說輸入常常是外電通稿（英文 slug ＋ 場次 ＋ Restrictions），要翻成繁中臺灣用語。
  - 來源優先取「Must credit X」這類版權要求；沒有就取通稿指名的通訊社；
    都沒有就回空字串讓編輯自己填（不准猜）。
  - 只回來源名——「畫面來源：」由 `compose.vstrip_source_text` 自動補。
- 前端：直標面板最上面多一個貼文區與「AI 消化標題」鈕。來源判不出來時**不覆蓋**
  編輯已經填好的那一欄。

使用者給的範例輸入（布希總統中心九一一廿五週年）已存進測試的說明裡。

## 3. 版本號機制

`V8.2` 從來沒動過。改成：

- `VERSION` 檔是唯一真相源，格式 `YYMMDD-XX`（YY＝年份後兩碼，XX 從 `01` 起、
  換一天重新從 `01` 開始）。使用者說「從 00 開始」，但給的範例是 `260909-01`，以範例為準。
- `scripts/bump_version.py` 遞增（或 `--set`），順便改 `index.html` 大標右邊那顆標籤。
- `tests/test_app_version.py` 擋兩件事：格式不對、`VERSION` 與 `index.html` 對不上。
- 使用者要的是「每次**改動**都更新」，不是每次佈署——所以是腳本＋測試，不是 CI 產物。

## 4. 蓋章 OFF 的底帶（第三批沒做成）

使用者實測蓋章 OFF ＋字多，半邊底部仍然完全沒有東西，並附了成果圖；同時開放
「底部元素可跨版（就像標題可跨版）」。

**根因**（兩個，都要修）：

1. 第三批的做法是叫模型「把最後一張 `[內文小標]` 下移到底帶」。那張卡在 `variable`
   裡跟其他卡長得一模一樣，模型沒有任何依據把它挑出來，於是四張一起疊在半邊。
   蓋章 ON 之所以做得到，是因為 `<蓋章>` 是 `variable` 裡一個**看得見的標記**。
2. 第 1 條寫「A large rectangular area filling most of the {side} half」，模型照著
   畫成一整片高牆，底下那條帶根本不存在——成果圖就是這樣。實際的挖空框是
   `compose.apply_broadcast_hole` 畫的 16:9 寬扁視窗（寬佔安全區四成五、垂直置中），
   上下本來各留一條帶。

**修法**：

- 給底帶自己的標記 `<底帶>`，比照 `<蓋章>`。第 5／6 條改寫成「`variable` 的最後一行
  是 `<底帶>`，它是底下那條跨全寬的橫帶，樣式是一般資訊卡不是彩色蓋章」，並明說
  它跨兩個半邊（使用者開放的）。`news_prompt.EDITOR_TEXT_RULES` 補一條標記說明
  （記者版不動——記者沒有播出鏡面，而且那份 prompt 是凍結的）。
- 第 1 條改寫成「寬而扁的橫幅視窗、垂直置中、上面留一條、**下面留更深一條**、
  不到畫面底部」。仍然一個數字都沒有（版型鐵律）。
- `main.ensure_bottom_band_line`：確定性兜底。prompt 只是勸告，第三批就是敗在這裡。
  消化結果沒有 `<底帶>` 行就把最後一張卡升級成底帶，位置與內容都不動，只換標記。

## 5. 消化太慢、偶爾逾時沒生成

這個 repo 自己量過兩次（見 `main.DIGEST_MAX_TOKENS` 上方的註解），結論一致：

- 真正寫出來的正文非常穩定，**856–1361 token**；
- 會爆的是**思考**，603–4873，而且思考量跟著規則**條數**漲、與正文長度無關；
- 播出鏡面是規則最多的一條線（消化 prompt 24.3K 字元，分類失敗退回自動判斷時 32.1K），
  所以它最慢；
- 一次消化最壞是五次 attempt，Cloud Run 請求上限 300 秒，實測撞過「重試後 269 秒才回應」。

所以不再走「刪規則」那條路（刪掉的每一條都是使用者驗收過的行為，而且這一批第 4 項
還必須加規則）。改成兩個確定性的措施：

| 措施 | 內容 |
| --- | --- |
| 思考封頂 | OpenRouter 統一參數 `reasoning.max_tokens`，預設 2000（`DIGEST_REASONING_MAX_TOKENS`，設 0 停用）。只在 `DIGEST_BACKEND=openrouter` 時送——原生 OpenAI 收到這個欄位會 400。模型不吃就自動重送一次不帶該欄位的請求。預算留不下正文空間（`max_tokens - 2500 < 1024`）時不送。 |
| 迴圈期限 | `DIGEST_DEADLINE_SECONDS`（預設 230 秒）。超過就停止重試、回 503 講清楚，而不是讓 Cloud Run 在第 300 秒硬砍——使用者看到的「沒有生成」就是那個。 |

正式站的消化模型是 `anthropic/claude-sonnet-5`，走 `reasoning.max_tokens`
（OpenAI 系走 `effort`，這裡不送）。

## 6. 標題裡的「9/12」被當成分段

`editor_formats._COVER_TITLE_SPLIT_RE` 把 `/` 當分隔符，於是
「古羅馬圖拉真浴場 9/12開放民眾參觀」在十點封面被切成「9」與「12開放民眾參觀」
（使用者附圖）。

兩處都要修：

- 分隔符 regex 改成 `[ 　\n\r｜|]+|(?<!\d)/+|/+(?!\d)`——斜線兩邊都是數字時
  是日期／比數，不分段；「羅馬/浴場」照舊分段。
- `compose._split_line_near_middle` 的超寬拆行也不准從數字內部斷開。舊守衛只擋
  數字—數字相鄰，`9/12` 仍可能切在 `9` 與 `/12` 之間。改成先算出所有數字 token
  （`\d+(?:[/.:]\d+)+|\d+`）的內部索引，一律不當斷點——順便涵蓋 `5.5`、`20:00`。

## 7. 底色框還是太高

使用者：要壓到第二段黃字標題（附圖）。

第三批把百分比整個拿掉、只留關係式描述，理由是「模型跟得動關係、跟不動百分比」。
結果反而更糟——模型手上就只剩模板那個 `lower 40%` 可抄。這一版把合成版的真實數字
寫回去，數字與關係式並存：

- 上緣 **78%**（＝`compose.YT_BAND_TOP_RATIO` 0.778），框只佔 **下方 22%**；
- 關係式改用**顏色**點名：上緣齊「白字」那行的基線，全飽和處在「金黃字」那行的上緣。
  顏色比「上面那一行／下面那一行」具體。
- 明列否定：不是 lower third、不是 lower 40%、不是半個畫面。
- 測試 `test_the_number_in_the_clause_matches_the_composite_band` 直接拿
  `compose.YT_BAND_TOP_RATIO` 去比對條文裡的數字，兩邊不會各寫各的。

## 8. 兩行標（白／黃）字級要完全一樣

根因：三個 AI 標題模板都寫著每一行 `filling almost the full width`（整點版是
`spanning almost the full width`）——那是叫**每一行各自**撐滿，字少的那行就被放大。
合成版本來就沒有這個問題（`compose._yt_shared_title_font` 兩行共用一個字級）。

改成：拿掉「各自撐滿」，另立一條——兩行共用**一個**字級，由**較長那行**決定
（較長那行撐滿的那個字級），較短那行照同一個字級排，自然變窄、留白，
**不准**放大去對齊寬度。三個模板（國內外／熱搜／整點）一起改。

> 「還可以再稍微縮小一點點」使用者同一輪撤回，`YT_TITLE_SIZE_RATIO` 不動。

---

## 沒驗到的

**本機這次一張圖都生不了**：`OPENROUTER_API_KEY` 已失效（401 User not found，第三批
就發現了），而 `OPENAI_API_KEY` 這次也回 `429 credit_balance_exhausted`（今天稍早還可用）。
所以第 2、4、5、7、8 項的**實際成品**都沒有本機驗收，只有單元測試與程式碼層面的驗證：

| 項目 | 驗到什麼 | 沒驗到什麼 |
| --- | --- | --- |
| 1 | markup 順序 | 瀏覽器實際畫面 |
| 2 | prompt 內容、端點回填、schema | 真的消化一次外電通稿的品質 |
| 3 | 格式、VERSION↔index.html 一致、遞增邏輯 | — |
| 4 | 條文、標記、兜底函式 | 生圖後底帶真的出現 |
| 5 | 參數形狀、後端判斷、期限常數 | 實際省下多少秒 |
| 6 | 分段與拆行的實際輸出 | — |
| 7 | 條文數字與 `YT_BAND_TOP_RATIO` 一致 | 生圖後框真的降到 78% |
| 8 | 三個模板都有共用字級條文 | 生圖後兩行真的一樣大 |

全套 1172 題綠。

---

## 補記：思考 token 確實已經開著（第 5 項的前提查證）

`reasoning.max_tokens` 的存在會**啟用**推理（OpenRouter 文件：`enabled` 由 `effort`
或 `max_tokens` 的存在推導）。如果正式站本來沒開，這個改動就會變成把每次消化都
弄慢——與需求相反。所以查了正式站的日誌：

```
[digest_usage] site=generate model=anthropic/claude-sonnet-5 budget=10000 completion_tokens=9535 ratio=0.95 finish=stop NEAR-LIMIT
[digest_usage] site=generate model=anthropic/claude-sonnet-5 budget=10000 completion_tokens=10000 ratio=1.00 finish=length TRUNCATED
[digest_usage] site=generate model=anthropic/claude-sonnet-5 budget=6000  completion_tokens=4599 ratio=0.77 finish=stop
```

`completion_tokens` 已經把思考算在裡面（Anthropic／OpenRouter 都是這樣報）。
觀測到的正文最大值是 1361 token，所以 9535 那一次有**八千多**是思考，
而 `10000 finish=length TRUNCATED` 就是使用者說的「偶有失敗」。
封頂 2000 是真的封頂，不是把它打開。

`log_digest_usage` 同時補記 `reasoning_tokens`（從 `completion_tokens_details` 拿），
以後不必再靠反推。

## 補記：`<底帶>` 的連帶影響

`main._VERBATIM_MARKER_RE` 原本只列 `<蓋章>`，其餘靠 `[<>]` 剝括號——`<底帶> 丁`
會剩下「底帶丁」，逐字守門員判成多出兩個字 → 五次重試 → 502。
「不消化 ＋ 播出鏡面 ＋ 蓋章 OFF」是合法組合，所以 `<底帶>` 也要明列。
`app.js` 查過：前端沒有解析標記的地方，只有 prompt 文字副本（已同步）。

---

## 實際生圖驗收（2026-09-09 晚，使用者儲值後）

本機仍走 OpenAI 原生（`DIGEST_BACKEND=native DIGEST_MODEL=gpt-5 IMAGE_BACKEND=native`），
OpenRouter 那把金鑰依舊 401。版面規則的驗收有效，消化文字風格與正式站的
`anthropic/claude-sonnet-5` 不完全等同。

四張樣張在 `D:\Downloads\` 與 `G:\我的雲端硬碟\Claude共用\AICG\`（前綴 `20260909-194`）：

| 樣張 | 驗的項目 | 結果 |
| --- | --- | --- |
| A 熱搜封面 AI 字＋底色框 | 7、8 | 兩行同字級（黃字明顯較短、置中留白，不再被放大）；框上緣落在白字腳下、約畫面 76%，黃字整行在框內 |
| B 國內外直播 AI 字＋底色框 | 7、8 | 同上，兩個版型一致 |
| C 播出鏡面 left 字多 蓋章 OFF | 4 | 底帶出現：「指出通膨趨緩與就業放緩　支持加快降息」跨全寬、在挖空框下方，四張卡在右半邊，示意圖浮水印在右下 |
| D 播出鏡面 right 字多 蓋章 OFF | 4 | 鏡射正確（卡在左、窗在右），底帶「降息判斷依據數據　非為政治壓力」同樣跨全寬 |

第 2 項用使用者給的那則路透通稿實測：

```
第一標題: 小布希與各界談911影響        => 10 格 / 上限 12
第二標題: 達拉斯布希中心25周年活動      => 12 格 / 上限 14
來源    : George W. Bush Presidential Center   （取自 Must credit 那一行）
```

### 這次驗收抓到的兩件事

1. **`/api/editor/cover-titles` 的輸出上限寫死 2000，對推理模型不夠。**
   直標那條 prompt 又多兩千多字元，實測 `completion_tokens=1905` 裡
   `reasoning_tokens=1856`，正文只剩四十幾個 token，整個吐空字串 →
   `JSONDecodeError` → 502。改成 `COVER_TITLE_DIGEST_MAX_TOKENS = DIGEST_MAX_TOKENS`
   （理由與主消化同一條：正文短而穩、爆的是思考，而上限是天花板不是用量）。
   順帶讓 `digest_reasoning_body` 的思考封頂在這條線上也生效——2000 的預算扣掉
   正文保留額之後低於 1024，等於封不到。

2. **第 5 項要修的那個失敗，這次當場重現了一次。** D 的第一次 attempt：
   `budget=10000 completion_tokens=10000 reasoning_tokens=10000 finish=length TRUNCATED`，
   raw content 全空、重試才成功。本機走原生 OpenAI 沒有思考封頂（那是 OpenRouter
   的欄位），正式站有。新加的 `reasoning_tokens` 欄位讓這件事第一次看得見。

### 品質上的小瑕疵（沒改，記著）
- 消化出來的「911周年」「25周年」在臺灣用法應該是「週年」。這是消化文字的問題不是版面，
  而且本機跑的是 gpt-5、不是正式站的模型，先不動。
- 來源回傳英文原名（`George W. Bush Presidential Center`）。條文寫的是「有標準中譯就用中譯，
  否則用原文」，這個機構沒有通用中譯，回原文合規。
