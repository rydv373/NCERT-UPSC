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


def test_guess_chapter_title_skips_short_or_numeric_lines():
    text = "3\n2025-26\nFederalism\nFederalism is a system of government."
    title = extract_text.guess_chapter_title(text)
    assert title == "Federalism"


def test_guess_chapter_title_returns_none_for_empty_text():
    assert extract_text.guess_chapter_title("") is None


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
