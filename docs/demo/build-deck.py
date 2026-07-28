"""把 deck.template.html 裡的 {{IMGn}} 佔位符換成 base64 data URI，產出單一自足的 demo-report.html。

用法：python docs/demo/build-deck.py
來源圖：docs/error-cases/ 的原始 PNG/JPG，先用 ffmpeg 縮到 960px 寬的 JPEG 再嵌入，
        避免單檔膨脹到 15MB（原圖合計 11.4MB）。
"""

import base64
import io
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
CASES = HERE.parent / "error-cases"

# 佔位符 -> 原始檔名
IMAGES = {
    "IMG1": "2026-07-23-像素安全框-GEMINI1-數字入圖.png",
    "IMG2": "2026-07-23-像素安全框-GEMINI2-工程圖標註.png",
    "IMG5": "2026-07-23-百分比安全框-R1-GPT1-標題貼頂底部壓帶.png",
    "IMG6": "2026-07-23-百分比安全框-R2-GEMINI1-括號入圖.png",
    "IMG8": "2026-07-23-沖之鳥島-位置偏移.jpg",
}

WIDTH = 960
QUALITY = "5"  # ffmpeg -q:v，數字越小畫質越好


def encode(src: pathlib.Path, tmpdir: pathlib.Path) -> str:
    out = tmpdir / (src.stem + ".jpg")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-vf", f"scale={WIDTH}:-2", "-q:v", QUALITY, str(out)],
        check=True,
    )
    b64 = base64.b64encode(out.read_bytes()).decode("ascii")
    return "data:image/jpeg;base64," + b64


def main() -> int:
    template = HERE / "deck.template.html"
    target = HERE / "demo-report.html"
    html = io.open(template, encoding="utf-8").read()

    with tempfile.TemporaryDirectory() as td:
        tmpdir = pathlib.Path(td)
        for token, filename in IMAGES.items():
            src = CASES / filename
            if not src.exists():
                print(f"找不到來源圖：{src}", file=sys.stderr)
                return 1
            placeholder = "{{" + token + "}}"
            if placeholder not in html:
                print(f"範本裡沒有 {placeholder}", file=sys.stderr)
                return 1
            html = html.replace(placeholder, encode(src, tmpdir))

    io.open(target, "w", encoding="utf-8", newline="\n").write(html)
    print(f"完成：{target}（{target.stat().st_size / 1024:.0f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
