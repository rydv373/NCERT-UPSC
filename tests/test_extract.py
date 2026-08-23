"""Tests for text cleaning/extraction logic in scripts/03_extract_text.py."""
import importlib.util
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("extract_text", SCRIPTS_DIR / "03_extract_text.py")
extract_text = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract_text)


def test_clean_text_strips_page_numbers_and_year_stamps():
    raw_pages = [
        "12\nWater Resources\nThis chapter discusses water resources in India.\n2025-26",
        "Reprint 2024-25\nMore content here about rivers and rainfall.\n45",
    ]
    cleaned = extract_text.clean_text(raw_pages)
    assert "2025-26" not in cleaned
    assert "Reprint 2024-25" not in cleaned
    assert "12" not in cleaned.splitlines()
    assert "45" not in cleaned.splitlines()
    assert "Water Resources" in cleaned
    assert "rivers and rainfall" in cleaned


def test_clean_text_keeps_substantive_lines_with_embedded_numbers():
    raw_pages = ["Chapter 3 discusses the 1857 revolt in detail."]
    cleaned = extract_text.clean_text(raw_pages)
    assert "1857 revolt" in cleaned


def test_clean_text_strips_repeats_of_running_header_but_keeps_first_occurrence():
    # regression: a running header repeated across most pages, with a page number prefix that
    # changes each time, isn't caught by the fixed NOISE_LINE_RES patterns. The first occurrence
    # is kept (NCERT often prints the real chapter title as the running header too, so blindly
    # stripping every occurrence can delete the only copy of the actual title); only the repeats
    # from the second page onward are noise worth removing.
    raw_pages = [
        f"{170 + i * 2} THEMES IN INDIAN HISTORY – PART II\nSome real paragraph text {i}."
        for i in range(6)
    ]
    cleaned = extract_text.clean_text(raw_pages)
    assert cleaned.count("THEMES IN INDIAN HISTORY") == 1
    for i in range(6):
        assert f"Some real paragraph text {i}." in cleaned


def test_clean_text_does_not_strip_short_documents_repeated_lines():
    # the repeated-header heuristic only kicks in for n_pages >= 3, so short chapters aren't
    # at risk of a real short recurring phrase being misidentified as a header
    raw_pages = ["Overview\nBody text one.", "Overview\nBody text two."]
    cleaned = extract_text.clean_text(raw_pages)
    assert "Overview" in cleaned


def test_guess_chapter_title_skips_short_or_numeric_lines():
    text = "3\n2025-26\nFederalism\nFederalism is a system of government."
    title = extract_text.guess_chapter_title(text)
    assert title == "Federalism"


def test_guess_chapter_title_returns_none_for_empty_text():
    assert extract_text.guess_chapter_title("") is None


def test_guess_chapter_title_skips_generic_unit_chapter_divider_lines():
    text = "UNIT\nIII\nCLIMATE AND VEGETATION\nThis unit deals with weather patterns."
    assert extract_text.guess_chapter_title(text) == "CLIMATE AND VEGETATION"


def test_guess_chapter_title_merges_two_line_dangling_title():
    text = "Light, Shadows and\nReflections\nWe see so many objects around us."
    assert extract_text.guess_chapter_title(text) == "Light, Shadows and Reflections"


def test_guess_chapter_title_merges_three_line_dangling_title():
    text = "Gender,\nReligion and\nCaste\nOverview\nThe existence of social diversity..."
    assert extract_text.guess_chapter_title(text) == "Gender, Religion and Caste"


def test_guess_chapter_title_does_not_merge_complete_single_word_title():
    text = "Federalism\nOverview\nIn the previous chapter, we noted..."
    assert extract_text.guess_chapter_title(text) == "Federalism"


def test_guess_chapter_title_strips_leading_chapter_number():
    text = "2 From Trade to Territory\nSome body text follows here."
    assert extract_text.guess_chapter_title(text) == "From Trade to Territory"


def test_guess_chapter_title_skips_in_this_chapter_boilerplate():
    text = "In this chapter…\nGovernment Budget\nThe budget is a statement..."
    assert extract_text.guess_chapter_title(text) == "Government Budget"


def test_guess_chapter_title_skips_section_divider():
    text = "SECTION I\nPastoralists in the Modern World\nBody text about herders."
    assert extract_text.guess_chapter_title(text) == "Pastoralists in the Modern World"


def test_guess_chapter_title_does_not_treat_india_as_a_roman_numeral():
    # regression: an unanchored roman-numeral regex would match "I" as a prefix of "India"
    # and wrongly treat this whole line as a skippable generic divider
    text = "India and the Contemporary World\nBody text follows."
    assert extract_text.guess_chapter_title(text) == "India and the Contemporary World"


def make_char(text, x0, top):
    return {"text": text, "x0": x0, "top": top, "upright": True}


def test_drop_fake_bold_duplicates_removes_close_offset_pairs():
    # "Food" simulated-bold: every letter drawn twice ~0.7pt apart
    chars = [
        make_char("F", 385.44, 107.76), make_char("F", 384.72, 108.48),
        make_char("o", 393.36, 107.76), make_char("o", 392.64, 108.48),
        make_char("o", 402.60, 107.76), make_char("o", 401.88, 108.48),
        make_char("d", 411.84, 107.76), make_char("d", 411.12, 108.48),
    ]
    drop_ids = extract_text._drop_fake_bold_duplicates(chars)
    kept = [c for c in chars if id(c) not in drop_ids]
    assert "".join(c["text"] for c in kept) == "Food"


def test_drop_fake_bold_duplicates_keeps_genuinely_repeated_letters():
    # two real, separate 'o' letters a full character-width apart (not a bold duplicate)
    chars = [make_char("o", 100.0, 50.0), make_char("o", 108.0, 50.0)]
    drop_ids = extract_text._drop_fake_bold_duplicates(chars)
    assert drop_ids == set()


def test_drop_fake_bold_duplicates_not_fooled_by_rounding_bucket_edge_case():
    # regression: top values 1.2pt apart that round to DIFFERENT integers (133 vs 135, since
    # 134.59 rounds to 135) used to land in non-adjacent sort buckets whenever unrelated chars
    # elsewhere on the page rounded to the value in between, so the old sort-adjacency approach
    # missed this real duplicate pair entirely.
    chars = [
        make_char("F", 140.4, 134.59),
        make_char("F", 140.4, 133.39),
        # unrelated chars elsewhere on the page that would sit in the "134" bucket
        make_char("X", 400.0, 134.0),
        make_char("Y", 500.0, 134.2),
    ]
    drop_ids = extract_text._drop_fake_bold_duplicates(chars)
    f_chars = [c for c in chars if c["text"] == "F"]
    assert sum(1 for c in f_chars if id(c) in drop_ids) == 1


def test_process_row_always_recomputes_chapter_title(tmp_path, monkeypatch):
    # regression: chapter_title must be recomputed on every extraction run, not left stale from
    # a previous (possibly buggy) run just because a value already exists
    row = {
        "pdf_path": "x.pdf",
        "text_path": "x.txt",
        "status": "ok",
        "chapter_title": "stale garbled title",
    }
    (tmp_path / "x.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(extract_text, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(extract_text, "extract_pdf_text", lambda p: ["Federalism\nOverview\n" + "word " * 40])

    extract_text.process_row(row)
    assert row["chapter_title"] == "Federalism"


def test_min_words_threshold_flags_image_only(tmp_path, monkeypatch):
    import json
    row = {
        "pdf_path": "data/raw_pdfs/x.pdf",
        "text_path": "data/text/x.txt",
        "status": "ok",
        "chapter_title": None,
    }
    fake_pdf = tmp_path / "x.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(extract_text, "PROJECT_ROOT", tmp_path)
    row["pdf_path"] = "x.pdf"
    row["text_path"] = "x.txt"
    monkeypatch.setattr(extract_text, "extract_pdf_text", lambda p: ["short"])

    extract_text.process_row(row)
    assert row["status"] == "image_only"
