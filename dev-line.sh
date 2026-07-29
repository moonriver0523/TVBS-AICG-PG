#!/usr/bin/env bash
# LINE Bot 測試環境：cloudflared 隧道 + 後端 8787
#
# 順序很重要：先開隧道拿到網址、寫回 .env，最後才啟動後端。
# 後端是在啟動時載入 .env 的，先啟動就讀不到這次的隧道網址。
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:$PATH"

command -v cloudflared >/dev/null || { echo "找不到 cloudflared，請先 brew install cloudflared"; exit 1; }

for KEY in LINE_CHANNEL_SECRET LINE_CHANNEL_ACCESS_TOKEN; do
    if ! grep -qE "^${KEY}=.+" .env 2>/dev/null; then
        echo "⚠️  .env 的 ${KEY} 還沒填，Bot 會回 503。"
        echo "    請先到 LINE Developers Console 取得後填入 .env。"
        exit 1
    fi
done

cleanup() {
    echo ""
    echo "正在關閉..."
    kill "$TUNNEL_PID" "$BACKEND_PID" 2>/dev/null || true
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

echo "啟動後端 (127.0.0.1:8787) ..."
uv run uvicorn main:app --host 127.0.0.1 --port 8787 &
BACKEND_PID=$!

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
echo "按 Ctrl+C 可同時關閉隧道與後端。"
wait
