"""Extract cleaned per-chapter text from downloaded PDFs.

For every catalog row with status "ok" and an existing PDF, extracts text with pdfplumber,
strips common NCERT header/footer noise (bare page numbers, "20XX-XX" rationalisation-year
stamps, repeated running headers), and writes the result to text_path. Chapters with near-empty
extraction are marked "image_only" (no OCR in v1) instead of silently producing an empty file.
Also fills in catalog chapter_title (best-effort: first substantial line of chapter text) and
word_count, then writes catalog.json back.
"""
import json
import re
import sys

import pdfplumber

from utils import CATALOG_JSON, PROJECT_ROOT

MIN_WORDS_FOR_TEXT = 30  # below this, treat extraction as image_only

# Lines that are pure noise: bare page numbers, rationalisation-year stamps, etc.
NOISE_LINE_RES = [
    re.compile(r"^\s*\d{1,4}\s*$"),                       # bare page number
    re.compile(r"^\s*20\d{2}-\d{2}\s*$"),                  # "2025-26" footer stamp
    re.compile(r"^\s*Reprint\s+20\d{2}-\d{2}\s*$", re.I),
    re.compile(r"^\s*Rationalised\s+20\d{2}-\d{2}\s*$", re.I),
]


def clean_text(raw_pages: list[str]) -> str:
    cleaned_lines = []
    for page in raw_pages:
        for line in page.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if any(pat.match(stripped) for pat in NOISE_LINE_RES):
                continue
            cleaned_lines.append(stripped)
    return "\n".join(cleaned_lines)


def guess_chapter_title(cleaned_text: str) -> str | None:
    for line in cleaned_text.splitlines():
        alpha_chars = sum(c.isalpha() for c in line)
        if alpha_chars < 4:
            continue
        return line[:200]
    return None


def extract_pdf_text(pdf_path) -> list[str]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return pages


def process_row(row: dict) -> None:
    pdf_path = PROJECT_ROOT / row["pdf_path"]
    text_path = PROJECT_ROOT / row["text_path"]

    if not pdf_path.exists():
        row["status"] = "pdf_missing"
        return

    try:
        raw_pages = extract_pdf_text(pdf_path)
    except Exception as e:
        print(f"   extract_failed: {pdf_path} ({e})", file=sys.stderr)
        row["status"] = "extract_failed"
        return

    cleaned = clean_text(raw_pages)
    word_count = len(cleaned.split())

    if word_count < MIN_WORDS_FOR_TEXT:
        row["status"] = "image_only"
        row["word_count"] = word_count
        return

    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(cleaned, encoding="utf-8")

    row["word_count"] = word_count
    row["status"] = "ok"
    if not row.get("chapter_title"):
        row["chapter_title"] = guess_chapter_title(cleaned)


def main():
    with open(CATALOG_JSON, encoding="utf-8") as f:
        rows = json.load(f)

    total = sum(1 for r in rows if r["status"] == "ok")
    done = 0
    counts = {"ok": 0, "image_only": 0, "extract_failed": 0, "pdf_missing": 0}

    for row in rows:
        if row["status"] != "ok":
            continue
        process_row(row)
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        done += 1
        if done % 20 == 0 or done == total:
            print(f"[{done}/{total}] extracted", file=sys.stderr)

    with open(CATALOG_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {counts}", file=sys.stderr)


if __name__ == "__main__":
    main()
