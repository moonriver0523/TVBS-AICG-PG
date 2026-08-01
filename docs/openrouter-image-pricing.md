# OpenRouter 圖片模型費用速查

> 建立：2026-07-22 ｜ 資料來源：OpenRouter `/api/v1/images/models` + 各模型 `/endpoints`
> 用途：AICG 生成器選圖片模型時的費用參考。**價格會變動，最新價請用文末指令重查。**

## ⚠️ 先讀：計價方式的坑

- **多數模型按 token 計費，不是每張固定價** → 實際費用會隨「解析度 / 品質」大幅浮動。
- **GPT 系列高品質最容易爆量**：實測 `gpt-image-1` 一張 **US$0.262**，是 `gemini-2.5-flash-image`（$0.039）的 **6.7 倍**。品質調低可省很多。
- **固定價模型最好抓預算**：Seedream、Recraft、Grok 一張就是一張。

## 費用表（2026-07-22 抓取）

| 模型 | 官方費率 | 一張 16:9 估算/實測 | 備註 |
|---|---|---|---|
| `google/gemini-3-pro-image` ⭐專案指定 | $0.00012/token | 約 **$0.13–0.15**（2K 更高） | 中文通常最穩，尚未實測 |
| `google/gemini-3.1-flash-image` | $0.00006/token | 約 $0.08 | 3.1 版 flash |
| `google/gemini-2.5-flash-image` | $0.00003/token | **實測 $0.039** ✅ | 中文標題會亂碼、內文變英文 |
| `openai/gpt-image-2` ⭐專案指定（2026-08-01 起） | $0.00003/token | 約 $0.04–0.26（看品質） | **OpenAI 家族唯一支援 21:9** |
| `openai/gpt-image-1` | $0.00004/token | **實測 $0.262** ⚠️ | 中文九成正確，但高品質很貴；只有 1:1/3:2/2:3 |
| `openai/gpt-5-image` | $0.00004/token | 約 $0.05–0.26 | 無 `aspect_ratio` 參數 |
| `openai/gpt-5.4-image-2` | $0.00003/token | 約 $0.04–0.20 | 無 `aspect_ratio` 參數；2026-08-01 前誤當預設，已改掉 |
| `bytedance-seed/seedream-4.5` | **固定 $0.04/張** | **實測 $0.040** ✅ | 標題 3D 最美，但會把排版指令/簡體字畫進圖，最不可控。最低要 2560x1440 |
| `black-forest-labs/flux.2-pro` | **$0.03/百萬畫素** | 2K≈$0.11、4K≈$0.25 | |
| `microsoft/mai-image-2.5` | $0.000047/token | 約 $0.06 | 微軟 |
| `x-ai/grok-imagine-image-quality` | **固定 $0.07/張** | $0.07 | xAI Grok |
| `recraft/recraft-v4.1` | **固定 $0.035/張** | $0.035 | Recraft，另有向量/SVG 版本 |

> token 估算基準：1K 16:9 圖 ≈ 1290 output tokens。GPT 高品質實際 token 遠高於此，故估算偏低，以實測為準。

## 中文新聞圖表實測結論（2026-07-22）

同一份「資料圖表（記者版）關稅」提示詞測三個模型：

| 模型 | 中文字 | 指令外洩 | 成本 | 可用度 |
|---|---|---|---|---|
| gemini-2.5-flash-image | ❌ 標題全亂碼、內文變英文 | 無 | $0.039 | 低 |
| gpt-image-1 | ✅ 九成正確（少數錯字如「關→國」） | 無 | $0.262 | 最高（但貴） |
| seedream-4.5 | 標題最美但混簡體 | ❌ 嚴重把 px 指令畫進圖 | $0.040 | 低（不可控） |

- **尚未實測專案指定的 `gemini-3-pro-image` / `gpt-image-2`**（前面誤用了較弱的 flash / v1）。
  → 2026-08-01 補測：`gpt-image-2` 已實跑 2 張，繁中與版面都正確，見下節。
- 決策：**OpenRouter 暫不接進 AICG 生成器**；中文精準度未達「一擊即中、可直接上鏡」標準。
  → 此決策後來已推翻，OpenRouter 現在是預設傳輸層。

## `aspect_ratio` 支援度（2026-08-01 抓取）⚠️ 選模型前必看

**帶了模型不支援的 `aspect_ratio`，OpenRouter 不會報錯也不會警告，就是靜靜忽略。**
2026-08-01 的「附參考圖就掉出 21:9」查了整晚，根因就是預設模型根本沒有這個參數。

| 模型 | 支援的 `aspect_ratio` |
|---|---|
| `openai/gpt-image-2` | 1:1 / 3:2 / 2:3 / 4:3 / 3:4 / 16:9 / 9:16 / **21:9** / auto |
| `openai/gpt-image-1`、`-1-mini` | 1:1 / 3:2 / 2:3 / auto（**沒有 21:9**） |
| `openai/gpt-5-image`、`-mini`、`gpt-5.4-image-2` | **完全沒有這個參數** |
| `google/gemini-2.5-flash-image`、`3-pro-image`(+preview) | 1:1 / 2:3 / 3:2 / 3:4 / 4:3 / 4:5 / 5:4 / 9:16 / 16:9 / **21:9** |
| `google/gemini-3.1-flash-image`、`-lite` | 上列再加 1:4 / 1:8 / 4:1 / 8:1 |
| `black-forest-labs/flux.2-*`、`sourceful/riverflow-v2*` | 含 **21:9**、auto |
| `bytedance-seed/seedream-4.5`、`x-ai/grok-imagine-*` | 含 21:9（Seedream 另有 19.5:9、20:9） |
| `recraft/*`、`krea/*`、`microsoft/mai-image-2.5*` | **沒有 21:9**（最寬只到 16:9） |

程式端已把這張表釘進 `main.MODEL_ASPECT_RATIOS`，做不到的比例直接回 400；
新增模型時記得一起補表（表上沒有的只警告不擋）。重查指令見文末。

## 這把 key 可用的圖片模型（共 43 個，2026-07-22）

Google（Gemini 2.5/3-pro/3.1 flash 系列）、OpenAI（gpt-image-1/2、gpt-5-image、gpt-5.4-image-2、mini）、
ByteDance Seedream 4.5、Black Forest Labs Flux 2（flex/klein/pro/max）、Microsoft MAI 2.5、
xAI Grok Imagine、Recraft v3/v4/v4.1（含向量 vector 版）、Sourceful Riverflow v2/v2.5、Krea 2、openrouter/auto。

## 日後自己重查最新價（指令）

```bash
KEY="$OPENROUTER_API_KEY"   # 或直接貼 key
# 1. 列出所有圖片模型
curl -s https://openrouter.ai/api/v1/images/models -H "Authorization: Bearer $KEY" | python3 -m json.tool
# 2. 查單一模型費率（pricing 陣列，看 billable=output_image 的 cost_usd）
curl -s https://openrouter.ai/api/v1/images/models/google/gemini-3-pro-image/endpoints \
  -H "Authorization: Bearer $KEY" | python3 -m json.tool
```

- 費率欄位在各模型 `/endpoints` → `endpoints[].pricing[]`，`billable`=`output_image`、`unit`=`token`、`cost_usd`=每 token 單價。
- 固定價模型的 `unit` 會是 `image`（例：Seedream $0.04/張）。

## 生成 API 用法備忘

```
POST https://openrouter.ai/api/v1/images
Headers: Authorization: Bearer <KEY> ; Content-Type: application/json
Body:   {"model":"...", "prompt":"...", "aspect_ratio":"16:9", "resolution":"1K"}
回傳:   data[0].b64_json (base64) + media_type ; usage.cost = 這次實際花費(US$)
```

- 圖片以 base64 回傳，成功才收費、失敗不收。
- Seedream 有最低畫素限制（≥3,686,400 px），要改用 `"size":"2560x1440"`，`resolution:1K` 會被擋。
