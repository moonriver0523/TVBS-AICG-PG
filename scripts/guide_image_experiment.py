"""B 階段：安全框「參考圖引導」實驗執行器。

問題背景：像素版、百分比版、純文字版三輪 prompt 實驗都撞到同一面牆——
模型看得懂安全框要求，但做不到空間精準；寫成數字還會被畫進圖裡。
（見 docs/error-cases/ 三份分析文件。）本階段換通道：不在文字裡講留白，
改用「圖」告訴模型內容該落在哪。

三種機制對照：
1. baseline —— 現行 main 的純文字安全框規則，什麼圖都不附。對照組。
2. guide  —— 同樣的 prompt，額外附一張安全框引導圖（OpenRouter `input_references`）。
              與 baseline 的唯一差異就是多了圖片通道，A/B 乾淨。
3. mask   —— OpenAI native `images.edit`＋遮罩：遮罩不透明處 API 保證不動，
              留白由介面硬性保證而非模型自律。這一 arm 會改用「畫滿可編輯區」的
              指示並移除文字留白規則，否則會二次縮小造成過縮浪費。

模型一致性：guide/baseline 兩組都走 production 現行的 OpenRouter 模型
（OPENROUTER_GPT_MODEL／OPENROUTER_GEMINI_MODEL），所以差異不會混入模型變因。
mask 組因為 OpenRouter 圖片端點不支援遮罩，只能走 OpenAI 原生模型，
這是已知且必須在報告中揭露的變因。

預設是乾跑（只印出要做什麼、不花錢）。要真的呼叫付費 API 必須明確加 --go。

用法：
    uv run python scripts/guide_image_experiment.py                    # 乾跑，看清單
    uv run python scripts/guide_image_experiment.py --go               # 實際生成 core 輪
    uv run python scripts/guide_image_experiment.py --round full --go
    uv run python scripts/guide_image_experiment.py --arms gpt-mask --go
    uv run python scripts/guide_image_experiment.py --capture-digest "<新聞原文>"
"""

import argparse
import base64
import json
import os
import ssl
import sys
import time
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import news_prompt  # noqa: E402  （需先加入專案根目錄到 sys.path）

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
ASSET_DIR = SCRIPT_DIR / "assets"
FIXTURE_DIR = SCRIPT_DIR / "fixtures"
DEFAULT_FIXTURE = FIXTURE_DIR / "digest-layout-test.json"
DEFAULT_OUT_DIR = SCRIPT_DIR / "output"

CANVAS = (1280, 720)

# 附引導圖時追加的說明。刻意不提任何數字，也明確聲明引導圖不是配色／風格參考——
# 「引導圖顏色滲進輸出」是本輪要偵測的失敗型態之一。
GUIDE_IMAGE_CLAUSE = """
==================================================
ATTACHED LAYOUT GUIDE
==================================================
- The attached image is a LAYOUT GUIDE ONLY. It is not a style, colour, or content reference.
- Never reproduce the guide's colours, blocks, outlines, or shapes in the output.
- Read it purely as a map of where content may go: place the entire infographic inside the region the guide marks as usable, and leave the surrounding region as plain continuous background with nothing in it.
- The guide's proportions are authoritative. If any instruction elsewhere conflicts with the guide's usable region, follow the guide."""

# mask arm 專用：留白已由 API 遮罩保證，若再要求模型自己留邊會二次縮小（過縮浪費）。
MASK_FILL_CLAUSE = """
==================================================
EDITABLE REGION (OVERRIDES ALL LAYOUT MARGIN INSTRUCTIONS)
==================================================
- Fill the entire editable region of the canvas with the infographic, edge to edge within that region.
- Do not add any further inner margin of your own; the surrounding area is already reserved outside your control.
- IGNORE every instruction anywhere above about scaling the design down, keeping it in a central region, or leaving empty margins, borders, or reserved bands. Those margins already exist outside the editable region and must not be duplicated inside it.
- Compose so the design reads as complete and balanced within the editable region."""

# AI 消化被強制要求 structure 必須以這句開頭（來源：main.py 的 SYSTEM_PROMPT_TEMPLATE／
# EDITOR_SYSTEM_PROMPT_TEMPLATE）。mask arm 要把它拿掉，否則遮罩留白之外又縮一次。
# tests/test_guide_experiment.py 會驗這兩句仍與 main.py 逐字相同，防止漂移。
MANDATED_STRUCTURE_SENTENCE_REPORTER = (
    "The entire infographic — including the title, icon cards, and side panels — is treated "
    "as one group and scaled down so it occupies only the central region of the frame, "
    "surrounded by a thick, clearly visible empty margin of unchanged background on the top, "
    "left and right, and an even deeper empty band along the bottom; every element stays well "
    "inside this central zone and nothing reaches into the surrounding empty border."
)
MANDATED_STRUCTURE_SENTENCE_EDITOR = (
    "The entire infographic — including the title, icon cards, and data charts — is treated "
    "as one group and scaled down so it occupies only the central region of the frame, "
    "surrounded by a thick, clearly visible empty margin of unchanged background on the top, "
    "left and right, and an even deeper empty band along the bottom; every element stays well "
    "inside this central zone and nothing reaches into the surrounding empty border."
)


ARMS: dict[str, dict[str, str]] = {
    "gemini-baseline": {"provider": "gemini", "mechanism": "baseline", "guide": ""},
    "gpt-baseline": {"provider": "gpt", "mechanism": "baseline", "guide": ""},
    "gemini-guide-wireframe": {
        "provider": "gemini",
        "mechanism": "guide",
        "guide": "wireframe",
    },
    "gemini-guide-twotone": {"provider": "gemini", "mechanism": "guide", "guide": "twotone"},
    "gemini-guide-chroma": {"provider": "gemini", "mechanism": "guide", "guide": "chroma"},
    "gpt-guide-wireframe": {"provider": "gpt", "mechanism": "guide", "guide": "wireframe"},
    "gpt-guide-twotone": {"provider": "gpt", "mechanism": "guide", "guide": "twotone"},
    "gpt-mask": {"provider": "gpt", "mechanism": "mask", "guide": "edit-mask"},
}

ROUNDS: dict[str, tuple[str, ...]] = {
    # 回答核心問題所需的最小組合：兩個對照組＋兩個引導組（同引導圖跨兩家）＋硬約束組
    "core": (
        "gemini-baseline",
        "gpt-baseline",
        "gemini-guide-wireframe",
        "gpt-guide-wireframe",
        "gpt-mask",
    ),
    # 加上抽象色塊引導與滲色偵測
    "full": (
        "gemini-baseline",
        "gpt-baseline",
        "gemini-guide-wireframe",
        "gpt-guide-wireframe",
        "gemini-guide-twotone",
        "gpt-guide-twotone",
        "gemini-guide-chroma",
        "gpt-mask",
    ),
}


def load_digest(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in ("role", "chart_type", "style", "structure", "variable") if k not in data]
    if missing:
        raise SystemExit(f"fixture 缺欄位：{missing}")
    return data


def capture_digest(news_text: str, out_path: Path, role: str, density: str, type_label: str) -> None:
    """呼叫 production 的消化流程並存成 fixture。這會呼叫付費 API。"""
    from main import GenerateRequest, generate  # 延後匯入，乾跑時不需要金鑰

    result = generate(
        GenerateRequest(
            news_text=news_text, type_label=type_label, role=role, density=density
        )
    )
    payload = {
        "_note": f"以 --capture-digest 實際擷取（{date.today().isoformat()}）",
        "role": role,
        "type_label": type_label,
        "chart_type": result.chart_type or type_label,
        "style": result.style,
        "structure": result.structure,
        "variable": result.variable,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已寫出 fixture：{out_path}")
    if "%" in result.structure:
        print("⚠️ structure 出現 '%'，與消化規則相違，請人工檢視後再用於實驗")


def build_arm_prompt(digest: dict[str, str], arm: str) -> str:
    """組出該 arm 的完整 prompt。baseline 與 production 逐字相同。"""
    config = ARMS[arm]
    role = digest["role"]
    structure = digest["structure"]

    if config["mechanism"] == "mask":
        # 消化強制的「縮小置中留厚邊」開頭句與遮罩機制衝突，先拿掉再組。
        mandated = (
            MANDATED_STRUCTURE_SENTENCE_EDITOR
            if role == "編輯"
            else MANDATED_STRUCTURE_SENTENCE_REPORTER
        )
        if mandated in structure:
            structure = structure.replace(mandated, "").lstrip()
        else:
            print(f"  ⚠️ {arm}：structure 沒有預期的強制開頭句，遮罩組可能出現二次縮小")

    prompt = news_prompt.build_prompt(
        role=role,
        engine=config["provider"],
        type_label=digest.get("chart_type") or digest.get("type_label", ""),
        style=digest["style"],
        structure=structure,
        variable=news_prompt.compose_variable(digest["variable"]),
    )

    if config["mechanism"] == "guide":
        return prompt + "\n" + GUIDE_IMAGE_CLAUSE

    if config["mechanism"] == "mask":
        # 從 production prompt 中拿掉文字版留白規則（來源同一份常數，不會漂移）
        safe_block = (
            news_prompt.EDITOR_SAFE_AREA if role == "編輯" else news_prompt.REPORTER_SAFE_AREA
        )
        if safe_block not in prompt:
            raise SystemExit("找不到安全框段落，news_prompt 可能已改動，請同步本腳本")
        prompt = prompt.replace(safe_block + "\n\n", "").replace(safe_block, "")
        canvas_line = (
            "- Scale the whole design down so it fills only the central region, "
            "surrounded by a thick empty margin on every side (deeper at the bottom); "
            "when unsure, make the margin bigger, never smaller\n"
        )
        if canvas_line not in prompt:
            raise SystemExit("找不到 CANVAS 留白句，news_prompt 可能已改動，請同步本腳本")
        prompt = prompt.replace(canvas_line, "")
        return prompt + "\n" + MASK_FILL_CLAUSE

    return prompt


def guide_path(variant: str) -> Path:
    path = ASSET_DIR / f"safe-guide-{variant}-{CANVAS[0]}x{CANVAS[1]}.png"
    if not path.exists():
        raise SystemExit(f"缺引導圖 {path}，請先執行 scripts/make_safe_frame_guide.py")
    return path


def data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def call_openrouter(model: str, prompt: str, guide: Path | None, image_size: str) -> tuple[str, str]:
    """呼叫 OpenRouter 圖片端點，回傳 (base64 圖, media_type)。附圖走 input_references。"""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("缺 OPENROUTER_API_KEY")

    payload: dict[str, object] = {"model": model, "prompt": prompt, "aspect_ratio": "16:9"}
    if any(tag in model for tag in ("gemini", "seedream", "riverflow")):
        payload["resolution"] = image_size
    if guide is not None:
        payload["input_references"] = [
            {"type": "image_url", "image_url": {"url": data_url(guide)}}
        ]

    request = Request(
        "https://openrouter.ai/api/v1/images",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urlopen(request, timeout=240, context=context) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"OpenRouter 失敗 {exc.code}：{body}") from exc
    except (URLError, TimeoutError) as exc:
        raise SystemExit(f"OpenRouter 連線失敗：{exc}") from exc

    data = result.get("data") or []
    item = data[0] if data else {}
    if not item.get("b64_json"):
        raise SystemExit(f"OpenRouter 未回傳圖片：{json.dumps(result)[:400]}")
    return item["b64_json"], item.get("media_type", "image/png")


def call_openai_edit(prompt: str) -> tuple[str, str, str]:
    """OpenAI native images.edit＋遮罩。回傳 (base64 圖, media_type, model)。"""
    from openai import OpenAI

    model = os.getenv("OPENAI_EDIT_MODEL", os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2"))
    base = guide_path("edit-base")
    mask = guide_path("edit-mask")
    client = OpenAI()
    with base.open("rb") as image_file, mask.open("rb") as mask_file:
        result = client.images.edit(
            model=model,
            image=image_file,
            mask=mask_file,
            prompt=prompt,
            size=f"{CANVAS[0]}x{CANVAS[1]}",
            quality=os.getenv("OPENAI_IMAGE_QUALITY", "medium"),
            output_format="png",
        )
    if not result.data or not result.data[0].b64_json:
        raise SystemExit("OpenAI images.edit 未回傳圖片")
    return result.data[0].b64_json, "image/png", model


def run_arm(arm: str, digest: dict[str, str], out_dir: Path, image_size: str) -> dict[str, object]:
    config = ARMS[arm]
    prompt = build_arm_prompt(digest, arm)
    started = time.time()

    if config["mechanism"] == "mask":
        b64, media_type, model = call_openai_edit(prompt)
    else:
        env_key = "OPENROUTER_GPT_MODEL" if config["provider"] == "gpt" else "OPENROUTER_GEMINI_MODEL"
        default = (
            "openai/gpt-5.4-image-2"
            if config["provider"] == "gpt"
            else "google/gemini-3-pro-image"
        )
        model = os.getenv(env_key, default)
        guide = guide_path(config["guide"]) if config["guide"] else None
        b64, media_type = call_openrouter(model, prompt, guide, image_size)

    suffix = "jpg" if "jpeg" in media_type else "png"
    stem = f"{date.today().isoformat()}-guide-{arm}"
    image_path = out_dir / f"{stem}.{suffix}"
    image_path.write_bytes(base64.b64decode(b64))
    (out_dir / f"{stem}.prompt.txt").write_text(prompt, encoding="utf-8")

    return {
        "arm": arm,
        "mechanism": config["mechanism"],
        "provider": config["provider"],
        "guide": config["guide"],
        "model": model,
        "image": str(image_path),
        "prompt_chars": len(prompt),
        "elapsed_sec": round(time.time() - started, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="安全框參考圖引導實驗")
    parser.add_argument("--round", choices=tuple(ROUNDS), default="core")
    parser.add_argument("--arms", help="逗號分隔的 arm 名稱，指定時覆寫 --round")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--image-size", default="1K")
    parser.add_argument("--go", action="store_true", help="真的呼叫付費 API（預設只乾跑）")
    parser.add_argument("--capture-digest", metavar="NEWS_TEXT", help="擷取真實 digest 存成 fixture")
    parser.add_argument("--role", default="記者")
    parser.add_argument("--density", default="standard")
    parser.add_argument("--type-label", default="資料圖表")
    args = parser.parse_args()

    if args.capture_digest:
        capture_digest(
            args.capture_digest, args.fixture, args.role, args.density, args.type_label
        )
        return

    digest = load_digest(args.fixture)
    if args.arms:
        arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
        unknown = [a for a in arms if a not in ARMS]
        if unknown:
            raise SystemExit(f"未知 arm：{unknown}（可用：{list(ARMS)}）")
    else:
        arms = ROUNDS[args.round]

    print(f"fixture：{args.fixture.name}（{digest['role']}／{digest.get('chart_type')}）")
    print(f"arms（{len(arms)}）：{', '.join(arms)}")

    if not args.go:
        print("\n=== 乾跑，未呼叫任何 API ===")
        for arm in arms:
            config = ARMS[arm]
            prompt = build_arm_prompt(digest, arm)
            has_safe = news_prompt.REPORTER_SAFE_AREA in prompt or news_prompt.EDITOR_SAFE_AREA in prompt
            print(
                f"  {arm:24} 機制={config['mechanism']:<8} 引導圖={config['guide'] or '無':<10} "
                f"prompt={len(prompt)}字 文字留白規則={'有' if has_safe else '無'}"
            )
        print("\n確認無誤後加 --go 實際生成。")
        return

    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "date": date.today().isoformat(),
        "fixture": str(args.fixture),
        "prompt_version": news_prompt.PROMPT_VERSION,
        "canvas": list(CANVAS),
        "image_size": args.image_size,
        "runs": [],
    }
    for arm in arms:
        print(f"\n▶ {arm} …", flush=True)
        try:
            record = run_arm(arm, digest, args.out_dir, args.image_size)
        except SystemExit as exc:  # 單一 arm 失敗不該讓整輪白跑
            print(f"  ✗ {exc}")
            manifest["runs"].append({"arm": arm, "error": str(exc)})
            continue
        print(f"  ✓ {record['image']}（{record['elapsed_sec']}s，{record['model']}）")
        manifest["runs"].append(record)

    manifest_path = args.out_dir / f"{date.today().isoformat()}-guide-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n清單：{manifest_path}")
    print("下一步量測：uv run python scripts/measure_safe_area.py "
          f"{args.out_dir}/*.png --overlay")


if __name__ == "__main__":
    main()
