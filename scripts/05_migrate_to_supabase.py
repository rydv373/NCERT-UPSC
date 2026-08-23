"""One-off/rerunnable migration: push the local catalog + extracted text + PDFs into Supabase.

Run supabase/schema.sql in the Supabase SQL editor first (creates the `chapters` table and the
"pdfs" Storage bucket must exist — create it manually in the Supabase dashboard: Storage -> New
bucket -> name "pdfs" -> Public bucket).

Requires two env vars (the service_role key bypasses RLS so this script can write; never use it
anywhere client-facing):
    SUPABASE_URL
    SUPABASE_SERVICE_KEY

Usage:
    export SUPABASE_URL=https://xxxxx.supabase.co
    export SUPABASE_SERVICE_KEY=eyJ...
    python3 05_migrate_to_supabase.py
"""
import json
import os
import sys

from supabase import create_client

from utils import CATALOG_JSON, PROJECT_ROOT

BUCKET = "pdfs"


def get_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY env vars first.", file=sys.stderr)
        sys.exit(1)
    return create_client(url, key)


UPSERT_BATCH_SIZE = 50


def upload_pdf(sb, pdf_path, storage_path) -> bool:
    try:
        data = pdf_path.read_bytes()
        sb.storage.from_(BUCKET).upload(
            storage_path, data,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
        return True
    except Exception as e:
        print(f"   PDF upload failed for {storage_path}: {e}", file=sys.stderr)
        return False


def flush_batch(sb, batch: list) -> int:
    """Upsert a batch of chapter rows. Returns how many succeeded.

    Falls back to one-row-at-a-time on a batch failure so a single malformed row (e.g. a data
    issue in one chapter) doesn't discard the rest of an otherwise-good batch.
    """
    if not batch:
        return 0
    try:
        sb.table("chapters").upsert(batch, on_conflict="book_code,chapter_no").execute()
        return len(batch)
    except Exception as e:
        print(f"   Batch upsert failed ({len(batch)} rows), retrying individually: {e}", file=sys.stderr)
        succeeded = 0
        for record in batch:
            try:
                sb.table("chapters").upsert(record, on_conflict="book_code,chapter_no").execute()
                succeeded += 1
            except Exception as row_e:
                print(f"   Row upsert failed for {record['book_code']} ch.{record['chapter_no']}: {row_e}", file=sys.stderr)
        return succeeded


def main():
    sb = get_client()

    with open(CATALOG_JSON, encoding="utf-8") as f:
        rows = json.load(f)

    ok_rows = [r for r in rows if r["status"] == "ok"]
    total = len(ok_rows)
    migrated = 0
    skipped = 0
    batch = []

    for i, row in enumerate(ok_rows, start=1):
        pdf_path = PROJECT_ROOT / row["pdf_path"]
        text_path = PROJECT_ROOT / row["text_path"]

        if not pdf_path.exists() or not text_path.exists():
            skipped += 1
            continue

        body = text_path.read_text(encoding="utf-8")
        # storage path mirrors the local layout, minus the "data/raw_pdfs/" prefix
        storage_path = str(row["pdf_path"]).removeprefix("data/raw_pdfs/")

        if not upload_pdf(sb, pdf_path, storage_path):
            skipped += 1
            continue

        batch.append({
            "subject": row["subject"],
            "class": row["class"],
            "book": row["book"],
            "book_code": row["book_code"],
            "chapter_no": row["chapter_no"],
            "chapter_title": row.get("chapter_title"),
            "source": row.get("source"),
            "pdf_storage_path": storage_path,
            "word_count": row.get("word_count"),
            "status": row["status"],
            "body": body,
        })

        if len(batch) >= UPSERT_BATCH_SIZE:
            migrated += flush_batch(sb, batch)
            batch = []
            print(f"[{i}/{total}] migrated so far: {migrated} ({skipped} skipped)", file=sys.stderr)

    migrated += flush_batch(sb, batch)
    failed = total - migrated

    print(f"\nDone. {migrated}/{total} chapters migrated to Supabase, {failed} failed/skipped.", file=sys.stderr)


if __name__ == "__main__":
    main()
