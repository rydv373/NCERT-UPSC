"""Streamlit dashboard: search + browse the NCERT-for-UPSC corpus."""
import sqlite3
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from utils import PROJECT_ROOT, SEARCH_INDEX_DB  # noqa: E402

st.set_page_config(page_title="NCERT for UPSC", layout="wide")


@st.cache_resource
def get_conn():
    conn = sqlite3.connect(str(SEARCH_INDEX_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def run_search(conn, query: str, subject: str, klass, book: str, limit: int = 50):
    sql = """
        SELECT c.id, c.subject, c.class, c.book, c.chapter_no, c.chapter_title,
               c.pdf_path, c.text_path,
               snippet(chapters_fts, 1, '**', '**', ' … ', 20) AS snippet,
               bm25(chapters_fts) AS rank
        FROM chapters_fts
        JOIN chapters c ON c.id = chapters_fts.rowid
        WHERE chapters_fts MATCH ?
    """
    params = [query]
    if subject and subject != "All":
        sql += " AND c.subject = ?"
        params.append(subject)
    if klass and klass != "All":
        sql += " AND c.class = ?"
        params.append(int(klass))
    if book and book != "All":
        sql += " AND c.book = ?"
        params.append(book)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def get_distinct(conn, col, where="", params=()):
    rows = conn.execute(f"SELECT DISTINCT {col} FROM chapters {where} ORDER BY {col}", params).fetchall()
    return [r[0] for r in rows]


def corpus_stats(conn):
    total = conn.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
    books = conn.execute("SELECT COUNT(DISTINCT book || class) FROM chapters").fetchone()[0]
    return total, books


def render_chapter(row):
    st.subheader(f"{row['book']} (Class {row['class']}) — Ch. {row['chapter_no']}: {row['chapter_title'] or '(untitled)'}")
    st.caption(f"{row['subject']} · Class {row['class']} · source PDF: {row['pdf_path']}")
    text_path = PROJECT_ROOT / row["text_path"]
    if text_path.exists():
        st.text_area("Chapter text", text_path.read_text(encoding="utf-8"), height=500)
    else:
        st.warning("Extracted text not found on disk.")
    pdf_path = PROJECT_ROOT / row["pdf_path"]
    if pdf_path.exists():
        st.caption(f"Original PDF: {pdf_path}")


def main():
    st.title("NCERT for UPSC — Search & Browse")

    if not SEARCH_INDEX_DB.exists():
        st.error(f"Search index not found at {SEARCH_INDEX_DB}. Run scripts/04_build_index.py first.")
        return

    conn = get_conn()
    total, books = corpus_stats(conn)
    st.caption(f"{books} books · {total} chapters indexed")

    tab_search, tab_browse = st.tabs(["Search", "Browse"])

    with tab_search:
        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
        with col1:
            query = st.text_input("Search the corpus", placeholder="e.g. federalism, monsoon, fundamental rights")
        with col2:
            subject = st.selectbox("Subject", ["All"] + get_distinct(conn, "subject"))
        with col3:
            classes = get_distinct(conn, "class")
            klass = st.selectbox("Class", ["All"] + [str(c) for c in classes])
        with col4:
            book_where = ""
            book_params = ()
            if subject != "All":
                book_where = "WHERE subject = ?"
                book_params = (subject,)
            book = st.selectbox("Book", ["All"] + get_distinct(conn, "book", book_where, book_params))

        if query:
            try:
                results = run_search(conn, query, subject, klass, book)
            except sqlite3.OperationalError as e:
                st.error(f"Search query error: {e}")
                results = []
            st.write(f"{len(results)} result(s)")
            for row in results:
                with st.expander(f"{row['book']} (Class {row['class']}) — Ch. {row['chapter_no']}: {row['chapter_title'] or '(untitled)'}"):
                    st.markdown(row["snippet"], unsafe_allow_html=False)
                    if st.button("Open full chapter", key=f"open_{row['id']}"):
                        st.session_state["open_chapter_id"] = row["id"]

        if "open_chapter_id" in st.session_state:
            row = conn.execute("SELECT * FROM chapters WHERE id = ?", (st.session_state["open_chapter_id"],)).fetchone()
            if row:
                st.divider()
                render_chapter(row)

    with tab_browse:
        subjects = get_distinct(conn, "subject")
        for subj in subjects:
            with st.expander(subj):
                classes = get_distinct(conn, "class", "WHERE subject = ?", (subj,))
                for klass in classes:
                    st.markdown(f"**Class {klass}**")
                    books_list = get_distinct(conn, "book", "WHERE subject = ? AND class = ?", (subj, klass))
                    for b in books_list:
                        chapters = conn.execute(
                            "SELECT id, chapter_no, chapter_title, status FROM chapters "
                            "WHERE subject = ? AND class = ? AND book = ? ORDER BY chapter_no",
                            (subj, klass, b),
                        ).fetchall()
                        st.write(f"— {b} ({len(chapters)} chapters)")
                        cols = st.columns(4)
                        for i, ch in enumerate(chapters):
                            label = f"Ch.{ch['chapter_no']}: {(ch['chapter_title'] or '')[:30]}"
                            if cols[i % 4].button(label, key=f"browse_{ch['id']}"):
                                st.session_state["open_chapter_id"] = ch["id"]

        if "open_chapter_id" in st.session_state:
            row = conn.execute("SELECT * FROM chapters WHERE id = ?", (st.session_state["open_chapter_id"],)).fetchone()
            if row:
                st.divider()
                render_chapter(row)


if __name__ == "__main__":
    main()
