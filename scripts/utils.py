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
    return len(content) >= min_size and content[:4] == b"%PDF"


def wayback_snapshot_url(session: requests.Session, original_url: str) -> str | None:
    """Look up the most recent Wayback Machine snapshot of original_url, if any.

    Returns a fully-qualified web.archive.org URL usable for direct download, or None.
    """
    try:
        resp = session.get(
            "https://archive.org/wayback/available",
            params={"url": original_url},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        closest = data.get("archived_snapshots", {}).get("closest")
        if closest and closest.get("available"):
            return closest["url"]
    except Exception:
        return None
    return None


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
