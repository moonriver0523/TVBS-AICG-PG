"""回查生成紀錄：把使用者回報的一張成圖，還原成當時的輸入、消化結果與 prompt。

用法（repo 根目錄）：
    # 看最近幾筆
    python scripts/find_generation.py --recent 5
    # 依時間找（使用者回報的圖，用檔案修改時間比對）
    python scripts/find_generation.py --near "2026-07-31 23:06"
    # 依關鍵字找
    python scripts/find_generation.py --text 休達
    # 依 request_id 或 LINE 成圖檔名找，並印出完整 prompt
    python scripts/find_generation.py --id 3f9a1c2b7d40 --full
    python scripts/find_generation.py --image 20260731-230612-a1b2c3.png --full

沒有紀錄時的回退作法仍是請使用者重貼原文——但那正是這個機制要避免的情況。
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import request_log  # noqa: E402


def load_records() -> list[dict]:
    records = []
    for path in sorted(request_log.LOG_DIR.glob("generations-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    records.sort(key=lambda r: r.get("ts", ""))
    return records


def show(record: dict, full: bool) -> None:
    print("=" * 70)
    print(f"{record.get('ts', '')}  [{record.get('source', '')}]  "
          f"id={record.get('request_id', '')}")
    if record.get("source") == "image-file":
        print(f"  成圖檔名 {record.get('image_name', '')}")
        return
    meta = " / ".join(
        filter(None, [
            record.get("provider", ""),
            record.get("image_model", ""),
            record.get("chart_type", ""),
            record.get("density", ""),
            record.get("prompt_version", ""),
        ])
    )
    if meta:
        print(f"  {meta}")
    news = record.get("news_text", "")
    print(f"\n【原始新聞】\n{news if full else news[:200] + ('…' if len(news) > 200 else '')}")
    print(f"\n【variable】\n{record.get('variable', '')}")
    if full:
        print(f"\n【style】\n{record.get('style', '')}")
        print(f"\n【structure】\n{record.get('structure', '')}")
        prompt = record.get("prompt", "")
        if prompt:
            print(f"\n【最終 prompt】\n{prompt}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recent", type=int, metavar="N", help="列出最近 N 筆")
    parser.add_argument("--near", metavar="TIME", help="找此時間附近的紀錄，如 '2026-07-31 23:06'")
    parser.add_argument("--window", type=int, default=10, help="--near 的前後分鐘數，預設 10")
    parser.add_argument("--text", metavar="KEYWORD", help="在原始新聞／variable 中搜尋關鍵字")
    parser.add_argument("--id", metavar="REQUEST_ID", help="依 request_id 找")
    parser.add_argument("--image", metavar="NAME", help="依 LINE 成圖檔名找")
    parser.add_argument("--full", action="store_true", help="印出完整 prompt 與各欄位")
    args = parser.parse_args()

    records = load_records()
    if not records:
        print(f"沒有任何紀錄（找過 {request_log.LOG_DIR}）", file=sys.stderr)
        print("若這是舊事件，機制上線前的請求本來就沒有留存。", file=sys.stderr)
        sys.exit(1)

    if args.image:
        hits = [r for r in records if r.get("image_name") == args.image]
        if not hits:
            print(f"找不到成圖 {args.image}", file=sys.stderr)
            sys.exit(1)
        args.id = hits[0].get("request_id")

    if args.id:
        records = [r for r in records if r.get("request_id") == args.id]
    elif args.near:
        target = datetime.fromisoformat(args.near)
        span = timedelta(minutes=args.window)
        picked = []
        for record in records:
            try:
                ts = datetime.fromisoformat(record["ts"]).replace(tzinfo=None)
            except (KeyError, ValueError):
                continue
            if abs(ts - target) <= span:
                picked.append(record)
        records = picked
    elif args.text:
        records = [
            r for r in records
            if args.text in r.get("news_text", "") or args.text in r.get("variable", "")
        ]
    elif args.recent:
        records = records[-args.recent:]
    else:
        records = records[-3:]

    if not records:
        print("沒有符合條件的紀錄", file=sys.stderr)
        sys.exit(1)
    for record in records:
        show(record, args.full)


if __name__ == "__main__":
    main()
