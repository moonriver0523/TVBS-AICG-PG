"""端到端驗證安全框置框：新聞原文 → 消化 → 滿版 prompt → 生圖 → 置框 → 量測。

用途有二：
1. 補齊 GPT 側的置框實測（B/A 兩階段都只測到 Gemini，因為 OpenRouter 撞週用量上限）。
2. 為「21:9 要不要成為 safe_frame 模式預設」累積樣本——目前 16:9 與 21:9 各只有 1 張，
   而 R4 分析的教訓是 n=1～2 的差異會被模型隨機性淹沒。

金鑰：若 .env 有 OPENAI_API_KEY_ALT，本腳本會改用它（讓另一把 OpenAI 金鑰可以單獨拿來
測試，不必動到 production 用的 OPENAI_API_KEY）。金鑰一律只從環境讀，不接受命令列傳入。

預設乾跑。要真的呼叫付費 API 必須明確加 --go。

用法：
    uv run python scripts/verify_safe_frame_e2e.py --provider gpt
    uv run python scripts/verify_safe_frame_e2e.py --provider gpt --samples 2 --go
    uv run python scripts/verify_safe_frame_e2e.py --provider gemini --aspect 21:9 --samples 4 --go
"""

import argparse
import base64
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

load_dotenv()

DEFAULT_OUT_DIR = SCRIPT_DIR / "output"

# 固定素材：與 B 階段 fixture 同一則，讓跨輪結果可比。
# 內容為版面測試示意用途，數據是虛構的圓整數字，不得播出。
NEWS_TEXT = """國際咖啡組織最新報告指出，全球咖啡豆期貨均價連續三個季度走高，
最新一期均價達每磅3.8美元，創近期新高。主要產區受氣候影響減產約12%，
是本波漲勢的主因。零售端價格反映通常落後約兩個月，分析師認為成本壓力尚未見頂。"""


def prepare_environment(provider: str, transport: str) -> list[str]:
    """套用金鑰與後端設定，回傳給人看的設定摘要（不含任何金鑰內容）。"""
    notes = []

    alt_key = os.getenv("OPENAI_API_KEY_ALT", "").strip()
    if alt_key:
        os.environ["OPENAI_API_KEY"] = alt_key
        notes.append("OpenAI 金鑰：使用 OPENAI_API_KEY_ALT")
    else:
        notes.append("OpenAI 金鑰：使用 OPENAI_API_KEY（未設 OPENAI_API_KEY_ALT）")

    if transport == "native":
        # 生圖走原生。digest 也必須避開 OpenRouter，否則撞週用量上限直接 403。
        os.environ["IMAGE_BACKEND"] = "native"
        os.environ["OPENROUTER_API_KEY"] = ""
        notes.append("傳輸層：原生（生圖與消化都不經 OpenRouter）")
        notes.append(
            "生圖模型："
            + (
                os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
                if provider == "gpt"
                else os.getenv("GEMINI_IMAGE_MODEL", "gemini-3-pro-image")
            )
        )
    else:
        os.environ["IMAGE_BACKEND"] = "openrouter"
        notes.append("傳輸層：OpenRouter（與 production 相同；注意週用量上限）")

    return notes


def run_once(provider: str, aspect: str, index: int, out_dir: Path) -> Path:
    from main import NewsImageGenerateRequest, generate_news_image

    result = generate_news_image(
        NewsImageGenerateRequest(
            news_text=NEWS_TEXT,
            role="記者",
            density="standard",
            provider=provider,
            aspect_ratio=aspect,
            safe_frame=True,
        )
    )
    stem = f"{date.today().isoformat()}-e2e-{provider}-{aspect.replace(':', 'x')}-{index}"
    path = out_dir / f"{stem}.png"
    path.write_bytes(base64.b64decode(result.image_data_base64))
    print(f"  ✓ {path.name}（{result.model}）標題：{result.title or '（未取到）'}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="端到端驗證安全框置框")
    parser.add_argument("--provider", choices=("gpt", "gemini"), default="gpt")
    parser.add_argument("--aspect", default="16:9", help="送給模型的長寬比，例如 16:9 或 21:9")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument(
        "--transport",
        choices=("native", "openrouter"),
        default="native",
        help="預設 native：OpenRouter 週用量上限未解時唯一可行的路",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--go", action="store_true", help="真的呼叫付費 API（預設只乾跑）")
    args = parser.parse_args()

    notes = prepare_environment(args.provider, args.transport)
    print(f"provider={args.provider} aspect={args.aspect} samples={args.samples}")
    for note in notes:
        print(f"  - {note}")
    print("  - safe_frame=True（滿版生成後由 safe_frame.py 置框，輸出 1920×1080）")

    if not args.go:
        print("\n=== 乾跑，未呼叫任何 API ===")
        print(f"將產生 {args.samples} 張圖並逐邊量測。確認無誤後加 --go。")
        return

    args.out_dir.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []
    for index in range(1, args.samples + 1):
        print(f"\n▶ 第 {index}/{args.samples} 張 …", flush=True)
        try:
            produced.append(run_once(args.provider, args.aspect, index, args.out_dir))
        except Exception as exc:  # noqa: BLE001 — 單張失敗不該讓整輪白跑
            print(f"  ✗ {type(exc).__name__}: {exc}")

    if not produced:
        raise SystemExit("沒有任何圖產生，請看上面的錯誤訊息")

    # 量測沿用同一支工具，判定基準與 error-cases 各輪一致
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "measure_safe_area", SCRIPT_DIR / "measure_safe_area.py"
    )
    measure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measure)

    print("\n=== 逐邊量測（基準 上10.09/左7.29/右7.60/下20.37%）===")
    verdicts = []
    for path in produced:
        result = measure.measure(path)
        if "error" in result:
            print(f"{path.name}: {result['error']}")
            continue
        pct = result["measured_pct"]
        print(
            f"{path.name}\n  上{pct['top']:5.2f} 左{pct['left']:5.2f} "
            f"右{pct['right']:5.2f} 下{pct['bottom']:5.2f} → {result['overall']}"
        )
        verdicts.append(result["overall"])

    passed = sum(1 for v in verdicts if v == "pass")
    wasteful = sum(1 for v in verdicts if v == "wasteful")
    failed = sum(1 for v in verdicts if v == "fail")
    print(f"\n合計：完全合格 {passed}／合格但過縮 {wasteful}／不合格 {failed}")
    if failed:
        print("⚠️ 出現不合格：置框是純數學運算，理論上不該失敗，請檢查來源圖與 overlay")


if __name__ == "__main__":
    main()
