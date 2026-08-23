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


def _normalize_for_header_detection(line: str) -> str:
    """Strip a leading/trailing page-number token so a running header like
    "170 THEMES IN INDIAN HISTORY" and "172 THEMES IN INDIAN HISTORY" (same header, different
    page) are recognised as the same repeated line despite the page number changing.
    """
    return re.sub(r"^\d{1,4}\s+|\s+\d{1,4}$", "", line).strip()


def clean_text(raw_pages: list[str]) -> str:
    # Detect running headers/footers (book/chapter name repeated on most pages) by frequency:
    # any line whose page-number-stripped form appears on a large share of pages is treated as
    # boilerplate, not chapter content, even though NOISE_LINE_RES can't match it by pattern
    # alone (the exact text varies per book).
    pages_lines = [[l.strip() for l in page.splitlines() if l.strip()] for page in raw_pages]
    n_pages = len(pages_lines)
    repeated_norms = set()
    if n_pages >= 3:
        norm_counts: dict[str, int] = {}
        for lines in pages_lines:
            for norm in {_normalize_for_header_detection(l) for l in lines}:
                if len(norm) >= 4:  # skip near-empty normalized forms (e.g. pure page numbers)
                    norm_counts[norm] = norm_counts.get(norm, 0) + 1
        threshold = max(3, int(n_pages * 0.4))
        repeated_norms = {norm for norm, c in norm_counts.items() if c >= threshold}

    # NCERT books often print the chapter's own title as the running header on every page, so
    # the first occurrence of a "repeated" line is frequently the real heading, not boilerplate
    # — only strip repeats from the second occurrence onward, so the title survives once.
    seen_norms = set()
    cleaned_lines = []
    for lines in pages_lines:
        for stripped in lines:
            if any(pat.match(stripped) for pat in NOISE_LINE_RES):
                continue
            norm = _normalize_for_header_detection(stripped)
            if norm in repeated_norms:
                if norm in seen_norms:
                    continue
                seen_norms.add(norm)
            cleaned_lines.append(stripped)
    return "\n".join(cleaned_lines)


GENERIC_HEADING_WORDS = {"unit", "chapter", "part", "section"}
# boilerplate lines NCERT uses that are never the actual chapter title
GENERIC_HEADING_PHRASES = {"in this chapter", "introduction", "overview"}
# a title line ending in one of these clearly continues onto the next line
# (e.g. "Light, Shadows and" / "Reflections", "Natural Hazards and" / "Disasters")
DANGLING_LAST_WORDS = {"and", "or", "of", "the", "in", "for", "to", "a", "an", "&"}
ROMAN_NUMERAL_RE = re.compile(r"^(?=[MDCLXVI])M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")


def _is_generic_heading_word(word: str) -> bool:
    return word.lower() in GENERIC_HEADING_WORDS or bool(ROMAN_NUMERAL_RE.match(word.upper()))


def guess_chapter_title(cleaned_text: str) -> str | None:
    lines = cleaned_text.splitlines()
    for i, line in enumerate(lines):
        # a leading chapter-number digit (e.g. "2 From Trade to Territory") isn't part of the title
        line = re.sub(r"^\d{1,2}\s+(?=[A-Za-z])", "", line)

        alpha_chars = sum(c.isalpha() for c in line)
        if alpha_chars < 4:
            continue
        words = re.findall(r"[A-Za-z]+", line)
        # skip standalone "UNIT III"/"CHAPTER"/"SECTION I" divider lines and boilerplate phrases
        # like "In this chapter" / "Introduction" / "Overview" in favour of the real heading
        if words and all(_is_generic_heading_word(w) for w in words):
            continue
        if line.strip().lower().rstrip(".…") in GENERIC_HEADING_PHRASES:
            continue

        # a title line ending in a comma or a dangling connector word continues onto the next
        # line (e.g. "Gender," / "Religion and" / "Caste" spans three lines) — keep pulling
        # lines in until one doesn't dangle.
        j = i
        cur_words = words
        dangling = line.rstrip().endswith(",") or (cur_words and cur_words[-1].lower() in DANGLING_LAST_WORDS)
        while dangling and j + 1 < len(lines):
            j += 1
            cur_words = re.findall(r"[A-Za-z]+", lines[j])
            dangling = lines[j].rstrip().endswith(",") or (cur_words and cur_words[-1].lower() in DANGLING_LAST_WORDS)

        title = " ".join([line.strip()] + [l.strip() for l in lines[i + 1:j + 1]])
        return title[:200]
    return None


def _drop_fake_bold_duplicates(chars: list) -> set:
    """Return ids of characters that are "fake bold" duplicates to drop.

    Some NCERT PDFs simulate bold by drawing the exact same glyph twice at a ~0.5-1pt offset
    instead of embedding a real bold font, which otherwise doubles every letter in the extracted
    text (e.g. "Food Security" -> "FFoooodd SSeeccuurriittyy"). A genuinely repeated letter within
    a word sits a full character-width apart (several points), so a same-text char within ~1.5pt
    of one already kept is treated as a duplicate stroke, not a second letter.
    """
    # Group by character first rather than relying on any single sort order being adjacency-
    # preserving: rounding/sorting by position alone can push two genuinely-close characters
    # (e.g. top=133.39 and top=134.59, 1.2pt apart) into non-adjacent buckets whenever unrelated
    # characters elsewhere on the page happen to round to the value in between. Only characters
    # with identical text can possibly be duplicate strokes of each other, so comparing within
    # same-text groups is both correct and cheap.
    by_text: dict[str, list] = {}
    for c in chars:
        by_text.setdefault(c["text"], []).append(c)

    drop_ids = set()
    for group in by_text.values():
        kept: list = []
        for c in group:
            if any(abs(c["x0"] - k["x0"]) < 1.5 and abs(c["top"] - k["top"]) < 1.5 for k in kept):
                drop_ids.add(id(c))
            else:
                kept.append(c)
    return drop_ids


def extract_pdf_text(pdf_path) -> list[str]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # Drop rotated (non-upright) characters before extracting: NCERT chapter pages
            # commonly carry a decorative sideways running-header (chapter name + number)
            # printed in the margin, which extract_text() otherwise interleaves into the
            # reading order character-reversed and ahead of the real heading.
            chars = [c for c in page.chars if c.get("upright", True)]
            dup_ids = _drop_fake_bold_duplicates(chars)
            cleaned_page = page.filter(
                lambda obj: obj.get("object_type") != "char"
                or (obj.get("upright", True) and id(obj) not in dup_ids)
            )
            # y_tolerance=8 (default 3) merges oversized drop-cap initial letters — common on
            # NCERT chapter-opening headings — back onto the same line as the rest of the word;
            # verified this doesn't merge separate body paragraph lines or footer/page-number
            # stamps, which sit much further apart.
            text = cleaned_page.extract_text(y_tolerance=8) or ""
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
