#!/usr/bin/env bash
# 本機起一份完整的網頁版（Windows / Git Bash 適用）。
#
# 存在理由：每改一條 prompt 規則就 deploy 一次 Cloud Run，一輪要好幾分鐘，
# 而這些改動九成是純文字規則，本機跑起來一模一樣。雲端只在要驗真正的部署
# 行為（revision、secret、流量）時才需要。
#
# 金鑰：本機 Windows 使用者環境變數裡那把 OPENROUTER_API_KEY 已失效
# （2026-09-05 實測 401 User not found），所以改成啟動時從 Secret Manager
# 取用。值只存在於這個 process 的環境變數裡，不列印、不寫檔。
#
# 前端的 X-API-Key：app.js 進 git 的是占位字串 __NEWS_IMAGE_API_KEY__，
# 容器啟動時才由 entrypoint.sh 換掉。本機的 .env 刻意把 NEWS_IMAGE_API_KEY
# 設成同一個占位字串，所以前後端對得上，不需要 sed。
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8787}"

# 埠被佔住就直接停下來報告，不要自作主張砍別人的 process。
# 2026-09-05 踩到：8787 上有一個兩天前啟動的 python，砍不掉（權限）但腳本印了
# 「先關閉...」就繼續往下跑，uvicorn 綁定失敗自己退出，而 curl 仍然拿得到 200
# ——回應來自那個舊 server。這種「看起來活著、其實跑的是舊程式」最會誤導驗收。
BUSY=$(netstat -ano 2>/dev/null | grep "LISTENING" | grep ":${PORT} " | awk '{print $NF}' | head -1 || true)
if [ -n "$BUSY" ]; then
    echo "埠 ${PORT} 已被 PID ${BUSY} 佔用，這支腳本不會替你砍掉它。" >&2
    echo "要嘛先自行確認並關閉那個 process，要嘛換一個埠：PORT=8788 $0" >&2
    exit 1
fi

if [ -z "$OPENROUTER_API_KEY" ] || [ "${FORCE_SECRET:-}" = "1" ]; then
    echo "從 Secret Manager 取 OPENROUTER_API_KEY..."
    OPENROUTER_API_KEY="$(gcloud secrets versions access latest --secret=OPENROUTER_API_KEY)"
    export OPENROUTER_API_KEY
fi

echo "啟動本機後端：http://127.0.0.1:${PORT}"
echo "  第一頁 http://127.0.0.1:${PORT}/    一鍵成圖 http://127.0.0.1:${PORT}/hybrid.html"
exec ./.venv/Scripts/uvicorn.exe main:app --host 127.0.0.1 --port "$PORT"
