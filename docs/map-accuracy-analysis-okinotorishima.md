[![「沖ノ鳥島フォーラム」 初のオンライン配信｜東京都](https://images.openai.com/static-rsc-4/eCSZnUIdVL-pSb9HHNk_i2LTsvhR0eDj-jSpIUAJnrCmAGYbMWKKQyvW9_3zTNyuP0-Yak-MBCVisT43dUgg5EA5TrBMcPWEgfBJWkB76Ju6izb7MFblVk6_Vw0dxEPtCGZwUN3IPfF95ZJzceRXnvORKjcaf-kDiOwQ_oB6Xwc?purpose=inline)](https://www.spt.metro.tokyo.lg.jp/tosei/hodohappyo/press/2021/03/03/08.html?utm_source=chatgpt.com)

有問題，而且問題不在「沖之鳥島」名稱，而是**地圖定位條件不足，構圖要求又迫使模型自行重組地理位置**。

官方座標顯示，沖之鳥島位於**北緯20°25′31″、東經136°04′11″**，距東京都心以南約1,700公里，距沖繩約1,100公里；它的位置遠比一般人直覺中的「沖繩南方」更偏東、更偏南。([地質調查所][1])

## 主要問題

### 1. 「Japan Okinotorishima and surrounding ocean」範圍太模糊

你要求同一張地圖同時呈現：

* 日本本土
* 沖之鳥島
* 180公里射擊距離
* EEZ範圍
* 4艘軍艦

但日本本土到沖之鳥島相距約1,700公里，180公里在這種比例尺下只會變成很短的一小段。模型為了讓畫面「看得懂」，很容易把沖之鳥島往日本、沖繩或小笠原群島方向拉近。

也就是說，模型不是不知道地名，而是會為了構圖可讀性，**犧牲真實比例**。

### 2. 沒有提供固定座標

目前只有：

> depict Japan Okinotorishima and surrounding ocean

但沒有明確指定：

* 沖之鳥島座標
* 地圖上下左右涵蓋範圍
* 北方朝上
* 經緯線方向
* 不可移動島嶼位置
* 不可為了排版縮短距離

對圖像生成模型而言，「沖之鳥島」比較像語意標籤，不是GIS座標點。

### 3. 「simplified map」會放寬地理準確度

這一句是危險來源：

> place a simplified western Pacific map panel

「simplified」容易被理解為：

* 簡化島鏈
* 改變島嶼間距
* 重新排列陸塊
* 將沖之鳥島移到較容易閱讀的位置
* 以象徵性位置取代真實位置

建議改成：

> geographically accurate simplified cartography

並進一步說明：只能簡化線條，不能改變座標、方位與相對距離。

### 4. EEZ沒有設定實際半徑

原文只有：

> a thin EEZ radius boundary

但沒有指定半徑。模型可能畫成任意大小，甚至把EEZ畫得像島嶼周圍幾十公里的警戒圈。

依一般EEZ圖示邏輯，應明確寫成：

> a 200-nautical-mile 370-kilometre radius boundary

同時因為沖之鳥島的EEZ主張具有外交爭議，新聞圖表最好標示：

> 日本主張的專屬經濟區範圍 示意

而不要直接呈現成沒有爭議的國際邊界。

### 5. 180公里沒有要求「依比例尺繪製」

這句：

> a labeled 180 km directional line

只要求線上寫「180 km」，卻沒有要求線的實際長度符合比例尺。

模型可能畫一條很長的線，再標180公里；也可能只把紅點隨意放在左下角。

應改成：

> The 180 km line must be plotted proportionally according to the same map scale and extend from Okinotorishima toward true southwest at an approximate bearing of 225 degrees

以沖之鳥島官方座標為起點，依正西南225度、180公里作示意推算，射擊位置大約落在：

**北緯19.28°、東經134.86°**

這只能作為「方位與距離示意」，除非日方公開更精確座標，否則不要在新聞圖上直接標成官方座標。

### 6. 單張地圖不適合兼顧全局與細節

最可靠的做法是使用**雙層地圖**：

* 小型定位圖：顯示日本、沖繩、沖之鳥島在西太平洋的關係
* 主要細節圖：放大沖之鳥島、EEZ圈與西南方180公里射擊點

這比要求一張地圖同時包辦所有資訊準確得多。

### 7. 版面指令有輕微衝突

前面寫：

> Main Title Positioned at the very top of the frame

但SAFE AREA又寫：

> The top 15% margin must contain NO title text

這兩條互相衝突。雖然你後面寫SAFE AREA優先，但模型仍可能混淆。

建議把前面改成：

> Positioned at the top of the active content area directly below the reserved 15% empty top margin

另外，左右各保留15%，右側再放三張資訊卡，地圖實際可用寬度會非常窄，也會增加模型扭曲地圖的機率。

---

## 建議直接替換的地圖段落

```text
==================================================
MAP ACCURACY RULES
THESE RULES OVERRIDE ALL VISUAL AND LAYOUT PREFERENCES
==================================================

Geographic accuracy is mandatory.
Do not relocate compress distort rotate or rearrange any geographic feature for visual balance.

Use a north-up map orientation.
North must be at the top
East must be on the right
West must be on the left
South must be at the bottom

Okinotorishima must be fixed at the real-world location:

Latitude 20°25′31″ North
Longitude 136°04′11″ East

Okinotorishima is located far south of mainland Japan and southeast of Okinawa.
Do not place it close to Okinawa Kyushu Taiwan the Philippines or the Japanese main islands.
Do not shorten the geographic distance between Japan Okinawa and Okinotorishima.

Use two separate map levels:

1 Locator overview map

Show a geographically accurate western Pacific locator map covering approximately:

Longitude 122° East to 146° East
Latitude 18° North to 46° North

Show the real relative positions of:
Japan
Tokyo
Okinawa
Okinotorishima

Okinotorishima must appear near the lower central portion of the locator map at its correct coordinate.
Use a small highlighted locator dot.
Do not enlarge or reposition the island.

2 Okinotorishima detailed map

Show a separate enlarged local map covering approximately:

Longitude 132° East to 140° East
Latitude 16.5° North to 24.5° North

Place Okinotorishima at:
20°25′31″ North
136°04′11″ East

Draw a thin circular boundary centered exactly on Okinotorishima representing the approximately 200 nautical mile 370 kilometre area claimed by Japan as an exclusive economic zone.

Label it:
日本主張的專屬經濟區範圍 示意

Place the reported firing location exactly southwest of Okinotorishima.
Use an approximate true bearing of 225 degrees.
The distance between Okinotorishima and the firing marker must be proportionally represented as 180 kilometres using the same map scale.

The approximate schematic firing point may be plotted near:
Latitude 19.28° North
Longitude 134.86° East

Connect the two points with a straight measurement line.
Label the line:
約180公里

Add a north arrow and a clearly visible 200 kilometre scale bar.

Only simplify coastline styling and visual detail.
Never simplify geographic positions distances bearings or relative scale.

Do not invent islands coastlines landmasses or maritime boundaries.
If accurate coastlines cannot be maintained use a clean ocean coordinate grid with accurate point markers rather than fabricated geography.
```

## 原本STRUCTURE地圖部分可改成

```text
Under the headline place a two-level geographic map composition.

Use a small north-up western Pacific locator map to show the true relative positions of mainland Japan Okinawa and Okinotorishima.

Beside or below it place a larger detailed map centered on Okinotorishima at 20°25′31″ North and 136°04′11″ East.

The detailed map must accurately show the reported firing point approximately 180 kilometres southwest of Okinotorishima at a true bearing of approximately 225 degrees.

The 180 kilometre distance must be drawn proportionally according to the displayed map scale.

Show Japan’s claimed 200-nautical-mile exclusive economic zone around Okinotorishima as a thin schematic boundary clearly labeled 日本主張的專屬經濟區範圍 示意.

Do not move Okinotorishima closer to Japan Okinawa or any other landmass for visual convenience.
```

## 最關鍵的一點

即使加入完整座標，**純文字生圖模型仍不保證地圖準確**。最穩定的新聞製圖流程是：

1. 先用官方地圖或GIS產生正確底圖
2. 將底圖作為參考圖片上傳
3. 指定模型「不得修改陸地輪廓、島嶼位置、比例尺與標記座標」
4. 只讓模型處理配色、資訊卡、標題、艦艇圖示與視覺風格

你的原PROMPT不是「資料錯誤」，而是把**地理製圖、視覺設計與版面重排同時交給生成模型自由處理**，因此沖之鳥島位置跑掉其實很容易發生。

[1]: https://www.gsi.go.jp/KOKUJYOHO/center.htm?utm_source=chatgpt.com "日本の東西南北端点の経度緯度"
