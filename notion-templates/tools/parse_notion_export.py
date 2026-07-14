#!/usr/bin/env python3
"""解析 Notion 匯出的 AI圖資料庫，輸出結構化 templates.json + INDEX.md"""
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

EXPORT = Path.home() / "Downloads/AI圖資料庫"
MASTER = EXPORT / "Projects/AI圖/AI圖資料庫 (Master)/AI圖資料庫 (Master)"
NBP = EXPORT / "Projects/AI圖/NBP Collection (岱軒版)"
REPO = Path("/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG")
OUT_DIR = REPO / "notion-templates"

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VID_EXT = {".mp4", ".mov", ".webm"}

ID_RE = re.compile(r"\s+([0-9a-f]{32})\.md$")
SECTION_RE = re.compile(r"^- \*(.+?)\*\s*$")
IMG_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
META_RE = re.compile(r"^([^:：]{1,20}?): (.+)$")


def norm(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def parse_md(md_path: Path) -> dict:
    text = norm(md_path.read_text(encoding="utf-8"))
    lines = text.split("\n")
    name = lines[0].lstrip("# ").strip() if lines else md_path.stem
    m = ID_RE.search(md_path.name)
    nid = m.group(1) if m else None

    # metadata: H1 之後到 <aside> 或第一個空行群之前的 Key: value
    metadata = {}
    for line in lines[1:]:
        if line.startswith("<aside") or SECTION_RE.match(line):
            break
        mm = META_RE.match(line.strip())
        if mm:
            metadata[mm.group(1).strip()] = mm.group(2).strip()

    # 圖片引用（依出現順序）
    img_refs = [norm(unquote(u)) for u in IMG_REF_RE.findall(text)]

    # sections: - *label* 後的縮排區塊
    sections = []
    i = 0
    while i < len(lines):
        sm = SECTION_RE.match(lines[i])
        if not sm:
            i += 1
            continue
        label = sm.group(1).strip()
        i += 1
        body_lines = []
        while i < len(lines):
            ln = lines[i]
            if SECTION_RE.match(ln) or ln.strip() == "</aside>":
                break
            body_lines.append(ln)
            i += 1
        # 抽出 code fences；沒有 fence 就保留純文字
        body = "\n".join(body_lines)
        blocks = []
        fence_re = re.compile(r"^\s*```[^\n]*\n(.*?)^\s*```\s*$", re.M | re.S)
        for fm in fence_re.finditer(body):
            code = fm.group(1)
            # 去掉共同縮排
            code_lines = code.split("\n")
            indents = [len(l) - len(l.lstrip()) for l in code_lines if l.strip()]
            pad = min(indents) if indents else 0
            code = "\n".join(l[pad:] if len(l) >= pad else l for l in code_lines).strip()
            if code:
                blocks.append(code)
        if not blocks:
            plain = "\n".join(l.strip() for l in body_lines if l.strip() and not IMG_REF_RE.search(l))
            if plain:
                blocks.append(plain)
        sections.append({"label": label, "blocks": blocks})
        # i 停在下一個 section 或 </aside>

    return {"id": nid, "name": name, "metadata": metadata,
            "image_refs": img_refs, "sections": sections}


def asset_dir_for(md_path: Path) -> Path | None:
    base = ID_RE.sub("", md_path.name)
    d = md_path.parent / base
    return d if d.is_dir() else None


def main():
    templates = []
    md_files = sorted(MASTER.glob("*.md"))
    for md in md_files:
        t = parse_md(md)
        t["source_md"] = str(md.relative_to(EXPORT))
        d = asset_dir_for(md)
        imgs, vids = [], []
        if d:
            for f in sorted(d.iterdir()):
                if f.suffix.lower() in IMG_EXT:
                    imgs.append(f.name)
                elif f.suffix.lower() in VID_EXT:
                    vids.append(f.name)
            t["asset_dir"] = str(d.relative_to(EXPORT))
        else:
            t["asset_dir"] = None
        t["images"] = imgs
        t["videos"] = vids
        # 代表圖：md 內第一個引用且存在的圖，否則資產夾第一張
        rep = None
        if d:
            for ref in t["image_refs"]:
                cand = EXPORT / "Projects/AI圖/AI圖資料庫 (Master)/AI圖資料庫 (Master)" / ref
                if cand.suffix.lower() in IMG_EXT and cand.exists():
                    rep = cand
                    break
            if rep is None and imgs:
                rep = d / imgs[0]
        t["rep_image_src"] = str(rep.relative_to(EXPORT)) if rep else None
        del t["image_refs"]
        templates.append(t)

    # NBP Collection：純圖庫
    nbp = []
    for d in sorted(p for p in NBP.iterdir() if p.is_dir()):
        files = sorted(f.name for f in d.iterdir()
                       if f.suffix.lower() in IMG_EXT | VID_EXT)
        nbp.append({"name": norm(d.name), "dir": str(d.relative_to(EXPORT)), "files": files})

    # Master CSV（頂層那份是 view 匯出）
    csvs = list(EXPORT.glob("*.csv"))
    csv_rows = 0
    if csvs:
        with open(csvs[0], encoding="utf-8-sig") as f:
            csv_rows = sum(1 for _ in csv.DictReader(f))

    OUT_DIR.mkdir(exist_ok=True)
    out = {
        "source": "Notion 匯出 AI圖資料庫 (2026-07-14)",
        "export_root": str(EXPORT),
        "template_count": len(templates),
        "csv_row_count": csv_rows,
        "templates": templates,
        "nbp_collection": nbp,
    }
    (OUT_DIR / "templates.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # 統計
    empty_prompt = [t["name"] for t in templates
                    if not any(b for s in t["sections"] for b in s["blocks"])]
    print(f"模板數: {len(templates)}  (CSV rows: {csv_rows})")
    print(f"NBP 集合: {len(nbp)} 個圖庫夾")
    print(f"有代表圖: {sum(1 for t in templates if t['rep_image_src'])}")
    print(f"完全沒有 prompt 內容: {len(empty_prompt)}")
    for n in empty_prompt[:15]:
        print("  -", n)
    # 構圖TAG 分佈
    from collections import Counter
    c = Counter()
    for t in templates:
        for tag in t["metadata"].get("構圖TAG", "").split(","):
            tag = tag.strip()
            if tag:
                c[tag] += 1
    print("構圖TAG 分佈:", dict(c.most_common(15)))


if __name__ == "__main__":
    sys.exit(main())
