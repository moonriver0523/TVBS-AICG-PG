#!/usr/bin/env bash
# LINE Bot 測試環境：cloudflared 隧道 + 後端 8787 + 健康檢查自動重啟
#
# 用法：
#   ./dev-line.sh          預設模式，後端不帶 --reload（穩定優先，測試/demo 用這個）
#   ./dev-line.sh --watch  開發模式，後端帶 --reload（改程式碼自動生效）
#
# 順序很重要：先開隧道拿到網址、寫回 .env，最後才啟動後端。
# 後端是在啟動時載入 .env 的，先啟動就讀不到這次的隧道網址。
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:$PATH"

WATCH=false
[ "${1:-}" = "--watch" ] && WATCH=true

command -v cloudflared >/dev/null || { echo "找不到 cloudflared，請先 brew install cloudflared"; exit 1; }

for KEY in LINE_CHANNEL_SECRET LINE_CHANNEL_ACCESS_TOKEN; do
    if ! grep -qE "^${KEY}=.+" .env 2>/dev/null; then
        echo "⚠️  .env 的 ${KEY} 還沒填，Bot 會回 503。"
        echo "    請先到 LINE Developers Console 取得後填入 .env。"
        exit 1
    fi
done

CLEANED_UP=false
cleanup() {
    $CLEANED_UP && return
    CLEANED_UP=true
    echo ""
    echo "正在關閉..."
    kill "$WATCHDOG_PID" "$TUNNEL_PID" 2>/dev/null || true
    # 用 port 找目前實際的後端 PID，而不是靠 $BACKEND_PID——
    # 看門狗重啟過後端的話，那個變數在這個 shell 裡是舊的，會殺錯或殺不到
    CURRENT_BACKEND=$(lsof -nP -tiTCP:8787 -sTCP:LISTEN 2>/dev/null || true)
    [ -n "$CURRENT_BACKEND" ] && kill $CURRENT_BACKEND 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 清掉殘留在 8787 的舊後端
STALE_PID=$(lsof -nP -tiTCP:8787 -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$STALE_PID" ]; then
    echo "偵測到 8787 殘留後端 (PID $STALE_PID)，先關閉..."
    kill $STALE_PID 2>/dev/null || true
    sleep 1
fi

TUNNEL_LOG=$(mktemp)
echo "開啟 cloudflared 隧道..."
cloudflared tunnel --url http://127.0.0.1:8787 --no-autoupdate > "$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!

PUBLIC_URL=""
for _ in $(seq 1 30); do
    PUBLIC_URL=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -1 || true)
    [ -n "$PUBLIC_URL" ] && break
    sleep 1
done

if [ -z "$PUBLIC_URL" ]; then
    echo "隧道網址取得失敗，log 如下："
    cat "$TUNNEL_LOG"
    exit 1
fi

# 寫回 .env（.env 已被 gitignore，不會進版控）
if grep -q "^PUBLIC_BASE_URL=" .env; then
    sed -i '' "s#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=${PUBLIC_URL}#" .env
else
    echo "PUBLIC_BASE_URL=${PUBLIC_URL}" >> .env
fi

# 2026-07-29 實際發生過：git commit 時 pre-commit 把未暫存的 .py 檔
# stash 到 ~/.cache 再 restore，短時間內兩次寫入同一個被監看的檔案
# （例如 main.py），讓 uvicorn --reload 底層的 watchfiles reloader 崩潰、
# 整個行程被拖死——從外面看不出來（隧道仍活著），demo 前 100 分鐘才發現。
# 查證：watchfiles 的 DefaultFilter 本來就會忽略 .git（ignore_dirs 內建），
# reload 預設也只監看 *.py，所以 static/.omc 本來就不會觸發——
# 真正的病灶是「一般 .py 檔被 stash/restore 兩次」，這件事沒有乾淨的
# reload-exclude 可以擋。所以預設不帶 --reload 才是真正的防護；
# --watch 模式仍有這個風險，只是換來改程式碼即時生效，
# 兩者擇一，靠下面的健康檢查兜底（任何原因崩潰都會在～30秒內自動重啟）。
start_backend() {
    if $WATCH; then
        uv run uvicorn main:app --host 127.0.0.1 --port 8787 --reload &
    else
        uv run uvicorn main:app --host 127.0.0.1 --port 8787 &
    fi
    BACKEND_PID=$!
}

echo "啟動後端 (127.0.0.1:8787)$($WATCH && echo ' [--watch 開發模式]') ..."
start_backend

# 健康檢查：每 15 秒 ping 一次，連續兩次不通就自動重啟並印出明顯警告。
# 本機服務「沒有人在看」時失效是靜默的，這是那個教訓的護欄——
# 上次是靠背景任務的失敗通知才發現後端已經掛了一段時間。
(
    fails=0
    while true; do
        sleep 15
        if curl -s -o /dev/null --max-time 5 http://127.0.0.1:8787/openapi.json; then
            fails=0
        else
            fails=$((fails + 1))
            echo "⚠️  健康檢查失敗（第 $fails 次）：後端沒有回應"
            if [ "$fails" -ge 2 ]; then
                echo "⚠️  後端疑似掛了，自動重啟中...（隧道網址不受影響，不用重貼 webhook）"
                kill "$BACKEND_PID" 2>/dev/null || true
                sleep 1
                start_backend
                fails=0
            fi
        fi
    done
) &
WATCHDOG_PID=$!

sleep 3
echo ""
echo "=================================================="
echo " 把這個網址貼到 LINE Developers Console 的 Webhook URL："
echo ""
echo "   ${PUBLIC_URL}/line/webhook"
echo ""
echo " 貼完按 Verify，應顯示 Success。"
echo " 注意：每次重開隧道網址都會變，要重貼一次。"
echo "=================================================="
echo ""
echo "按 Ctrl+C 可同時關閉隧道、後端與健康檢查。"
wait
