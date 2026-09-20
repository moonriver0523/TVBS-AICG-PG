# -*- coding: utf-8 -*-
"""2026-09-15 B32：維基查照行程內 TTL 快取。消化與生圖各查一次，第二次不得再打 HTTP。"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("NEWS_IMAGE_API_KEY", "test-key")

import photo_lookup  # noqa: E402


def _page(*, title="某人", qid="Q1", thumbnail=True, missing=False) -> bytes:
    page: dict = {"title": title}
    if missing:
        page["missing"] = True
    if qid:
        page["pageprops"] = {"wikibase_item": qid}
    if thumbnail:
        page["thumbnail"] = {"source": "https://upload.wikimedia.org/x.jpg"}
    return json.dumps({"query": {"pages": [page]}}).encode("utf-8")


def _claim(prop: str, value) -> bytes:
    return json.dumps(
        {"claims": {prop: [{"mainsnak": {"datavalue": {"value": value}}}]}}
    ).encode("utf-8")


def _human_hit_side_effect():
    """一次成功查照：wikipedia query → P31=Q5 → 下載圖片。"""
    return [_page(), _claim("P31", {"id": "Q5"}), b"binary"]


class PhotoLookupCacheTests(unittest.TestCase):
    def setUp(self):
        photo_lookup.clear_photo_lookup_cache()

    def tearDown(self):
        photo_lookup.clear_photo_lookup_cache()

    def test_same_name_hits_http_only_once(self):
        calls = _human_hit_side_effect()
        with patch.object(photo_lookup, "_get", side_effect=calls) as get:
            first = photo_lookup.find_reference_photo("賴清德", langs=("zh",))
            second = photo_lookup.find_reference_photo("賴清德", langs=("zh",))
        self.assertIsNotNone(first)
        self.assertEqual(first.image_base64, second.image_base64)
        self.assertEqual(get.call_count, 3)

    def test_miss_is_cached_until_short_ttl_expires(self):
        clock = {"now": 0.0}

        def monotonic():
            return clock["now"]

        with patch.object(photo_lookup, "_get", return_value=None) as get:
            with patch.object(photo_lookup.time, "monotonic", side_effect=monotonic):
                self.assertIsNone(photo_lookup.find_reference_photo("查無此人", langs=("zh",)))
                self.assertEqual(get.call_count, 1)
                clock["now"] = 59.0
                self.assertIsNone(photo_lookup.find_reference_photo("查無此人", langs=("zh",)))
                self.assertEqual(get.call_count, 1)
                clock["now"] = 61.0
                self.assertIsNone(photo_lookup.find_reference_photo("查無此人", langs=("zh",)))
                self.assertEqual(get.call_count, 2)

    def test_hit_survives_the_short_ttl_but_expires_after_fifteen_minutes(self):
        clock = {"now": 0.0}

        def monotonic():
            return clock["now"]

        with patch.object(photo_lookup, "_get", side_effect=_human_hit_side_effect() * 2) as get:
            with patch.object(photo_lookup.time, "monotonic", side_effect=monotonic):
                first = photo_lookup.find_reference_photo("卓榮泰", langs=("zh",))
                self.assertIsNotNone(first)
                self.assertEqual(get.call_count, 3)
                clock["now"] = 61.0
                again = photo_lookup.find_reference_photo("卓榮泰", langs=("zh",))
                self.assertEqual(again.image_base64, first.image_base64)
                self.assertEqual(get.call_count, 3)
                clock["now"] = 15 * 60 + 1
                photo_lookup.find_reference_photo("卓榮泰", langs=("zh",))
                self.assertEqual(get.call_count, 6)

    def test_different_names_do_not_share_a_cache_entry(self):
        def by_url(url, timeout):
            if "titles=%E7%94%B2" in url or "titles=甲" in url:
                return _page(title="甲")
            if "titles=%E4%B9%99" in url or "titles=乙" in url:
                return _page(title="乙")
            if "wbgetclaims" in url:
                return _claim("P31", {"id": "Q5"})
            return b"binary"

        with patch.object(photo_lookup, "_get", side_effect=by_url) as get:
            a = photo_lookup.find_reference_photo("甲", langs=("zh",))
            b = photo_lookup.find_reference_photo("乙", langs=("zh",))
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertEqual(get.call_count, 6)
        self.assertNotEqual(a.source_page, b.source_page)

    def test_evicts_the_oldest_entry_when_over_the_cap(self):
        original_max = photo_lookup.CACHE_MAX_ENTRIES
        photo_lookup.CACHE_MAX_ENTRIES = 2
        try:
            with patch.object(
                photo_lookup,
                "_get",
                side_effect=_human_hit_side_effect() * 4,
            ) as get:
                photo_lookup.find_reference_photo("一人", langs=("zh",))
                photo_lookup.find_reference_photo("二人", langs=("zh",))
                self.assertEqual(get.call_count, 6)
                photo_lookup.find_reference_photo("三人", langs=("zh",))
                self.assertEqual(get.call_count, 9)
                photo_lookup.find_reference_photo("一人", langs=("zh",))
                self.assertEqual(get.call_count, 12)
        finally:
            photo_lookup.CACHE_MAX_ENTRIES = original_max

    def test_timeout_is_not_part_of_the_cache_key(self):
        with patch.object(photo_lookup, "_get", side_effect=_human_hit_side_effect()) as get:
            photo_lookup.find_reference_photo("柯文哲", langs=("zh",), timeout=10)
            photo_lookup.find_reference_photo("柯文哲", langs=("zh",), timeout=3)
        self.assertEqual(get.call_count, 3)

    def test_oversized_photo_evicts_old_entries_until_byte_budget_fits(self):
        original = photo_lookup.CACHE_MAX_BYTES
        photo_lookup.CACHE_MAX_BYTES = 20
        try:
            small = photo_lookup.ReferencePhoto(
                image_base64="a" * 10,
                mime_type="image/jpeg",
                image_url="u",
                source_page="p",
                lang="zh",
            )
            huge = photo_lookup.ReferencePhoto(
                image_base64="b" * 15,
                mime_type="image/jpeg",
                image_url="u",
                source_page="p",
                lang="zh",
            )
            small_outcome = photo_lookup.PortraitLookupOutcome(
                photo=small, entry_found=True, matched_name="old", language="zh",
            )
            huge_outcome = photo_lookup.PortraitLookupOutcome(
                photo=huge, entry_found=True, matched_name="new", language="zh",
            )
            photo_lookup._cache_put(("old", (), ("zh",)), small_outcome)
            photo_lookup._cache_put(("new", (), ("zh",)), huge_outcome)
            self.assertIs(
                photo_lookup._cache_get(("old", (), ("zh",))),
                photo_lookup._CACHE_MISS,
            )
            kept = photo_lookup._cache_get(("new", (), ("zh",)))
            self.assertEqual(kept.photo.image_base64, huge.image_base64)
            total = sum(
                len(outcome.photo.image_base64)
                for _expires, outcome in photo_lookup._CACHE.values()
                if outcome is not None and outcome.photo is not None
            )
            self.assertLessEqual(total, 20)
            self.assertEqual(total, 15)
        finally:
            photo_lookup.CACHE_MAX_BYTES = original

    def test_clear_photo_lookup_cache_forces_a_refetch(self):
        with patch.object(photo_lookup, "_get", side_effect=_human_hit_side_effect() * 2) as get:
            photo_lookup.find_reference_photo("金正恩", langs=("zh",))
            photo_lookup.clear_photo_lookup_cache()
            photo_lookup.find_reference_photo("金正恩", langs=("zh",))
        self.assertEqual(get.call_count, 6)
