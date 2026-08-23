"""Tests for the FTS5 search index: build a tiny in-memory index from fixture chapters
and assert known queries return the expected chapter with sane ranking.
"""
import sqlite3

import pytest

SCHEMA = """
CREATE TABLE chapters (
    id INTEGER PRIMARY KEY,
    subject TEXT, class INTEGER, book TEXT, book_code TEXT,
    chapter_no INTEGER, chapter_title TEXT, status TEXT
);
CREATE VIRTUAL TABLE chapters_fts USING fts5(
    chapter_title, body, content='', tokenize='porter unicode61'
);
"""

FIXTURE_CHAPTERS = [
    {
        "subject": "Geography", "class": 10, "book": "Contemporary India II", "book_code": "jess1",
        "chapter_no": 2, "chapter_title": "Water Resources",
        "body": "Water is a renewable resource. Multi-purpose river valley projects manage water resources across India.",
    },
    {
        "subject": "Polity", "class": 11, "book": "Political Theory", "book_code": "keps1",
        "chapter_no": 3, "chapter_title": "Federalism",
        "body": "Federalism divides power between the union and the states, a core feature of the Indian constitution.",
    },
    {
        "subject": "Geography", "class": 9, "book": "Contemporary India I", "book_code": "iess1",
        "chapter_no": 4, "chapter_title": "Climate",
        "body": "The monsoon dominates the climate of India, bringing seasonal rainfall across the subcontinent.",
    },
]


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    for i, ch in enumerate(FIXTURE_CHAPTERS, start=1):
        c.execute(
            "INSERT INTO chapters (id, subject, class, book, book_code, chapter_no, chapter_title, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'ok')",
            (i, ch["subject"], ch["class"], ch["book"], ch["book_code"], ch["chapter_no"], ch["chapter_title"]),
        )
        c.execute(
            "INSERT INTO chapters_fts (rowid, chapter_title, body) VALUES (?, ?, ?)",
            (i, ch["chapter_title"], ch["body"]),
        )
    c.commit()
    return c


def search(conn, query):
    sql = """
        SELECT c.chapter_title, c.book, bm25(chapters_fts) AS rank
        FROM chapters_fts JOIN chapters c ON c.id = chapters_fts.rowid
        WHERE chapters_fts MATCH ? ORDER BY rank
    """
    return conn.execute(sql, (query,)).fetchall()


def test_search_finds_expected_chapter_by_body_term(conn):
    results = search(conn, "federalism")
    assert len(results) == 1
    assert results[0][0] == "Federalism"


def test_search_monsoon_matches_climate_chapter(conn):
    results = search(conn, "monsoon")
    assert len(results) == 1
    assert results[0][0] == "Climate"


def test_search_water_resources_ranks_title_match_first(conn):
    results = search(conn, "water")
    assert len(results) >= 1
    assert results[0][0] == "Water Resources"


def test_search_no_match_returns_empty(conn):
    results = search(conn, "nonexistentterm12345")
    assert results == []


def test_search_multi_word_query(conn):
    results = search(conn, "union states")
    assert len(results) == 1
    assert results[0][0] == "Federalism"
