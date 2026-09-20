"""Clerk 登入驗證：把前端帶來的 session token 換成「這是哪一位同仁」。

2026-08-25 加。動機：稽核需求要求每一筆生成都能對到人，但站台密碼門
（main.py 的 site_password_gate）是全公司共用一組密碼，系統從頭到尾不知道誰是誰；
`request_log` 的 client_id 欄位雖然早就存在，前端卻從來沒有填過（app.js 無此欄位）。

接的是 TVBS 既有的 Clerk 專案 tvbs.ai / Development 環境——同事已用 Microsoft
公司帳號註冊過，不需要重新註冊，與 yt-content-helper-v2 共用同一批使用者。

設計取捨：
- 設了 CLERK_PUBLISHABLE_KEY 才啟用。不設就完全是舊行為（密碼門或全開），
  沿用 site_password_gate 與 request_log 的「預設不改變既有部署」慣例。
- token 在本機用 JWKS 公鑰驗章，不是每次請求都打 Clerk API——那會把 Clerk 的延遲
  加到每一次生成上，而且 Clerk 掛掉時整個站就不能用。
- session token 的預設 claims 只有 `sub`（使用者 ID），沒有 email／姓名。人名要另外
  用 Backend API 查，查到就快取住：稽核紀錄要給人看，只存一串 user_xxx 沒有意義。
- 查不到人名不擋請求，退回只記 user_id。身分查詢失敗不該讓同仁不能工作。
"""

import base64
import binascii
import os
import threading
import time

import httpx
import jwt
from jwt import PyJWKClient

PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "").strip()
SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "").strip()
ENABLED = PUBLISHABLE_KEY != ""

# 允許使用的 email 網域，逗號分隔，例：tvbs.com.tw,innov.tvbs.com.tw
#
# 為什麼在自家程式做而不用 Clerk 的 allowlist（2026-08-25 決策）：
# 1. Clerk 的 allowlist 要 Pro 方案才能用。
# 2. 更關鍵的是它是「整個實例」層級的設定——clerk.tvbs.ai 是共用正式實例，
#    330 位使用者背後不只這個專案，改它會牽動其他 TVBS 服務的註冊規則。
#    在這裡檢查只影響本服務，staging 與 production 也能各自設不同規則。
#
# 不設就是舊行為（任何登入成功的人都能用），維持「預設不改變既有部署」的慣例。
ALLOWED_EMAIL_DOMAINS = tuple(
    d.strip().lower().lstrip("@")
    for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "").split(",")
    if d.strip()
)

# 使用者資料快取存活時間。同事改名字的頻率以月計，一小時內用舊值完全可接受，
# 換來的是每次生成少一次對 Clerk 的往返。
_USER_CACHE_TTL = 3600
_user_cache: dict[str, tuple[float, dict]] = {}
_user_cache_lock = threading.Lock()

_jwk_client: PyJWKClient | None = None


def _frontend_api() -> str:
    """從 publishable key 反解 Clerk 的 Frontend API 網域。

    Clerk 的 pk 就是 `pk_test_` / `pk_live_` 加上 base64(網域 + "$")，
    所以不必另外設一個環境變數，少一個會設錯的地方。
    """
    override = os.getenv("CLERK_FRONTEND_API", "").strip()
    if override:
        return override.removeprefix("https://").rstrip("/")
    body = PUBLISHABLE_KEY.split("_", 2)[-1]
    try:
        # base64 沒有 padding 時 b64decode 會炸，補足再解。
        decoded = base64.b64decode(body + "=" * (-len(body) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""
    return decoded.rstrip("$")


FRONTEND_API = _frontend_api() if ENABLED else ""
ISSUER = f"https://{FRONTEND_API}" if FRONTEND_API else ""
JWKS_URL = f"{ISSUER}/.well-known/jwks.json" if ISSUER else ""


def _get_jwk_client() -> PyJWKClient | None:
    global _jwk_client
    if not JWKS_URL:
        return None
    if _jwk_client is None:
        # PyJWKClient 自己會快取金鑰並在遇到未知 kid 時重抓，Clerk 輪替金鑰時
        # 不需要我們重啟服務。
        _jwk_client = PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwk_client


def _fetch_user(user_id: str) -> dict:
    """用 Backend API 補上 email 與姓名。失敗回空 dict，呼叫端要能接受。"""
    if not SECRET_KEY or not user_id:
        return {}
    try:
        response = httpx.get(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {SECRET_KEY}"},
            timeout=5.0,
        )
        if response.status_code != 200:
            return {}
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - 查不到人名不該擋住生成
        print(f"[clerk_auth] fetch user failed: {exc}", flush=True)
        return {}

    email = ""
    primary_id = data.get("primary_email_address_id")
    for entry in data.get("email_addresses") or []:
        if entry.get("id") == primary_id or not email:
            email = entry.get("email_address", "") or email
    name = " ".join(
        part for part in (data.get("first_name"), data.get("last_name")) if part
    ).strip()
    return {"email": email, "name": name or data.get("username") or ""}


def _user_info(user_id: str) -> dict:
    now = time.time()
    with _user_cache_lock:
        cached = _user_cache.get(user_id)
        if cached and now - cached[0] < _USER_CACHE_TTL:
            return cached[1]
    info = _fetch_user(user_id)
    # 查詢失敗（回空 dict）不進快取：否則 Clerk 一次短暫的故障會被記住一小時，
    # 而在網域檢查啟用時「查不到 email」等於擋人，代價太高。
    if info:
        with _user_cache_lock:
            _user_cache[user_id] = (now, info)
    return info


def _domain_allowed(email: str) -> bool:
    """檢查 email 網域是否在允許清單內。未設定清單時一律放行。"""
    if not ALLOWED_EMAIL_DOMAINS:
        return True
    domain = email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""
    if not domain:
        return False
    # 完全相符，或是允許網域的子網域（mail.tvbs.com.tw 也算 tvbs.com.tw）。
    return any(
        domain == allowed or domain.endswith("." + allowed)
        for allowed in ALLOWED_EMAIL_DOMAINS
    )


def verify_token(token: str) -> dict | None:
    """驗證 session token，回 {user_id, email, name}；無效回 None。"""
    if not ENABLED or not token:
        return None
    client = _get_jwk_client()
    if client is None:
        return None
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=ISSUER,
            # Clerk 的 session token 不帶 aud，關掉這項檢查；簽章與 issuer 已足以
            # 確認 token 出自我們這個 Clerk 實例。
            options={"verify_aud": False},
            # Clerk token 生命週期只有 60 秒、由前端自動續發，容器與 Clerk 之間
            # 幾秒的時鐘差就會誤判過期，給 10 秒寬容。
            leeway=10,
        )
    except Exception as exc:  # noqa: BLE001 - 驗不過就是沒登入，不需要細分原因
        print(f"[clerk_auth] token rejected: {exc}", flush=True)
        return None

    user_id = claims.get("sub", "")
    if not user_id:
        return None
    info = _user_info(user_id)
    email = info.get("email", "")

    # 網域檢查是 fail-closed：查不到 email 就擋。這裡的代價不對稱——放行的代價是
    # 陌生人可以消耗會花錢的 API，擋掉的代價只是使用者重試一次。
    # 查詢失敗不會被快取（見 _user_info），所以 Clerk 短暫故障會自行恢復。
    if ALLOWED_EMAIL_DOMAINS and not _domain_allowed(email):
        print(
            f"[clerk_auth] denied: user={user_id} email={email or '(查不到)'} "
            f"不在允許網域 {list(ALLOWED_EMAIL_DOMAINS)}",
            flush=True,
        )
        return None

    return {
        "user_id": user_id,
        "email": email,
        "name": info.get("name", ""),
    }


def extract_token(request) -> str:
    """從請求取出 session token。

    前端呼叫 API 時放在 Authorization: Bearer；瀏覽器直接開網頁時 Clerk 會種
    `__session` cookie，兩條路都要接得住（頁面本身也要擋）。
    """
    header = request.headers.get("authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return request.cookies.get("__session", "")
