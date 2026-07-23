# TODO

## 地圖／位置圖：自動生成 Prompt 缺乏地理準確規則（2026-07-23 清查）

**現象**：自動生成的地圖類 CG，島嶼／地點位置常與真實地理位置有明顯落差。
案例：沖之鳥島 EEZ 實彈射擊爭議圖 — 沖之鳥島被畫得太靠近日本本土／沖繩（實際在東京南方約 1,700 公里，N20°25′31″ E136°04′11″）。

**清查結論**（懷疑屬實，且有四層原因）：

1. **自動流程零地理規則**（`main.py`）
   - 自動判斷只有「何時選地圖類型」的規則（`main.py:86`），選定後 style/structure 生成指令對地圖零要求：無座標、無北方朝上、無比例尺、無「不得移動地物」。
2. **SAFE AREA 規則反向禁止座標**（`SYSTEM_PROMPT_TEMPLATE` 內）
   - 「NEVER express any position... as a percentage, pixel, ratio, or number of any kind」為防版面數字入圖，副作用是 digest 模型連經緯度都不敢寫。
3. **唯一有座標紀律的是手動模板**（`app.js:192`「指定國家 標記」）
   - 要求 marker 依真實座標放置＋使用者手填 `lat,long`，但自動流程不會經過它。
4. **Digest 模型查不到座標**
   - 後端無 GIS／搜尋，座標只能靠模型記憶，冷門地點（如沖之鳥島）容易錯。

**修法方案**：

- [ ] `build_digest_instructions()`：當 `chart_type == "地圖／位置"` 時條件注入 MAP ACCURACY RULES 區塊：
  - 北方朝上（north-up）、東西南北方位固定
  - 已知地名輸出經緯度，marker 固定於真實座標，不得為構圖移動／壓縮／重排地物
  - 距離線（如 180 公里）須依同一比例尺按比例繪製，附方位角
  - 大範圍＋細節建議雙層地圖（locator overview + detailed map）
  - EEZ 等爭議範圍標示「主張範圍 示意」
  - 「simplified」僅限線條簡化，不得改變座標、方位、相對距離
- [ ] SAFE AREA 禁數字條款加豁免：「地理座標、距離數值、比例尺」不在禁止之列
- [ ] （進階）最穩定路線：GIS／官方底圖作為參考圖上傳，模型只處理配色、資訊卡、標題與風格，不得改動陸地輪廓與標記座標 — 參見 `docs/hybrid-rendering-proposal.md`

**參考資料**：`docs/map-accuracy-analysis-okinotorishima.md`（完整分析，含可直接替換的 MAP ACCURACY RULES prompt 段落與 STRUCTURE 改寫範例）。

預估工時：約 20 分鐘（含一次生圖測試驗證）。
