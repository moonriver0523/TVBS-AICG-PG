# LINE Bot 設定與測試（最小原型）

使用者在 LINE 貼一段新聞文字 → AI 消化 → 生圖 → Bot 回貼圖片。
流程與網頁版第一頁相同，差別在完全跑在後端。

## 一、建立 LINE channel（只需做一次）

1. 到 [LINE Developers Console](https://developers.line.biz/console/) 用 LINE 帳號登入
2. 建立 **Provider**（例如 `TVBS`）
3. 在該 Provider 下建立 **Messaging API channel**
4. 取得兩個值：
   - **Channel secret**：Basic settings 分頁
   - **Channel access token (long-lived)**：Messaging API 分頁最下方，按 Issue
5. 同一頁把 **Auto-reply messages** 關掉（否則官方帳號會自動回罐頭訊息蓋掉 Bot 的回覆）

把兩個值填進 `.env`（此檔已被 gitignore，不會進版控）：

```
LINE_CHANNEL_SECRET=你的 channel secret
LINE_CHANNEL_ACCESS_TOKEN=你的 access token
```

> Token 請自己在編輯器裡貼上，不要貼進對話。

## 二、啟動測試環境

```bash
./dev-line.sh
```

腳本會依序：清掉 8787 殘留 → 開 cloudflared 隧道 → 把隧道網址寫回 `.env` 的
`PUBLIC_BASE_URL` → 啟動後端 → 印出 Webhook URL。

順序不能顛倒：後端在啟動時載入 `.env`，先啟動就讀不到這次的隧道網址。

## 三、設定 Webhook

把腳本印出的網址貼到 Console 的 **Messaging API → Webhook URL**：

```
https://xxxx.trycloudflare.com/line/webhook
```

按 **Verify**，應顯示 Success，並把 **Use webhook** 打開。

⚠️ cloudflared 快速隧道每次重開網址都會變，要重貼一次。

## 四、測試

用手機 LINE 掃 Console 上的 QR code 加好友，貼一段新聞文字給它。
預期：先秒回「收到！AI 消化與生圖中…」，30–120 秒後回傳圖片。

## 設計上的取捨（LINE 平台限制造成）

| 限制 | 因應 |
|---|---|
| 圖片訊息只吃公開 HTTPS 網址，不收 base64 | 生成後存 `static/generated/`，經隧道對外 |
| `previewImageUrl` 上限 1 MB，原圖常 1–2 MB | 另存 480px 寬的 JPEG 縮圖 |
| replyToken 時效約 30 秒 ≪ 生圖 30–120 秒 | 先 `reply` 秒回收到（免費），完成後改 `push` |
| Webhook 逾時會重送 | 一律先回 200，實際工作丟背景任務 |

**費用**：Messaging API 本身免費，`reply` 不限量；`push` 計入官方帳號月免費額度
（一般免費方案約 200 則／月）。自己測試用量很小。

## 目前的原型限制

- 角色固定「記者」；圖表類型由 AI 自動判斷
- 文字密度預設「簡化」（手機上好讀），要改回標準版就把 `.env` 的
  `LINE_DIGEST_DENSITY` 設成 `standard` 並重啟後端
- 背景任務跑在同一個 uvicorn 行程，沒有佇列——多人同時下指令會排隊變慢
- `static/generated/` 的圖超過 24 小時會在下次請求時自動清掉
- 沒有重複訊息去重：LINE 重送時可能重複生成

## 已知的技術債

`news_prompt.py` 的規則字串是從前端 `app.js` 移植的**第二份來源**。
改任一邊都必須同步另一邊，否則 LINE 出的圖會與網頁版不一致。
（目前有測試以位元組比對兩者輸出，不同步會被測出來。）
