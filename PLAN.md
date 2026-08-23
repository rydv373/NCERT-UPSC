# NCERT-for-UPSC Knowledge Base — Plan

Goal: collect the standard "NCERT for UPSC" textbook set, extract and organize it chapter-by-chapter with clean metadata, and expose it through a local full-text search dashboard so any topic can be found instantly across subjects/classes.

Status legend: `[ ]` todo · `[x]` done · `[~]` in progress

---

## 1. Scope

### 1.1 Book list (standard UPSC set — confirmed with user)

| Subject | Classes | Books |
|---|---|---|
| History | 6–12 | Our Pasts I, II, III (Part 1 & 2); India & the Contemporary World I, II; Themes in World History; Themes in Indian History I, II, III |
| Geography | 6–12 | The Earth Our Habitat; Our Environment; Resource and Development; Contemporary India I, II; Fundamentals of Physical Geography; India — Physical Environment; Fundamentals of Human Geography; India — People and Economy |
| Polity (Pol. Science) | 9–12 | Democratic Politics I, II; Indian Constitution at Work; Political Theory; Contemporary World Politics; Politics in India Since Independence |
| Economics | 9–12 | Economics (Class 9); Understanding Economic Development; Indian Economic Development; Statistics for Economics; Introductory Microeconomics; Introductory Macroeconomics |
| Science | 6–10 | Science (one book per class) |

~38 books, ~280–320 chapters total (estimate, confirmed once catalog is scraped). English medium only for v1.

### 1.2 Out of scope (v1)
- Hindi/other-language editions
- Sociology, Art & Culture, Environment (Shankar IAS-style) supplementary books — noted as a possible v2 addition
- OCR for scanned/image-only pages (flag and skip; most NCERT PDFs are text-native)

---

## 2. Data sourcing strategy

**Revised 2026-08-23 after inspecting the live site — see rationale below.**

**Curated book→code list, not a live dropdown scrape.** `textbook.php`'s `change1()` JS was
hand-parsed once to recover every book code in scope (see `scripts/01_scrape_catalog.py:BOOK_LIST`).
NCERT's ongoing NCF-2023 curriculum rollout has already retired several standard-UPSC titles from
the *live* dropdown — confirmed 404 on `ncert.nic.in` — even though the site still serves stable
per-chapter PDF URLs (`https://ncert.nic.in/textbook/pdf/{code}{chapter:02d}.pdf`) for books that
remain current:
- Classes 6–9 Social Science (History/Geography/Civics/Economics) has been replaced by the combined
  "Exploring Society – India and Beyond" / "Understanding Society India and Beyond" NCF books.
- Class 6 History, Geography, and Science old editions are fully retired.
- Class 7–8 old editions and Class 9 Science are still live directly.

Per user decision (2026-08-23): **old/classic editions are used throughout** (matching the
established "NCERT for UPSC" reading list), not the new NCF replacements.

**Chapter discovery, per book:**
1. If the book's code is still live on the official site, HEAD-probe
   `https://ncert.nic.in/textbook/pdf/{code}{01,02,...}.pdf` directly and record which chapters
   respond 200 (`source: "official"`).
2. If retired (chapter 01 404s), query the **Wayback Machine CDX API**
   (`web.archive.org/cdx/search/cdx?url=ncert.nic.in/textbook/pdf/{code}*&filter=statuscode:200`)
   to discover which chapter PDFs were ever archived, then download from the closest archived
   snapshot (`source: "wayback"`).
3. Every download is verified as a valid PDF (magic bytes `%PDF`, size > ~20KB); retry once on
   failure.

**The two GitHub mirrors originally proposed here (`avallark/NCERT-TextBooks`, `utsingh/upsc`) were
checked and dropped**: neither hosts per-chapter class 6–9 PDFs (avallark has only whole-book PDFs
for classes 8–11; utsingh/upsc is mostly current-affairs compilations, not NCERT textbooks). The
Wayback Machine turned out to be the only reliable fallback and covers every retired book/chapter
found so far.

**Licensing note:** NCERT explicitly permits free download/use of its textbooks for educational
purposes; this project only stores content locally for personal search/study, not redistribution.

---

## 3. Project structure

```
NCERT-UPSC/
├── PLAN.md
├── requirements.txt
├── data/
│   ├── catalog.json          # master metadata index (source of truth)
│   ├── catalog.csv           # same, flat, for quick eyeballing
│   ├── raw_pdfs/<Subject>/<Class>/<Book>/ch_XX.pdf
│   ├── text/<Subject>/<Class>/<Book>/ch_XX.txt   # cleaned extracted text
│   └── search_index.sqlite   # SQLite FTS5 full-text index
├── scripts/
│   ├── 01_scrape_catalog.py  # build catalog.json from ncert.nic.in (+ fallback mirrors)
│   ├── 02_download_pdfs.py   # download all chapter PDFs per catalog
│   ├── 03_extract_text.py    # PDF -> cleaned per-chapter text
│   ├── 04_build_index.py     # build/refresh SQLite FTS5 index from text + catalog
│   └── utils.py               # shared helpers (paths, slugify, http session w/ retries)
├── app/
│   └── app.py                 # Streamlit dashboard
└── tests/
    ├── test_scraper.py
    ├── test_extract.py
    └── test_search.py
```

`catalog.json` schema (one row per chapter — the unit of search):
```json
{
  "subject": "Geography",
  "class": 10,
  "book": "Contemporary India II",
  "book_code": "jess3",
  "chapter_no": 2,
  "chapter_title": "Water Resources",
  "source": "official | mirror:<repo>",
  "pdf_path": "data/raw_pdfs/Geography/Class10/Contemporary_India_II/ch_02.pdf",
  "text_path": "data/text/Geography/Class10/Contemporary_India_II/ch_02.txt",
  "word_count": 3120,
  "status": "ok | pdf_missing | extract_failed | image_only"
}
```

---

## 4. Pipeline steps

1. **Scrape catalog** (`01_scrape_catalog.py`) — build the full book/chapter list against the Section 1.1 scope; write `catalog.json`. Cross-check chapter counts look sane (e.g. no book with 0 or 40 chapters) before proceeding.
2. **Download** (`02_download_pdfs.py`) — polite rate-limited downloads (small delay between requests), resumable (skip files already present), fallback to mirror repos on 404s, log failures to `catalog.json` status field.
3. **Extract text** (`03_extract_text.py`) — `pdfplumber` per PDF → per-chapter `.txt`; strip headers/footers/page numbers via regex heuristics; detect near-empty extraction (image-only scan) and mark `image_only` in catalog for visibility (no OCR in v1).
4. **Build search index** (`04_build_index.py`) — SQLite with an FTS5 virtual table (`chapters_fts`) over chapter text + a regular table carrying the catalog metadata joined by chapter id; supports ranked full-text search with snippet/highlight.
5. **Dashboard** (`app/app.py`, Streamlit) —
   - Search bar (FTS5 query, ranked results with highlighted snippets)
   - Filters: subject, class, book
   - Browse tree view (Subject → Class → Book → Chapter) as an alternative to search
   - Chapter reader pane (full extracted text, plus a link/path to the original PDF)
   - Basic corpus stats (books/chapters indexed, coverage gaps from `status` field)

---

## 5. Testing

- `tests/test_scraper.py` — catalog parser against a saved sample HTML fixture of `textbook.php`; asserts expected book codes/chapter counts extracted correctly.
- `tests/test_extract.py` — text extraction + cleaning on 1–2 sample PDFs (small known chapter); asserts non-trivial word count and absence of obvious footer junk.
- `tests/test_search.py` — build a tiny in-memory FTS5 index from fixture chapters; assert a known query returns the expected chapter and that ranking is sane.
- **Manual smoke test before full run:** pipeline steps 1–4 executed end-to-end on a *single* book (e.g. Class 10 Geography) first, output eyeballed, before scaling to all ~38 books — cheaper to catch a bad URL pattern or bad text-cleaning regex early.
- Dashboard manually exercised in-browser: run a handful of real UPSC-relevant queries (e.g. "fundamental rights", "green revolution", "monsoon", "federalism") and confirm relevant chapters surface.

---

## 6. Execution order

1. [x] Write `PLAN.md` (this file)
2. [x] Scaffold project (folders, `requirements.txt`, `utils.py`)
3. [x] Implement + smoke-test `01_scrape_catalog.py` on one subject/class first
4. [x] Run full catalog scrape across all subjects/classes in scope; review `catalog.json` counts — 35 books, 266 chapters
5. [x] Implement `02_download_pdfs.py`
6. [x] Implement `03_extract_text.py`
7. [x] Implement `04_build_index.py`
8. [x] Implement `app/app.py` Streamlit dashboard
9. [x] Write `tests/` (16 tests, mocked/offline)
10. [ ] Run full download + extraction + index build; review failure/`image_only` counts
11. [ ] Smoke-test dashboard in-browser with real UPSC queries
12. [ ] Final review with user; note any gaps for possible v2 (OCR, Hindi medium, extra subjects)

---

## 7. Open risks / assumptions

- NCERT PDF URL pattern (`{code}{chapter:02d}.pdf`) is based on documented conventions from existing open-source NCERT downloaders, not an official API — will be verified against real responses in step 3 of execution order, with mirror fallback if it doesn't hold for some books.
- ncert.nic.in may rate-limit or change markup — scraper isolates this into one module so it's the only piece likely to need rework.
- No OCR in v1, so any scanned-image chapters will show up empty/marked `image_only` rather than silently missing.
