#!/usr/bin/env bash
# 本機全 OpenAI 版：消化與生圖都走使用者自己的 OPENAI_API_KEY，完全不碰 OpenRouter。
#
# 存在理由：2026-09-05 起本機那把 OPENROUTER_API_KEY 回 401 User not found，
# dev-local.sh 會改去 Secret Manager 取雲端那把，等於本機測試仍打雲端帳單與雲端配額。
# 使用者要的是「本機所有測試都用 OpenAI key」，所以這支把兩個後端都釘成原生。
#
# 為什麼要明寫 DIGEST_BACKEND=native 而不是只把 key 拿掉：main.py 的後端選擇
# 以 DIGEST_BACKEND 為準（2026-09-03 修的坑），而 OPENROUTER_API_KEY 同時存在於
# .env 與 Windows 使用者環境變數，光註解 .env 沒有用——所以這裡連 unset 一起做。
#
# 安全框需要 21:9，原生 OpenAI 生圖的 NATIVE_GPT_IMAGE_SIZES 有 21:9（1680x720），
# 這條路走得通。差別是原生路徑送不出多張參考圖（見 supports_multiple_reference_images）,
# 需要多張參考圖時仍得回頭走 OpenRouter。
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8788}"

if [ -z "$OPENAI_API_KEY" ]; then
    echo "找不到 OPENAI_API_KEY（應在 Windows 使用者環境變數裡）。" >&2
    exit 1
fi

# 埠被佔住就停下報告，不自作主張砍別人的 process（dev-local.sh 的同一條教訓：
# 綁定失敗但舊 server 還在，curl 拿得到 200，驗收的其實是舊程式）。
BUSY=$(netstat -ano 2>/dev/null | grep "LISTENING" | grep ":${PORT} " | awk '{print $NF}' | head -1 || true)
if [ -n "$BUSY" ]; then
    echo "埠 ${PORT} 已被 PID ${BUSY} 佔用，這支腳本不會替你砍掉它。" >&2
    echo "換一個埠：PORT=8789 $0" >&2
    exit 1
fi

unset OPENROUTER_API_KEY
export DIGEST_BACKEND=native
export IMAGE_BACKEND=native
# gpt-5.6-terra（原生預設）在本機實測會洩漏頻道標記與簡體垃圾語料，改用 sol。
export DIGEST_MODEL="${DIGEST_MODEL:-gpt-5.6-sol}"

echo "本機全 OpenAI 版：http://127.0.0.1:${PORT}"
echo "  第一頁 http://127.0.0.1:${PORT}/    一鍵成圖 http://127.0.0.1:${PORT}/hybrid.html"
echo "  消化 ${DIGEST_MODEL}｜生圖 原生 OpenAI｜OpenRouter 已停用"
exec ./.venv/Scripts/uvicorn.exe main:app --host 127.0.0.1 --port "$PORT"
