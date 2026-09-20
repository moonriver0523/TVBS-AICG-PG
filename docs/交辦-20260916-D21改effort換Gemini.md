# 交辦：D21 插隊動刀——消化改送 `reasoning.effort`，主模型換 gemini-3.8-flash

**2026-09-16 使用者裁定：這一波動刀插隊，優先做這個。**

## 為什麼要改（實測依據，不要再重測）

四輪實測（各 10 次，同稿同參數，明細在 `D:\Downloads\AICG\後台紀錄\20260916\`）：

| 設定 | 成功 | 截斷 | 耗時平均 | 最壞 | maximum 檔 | 簡體 |
|---|---|---|---|---|---|---|
| sonnet-5 ＋ `max_tokens=2000`（**現況**） | 5/10 | 3 | 131 秒 | 201 秒 | — | 2/10 |
| sonnet-5 ＋ `effort=low` | 7/10 | 0 | 18 秒 | 27 秒 | 2/5 | 0/10 |
| **gemini-3.8-flash ＋ `effort=low`** | **9/10** | 0 | **6 秒** | 12 秒 | **5/5** | 0/10 |
| gpt-5.6-luna ＋ `effort=low` | 6/10 | 4 | 46 秒 | 107 秒 | 4/5 | 0/10 |

**根因**：`reasoning.max_tokens` 被 Sonnet 5 官方明說會忽略，所以現行的思考封頂
從來沒生效過；`reasoning.effort` 則確實被遵守（實測 reasoning_tokens 從
4005–11999 掉到 0–842）。

第二輪 gemini 用 **10 則不同的真實稿**（211–2,330 字）再驗一次：9/10、4–8 秒、
**耗時對稿長不敏感**、簡體 0/10。

## 要改的東西（範圍已盤點過，不要擴大）

1. **`digest_reasoning_body()`（`main.py:243`）**：改送 `{"reasoning": {"effort": ...}}`。
   - effort 值要能用環境變數設定（例 `DIGEST_REASONING_EFFORT`），**預設 `low`**。
   - 設成空字串／`off` 之類時＝完全不送 reasoning 欄位（保留退路）。
   - `DIGEST_REASONING_MAX_TOKENS`／`DIGEST_REASONING_MIN_TOKENS`／`DIGEST_REASONING_HEADROOM`
     這三個常數怎麼處理由你判斷，但**不要靜默留著一段永遠不會執行的死碼**；
     若決定保留，要在註解寫明為什麼。
2. **`main.py:234` 的註解**：現在寫著「OpenAI 系走 effort，這裡不送」，**這句是錯的**
   ——實查 OpenRouter，`anthropic/claude-sonnet-5` 的五個端點全部 `reasoning=True`。
   **這個錯誤註解就是這條路整整沒被嘗試過的原因**，務必改掉並註明實測依據。
3. **`DIGEST_PROVIDER_ORDER`（`main.py:268`）**：現值
   `anthropic,claude-on-aws,azure/global,amazon-bedrock/global` **全是 Anthropic 家族**，
   換模型後完全不適用。
   - 改成送 **`provider.require_parameters: true`**（讓 OpenRouter 只挑真的吃得下
     本次參數的端點），而不是換一份寫死的 Google 白名單。
   - **這同時解掉帳本 B74**（白名單裡的 `azure/global`、`amazon-bedrock/global`
     兩個端點其實不支援 `structured_outputs`，過載 fallback 過去時 strict schema
     會被靜默丟棄）。
   - **已實測**：20 次呼叫送 `require_parameters: true` 全部順利路由，
     沒有出現「無 provider 可用」，這是它唯一的疑慮，已排除。
   - `allow_fallbacks` 維持 `true`。
4. **主模型**：`DEFAULT_DIGEST_MODEL`（`main.py:126`）與 `.env` 的 `DIGEST_MODEL`
   換成 `google/gemini-3.8-flash`。
   - ⚠ **必須保留用環境變數退回 Claude 的能力**，而且退回時不用改程式碼。
     這是換主模型，影響整站，出事要能三分鐘內回退。
   - `resolve_digest_model()` 的既有邏輯（帶 `/` 的 slug 只在 client 真的指向
     openrouter 時才採用，見 `main.py:153` 的註解）**不要破壞**，那是 2026-09-13
     的事故修正。

## 絕對禁令

- **不准動 prompt**（凍結快照）。`news_prompt.py` 的規則常數、
  `tests/test_reporter_prompt_frozen.py` 管理的 fixture、任何 rng_pins 檔案，一律不准改。
- **不准打任何付費 API**。全部用 mock。
- **不准 commit、不准 push。**
- **不准順手改其他缺陷**（B57 塊數防呆、B71 簡體字、B70 標籤都不在本次範圍）。
- 做不到或會違反上述任何一條就**停手回報**，不要自己找變通。

## 測試

- `tests/test_generate_retry.py::DefaultReasoningPayloadBaselineTests` **就是為了這次改動而釘的**
  （不 patch 環境變數、用字面值釘住現在送出的 `reasoning: {"max_tokens": 2000}`）。
  它**會轉紅，這是預期內的**——請把它更新成釘住新的 payload，
  並在註解寫明「2026-09-16 從 max_tokens 改為 effort，依據 D21 四輪實測」。
- `tests/test_digest_provider_routing_20260911.py` 釘著舊的 provider order，會受影響，一併更新。
- **新增測試**：①送出的 payload 真的帶 `reasoning.effort`；
  ②`DIGEST_REASONING_EFFORT` 的環境變數覆寫有效（含「不送」那條路）；
  ③provider body 真的帶 `require_parameters: true`；
  ④用環境變數退回 Claude 時，模型與 provider 設定都正確。
- 驗收：`.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q` **全綠**
  （目前基準是 1963 題 OK／expected failures=1，那 1 個 expectedFailure 是 B71 的，不要動它）。

## 回報

①改了哪些檔案、每處為什麼這樣改；②新舊 payload 的實際差異（貼出來）；
③測試結果；④**你認為有風險但沒動的地方**。
