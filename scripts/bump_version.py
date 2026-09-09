"""版本號遞增（2026-09-09 使用者：「每次改動（不是佈署）都要更新版本號」）。

格式 YYMMDD-XX：YY 是年份後兩碼，XX 從 01 起算、換一天就從 01 重來
（使用者說「從00開始」，但給的範例是 260909-01，以範例為準）。

    python -X utf8 scripts/bump_version.py            # 依今天日期遞增
    python -X utf8 scripts/bump_version.py --set 260909-07

VERSION 檔是唯一真相源，這支腳本順便把 index.html 上的顯示字串改成同一個值；
兩邊對不上會被 tests/test_app_version.py 擋下來。
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
INDEX_FILE = ROOT / "index.html"

VERSION_RE = re.compile(r"^\d{6}-\d{2}$")
# index.html 大標右邊那顆版本標籤，內容整個換掉（見 tests/test_app_version.py）
INDEX_SPAN_RE = re.compile(
    r'(<span id="appVersion"[^>]*>)([^<]*)(</span>)'
)


def read_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def next_version(current: str, today: datetime.date) -> str:
    stamp = today.strftime("%y%m%d")
    if current.startswith(f"{stamp}-"):
        return f"{stamp}-{int(current.split('-')[1]) + 1:02d}"
    return f"{stamp}-01"


def write_version(version: str) -> None:
    if not VERSION_RE.match(version):
        raise SystemExit(f"版本號格式不對（要 YYMMDD-XX）：{version}")
    VERSION_FILE.write_text(version + "\n", encoding="utf-8")
    html = INDEX_FILE.read_text(encoding="utf-8")
    html, count = INDEX_SPAN_RE.subn(rf"\g<1>{version}\g<3>", html)
    if count != 1:
        raise SystemExit(f"index.html 找不到（或找到多個）版本標籤：{count} 個")
    INDEX_FILE.write_text(html, encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="value", help="直接指定版本號（YYMMDD-XX）")
    args = parser.parse_args(argv)
    version = args.value or next_version(read_version(), datetime.date.today())
    write_version(version)
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
