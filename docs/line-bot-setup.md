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

- 角色預設「記者」。訊息開頭寫 `編輯`／`編輯：`，或獨立一行 `指示: 編輯`，才走編輯規則（兩行標題、蓋章、標準密度）。只傳「編輯」兩字會記住角色、不生圖；之後貼稿沿用。圖表類型由 AI 自動判斷
- 記者的文字密度預設「簡化」（手機上好讀），要改回標準版就把 `.env` 的
  `LINE_DIGEST_DENSITY` 設成 `standard` 並重啟後端。編輯固定標準密度
- 安全框與記者同一套官方置框（預設開）
- 背景任務跑在同一個 uvicorn 行程，沒有佇列——多人同時下指令會排隊變慢
- `static/generated/` 的圖超過 7 天會在下次請求時自動清掉（2026-08-08 由 24 小時延長）
- 沒有重複訊息去重：LINE 重送時可能重複生成

## 永久化方案（2026-07-29 決議：demo 後執行）

現況痛點有兩個，常被混為一談：

1. **重開網址就變** —— cloudflared 快速隧道每次隨機給網址，得回 LINE Console 重貼
2. **依賴筆電開著** —— 後端跑本機，闔蓋／斷網就死；這才是 5–15 人內測的真正阻礙

原本打算用 cloudflared **具名隧道**取得固定網址，但查過帳號後發現
**Cloudflare 上沒有任何網域**（具名隧道要綁 DNS，需要一個託管在 Cloudflare 的 zone），
此路不通，且它也只解決問題 1。

**改採雲端部署（Render 免費層）**：平台本身就配固定子網域（`xxx.onrender.com`），
不必買網域，且一併解決問題 2。免費層閒置會休眠、冷啟動 30–60 秒；
首次 webhook 可能逾時但 LINE 會重送，且生圖本來就要 30–120 秒，影響有限。

**執行前必須先確認**：公司是否允許把 `OPENROUTER_API_KEY` 與 LINE token 放到外部雲端平台。
本 repo 含電視台內部 prompt 資產（已轉 Private），這一步不該逕行決定；
另一個專案（TVBS-Aigent-Fable）已訂下「測試期雲端、正式期搬公司內網 NAS」，可沿用同一原則。

## 已知的技術債

`news_prompt.py` 的規則字串是從前端 `app.js` 移植的**第二份來源**。
改任一邊都必須同步另一邊，否則 LINE 出的圖會與網頁版不一致。
（目前有測試以位元組比對兩者輸出，不同步會被測出來。）
