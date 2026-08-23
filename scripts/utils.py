"""Shared helpers for the NCERT-for-UPSC pipeline: paths, HTTP session, slugify, Wayback lookup."""
import re
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_PDFS_DIR = DATA_DIR / "raw_pdfs"
TEXT_DIR = DATA_DIR / "text"
CATALOG_JSON = DATA_DIR / "catalog.json"
CATALOG_CSV = DATA_DIR / "catalog.csv"
SEARCH_INDEX_DB = DATA_DIR / "search_index.sqlite"

NCERT_BASE = "https://ncert.nic.in/textbook/pdf"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
REQUEST_DELAY_SECONDS = 0.4  # politeness delay between requests to ncert.nic.in


def slugify(text: str) -> str:
    """Turn a book/subject title into a filesystem-safe path component."""
    text = text.strip().replace("&", "and")
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s]+", "_", text)
    return text.strip("_")


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def official_chapter_url(code: str, chapter_no: int) -> str:
    return f"{NCERT_BASE}/{code}{chapter_no:02d}.pdf"


def polite_sleep() -> None:
    time.sleep(REQUEST_DELAY_SECONDS)


def is_valid_pdf(content: bytes, min_size: int = 20_000) -> bool:
    """Check magic bytes, minimum size, and that the file actually ends with a PDF trailer.

    Header-only checks let truncated downloads through (seen in practice with flaky Wayback
    Machine responses: a real %PDF header followed by a connection that dropped mid-transfer).
    A well-formed PDF ends with %%EOF (optionally followed by whitespace/a startxref block).
    """
    if len(content) < min_size or content[:4] != b"%PDF":
        return False
    return b"%%EOF" in content[-2048:]


def wayback_all_snapshots(session: requests.Session, original_url: str) -> list[str]:
    """Return every archived timestamp (200-status) for original_url, newest first.

    Trying multiple independent archived copies (rather than trusting a single "closest" pick)
    matters because archive.org intermittently serves a degraded/truncated response for one
    snapshot while other timestamps of the exact same file are fine.
    """
    try:
        resp = session.get(
            "http://web.archive.org/cdx/search/cdx",
            params={
                "url": original_url,
                "output": "json",
                "filter": "statuscode:200",
                "limit": 50,
            },
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        return []

    if not rows or len(rows) < 2:
        return []

    header = rows[0]
    idx_ts = header.index("timestamp")
    timestamps = sorted({row[idx_ts] for row in rows[1:]}, reverse=True)
    return [f"http://web.archive.org/web/{ts}/{original_url}" for ts in timestamps]


def wayback_cdx_chapters(session: requests.Session, code: str, max_chapter: int = 25) -> list[int]:
    """Query the Wayback CDX API to discover which {code}NN.pdf chapters were ever archived
    with a 200 status. Returns a sorted list of chapter numbers found.
    """
    url = f"http://web.archive.org/cdx/search/cdx"
    params = {
        "url": f"ncert.nic.in/textbook/pdf/{code}*",
        "output": "json",
        "filter": "statuscode:200",
        "limit": 500,
    }
    try:
        resp = session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        return []

    if not rows or len(rows) < 2:
        return []

    header = rows[0]
    idx_original = header.index("original")
    idx_status = header.index("statuscode")

    pattern = re.compile(rf"{re.escape(code)}(\d{{2}})\.pdf$", re.IGNORECASE)
    chapters = set()
    for row in rows[1:]:
        original = row[idx_original]
        status = row[idx_status]
        if status != "200":
            continue
        m = pattern.search(original)
        if m:
            n = int(m.group(1))
            if 1 <= n <= max_chapter:
                chapters.add(n)
    return sorted(chapters)
