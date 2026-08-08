# 2026-08-08 LINE 版：生物相關新聞圖表遭 OpenAI 安全系統擋下

## 事發經過

LINE 版測試環境重啟後（`dev-line.sh` 隧道 + 後端），使用者透過 LINE 官方帳號貼一則
**跟生物有關的新聞**要求生成圖表，webhook 正常收到（`POST /line/webhook` 200 OK），
但送圖片生成 API 時被 OpenAI 安全系統擋下，未產出圖片。

## 錯誤訊息

```
[OpenRouter image HTTPError] 400: {"error":{"message":"Your request was rejected by the
safety system. If you believe this is an error, contact us at help.openai.com and include
the request ID req_a7f2bd8330074ab7b3dc0f35146dc35c.","code":400,"metadata":{"provider_name":"OpenAI"}}}
```

- Request ID：`req_a7f2bd8330074ab7b3dc0f35146dc35c`
- 來源：`main.py` `generate_image_raw()` 的 `HTTPError` 分支（`main.py:1058`）
- 對應提供商：OpenAI（經 OpenRouter 轉發）

## 已排除的環節

- Webhook 連線、隧道、後端本身皆正常（同一輪 log 前後都是 200 OK）
- 不是尺寸/比例類問題（`assert_aspect_ratio_supported` 沒有觸發）
- 是 OpenAI 生圖端「內容安全」判定拒絕，非額度或金鑰問題

## 尚未查明

- **實際送出的新聞內容/生成 prompt 未記錄在後端 log**——`line_bot.py` 與 `main.py`
  目前的 print 只記錄錯誤本身，不記錄稿件原文或組出的 prompt，因此無法從 log
  回溯是哪個詞彙（人名／物種／醫療用詞／圖像描述等）觸發安全過濾。
- 若要精確歸因，需要使用者回憶或提供當時貼的新聞稿全文/截圖。

## 待辦

- [x] **2026-08-08 已修復**：`request_log.py` 新增 `log_failure()`，`main.py` 的
      `generate_news_image()` 在 `generate_image()` 失敗時會連同新聞原文、消化結果、
      最終 prompt、錯誤訊息一起記到 `logs/generations-*.jsonl`（`ok: false`），
      同一批文字保留期限（預設 14 天，`REQUEST_LOG_RETENTION_DAYS` 可調）。
      同時把 `static/generated/` 的圖片保留期從 24 小時延長到 7 天
      （`line_bot.py` 的 `KEEP_FILES_HOURS`），事故後有更多時間回查。
      往後同類案例可直接查當天的 JSONL，不必再靠使用者回憶原文。
- [ ] 補一則稿件內容供覆盤（若使用者記得或截圖還在）——本次事發早於上述修復，
      log 裡沒有這筆的原文
- [ ] 若後續能重現，補充是哪類生物新聞（例如疫情/病毒/動物解剖圖等）觸發，
      納入主管報告的「已知限制」一欄

**Why 值得記錄：** OpenAI 安全系統的拒絕沒有明確分類原因，目前是黑盒；
若未來要跟主管報告 LINE 版限制，這類「送出去但被上游安全系統擋下、非我方可控」
的失敗需要單獨列出，避免被誤認為系統本身的錯誤。
