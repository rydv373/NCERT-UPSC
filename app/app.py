"""Streamlit dashboard: search + browse the NCERT-for-UPSC corpus.

Backend: Supabase (Postgres + Storage) if SUPABASE_URL/SUPABASE_ANON_KEY are configured (via
.streamlit/secrets.toml locally, or the app's Secrets panel when deployed) — this is what
scripts/05_migrate_to_supabase.py populates. Falls back to the local SQLite FTS5 index
(data/search_index.sqlite, built by scripts/04_build_index.py) when Supabase isn't configured, so
`streamlit run app/app.py` still works for local development without any cloud account. See
DEPLOYMENT.md.
"""
import os
import sqlite3
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from utils import PROJECT_ROOT, SEARCH_INDEX_DB  # noqa: E402

st.set_page_config(page_title="NCERT for UPSC", layout="wide")

BUCKET = "pdfs"
CACHE_TTL = 300  # seconds — corpus is static within a session, so this just bounds staleness


def get_secret(name: str) -> str | None:
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name)


@st.cache_resource
def get_backend():
    """Returns ("supabase", client) if configured AND reachable, else ("sqlite", connection) if
    the local index exists, else (None, None).

    Credentials being present isn't enough to commit to Supabase — e.g. supabase/schema.sql not
    having been run yet (table missing) would otherwise surface as an unhandled exception deep in
    the UI instead of a clean fallback, so this does one lightweight probe query up front.
    """
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_ANON_KEY")
    if url and key:
        from supabase import create_client
        client = create_client(url, key)
        try:
            client.table("chapters").select("id").limit(1).execute()
            return "supabase", client
        except Exception as e:
            st.warning(f"Supabase configured but not reachable ({e}); falling back to local SQLite if available.")

    if SEARCH_INDEX_DB.exists():
        conn = sqlite3.connect(str(SEARCH_INDEX_DB), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return "sqlite", conn

    return None, None


# ---------------------------------------------------------------------------
# Supabase backend
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL)
def _sb_all_chapters(_sb):
    """One round trip for every chapter's browse-relevant columns, avoiding an N+1 query
    pattern (a naive per-subject/class/book loop would issue dozens of sequential requests)."""
    return (
        _sb.table("chapters")
        .select("id,subject,class,book,chapter_no,chapter_title")
        .order("subject").order("class").order("book").order("chapter_no")
        .execute().data
    )


@st.cache_data(ttl=CACHE_TTL)
def _sb_corpus_stats(_sb):
    total = _sb.table("chapters").select("id", count="exact").execute().count
    books = len({(r["book"], r["class"]) for r in _sb_all_chapters(_sb)})
    return total, books


def _sb_search(sb, query, subject, klass, book, limit=50):
    resp = sb.rpc("search_chapters", {
        "search_query": query,
        "p_subject": None if subject == "All" else subject,
        "p_class": None if klass == "All" else int(klass),
        "p_book": None if book == "All" else book,
        "p_limit": limit,
    }).execute()
    return resp.data or []


def _sb_get_chapter(sb, chapter_id):
    resp = sb.table("chapters").select("*").eq("id", chapter_id).execute()
    return resp.data[0] if resp.data else None


def _sb_render_chapter(sb, row):
    if row.get("pdf_storage_path"):
        url = sb.storage.from_(BUCKET).get_public_url(row["pdf_storage_path"])
        st.link_button("Open original PDF", url)
        st.caption(f"Storage path: {row['pdf_storage_path']}")
    else:
        st.warning("No PDF on file for this chapter.")
    body = row.get("body")
    if body:
        st.text_area("Chapter text", body, height=500, key=f"text_{row['id']}")
    else:
        st.warning("Extracted text not found.")


# ---------------------------------------------------------------------------
# Local SQLite backend
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL)
def _sqlite_all_chapters(_conn):
    rows = _conn.execute(
        "SELECT id, subject, class, book, chapter_no, chapter_title FROM chapters "
        "ORDER BY subject, class, book, chapter_no"
    ).fetchall()
    return [dict(r) for r in rows]


@st.cache_data(ttl=CACHE_TTL)
def _sqlite_corpus_stats(_conn):
    total = _conn.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
    books = _conn.execute("SELECT COUNT(DISTINCT book || class) FROM chapters").fetchone()[0]
    return total, books


def _sqlite_search(conn, query, subject, klass, book, limit=50):
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
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _sqlite_get_chapter(conn, chapter_id):
    row = conn.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    return dict(row) if row else None


def _sqlite_render_chapter(row):
    pdf_path = PROJECT_ROOT / row["pdf_path"]
    if pdf_path.exists():
        st.download_button(
            "Open original PDF", data=pdf_path.read_bytes(), file_name=pdf_path.name,
            mime="application/pdf", key=f"pdf_{row['id']}",
        )
        st.caption(f"Path: {pdf_path}")
    else:
        st.warning(f"Original PDF not found on disk: {pdf_path}")

    text_path = PROJECT_ROOT / row["text_path"]
    if text_path.exists():
        st.text_area("Chapter text", text_path.read_text(encoding="utf-8"), height=500, key=f"text_{row['id']}")
    else:
        st.warning("Extracted text not found on disk.")


# ---------------------------------------------------------------------------
# Backend-agnostic UI
# ---------------------------------------------------------------------------

def render_chapter(backend, client, row):
    st.subheader(f"{row['book']} (Class {row['class']}) — Ch. {row['chapter_no']}: {row['chapter_title'] or '(untitled)'}")
    st.caption(f"{row['subject']} · Class {row['class']}")
    if backend == "supabase":
        _sb_render_chapter(client, row)
    else:
        _sqlite_render_chapter(row)


def main():
    st.title("NCERT for UPSC — Search & Browse")

    backend, client = get_backend()
    if backend is None:
        st.error(
            "No data backend available. Either configure Supabase "
            "(SUPABASE_URL / SUPABASE_ANON_KEY in .streamlit/secrets.toml) or run the local "
            "pipeline through scripts/04_build_index.py to build data/search_index.sqlite. "
            "See DEPLOYMENT.md."
        )
        return
    st.caption(f"Backend: {'Supabase' if backend == 'supabase' else 'local SQLite'}")

    if backend == "supabase":
        all_chapters = _sb_all_chapters(client)
        total, books = _sb_corpus_stats(client)
    else:
        all_chapters = _sqlite_all_chapters(client)
        total, books = _sqlite_corpus_stats(client)

    st.caption(f"{books} books · {total} chapters indexed")

    subjects = sorted({c["subject"] for c in all_chapters})

    tab_search, tab_browse = st.tabs(["Search", "Browse"])

    with tab_search:
        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
        with col1:
            query = st.text_input("Search the corpus", placeholder="e.g. federalism, monsoon, fundamental rights")
        with col2:
            subject = st.selectbox("Subject", ["All"] + subjects)
        with col3:
            classes = sorted({c["class"] for c in all_chapters if subject == "All" or c["subject"] == subject})
            klass = st.selectbox("Class", ["All"] + [str(c) for c in classes])
        with col4:
            books_opt = sorted({
                c["book"] for c in all_chapters
                if (subject == "All" or c["subject"] == subject)
                and (klass == "All" or str(c["class"]) == klass)
            })
            book = st.selectbox("Book", ["All"] + books_opt)

        if query:
            try:
                if backend == "supabase":
                    results = _sb_search(client, query, subject, klass, book)
                else:
                    results = _sqlite_search(client, query, subject, klass, book)
            except Exception as e:
                st.error(f"Search query error: {e}")
                results = []
            st.write(f"{len(results)} result(s)")
            for row in results:
                with st.expander(f"{row['book']} (Class {row['class']}) — Ch. {row['chapter_no']}: {row['chapter_title'] or '(untitled)'}"):
                    st.markdown(row["snippet"], unsafe_allow_html=False)
                    if st.button("Open full chapter", key=f"open_{row['id']}"):
                        st.session_state["open_chapter_id"] = row["id"]

    with tab_browse:
        for subj in subjects:
            with st.expander(subj):
                subj_chapters = [c for c in all_chapters if c["subject"] == subj]
                classes = sorted({c["class"] for c in subj_chapters})
                for klass in classes:
                    st.markdown(f"**Class {klass}**")
                    class_chapters = [c for c in subj_chapters if c["class"] == klass]
                    books_list = sorted({c["book"] for c in class_chapters})
                    for b in books_list:
                        chapters = sorted(
                            (c for c in class_chapters if c["book"] == b),
                            key=lambda c: c["chapter_no"],
                        )
                        st.write(f"— {b} ({len(chapters)} chapters)")
                        cols = st.columns(4)
                        for i, ch in enumerate(chapters):
                            label = f"Ch.{ch['chapter_no']}: {(ch['chapter_title'] or '')[:30]}"
                            if cols[i % 4].button(label, key=f"browse_{ch['id']}"):
                                st.session_state["open_chapter_id"] = ch["id"]

    if "open_chapter_id" in st.session_state:
        if backend == "supabase":
            row = _sb_get_chapter(client, st.session_state["open_chapter_id"])
        else:
            row = _sqlite_get_chapter(client, st.session_state["open_chapter_id"])
        if row:
            st.divider()
            render_chapter(backend, client, row)


if __name__ == "__main__":
    main()
