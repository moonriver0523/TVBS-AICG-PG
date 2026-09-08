"""把 TVBS logo 的「V」左筆畫補回被截掉的上半截。

作法：量測既有筆畫左右緣的直線斜率，往上外插到 T 直劃的頂端列
（原始 logo 兩者切齊），以 8 倍超取樣填成同斜率的平行四邊形，
再與原圖 alpha 取 max，只加不減。
"""
import sys
import numpy as np
from PIL import Image, ImageDraw

SS = 8  # supersample


def runs(alpha, y):
    row = alpha[y] >= 128
    out, s = [], None
    for i, v in enumerate(row):
        if v and s is None:
            s = i
        if not v and s is not None:
            out.append((s, i - 1))
            s = None
    if s is not None:
        out.append((s, len(row) - 1))
    return [r for r in out if r[1] - r[0] >= 2]


def sub(alpha, y, l, r):
    lsub = l - (alpha[y, l - 1] / 255.0 if l > 0 else 0.0)
    rsub = r + (alpha[y, r + 1] / 255.0 if r + 1 < alpha.shape[1] else 0.0)
    return lsub, rsub


def edges(alpha, y, xlo, xhi):
    """追蹤法：挑左緣落在 [xlo, xhi] 且寬度沒暴增（沒跟隔壁筆畫合體）的那條 run。"""
    cands = [r for r in runs(alpha, y) if xlo <= r[0] <= xhi]
    if not cands:
        return None
    l, r = cands[0]
    return sub(alpha, y, l, r)


def fit(alpha, rows, xlo, xhi):
    ys, ls, rs = [], [], []
    prev_w = None
    for y in rows:
        e = edges(alpha, y, xlo, xhi)
        if not e:
            continue
        w = e[1] - e[0]
        if prev_w is not None and w > prev_w * 1.4:
            break  # 已與相鄰筆畫合併，不再取樣
        prev_w = w
        ys.append(y)
        ls.append(e[0])
        rs.append(e[1])
    ys = np.array(ys, float)
    pl = np.polyfit(ys, np.array(ls), 1)
    pr = np.polyfit(ys, np.array(rs), 1)
    resid = max(np.abs(np.polyval(pl, ys) - ls).max(), np.abs(np.polyval(pr, ys) - rs).max())
    return pl, pr, resid


def patch(path, out, y_top, y_seam, fit_rows, xlo, xhi, overlap=6):
    im = Image.open(path).convert("RGBA")
    a = np.array(im)
    alpha = a[:, :, 3]
    pl, pr, resid = fit(alpha, fit_rows, xlo, xhi)
    y_bot = y_seam + overlap
    poly = [
        (np.polyval(pl, y_top), y_top),
        (np.polyval(pr, y_top), y_top),
        (np.polyval(pr, y_bot), y_bot),
        (np.polyval(pl, y_bot), y_bot),
    ]
    w, h = im.size
    mask = Image.new("L", (w * SS, h * SS), 0)
    ImageDraw.Draw(mask).polygon([(x * SS, y * SS) for x, y in poly], fill=255)
    mask = mask.resize((w, h), Image.BOX)
    m = np.array(mask)
    new_alpha = np.maximum(alpha, m)
    a[:, :, 3] = new_alpha
    a[:, :, 0:3] = np.where((new_alpha > 0)[:, :, None], 255, a[:, :, 0:3])
    Image.fromarray(a, "RGBA").save(out)
    print(f"{path}: 斜率 L={pl[0]:+.4f} R={pr[0]:+.4f} 殘差={resid:.2f}px  "
          f"top列 x={poly[0][0]:.1f}..{poly[1][0]:.1f}  seam({y_seam}) 實測={edges(alpha, y_seam, xlo, xhi)} "
          f"外插={np.polyval(pl, y_seam):.1f}..{np.polyval(pr, y_seam):.1f}")


if __name__ == "__main__":
    dst = sys.argv[1] if len(sys.argv) > 1 else "."
    patch("static/brand/tvbs-logo-white.png", f"{dst}/tvbs-logo-white.png",
          y_top=54, y_seam=69, fit_rows=range(74, 101), xlo=70, xhi=100)
    patch("static/brand/tvbs-logo-white-plain.png", f"{dst}/tvbs-logo-white-plain.png",
          y_top=91, y_seam=132, fit_rows=range(140, 226), xlo=260, xhi=360)
