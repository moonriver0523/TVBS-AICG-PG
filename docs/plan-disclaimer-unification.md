# B70／F43 標籤系統整合模組化實作計畫

日期：2026-09-21  
範圍：只規劃「示意圖／AI示意圖／畫面來源」的判定、欄位、位置、碰撞、前端控制與相容遷移；本文件不實作。

## 1. 現況盤點與實際驗證

### 1.1 三套平行實作

| 路徑 | 輸入／狀態 | 判定 | 繪製 | 位置詞彙與 UI |
|---|---|---|---|---|
| 一般 CG／播出鏡面 | `ImageGenerateRequest.disclaimer_kind`、`disclaimer_source_text`、`disclaimer_corner` | `main.resolve_image_disclaimer(portrait_mode, source_text)`；網頁版主要由 `apply_portrait_to_image_request()` 回填 `disclaimer_kind` | `compose.paste_disclaimer_note()` → `_disclaimer_box()` | `upper_left`／`lower_left`／`upper_right`／`lower_right`；`index.html` 有兩份同步控制列，`app.js.disclaimerPayload()` 只進兩個 generate payload |
| YT 直播直標 | `YtOverlayRequest.source_text`、`source_corner`、舊 `source_follow_logo` | 沒有走 resolver；端點沒有「底圖是否 AI」或肖像來源資訊，只要 `source_text` 非空就畫來源 | `yt_vertical_layout()` 算 `source` box，`compose_yt_overlay()` 畫字；文字前綴由 `vstrip_source_text()` 補 | `tl`／`bl`／`tr`／`br`；自己的來源輸入與四角按鈕 |
| 十點封面 | `source_left`／`source_right`，另有 `left_is_ai`／`right_is_ai` | `compose_ten_cover()` 內各格自行 `if is_ai ... elif source_text` | `_draw_cover_ai_note()` | 無位置欄位、無前端來源輸入；位置由版型固定 |
| 四種 YT 封面 | `source_text`，另有 `is_ai` → `ai_note` | 四支 `compose_yt_*_cover()` 各自 `if ai_note ... elif source_text` | `_draw_ai_note()` 或 `_draw_live24_ai_note()` | 無位置欄位、無前端來源輸入；位置由版型固定 |

前端缺口已確認：`tenCoverFields()` 不送 `source_left`／`source_right`，`ytCoverFields()` 不送 `source_text`；`index.html` 也沒有封面專用來源輸入。後端 schema、compose 與回應欄位雖已存在，正常網頁操作仍無法填入來源名。自動產生的 AI 標籤不受此缺口影響，因為它來自後端的 `is_ai` 判斷。

### 1.2 缺陷 2 的驗證結論：目前「結果局部互斥」，但規則沒有統一

實際讀過以下呼叫鏈：

- 十點封面：`_cover_full_composite()`／`_cover_composite()` 把自行算出的 `left_is_ai`、`right_is_ai` 與未解析的 `source_left`、`source_right` 一起傳給 `compose_ten_cover()`；後者在左右格分別使用 `if left_is_ai ... elif left_source_text`、`if right_is_ai ... elif right_source_text`。`mode="ai"` 則由 `_cover_ai()._post_paste()` 無條件呼叫 `paste_cover_ai_note()`，完全不讀來源欄位。
- YT 封面：`editor_yt_cover()` 把 `_yt_cover_background()` 等路徑算出的 `is_ai` 同時傳成 `ai_note=is_ai`，並把原始 `req.source_text` 傳給四支 compose；四支 compose 都用 `if ai_note ... elif source_text`。因此正常路徑目前不會同時畫兩種標籤。
- 直標：`editor_yt_overlay()` 直接把 `req.source_text`／`source_corner` 交給 layout 與 compose。它沒有 AI provenance 輸入，因此既無從判斷「示意圖」，也沒有呼叫 resolver。

所以應精確描述為：

1. 「封面同時出現 AI 與來源」在目前 compose 的正常呼叫中**無法重現**；現有 `tests/test_f43_source_label.py` 與 `tests/test_f43_yt_cover_source_label.py` 正在釘這個局部 `if/elif` 行為。
2. 但三條線確實沒有共用唯一判定。封面用 `is_ai`／`panel_is_ai`，一般 CG 用 `portrait_mode`，直標根本沒有 provenance。只要 B70 判準改動，三套就會漂移。
3. recompose 還有實際信任風險：十點直接相信請求帶回的 `background_is_ai`／`background_right_is_ai`；YT 在「帶底圖＋來源但沒明送 `background_is_ai`」時會擋 400，卻仍相信明送的 `False`。手工或有 bug 的舊客戶端可以讓 AI 底圖被當成原圖來源，或讓該有 AI 標籤的圖漏標。這是「該標時沒標／錯標來源」的可行路徑，不是 compose 同時畫兩個的問題。
4. `main.resolve_image_disclaimer()` 目前只在一般生成鏈路被使用；封面與直標均未呼叫。`ImageGenerateRequest.disclaimer_kind` 又允許既有 caller 預先指定，`_fill_in_disclaimer_kind()` 採「只補、不覆蓋」，因此它也還不是不可繞過的真正唯一真相源。

### 1.3 幾何與碰撞能力

- 一般 CG 的 `_disclaimer_box()` 只做安全區、`HOLE_INSET` 與四角定位；`HOLE_INSET` 只是離安全區外框的 margin，**沒有**扣除 `broadcast_hole_rect()` 的洞框 bbox。改為 normalized coordinate 時必須另把洞框列為 hard exclusion，不能把現行幾何直接一般化後就宣稱已避洞（見 9.2）。
- 直標的 `yt_vertical_layout()` 已能算出 `box`、`live`、`label`、`logo`、`source` 等實際矩形，且現行「與 Logo 同角就讓開」有測試覆蓋。
- YT 封面的 `_render_fixed_elements_bbox()` 會在透明畫布真正繪製固定元素，再由 alpha bbox 量出像素外框；`_yt_news_or_hot_fixed_boxes()`、`_yt_hourly_fixed_boxes()`、`_yt_live24_fixed_boxes()` 已使用它。
- `yt_cover_protect_boxes()` **不能原封不動當標籤碰撞表**：它是 B55 照片保護用途，測試還刻意要求「不要進標題區」，因此不含標題／標題帶；部分頂端元素也被合併成一個聯集 bbox。可直接重用的是 `_render_fixed_elements_bbox()` 這個量測 primitive 與各版型 render helper；標籤碰撞需另建包含固定元素、標題與標題帶的 obstacle boxes。
- 十點封面目前沒有對應的 obstacle API，需量出標頭帶、節目標籤、日期、ON AIR／精華章、左右標題區，且 split 要以左右 panel 分開處理。

### 1.4 既有硬契約

- 測試是 `unittest`；不可使用 `discover()`。目前基準為 2237 題全綠。
- `Capability.disclaimer` → `hides_for()` → `app.js EDITOR_FORMATS[].hides` 有 parity；`HIDES_ON_2026_09_14` 是凍結表。任何顯示控制列的改動都要先改 `Capability`，再依推導結果同步前端 literal 與凍結表，不能單獨手改某筆 `hides`。
- 一般 CG 的控制列在兩個 DOM 位置各一份，狀態需同步；兩個 generate fetch 都要送，現有測試要求 `...disclaimerPayload()` 恰為 2 次。
- `ImageRefineRequest` 不收標籤欄位；refine 只改未貼固定元素的來源圖，標籤在後續 recompose／generate 階段重貼。此界線維持不變。
- 來源長度維持 40：HTML `maxlength="40"`、Pydantic `Field(max_length=40)`、前端 state 截斷三者一致。

## 2. 目標架構

### 2.1 唯一真相源與深模組 seam

新增純政策模組 `disclaimer.py`，唯一公開判定介面為：

```python
resolve_disclaimer(
    *,
    ai_disclosure_required: bool,
    source_text: str = "",
) -> ResolvedDisclaimer
```

`ResolvedDisclaimer` 是不可變資料物件，欄位只含 `kind: Literal["", "ai", "source"]` 與已 trim、但尚未補「畫面來源：」前綴的 `text`。規則只有三條：AI 必標時一律回 `ai` 並忽略來源；否則有來源回 `source`；否則回空。caller 不得自己寫 `if ai_note/elif source_text`。

一般 CG 的 `portrait_mode in PORTRAIT_MODES_NEEDING_DISCLAIMER`、十點每格的 `panel_is_ai`、YT 封面的 `is_ai`，都只負責產生 `ai_disclosure_required` 這個事實；互斥與文字選擇一律交給 `resolve_disclaimer()`。直標目前不生圖、也無 provenance，明確傳 `False`；若未來直標要覆蓋 AI 來源訊號，先替端點增加可信 provenance，而不是讓前端直接選 `kind="ai"`。

`main.resolve_image_disclaimer(portrait_mode, source_text)` 先保留成薄相容 wrapper，內部只做 portrait mode → boolean，再呼叫新函式；一個 deprecation 週期後再移除。如此現有 import 不會在第一個 PR 全斷，但唯一政策實作已只有一份。

### 2.2 統一輸入模型

新增共用 schema：

```python
class DisclaimerPosition(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)

class DisclaimerInput(BaseModel):
    target: Literal["canvas", "left_panel", "right_panel"] = "canvas"
    source_text: str = Field(default="", max_length=40)
    position: DisclaimerPosition | None = None
```

各請求新增 `disclaimers: list[DisclaimerInput]`，並限制 target：

- `ImageGenerateRequest`、`YtCoverRequest`、`YtOverlayRequest`：最多一筆，只能 `canvas`。
- `TenCoverRequest`：滿版只能 `left_panel`（語意為唯一 panel）；split 可各一筆 `left_panel`／`right_panel`，不得重複。
- `ImageRefineRequest`：**不新增**此欄位。

`position=None` 不是 `(0.5, 0.5)`，而是「沿用該版型 2026-09-21 的既有位置」，確保舊請求逐像素相容；唯一例外是以前根本不貼新標籤的 `broadcast_hole`，它沒有可維持的標籤像素基準，預設位置須另選不遮洞框與洞框浮水印的位置（見 9.4）。新位置一律用 target-relative 的 normalized `(x, y)`：`canvas` 是整張成品，`left_panel`／`right_panel` 是各自 panel 的最終像素矩形；`(x, y)` 表示**標籤中心點**，不是左上角，也不是瀏覽器預覽圖像素。中心點最符合拖曳手勢，且來源文字長短改變時不會把使用者選的位置改解讀成另一個角落。後端先依成品實際尺寸、profile 與文字量出真實 bbox，再驗證整個 bbox 位於 `safe_area_spec.safe_rect` 內；若有 `broadcast_hole`，還要驗證不與 `broadcast_hole_rect()` 相交。因 safe rect 扣掉洞框後不是單一矩形，API 不能只回一個 `placement_bounds` 矩形，還須回 hard-exclusion bbox。

前端把 Pointer Event 在預覽圖 content box 內的位置換成 target-relative 0–1；後端回傳同一座標系的 `placement_bounds`，前端只依這個權威範圍夾住拖曳，不複製 safe-area／字級／內距算式。若惡意或過期 client 仍送到範圍外，後端回 400 `outside_safe_area`，**不**靜默夾回，避免輸出位置和使用者送出的值不一致。四角快捷鍵由後端回傳的 bounds 算中心點；legacy corner adapter 也在量出 bbox 後做同一轉換，不再假設四角固定等於 `(0,0)`／`(1,1)`。

外部輸入不再接受有權決定結果的 `kind`。`ImageGenerateRequest.disclaimer_kind` 在遷移期保留但標為 deprecated、只供讀取舊紀錄；生成時必須由 resolver 重算，不再「caller 已填就不覆蓋」。這是必要的行為修正，否則無法宣稱唯一真相源。

### 2.3 欄位保留、改名、廢棄

| 舊欄位 | 目標 | 遷移行為 |
|---|---|---|
| `ImageGenerateRequest.disclaimer_source_text` | `disclaimers[0].source_text` | 保留一個 deprecation 週期；未送新欄位時轉成 `canvas` input |
| `ImageGenerateRequest.disclaimer_corner` | `disclaimers[0].position` | 保留；在 renderer 已知 bbox 後轉成四角中心座標；新前端只把四角當快捷鍵，不再送 corner 字串 |
| `ImageGenerateRequest.disclaimer_kind` | 廢棄外部控制 | 遷移期接受但忽略其判定權；回應／稽核可記錄 resolved kind |
| `YtOverlayRequest.source_text` | `disclaimers[0].source_text` | 舊欄位 adapter；新前端只送新欄位 |
| `YtOverlayRequest.source_corner` | `disclaimers[0].position` | `tl/bl/tr/br` 只保留在 legacy adapter；renderer 已知 bbox 後轉成中心座標，核心與新前端永遠不用短碼 |
| `source_follow_logo` | 廢棄 | 只留給未帶新 position／未帶 `source_corner` 的最舊請求，映射到既有預設位置 |
| `TenCoverRequest.source_left/right` | `disclaimers[target=left_panel/right_panel].source_text` | 保留 adapter；回應的 `source_left/right` 暫留，避免後台／重送舊紀錄斷裂 |
| `YtCoverRequest.source_text` | `disclaimers[0].source_text` | 保留 adapter；`YtCoverResponse.source_text` 暫留 |

新 canonical vocabulary 一律使用完整後端方位語意；不把 `tl` 擴散到新 schema。這確實改變「不做對照層」的既有決定，但值得，原因是現在已經存在兩套互不相容詞彙，若不在輸入 seam 做一次性 legacy normalization，就只能永久維護兩套核心幾何。adapter 必須只存在於 Pydantic 的 legacy parser，解析後立即變成 normalized position；前端、resolver、renderer、測試的新案例全部只看新模型，避免形成第二個長期對照層。

舊後台紀錄／重送：讀取時先看 `disclaimers`；沒有才讀舊欄位。完全沒有位置欄位時採版型 legacy default，不套一個全域預設。稽核輸出新增 resolved `kind`、normalized position、target 與 legacy-adapter-used flag，方便確認遷移量；舊欄位至少保留一個可觀測的發布週期後，另開移除 PR。

### 2.4 統一繪製介面

`compose.py` 提供一個共用高階介面，隱藏文字正規化、量字、縮字、座標、碰撞與繪製：

```python
paste_resolved_disclaimer(
    image: bytes | Image.Image,
    *,
    disclaimer: ResolvedDisclaimer,
    position: DisclaimerPosition | None,
    profile: DisclaimerLayoutProfile,
    target: str = "canvas",
    obstacles: Sequence[NamedBox] = (),
) -> DisclaimerRenderResult
```

`DisclaimerRenderResult` 至少帶 `image_bytes`、透明 `layer_png_bytes`、實際 `bbox`、canonical `position`、`placement_bounds` 與具名 `obstacles`。同一個 renderer 同時供正式輸出與拖曳端點使用；前端拿到的透明 layer 就是 Pillow 真正畫出的字與底板，只做 CSS 位移，不自行重畫一份近似標籤。這讓字級、底板高、內距、安全區與 `HOLE_INSET` 全都留在後端模組內，維持 locality，也符合 repo「不要做對照層」的原則。

`DisclaimerLayoutProfile` 是 repo 內固定的 style／安全區資料，不由 API 傳入；至少有 `cg`、`vstrip`、`ten_cover`、`yt_news`、`yt_hourly`、`yt_live24`、`yt_hot`。視覺可維持各版型現況（字型、半透明底板、顏色），但幾何與 collision contract 共用。`vstrip_source_text()` 的前綴正規化移到政策模組並保留舊函式 wrapper，避免 renderer 名稱反過來成為全站文字規則。

現有 `paste_disclaimer_note()`、`_draw_cover_ai_note()`、`_draw_ai_note()`、`_draw_live24_ai_note()` 第一階段保留為 adapter，逐一改成呼叫共用介面；所有 caller 遷完再移除 adapter。不要建立一層只轉參數、但永久存在的 shallow wrapper。

## 3. 自由位置功能設計

### 3.1 開放層級

建議分級，不建議三套無條件全自由：

| 場景 | 可選範圍 | 後端規則 | 理由 |
|---|---|---|---|
| 一般 CG | 安全區內全自由 | 只檢查安全區與畫布，不做內容語意碰撞 | 沒有程式固定家具；使用者對底圖內容負責 |
| broadcast 無挖空 | 同一般 CG | 依實際 broadcast safe profile | 現況已可四角，generalize 風險低 |
| broadcast 有 `broadcast_hole` | 安全區內自由，但不得落進洞框；洞框浮水印與新標籤都保留 | UI 不 disabled；後端在洞框與浮水印畫完後仍貼新標籤。洞框 bbox 是 hard exclusion；浮水印 bbox 是一般 obstacle，依裁決 2 只警示 | **裁決 1 已反轉舊方案**；兩個都貼，且不得再以 `broadcast_hole` 跳過 |
| YT 直標 | 安全區內自由，但不得碰直標、LIVE／小標、Logo | 量出 candidate bbox 後硬擋碰撞 | 現行自動讓 Logo 是四角特例；任意點若繼續自動移位會讓實際輸出和選擇不一致 |
| 十點／YT 封面 | 安全區內自由，但不得碰任何固定元素與程式標題區 | 量出 candidate bbox 後硬擋碰撞 | 家具多，無限制拖曳會直接壓 Logo／標題；白名單矩形會隨版型演進過時 |

受限場景採「碰撞後擋下並提示」，不採靜默自動讓開。錯誤應是 400，detail 至少包含 target、碰到的具名物件（如 `TVBS Logo`、`LIVE badge`、`title_band`）與候選 bbox；前端把衝突格／滑桿區域標紅。自動找最近空位只能做成使用者明按的「移到最近可用位置」，不能在生成時偷偷做。

### 3.2 碰撞來源

1. 共用 `boxes_overlap(a, b, padding)`，半開區間規則固定，預設 padding 依畫布比例換算，避免元素雖未交疊卻貼得太近。
2. 直標：從 `yt_vertical_layout()` 取得 `box`、`live`、`label`、`logo`；空 bbox 略過。來源標籤本身不再先被 layout 排位，layout 只回 obstacles 與 label target rect。
3. YT 封面：新增 `yt_cover_disclaimer_obstacles(layout, render_context)`。重用 `_render_fixed_elements_bbox()` 與真正的固定元素 render helper，**不要改變** `yt_cover_protect_boxes()` 的 B55 語意；再加入程式繪製的標題 bbox／標題帶。`draw_titles=False` 或模型負責日期牌時，要依實際 render context 排除不存在的 obstacle。
4. 十點：新增 `ten_cover_disclaimer_obstacles(layout, draw_titles, badge, ...)`，以同一批真正的 header／badge／title draw helper 在透明畫布量測；split 回傳帶 target 的左右 obstacle，不能用一個跨全寬 union bbox 把中央空間誤封。
5. 先 fit 字、得到標籤真實 bbox，再碰撞；不可用固定「AI示意圖」寬度估來源文字。縮字只解決標籤自身超出可用寬度，不可拿來鑽過固定家具；縮到既有下限仍放不下即 400。

`_render_fixed_elements_bbox()` 因此可直接成為共用量測 primitive；`yt_cover_protect_boxes()` 只可作為 fixed-element 資料的參考／內部 helper，不可直接當完整 collision list，否則標題區會漏保護。

### 3.3 UI：以預覽圖拖曳為主互動

主要互動確定為「在預覽圖上直接拖曳標籤」。四角按鈕只保留為快捷鍵／預設值，X/Y 數字欄位只作鍵盤與無法拖曳時的 fallback；不再把九宮格列為主方案。

#### 3.3.1 「貼標籤前」底圖如何交給前端

一般 CG／播出鏡面的正式順序維持：模型圖 → 置框 → `broadcast_hole`（若有）→ 標籤。`apply_image_disclaimer()` 在最後一步前先保存完全相同尺寸與像素的底圖，`ImageGenerateResponse` 新增建議欄位 `disclaimer_base_image_base64` 與 `disclaimer_base_mime_type`；它和既有 `source_image_base64` 不同，後者是置框前、供模型 refine 的原圖，兩者不可混用。另回 `disclaimer_layer_base64`、`disclaimer_bbox`、`placement_bounds` 與簽章／opaque `disclaimer_render_token`；layer 很小，且由同一 Pillow renderer 產生，前端不必重做 `PORTRAIT_DISCLAIMER_*`、`safe_rect` 或 `HOLE_INSET`。

可選的另一種作法是只回 `disclaimer_base_id`，由伺服器暫存底圖。它少傳一張 base64；直接內嵌則會同時回成品與底圖，未壓縮前接近兩份 raster payload，而且 base64 各自另有約 33% 編碼膨脹。id 方案雖省傳輸，卻會新增 TTL、清除、容量上限、多人授權、重整後失效、部署重啟、水平擴充共享儲存與 sticky-session 問題。**建議第一版直接回 `disclaimer_base_image_base64`**：repo 已有封面回傳壓字前底圖的先例，流程無狀態、失敗可重試，也不需要把一次 PIL 操作變成有生命週期的資產服務。若實際 response telemetry 證明傳輸量不可接受，再把相同外部語意換成有 TTL 的物件儲存／id；不要先引入 server RAM 暫存。

#### 3.3.2 重貼端點

新增獨立端點，不在 `/api/images/generate` 加 `reposition_only` 旗標，也不沿用 `/api/images/refine`：前者容易誤觸模型生圖，後者已有 `ImageRefineRequest` **不得出現 disclaimer 欄位**的硬契約。建議介面為：

```json
POST /api/images/disclaimer/render
{
  "disclaimer_base_image_base64": "...",
  "disclaimer_base_mime_type": "image/png",
  "disclaimer_render_token": "opaque-signed-context",
  "disclaimer": {
    "target": "canvas",
    "source_text": "中央社",
    "position": {"x": 0.73, "y": 0.18}
  }
}

200
{
  "image_data_base64": "...",
  "mime_type": "image/png",
  "disclaimer": {"target": "canvas", "position": {"x": 0.73, "y": 0.18}},
  "disclaimer_layer_base64": "...",
  "disclaimer_bbox": {"x0": 0.68, "y0": 0.15, "x1": 0.78, "y1": 0.21},
  "placement_bounds": {"min_x": 0.08, "min_y": 0.09, "max_x": 0.92, "max_y": 0.91},
  "obstacles": [],
  "notices": []
}
```

token 綁定底圖 digest、實際 provenance／resolved kind、profile、target、canvas 尺寸與版型 render context；client 可以改 `source_text` 與 `position`，不能藉此把 AI 圖改標成來源圖、換底圖或偽造較寬鬆的 safe area。端點只驗證、呼叫 `paste_resolved_disclaimer()` 一次並回 PNG，沒有模型呼叫。位置越界或碰撞回 400，detail 帶穩定 code、具名 obstacle 與 candidate bbox。既有 `ImageRefineRequest` 與其前端 payload／釘住測試完全不改，只新增 `DisclaimerRenderRequest`／`DisclaimerRenderResponse` 的獨立測試。

#### 3.3.3 拖曳、觸控與網路節奏

- 預覽用 `disclaimer_base_image_base64` 當底層、後端回傳的真實透明 layer 當拖曳層。`pointermove` 期間只對 layer 做 CSS transform，依後端回的 `placement_bounds` 與 obstacle bbox 顯示合法／紅色衝突狀態；不建立 HTML/CSS 假標籤，也不複製 Pillow 幾何。
- 不對每個 `pointermove` throttle／debounce 打後端；`pointerup` 才呼叫重貼端點一次，以回傳成品、bbox 與 canonical position 取代暫時預覽。鍵盤連按可在 `keyup` 或 150–250 ms trailing debounce 後送一次。理由是畫面可維持 60fps、網路慢也不拖住手勢，放手後仍由後端做唯一權威驗證。
- 使用 Pointer Events＋`setPointerCapture()` 同時支援滑鼠、觸控筆與手機觸控；handle 至少 44×44 CSS px，拖曳區設 `touch-action: none`，但只攔截 handle，不阻止整頁捲動。鍵盤以方向鍵移 1%、Shift＋方向鍵移 5%，並用 `aria-valuetext` 唸出百分比與衝突原因。
- 不支援 Pointer Events、預覽尚未產生、layer 載入失敗或使用者採鍵盤操作時，fallback 是四角快捷鍵＋X/Y 0–100 數字欄位；它們寫入同一份 normalized state，不形成第二套位置模型。
- 十點 split 顯示「左格／右格」切換，每格各自保存來源與位置；滿版顯示「全版」。一般 CG 的兩份控制 DOM 仍共用同一 state 與更新函式；兩個 generate payload 仍各呼叫同一個 `disclaimerPayload()`。封面／直標改用相同 builder 產生 `disclaimers`，而非再手拼 `source_*`。
- `broadcast_hole` 開啟時來源輸入、拖曳 handle、快捷鍵與數字欄位全部維持可用；前端顯示洞框 hard exclusion 與洞框浮水印 obstacle，不能因開關而灰掉或隱藏控制項。**此處依裁決 1 修正原先的 disabled 方案。**

#### 3.3.4 封面六版型

建議開放拖曳，但排在 obstacle exporter 完成之後，以 feature flag 分批開。四種 YT 封面目前由 `_draw_ai_note()`／`_draw_live24_ai_note()` 依版型幾何定位，十點滿版／雙切由 `_draw_cover_ai_note()` 定位；這些函式改由共用 renderer 接收 optional position，`None` 時仍走原幾何。六版型都要把標籤調整為最後一個繪製步驟，並保存「所有其他固定元素已畫完、只有標籤尚未畫」的 `disclaimer_base_image_base64`；既有版型預設位置、縮字下限與放不下即擋下的護欄都保留。

YT 封面的固定元素由各真實 render helper 經 `_render_fixed_elements_bbox()` 量出具名 bbox；`yt_cover_protect_boxes()` 可提供 B55 已驗證的固定元素集合參考，但不能直接當完整 collision list，仍須補標題／標題帶。十點封面則用 `ten_cover_disclaimer_obstacles()` 分 target 回傳。後端把這些 bbox 放入 `DisclaimerRenderResult.obstacles`，前端只縮放顯示，不自行推導。

拖曳時允許 ghost layer 穿過障礙物以免游標被卡住，但碰撞時標紅且不更新 last-valid position；放手若仍碰撞就回復 last-valid，不能提交。這屬於「硬擋」，不是自動讓開，也不是只警示：自動移位會讓輸出背離編輯選點，只警示則可能把合規標籤壓在 Logo／標題上。後端在每次重貼重新量 candidate bbox 並以同一 obstacle 清單驗證，不能相信前端。若第一期不批准封面開放，六版型維持 legacy default，但共用 renderer／回應欄位仍先完成，日後不需再造一套互動。

## 4. 分階段實作計畫

### PR 1：鎖定現況、抽出唯一政策模組（低風險，無預期像素變更）

1. 新增 `disclaimer.py`：`ResolvedDisclaimer`、`resolve_disclaimer()`、來源文字正規化。
2. `main.resolve_image_disclaimer()` 改為 compatibility wrapper；`apply_portrait_to_image_request()`、`_fill_in_disclaimer_kind()` 先透過 wrapper 使用新核心。
3. 加 characterization tests：一般 CG、十點左右格、四種 YT 封面、直標的現況矩陣；特別記錄「compose 正常路徑目前不會雙標」與 recompose provenance 信任點。
4. 不改 schema、不改 UI、不改 compose 位置；此 PR 可單獨以既有 2237 題＋新題驗收。

### PR 2：加入 canonical schema 與 legacy adapters（中風險；外部 contract 擴充，舊行為應不變）

1. 在 `main.py` 定義或匯入 `DisclaimerInput`／`DisclaimerPosition`，加入四種 request；明確排除 `ImageRefineRequest`。
2. 為舊欄位加 `model_validator(mode="before")`：只有新 `disclaimers` 缺席時才轉換；新舊同送但內容矛盾時回 422，不猜優先權。
3. `tl/bl/tr/br` 只在 `YtOverlayRequest` legacy parser 留下 legacy placement 語意，等 renderer 量出 bbox 後轉成中心座標；新欄位若收到短碼直接 422。
4. 回應與 archive 增加 resolved kind／position／target；`ImageGenerateResponse` 加入 `disclaimer_base_image_base64`／MIME、layer、bbox、placement bounds 與 render token 的 optional 欄位，舊 `source_*` 回應欄位保留且語意不變。
5. 定義獨立的 `DisclaimerRenderRequest`／`DisclaimerRenderResponse`；此 PR 只先鎖 schema，不借用或擴充 `ImageRefineRequest`。
6. 釘住 max 1／max 2、target 合法性、重複 target、normalized 範圍、40 字上限、舊紀錄 default，以及 refine schema／payload 完全沒有 disclaimer 欄位。

### PR 3：所有 compose caller 改走 resolver 與統一 renderer（高風險；判定權與像素路徑變更）

1. 在 `compose.py` 新增 `paste_resolved_disclaimer()`、`DisclaimerRenderResult`、profile、文字 fit 與 normalized center geometry；`position=None` 必須逐像素重現各版型舊位置，並由同一條路徑產生透明 layer、bbox 與 placement bounds。
2. 一般 CG：`apply_image_disclaimer()` 不再讀 caller 提供的 kind 作真相，接收 resolved object；在置框／挖洞後、貼標籤前保存 exact `disclaimer_base_image_base64`，與置框前 refine 用的 `source_image_base64` 分開。
3. 十點：`_cover_full_composite()`、`_cover_composite()`、`_cover_ai()._post_paste()` 針對每個 target 呼叫 `resolve_disclaimer(ai_disclosure_required=...)`，`compose_ten_cover()` 改收 resolved label／placement，不再自行 `if is_ai/elif source`。
4. YT 封面：`editor_yt_cover()` 在知道 `is_ai` 後只 resolve 一次，四支 `compose_yt_*_cover()` 接收 resolved label；刪除四份互斥分支。
5. 直標：端點以 `ai_disclosure_required=False` resolve，再把 resolved source 傳給 layout／renderer。這不代表直標能自動辨識直播訊號是否 AI；該限制留在介面文件。
6. 舊 draw 函式先做 adapter；用像素 golden／bbox assertion 證明未傳新 position 時不變。
7. `disclaimer_kind` 預填不再能覆蓋 resolver。這是刻意行為變更：舊 caller 若送錯 kind，結果會改為政策正確值。
8. 封面若要開放拖曳，先調整為標籤最後畫並保存 exact pre-disclaimer base；用 golden 證明 draw order 重排沒有改變既有成品像素。

### PR 4：建立 obstacle 模型與受限自由定位（高風險；新增可預期的 400）

1. `compose.py` 新增 `NamedBox`、`boxes_overlap()`、`validate_disclaimer_placement()`。
2. 直標新增 obstacle exporter；移除「只有同角才讓開」作為新 position 的核心規則。legacy `source_corner` 先保留為 legacy placement，等 bbox 已知才轉成能重現舊位置的 normalized center，確保舊請求不新增 400。
3. YT 封面新增 `yt_cover_disclaimer_obstacles()`；重用 `_render_fixed_elements_bbox()`，補齊標題／帶狀區，保留 `yt_cover_protect_boxes()` 原介面與 B55 行為。
4. 十點新增 `ten_cover_disclaimer_obstacles()`，處理 full／split、左右 target、header／badge／title。
5. renderer 回傳 target-relative normalized `placement_bounds` 與 obstacles；前端可拿來預覽，但新 position 仍由後端重算。越界回 400 `outside_safe_area`，碰撞回 400 `collision` 與具名 detail；legacy default 若歷史上本來重疊，為相容可標記 `legacy=True` 走原位置，但需用測試與註解限制，不能讓新 position 繞過。
6. 做 1920×1080、實際輸入尺寸、中心點／長短文字與前端顯示縮放測試，避免重演「相信 caller canvas 而不是成品尺寸」問題。

### PR 5：前端全面接線與封面缺口修復（高風險；使用者可見行為變更）

1. `Capability.disclaimer` 改成所有需要標籤控制的版型為 `True`；從 `hides_for()` 的輸出同步更新 `app.js EDITOR_FORMATS[].hides`，同 PR 更新 `HIDES_ON_2026_09_14`。不可只改 app.js。
2. 把兩份一般控制列升級成預覽圖拖曳，仍由 `querySelectorAll` 同步；四角與 X/Y 數字只作快捷／fallback。保留 `disclaimerPayload()` 且在兩個 generate fetch 各出現一次。
3. `tenCoverFields()` 送 left／right `disclaimers`，`ytCoverFields()` 與 `vstripFields()` 送 canvas `disclaimers`。封面來源第一次真正能由 UI 填入，修復缺陷 1。
4. 十點 split 提供左右 target 編輯；其餘版型只一組。切換版型時 state 依 format＋target 保存，避免把「路透社」從十點左格意外帶到直播直標。
5. `broadcast_hole` 開啟時控制項照常可用、payload 照常送、後端照常繪製；response 回傳洞框 hard exclusion、浮水印 obstacle，以及實際碰撞 warnings。**此處依裁決 1 修正原先的 skip／disabled 方案。**
6. refine payload 與 `ImageRefineRequest` 完全不碰；recompose 由 `tenCoverFields()`／`ytCoverFields()` 重送目前標籤設定。
7. 新增 `POST /api/images/disclaimer/render`：驗證 signed context 與底圖 digest，只做一次 PIL 重貼；不得呼叫任何模型 provider。前端 pointermove 只移動後端 layer，pointerup 才呼叫端點。
8. 用 Pointer Events 完成滑鼠／觸控／筆、pointer capture、44 px handle、鍵盤步進、ARIA 與四角／數字 fallback；封面是否啟用依本計畫待裁項與 PR 4 obstacle 完成度決定。

### PR 6：移除 deprecated surface（中風險；明確相容性斷點，需另行批准）

達到事先裁定的遷移門檻後，才移除 `disclaimer_kind` 的外部輸入、`source_text`／`source_corner`／`source_follow_logo`、`source_left/right` 舊 request 欄位，以及只剩 pass-through 的 compose wrappers。移除前先從 archive 的 `legacy-adapter-used` 統計確認沒有活躍舊 caller；若沒有可觀測資料，不執行此 PR。

## 5. 每階段檔案與測試清單

測試一律以 `loadTestsFromNames` 跑指定 module；例如：

```powershell
python -c "import unittest; names=['tests.test_b70_f43_disclaimer','tests.test_f43_source_label','tests.test_f43_yt_cover_source_label']; r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names)); raise SystemExit(not r.wasSuccessful())"
```

全套也必須沿用 repo 現有的 `loadTestsFromNames` 清單／runner，不用 `python -m unittest discover`。

| PR | 要動的 production／doc 檔 | 既有測試：要改或必跑 | 新測試 |
|---|---|---|---|
| 1 | 新增 `disclaimer.py`；`main.py` | `tests/test_b70_f43_disclaimer.py` 的 `ResolveImageDisclaimerTests`、`SourceTextReachesTheResolverTests`；`tests/test_f43_source_label.py`；`tests/test_f43_yt_cover_source_label.py`；`tests/test_followups_20260909.py::VstripSourceTests` | `tests/test_disclaimer_policy.py`：完整 truth table、trim、AI 優先、不可同時回兩種 |
| 2 | `main.py`（共用 schema、四 request、response/archive、render request/response）；必要時 `request_log.py`（若 archive schema 在此） | `tests/test_b70_f43_disclaimer.py::FrontEndSendsTheDisclaimerFieldsTests` 的 backend annotation／max length 部分；`tests/test_f43_source_label.py` endpoint classes；`tests/test_f43_yt_cover_source_label.py` endpoint／trust guard；`tests/test_followups_20260909.py::VstripSourceTests.test_api_and_ui_carry_the_new_field` | `tests/test_disclaimer_schema.py`：新舊輸入、衝突 422、targets、0–1、40 字、legacy defaults、response optional 欄位、render schema、`ImageRefineRequest` 無欄位且 refine payload 不送 |
| 3 | `disclaimer.py`、`compose.py`、`main.py` | `tests/test_b70_f43_disclaimer.py` 的 compose／wiring／full-pipeline／web E2E；`tests/test_f43_source_label.py::ComposeTenCoverSourceLabelTests`；`tests/test_f43_yt_cover_source_label.py::ComposeMutualExclusionTests`；`tests/test_yt_cover.py` 的 `ComposeTests`／`HourlyComposeTests`／`HotCoverTests`；`tests/test_portrait_rules.py` 與 `tests/test_ref_upload_module_20260913.py` 中 disclaimer cases | `tests/test_disclaimer_rendering.py`：各 profile legacy bbox／像素、normalized center、四角 adapter、長字 fit、exact pre-disclaimer base、layer 與成品像素合成一致、每個 caller 只 resolve 一次 |
| 4 | `compose.py` | `tests/test_followups_20260909.py::VstripSourceTests`；`tests/test_b55_yt_cover_photo_protection.py::ProtectBoxesUnitTests`；`tests/test_b55_transparent_title_layer.py::OverlayTitleLayerYtCoverUnitTests` 與 `DateTabIsOnlyProtectedWhenTheProgramDrawsItTests`；各封面 compose tests | `tests/test_disclaimer_collision.py`：每版型每個具名 obstacle、padding、title on/off、date tab on/off、十點左右、placement bounds、前端夾住但後端越界仍 400、錯誤 detail、legacy bypass 限定 |
| 5 | `main.py`、`editor_formats.py`、`app.js`、`index.html` | `tests/test_format_capabilities_20260914.py` 全檔；`tests/test_b70_f43_disclaimer.py::FrontEndSendsTheDisclaimerFieldsTests`；`tests/test_yt_vstrip_ui.py::MarkupTests`／`FormatWiringTests`；`tests/test_f43_source_label.py`、`tests/test_f43_yt_cover_source_label.py` endpoint E2E；所有 recompose／refine frontend source tests | `tests/test_disclaimer_ui_contract.py`：兩頁同步、generate 出現次數仍為 2、refine 零欄位、封面／直標 payload、左右 target、broadcast disabled、maxlength 40、Pointer Events／pointerup 單次呼叫、CSS layer、觸控／鍵盤／四角與數字 fallback；`tests/test_disclaimer_render_endpoint.py`：無模型呼叫、token／digest、防 kind 偽造、越界／碰撞 400、輸出像素 |
| 6 | `main.py`、`compose.py`、`app.js`，移除過期註解；更新相關 docs | 上列所有標籤測試＋全套 2237 基準；把 legacy acceptance tests 改為 unknown／extra field 的裁定結果 | migration-removal tests：舊欄位是 422、archive replay 有明確版本錯誤，不可靜默遺失 |

### 必須逐一標記為「刻意行為變更」的既有測試

1. `tests/test_b70_f43_disclaimer.py::SourceTextReachesTheResolverTests.test_a_kind_the_caller_already_set_is_never_overwritten`：PR 3 改成「caller kind 沒有判定權，resolver 結果覆蓋／忽略它」。這是建立唯一真相源所必需。
2. `tests/test_b70_f43_disclaimer.py::FrontEndSendsTheDisclaimerFieldsTests.test_the_buttons_use_the_backend_vocabulary`：新 UI 不再送 corner 字串，改驗拖曳／快捷鍵共用 normalized center position；完整字詞只保留 legacy parser／快捷顯示語意。
3. 同 class 的 `test_every_corner_the_ui_offers_is_one_the_backend_accepts`：改驗四角快捷使用後端 `placement_bounds` 算出合法中心點，不再釘死 0／0.5／1。
4. 同 class 的 `test_cover_formats_hide_the_row`：PR 5 反轉為封面顯示；這正是修復「後端會畫、前端填不了」。
5. `tests/test_format_capabilities_20260914.py::TableShape.test_hides_are_exactly_what_the_frontend_had_on_wiring_day` 的 `HIDES_ON_2026_09_14`：封面（及若採共用列的直標）移除 `disclaimer: True`，註明 2026-09-21 的刻意變更；`FrontendParity.test_app_js_hides_match_the_table` 必須仍綠。
6. `tests/test_followups_20260909.py::VstripSourceTests.test_api_and_ui_carry_the_new_field`：由 `source_corner` 短碼改驗 `disclaimers[].position`；另保留 backend-only legacy short-code test。
7. `tests/test_yt_vstrip_ui.py::MarkupTests.test_three_text_fields` 與 `test_five_button_groups`：若移除直標獨立來源控制，改驗共用標籤控制與直標其餘四組；不是把來源功能刪掉。
8. `tests/test_f43_source_label.py::ComposeTenCoverSourceLabelTests` 與 `tests/test_f43_yt_cover_source_label.py::ComposeMutualExclusionTests`：測試面由 compose 內部 `if/elif` 改到 `resolve_disclaimer()` 的公開 seam；endpoint 可觀察結果仍維持。
9. `tests/test_b70_f43_disclaimer.py::GenerateImageWiringTests.test_broadcast_hole_set_skips_the_new_stamp_to_avoid_double_stamping`：依裁決 1 **反轉**為洞框浮水印與新標籤兩者都畫，並驗證呼叫順序是 `apply_broadcast_hole()` 後才 `paste_disclaimer_note()`。這是刻意行為變更，不是 regression；洞框浮水印沒有被取代。

其餘既有測試應視為 regression，不應為了讓重構通過而放寬。尤其下列契約必須原樣保留：`disclaimerPayload()` 在兩個 generate payload 恰兩次、refine 不送且 `ImageRefineRequest` 不收、maxlength 40、舊請求未帶 position 時像素位置不變、B55 `yt_cover_protect_boxes()` 不侵入標題區。另新增硬契約：pre-disclaimer base 必須是置框／挖洞後且貼標籤前的 exact pixels，render 端點不得呼叫模型，後端永遠重驗位置。

每個 PR 的驗收順序：先跑該列 named modules，再跑完整 2237 題基準（加上新題後總數應只增加），最後檢查 `git diff --check`。任何像素 golden 更新都要附 before／after bbox 與「為何是需求造成」的說明，不能只重錄 golden。

## 6. 需要使用者裁決的項目

1. **broadcast hole 開啟時怎麼辦？**  
   建議：維持洞框自己的浮水印，新控制整列 disabled 並說明，不另外貼來源／AI 標籤。理由是現況已避免雙貼，改成「新標籤取代洞框浮水印」會牽涉播出模板規範。若選取代方案，需另定洞框 watermark 的 kind、位置與來源文字能否出現。

2. **封面碰撞要自動移位還是擋下？**  
   建議：擋下並指名碰撞物；可另提供使用者主動按的「最近可用位置」。理由是新聞成品的位置是編輯決策，靜默移位會使預覽／輸入與輸出不一致，也讓測試依賴搜尋順序。

3. **貼標籤前底圖欄位名稱是否採 `disclaimer_base_image_base64`／`disclaimer_base_mime_type`？**  
   建議：採用。它清楚表示這是「標籤 renderer 的底圖」，不會與既有置框前、供模型 refine 的 `source_image_base64` 混淆；透明拖曳層另叫 `disclaimer_layer_base64`。若要沿用封面的 `background_image_base64`，必須先接受該名稱在一般 CG 沒有「背景」語意且較易誤用。

4. **重貼介面是否採獨立 `POST /api/images/disclaimer/render` 與上述 request／response？**  
   建議：採用獨立端點與 signed `disclaimer_render_token`。不要在生圖端點加旗標，也不要修改 `/api/images/refine`／`ImageRefineRequest`；兩者都會擴大既有介面並使「這次到底會不會呼叫模型」變得不清楚。另需裁定 token 的 TTL；建議至少覆蓋同一編輯工作階段，預設 2 小時，過期要求重新產出預覽。

5. **封面六版型第一期是否開放拖曳？**  
   建議：開放，但必須等 PR 4 的具名 obstacle／placement bounds 完成，並以 feature flag 分版型啟用；未完成的版型維持 legacy default，不提供只有警示、仍可送出的半套拖曳。若時程優先，可先上一般 CG／無挖洞 broadcast／直標，再另批封面 flag，不影響統一 schema。

6. **十點 split 是否允許左右兩格各自位置？**  
   建議：允許，並各自保存來源與位置。理由是現有來源本來就是左右獨立；只給一個全域位置會使其中一格因家具不同而不可用，或迫使兩個標籤錯位。

7. **舊短碼 `tl/bl/tr/br` 保留多久？**  
   建議：backend request adapter 保留一個可觀測發布週期；新 UI 立即停止送。archive 顯示 legacy 使用量歸零後才執行 PR 6。若無法統計，寧可長期接受但只限 parsing seam，不把短碼放回核心型別。

8. **舊 caller 明送 `disclaimer_kind` 的相容性斷點？**  
   建議：PR 2 仍接受欄位但告警，PR 3 起忽略其判定權，PR 6 才從 schema 移除。理由是「caller 可覆蓋」與「唯一真相源」不能同時成立；越早停止信任越安全。

9. **recompose provenance 是否要在本案改為不可偽造 token？**  
   建議：本案先做最低限度修正：server response 回一個簽章／opaque provenance token，recompose 帶回並驗證；沒有 token 的舊請求維持既有 guard 與 notice，一個週期後強制。只信任 `background_is_ai: bool` 對「畫面來源」這種正面宣稱不夠。若不批准 token，計畫必須明列此風險為接受，不可宣稱已完全解決缺陷 2。

10. **「AI示意圖」還是「示意圖」的顯示文案是否統一？**  
   建議：政策 kind 統一為 `ai`，顯示文字由 profile 決定，第一輪維持各版型現況以避免非必要像素變更；若法遵要求全站同字，再另給一個明確文字表，不把文案散在 draw helper。

11. **碰撞安全距離數字。**  
   建議起始值為短邊的 1%（1080p 為 11 px，四捨五入），並以 profile 可覆寫；驗收樣張後再裁。固定寫 16 px 會在不同尺寸失去比例，完全 0 px 又會視覺黏住。

## 7. 明確不做的事

- 不讓前端直接選 `kind="ai"`／`kind="source"`；前端只提供來源文字與位置，真實 provenance 決定 kind，避免使用者把 AI 圖標成來源圖。
- 不把 AI／來源拆成兩組位置控制；兩者互斥且同一張成品只會有一種，兩套狀態只會製造不一致。
- 不把三種既有視覺樣式強制改成完全相同。此案統一的是政策、欄位語意、位置幾何與碰撞 seam；字型／底板可以由 profile 保留版型識別。
- 不直接拿 `yt_cover_protect_boxes()` 當完整碰撞表，也不為本案改變它的 B55 照片保護 contract；它刻意排除標題區。
- 不做「碰撞後靜默找空位」、不讓輸出位置依 obstacle iteration order 漂移。
- 不在前端用 HTML／CSS 重畫一份近似 Pillow 標籤；拖曳的是後端產生的透明 layer，正式成品一律由後端重貼。
- 不在 `pointermove` 每一幀呼叫後端；移動中只做 CSS 預覽，放手才重貼與驗證。
- 不把標籤欄位塞進 `ImageRefineRequest`。refine 處理底圖，標籤由 generate／recompose 的固定元素階段重貼。
- 不在同一個 PR 移除所有舊欄位。先雙讀、觀測、停止新前端寫入，再依資料移除；避免後台舊紀錄與非網頁 caller 無預警中斷。
- 不順手重寫封面標題、B55 保護、safe frame 或 broadcast hole 幾何；只抽取可重用的 bbox 量測，避免把高風險版面變更混進標籤整合。
- 不使用 `pytest` 或 `unittest discover`，也不以少量 targeted tests 取代完整 2237 題回歸。

---

## 8. 使用者裁決（2026-09-21）

第 6 節 11 項全數裁定如下。**裁決優先於本文件其他章節的建議**；與前文衝突處以本節為準。

| # | 題目 | 裁決 | vs 建議 |
|---|---|---|---|
| 1 | `broadcast_hole` 開啟時 | **兩個都貼**：洞框浮水印保留，另外再貼來源／AI 標籤 | 偏離 |
| 2 | 封面碰撞 | **只警示，仍可送出** | 偏離 |
| 3 | 底圖欄位命名 | `disclaimer_base_image_base64`／`disclaimer_layer_base64` | 採納 |
| 4 | 重貼介面 | 獨立 `POST /api/images/disclaimer/render` ＋簽章 token，TTL 2 小時 | 採納 |
| 5 | 封面六版型 | **第一期六個一次到位**，不分批、不用 feature flag | 偏離 |
| 6 | 十點 split | 左右格各自保存來源與位置 | 採納 |
| 7 | 舊短碼 `tl/bl/tr/br` | 後端保留一個發布週期，新 UI 立即停送 | 採納 |
| 8 | 舊 caller 明送 `disclaimer_kind` | **馬上停聽**，不走三步緩衝 | 比建議更嚴 |
| 9 | recompose provenance | 加簽章／opaque token 驗證 | 採納 |
| 10 | 標籤文案 | **全站統一「AI示意圖」** | 偏離 |
| 11 | 碰撞安全距離 | 短邊 1%（1080p ≈ 11 px），profile 可覆寫 | 採納 |

### 8.1 裁決造成的設計變更

**（裁決 1）挖空框不再是標籤的禁區。**
3.1 表格中「broadcast 有 `broadcast_hole`」那一列作廢。挖空開啟時：
- 前端**不**灰掉控制項；來源輸入、拖曳 handle、四角快捷、數字欄位全部正常可用。
- 後端**不**再跳過標籤繪製；`apply_image_disclaimer()` 在挖空框浮水印之後照常貼標籤。
- 同一張成品會同時出現洞框浮水印與本系統標籤，這是刻意的。
- 可用區需扣掉挖空框本身；9.2 的實查確認 `HOLE_INSET` 單獨不足，必須使用 `broadcast_hole_rect()` 的 bbox 建 hard exclusion，標籤不得落進洞內。
- 既有「挖空時跳過標籤」的行為若有測試釘住，屬**刻意行為變更**，須逐一點名改寫。

**（裁決 2）碰撞由硬擋改為警示。**
3.1 末段「受限場景採碰撞後擋下」與 3.2 第 5 點「縮到下限仍放不下即 400」的擋下語意，改為：
- 後端**不**因碰撞回 400。obstacle 模型仍要做（裁決 11 的 1% 距離要靠它算），但結果只進 response 的 `notices`／`warnings`，附具名物件與 candidate bbox。
- 安全區／畫布越界**仍然 400**——那是幾何合法性，不是碰撞。
- 前端拖曳時照常標紅，但**放手可以提交**；不回復 last-valid position。
- 3.3.4 末段「放手若仍碰撞就回復 last-valid，不能提交」作廢。
- 縮字下限仍在（標籤自身放不下仍是錯誤），與碰撞警示是兩回事。

**（裁決 5）封面六版型不分批。**
PR 4 的 obstacle exporter 必須一次涵蓋十點滿版／十點 split ／四種 YT 封面，PR 5 才能上；沒有「未完成版型維持 legacy default」這條退路。feature flag 不需要。這使 PR 4 成為本案最大的單一工作量，排程要據此估。

**（裁決 8）判定權立即收歸單一真相源。**
第 4 節 PR 2 的「仍接受欄位但告警」改為：PR 2 一落地就忽略 caller 明送的 `disclaimer_kind` 判定權，一律由 `resolve_disclaimer()` 決定。欄位本身仍留在 schema（PR 6 才移除），但不再影響結果。第 6 節第 8 項的三步緩衝作廢。任何依賴 caller 覆蓋的既有測試屬**刻意行為變更**。

**（裁決 10）文案全站統一為「AI示意圖」。**
2.4 的「顯示文字由 profile 決定、第一輪維持各版型現況」作廢。所有版型的 AI 標籤一律「AI示意圖」五字。這會產生**可預期的像素變更**：任何現行寫「示意圖」的版型，其既有樣張比對測試須逐一點名改寫並標記為刻意變更。文字表仍集中在一處，不散落 draw helper（這點維持）。

### 8.2 本節新產生的待辦

- 盤點六個封面版型與直標各自實際寫的字，確認哪幾個需要改成「AI示意圖」。
- 盤點「挖空時跳過標籤」的所有程式路徑與測試。
- 重新估 PR 4 工作量（六版型 obstacle 一次到位）。

## 9. 開工前盤點（2026-09-21）

本節是對 8.2 前兩項的實碼查核；第 8 節裁決仍是最高優先。查核時先用 codebase knowledge graph 找定義與 caller；`get_code_snippet`／`trace_path` 因本環境 approval policy 無法讀取，才回退到具行號的本機原始碼與字串搜尋。沒有讀取 `MASTER-列管清單.md` 全文。

### 9.1 各版型目前實際畫出的文案

共同來源前綴只有一份：`compose.py:2877` 的 `VSTRIP_SOURCE_PREFIX = "畫面來源："`，`compose.py:2980-2989` 的 `vstrip_source_text()` 會 trim，空字串仍空；已經以「畫面來源」開頭就原樣回傳，否則補上全形冒號版本「畫面來源：」。它目前涵蓋一般 CG／播出鏡面、直標、十點滿版／split、四種 YT 封面的**來源標籤**；它不負責任何 AI 文案，也不處理洞框自己的浮水印。

| 路徑 | AI 標籤現在實際畫出的字 | 「畫面來源」現在實際畫出的字 | 定義與消費點 | 裁決 10 是否要改字 |
|---|---|---|---|---|
| 一般 CG／播出鏡面（`compose.paste_disclaimer_note()`） | `示意圖` | 裸來源名 `美聯社` 會成為 `畫面來源：美聯社`；已帶「畫面來源」者原樣 | `PORTRAIT_DISCLAIMER_TEXT = "示意圖"` 在 `compose.py:417`；`paste_disclaimer_note()` 於 `compose.py:446-496`，其中 `compose.py:467` 在 AI 常數與 `vstrip_source_text()` 間選一個 | **要**：`PORTRAIT_DISCLAIMER_TEXT` 改為 `AI示意圖` |
| 直標 `yt_vstrip` | **沒有 AI 標籤能力，也沒有 AI 文案常數**；現行 request 只有來源句 | `畫面來源：`＋來源名 | 前綴常數／helper 在 `compose.py:2877, 2980-2989`；layout 於 `compose.py:3112-3120` 先正規化並量寬，實際繪字在 `compose.py:3333-3340` 再正規化後畫出 | 現有字不用改；若統一介面要讓直標也能顯示 AI 標籤，這是**新增 provenance／AI 分支**，不能誤寫成單純換字 |
| 十點封面滿版 | `AI示意圖` | `畫面來源：`＋左格來源名（滿版唯一 panel 沿用 left） | `COVER_AI_NOTE = "AI示意圖"` 在 `compose.py:559`；純 AI 滿版 `paste_cover_ai_note(split=False)` 在 `compose.py:862-882`；合成滿版走 `compose_ten_cover()` 的 `compose.py:1418-1493`；draw helper 預設值在 `compose.py:1019-1043` | 不用改 |
| 十點封面 split | 左、右 AI 格各畫 `AI示意圖` | 非 AI 格各自畫 `畫面來源：`＋各格來源名 | 同一 `COVER_AI_NOTE`（`compose.py:559`）；純 AI split 在 `compose.py:862-882` 畫兩枚；合成 split 的左右互斥分支在 `compose.py:1479-1493` | 不用改 |
| `yt_live_cover`（實作名 `compose_yt_cover`） | `AI示意圖` | `畫面來源：`＋來源名 | `YT_AI_NOTE = "AI示意圖"` 在 `compose.py:1607`；`_draw_ai_note()` 預設文案在 `compose.py:1667-1693`；互斥分支在 `compose.py:1952-1960` | 不用改 |
| `yt_hourly_cover` | `AI示意圖` | `畫面來源：`＋來源名 | 同一 `YT_AI_NOTE`（`compose.py:1607`）與 `_draw_ai_note()`；互斥分支在 `compose.py:2190-2199` | 不用改 |
| `yt_live24_cover` | `AI示意圖` | `畫面來源：`＋來源名 | 同一 `YT_AI_NOTE`（`compose.py:1607`）；靠左的 `_draw_live24_ai_note()` 預設文案在 `compose.py:2584-2605`；互斥分支在 `compose.py:2565-2573` | 不用改 |
| `yt_hot_cover` | `AI示意圖` | `畫面來源：`＋來源名 | 同一 `YT_AI_NOTE`（`compose.py:1607`）與 `_draw_ai_note()`；互斥分支在 `compose.py:2749-2755` | 不用改 |

另有一條不在上表七條 UI 路徑之內、但仍是全站可見 AI 文案：洞框浮水印 `compose.WATERMARK_TEXT` 現為 `示意圖`（`compose.py:305`），由 `apply_broadcast_hole()` 在 `compose.py:382-392` 畫出。裁決 10 的「全站」也涵蓋它，因此同樣要改成 `AI示意圖`；不能只改 `PORTRAIT_DISCLAIMER_TEXT` 後留下第二種字樣。

#### 文案變更會紅的既有測試

以 runtime 暫時把 `WATERMARK_TEXT`／`PORTRAIT_DISCLAIMER_TEXT` 換成 `AI示意圖`，再用 `unittest.defaultTestLoader.loadTestsFromNames()` 實跑確認（沒有改檔）：

1. `tests/test_followups_20260909.py:191-203::BroadcastBottomStripTests.test_stamp_on_leaves_the_watermark_corner_clear` 會紅，因 `tests/test_followups_20260909.py:198` 明確斷言 `WATERMARK_TEXT == "示意圖"`。只改期望文案；它後半段釘住 lower-right 保留區的斷言仍要保留。這是**刻意文案變更**。
2. `tests/test_editor_formats.py:229-239::ComposeOutputTests.test_base_canvas_compose_is_byte_identical_to_the_golden` 會紅，因它在 `tests/test_editor_formats.py:236-239` 比對整張 PNG SHA-256；浮水印多出 `AI` 必然改 hash。重錄時要附 before／after watermark bbox。這是**刻意像素變更**。
3. `tests/test_b70_f43_disclaimer.py:108-112::ComposePasteDisclaimerNoteTests.test_ai_kind_draws_the_fixed_text` **不會紅**：方法名雖稱 fixed text，實際只驗尺寸與 mode，沒有驗字串或像素。這是覆蓋缺口，實作 PR 應補一個攔截 `_draw_text` 並明確驗 `AI示意圖` 的 assertion。
4. 十點與四種 YT 封面的常數原本就是 `AI示意圖`，所以 `tests/test_cover_ai_note.py`、`tests/test_f43_source_label.py::ComposeTenCoverSourceLabelTests`、`tests/test_f43_yt_cover_source_label.py::ComposeMutualExclusionTests` 不應因裁決 10 變紅；若變紅就是**誤傷／regression**。直標目前沒有 AI 字可換，來源前綴也不變。

### 9.2 `broadcast_hole` 開啟時跳過標籤：完整路徑

#### 後端實作點

實際 skip 只有一個：`main.generate_image()`（定義 `main.py:3541`）在模型生圖、safe frame 與洞框都完成後，於 `main.py:3580-3586` 用：

```python
if req.disclaimer_kind and not req.broadcast_hole:
    result = apply_image_disclaimer(result, req, profile=frame_profile)
```

也就是 `broadcast_hole` 只要是非空字串（現行合法值為 `left`／`right`），即使 `disclaimer_kind` 是 `ai` 或 `source` 也完全不呼叫 `apply_image_disclaimer()`。`/api/images/generate` 直接走這一點；`/api/news-image` 也沒有第二個 skip，而是在 `main.py:5484-5512` 把 `broadcast_hole_for(req)` 與已 resolve 的 `disclaimer_kind` 組成 `ImageGenerateRequest` 後呼叫同一個 `generate_image()`。因此刪除 `and not req.broadcast_hole` 就能覆蓋兩條後端入口，不能在兩個 endpoint 各補一次。

`apply_image_disclaimer()` 本身在 `main.py:4054-4080` 沒有洞框判斷，只呼叫 `compose.paste_disclaimer_note()`；它的 docstring 已說是「置框（與可能的播出鏡面挖空框）都貼完之後」才執行，與裁決指定順序一致。

#### 前端現況

前端**沒有**「洞框開啟就隱藏／停用 disclaimer」的現行邏輯：

- `app.js:1717-1721` 的 `toggleHole()` 只翻 `state.hole`、更新壓框按鈕與 toast，沒有碰 disclaimer controls。
- `app.js:2955-2971` 的 `updateDisclaimerControls()` 只同步角落按鈕、來源輸入值，並依 `editorFormat().hides.disclaimer` 隱藏不適用版型；它不讀 `state.hole`，也不設 `disabled`。
- `index.html:741-758` 與 `index.html:1036-1055` 的兩份控制列沒有 `broadcast_hole` 條件或 `disabled` 屬性。

所以「UI 不灰掉」在現況已成立；要改的是計畫前文原先打算新增的 disabled 設計，而不是移除既有前端程式。本次已明改 3.1、3.3.3 與 PR 5，避免未來照舊計畫誤做。

#### 洞框與浮水印

- 洞框 bbox 已可直接取得：`compose.broadcast_hole_rect(canvas, side, profile)`（`compose.py:322-352`）。1920×1080、`EDITOR_FRAME_PROFILE` 實算 safe rect 為 `(77, 43, 1843, 1037)`；左洞為 `(101, 319, 885, 760)`，右洞為 `(1035, 319, 1819, 760)`。
- `compose.apply_broadcast_hole()`（`compose.py:355-396`）先在該 bbox 畫白底、灰框、圓角洞框，再由 `compose.py:382-392` 畫浮水印。浮水印常數為 `WATERMARK_TEXT = "示意圖"`、30 px、淺灰 `(236,236,236)`（`compose.py:305-307`），無底板、有 3 px stroke，固定以 safe rect 右下內縮 `HOLE_INSET` 的 `(x1-inset, y1-inset)` 為 `anchor="rs"`；1920×1080 的 anchor 是 `(1819, 1013)`，與洞框在左或右無關。
- 它會和新標籤的現行預設 `lower_right` **直接打架**。`_disclaimer_box()`（`compose.py:425-443`）也用同一個右下 anchor；以新字 `AI示意圖` 實算新標籤 plate 約 `(1713, 961, 1819, 1013)`，而舊／新浮水印 ink bbox 約為 `(1771,987,1822,1017)`／`(1741,987,1822,1017)`，有實質重疊，不只是安全距離不足。

#### 可用區的明確做法

`HOLE_INSET` **不夠**。它只是 24 px scalar margin：`broadcast_hole_rect()` 用它把洞框離 safe rect 外框內縮（`compose.py:335-351`），`_disclaimer_box()` 又各自用它把標籤離 safe rect 外框內縮（`compose.py:433-442`）；兩者沒有互相看 bbox。裁決要求的實作應為：

1. 先以成品實際尺寸呼叫 `broadcast_hole_rect()`，取得洞框 bbox。
2. 以裁決 11 的短邊 1%（profile 可覆寫）膨脹該 bbox，列入 `hard_exclusions`；candidate label bbox 與它相交時屬幾何非法，回 `outside_available_region`，不是一般家具碰撞 warning。這樣才真正做到「不得落進洞內」。
3. safe rect 減洞框後不是單一矩形，現計畫只回單一 `placement_bounds` 不足；response 需另回 `hard_exclusions`（bbox list），前端照比例畫禁區，後端仍逐次重驗 candidate bbox。
4. 浮水印 bbox 目前沒有公開 helper；`broadcast_hole_rect()` 只回白色洞框。新增 `broadcast_watermark_bbox(canvas, profile, text)`（或統一的 `broadcast_hole_obstacles()`）用與 `apply_broadcast_hole()` 完全相同的 font、stroke、anchor 量測，作為具名 obstacle `broadcast_hole_watermark`。依裁決 2，它與新標籤相撞只回 warning、仍可提交；預設位置則應主動選開，避免每張預設成品都疊字。

這也修正了前文 1.3、2.2 與 8.1 將 `HOLE_INSET` 說成足以形成洞框可用區的錯誤；`HOLE_INSET` 可沿用作 outer margin，但不能代替洞框 bbox 幾何。

### 9.3 釘住「挖空時不畫標籤」的測試

現有 suite 只有一題直接釘住 skip：`tests/test_b70_f43_disclaimer.py:220-234::GenerateImageWiringTests.test_broadcast_hole_set_skips_the_new_stamp_to_avoid_double_stamping`。它 patch `compose.paste_disclaimer_note` 後送 `broadcast_hole="left"`、`disclaimer_kind="ai"`，最後 `assert_not_called()`。裁決 1 後此題必紅，屬**刻意行為變更**；應改名為例如 `test_broadcast_hole_keeps_its_watermark_and_stamps_the_disclaimer_afterwards`，同時 spy `compose.apply_broadcast_hole` 與 `compose.paste_disclaimer_note`，驗兩者各一次且順序正確。

沒有前端測試釘住 disabled／hidden，因前端本來就沒有該行為。文案統一另外造成 9.1 所列兩題刻意失敗；它們不是 skip 行為的測試。除此之外，現有洞框幾何測試都應維持綠色：例如 `tests/test_editor_formats.py:241-267::ComposeOutputTests.test_high_res_watermark_scales_with_the_canvas_height` 只驗縮放關係，`tests/test_followups_20260909.py:205-212::BroadcastBottomStripTests.test_the_watermark_really_is_at_the_bottom_right_for_both_sides` 只驗 anchor 與 inset。若它們因解除 skip 而紅，屬**誤傷／regression**，不應改鬆。

### 9.4 新發現的待裁項

1. **洞框開啟時，新標籤的 legacy default 放哪裡？** 以前整枚被 skip，沒有可維持的標籤像素基準；直接沿用 `lower_right` 又必定壓住洞框浮水印。建議依洞框側選「對側上角」：左洞用 `upper_right`、右洞用 `upper_left`。理由是同時避開中央洞框與固定在右下的浮水印，而且這條路沒有舊標籤位置可被破壞。使用者若拖到別處，仍依 hard exclusion＋warning 規則處理。

除這一項外，文案沒有新待裁：`WATERMARK_TEXT` 是否改名已被裁決 10 的「全站」涵蓋；直標目前沒有 AI provenance，後續是否畫 AI 標籤則屬既定統一介面施工範圍，不應由 compose 猜測。
