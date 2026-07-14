# TVBS-AICG-PG

新聞 CG Prompt 生成器 — TVBS 國際新聞內部工具，輸入少數變量，依標準化模板自動生成新聞資訊圖表的 AI Prompt（Gemini / GPT 通用）。

## 開發前必讀

**`docs/HANDOFF.md`** — 完整技術交接文件：架構說明、目前進度、待辦事項。開新對話接手開發前，先看這份。

`docs/notion-integration-plan.md` — 未來若要接 Notion 資料庫做即時同步的規劃書。

## 檔案說明

- `index.html` — 前端介面結構與樣式（Tailwind CDN）
- `app.js` — 前端資料模型（四大圖表類型的風格/構圖/變量模板）與核心邏輯
- `main.py` — 後端代理伺服器：轉發「AI 消化」與圖片生成 API 呼叫，API key 存於後端 `.env`，不曝露在瀏覽器
- `docs/` — 技術文件

## 快速開始

1. 啟動後端（AI 消化功能需要）：
   ```
   uv run uvicorn main:app --host 127.0.0.1 --port 8787
   ```
2. 用瀏覽器開啟 `index.html`

## AI 自動消化

「AI 自動消化整理」透過 OpenAI Responses API 產生風格、構圖與內容欄位。請在本機 `.env` 設定：

```
OPENAI_API_KEY=your_api_key
# 可選：預設為 gpt-5.6-terra
OPENAI_DIGEST_MODEL=gpt-5.6-terra
```

OpenAI API 的計費獨立於 ChatGPT 訂閱，依 API 用量計費。

### 文字密度與工作角色

AI 自動消化有兩個獨立設定：

- 工作角色：`記者`／`編輯`
- 文字密度：`標準`／`簡化`

`標準`維持既有整理規則；`簡化`會依素材只保留 1～3 個重點，並在單一主視覺、大數字／結論、主題大圖三種聚焦方式中選擇最適合的呈現。文字密度只影響 AI 自動消化，不會刪減手動輸入內容。

## 圖片生成（Gemini / GPT）

前端確認最終 Prompt 後，可依右上角選擇的 Gemini／GPT 引擎，透過後端一鍵生成 16:9／1K 圖片。請在本機 `.env` 設定：

```
GEMINI_API_KEY=your_api_key
# 可選：預設為 Nano Banana Pro
GEMINI_IMAGE_MODEL=gemini-3-pro-image

# GPT 圖片沿用上方 OPENAI_API_KEY
# 可選：預設為 gpt-image-2
OPENAI_IMAGE_MODEL=gpt-image-2
# 可選：low / medium / high / auto，預設 medium
OPENAI_IMAGE_QUALITY=medium
```

Gemini 使用原生 `1K` 設定；GPT 使用符合模型限制的 16:9 最小尺寸 1280×720 PNG。金鑰僅由 `main.py` 讀取，絕不放入前端程式碼。

## 目前版本

V8.2 — 詳見 `docs/HANDOFF.md` 第七節「已收錄的模板現況」
