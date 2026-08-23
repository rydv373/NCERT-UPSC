"""Build data/catalog.json (and catalog.csv) for the standard NCERT-for-UPSC book set.

Book -> NCERT book-code mapping is curated (see BOOK_LIST below), not scraped live from
ncert.nic.in/textbook.php on every run. That page's book-selection JS was hand-parsed once
(2026-08-23) to recover every code in scope; a handful of books already have their old edition
code fully retired from the visible dropdown by NCERT's ongoing NCF-2023 curriculum rollout
(classes 6-9, Social Science + some Science titles), even though NCERT keeps stable per-chapter
PDF URLs in the form https://ncert.nic.in/textbook/pdf/{code}{chapter:02d}.pdf. Re-scraping the
dropdown on every run would not recover those retired codes anyway, so the curated table is the
more reliable source of truth for a scope this fixed (~35 books).

For each book this script determines which chapters actually exist:
- source="official": chapters are found by probing official URLs directly (HEAD requests).
- source="wayback": the code is retired from the official site (chapter 01 404s); chapters are
  discovered via the Wayback Machine CDX API and downloaded from archived snapshots later.
"""
import csv
import json
import sys

from utils import (
    CATALOG_CSV,
    CATALOG_JSON,
    get_session,
    official_chapter_url,
    polite_sleep,
    wayback_cdx_chapters,
)

# subject, class, book title, ncert book code, max chapter to probe for official books
BOOK_LIST = [
    # History (6-12)
    ("History", 6, "Our Pasts I", "fess1", None),
    ("History", 7, "Our Pasts II", "gess1", 20),
    ("History", 8, "Our Pasts III", "hess2", 20),
    ("History", 9, "India and the Contemporary World I", "iess3", None),
    ("History", 10, "India and the Contemporary World II", "jess3", 20),
    ("History", 11, "Themes in World History", "kehs1", 20),
    ("History", 12, "Themes in Indian History I", "lehs1", 20),
    ("History", 12, "Themes in Indian History II", "lehs2", 20),
    ("History", 12, "Themes in Indian History III", "lehs3", 20),
    # Geography (6-12)
    ("Geography", 6, "The Earth Our Habitat", "fess2", None),
    ("Geography", 7, "Our Environment", "gess2", 20),
    ("Geography", 8, "Resource and Development", "hess4", 20),
    ("Geography", 9, "Contemporary India I", "iess1", None),
    ("Geography", 10, "Contemporary India II", "jess1", 20),
    ("Geography", 11, "Fundamentals of Physical Geography", "kegy2", 20),
    ("Geography", 11, "India Physical Environment", "kegy1", 20),
    ("Geography", 12, "Fundamentals of Human Geography", "legy1", 20),
    ("Geography", 12, "India People and Economy", "legy2", 20),
    # Polity (9-12)
    ("Polity", 9, "Democratic Politics I", "iess4", None),
    ("Polity", 10, "Democratic Politics II", "jess4", 20),
    ("Polity", 11, "Political Theory", "keps1", 20),
    ("Polity", 11, "Indian Constitution at Work", "keps2", 20),
    ("Polity", 12, "Contemporary World Politics", "leps1", 20),
    ("Polity", 12, "Politics in India Since Independence", "leps2", 20),
    # Economics (9-12)
    ("Economics", 9, "Economics", "iess2", None),
    ("Economics", 10, "Understanding Economic Development", "jess2", 20),
    ("Economics", 11, "Indian Economic Development", "keec1", 20),
    ("Economics", 11, "Statistics for Economics", "kest1", 20),
    ("Economics", 12, "Introductory Microeconomics", "leec2", 20),
    ("Economics", 12, "Introductory Macroeconomics", "leec1", 20),
    # Science (6-10)
    ("Science", 6, "Science", "fesc1", None),
    ("Science", 7, "Science", "gesc1", 20),
    ("Science", 8, "Science", "hesc1", 20),
    ("Science", 9, "Science", "iesc1", 20),
    ("Science", 10, "Science", "jesc1", 20),
]


def probe_official_chapters(session, code: str, max_chapter: int) -> list[int]:
    """HEAD-probe official chapter URLs 1..max_chapter, stop after 2 consecutive misses."""
    found = []
    misses = 0
    for n in range(1, max_chapter + 1):
        url = official_chapter_url(code, n)
        try:
            resp = session.head(url, timeout=15, allow_redirects=True)
        except Exception:
            resp = None
        polite_sleep()
        if resp is not None and resp.status_code == 200:
            found.append(n)
            misses = 0
        else:
            misses += 1
            if misses >= 2 and found:
                break
            if misses >= 2 and not found:
                break
    return found


def build_catalog() -> list[dict]:
    session = get_session()
    rows = []
    for subject, klass, book, code, max_chapter in BOOK_LIST:
        print(f"-- {subject} | Class {klass} | {book} ({code})", file=sys.stderr)

        if max_chapter is not None:
            chapters = probe_official_chapters(session, code, max_chapter)
            source = "official"
            if not chapters:
                print(f"   official probe found 0 chapters, falling back to wayback", file=sys.stderr)
                chapters = wayback_cdx_chapters(session, code)
                source = "wayback"
        else:
            chapters = wayback_cdx_chapters(session, code)
            source = "wayback"

        if not chapters:
            print(f"   WARNING: no chapters found for {code} via any source", file=sys.stderr)
            rows.append({
                "subject": subject,
                "class": klass,
                "book": book,
                "book_code": code,
                "chapter_no": None,
                "chapter_title": None,
                "source": source,
                "pdf_path": None,
                "text_path": None,
                "word_count": None,
                "status": "pdf_missing",
            })
            continue

        print(f"   {len(chapters)} chapters found ({source}): {chapters}", file=sys.stderr)
        for n in chapters:
            book_slug = f"{book.replace(' ', '_')}"
            pdf_path = f"data/raw_pdfs/{subject}/Class{klass}/{book_slug}/ch_{n:02d}.pdf"
            text_path = f"data/text/{subject}/Class{klass}/{book_slug}/ch_{n:02d}.txt"
            rows.append({
                "subject": subject,
                "class": klass,
                "book": book,
                "book_code": code,
                "chapter_no": n,
                "chapter_title": None,
                "source": source,
                "pdf_path": pdf_path,
                "text_path": text_path,
                "word_count": None,
                "status": "ok",
            })
    return rows


def write_catalog(rows: list[dict]) -> None:
    CATALOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(CATALOG_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    fieldnames = [
        "subject", "class", "book", "book_code", "chapter_no", "chapter_title",
        "source", "pdf_path", "text_path", "word_count", "status",
    ]
    with open(CATALOG_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    rows = build_catalog()
    write_catalog(rows)

    total_books = len({(r["subject"], r["class"], r["book"]) for r in rows})
    total_chapters = sum(1 for r in rows if r["status"] == "ok")
    missing_books = sum(1 for r in rows if r["status"] == "pdf_missing")
    print(f"\nDone. {total_books} books, {total_chapters} chapters catalogued.", file=sys.stderr)
    if missing_books:
        print(f"WARNING: {missing_books} books had no chapters found at all.", file=sys.stderr)
    print(f"Wrote {CATALOG_JSON} and {CATALOG_CSV}", file=sys.stderr)


if __name__ == "__main__":
    main()
