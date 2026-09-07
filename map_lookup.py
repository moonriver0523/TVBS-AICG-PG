"""真實地圖底圖：地名 → 座標 → 拼接好的 OSM 底圖 PNG。

**為什麼需要這個模組。** 2026-09-04 實測（基隆廟口／西定路／大武崙淹水）：
消化端照 MAP_ACCURACY_RULES 乖乖寫出了經緯度，但那些座標來自模型記憶——
「西定路」給的是 121.7240°E，實際約 121.740°E，差約 1.6 公里，成圖上那支標記
就插到山區去了。地標名氣越小越不可靠（同案例的「基隆廟口」只差約 110 公尺）。
座標交給生圖模型「憑印象」是錯的分工：地理是可查的事實，該由程式去查、去畫，
比照 `safe_frame.py`／`compose.py` 的「空間精準的事情不交給模型」原則。

**資料來源與授權（2026-09-04 使用者裁決：用 OpenStreetMap）。**
- 地理編碼走 Nominatim，圖磚走 `OSM_TILE_URL`（預設官方伺服器）。
- OSM 資料是 ODbL，**成圖上必須標註「© OpenStreetMap contributors」**，
  因此 `render_basemap` 一律把出處字樣燒進底圖，沒有關掉的參數。
- 官方圖磚伺服器的使用條款不歡迎自動化大量抓取。這裡的對策是：帶可識別的
  User-Agent、抓到的圖磚寫進磁碟快取（同一區域第二次就不再連外）、單張底圖
  的圖磚數設上限。**要上正式量之前應改指向付費圖磚商**（Geoapify／Stadia 等，
  設 `OSM_TILE_URL` 即可換，不必改程式）。
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import pathlib
import re
import ssl
import tempfile
import time
import urllib.parse
import urllib.request

_UA = "TVBS-AICG/1.0 (+https://github.com/moonriver0523/TVBS-AICG-PG)"
_TIMEOUT = 8

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_SIZE = 256
# 單張底圖最多抓幾張圖磚。上限存在的理由是使用條款而不是效能：
# 沒有上限時一個「請畫出台灣與日本的相對位置」就會掃掉整片圖磚。
MAX_TILES = 24
ATTRIBUTION = "© OpenStreetMap contributors"

_CACHE_DIR = pathlib.Path(
    os.getenv("OSM_TILE_CACHE", pathlib.Path(tempfile.gettempdir()) / "tvbs-aicg-osm")
)
# Nominatim 要求每秒最多一次查詢；這裡記上一次查詢的時間自我節流。
_last_geocode_at = 0.0
_GEOCODE_MIN_INTERVAL = 1.0


class MapLookupError(RuntimeError):
    """查不到或抓不到。呼叫端必須能接受沒有底圖（退回純 prompt 那條路）。"""


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def _get(url: str, *, timeout: int = _TIMEOUT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as resp:
        return resp.read()


# 可以當「地點」用的 OSM 主分類。地理實體才收：行政區、聚落、道路、水域、
# 地形、土地利用、園區、景點、機場、車站。刻意不收 amenity／shop／office／
# building／healthcare 這些**單一營業場所**——它們是店家名稱撞名的主要來源。
GEOGRAPHIC_CLASSES = frozenset({
    "place", "boundary", "landuse", "highway", "waterway", "natural",
    "leisure", "tourism", "aeroway", "railway", "military",
})


def _looks_like_the_place_asked_for(query: str, hit: dict) -> bool:
    """這筆結果認得出是我們查的東西嗎。

    2026-09-05 實查到的兩種錯配，各需要一道檢查：
      1.「北海岸」比對到臺中市北屯區一家叫「北海岸」的餐廳（離基隆 130 公里）。
         名稱完全吻合，擋不掉，但 class=amenity——它是店，不是地方。
      2.「市區」比對到國立臺灣師範大學，importance 0.521 比任何正確結果都高。
         class 是 amenity 也擋得掉，但更根本的是名稱對不上：查的字詞在結果裡
         完全找不到。
    importance 不能當門檻：正確的「廟口夜市牌樓」是 0.000。
    """
    if (hit.get("class") or "") not in GEOGRAPHIC_CLASSES:
        return False
    # 名稱對應。中文沒有詞界，整串比對會誤殺正確結果——查「基隆廟口」、
    # Nominatim 回「廟口夜市（…基隆市…）」是對的，但「基隆廟口」四個字並不
    # 連續出現在結果裡。改成看有沒有**長度 2 以上的連續片段**對得上：
    # 上例的「基隆」與「廟口」都對得上，而「市區」對到師大時只剩單字重疊。
    haystack = f"{hit.get('name') or ''}｜{hit.get('display_name') or ''}"
    for token in (t for t in re.split(r"[\s,、]+", query) if t):
        for size in range(len(token), 1, -1):
            for start in range(len(token) - size + 1):
                if token[start:start + size] in haystack:
                    return True
    return False


def geocode(place: str, *, country: str = "tw", timeout: int = _TIMEOUT) -> tuple[float, float] | None:
    """地名 → (lat, lon)；查不到、或查到的東西不像那個地方，都回 None。

    刻意不做模糊比對或「最像的那個」：查不到就是查不到，讓呼叫端退回示意圖，
    比標一個錯的地點好——標錯地點在新聞畫面上就是播出事故。

    2026-09-05 補上可信度檢查。在那之前這裡是 `limit=1` 直接收下 Nominatim 的
    第一名，也就是實作在做的正是上面那句話說不做的事：Nominatim 一定會給你
    「最像的那個」，模糊地名（北海岸／市區／低窪地區）於是被配到隨便一家同名
    店家，而那個橘點會被燒進底圖、生圖模型又被要求不准移動標點。
    """
    global _last_geocode_at
    name = (place or "").strip()
    if not name:
        return None
    wait = _GEOCODE_MIN_INTERVAL - (time.monotonic() - _last_geocode_at)
    if wait > 0:
        time.sleep(wait)
    _last_geocode_at = time.monotonic()
    query = urllib.parse.urlencode(
        # limit 從 1 拉到 5：第一名被判定不可信時，後面可能有真正的地理實體。
        {"q": name, "format": "json", "limit": 5, "countrycodes": country}
    )
    try:
        payload = json.loads(_get(f"{NOMINATIM_URL}?{query}", timeout=timeout).decode("utf-8"))
    except Exception as exc:  # 網路／解析失敗都當查不到
        print(f"[map_lookup] geocode 失敗 {name}：{exc}", flush=True)
        return None
    if not payload:
        return None
    for hit in payload:
        if not isinstance(hit, dict) or not _looks_like_the_place_asked_for(name, hit):
            continue
        try:
            return float(hit["lat"]), float(hit["lon"])
        except (KeyError, TypeError, ValueError):
            continue
    first = payload[0] if isinstance(payload[0], dict) else {}
    print(
        f"[map_lookup] geocode 不採信 {name}："
        f"比對到 {first.get('name')}（{first.get('class')}/{first.get('type')}）"
        f" @ {first.get('display_name')}",
        flush=True,
    )
    return None


def _lat_to_y(lat: float, zoom: int) -> float:
    rad = math.radians(lat)
    n = 2.0**zoom
    return (1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * n


def _lon_to_x(lon: float, zoom: int) -> float:
    return (lon + 180.0) / 360.0 * 2.0**zoom


def choose_zoom(points: list[tuple[float, float]], width: int, height: int) -> int:
    """挑一個能把所有點都納入畫面的最大縮放層級（數字越大越近）。

    由近往遠試，第一個裝得下的就用——先試最近的才不會拿到一張什麼都看不清的
    小比例尺圖。單點時沒有範圍可言，直接給街區級。
    """
    if len(points) < 2:
        return 14
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    for zoom in range(18, 1, -1):
        span_x = (_lon_to_x(max(lons), zoom) - _lon_to_x(min(lons), zoom)) * TILE_SIZE
        span_y = (_lat_to_y(min(lats), zoom) - _lat_to_y(max(lats), zoom)) * TILE_SIZE
        # 留邊：點貼在邊緣的底圖沒有上下文，標記也會被裁到
        if span_x <= width * 0.8 and span_y <= height * 0.8:
            return zoom
    return 2


def _tile_bytes(url_template: str, zoom: int, x: int, y: int) -> bytes:
    url = url_template.format(z=zoom, x=x, y=y)
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cached = _CACHE_DIR / key[:2] / f"{key}.png"
    if cached.exists():
        return cached.read_bytes()
    data = _get(url)
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    except OSError as exc:  # 快取寫不進去不該讓整張底圖失敗
        print(f"[map_lookup] 圖磚快取寫入失敗（不影響本次）：{exc}", flush=True)
    return data


def project(point: tuple[float, float], centre: tuple[float, float], zoom: int,
            width: int, height: int) -> tuple[int, int]:
    """把經緯度換算成底圖上的像素座標。標點要畫得準，全靠這一步。"""
    cx = _lon_to_x(centre[1], zoom) * TILE_SIZE
    cy = _lat_to_y(centre[0], zoom) * TILE_SIZE
    px = _lon_to_x(point[1], zoom) * TILE_SIZE - (cx - width / 2)
    py = _lat_to_y(point[0], zoom) * TILE_SIZE - (cy - height / 2)
    return round(px), round(py)


def render_basemap(
    points: list[tuple[float, float]],
    *,
    width: int = 1024,
    height: int = 576,
    zoom: int | None = None,
    tile_url: str | None = None,
    mark: bool = True,
    labels: list[str] | None = None,
) -> bytes:
    """把涵蓋所有座標的 OSM 底圖拼成一張 PNG（含出處標註）。

    `mark=True` 時由**程式**在每個座標上畫一個明顯的圓標。這不是美術，是定位：
    生圖模型拿到底圖後只被要求「照著現有標記重新美化，不要移動」，位置就不再
    由模型決定。比照 safe_frame／compose 的原則——空間精準的事情程式做。
    """
    from PIL import Image, ImageDraw  # 延後匯入：沒用到地圖時不必付 Pillow 的啟動成本

    if not points:
        raise MapLookupError("沒有可用的座標，無法產生底圖")
    template = tile_url or os.getenv("OSM_TILE_URL", DEFAULT_TILE_URL)
    level = zoom if zoom is not None else choose_zoom(points, width, height)

    centre_lat = (max(p[0] for p in points) + min(p[0] for p in points)) / 2
    centre_lon = (max(p[1] for p in points) + min(p[1] for p in points)) / 2
    centre_x = _lon_to_x(centre_lon, level) * TILE_SIZE
    centre_y = _lat_to_y(centre_lat, level) * TILE_SIZE

    left = centre_x - width / 2
    top = centre_y - height / 2
    x0, x1 = math.floor(left / TILE_SIZE), math.floor((left + width) / TILE_SIZE)
    y0, y1 = math.floor(top / TILE_SIZE), math.floor((top + height) / TILE_SIZE)
    count = (x1 - x0 + 1) * (y1 - y0 + 1)
    if count > MAX_TILES:
        raise MapLookupError(
            f"這個範圍需要 {count} 張圖磚，超過上限 {MAX_TILES}——"
            "範圍太大時應改用小比例尺定位圖，而不是掃更多圖磚"
        )

    canvas = Image.new("RGB", (width, height), (233, 229, 220))
    span = 2**level
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            if not (0 <= ty < span):
                continue
            try:
                tile = Image.open(io.BytesIO(_tile_bytes(template, level, tx % span, ty)))
            except Exception as exc:
                print(f"[map_lookup] 圖磚抓取失敗 z{level}/{tx}/{ty}：{exc}", flush=True)
                continue
            canvas.paste(tile, (int(tx * TILE_SIZE - left), int(ty * TILE_SIZE - top)))

    draw = ImageDraw.Draw(canvas)
    if mark:
        # 地名也由程式烙上去。2026-09-05 第四、五輪連續兩輪撞到：pin 位置照著
        # 橘點畫對了，名字卻配錯（最北的橘點是中壢交流道，成品標成楊梅），
        # 連帶旁邊的事故圖示也跟著錯。原因是底圖只有點、沒有身分線索，模型
        # 只能自己猜哪個點是誰。點的身分是已知事實，不該讓模型猜——比照
        # safe_frame／compose 的原則，這種事程式做。
        try:
            import compose

            label_font = compose._font(20)
        except Exception:  # 找不到字型不能讓底圖整個失敗，退回只有點
            label_font = None
        for index, point in enumerate(points):
            px, py = project(point, (centre_lat, centre_lon), level, width, height)
            draw.ellipse((px - 16, py - 16, px + 16, py + 16), fill=(255, 138, 0),
                         outline=(255, 255, 255), width=5)
            name = (labels[index] if labels and index < len(labels) else "").strip()
            if not name or label_font is None:
                continue
            box = draw.textbbox((0, 0), name, font=label_font)
            tw, th = box[2] - box[0], box[3] - box[1]
            # 預設標在點的右側；貼到右緣就翻到左側，免得字被裁掉
            tx = px + 24 if px + 24 + tw + 12 <= width else px - 24 - tw - 12
            ty = max(0, min(py - th // 2 - 6, height - th - 12))
            draw.rectangle((tx - 6, ty - 4, tx + tw + 6, ty + th + 8),
                           fill=(255, 255, 255), outline=(255, 138, 0), width=2)
            draw.text((tx, ty - box[1] + 2), name, font=label_font, fill=(20, 20, 20))

    # ODbL 要求標註出處；沒有關掉它的參數，因為關掉就是違反授權
    try:
        import compose

        font = compose._font(14)
    except Exception:
        font = None
    box = draw.textbbox((0, 0), ATTRIBUTION, font=font)
    pad = 4
    draw.rectangle(
        (width - (box[2] - box[0]) - pad * 3, height - (box[3] - box[1]) - pad * 3, width, height),
        fill=(255, 255, 255),
    )
    draw.text(
        (width - (box[2] - box[0]) - pad * 2, height - (box[3] - box[1]) - pad * 2),
        ATTRIBUTION,
        fill=(60, 60, 60),
        font=font,
    )

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()
