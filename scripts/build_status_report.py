"""產生給主管看的單頁進度報告（自帶樣式與內嵌圖片的 HTML）。

為什麼做成產生器而不是手寫 HTML：圖片要 base64 內嵌才能離線開啟與轉寄，
手寫等於把幾百 KB 的亂碼貼進原始碼，之後換一張圖就得重貼。這支腳本負責
壓縮、內嵌與組版，換圖只要換路徑再跑一次。

用法：
    python scripts/build_status_report.py
    python scripts/build_status_report.py --line-shots D:/Downloads   # 指定截圖來源

LINE 對話截圖需人工提供（LINE 桌面版是原生程式，無法自動截圖）。
放在來源資料夾、檔名含 "貼稿" 與 "收圖" 即可被認出；找不到就留佔位框，
不會拿假畫面充數。
"""

from __future__ import annotations

import argparse
import base64
import html
import io
from datetime import date
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "aicg-進度報告.html"

# 報告用圖一律放這裡、跟著版控走。
# 不要改指向 static/generated——那個資料夾超過 24 小時會自動清空，
# 2026-08-04 就發生過：重跑腳本時範例圖已被清掉，報告靜靜少了兩張圖。
ASSETS = REPO / "docs" / "assets" / "report"

EMBED_WIDTH = 1100
JPEG_QUALITY = 82


def embed(path: Path, max_width: int = EMBED_WIDTH) -> str | None:
    """縮圖後轉 data URI；檔案不存在回 None（呼叫端要能接受沒有圖）。

    線條圖（規格示意圖那種）轉 JPEG 會在文字邊緣糊掉，所以夠小又不需縮的 PNG
    直接原樣內嵌；照片類一律走 JPEG，否則整份檔案會大好幾倍。
    """
    if not path.exists():
        return None
    if path.suffix.lower() == ".png" and path.stat().st_size <= 300 * 1024:
        with Image.open(path) as probe:
            if probe.width <= max_width:
                return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode(
                    "ascii"
                )
    with Image.open(path) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            height = round(image.height * max_width / image.width)
            image = image.resize((max_width, height), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def find_line_shot(folder: Path, keyword: str) -> Path | None:
    """先找版控裡的 assets，再找使用者指定的來源資料夾（例如下載夾）。

    截圖一旦確定就該複製進 assets，否則下次重跑時人家的下載夾早就清空了，
    報告會靜靜少一張圖——這正是原本指向 static/generated 踩到的坑。
    """
    for base in (ASSETS, folder):
        if not base.exists():
            continue
        for candidate in sorted(base.glob("*")):
            if candidate.suffix.lower() in {".png", ".jpg", ".jpeg"} and keyword in candidate.name:
                return candidate
    return None


def figure(data_uri: str | None, caption: str, placeholder: str) -> str:
    cls = "shot"
    if data_uri is None:
        return (
            f'<figure class="{cls}"><div class="placeholder">{html.escape(placeholder)}</div>'
            f"<figcaption>{html.escape(caption)}</figcaption></figure>"
        )
    return (
        f'<figure class="{cls}"><img alt="{html.escape(caption)}" src="{data_uri}">'
        f"<figcaption>{html.escape(caption)}</figcaption></figure>"
    )


CSS = """
:root { --ink:#1c2431; --muted:#5b6676; --line:#dde3ea; --accent:#0b5cab; --bg:#fff; }
* { box-sizing:border-box; }
body { margin:0; padding:0; background:#eef1f5; color:var(--ink);
  font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",system-ui,sans-serif; line-height:1.75; }
.page { max-width:1000px; margin:0 auto; background:var(--bg); padding:56px 60px 72px; }
h1 { font-size:30px; margin:0 0 6px; letter-spacing:.5px; }
.sub { color:var(--muted); margin:0 0 28px; font-size:15px; }
h2 { font-size:22px; margin:44px 0 14px; padding-bottom:8px; border-bottom:3px solid var(--accent); }
h3 { font-size:17px; margin:26px 0 8px; }
p, li { font-size:15px; }
.lead { background:#f4f8fd; border-left:4px solid var(--accent); padding:16px 20px; margin:0 0 28px; }
.lead strong { font-size:16px; }
table { width:100%; border-collapse:collapse; margin:14px 0 8px; font-size:14.5px; }
th, td { border:1px solid var(--line); padding:9px 12px; text-align:left; vertical-align:top; }
th { background:#f5f7fa; font-weight:600; }
.purpose { border:1px solid var(--line); border-left:5px solid var(--accent); border-radius:8px;
  padding:16px 20px 18px; margin:16px 0; }
.purpose > b { display:block; font-size:16.5px; margin-bottom:10px; color:var(--accent); }
.pair { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
.pair > div { font-size:14.5px; }
.lbl { display:block; font-weight:600; font-size:12.5px; letter-spacing:.5px; margin-bottom:3px;
  color:var(--muted); }
.purpose .cards { margin:14px 0 0; }
@media (max-width:720px) { .pair { grid-template-columns:1fr; gap:10px; } }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(228px,1fr)); gap:14px; margin:16px 0; }
.card { border:1px solid var(--line); border-radius:9px; padding:14px 16px; }
.card b { display:block; margin-bottom:4px; }
.card span { color:var(--muted); font-size:13.5px; }
.steps { counter-reset:s; list-style:none; padding:0; margin:16px 0; }
.steps li { counter-increment:s; position:relative; padding:0 0 0 44px; margin-bottom:14px; }
.steps li::before { content:counter(s); position:absolute; left:0; top:1px; width:29px; height:29px;
  border-radius:50%; background:var(--accent); color:#fff; text-align:center; line-height:29px; font-size:14px; }
figure.shot { margin:18px 0; }
figure.shot img { width:100%; border:1px solid var(--line); border-radius:7px; display:block; }
figcaption { color:var(--muted); font-size:13px; margin-top:6px; }
.placeholder { border:2px dashed #c3ccd8; border-radius:7px; padding:52px 18px; text-align:center;
  color:var(--muted); font-size:14px; background:#fafbfc; }
.note { background:#fffaf0; border:1px solid #f0dfc0; border-radius:7px; padding:13px 16px; font-size:14px; margin:16px 0; }
.foot { margin-top:44px; padding-top:16px; border-top:1px solid var(--line); color:var(--muted); font-size:13px; }
@media print { body { background:#fff; } .page { padding:0; max-width:none; } }
@media (max-width:720px) { .page { padding:28px 20px 44px; } }
"""


def build(line_shots_dir: Path) -> str:
    today = date.today().isoformat()

    trump = embed(ASSETS / "sample-portrait-trump.jpg")
    drill = embed(ASSETS / "sample-map-drill.jpg")
    garbled = embed(ASSETS / "fail-garbled-title.jpg")
    spec = embed(ASSETS / "safe-frame-spec.png", 1302)
    # 桌面版 LINE 的截圖是橫式視窗，縮到手機直式寬度會小到看不清字，維持原寬滿版。
    shot_input = embed(find_line_shot(line_shots_dir, "貼稿") or Path("nonexistent"), 880)
    shot_output = embed(find_line_shot(line_shots_dir, "收圖") or Path("nonexistent"), 880)

    samples = "".join(
        [
            figure(
                drill,
                "地圖類：由防衛白皮書新聞稿直接生成，含比例尺、指北針、演習名稱與時間，"
                "推測性的範圍一律標「示意」",
                "（成品圖缺漏）",
            ),
            figure(trump, "真人肖像：自動查得參考照片後繪製，並標示「示意圖」", "（成品圖缺漏）"),
        ]
    )

    shots = figure(
        shot_input,
        "步驟二、三：把新聞文字貼進對話框送出，系統立刻回覆「收到」（下午 5:45）",
        "待補：LINE 對話截圖（貼稿）",
    ) + figure(
        shot_output,
        "步驟四：約三分鐘後回傳成品圖，點開即可下載（下午 5:48）",
        "待補：LINE 對話截圖（收圖）",
    )

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AICG 新聞圖卡生成器 — 專案進度報告</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">

<h1>AICG 新聞圖卡生成器 — 專案進度報告</h1>
<p class="sub">TVBS 國際新聞中心｜報告日期 {today}</p>

<div class="lead">
<strong>一句話：工具已經可以做出直接上鏡品質的新聞圖卡，並且做出了手機版（LINE）讓編輯在任何地方都能出圖；
但還停在本機測試階段，尚未部署成多人可用的服務，效益數字也還沒有正式量測。</strong>
</div>

<h2>一、專案進度</h2>

<h3>目前能做到什麼</h3>
<p>編輯把一段新聞文字交給系統，系統自動整理成圖卡文案、選定版型並生成完整圖卡，
四周留白符合電視播出安全框，可直接送進鏡面。目前有兩種操作方式：<strong>網頁版</strong>（功能完整，可逐項微調）
與 <strong>LINE 版</strong>（貼一段文字就出圖，適合突發與外出時使用）。</p>

<h3>本 APP 誕生的目的：要解決哪些問題</h3>
<p>一個目標貫穿整個專案：<strong>讓記者與編輯共用同一套流程，一次就做出可以直接上鏡的新聞圖卡。</strong>
底下三件事，就是這個工具存在的理由。</p>

<div class="purpose">
<b>目的一 · 一鍵生成，不必再各自摸索</b>
<div class="pair">
  <div><span class="lbl">原本的問題</span>
  每位編輯用自己的 Gemini 反覆試，一張圖來回 20–30 分鐘；同一則新聞不同人做出來風格不一致。
  AI 還常自作主張刪改內容、寫出錯字、亂碼或簡體字，改完往往還要進 Photoshop 補一次。</div>
  <div><span class="lbl">現在怎麼解</span>
  貼上新聞原文、按一次，系統自動整理文案、判斷圖表類型、選版型、生成、輸出成品，
  全程不需要有人在旁邊盯著改。所有人共用同一套版型、配色與規則。</div>
</div>
<div class="cards">
  <div class="card"><b>繁體中文不亂碼</b><span>標題與內文用字正確，不再出現亂碼或簡體字。</span></div>
  <div class="card"><b>內容不被亂改</b><span>規則禁止 AI 自行增補新聞沒說的內容，版面留白也不得拿捏造的資訊去填滿。</span></div>
  <div class="card"><b>真人肖像有依據</b><span>具名真人會先找出可用的參考照片再繪製；查不到就一律不畫臉，改用背影並標示示意圖。</span></div>
</div>
{figure(
    garbled,
    "早期失敗案例：標題整排變成無意義的亂碼（「美國会牴刡佈齎発絲动唢」），"
    "內文自己變成英文，連「台灣」都寫成「台濱」。這種圖完全不能上鏡，"
    "而且每次結果都不一樣——這正是「一鍵生成」必須連文字正確性一起解決的原因。",
    "（案例圖缺漏）",
)}
</div>

<div class="purpose">
<b>目的二 · 記者在外面也能馬上做圖</b>
<div class="pair">
  <div><span class="lbl">原本的問題</span>
  一定要回到電腦前、開工具、學會介面才做得出圖。外勤、突發、或人在路上時，等於做不了。</div>
  <div><span class="lbl">現在怎麼解</span>
  做了 LINE 版：<strong>聊天室就是介面</strong>。把新聞文字貼進對話框送出，圖就直接回到對話裡，
  不必開電腦、不必安裝任何東西、也不必學操作。實際流程見第二節。</div>
</div>
</div>

<div class="purpose">
<b>目的三 · 安全框一定符合播出規定</b>
<div class="pair">
  <div><span class="lbl">原本的問題</span>
  電視畫面上下左右必須留白，底部還要留給下標與跑馬燈。這件事交給 AI 自己拿捏完全不可靠——
  試過直接告訴它留多少像素，它把數字當成美術字畫進畫面；改用百分比，又出現標題貼齊上緣、
  資訊條壓進下標區。前後三輪十九張圖，沒有一次穩定達標。</div>
  <div><span class="lbl">現在怎麼解</span>
  改由程式在固定座標上置框，不再請 AI 配合，用的是與公司既有 Studio Locked-Frame 工具
  同一組官方數值。實測四邊全部合格，而且<strong>每次結果都一樣</strong>，不再是抽卡。</div>
</div>
{figure(
    spec,
    "採用的安全框規格：1920×1080 基準下，安全區為 X=140、Y=109、寬 1634、高 751。"
    "四邊刻意不對稱，下方留白最大，是為了預留下標與跑馬燈的位置。",
    "（規格圖缺漏）",
)}
</div>

<div class="note"><strong>要誠實說明的一點：</strong>上面三項都是已經做到的功能，
但「省下多少時間、少了幾次重生」這類效益數字，還沒有在真實編務流程中量測過。
要拿到可信的數字，需要實際試用一段時間並記錄每張圖的耗時與重生次數——這也是下一階段建議優先做的事。</div>

<h3>還沒解決的部分</h3>
<ul>
<li>地圖、數字、日期與資料來源的<strong>自動查核</strong>仍需人工把關</li>
<li>滿意的畫面無法<strong>只改局部</strong>，目前仍是整張重新生成</li>
<li>尚未部署成<strong>多人可用的正式服務</strong>（見第三節）</li>
<li>真人肖像會連參考照片的<strong>姿勢一起複製</strong>，用在特定語境（如訃聞）需人工確認</li>
</ul>

<h3>實際成品</h3>
<p>以下兩張都是系統實際輸出、未經任何人工修圖的成品。</p>
{samples}

<h2>二、LINE 版操作流程</h2>
<p>LINE 版的用意是讓編輯不必開電腦：在手機上貼一段新聞文字就能拿到圖卡，
適合突發新聞或外出時使用。內容規則與網頁版完全相同。</p>

<ol class="steps">
<li><strong>加入官方帳號</strong>——掃 QR code 加好友，只需做一次。</li>
<li><strong>貼上新聞文字</strong>——直接把稿子或素材貼進對話框送出，不需要下任何指令。</li>
<li><strong>系統立刻回覆「收到！AI 消化與生圖中」</strong>——接著在背景整理文案、選版型並生成圖卡。</li>
<li><strong>收到成品圖</strong>——約 30 秒–3 分鐘後回傳，點開即可下載使用。</li>
</ol>

{shots}

<h3>目前的使用限制</h3>
<table>
<tr><th style="width:34%">限制</th><th>說明</th></tr>
<tr><td>一次一則</td><td>沒有排隊機制，多人同時使用會依序處理、等待變長。</td></tr>
<tr><td>等待 30 秒–3 分鐘</td><td>生圖本身需要時間，屬於正常範圍；地圖等複雜圖表偏長。</td></tr>
<tr><td>角色固定為「記者」</td><td>圖表類型由 AI 自動判斷，尚未開放在 LINE 上切換。</td></tr>
<tr><td>網址會變動</td><td>目前是本機測試環境，每次重新啟動連線網址就會改變，需要重新設定一次。</td></tr>
<tr><td>依賴電腦開機</td><td>服務跑在本機，電腦關機或斷網就無法使用——這是目前最大的實用性阻礙。</td></tr>
<tr><td>圖片保留 24 小時</td><td>逾時自動清除，需要留存請即時下載。</td></tr>
</table>

<h2>三、未來拓展</h2>

<table>
<tr><th style="width:22%">項目</th><th style="width:34%">要解決什麼</th><th style="width:18%">額外成本</th><th>初估時程</th></tr>
<tr><td><strong>正式部署</strong></td>
    <td>不再依賴個人電腦開機，網址固定，5–15 人可同時內測使用。</td>
    <td>雲端免費方案可先行，未來視用量而定</td><td>數天</td></tr>
<tr><td><strong>混合版型</strong></td>
    <td>AI 只生成背景畫面，所有中文、數字與資料來源改由程式繪製，從根本消除錯字與數字錯誤。技術原型已完成並驗證通過。</td>
    <td>無額外費用（同樣的生圖次數）</td><td>數週</td></tr>
<tr><td><strong>局部修訂</strong></td>
    <td>滿意的畫面只改其中一塊，不必整張重生，可直接減少生成次數與等待時間。</td>
    <td>無額外費用</td><td>待評估</td></tr>
<tr><td><strong>跨組別延伸</strong></td>
    <td>從編輯台擴及記者、網路新聞與社群，各自需要不同尺寸與風格的版型。</td>
    <td>視版型數量而定</td><td>視推廣節奏</td></tr>
</table>
<p style="color:#5b6676;font-size:13.5px;margin-top:2px;">時程為初步估計，尚未做正式工時評估。</p>

<h3>需要主管決定的事項</h3>
<div class="note">
<strong>正式部署前必須先確認：公司是否允許把 API 金鑰與 LINE 權杖放到外部雲端平台。</strong>
本專案含有台內的 prompt 資產（程式碼倉庫已轉為私有）。
另一個專案已訂下「測試期用雲端、正式期搬回公司內網」的原則，本專案建議沿用，但需要主管確認。
</div>

<h3>建議的下一步</h3>
<ol>
<li>先在小範圍（核心編輯 3–5 人）實際試用兩週，同時記錄每張圖的耗時與重生次數，把效益數字補上</li>
<li>取得金鑰放置的授權後完成部署，解除「依賴電腦開機」這個最大阻礙</li>
<li>再依試用回饋決定混合版型與局部修訂的優先順序</li>
</ol>

<div class="foot">
資料來源：專案原始提案摘要、LINE 版設定文件、混合版型提案，以及實際生成紀錄與驗證紀錄。<br>
本報告由 <code>scripts/build_status_report.py</code> 產生，更新內容或替換圖片後重新執行即可。
</div>

</div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--line-shots",
        default="D:/Downloads",
        help="LINE 對話截圖所在資料夾（檔名含「貼稿」「收圖」）",
    )
    args = parser.parse_args()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(Path(args.line_shots)), encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"已產生 {OUT}（{size_kb:.0f} KB）")


if __name__ == "__main__":
    main()


