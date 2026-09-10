"""生成紀錄後台：逐筆看「誰、什麼時候、用什麼新聞、生出什麼圖」。

2026-08-25 加。在此之前專案完全沒有任何後台路由，出事只能 ssh 進容器翻 JSONL，
而容器磁碟每次部署就清空，等於沒有紀錄可翻。

設計取捨：
- 獨立成一支模組、由 main.py 呼叫 register(app)，把 main.py 的改動壓到兩行。
- 設了 ADMIN_PASSWORD 才掛載路由。不設就完全沒有 /admin 這條路徑（404），
  沿用專案「預設不改變既有部署」的慣例。
- 後台密碼與 SITE_PASSWORD 分開：站台密碼是全體同仁都知道的，後台看得到所有人的
  產出（含新聞原文），不該用同一組。
- 純伺服器端渲染的 HTML，不引入前端框架。這頁是內部稽核用，能看、能篩、能點開圖
  就夠了，不值得為它增加建置流程。
"""

import base64
import hmac
import html
import os

from fastapi import Header, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

import audit_archive

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()

_UNAUTHORIZED = Response(
    content="需要後台密碼",
    status_code=401,
    headers={"WWW-Authenticate": 'Basic realm="TVBS AICG Admin"'},
    media_type="text/plain; charset=utf-8",
)


def _authorized(request: Request) -> bool:
    header = request.headers.get("authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
    except Exception:  # noqa: BLE001
        return False
    # 與站台密碼門一致：帳號欄不檢查，只認密碼。
    _, _, supplied = decoded.partition(":")
    return hmac.compare_digest(supplied, ADMIN_PASSWORD)


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _row(record: dict) -> str:
    # 姓名與 email 都顯示：姓名好認人，email 是唯一的（同名同姓分得開）。
    name = record.get("user_name", "")
    email = record.get("user_email", "")
    if name and email:
        who = f'{_esc(name)}<br><span class="muted">{_esc(email)}</span>'
    else:
        who = _esc(name or email or "（未署名）")
    month = record.get("_month", "")
    image_file = record.get("image_file", "")
    if image_file and month:
        thumb = (
            f'<a href="/admin/image/{_esc(month)}/{_esc(image_file)}" target="_blank">'
            f'<img src="/admin/image/{_esc(month)}/{_esc(image_file)}" loading="lazy"></a>'
        )
    else:
        thumb = '<span class="muted">無圖</span>'

    news = _esc(record.get("news_text", ""))
    prompt = _esc(record.get("prompt", ""))
    return f"""
    <tr>
      <td class="nowrap">{_esc(record.get("ts", ""))[:19].replace("T", " ")}</td>
      <td class="who">{who}</td>
      <td class="nowrap">{_esc(record.get("type_label") or record.get("chart_type"))}</td>
      <td class="thumb">{thumb}</td>
      <td class="text">
        <details><summary>新聞原文（{len(record.get("news_text", "") or "")} 字）</summary>
          <pre>{news}</pre></details>
        <details><summary>最終 prompt</summary><pre>{prompt}</pre></details>
        <div class="meta muted">
          model: {_esc(record.get("image_model"))} ·
          provider: {_esc(record.get("provider"))} ·
          id: {_esc(record.get("request_id"))}
        </div>
      </td>
    </tr>"""


_STYLE = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, "Noto Sans TC", sans-serif; margin: 0; padding: 24px;
       background: Canvas; color: CanvasText; }
h1 { font-size: 20px; margin: 0 0 4px; }
.bar { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; margin: 16px 0; }
label { font-size: 12px; display: block; opacity: .7; margin-bottom: 2px; }
input, select { padding: 6px 8px; font-size: 14px; }
button { padding: 7px 14px; font-size: 14px; cursor: pointer; }
.wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border-bottom: 1px solid rgba(128,128,128,.3); padding: 8px; text-align: left;
         vertical-align: top; }
th { position: sticky; top: 0; background: Canvas; }
.nowrap { white-space: nowrap; }
.who { font-weight: 600; }
.thumb img { max-width: 200px; height: auto; border-radius: 4px; display: block; }
.text { max-width: 640px; }
pre { white-space: pre-wrap; word-break: break-word; margin: 6px 0; padding: 8px;
      background: rgba(128,128,128,.12); border-radius: 4px; max-height: 240px;
      overflow: auto; font-size: 12px; }
summary { cursor: pointer; font-size: 12px; }
.meta { font-size: 11px; margin-top: 6px; }
.muted { opacity: .6; }
.empty { padding: 40px; text-align: center; opacity: .6; }
"""


def _page(records: list[dict], months: list[str], month: str, user: str) -> str:
    options = ['<option value="">全部月份</option>']
    for value in months:
        selected = " selected" if value == month else ""
        options.append(f'<option value="{_esc(value)}"{selected}>{_esc(value)}</option>')

    if records:
        body = f"""<div class="wrap"><table>
        <thead><tr><th>時間</th><th>使用者</th><th>類型</th><th>成圖</th><th>內容</th></tr></thead>
        <tbody>{"".join(_row(r) for r in records)}</tbody></table></div>"""
    else:
        body = '<p class="empty">沒有符合條件的紀錄。</p>'

    return f"""<!doctype html><html lang="zh-Hant"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AICG 生成紀錄後台</title><style>{_STYLE}</style></head><body>
<h1>AICG 生成紀錄</h1>
<p class="muted">顯示 {len(records)} 筆（上限 200 筆，用篩選縮小範圍）</p>
<form class="bar" method="get">
  <div><label>月份</label><select name="month">{"".join(options)}</select></div>
  <div><label>使用者（email 或姓名，部分符合即可）</label>
       <input name="user" value="{_esc(user)}" placeholder="全部"></div>
  <button type="submit">篩選</button>
</form>
{body}
</body></html>"""


def register(app) -> None:
    """把後台路由掛上去。沒設 ADMIN_PASSWORD 就什麼都不掛。"""
    if not ADMIN_PASSWORD:
        return

    @app.get("/admin", response_class=HTMLResponse)
    def admin_index(request: Request, month: str = "", user: str = ""):
        if not _authorized(request):
            return _UNAUTHORIZED
        if not audit_archive.ENABLED:
            return PlainTextResponse(
                "尚未設定 AUDIT_ARCHIVE_DIR，沒有歸檔可看。", status_code=503
            )
        records = audit_archive.list_records(month=month, limit=200, user=user)
        return HTMLResponse(
            _page(records, audit_archive.available_months(), month, user)
        )

    @app.get("/admin/image/{month}/{filename}")
    def admin_image(request: Request, month: str, filename: str):
        if not _authorized(request):
            return _UNAUTHORIZED
        found = audit_archive.read_image(month, filename)
        if found is None:
            raise HTTPException(status_code=404, detail="找不到這張圖")
        data, mime = found
        return Response(content=data, media_type=mime)
