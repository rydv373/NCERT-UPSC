"""Tests for the catalog-building logic in scripts/01_scrape_catalog.py and scripts/utils.py.

Network calls are mocked so these run offline and deterministically.
"""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import utils  # noqa: E402

spec = importlib.util.spec_from_file_location("scrape_catalog", SCRIPTS_DIR / "01_scrape_catalog.py")
scrape_catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scrape_catalog)


def make_head_response(status_code):
    resp = MagicMock()
    resp.status_code = status_code
    return resp


def test_probe_official_chapters_stops_after_two_misses(monkeypatch):
    monkeypatch.setattr(utils, "REQUEST_DELAY_SECONDS", 0)
    session = MagicMock()
    # chapters 1-5 exist, 6+ don't
    responses = {n: 200 if n <= 5 else 404 for n in range(1, 10)}

    def fake_head(url, timeout=15, allow_redirects=True):
        for n, code in responses.items():
            if url.endswith(f"{n:02d}.pdf"):
                return make_head_response(code)
        return make_head_response(404)

    session.head.side_effect = fake_head
    chapters = scrape_catalog.probe_official_chapters(session, "testcode", max_chapter=9)
    assert chapters == [1, 2, 3, 4, 5]


def test_probe_official_chapters_no_chapters_found(monkeypatch):
    monkeypatch.setattr(utils, "REQUEST_DELAY_SECONDS", 0)
    session = MagicMock()
    session.head.return_value = make_head_response(404)
    chapters = scrape_catalog.probe_official_chapters(session, "deadcode", max_chapter=5)
    assert chapters == []


def test_wayback_cdx_chapters_filters_by_status_and_pattern():
    session = MagicMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = [
        ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
        ["k1", "t1", "https://ncert.nic.in/textbook/pdf/abc101.pdf", "application/pdf", "200", "d1", "100"],
        ["k2", "t2", "https://ncert.nic.in/textbook/pdf/abc102.pdf", "text/html", "301", "d2", "100"],
        ["k3", "t3", "https://ncert.nic.in/textbook/pdf/abc102.pdf", "application/pdf", "200", "d3", "100"],
        ["k4", "t4", "https://ncert.nic.in/textbook/pdf/abc1cc.jpg", "image/jpeg", "200", "d4", "100"],
    ]
    session.get.return_value = resp

    chapters = utils.wayback_cdx_chapters(session, "abc1")
    # chapter 1 and 2 found (200 status, matching NNpdf pattern); the jpg and the 301 row excluded
    assert chapters == [1, 2]


def test_wayback_cdx_chapters_handles_empty_response():
    session = MagicMock()
    session.get.side_effect = Exception("network error")
    chapters = utils.wayback_cdx_chapters(session, "nocode")
    assert chapters == []


def test_book_list_has_no_duplicate_book_codes_per_class_subject():
    seen = set()
    for subject, klass, book, code, _ in scrape_catalog.BOOK_LIST:
        key = (subject, klass, book)
        assert key not in seen, f"duplicate entry: {key}"
        seen.add(key)


def test_slugify_produces_filesystem_safe_names():
    assert utils.slugify("India & the Contemporary World") == "India_and_the_Contemporary_World"
    assert utils.slugify("  Our Pasts I  ") == "Our_Pasts_I"
