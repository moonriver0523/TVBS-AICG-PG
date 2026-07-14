#!/usr/bin/env python3
"""從 templates.json 產生 notion-templates/INDEX.md（分類縮圖總覽）"""
import json
from collections import OrderedDict
from pathlib import Path

REPO = Path("/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG")
data = json.loads((REPO / "notion-templates/templates.json").read_text(encoding="utf-8"))

# 主分類判定：依構圖TAG 的優先序歸類
GROUPS = OrderedDict([
    ("地圖", ["♖ 地圖"]),
    ("人物/小檔案", ["♖ 人物", "小檔案"]),
    ("物件/軍武", ["♖ 物件"]),
    ("儀表板/數據圖表", ["儀表板", "長條圖", "折線圖", "圓餅圖", "三切", "列點格"]),
    ("摘要/聲明", ["摘要", "摘要: 社群", "摘要: 引述媒體", "摘要: 聲明"]),
    ("字卡", ["♖ 字卡"]),
    ("底圖/Icon", ["♖ 底圖", "Icon"]),
    ("其他圖表", ["♖ 圖表"]),
    ("動畫（未分類）", ["♖ 動畫"]),
])

def classify(t):
    tags = [x.strip() for x in t["metadata"].get("構圖TAG", "").split(",") if x.strip()]
    for gname, gtags in GROUPS.items():
        if any(tag in tags for tag in gtags):
            return gname
    return "未標記"

grouped = {}
for t in data["templates"]:
    grouped.setdefault(classify(t), []).append(t)

lines = ["# AI圖資料庫 模板總覽（Notion 匯出 2026-07-14）", ""]
lines.append(f"共 {data['template_count']} 個模板。完整 prompt 內容在 [templates.json](templates.json)；")
lines.append(f"原始匯出（含全部 549 圖 / 104 影片）在本機 `{data['export_root']}`。")
lines.append("")
order = list(GROUPS.keys()) + ["未標記"]
for g in order:
    items = grouped.get(g)
    if not items:
        continue
    lines.append(f"## {g}（{len(items)}）")
    lines.append("")
    lines.append("| 縮圖 | 名稱 | 風格包 | 構圖TAG | 用途TAG | 動畫 |")
    lines.append("|---|---|---|---|---|---|")
    for t in sorted(items, key=lambda x: x["name"]):
        md = t["metadata"]
        img = f'<img src="images/{t["id"]}.jpg" width="160">' if t.get("rep_image") else ""
        anim = "🎬" if t["videos"] or "♖ 動畫" in md.get("構圖TAG", "") else ""
        lines.append(f"| {img} | {t['name']} | {md.get('✠ 風格包','')} | {md.get('構圖TAG','')} | {md.get('用途 TAG','')} | {anim} |")
    lines.append("")

(REPO / "notion-templates/INDEX.md").write_text("\n".join(lines), encoding="utf-8")
for g in order:
    if g in grouped:
        print(g, len(grouped[g]))
