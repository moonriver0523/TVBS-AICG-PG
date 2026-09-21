# D22 追加評估：生圖端是否接收消化前新聞原文

日期：2026-09-21  
範圍：只評估 D22 與 B70／F43 的整併關係；不實作、不變更既有行為。

## 結論先行

選 **(b) 分開做，但共用 B70／F43 抽出的 seam**。

D22 的接線位置確實與 B70／F43 高度重疊：都是 `ImageGenerateRequest`，也都是 `app.js` 內兩個 `/api/images/generate` request body。以目前程式計，D22 的前端最小接線只是兩個 payload 各加一個欄位，或由一個共用 helper 回傳後在兩處展開；「因為主檔一萬多行，所以不值得碰」已不是成立的主要反對理由。現行 `app.js` 是 **4,006 行**，而且 PR 5 本來就要改同兩個 payload。

但 D22 不應混進 B70／F43 的 PR 2 或 PR 5。標籤案改的是 provenance、標籤 schema、幾何、拖曳與 compose；D22 改的是「哪些新聞內容可進入生圖模型」這個模型信任介面。後者會改 prompt 語意、成本、內容忠實度與 B55 的文字正確性風險，驗收方式也不是標籤測試能涵蓋。把兩者塞在同一 PR，若成品退化，無法判斷是標籤／版面改造還是原文污染 prompt。

建議順序是：先完成 B70／F43 PR 2，再完成 PR 5 並穩定兩個 generate payload；D22 另開 `D22-PR1`，排在 PR 5 後、無須等待移除 legacy 欄位的 PR 6。D22 共用的是已穩定的 `ImageGenerateRequest` request seam、兩個明確的 image payload call site，以及既有 transport／prompt baseline 測試，不共用標籤政策或 renderer。

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

若採前端明送，D22 的最小接線為：

1. `main.ImageGenerateRequest` 新增一個 optional `news_text` 欄位。
2. `handleOneClickGenerate()` 的 image payload 送出該次區域變數 `input`。
3. `handleImageGeneration()` 的 image payload從 `#aiInput` 讀取目前原文；更穩妥的作法是消化成功時把原文與該次 digest 一起保存成明確 state，再由同一個 helper 取值，避免使用者消化後改了輸入框卻未重新消化。
4. 後端新增一個集中式 prompt adapter，把有上限的 context 放入 provider 最終 prompt；不可在 OpenAI／Gemini／OpenRouter 三個 transport 各拼一次。
5. 稽核路徑優先記 `req.news_text`；memo 只保留為舊 caller 的 audit fallback，不能再覆蓋明送值。

所以前端直接改動是 **2 個 payload 欄位**，後端是 **1 個 schema 欄位＋1 個集中式 prompt adapter**。與 disclaimer 是同兩個前端函式，但不是同一個政策函式：`disclaimerPayload()` 管標籤，D22 應另有 `newsContextPayload()`，或在日後真正抽出的 `imageGeneratePayload()` 中成為獨立欄位，不應塞進 `disclaimerPayload()`。

「大檔風險」仍有一小部分成立：兩個 payload 容易只改到一處，且 `handleImageGeneration()` 是消化後人工確認再生圖的另一條路，取哪一版原文有狀態一致性問題。不過 B70／F43 已用「出現次數恰為 2」的 contract test 管同一風險，故風險來源已從「碰大檔」縮小成「兩路 payload 與 digest state 必須一致」。不能再用檔案總行數作為否決 D22 的充分理由。

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

- `ImageGenerateRequest.news_text` 預設空字串。
- 一般 CG 網頁的兩個明確 payload 才送；內部 B55 `titlelayer` request、`ImageRefineRequest`、重貼 disclaimer endpoint 都不繼承。
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
   - 新增 `news_text: str = Field(default="", max_length=20_000)`。
   - 新增 `visual_context: str = Field(default="", max_length=4_000)`，或只收 `news_text` 再由同次 digest response 的欄位傳送；兩者不可含糊地互相覆蓋。建議 canonical 欄位為 `visual_context`，`news_text` 只供 correlation／稽核。
   - `ImageRefineRequest` 維持完全不收這兩個欄位。
2. `app.js`
   - `digestNewsText()`／`_digestFetch()` 保留本次輸入與 digest response 的綁定 state，不能只在生圖當下重讀可能已改過的 textarea。
   - `handleOneClickGenerate()` 與 `handleImageGeneration()` 的兩個 payload 透過同一 `newsContextPayload()` 明送；測試釘出現次數為 2。
   - 不碰 `tenCoverFields()`、`ytCoverFields()`、`vstripFields()`，除非另行裁決封面也納入 D22。
3. `news_prompt.py`
   - 新增純函式 `append_visual_context(prompt, context)`；context 放在清楚的「background only／never render wording」區塊，並由 `ensure_final_image_baseline()` 保證最終硬規則仍在最後且只出現一次。
   - 不修改 `VARIABLE FIELDS`，不把 context 混入 `style`／`structure`，讓既有文字唯一來源仍可測。
4. `main.generate_image_raw()`
   - provider dispatch 前集中呼叫 context adapter，再注入 `FINAL_IMAGE_BASELINE`；OpenRouter、native GPT、Gemini 共用，避免三套漂移。
   - 對 `titlelayer`、refine、disclaimer render 明確不注入。
5. `_enrich_archive_fields()`
   - 明送的 `req.news_text` 優先；只有舊 caller 欄位為空時才用 `_recall_digest()` 補 audit。
   - archive 加 `news_context_mode`（`none`／`visual`／`raw_experiment`）、原文 digest/hash、注入 characters／estimated tokens、是否截斷，才能比較品質與成本。

### 5.2 測試

新增 `tests/test_d22_news_context.py`，至少包含：

- `ImageGenerateRequest` 的 20,000 字 transport 上限與 `visual_context` 4,000 字上限。
- 兩個前端 image payload 都明送，且綁的是完成消化的那一版原文；payload builder 出現次數恰為 2。
- 模擬 textarea 在消化後被改動，未重新消化不得把新稿配給舊 prompt。
- `append_visual_context()` 的空值 no-op、固定截斷、delimiter、不得改 `VARIABLE FIELDS`、`FINAL_IMAGE_BASELINE` 最後且恰一次。
- OpenRouter、native GPT、Gemini 三條 transport 都只收到一次 context；caller request object 不被 mutate。
- `_remember_digest` 中故意放另一稿時，明送 `req.news_text` 仍勝出；未明送的舊 caller 才可用 memo 做 archive fallback，且 memo 永不進模型。
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

4. **涵蓋路徑。**  
   建議第一期只涵蓋一般 CG 的兩個 `/api/images/generate` payload；封面、YT、title-layer、refine、disclaimer render 全排除。封面本已有 `news_text` 用於畫面描述推導，不等於應直接餵給最終生圖模型。

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
- 集中式 prompt adapter 必須涵蓋封面與直標的生圖呼叫路徑，不只 `/api/images/generate` 的兩個 payload。
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
