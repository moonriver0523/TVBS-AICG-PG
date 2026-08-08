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

- [ ] 補一則稿件內容供覆盤（若使用者記得或截圖還在）
- [ ] 評估是否要在 `main.py` 生圖失敗時，額外記錄（僅本機、不外流）當次 prompt 摘要，
      方便未來同類案例排查，同時要顧到暫存內容的保留期限與個資規範（見 TODO.md
      「暫存的照片是個人資料」同一原則）
- [ ] 若後續能重現，補充是哪類生物新聞（例如疫情/病毒/動物解剖圖等）觸發，
      納入主管報告的「已知限制」一欄

**Why 值得記錄：** OpenAI 安全系統的拒絕沒有明確分類原因，目前是黑盒；
若未來要跟主管報告 LINE 版限制，這類「送出去但被上游安全系統擋下、非我方可控」
的失敗需要單獨列出，避免被誤認為系統本身的錯誤。
