"""量測生成圖的內容邊界，逐邊對照 TVBS 官方安全框判定。

為什麼需要這支：過去四輪實驗的邊距都是「目測比例」（見 error-cases 各分析文件的
「數字為目測比例」註記），不同輪之間不可比、也容易誤判。這支用固定演算法給出可重現的數字。

原理：資訊圖表的內容（文字、卡片、圖示）邊緣對比強烈，背景（漸層、光暈）平滑。
因此取邊緣強度圖二值化，再逐列／逐行統計強邊緣像素密度，密度超過門檻的第一與最後
一列／行即為內容邊界。

⚠️ 這是啟發式量測，不是像素級真值：背景若含明顯格線、掃描線或邊框裝飾，會被算成內容。
**務必搭配 `--overlay` 產生的疊圖目視確認**，再採用數字。
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import safe_area_spec  # noqa: E402  （需先加入專案根目錄到 sys.path）

# 邊緣強度二值化門檻（0-255）。調高＝只認很銳利的邊，較不會把背景紋理當內容。
DEFAULT_EDGE_THRESHOLD = 60
# 一列／行中強邊緣像素佔該列長度的比例，超過才算「有內容」。用來濾掉零星雜訊。
DEFAULT_DENSITY = 0.01


def _strong_edge_counts(binary: Image.Image) -> tuple[list[int], list[int]]:
    """回傳 (每列的強邊緣像素數, 每行的強邊緣像素數)。用 1 像素切片的直方圖統計。"""
    width, height = binary.size
    row_counts = [binary.crop((0, y, width, y + 1)).histogram()[255] for y in range(height)]
    col_counts = [binary.crop((x, 0, x + 1, height)).histogram()[255] for x in range(width)]
    return row_counts, col_counts


def _first_last_above(counts: list[int], minimum: float) -> tuple[int, int] | None:
    hits = [i for i, c in enumerate(counts) if c >= minimum]
    if not hits:
        return None
    return hits[0], hits[-1]


def measure(
    path: Path,
    edge_threshold: int = DEFAULT_EDGE_THRESHOLD,
    density: float = DEFAULT_DENSITY,
) -> dict[str, object]:
    """量測單張圖的內容 bounding box 與四邊留白比例。"""
    with Image.open(path) as opened:
        img = opened.convert("RGB")
    width, height = img.size

    # FIND_EDGES 會在最外圈 1 像素產生假邊緣，先內縮再分析，之後把座標補回去。
    inset = 1
    core = img.crop((inset, inset, width - inset, height - inset)).convert("L")
    edges = core.filter(ImageFilter.FIND_EDGES)
    binary = edges.point(lambda v: 255 if v >= edge_threshold else 0)

    row_counts, col_counts = _strong_edge_counts(binary)
    core_w, core_h = binary.size
    rows = _first_last_above(row_counts, core_w * density)
    cols = _first_last_above(col_counts, core_h * density)

    if rows is None or cols is None:
        return {
            "file": path.name,
            "size": [width, height],
            "error": "偵測不到內容邊緣，可能整張近乎空白或門檻設得太高",
        }

    top = rows[0] + inset
    bottom = rows[1] + inset
    left = cols[0] + inset
    right = cols[1] + inset

    measured = {
        "top": top / height,
        "left": left / width,
        "right": (width - 1 - right) / width,
        "bottom": (height - 1 - bottom) / height,
    }
    result: dict[str, object] = {
        "file": path.name,
        "size": [width, height],
        "content_bbox": [left, top, right, bottom],
        **safe_area_spec.summarize(measured),
    }
    return result


def write_overlay(path: Path, result: dict[str, object], out_dir: Path) -> Path:
    """把偵測到的內容框（紅）與官方安全框（青）畫在圖上，供目視確認量測是否可信。"""
    with Image.open(path) as opened:
        img = opened.convert("RGB")
    width, height = img.size
    draw = ImageDraw.Draw(img)

    x0, y0, x1, y1 = safe_area_spec.safe_rect(width, height)
    draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(0, 255, 255), width=3)

    bbox = result.get("content_bbox")
    if isinstance(bbox, list):
        draw.rectangle(bbox, outline=(255, 40, 40), width=3)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{path.stem}-overlay.png"
    img.save(out_path)
    return out_path


def _format_row(result: dict[str, object]) -> str:
    if "error" in result:
        return f"{result['file']}: {result['error']}"
    measured = result["measured_pct"]
    verdicts = result["verdicts"]
    parts = [
        f"{edge[:1].upper()} {measured[edge]:5.2f}% {verdicts[edge]:<8}"
        for edge in safe_area_spec.EDGES
    ]
    return f"{result['file']}\n  " + " | ".join(parts) + f"\n  整體：{result['overall']}"


def main() -> None:
    parser = argparse.ArgumentParser(description="量測生成圖的安全框合格度")
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--edge-threshold", type=int, default=DEFAULT_EDGE_THRESHOLD)
    parser.add_argument("--density", type=float, default=DEFAULT_DENSITY)
    parser.add_argument(
        "--overlay",
        action="store_true",
        help="另存疊圖（紅＝偵測到的內容框，青＝官方安全框），用來確認量測可信度",
    )
    parser.add_argument("--overlay-dir", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None, help="把結果寫成 JSON")
    args = parser.parse_args()

    required = {e: round(safe_area_spec.MARGIN_FRACTIONS[e] * 100, 2) for e in safe_area_spec.EDGES}
    print(f"官方需求留白：{required}")
    print(f"（門檻 edge={args.edge_threshold} density={args.density}）\n")

    results = []
    for image_path in args.images:
        if not image_path.exists():
            print(f"跳過不存在的檔案：{image_path}")
            continue
        result = measure(image_path, args.edge_threshold, args.density)
        if args.overlay and "error" not in result:
            overlay_dir = args.overlay_dir or image_path.parent / "overlay"
            overlay_path = write_overlay(image_path, result, overlay_dir)
            result["overlay"] = str(overlay_path)
            print(f"疊圖：{overlay_path}")
        results.append(result)
        print(_format_row(result))
        print()

    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已寫出 {args.json}")


if __name__ == "__main__":
    main()
