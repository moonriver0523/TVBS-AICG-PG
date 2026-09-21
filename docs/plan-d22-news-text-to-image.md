# D22 追加評估：生圖端是否接收消化前新聞原文

日期：2026-09-21  
範圍：只評估 D22 與 B70／F43 的整併關係；不實作、不變更既有行為。

## 結論先行

選 **(b) 分開做，但共用 B70／F43 抽出的 seam**。

D22 的一般 CG／播出鏡面接線位置確實與 B70／F43 高度重疊：都是 `ImageGenerateRequest`，也都是 `app.js` 內兩個 `/api/images/generate` request body。**但本段原先把範圍限定成這兩個 payload，已被第 7 節裁決 4 推翻**；核准範圍還包括十點與四種 YT 封面，須另外接既有封面畫面推導 seam。`yt_vstrip` 則沒有生圖模型可注入，實際邊界見第 8 節。現行 `app.js` 是 **4,006 行**，而且 PR 5 本來就要改同兩個一般 CG payload。

但 D22 不應混進 B70／F43 的 PR 2 或 PR 5。標籤案改的是 provenance、標籤 schema、幾何、拖曳與 compose；D22 改的是「哪些新聞內容可進入生圖模型」這個模型信任介面。後者會改 prompt 語意、成本、內容忠實度與 B55 的文字正確性風險，驗收方式也不是標籤測試能涵蓋。把兩者塞在同一 PR，若成品退化，無法判斷是標籤／版面改造還是原文污染 prompt。

建議順序是：先完成 B70／F43 PR 2，再完成 PR 5 並穩定兩個 generate payload；D22 另開 `D22-PR1`，排在 PR 5 後、無須等待移除 legacy 欄位的 PR 6。一般 CG／播出鏡面共用已穩定的 `ImageGenerateRequest` seam 與兩個 image payload call site；封面另沿用既有畫面推導 seam。D22 不共用標籤政策或 renderer。

依題意，因結論不是「一起做」，**不修改** `docs/plan-disclaimer-unification.md`。

## 1. 實際程式與技術重疊度

### 1.1 D22 列管行號已漂移

`main.py:518-526` 的說明仍與現況相符：消化與生圖是兩次獨立請求，沒有嚴格 correlation id，因此以 user_id＋時間窗補稽核資料。

但列管文字所指的 `app.js:1145-1146` 已不是 fetch；現行該處是輸入區 DOM 搬移。真正呼叫點是：

- `app.js:2310-2332`：`_digestFetch()` POST `AI_BACKEND_URL`，其中 `news_text: input` 在 `app.js:2315`。
- `app.js:3138-3165`：`handleOneClickGenerate()` 的第一個 `IMAGE_BACKEND_URL` payload。
- `app.js:3266-3287`：`handleImageGeneration()` 的第二個 `IMAGE_BACKEND_URL` payload。

兩個生圖 payload 正是 B70／F43 PR 5 要維持 `...disclaimerPayload()` 各出現一次的兩處（目前在 `app.js:3164`、`app.js:3286`）。因此 D22 與 disclaimer 前端改動是**同兩個 object literal、不同欄位語意**。

### 1.2 最小改動量

依第 7 節裁決，D22 的核准接線為：

1. 一般 CG／播出鏡面的 digest response 產出 optional `visual_context`；前端把它和該次 digest 綁定，再由兩個 `/api/images/generate` payload 明送。
2. 十點與四種 YT 封面的標題消化 response 同樣產出 `visual_context`；`tenCoverFields()`／`ytCoverFields()` 明送給各自端點。既有 `news_text` 保留供標題消化、稽核與舊 caller fallback，但同一次畫面推導只能選一份來源，細節見第 8 節。
3. 後端對一般 CG／播出鏡面使用集中式 prompt adapter；封面則在既有 `resolve_cover_visuals()`／`derive_yt_cover_plan()` seam 消費，不可把同一份內容再附到最終生圖 prompt。
4. `yt_vstrip` 仍走純 compose；不得為了字面滿足「全部版型」而新增一條背景生圖流程。
5. 稽核路徑記明送的 context mode／長度；memo 只保留為舊 caller 的 audit fallback，不能成為模型輸入。

所以「只改 2 個 payload 欄位、1 個 schema 欄位」是裁決前的低估。與 disclaimer 共用的仍只是一般 CG 的兩個前端函式；封面還要改各自 request／response schema、digest state 與畫面推導 seam。D22 仍應使用獨立的 context helper，不應塞進 `disclaimerPayload()`。

「大檔風險」仍有一小部分成立：兩個 payload 容易只改到一處，且 `handleImageGeneration()` 是消化後人工確認再生圖的另一條路，取哪一版 `visual_context` 有狀態一致性問題。不過 B70／F43 已用「出現次數恰為 2」的 contract test 管同一風險，故風險來源已從「碰大檔」縮小成「兩路 payload 與 digest state 必須一致」。不能再用檔案總行數作為否決 D22 的充分理由。

## 2. `_remember_digest`／`_recall_digest` 不能升級成模型輸入

目前實作：

- `_DIGEST_MEMO_TTL = 1800`，即 30 分鐘。
- `_digest_memo` 每個 `user_id` 只有一筆 `(timestamp, fields)`。
- `_remember_digest()` 直接覆蓋該 user 的上一筆。
- `_recall_digest()` 只回該 user 尚未過期的最新一筆。
- `_enrich_archive_fields()` 只在 archive 欄位為空時用 memo 回補；這原本就是 best-effort 稽核補值，不是交易關聯。

若直接把 recall 結果放進模型，至少有以下 correctness 風險：

1. **多視窗／多分頁錯配**：同一帳號 A 分頁先消化甲稿，B 分頁再消化乙稿；A 分頁生圖時會拿到乙稿。
2. **完成順序錯配**：兩次消化併發時，較早送出的慢請求可能較晚完成並覆蓋 memo；「最新完成」不等於「這次生圖所屬」。
3. **消化後回頭操作舊結果**：使用者在 30 分鐘內切回舊 digest 再生圖，memo 仍是另一稿。
4. **TTL 不是關聯**：30 分鐘只判斷「夠新」，不能證明是同一工作；縮短 TTL 只增加 miss，不能消除誤配。
5. **process-local 狀態**：memo 是行程記憶體。多 worker、水平擴充、重新部署或請求落到另一實例時可能取不到；若共用帳號，碰撞更嚴重。
6. **silent failure**：缺 user_id 或過期時回 `{}`，沒有錯誤；用於 archive 尚可，用於模型會造成同一功能忽有忽無。

因此 memo **不能**成為 D22 的低成本正式解。錯配原文比沒有原文更危險，因為模型可能把另一則新聞的人名、數字或事件畫進本圖，而且從 API 狀態看仍是成功。

正式方案必須由前端明送本次生圖所屬資料。最低成本可直接送 `news_text`；更嚴格的替代是 `/api/generate` 回 `digest_id`，前端生圖時回傳該 id，後端以有界、可跨 worker 的 store 取原文。但這仍需要改前端與 request model，並新增 TTL、授權與儲存生命週期，對本案沒有比直接明送更便宜。若需要證明「原文與 digest 必為同一次」，則可同送 `digest_id`／原文 digest（hash）做一致性驗證；不能靠 user_id 猜。

## 3. 價值與反效果

### 3.1 可能改善的部分

原文可補上消化結果在 `style`／`structure`／`variable` 中省略的視覺背景，例如：

- 同名人物、機構、地點或事件的消歧。
- 車種、建築、設備、服裝、天候、場景關係等不一定適合寫成畫面文字，但有助於畫對的細節。
- 多事件新聞中「誰在何處做了什麼」的關係，降低 generic stock scene。
- 消化後描述過度精簡時，提供查核畫面物件是否有來源的第二份依據。

它**不應改善或重做標題**。標題與所有可讀文字仍只以 `VARIABLE FIELDS` 為唯一來源；生圖模型不得根據原文改字、補字、改數字或另下標。

### 3.2 主要反效果

現行 `news_prompt.py:797-802` 已規定只畫 `VARIABLE FIELDS` 的 words／figures／facts，並禁止自行加入數字、機構、來源與 caption；`main.py:1897-1915` 也明確把「可補充內容」限制在消化階段。把完整原文加到生圖 prompt 後，會引入一個新的、語意較模糊的內容來源：模型可能把「出現在 prompt」誤讀成「要求畫出」。

具體風險包括：

- 把原文中的日期、傷亡數、金額、百分比、車號等加到畫面，雖然它們是真實新聞內容，卻不是已定案的 `VARIABLE FIELDS`。
- 把人名、機構名、媒體名或品牌畫成額外 label／logo；`FINAL_IMAGE_BASELINE` 的「不得新增 prompt 未命名的人」在加入原文後也變弱，因為更多人已經「named in this prompt」。
- 用原文的另一種說法改寫標題，破壞「消化階段定案，生圖階段不得改字」。
- 原文含多起事件或背景沿革時，把非主題事件也畫進去，反而降低視覺焦點。
- 原文中若含「請加入」「標示」等引述或編輯語句，會形成低階 prompt injection；delimiter 與指令可以降低但不能形式化消除。
- 安全區規則中的「禁數字」主要是禁止用數字描述 canvas 幾何，避免模型把座標／比例畫出來；原文數字是內容，加入後仍可能被畫到安全區或擠壓版面，不能把既有規則誤當成完整防護。

### 3.3 與 B55 的衝突

B55 的透明標題層守門驗的是 alpha、可繪區、面積上下限與保護區；它**沒有 OCR，也不驗圖層中文字是否逐字等於指定標題**。因此若原文進入 `purpose="titlelayer"` 的模型 prompt，模型多畫一個原文數字、人名或機構名，只要仍落在允許字帶、面積也合法，就可能通過 B55 並被疊回原圖。

所以 D22 第一版必須有硬隔離：

- `ImageGenerateRequest.visual_context` 預設空字串，且硬上限 4,000 characters；一般生圖 request 不新增 raw `news_text` 模型輸入。
- 一般 CG／播出鏡面的兩個 payload，以及十點與四種 YT 封面的各自 payload 都可送；內部 B55 `titlelayer` request、`ImageRefineRequest`、重貼 disclaimer endpoint 一律不繼承。
- `apply_user_references_to_image_request()` 遇到 `purpose="titlelayer"` 時，不得把 news context 注入該 prompt。
- 若日後要讓封面 title-layer 看原文，先新增語意守門（至少能驗可讀文字只含指定 title；單靠現有像素／面積閘不夠），另案裁決。

### 3.4 緩解方案比較

| 輸入 | 視覺補益 | 誤加文字／事實風險 | 成本 | 建議 |
|---|---:|---:|---:|---|
| 完整原文 | 最高但邊際收益不明 | 最高 | 最高且最不穩定 | 不直接全量上線 |
| 截斷原文 | 中高 | 仍高，且可能切掉否定、歸屬或上下文 | 有上限 | 只適合 feature flag 實驗 |
| 另做自然語言摘要 | 中 | 摘要模型仍可能改意或遺漏 | 多一次模型成本／失敗點 | 不建議為「低成本 D22」新增第三次請求 |
| 同一次消化產出 `visual_context` | 中高 | 中；可明定不得含畫面文字 | 低增量 | 建議正式方案 |
| 只給實體清單 | 中低 | 人名／品牌仍可能被畫成字或臉 | 低 | 只適合需要消歧的類型 |
| 只給視覺相關敘述 | 高 | 最低但非零 | 低增量 | 最推薦，與 `style`／`structure` 一起驗收 |

推薦讓消化 schema 同次產出一個 bounded `visual_context`：只描述可由原文支持的場景、物件、關係與消歧資訊；明禁任何要畫出的標題、caption、數字、機構標籤與來源名。後端仍可收 `news_text` 供一致性／稽核，但生圖模型預設只吃 `visual_context`。完整原文模式只放在 feature flag 實驗組，用真實樣張判定它是否比結構化 context 更好。

## 4. Token 與成本量級

repo 的 transport 上限已有兩個重要數字：

- `ImageGenerateRequest.prompt` 上限 20,000 characters。
- 多條新聞 request 的 `news_text` 上限也是 20,000 characters；一般 `GenerateRequest.news_text` 目前甚至沒有 Pydantic 長度上限，前端不應假設永遠很短。

用現行 `news_prompt.build_prompt()` 本機量測：空的 `style`／`structure`／`variable` 仍約 **11,079 characters**；放入 600／1,200／500 characters 的代表性三欄後約 **13,379 characters**。這是英文規則為主，約可視為 **3,000–5,000 input tokens** 的量級，實際依 provider tokenizer 與中文字比例而變。

新聞原文可用以下保守量級估算：

- 短訊／整理稿：500–1,000 中文字，約 600–1,300 tokens。
- 一般完整新聞：1,000–2,500 中文字，約 1,200–3,200 tokens。
- 長稿／逐字材料：5,000–20,000 中文字，約 6,000–25,000 tokens。

所以典型原文可能讓現行 image input 增加約 **15%–80%**；若允許 20,000 字全送，則可能增加數倍，且讓不同稿件的成本與延遲變異過大。即使 provider context window 吃得下，也不代表值得付費或值得讓尾端硬規則被長原文稀釋。

建議限制分兩層：

1. `ImageGenerateRequest.news_text` 可接受與來源端一致的最多 20,000 characters，避免「消化成功、生圖卻因 schema 較短而 422」。
2. 真正注入模型的 `visual_context` 第一版硬上限 **4,000 characters**；若做 raw experiment，亦固定 4,000 characters，採 deterministic head＋tail（例如前 3,000、後 1,000）並加明確 truncation marker。不能默默依 provider 任意截斷。

4,000 是實驗起點，不是永久真理；上線前應以實際 input-token telemetry、延遲與違規率裁定是否下修。若摘要／抽取結果本來遠短於此，就送實際長度，不補滿。

D22 不應新增自動生圖重試：每個使用者動作仍只呼叫 image provider **1 次（attempt 上限固定為 1）**。A/B 的 control 與 treatment 是兩個明確實驗 arm，不得包裝成失敗後自動再試。若未來因 context 導致 provider 400 而設 fallback，最多只能明定「去除 context 後重試 1 次」，即總 attempt 上限 2，且要記錄 fallback；不得寫成無上限重試。本評估建議第一版連這一次 fallback 都不要加，以免靜默多燒一張圖。

## 5. 建議的獨立 `D22-PR1`

前提：B70／F43 PR 2 與 PR 5 已完成並全綠；不必等待 PR 6。

### 5.1 程式 seam（若使用者裁決啟動後才做）

1. `main.ImageGenerateRequest`
   - 新增 canonical `visual_context: str = Field(default="", max_length=4_000)`；依裁決不新增 raw `news_text` 模型輸入欄位。
   - `TenCoverRequest`／`YtCoverRequest` 另加同名 optional 欄位；既有 `news_text` 仍維持 20,000-character transport，僅供標題消化、稽核與第 8 節定義的 legacy fallback。
   - `ImageRefineRequest` 維持不收 `visual_context`。
2. `app.js`
   - `digestNewsText()`／`_digestFetch()` 保留本次輸入與 digest response 的綁定 state，不能只在生圖當下重讀可能已改過的 textarea。
   - `handleOneClickGenerate()` 與 `handleImageGeneration()` 的兩個 payload 透過同一 `newsContextPayload()` 明送；測試釘出現次數為 2。
   - `handleCoverTitleDigest()` 需把十點／YT 封面的 `visual_context` 與各自 textarea 的該次 digest 綁定，`tenCoverFields()`／`ytCoverFields()` 明送。`vstripFields()` 不送入 compose；理由見第 8 節。
3. `news_prompt.py`
   - 新增純函式 `append_visual_context(prompt, context)`；context 放在清楚的「background only／never render wording」區塊，並由 `ensure_final_image_baseline()` 保證最終硬規則仍在最後且只出現一次。
   - 不修改 `VARIABLE FIELDS`，不把 context 混入 `style`／`structure`，讓既有文字唯一來源仍可測。
4. 後端注入 seam
   - 一般 CG／播出鏡面在 `main.generate_image_raw()` provider dispatch 前集中呼叫 context adapter，再注入 `FINAL_IMAGE_BASELINE`；OpenRouter、native GPT、Gemini 共用，避免三套漂移。
   - 十點／YT 封面只在 `resolve_cover_visuals()`／`derive_yt_cover_plan()` 選用 `visual_context` 作來源材料；不得又經通用 adapter 把同一內容附到最終生圖 prompt。
   - 對 `titlelayer`、refine、disclaimer render 明確不注入。
5. `_enrich_archive_fields()`
   - 明送的 `req.visual_context` 只供模型與 context telemetry；原文 audit 仍只有舊 caller 欄位為空時才用 `_recall_digest()` 回補，memo 永不進模型。
   - archive 加 `news_context_mode`（`none`／`visual`）、context digest/hash、注入 characters／estimated tokens、是否截斷，才能比較品質與成本。

### 5.2 測試

新增 `tests/test_d22_news_context.py`，至少包含：

- 一般 `ImageGenerateRequest.visual_context` 的 4,000 字上限，以及封面既有 `news_text` 20,000 字 transport 不被縮短。
- 兩個前端 image payload 都明送，且綁的是完成消化的那一版 `visual_context`；payload builder 出現次數恰為 2。
- 模擬 textarea 在消化後被改動，未重新消化不得把新稿配給舊 prompt。
- `append_visual_context()` 的空值 no-op、固定截斷、delimiter、不得改 `VARIABLE FIELDS`、`FINAL_IMAGE_BASELINE` 最後且恰一次。
- OpenRouter、native GPT、Gemini 三條 transport 都只收到一次 context；caller request object 不被 mutate。
- `_remember_digest` 中故意放另一稿時，明送 `req.visual_context` 仍是唯一模型 context；memo 只可做 archive fallback，永不進模型。
- 同 user 兩分頁／反向完成順序的 characterization test，證明 memo 不可作模型 correlation。
- `purpose="titlelayer"`、`ImageRefineRequest`、`POST /api/images/disclaimer/render` 零 context。
- attempt 上限為 1；不因 context 自動多呼叫一次 image provider。

必跑既有回歸：

- `tests.test_b70_f43_disclaimer`
- `tests.test_final_image_baseline_paths`
- `tests.test_content_fidelity`
- `tests.test_prompt_parity`
- `tests.test_b55_transparent_title_layer`
- `tests.test_digest_stage_audit_20260920`
- `tests.test_generate_stream_20260915`

執行方式使用 `unittest` 的 named loading，例如：

```powershell
python -m unittest tests.test_d22_news_context tests.test_b70_f43_disclaimer tests.test_final_image_baseline_paths tests.test_content_fidelity tests.test_prompt_parity tests.test_b55_transparent_title_layer tests.test_digest_stage_audit_20260920 tests.test_generate_stream_20260915
```

再以專案既有的 `loadTestsFromNames` 全套命令跑完目前 **2237 題基準＋新增題目**；不得使用 `pytest` 或 `unittest discover`，不得讓既有 2237 題少一題或放寬斷言。

## 6. 需要使用者裁決

1. **D22 的目標究竟是 raw article，還是 visual grounding？**  
   建議裁決為 visual grounding：同一次消化多回一個只含視覺相關敘述的 `visual_context`；raw article 僅做 feature-flag A/B，不直接成為正式預設。

2. **是否批准 4,000-character 模型注入上限？**  
   建議批准作為實驗上限，transport 可收 20,000；依 telemetry 再下修。若堅持全文，需明確接受成本、延遲與硬規則稀釋，且仍不得超過一個寫死上限。

3. **截斷策略。**  
   建議 raw experiment 使用 deterministic 前 3,000＋後 1,000；正式版用 bounded `visual_context`，不截原文來冒充完整語意。需要裁決是否接受 head＋tail 可能切斷句子的風險。

4. **涵蓋路徑（已裁決）。**
   本項原建議「第一期只做一般 CG」已被第 7 節裁決 4 推翻。實作範圍改為一般 CG、播出鏡面、十點與四種 YT 封面；`titlelayer`、refine、disclaimer render 仍排除。封面沿用畫面推導 seam，不把 context 直接重複餵給最終生圖模型；`yt_vstrip` 的無生圖事實與建議邊界見第 8 節。

5. **A/B 驗收門檻。**  
   需先定義樣本數與判準：視覺事實錯誤率、額外文字／數字／Logo 違規率、標題逐字錯誤率、成本與延遲。建議只有 treatment 的視覺準確度明顯提升，且上述違規率不高於 control，才開正式 flag。

6. **是否要求嚴格 correlation。**  
   建議至少綁定前端保存的 digest state；若還要可稽核地證明同一次請求，新增 `digest_id`／hash。明確否決用 user_id＋TTL 作模型輸入關聯。

7. **B55 是否永遠排除。**  
   建議第一期硬排除。未來只有在有能力驗證透明層可讀文字與指定 title 相同後，才另案開放；現有 alpha／bbox／面積守門不足以保證文字忠實度。

## 最終建議

D22 的「接線成本」已因 B70／F43 同批 seam 改造而顯著下降，但「內容是否應進模型」仍是獨立、高風險的產品與模型政策決策。故不併入 B70／F43 PR 2 或 PR 5；先讓標籤改造穩定，再開獨立 `D22-PR1`，使用相同 request／payload seam、獨立 feature flag、固定長度與固定 attempt 上限做 A/B。

在沒有 A/B 證據前，不建議把消化前完整原文直接設為正式模型輸入；建議正式候選是同次消化產出的 bounded `visual_context`，而 `_remember_digest`／`_recall_digest` 永遠只保留為 audit fallback。

---

## 7. 使用者裁決（2026-09-21）

第 6 節 7 項全數裁定如下。**裁決優先於本文件其他章節的建議**。
排程面採本文件結論：D22 **不併入** B70／F43 的 PR 2／PR 5，另開獨立 `D22-PR1`，排在 PR 5 之後、不必等 PR 6。

| # | 題目 | 裁決 | vs 建議 |
|---|---|---|---|
| 1 | 餵什麼 | **只給 `visual_context`**（消化同次產出的畫面相關描述）；不送完整原文，不開 raw A/B arm | 採納正式方案，不做 raw 實驗 |
| 2 | 注入上限 | 硬上限 **4,000 characters**；transport 仍可收 20,000 | 採納 |
| 3 | 截斷策略 | deterministic **前 3,000 ＋後 1,000**，中間加明確 truncation marker | 採納 |
| 4 | 涵蓋路徑 | **全部版型都開**（一般CG、播出鏡面、直標、十點與四種 YT 封面） | 偏離（建議只做一般CG） |
| 5 | 驗收門檻 | 比對組 A/B，**兩條件都要過**：視覺準確度明顯提升，且額外文字／數字／Logo 違規率不高於 control | 採納 |
| 6 | 稿件配對 | **前端明確帶過來**；否決 user_id＋TTL 猜測 | 採納 |
| 7 | AI 標題層 | **例外，不吃** | 採納 |

### 7.1 裁決造成的設計變更

**（裁決 1＋3）`visual_context` 本身就受同一組長度規則。**
既然不做 raw arm，4,000 上限與前 3,000＋後 1,000 的截斷規則直接套用在 `visual_context`：消化端應該產出遠短於此的內容，截斷只是防線，不是常態。實際長度短於上限時就送實際長度，不補滿。3.4 表格中「完整原文」「截斷原文」「另做摘要」「只給實體清單」四列均不採用。

**（裁決 4）涵蓋範圍由一般CG 擴大到全部版型（標題層除外）。**
第 6 節第 4 項與 5.1 的 seam 需相應擴大：
- D22 seam 必須涵蓋封面既有畫面推導路徑，不只 `/api/images/generate` 的兩個 payload；直標沒有生圖呼叫可接，依第 8.7 節待裁。
- 封面路徑目前本來就有 `news_text` 用於推導畫面描述，需釐清那條路與新的 `visual_context` 的關係，**不可重複注入兩份語意相近的內容**。這是 `D22-PR1` 開工前要先查清的第一件事。
- 每一條新涵蓋的路徑都要確認 `visual_context` 為 optional、預設空字串，缺值時行為與現況完全相同。

**（裁決 7）標題層的硬隔離維持，且是唯一例外。**
3.3 的隔離清單維持有效：`purpose="titlelayer"` 的 request 一律不注入 `visual_context`；`ImageRefineRequest`、重貼 disclaimer endpoint 同樣不繼承。理由不變——B55 守門只驗 alpha、面積與保護區，沒有 OCR，無法擋住模型多畫一個未定案的人名或數字。日後若要開放，須先具備「標題層可讀文字等於指定 title」的驗證能力，另案裁決。

**（裁決 6）配對方式。**
前端在消化成功時保存 `visual_context` 與該次 digest 的關聯，生圖時明送；不加 `digest_id` 核對層。`_remember_digest`／`_recall_digest` 維持 audit fallback，不得成為模型輸入來源。

**（裁決 5）A/B 仍要做，但兩個 arm 都是 `visual_context`。**
control = 不送，treatment = 送。attempt 上限固定為 1，不加 fallback 重試（第 4 節結論維持）。

### 7.2 開工前先查清的事

1. 封面路徑既有的 `news_text` 用途，與新 `visual_context` 是否重疊。
2. 消化 schema 要新增 `visual_context` 欄位，其 prompt 約束文字（明禁任何要畫出的標題、caption、數字、機構標籤、來源名）需與 `news_prompt.py:797-802` 的既有禁令對齊，不可互相矛盾。
3. 全部版型涵蓋後的實際 token 增量，需重新量測（本文件第 4 節只量了一般CG 路徑）。

## 8. 開工前盤點（2026-09-21）

### 8.1 結論：封面既有 `news_text` 與新 `visual_context` 是同一語意層，不可並排注入

封面現況不是把 `news_text` 直接塞給 image provider，而是先讓文字模型把「標題＋新聞原文＋編輯指令」翻成可拍攝的 `visual_left`／`visual_right` 或 `visual`，再把該畫面描述交給生圖模型。這與 D22 定義的 `visual_context`——同次消化產出的場景、物件、關係與消歧資訊——在語意上是同一種 visual grounding，只是產生時間不同。既有推導規則也明定輸出必須是「鏡頭看得到什麼」、不得含 caption／標題／數字／圖表（`editor_formats.py:1020-1037`、`editor_formats.py:2313-2329`），和本文件第 3.4 節對 `visual_context` 的定義幾乎重合。

因此明確做法如下：

1. 封面 request 同時可攜帶 `news_text` 與 `visual_context`，但**同一次畫面推導只准選一份來源**：`visual_context.strip()` 非空時只用它；否則才以既有 `news_text` 作 legacy fallback。這是 `effective_visual_source = visual_context or news_text`，不是把兩段串起來。
2. `resolve_cover_visuals()`／`derive_yt_cover_plan()` 保留，因為它們除了場景還負責左右格分派、標題斷行與 `portrait_subjects`／英文名抽取；只是來源材料改吃上述 `effective_visual_source`。既有 `news_text` 仍供封面標題消化、稽核與舊 caller 相容。
3. 推導完成後，最終生圖 prompt **只放推導出的** `visual_left`／`visual_right`／`visual`；不得再由通用 `append_visual_context()` 附一次原始 `visual_context`。否則相同人物、地點、動作被兩種措辭重複一次，模型會把它視為加權訊號，增加重複人物／物件、硬切多景或過度強調某個事件的風險。
4. A/B 的封面 control 維持現況（沒有 `visual_context` 時仍以 `news_text` 推導），treatment 以 `visual_context` **取代**該次推導的 raw source。不能把 control 改成完全無 grounding，否則量到的是「拿掉 B53」而非 D22 增益。
5. 有現成底圖、全格 `asis` 或只重壓文字而根本不需要推導／生背景的分支，`visual_context` 維持 optional no-op；不得為了宣稱「有開」而多打一個模型。

### 8.2 封面 `news_text` 的實際來源、傳遞與消費

**共同來源與第一次消費（標題消化）：**

- 前端 `handleCoverTitleDigest()` 直接讀 textarea：十點讀 `#coverNewsText`、YT 讀 `#ytCoverNewsText`（`app.js:2615-2623`），並把原文以 `{ news_text, target }` POST 到 `/api/editor/cover-titles`（`app.js:2628-2632`）。直標另走同端點，見 8.5。
- 後端 transport 是 `CoverTitleDigestRequest.news_text`，上限 20,000 characters（`main.py:6703-6710`）；`_editor_cover_titles_impl()` 在 `digest_completion(..., news_text=req.news_text.strip())` 消費它以產生封面標題（`main.py:6873-6915`）。現行 `CoverTitleDigestResponse` 只有標題、來源與籤，沒有 `visual_context`（`main.py:6771-6786`）。
- 標題消化只回填標題欄，原 textarea 留在畫面上；目前沒有把「這份原文／未來的 `visual_context`」與該次回應綁成 state。生封面時會再次讀 textarea，因此使用者在消化後改原文、未重新消化，標題與畫面來源就可能來自不同版本。D22 必須在消化成功時保存配對，不能到生成當下才重讀。

**十點封面（滿版與 split）：**

- 生成 request 的原文由 `tenCoverFields()` 的 `#coverNewsText` 取得（`app.js:2421-2432`）；真正重生的 object literal 也再次讀同一欄（`app.js:2553-2563`）。後端欄位是 `TenCoverRequest.news_text`（`main.py:5635-5639`）。
- `resolve_cover_visuals()` 先組左右標題／既有描述，再把非空 `news_text` 附成 `News article source material`（`main.py:6055-6081`），交給 `COVER_VISUAL_DERIVE_SYSTEM`／`COVER_VISUAL_SCHEMA`（`main.py:6091-6103`；schema 欄位見 `editor_formats.py:1073-1088`）。它產出每格 `visual_*` 與具名真人，使用者已填的 `visual_*` 優先（`main.py:6111-6139`）。
- 滿版在無 `asis`／既有底圖時呼叫這支推導（`main.py:6984-7012`）；split 在至少有一格需生底圖時呼叫（`main.py:7213-7230`）。結果最後進入無字底圖 prompt（`main.py:6171-6190`、`main.py:6553-6557`、`main.py:6593-6600`），或 AI 整張封面的 `{visual_left}`／`{visual_right}`（`main.py:6341-6364`）。所以 raw `news_text` 的實際消費點是**第二次文字模型**，不是 image provider。

**四種 YT 封面（`yt_live_cover`／`yt_hourly_cover`／`yt_live24_cover`／`yt_hot_cover`）：**

- 四種 UI 共用 `ytCoverFields()`；layout 由當前版型決定，原文直接讀 `#ytCoverNewsText`（`app.js:2705-2733`）。後端共用 `YtCoverRequest.news_text`（`main.py:7367-7374`）與 `/api/editor/yt-cover`（`main.py:7993-7998`）；request 的 `layout` 值是 `news`／`hourly`／`hot`／`live24`（`main.py:7338-7344`）。
- 單則由 `resolve_yt_cover_plan()` 呼叫 `derive_yt_cover_plan(..., req.news_text)`（`main.py:7530-7556`）；雙則拆成左右 panel 後，每格仍各自把同一份 `panel_req.news_text` 交給推導（`main.py:7917-7939`）。
- `derive_yt_cover_plan()` 把原文附成 `News article source material`，明定只供認人與場景準確度、不得照抄（`main.py:7456-7506`），回傳 `visual` 與肖像欄位（`main.py:7568-7580`）。`visual` 最後進入 composite 無字底圖 prompt（`main.py:7654-7695`）或 AI 整張封面 prompt 的 `{visual}`（`main.py:7738-7745`）。
- 雙則現況會讓兩個 panel 各看到同一篇完整原文；換成單一 `visual_context` 後沿用同樣規則，以各自 title 作主題 selector。第一版不另發明 `visual_context_left/right`，避免偏離裁決的單一 canonical 欄位；若實拍出現跨格污染，再用證據另案拆欄位。

### 8.3 重複注入會發生什麼

若保留目前 `news_text → derived visual`，又把新 `visual_context` 直接附到最終 image prompt，image provider 會同時看到「二十至四十字的具體鏡頭」與「同一事件較長的場景／物件／關係描述」。這不是互補的標題與背景分工，而是同一視覺事實的兩次表述。可能結果包括：

- 同一人物或物件被畫兩次，或被拆成兩個場景；
- 多事件材料中，被重複提及的次要背景搶過標題主題；
- `visual_context` 的較長描述稀釋封面既有的單一鏡頭、單句與 text-free 約束；
- 兩份內容細節不一致時，模型自行折衷，反而降低可稽核性。

故封面的 D22 seam 應是「替換推導來源」，不是「再疊一個 final-prompt block」。一般 CG／播出鏡面才使用通用 `append_visual_context()`，封面 request 不應把 `visual_context` 繼續複製到內部 `ImageGenerateRequest`。

### 8.4 既有測試代表的契約與應新增的釘法

現有 B53 測試已釘住 raw `news_text` 會進封面推導 material：

- `tests/test_cover_photo_availability.py:231` `CoverNewsTextMaterialTests.test_news_text_is_appended_as_source_material`
- `tests/test_cover_photo_availability.py:243` `CoverNewsTextMaterialTests.test_empty_news_text_leaves_material_byte_identical`
- `tests/test_cover_photo_availability.py:259` `YtCoverNewsTextMaterialTests.test_news_text_is_appended_as_source_material`
- `tests/test_cover_photo_availability.py:269` `YtCoverNewsTextMaterialTests.test_empty_news_text_leaves_material_byte_identical`
- `tests/test_b68_cover_material_newline_20260920.py:47` `TenCoverMaterialNewlineTests.test_news_text_segment_uses_real_linebreaks`
- `tests/test_b68_cover_material_newline_20260920.py:69` `TenCoverMaterialNewlineTests.test_both_extra_segments_together_still_use_real_linebreaks`
- `tests/test_b68_cover_material_newline_20260920.py:87` `YtCoverMaterialNewlineRegressionTests.test_material_never_contains_literal_backslash_n`
- `tests/test_stage5b_ui.py:34` `Stage5bUiTests.test_cover_fields_send_news_text_verbatim`

採本節方案後，這些 legacy fallback 測試可保留；另加「`visual_context` 非空時 material 含它且不含 raw `news_text`」、「空值才退回 raw」、「最終 image prompt 不再出現原始 `visual_context` 第二次」及「titlelayer request 零 context」。若實作選擇直接刪除 legacy fallback，上述前七個 material 契約會刻意變紅；本盤點不建議那樣做。

### 8.5 直標與播出鏡面的類似內容注入現況

**直標 `yt_vstrip`：有原文消化，沒有生圖內容注入。** `handleVstripTitleDigest()` 讀 `#vstripNewsText` 並以 `target: 'yt_vstrip'` 送到封面標題消化端點（`app.js:2668-2682`）；後端用該原文產出兩段標題與來源名（`main.py:6873-6915`、`main.py:6944-6951`）。但真正生成時 `vstripFields()` 只送標題、來源與版面開關（`app.js:2884-2896`），`/api/editor/yt-overlay` 明確「不生圖、不打任何模型、沒有底圖」（`main.py:8407-8413`），只呼叫 `compose.compose_yt_overlay()` 畫透明 PNG（`main.py:8473-8507`）。所以它沒有可與 `visual_context` 類比的 image-prompt 注入點；原文只用來定稿可讀文字與來源。

**播出鏡面：有消化後內容注入，沒有 raw article／獨立 visual context 注入。** 它和一般 CG 共用主流程：`_digestFetch()` 把 `news_text`、`editor_format`、`hole_side` 與 `user_instruction` 送到 `/api/generate`（`app.js:2309-2331`），後端在 `generate()` 以 `news_text` 做消化，產出 `style`／`structure`／`variable`（`main.py:2994-3019`、`main.py:3055-3062`、`main.py:3202-3218`）；前端再把三欄放進 `buildPrompt()`（`app.js:3118-3132`）並只送組好的 `prompt` 到 `/api/images/generate`（`app.js:3138-3165`，人工確認路徑為 `app.js:3248-3287`）。因此它已有「消化結果進生圖」但沒有「原文或另一份場景摘要進生圖」；D22 應沿一般 CG seam 增加一次 bounded `visual_context`，不要重送 raw `news_text`。

### 8.6 與前文衝突及修正

- 原第 1.2 節把工作量寫成「2 個 payload 欄位＋1 個 schema 欄位」、原 5.1 寫「不碰 `tenCoverFields()`／`ytCoverFields()`／`vstripFields()`」，原第 6 節第 4 項建議只做一般 CG。三處都與第 7 節裁決 4 衝突，已在本次盤點直接修正為全部有生圖語意的路徑，並把封面 seam 明定在既有畫面推導層。
- 原第 3.3 節寫「一般 CG 網頁的兩個 payload 才送」，也已修正為一般 CG／播出鏡面與封面 payload 可帶；B55 `titlelayer`、refine、disclaimer render 仍硬隔離。

### 8.7 新待裁項

1. **`yt_vstrip` 的「全部版型都開」如何解讀。** 現行直標是透明 overlay，沒有 image provider、背景或 visual prompt，`visual_context` 沒有可消費之處。建議把裁決解讀為「所有會生背景圖的版型都開；`yt_vstrip` 保持純 compose，原文仍只用於既有標題／來源消化」，並在驗收矩陣標成 `N/A（無生圖模型）`。若要求 `visual_context` 必須對直標產生可見效果，就只能新增背景生圖或改變可讀文字，兩者都是新的產品功能與明顯擴案，不應混入 `D22-PR1`。
