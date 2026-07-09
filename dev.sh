#!/usr/bin/env bash
# 一次啟動後端代理（8787）與前端即時預覽（3000）
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:$PATH"

cleanup() {
    echo ""
    echo "正在關閉伺服器..."
    kill "$UVICORN_PID" "$BROWSERSYNC_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

echo "啟動後端代理 (http://127.0.0.1:8787) ..."
uv run uvicorn main:app --host 127.0.0.1 --port 8787 &
UVICORN_PID=$!

echo "啟動前端即時預覽 (http://localhost:3000) ..."
npx --yes browser-sync start --server --files "index.html, app.js" --port 3000 &
BROWSERSYNC_PID=$!

echo ""
echo "兩個伺服器都已啟動。按 Ctrl+C 可同時關閉。"
wait
