#!/usr/bin/env python3
"""為每個模板產出壓縮代表圖到 repo，並回寫 rep_image 欄位到 templates.json"""
import json
import subprocess
from pathlib import Path

EXPORT = Path.home() / "Downloads/AI圖資料庫"
REPO = Path("/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG")
OUT_JSON = REPO / "notion-templates/templates.json"
IMG_DIR = REPO / "notion-templates/images"
IMG_DIR.mkdir(exist_ok=True)

data = json.loads(OUT_JSON.read_text(encoding="utf-8"))
ok = fail = 0
for t in data["templates"]:
    dest = IMG_DIR / f"{t['id']}.jpg"
    src = None
    tmp_frame = None
    if t["rep_image_src"]:
        src = EXPORT / t["rep_image_src"]
    elif t["videos"] and t["asset_dir"]:
        vid = EXPORT / t["asset_dir"] / t["videos"][0]
        tmp_frame = Path("/tmp") / f"frame_{t['id']}.png"
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(vid),
             "-frames:v", "1", str(tmp_frame)])
        if r.returncode == 0 and tmp_frame.exists():
            src = tmp_frame
    if src is None or not src.exists():
        t["rep_image"] = None
        continue
    r = subprocess.run(
        ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "72",
         "--resampleHeightWidthMax", "1200", str(src), "--out", str(dest)],
        capture_output=True)
    if r.returncode == 0 and dest.exists():
        t["rep_image"] = f"notion-templates/images/{dest.name}"
        ok += 1
    else:
        t["rep_image"] = None
        fail += 1
        print("FAIL:", t["name"], r.stderr.decode()[:200])
    if tmp_frame and tmp_frame.exists():
        tmp_frame.unlink()

OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"成功 {ok}，失敗 {fail}，無圖 {sum(1 for t in data['templates'] if not t.get('rep_image'))}")
subprocess.run(["du", "-sh", str(IMG_DIR)])
