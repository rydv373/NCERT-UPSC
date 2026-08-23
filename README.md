# NCERT for UPSC

A local knowledge base of the standard "NCERT for UPSC" textbook set — collected chapter-by-chapter
with clean metadata and exposed through a full-text search dashboard, so any topic can be found
instantly across subjects and classes.

Covers History, Geography, Polity, Economics (classes 6–12) and Science (classes 6–10) — the
~35-book reading list UPSC aspirants traditionally build on. English medium only, old/classic
editions throughout (see [PLAN.md](PLAN.md) for why that matters and how sourcing works).

## What's in here

```
data/
  catalog.json / catalog.csv   # one row per chapter: subject, class, book, source, paths, status
  raw_pdfs/<Subject>/<Class>/<Book>/ch_XX.pdf
  text/<Subject>/<Class>/<Book>/ch_XX.txt
  search_index.sqlite          # SQLite FTS5 full-text index, built from the above
scripts/
  01_scrape_catalog.py         # builds catalog.json from a curated book list + live NCERT probing
  02_download_pdfs.py          # downloads every chapter PDF listed in the catalog
  03_extract_text.py           # PDF -> cleaned per-chapter text (pdfplumber)
  04_build_index.py            # builds the FTS5 search index
  utils.py                     # shared helpers
app/
  app.py                       # Streamlit search + browse dashboard
tests/                         # offline, mocked — no network needed to run
```

`data/raw_pdfs`, `data/text`, and `search_index.sqlite` are gitignored — they're generated
locally by the pipeline and are not committed (the PDFs are copyrighted NCERT content; this repo
only ships the code that fetches and indexes them for personal study, not the content itself).

## How the sourcing works

Book → NCERT book-code mapping is a curated list, not a live scrape of the book-selection
dropdown — several classic editions have been retired from that dropdown by NCERT's ongoing
curriculum rollout, even though their PDFs are still reachable by direct URL or via the Wayback
Machine. Full rationale in [PLAN.md § 2](PLAN.md).

- If a book's code is still live on `ncert.nic.in`, chapters are found by probing
  `https://ncert.nic.in/textbook/pdf/{code}{chapter:02d}.pdf` directly.
- If retired, chapters are discovered via the Wayback Machine CDX API and downloaded from an
  archived snapshot.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Running the pipeline

Run in order from the `scripts/` directory (each step is resumable — re-running skips work
already done):

```bash
cd scripts
python3 01_scrape_catalog.py    # -> data/catalog.json, data/catalog.csv
python3 02_download_pdfs.py     # -> data/raw_pdfs/**/*.pdf
python3 03_extract_text.py      # -> data/text/**/*.txt, updates catalog.json
python3 04_build_index.py       # -> data/search_index.sqlite
```

`02_download_pdfs.py` is polite (small delay between requests) and safe to re-run — it skips
files already downloaded. `03_extract_text.py` flags image-only/scanned chapters as `image_only`
in the catalog instead of writing empty text (no OCR in v1).

## Running the dashboard

```bash
streamlit run app/app.py
```

Opens a browser tab with:
- **Search** — full-text query with ranked results, snippets, and subject/class/book filters
- **Browse** — Subject → Class → Book → Chapter tree, for when you know what you want
- A chapter reader pane showing the cleaned extracted text and the path to the original PDF

## Tests

```bash
pytest tests/
```

All tests are offline (network calls mocked) and fast — safe to run anytime without hitting
ncert.nic.in or the Wayback Machine.

## Status / known gaps

See the status checklist and "Open risks / assumptions" in [PLAN.md](PLAN.md) for what's done,
what's left, and known limitations (no OCR, no Hindi medium, no v2 subjects yet).
