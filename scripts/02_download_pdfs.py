"""Download all chapter PDFs listed in data/catalog.json.

Resumable: skips files already present and well-formed on disk. Downloads from the official
ncert.nic.in URL for source="official" rows. For source="wayback" rows, tries every archived
snapshot timestamp of that chapter (newest first), not just the Wayback "available" API's single
"closest" pick — archive.org intermittently serves a degraded/truncated response for one snapshot
while other timestamps of the exact same file are fine, so falling through several candidates
recovers far more chapters than retrying one URL. Updates catalog.json's status field in place
(pdf_missing on failure) and writes it back at the end.
"""
import json
import sys
import time

from utils import (
    CATALOG_JSON,
    PROJECT_ROOT,
    get_session,
    is_valid_pdf,
    official_chapter_url,
    polite_sleep,
    wayback_all_snapshots,
)


def load_catalog() -> list[dict]:
    with open(CATALOG_JSON, encoding="utf-8") as f:
        return json.load(f)


def save_catalog(rows: list[dict]) -> None:
    with open(CATALOG_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)


def download_one(session, row: dict) -> bool:
    pdf_path = PROJECT_ROOT / row["pdf_path"]
    if pdf_path.exists() and is_valid_pdf(pdf_path.read_bytes()):
        return True  # already downloaded and well-formed, resumable skip

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    code = row["book_code"]
    chapter_no = row["chapter_no"]
    original_url = official_chapter_url(code, chapter_no)

    if row["source"] == "official":
        candidate_urls = [original_url] * 2  # one retry on transient network failure
    else:
        candidate_urls = wayback_all_snapshots(session, original_url)
        if not candidate_urls:
            return False

    for i, url in enumerate(candidate_urls):
        if i > 0:
            time.sleep(1.5)  # back off before trying the next candidate snapshot
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
