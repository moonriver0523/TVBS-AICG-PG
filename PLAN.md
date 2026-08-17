# TVBS AICG — 三項功能規劃書

> 給接手實作的 agent。撰寫於 2026-08-17，對應 commit `b7592c3`。
> 三個項目彼此獨立，可分開做、分開部署。**建議順序：③ → ① → ②**（理由見文末）。

---

## 0. 先讀這段：不做會出事的共通規則

### 0.1 記者版一個字都不能動

編輯與記者共用大量 prompt 常數，改一邊很容易誤傷另一邊，而且**誤傷不會有任何執行期錯誤**——只會讓記者悄悄出不一樣的圖。

`tests/test_reporter_prompt_frozen.py` 把改動前的記者 prompt 原文存成 fixture 逐字比對（消化 4 種組合 + 生圖 2 種）。**這條紅了就是誤傷，去改程式，不要改 fixture。** 真的要動記者 prompt 時，才連同 fixture 一起更新，並在 commit 訊息說明。

### 0.2 prompt 規則有兩份來源，必須同步

`news_prompt.py`（LINE Bot 用，後端組）與 `app.js`（網頁版用，前端組）是同一套規則的兩個實作。只改一邊不會報錯，只會讓兩條路徑出不一樣的圖。

`tests/test_prompt_parity.py` 會逐字比對這些常數。新增 prompt 常數時，**兩邊都要加，並在 parity 測試註冊**。

### 0.3 網頁版改動要進 cache-buster

`index.html` 的 `<script src="app.js?v=YYYYMMDDx">`。改了 `app.js` 就要往前跳一個字母，**不要重用舊字串**（舊字串可能還在使用者瀏覽器快取裡）。

### 0.4 生圖要花錢

每次生圖都是真實付費呼叫。驗證新功能時：

- 能用幾何／既有成品算出來的，就不要生圖（很多問題可以純數學驗證）
- 需要生圖時，**先跟使用者說明要生幾張、為什麼**，取得同意再跑
- 測試一律 mock 掉生圖呼叫（見 `tests/test_line_bot.py` 開頭的說明）

### 0.5 部署

```powershell
$g = "C:\Users\User\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
& $g run deploy tvbs-aicg-linebot --source . --region asia-east1 `
    --project tvbs-aicg-linebot --allow-unauthenticated --quiet
```

改環境變數用 `--update-secrets`（合併），**不要用 `--set-secrets`**（會整組覆蓋、洗掉其他設定）。

### 0.6 跑測試

沒有 pytest。有幾支測試會打真實 API，日常請跳過：

```powershell
$t = (Get-ChildItem tests\test_*.py |
      Where-Object { $_.Name -notmatch 'quality|real_world|map_accuracy|guide_experiment|content_fidelity' } |
      ForEach-Object { "tests." + $_.BaseName })
uv run python -m unittest @t
uv run ruff check .
```

---

## 1. 現況速查（已驗證，2026-08-17）

### 端點

| 路徑 | 用途 | 呼叫者 |
|---|---|---|
| `/api/generate` | 新聞消化（回 style/structure/variable） | 網頁版第一、二頁 |
| `/api/images/generate` | 純生圖（吃現成 prompt） | 網頁版 |
| `/api/news-image/generate` | 消化＋生圖一次到位 | LINE Bot、WorkCord |
| `/api/hybrid/digest` | 第三頁混合版型 | hybrid |

全部有 `verify_internal_api_key` 保護。

### 關鍵符號

| 位置 | 說明 |
|---|---|
| `main.py:140` `ImageGenerateRequest` | 含 `reference_image_data_url: str = ""` |
| `main.py:156` `ImageGenerateResponse` | **只有** `image_data_base64` / `mime_type` / `model` |
| `main.py:366` USER INSTRUCTIONS 區塊 | 7 條規則，教消化模型從文章裡辨識使用者指令 |
| `main.py:377` `build_digest_instructions()` | 組消化指令，role/density/type_label/full_bleed 分流 |
| `main.py:954` `supports_reference_image()` | 判斷這次後端送不送得出參考圖 |
| `main.py:1050` `generate_image_raw()` | 依 `IMAGE_BACKEND` 分派到 openrouter／native |
| `main.py:1104` `generate_via_openrouter()` | 參考圖走 `input_references`（**目前寫死只送一張**） |
| `main.py:1193` `generate_gpt_image()` | 原生 OpenAI 路徑，**沒有參考圖通道** |
| `main.py:1406` `resolve_portrait()` | 具名真人時自動查照片，佔用參考圖欄位 |
| `main.py:1469` `generate_news_image()` | 消化＋生圖＋置框的主流程 |
| `app.js:855` `buildPrompt()` | 網頁版組 prompt |
| `app.js:1171` `handleOneClickGenerate()` | 第一頁一鍵生成 |
| `safe_frame.py` | 生成後置框；編輯走純水平拉伸 |

### 生圖後端

**預設走 OpenRouter**（`IMAGE_BACKEND` 未設 = `openrouter`）。模型能力已向 `/api/v1/images/models` 查證：

| 模型 | aspect_ratio | input_references |
|---|---|---|
| `openai/gpt-image-2` | 1:1, 3:2, 2:3, 4:3, 3:4, 16:9, 9:16, 21:9, auto | **0–16 張** |
| `google/gemini-3-pro-image` | 上述再加 4:5, 5:4 | 0–14 張 |

⚠️ **OpenRouter 對不支援的參數不報錯，直接忽略。** 2026-08-01 曾因此讓 21:9 靜靜降級成 3:2，查了整晚。加新參數前先查 models 端點確認模型真的吃。

⚠️ 沒有任何模型支援自由像素尺寸（`size`／`width`／`height`）。網路文章講的 OpenRouter `size` 參數在這些模型的宣告裡不存在。

### 編輯版目前的成圖流程

```
prompt（EDITOR_FULL_BLEED_RULES：要求上下留背景帶）
  → gpt-image-2 生 16:9（1536×864）
  → safe_frame 不等比水平拉伸 +6.4%
  → 輸出 1748×924（＝對位框內緣，無畫布、無留白、零裁切）
```

記者版不同：21:9 生成 → FIT 置入 1920×1080 畫布 → 四周補 backdrop。**兩條路不要混談。**

---

## ③ 追加指令修改既有圖（建議先做）

### 目標

使用者看到成品不滿意，輸入「把標題改成紅色」「左邊那張圖換成長條圖」之類的指令，就地修改，不用整張重生。

### 為什麼優先

現在唯一的補救是「改文章再生一次」，等於重跑消化、版面全部重骰，連原本滿意的部分都會變。這是目前最痛的點。

### 可行性

- `gpt-image-2` 支援拿圖當輸入來改圖（`input_references` 0–16）
- 通道已存在：`ImageGenerateRequest.reference_image_data_url` → `generate_via_openrouter()` 的 `input_references`
- **缺的是狀態**：目前整條流程無狀態，每次生成都從新聞原文重跑消化，沒有「上一張圖」的概念

### ⚠️ 必須先修的坑：失真疊加

**這是本項目最重要的一段，不修會出事。**

安全框拉伸發生在生圖**之後**，而回傳給前端的 `image_data_base64` 是**已經拉伸過**的 1748×924。若把它餵回去當參考圖，改完再拉伸一次：

```
6.4% → 13.2% → 20.5% …
```

而且**很難察覺**——每次只多一點，等到看得出來時已經改過好幾輪。

**修法**：讓 `ImageGenerateResponse`／`NewsImageGenerateResponse` 額外回傳拉伸前的原圖，例如：

```python
class ImageGenerateResponse(BaseModel):
    image_data_base64: str        # 給人看的成品（已置框／拉伸）
    mime_type: str
    model: str
    source_image_base64: str = "" # 置框前的原始生成圖，供再編輯用
```

修改流程一律送 `source_image_base64`，成品只拿來顯示與下載。

> 欄位命名可自行決定，但**必須在 docstring 寫清楚兩者差別**，否則下一個人一定會拿錯。

### 實作項目

1. **後端回傳原圖**（如上）。`generate_image()`（`main.py:830`）置框前先留一份。
2. **新端點或新參數**：建議 `/api/images/refine`，收 `{source_image_base64, instruction, role, ...}`，跳過消化，直接組一個「以附圖為基礎，依指令修改」的 prompt。
   - 不要重用 `/api/images/generate` 硬塞——那條的語意是「從 prompt 生成」，混進去之後兩種行為會在同一個函式裡打架。
3. **改圖專用 prompt**：明確告訴模型「附圖是你上次的成品，只改指定的部分，其餘保持不變」。這段一樣要 `news_prompt.py` + `app.js` 兩份同步。
4. **前端**：成品下方加「追加修改」輸入框 + 送出鍵；`state` 留住 `source_image_base64`；每輪修改後更新它（用**新的**置框前原圖，不是成品）。
5. **多輪**：建議保留一個小 stack，讓使用者能退回上一版。

### 驗收標準

- [ ] 連續修改 3 輪後，成品尺寸仍是 1748×924，且與「原圖直接拉伸」逐像素相符（證明沒有二次拉伸）
- [ ] 單元測試：mock 生圖，斷言 refine 路徑送出的 `input_references` 是**置框前**的圖
- [ ] 單元測試：斷言 refine 不會呼叫消化端（省錢也省時間）
- [ ] 記者 frozen 測試仍綠
- [ ] 實際生圖驗證前先向使用者說明張數

---

## ① 使用者指令拆成獨立欄位

### 目標

網頁版把「指令」從新聞原文裡拆出來，獨立一個輸入框。

### 現況與問題

`main.py:366` 那段規則第 1 條要求消化模型自己判斷「哪幾行是指令」，而且明說指令**可能沒有任何標記**（"it may also be plain prose"）。這是分類任務，兩個方向都會錯：

- 指令被當成新聞內容 → 畫進圖裡（違反同段規則第 4 條）
- 新聞句被當成指令 → 內容無聲消失

### 拆欄的真正價值

不是「比較整齊」，是把**規則第 4 條從「靠 prompt 自律」變成「結構上不可能」**。順帶讓這個隱藏功能被看見。

### ⚠️ 埋在文章裡的解析**不可以拿掉**

兩個理由：

1. **LINE 版是聊天框**，沒有 UI 可以拆欄位，只能靠文內解析
2. 有人習慣直接貼完稿並在裡面寫「逐字保留」——那句是 **VERBATIM MODE** 的觸發條件（規則第 5 條）。只認新欄位的話，這些使用者會**無聲失效**，而且他們不會知道為什麼今天開始不逐字了

正解是「多一條高信賴度通道」，不是「換一條」。

### 實作項目

1. `GenerateRequest` / `NewsImageGenerateRequest` 加 `user_instruction: str = ""`
2. `build_digest_instructions()` 在有值時插入一段「以下是使用者指令，它絕對不是新聞內容」，並保留原本的文內解析規則
3. 規則措辭要處理「兩邊都有」的情況：專用欄位優先，文內的仍然要遵守（不要互相取消）
4. 網頁版第一頁 textarea 下方加「給 AI 的指令（選填）」單行／雙行輸入框
5. LINE 不動

### 驗收標準

- [ ] 只填欄位 → 指令生效，且 `variable` 裡不含指令文字
- [ ] 只寫在文章裡 → 行為與現在完全一致（回歸測試）
- [ ] 兩邊都有 → 兩者都被遵守，沒有一方被吃掉
- [ ] 欄位填了「逐字保留」→ VERBATIM MODE 正常觸發
- [ ] 記者 frozen 測試仍綠、parity 測試仍綠

---

## ② 使用者上傳參考圖

### 目標

使用者上傳照片／地圖／實景圖，配合文章一起消化生成。

### 現況

| | |
|---|---|
| 後端參考圖通道 | **已存在**，目前只用於自動查到的人物照 |
| 模型支援 | gpt-image-2 最多 16 張、Gemini 14 張 |
| 前端上傳 UI | **完全沒有**（`index.html`／`app.js`／`hybrid.html` 裡沒有任何 `type="file"`） |

所以後端約 8 成現成、前端 0。

### ⚠️ 真正的難點不是傳檔

**是告訴模型這張圖要拿來幹嘛。** 現在那個欄位的語意寫死是「人臉參考照」，prompt 裡沒有任何一句能處理「這是地圖，請以它為地理依據」。

要引入「參考圖用途」的概念，至少三種，每種一套措辭：

| 用途 | prompt 要說的事 |
|---|---|
| 肖像 | 依附圖的臉生成插畫化人像（現有邏輯） |
| 地圖底稿 | 以附圖的地理關係為準，不得自行改動位置 |
| 實景參考 | 場景、建物、器材的外觀依附圖 |

⚠️ 地圖類另有既有規則 `MAP_ACCURACY_IMAGE_RULES`，要確認不衝突。另可參考記憶：**AI 看圖驗證地理正確性不可靠**，地圖成品的驗收要逐點對照座標，沒把握就標「待人工複核」。

### ⚠️ 與自動肖像查照的衝突

`resolve_portrait()`（`main.py:1406`）在偵測到具名真人時會自動抓照片並佔用參考圖欄位。使用者也上傳圖時要決定優先序，或改成送多張（模型支援，但 `generate_via_openrouter()` 目前**寫死只送一張**，要改成陣列）。

⚠️ 肖像有條鐵律不可放寬：**畫面上有兩位以上具名真人時一律不生成臉孔**（2026-08-05 事故後加的）。多圖支援不得繞過這條。

### 不要另開一頁

流程完全一樣（貼文章 → 生圖），只是多一個選填附件。另開一頁等於把消化＋生圖整條 pipeline 複製一份，之後每次改都要改兩邊，而且切分使用者的心智模型。**第一頁 textarea 下面加一個「附參考圖（選填）」就夠了。**

### 實作項目

1. `generate_via_openrouter()` 的 `input_references` 改成支援多張
2. `ImageGenerateRequest` 的參考圖欄位改成 list，或新增 `reference_images: list[Reference]`，每筆帶 `purpose`
3. 每種 purpose 一套 prompt 片段（兩份來源同步）
4. `resolve_portrait()` 與使用者上傳的優先序
5. 前端：file input → 讀成 data URL → 預覽 → 送出。**限制大小**（LINE 那條有 1MB 限制的前例，網頁版也要擋，否則 base64 塞爆請求）
6. 原生 OpenAI 路徑（`generate_gpt_image()`）沒有參考圖通道——維持 `supports_reference_image()` 的既有處理，不要假裝送得出去

### 驗收標準

- [ ] 上傳一張地圖 + 一篇地理新聞 → 成品的地理關係與附圖一致
- [ ] 未上傳時行為與現在完全一致（回歸測試）
- [ ] 具名真人 + 使用者上傳圖同時存在 → 優先序符合設計，且兩人以上不生成臉孔的鐵律仍成立
- [ ] 超大圖被前端擋下並給明確訊息
- [ ] parity 測試仍綠

---

## 排序理由

| | 效益 | 成本 | 風險 |
|---|---|---|---|
| **③ 追加修改** | 最高——直接解決「不滿意只能整張重來」 | 中 | 低，但**必須先修回傳原圖**，否則失真疊加 |
| **① 指令拆欄** | 中 | 低 | 低 |
| **② 上傳參考圖** | 中高（地圖題材受惠最大） | 中高（要設計用途語意） | 中 |

③ 是唯一能改動「已經生出來的圖」的；①② 都只是讓輸入更精準。

---

## 附錄：這條路上已經試過並淘汰的做法

做編輯版安全框時試過的方案，**不要重蹈**（完整脈絡見 `safe_area_spec.py` 與 `safe_frame.STRETCH_PROFILES` 的註解，以及 git log）：

| 做法 | 淘汰原因 |
|---|---|
| 16:9 內縮框 + backdrop 漸層補左右 53px | 編輯反映裁到對位框後色帶還在，後製難處理 |
| COVER 上下裁 3% | 實測 6 張，模型邊界習慣穩定落在 3%，會削到蓋章橫幅的下緣金框 |
| 逐張偵測純背景再裁 | 有效（失真降到 0.25–1.24%）但使用者要求出圖後不動任何像素 |
| 生 21:9 再置框 | 21:9 是記者的比例；編輯對位框是 1.892，套框後上下反而留 87px |
| 直接生 1.892（2240×1184） | 需要 OpenAI 原生 key，OpenRouter 做不到；使用者決定不申請 |

**prompt 裡永遠不得出現任何比例數字或像素值**——歷史實驗證實模型會把數字當文字畫進圖裡（見 `docs/error-cases/2026-07-23-像素安全框-分析.md`）。
