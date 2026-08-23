"""Download all chapter PDFs listed in data/catalog.json.

Resumable: skips files already present on disk. Downloads from the official ncert.nic.in URL
for source="official" rows, and from the archived Wayback Machine snapshot for source="wayback"
rows (looked up via the Wayback "available" API, since catalog.json only records that a chapter
existed, not its exact snapshot timestamp). Retries once on failure. Updates catalog.json's
status field in place (pdf_missing on failure) and writes it back at the end.
"""
import sys

from utils import (
    CATALOG_JSON,
    PROJECT_ROOT,
    get_session,
    is_valid_pdf,
    official_chapter_url,
    polite_sleep,
    wayback_snapshot_url,
)
import json


def load_catalog() -> list[dict]:
    with open(CATALOG_JSON, encoding="utf-8") as f:
        return json.load(f)


def save_catalog(rows: list[dict]) -> None:
    with open(CATALOG_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)


def download_one(session, row: dict) -> bool:
    pdf_path = PROJECT_ROOT / row["pdf_path"]
    if pdf_path.exists() and pdf_path.stat().st_size > 20_000:
        return True  # already downloaded, resumable skip

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    code = row["book_code"]
    chapter_no = row["chapter_no"]

    if row["source"] == "official":
        url = official_chapter_url(code, chapter_no)
    else:
        original_url = official_chapter_url(code, chapter_no)
        snapshot = wayback_snapshot_url(session, original_url)
        if not snapshot:
            return False
        url = snapshot

    for attempt in range(2):
        try:
            resp = session.get(url, timeout=30)
            polite_sleep()
            if resp.status_code == 200 and is_valid_pdf(resp.content):
                pdf_path.write_bytes(resp.content)
                return True
        except Exception:
            pass
    return False


def main():
    rows = load_catalog()
    total = sum(1 for r in rows if r["status"] == "ok")
    done = 0
    failed = 0
    session = get_session()

    for row in rows:
        if row["status"] != "ok":
            continue
        ok = download_one(session, row)
        done += 1
        if not ok:
            failed += 1
            row["status"] = "pdf_missing"
        if done % 10 == 0 or done == total:
            print(f"[{done}/{total}] downloaded ({failed} failed so far)", file=sys.stderr)

    save_catalog(rows)
    print(f"\nDone. {done - failed}/{total} chapters downloaded, {failed} failed.", file=sys.stderr)


if __name__ == "__main__":
    main()
