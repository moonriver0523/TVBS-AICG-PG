# TVBS-AICG-PG

新聞 CG Prompt 生成器 — TVBS 國際新聞內部工具，輸入少數變量，依標準化模板自動生成新聞資訊圖表的 AI Prompt（Gemini / GPT 通用）。

## 開發前必讀

**`docs/HANDOFF.md`** — 完整技術交接文件：架構說明、目前進度、待辦事項。開新對話接手開發前，先看這份。

`docs/notion-integration-plan.md` — 未來若要接 Notion 資料庫做即時同步的規劃書。

## 檔案說明

- `index.html` — 前端介面結構與樣式（Tailwind CDN）
- `app.js` — 前端資料模型（四大圖表類型的風格/構圖/變量模板）與核心邏輯
- `main.py` — 後端代理伺服器：轉發「AI 消化」功能的 Claude API 呼叫，API key 存於後端 `.env`，不曝露在瀏覽器
- `docs/` — 技術文件

## 快速開始

1. 啟動後端（AI 消化功能需要）：
   ```
   uv run uvicorn main:app --host 127.0.0.1 --port 8787
   ```
2. 用瀏覽器開啟 `index.html`

## 目前版本

V8.2 — 詳見 `docs/HANDOFF.md` 第七節「已收錄的模板現況」
