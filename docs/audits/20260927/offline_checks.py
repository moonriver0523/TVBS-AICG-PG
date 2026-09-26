"""Offline audit runner; no .env loading, no external sockets, no real credentials.

Run from repository root: python docs/audits/20260927/offline_checks.py [suite]
The audit mode demonstrates existing defects; it is not a passing regression suite.
"""
import os
import sys
import time
import tempfile
import atexit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
import dotenv

_logs = tempfile.TemporaryDirectory(prefix="aicg-offline-audit-")
atexit.register(_logs.cleanup)

dotenv.load_dotenv = lambda *args, **kwargs: False
for key in list(os.environ):
    if any(part in key for part in (
        "API_KEY", "SECRET", "TOKEN", "PASSWORD", "CLERK", "LANGFUSE",
        "GCS_HISTORY", "AUDIT_ARCHIVE", "DIGEST_MODEL", "IMAGE_BACKEND", "DIGEST_BACKEND",
    )):
        os.environ.pop(key, None)
os.environ.update(
    OPENAI_API_KEY="offline-audit-dummy",
    OPENROUTER_API_KEY="offline-audit-dummy",
    NEWS_IMAGE_API_KEY="offline-audit-internal",
    REQUEST_LOG="1",
    REQUEST_LOG_DIR=_logs.name,
    LANGFUSE_TRACING_ENABLED="false",
)


def deny_external_network(event, args):
    if event == "socket.connect":
        address = args[1]
        # Windows asyncio uses loopback sockets for its own wakeup pipe.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return
        raise RuntimeError("OFFLINE_AUDIT_NETWORK_BLOCKED")


sys.addaudithook(deny_external_network)

if "suite" in sys.argv:
    import unittest

    started = time.monotonic()
    suite = unittest.defaultTestLoader.discover("tests")
    print("COLLECTED", suite.countTestCases(), flush=True)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print("AUDIT_SUMMARY", {
        "run": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped),
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
        "seconds": round(time.monotonic() - started, 1),
    }, flush=True)
    sys.exit(not result.wasSuccessful())

import main

token = main._current_user.set({"user_id": "audit-same-user"})
try:
    main._remember_digest(news_text="article-A", variable="A")
    main._remember_digest(news_text="article-B", variable="B")
    record = main._enrich_archive_fields({"prompt": "image-prompt-for-A"})
    print("AUD-04", {"expected_news": "article-A", "actual_news": record["news_text"],
                     "defect_reproduced": record["news_text"] != "article-A"})
finally:
    main._current_user.reset(token)
    main._digest_memo.pop("audit-same-user", None)

# Inspect names and exclusion rules only. Never read secret file contents.
import fnmatch

patterns = [line.strip() for line in (ROOT / ".dockerignore").read_text().splitlines()
            if line.strip() and not line.startswith("#")]
backups = [p.name for p in ROOT.glob(".env.bak-*") if p.is_file()]
included = [name for name in backups if not any(fnmatch.fnmatchcase(name, p) for p in patterns)]
print("AUD-01", {"backup_count": len(backups), "not_excluded_count": len(included),
                 "defect_reproduced": bool(included),
                 "note": "Static check of current simple patterns; no Docker build or deployment."})

import asyncio
from types import SimpleNamespace
from unittest.mock import patch


async def check_auth_blocking():
    marks = []

    async def ticker():
        await asyncio.sleep(0.01)
        marks.append(time.monotonic())

    async def next_handler(request):
        await asyncio.sleep(0)
        return "ok"

    def slow_verify(token):
        time.sleep(0.1)  # Simulate synchronous cache-miss I/O; never accesses network.
        return {"user_id": "audit-user"}

    started = time.monotonic()
    task = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    req = SimpleNamespace(url=SimpleNamespace(path="/api/generate"),
                          headers={"authorization": "Bearer AUDIT_DUMMY"}, cookies={})
    with patch.object(main.clerk_auth, "ENABLED", True), \
         patch.object(main.clerk_auth, "verify_token", side_effect=slow_verify):
        await main.clerk_login_gate(req, next_handler)
    await task
    delay = marks[0] - started
    print("AUD-07", {"ticker_expected_ms": 10, "ticker_actual_ms": round(delay*1000),
                     "defect_reproduced": delay > 0.09})


asyncio.run(check_auth_blocking())
