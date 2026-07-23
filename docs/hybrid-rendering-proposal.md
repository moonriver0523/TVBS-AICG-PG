# AI 視覺素材＋固定版型合成提案

> 狀態：**已批准實作（2026-07-23）**——% 版安全框實驗證實 prompt-only 天花板後獲准。
> 階段0 技術原型已完成並通過 §15 全部驗證項（分支 `feat/hybrid-rendering`，`hybrid.html`/`hybrid.js`）。
> 建立日期：2026-07-15

## 一、目的與核心原則

Gemini／GPT 直接生成完整新聞圖卡時，繁體中文、數字、單位、資料來源與複雜排版仍可能出現錯字、亂碼或資訊偏差。

本提案建議新增「混合版型模式」：

> AI 負責視覺創意，APP 負責資訊正確性。

AI 只生成背景、人物、物件、場景與裝飾素材；所有中文、數字、圖表、單位、資料來源與標籤，由網頁依固定版型繪製。現有完整 AI 生圖功能不移除，未來由使用者依新聞類型選擇模式。

## 二、建議工作流程

```text
新聞原文
  ↓
AI 消化成結構化資料
  ↓
使用者確認內容
  ↓
選擇固定版型
  ↓
AI 生成無文字背景／插圖
  ↓
APP 疊加中文、數字、圖表
  ↓
使用者預覽與修改
  ↓
輸出 1280×720 PNG
```

### 1. AI 消化新聞內容

AI 不直接決定最終像素，而是輸出可驗證的結構化資料：

```json
{
  "title": "美股三大指數收黑",
  "subtitle": "7月14日收盤",
  "items": [
    {
      "label": "道瓊",
      "value": "44,023.29",
      "change": "-0.98%",
      "direction": "down"
    }
  ],
  "source": "資料來源：Reuters",
  "visual_subject": "紐約證交所與下跌的金融市場氣氛"
}
```

使用者確認文字、數字與資料來源後，才進入圖片生成。

### 2. AI 只生成視覺素材

背景 Prompt 應要求：

- 不生成文字、數字、標誌或浮水印
- 只生成背景、人物、物件或主題插圖
- 指定標題區、資料區與底部安全區留白
- 避免高細節出現在文字區域
- 16:9、1K

```text
Generate a text-free broadcast news background.

Subject:
New York Stock Exchange, declining financial market atmosphere,
subtle red downward market graphics.

Layout requirements:
- 16:9, 1K
- No text, numbers, letters, logos or watermarks
- Keep the top 18% visually clean for a headline
- Keep three evenly spaced dark panels in the center
- Keep the bottom 20% completely empty
- Background and lighting only
```

### 3. APP 繪製可信資訊層

APP 負責主標題、次標題、中文內文、數字、百分比、幣別、單位、箭頭、圖表、國旗、標準 ICON、資料來源、安全區、固定配色與字型。中文使用真正的網頁字型，不使用 AI 生成的像素文字。

## 三、版型資料架構

內容、版型與 AI 素材必須分離：

```text
內容 JSON → 放什麼
版型 JSON → 放哪裡
AI 圖片 → 背景長什麼樣
```

```json
{
  "id": "market-three-column",
  "name": "三欄市場比較",
  "canvas": { "width": 1280, "height": 720 },
  "safeArea": { "top": 72, "left": 80, "right": 80, "bottom": 144 },
  "slots": {
    "title": {
      "x": 80,
      "y": 55,
      "width": 1120,
      "maxLines": 2,
      "fontSize": 52
    },
    "cards": { "x": 80, "y": 190, "width": 1120, "columns": 3 },
    "source": { "x": 900, "y": 555, "width": 300, "fontSize": 18 }
  }
}
```

AI 可以建議 `templateId`，但不得自由產生座標，以免版面失去可預測性。

## 四、第一批建議版型

優先製作：

1. 大標題＋三欄比較
2. 大標題＋左右比較
3. 三項／四項長條圖
4. 折線趨勢圖
5. 數字儀表板
6. 三張資訊卡
7. 人物照片＋右側生平
8. 時間軸／事件流程

第一階段暫不優先複雜世界地圖、軍事裝備拆解、自由構圖情境圖及元素高度不固定的海報。

## 五、技術方案

### 第一階段：SVG 固定版型

沿用目前 Vanilla JS＋FastAPI，不立即改成 React。前端以 SVG 建立 1280×720 合成畫布：

```text
Layer 1：AI 背景
Layer 2：遮罩、漸層與資訊面板
Layer 3：圖表
Layer 4：中文與數字
Layer 5：資料來源與安全區檢查
```

SVG 適合精準放置文字、矩形、線條、箭頭與圖表。圖表可考慮 Apache ECharts 的 SVG renderer。

- [W3C SVG 規格](https://www.w3.org/TR/SVG/)
- [Apache ECharts：Canvas 與 SVG renderer](https://echarts.apache.org/handbook/en/best-practices/canvas-vs-svg/)

### 第二階段：可拖拉編輯

若需要拖動文字、縮放圖片、裁切背景、圖層鎖定與復原／重做，再導入 Konva。第一階段不建議直接導入，避免固定版型尚未驗證前增加編輯器複雜度。

- [Konva 高品質圖片輸出](https://new.konvajs.org/docs/data_and_serialization/High-Quality-Export.html)

## 六、建議 UI 模式

### 混合版型模式（建議預設）

AI 生成背景或插圖，APP 繪製文字與圖表，適合資料新聞與大量中文。

### 完整 AI 生圖模式（保留現況）

Gemini／GPT 直接生成完整圖片，適合情境示意、人物插畫、災難場景與少文字視覺；UI 應警告文字與數字可能不準確。

### 純版型模式

不呼叫生圖 API，只使用固定背景、漸層、向量 ICON、圖表與上傳照片；成本最低、速度最快、穩定度最高。

## 七、第一版編輯功能

- 重新生成背景，但保留文字與資料
- 更換版型
- 調整背景亮度、模糊程度與焦點位置
- 調整標題字級與文字顏色
- 顯示／隱藏資料來源
- 上傳自己的照片
- 匯出 PNG

重要原則：重新生成背景不得清除已確認的內容資料。

## 八、自動品質檢查

匯出前檢查：

- 標題是否超過版型行數
- 文字是否超出欄位
- 是否出現簡體中文
- 數字是否缺少單位
- 百分比與正負方向是否一致
- 資料來源是否填寫
- 底部安全區是否有元素
- 文字與背景對比是否足夠
- 畫面是否為 16:9
- 輸出是否為 1K

重大問題禁止匯出；一般問題顯示警告。

## 九、輸出尺寸

最終畫布統一為 `1280×720`、16:9、PNG。GPT 背景使用 1280×720；Gemini 使用 16:9／1K，回傳後裁切或縮放至 1280×720；所有文字與圖表最後在 1280×720 畫布繪製。

## 十、專案保存

除了 PNG，還應保存可再次編輯的專案資料：

```json
{
  "templateId": "market-three-column",
  "provider": "gemini",
  "backgroundImage": "asset-id",
  "content": {},
  "styles": {},
  "version": 1
}
```

第一階段可使用瀏覽器 `localStorage`，並支援下載／載入 JSON 專案檔；資料庫整合留待後續階段。

## 十一、API 建議

現有 `/api/images/generate` 保留給完整 AI 生圖。新增：

```text
POST /api/assets/generate
```

```json
{
  "provider": "gemini",
  "mode": "background",
  "prompt": "...",
  "aspect_ratio": "16:9",
  "image_size": "1K",
  "template_id": "market-three-column"
}
```

MVP 可在瀏覽器完成 SVG 合成與 PNG 匯出，不必立即增加後端 render API。

## 十二、開發階段與工期估算

以下依目前專案架構估算，不含登入、正式雲端部署與資料庫後台。

### 階段 0：技術原型，約 1～2 個工作天

- 一個 1280×720 固定版型
- AI 生成無文字背景
- SVG 疊加標題與三個數字
- 匯出 PNG
- 驗證繁體中文字型與輸出品質

### 階段 1：可使用 MVP，約 5～8 個工作天

- 4～6 種固定版型
- 結構化內容 JSON
- Gemini／GPT 背景生成
- SVG 文字與基本圖表
- 文字溢位檢查
- 1K PNG 匯出
- 背景重新生成
- 本機專案保存

### 階段 2：簡易視覺編輯器，約 5～10 個工作天

- 拖動和縮放
- 圖層鎖定
- 背景裁切
- 字級與顏色控制
- 上傳照片
- 復原／重做
- 視需求導入 Konva

### 階段 3：模板與資料庫整合，約 1～2 週

- 模板管理、資料庫保存、歷史作品
- 複製舊圖與 Notion 模板轉換
- 使用者權限與素材快取

只做技術原型約 1～2 個工作天；可使用 MVP 約一週；完整系統約 3～5 週。

## 十三、優點與代價

### 優點

- 中文、數字與資料來源由程式控制
- 修改數字不必整張重新生圖
- 降低 API 重複生成成本
- Gemini／GPT 可替換
- 同一版型可大量重複使用
- 版面與安全區穩定
- 作品可保存並重新編輯
- 更適合正式播出

### 代價

- 必須先設計固定版型
- 自由度比完整 AI 生圖低
- 每種新聞形式需要對應版型
- AI 背景與資訊面板有時不完全融合
- 複雜地圖與軍事拆解需要專門處理

## 十四、模式對照

| 新聞類型 | 建議模式 |
|---|---|
| 股市、民調、比較表、時間軸 | 混合版型 |
| 大量中文與數字 | 混合版型 |
| 人物生平、資訊卡 | 混合版型 |
| 災難、戰爭、情境示意 | 完整 AI 生圖 |
| 幾乎沒有文字的插圖 | 完整 AI 生圖 |
| 每日固定更新圖表 | 純版型 |

## 十五、建議決策方式

先做「三欄數據比較」技術原型，不立即全面改造專案。原型需驗證：

- AI 無文字背景能否配合留白區
- 繁體中文字型是否清楚
- 數字與單位是否穩定呈現
- 版型與底部安全區是否符合新聞使用
- 1280×720 PNG 是否能進入實際工作流程
- 使用者是否覺得比完整 AI 生圖更快

通過原型驗證後，再決定是否進入階段 1。未獲使用者明確批准前，不開始實作本提案。
