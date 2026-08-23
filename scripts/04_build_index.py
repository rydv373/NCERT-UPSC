"""Build/refresh the SQLite FTS5 full-text index from data/catalog.json + extracted text files.

Two tables:
- chapters: regular table carrying catalog metadata, one row per chapter (id = rowid).
- chapters_fts: FTS5 virtual table over chapter_title + body text, joined to `chapters` by id,
  so search results can be ranked (bm25) and rendered with snippet()/highlight().
"""
import json
import sqlite3
import sys

from utils import CATALOG_JSON, PROJECT_ROOT, SEARCH_INDEX_DB

SCHEMA = """
DROP TABLE IF EXISTS chapters_fts;
DROP TABLE IF EXISTS chapters;

CREATE TABLE chapters (
    id INTEGER PRIMARY KEY,
    subject TEXT NOT NULL,
    class INTEGER NOT NULL,
    book TEXT NOT NULL,
    book_code TEXT NOT NULL,
    chapter_no INTEGER NOT NULL,
    chapter_title TEXT,
    source TEXT,
    pdf_path TEXT,
    text_path TEXT,
    word_count INTEGER,
    status TEXT
);

CREATE VIRTUAL TABLE chapters_fts USING fts5(
    chapter_title,
    body,
    content='',
    tokenize='porter unicode61'
);
"""


def build_index() -> None:
    with open(CATALOG_JSON, encoding="utf-8") as f:
        rows = json.load(f)

    SEARCH_INDEX_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SEARCH_INDEX_DB)
    conn.executescript(SCHEMA)

    indexed = 0
    for row in rows:
        if row["status"] != "ok" or not row.get("text_path"):
            continue
        text_path = PROJECT_ROOT / row["text_path"]
        if not text_path.exists():
            continue
        body = text_path.read_text(encoding="utf-8")

        cur = conn.execute(
            """INSERT INTO chapters
               (subject, class, book, book_code, chapter_no, chapter_title,
                source, pdf_path, text_path, word_count, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["subject"], row["class"], row["book"], row["book_code"],
                row["chapter_no"], row.get("chapter_title"), row.get("source"),
                row.get("pdf_path"), row.get("text_path"), row.get("word_count"),
                row["status"],
            ),
        )
        chapter_id = cur.lastrowid
        conn.execute(
            "INSERT INTO chapters_fts (rowid, chapter_title, body) VALUES (?, ?, ?)",
            (chapter_id, row.get("chapter_title") or "", body),
        )
        indexed += 1

    conn.commit()
    conn.close()
    print(f"Indexed {indexed} chapters into {SEARCH_INDEX_DB}", file=sys.stderr)


if __name__ == "__main__":
    build_index()
