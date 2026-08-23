-- NCERT-for-UPSC Supabase schema.
-- Run this once in the Supabase SQL editor (Project -> SQL Editor -> New query) before running
-- scripts/05_migrate_to_supabase.py. Safe to re-run: drops and recreates the table.

drop table if exists chapters;

create table chapters (
    id bigint generated always as identity primary key,
    subject text not null,
    class int not null,
    book text not null,
    book_code text not null,
    chapter_no int not null,
    chapter_title text,
    source text,
    pdf_storage_path text,   -- path inside the "pdfs" Storage bucket
    word_count int,
    status text not null,
    body text not null default '',
    search_vector tsvector generated always as (
        setweight(to_tsvector('english', coalesce(chapter_title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(body, '')), 'B')
    ) stored
);

create index chapters_search_idx on chapters using gin (search_vector);
create index chapters_subject_class_book_idx on chapters (subject, class, book);
-- lets the migration script upsert (re-runnable) instead of inserting duplicate rows on re-run
create unique index chapters_book_code_chapter_no_idx on chapters (book_code, chapter_no);

alter table chapters enable row level security;

-- Read-only public reference data (NCERT chapter text/metadata) — anonymous SELECT is fine,
-- no user data involved. Writes only ever happen from the migration script using the
-- service_role key, which bypasses RLS, so no insert/update/delete policy is needed here.
create policy "Public read access"
    on chapters for select
    to anon
    using (true);

-- Ranked full-text search with highlighted snippets, replacing SQLite's bm25()/snippet().
-- Called from the app as sb.rpc("search_chapters", {...}).
create or replace function search_chapters(
    search_query text,
    p_subject text default null,
    p_class int default null,
    p_book text default null,
    p_limit int default 50
)
returns table (
    id bigint,
    subject text,
    class int,
    book text,
    chapter_no int,
    chapter_title text,
    pdf_storage_path text,
    snippet text,
    rank real
)
language sql stable
as $$
    select
        c.id, c.subject, c.class, c.book, c.chapter_no, c.chapter_title, c.pdf_storage_path,
        ts_headline(
            'english', c.body, websearch_to_tsquery('english', search_query),
            'MaxFragments=1, MaxWords=30, MinWords=15, StartSel=**, StopSel=**'
        ) as snippet,
        ts_rank(c.search_vector, websearch_to_tsquery('english', search_query)) as rank
    from chapters c
    where c.search_vector @@ websearch_to_tsquery('english', search_query)
      and (p_subject is null or c.subject = p_subject)
      and (p_class is null or c.class = p_class)
      and (p_book is null or c.book = p_book)
    order by rank desc
    limit p_limit
$$;

grant execute on function search_chapters to anon;
