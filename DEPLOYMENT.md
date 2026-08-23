# Deployment plan — Supabase + hosting from GitHub

Status: **planning only, not yet implemented.** This document lays out two concrete paths to take
this project from "runs locally" to "hosted, backed by Supabase, deployed from GitHub." Pick one
before starting — they're different enough in effort that mixing them isn't worth it.

## Why this needs a real decision first

The current app (`app/app.py`) is a **Streamlit** app: a long-running Python server that keeps a
WebSocket connection open per user session and reads `data/search_index.sqlite` + `data/raw_pdfs/`
straight off local disk.

**Vercel does not run apps like that.** Vercel hosts static sites and short-lived serverless
functions (each request spins up fresh, no persistent process, no local disk to keep a SQLite
file or PDFs on). Streamlit has no supported Vercel deployment path. So "host on Vercel" and "keep
the Streamlit UI" are mutually exclusive — one of them has to give.

**Supabase fits either way.** It's a hosted Postgres database (with full-text search built in) plus
S3-compatible object storage, and both paths below use it the same way: as the replacement for
`search_index.sqlite` (→ Postgres full-text search) and `data/raw_pdfs/` (→ Supabase Storage).

| | Path A — keep Streamlit | Path B — rewrite for Vercel |
|---|---|---|
| Effort | Low — swap the DB, redeploy | High — new frontend from scratch |
| UI | Unchanged | Rebuilt (e.g. Next.js) |
| Host | Streamlit Community Cloud | Vercel |
| Recommended if | You just want this hosted, minimal rework | You specifically need it on Vercel (existing infra, team convention, custom domain setup already there, etc.) |

**Recommendation: Path A**, unless there's a specific reason it has to be Vercel. It reuses
everything already built and tested.

---

## Shared step 0: push to GitHub

Both paths assume the repo is on GitHub first (deploy platforms both connect by importing a GitHub
repo and auto-redeploying on push to `main`).

```bash
# from the project root, once you have an empty GitHub repo created:
git remote add origin <your-repo-url>
git push -u origin main
```

## Shared step 1: set up Supabase

1. Create a project at [supabase.com](https://supabase.com) (free tier is plenty for ~250 rows of
   metadata + text and ~250 PDFs).
2. In the SQL editor (Project → SQL Editor → New query), paste and run **[`supabase/schema.sql`](supabase/schema.sql)**
   — creates the `chapters` table with a generated `tsvector` column + GIN index (replaces SQLite
   FTS5 + `bm25()`: queries become
   `... where search_vector @@ plainto_tsquery('english', $1) order by ts_rank(search_vector, plainto_tsquery('english', $1)) desc`),
   plus a unique index on `(book_code, chapter_no)` so the migration script can safely re-run, and
   a Row Level Security policy allowing anonymous `SELECT` only (read-only public reference data —
   no write policy is granted; the migration script writes via the `service_role` key, which
   bypasses RLS).
3. In Storage (sidebar), create a bucket named exactly `pdfs`, set it **Public**.
4. In Project Settings → API, note the **Project URL**, the **`anon` public** key, and the
   **`service_role`** key (the last one is a secret — only ever used locally by the migration
   script below, never shipped to a browser or committed to git).

## Shared step 2: run the migration script

**[`scripts/05_migrate_to_supabase.py`](scripts/05_migrate_to_supabase.py)** is already written and
re-runnable (upserts on `(book_code, chapter_no)`, so running it again after the local corpus
changes just updates what changed):

```bash
export SUPABASE_URL=https://xxxxx.supabase.co
export SUPABASE_SERVICE_KEY=eyJ...        # service_role key, not anon
cd scripts && python3 05_migrate_to_supabase.py
```

It reads `data/catalog.json` + each `data/text/**/*.txt`, uploads each `data/raw_pdfs/**/*.pdf`
into the `pdfs` Storage bucket (mirroring the existing `<Subject>/<Class>/<Book>/ch_XX.pdf` path),
and upserts one row per chapter into `chapters` (metadata + the chapter body text). This is the
bridge between the local pipeline (scrape → download → extract, unchanged) and the hosted app —
run it once after `03_extract_text.py`, and re-run it whenever the local corpus changes.

---

## Path A — keep Streamlit, deploy to Streamlit Community Cloud

**Done — `app/app.py` is already rewritten for this.** It talks to Supabase exclusively (no more
`sqlite3`/local files): search goes through the `search_chapters` RPC (ranked results + `**`-marked
snippets via `ts_headline`), Browse and filters use plain `sb.table("chapters")` queries, and
"Open original PDF" is a `st.link_button` to the Storage bucket's public URL
(`sb.storage.from_("pdfs").get_public_url(row["pdf_storage_path"])`) instead of reading local bytes.

To run it:
1. Copy `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml`, fill in your project's
   **Project URL** and **`anon` public** key (not `service_role` — that key is for the migration
   script only). `secrets.toml` is gitignored.
2. `streamlit run app/app.py` — it now reads/writes nothing local, purely Supabase.
3. Push to GitHub, then on [share.streamlit.io](https://share.streamlit.io): "New app" → pick this
   repo/branch → set `app/app.py` as the entrypoint → paste the same two secrets into the app's
   Secrets panel (in the dashboard, not the repo) → Deploy.
4. Every push to `main` auto-redeploys.

## Path B — rewrite for Vercel (Next.js + Supabase)

1. Scaffold a new `web/` directory: `npx create-next-app@latest web` (or a lighter Vite+React app
   if a full framework is overkill for three pages).
2. Add `@supabase/supabase-js`, initialize a client using `NEXT_PUBLIC_SUPABASE_URL` /
   `NEXT_PUBLIC_SUPABASE_ANON_KEY` (safe to expose client-side — that's what the `anon` key + RLS
   read-only policy from step 1.4 is for).
3. Build three pages/routes, each a thin wrapper over a Supabase query, mirroring the current
   Streamlit tabs:
   - **Search** — `.textSearch("search_vector", query)`, ranked, with subject/class/book filters
     as additional `.eq()` calls.
   - **Browse** — grouped `.select()` queries (distinct subject → class → book → chapters), or a
     Postgres view for the tree structure.
   - **Chapter reader** — fetch one row by id, render `body`, link to the Storage public URL for
     the PDF.
4. `git push` this to GitHub (same repo, `web/` subdirectory, or a separate repo — either works).
5. Import the repo into [vercel.com](https://vercel.com), set the project root to `web/` if it's a
   subdirectory, add the two `NEXT_PUBLIC_SUPABASE_*` env vars in Vercel's project settings.
6. Deploy. Every push to `main` auto-redeploys; PRs get their own preview URL for free.

The Python pipeline (`scripts/01`–`04` + the new `05_migrate_to_supabase.py`) stays exactly as it
is either way — it's the offline data-preparation step that feeds Supabase, not part of the
deployed app itself.

---

## Status

**Path A is implemented and ready to run** once a Supabase project exists: `supabase/schema.sql`,
`scripts/05_migrate_to_supabase.py`, and the Supabase-backed `app/app.py` are all written. What's
still needed is a Supabase project (account access only you have) and then running the migration
+ deploying to Streamlit Community Cloud per the steps above.

**Path B is plan-only** — nothing under `web/` exists yet. It additionally needs a Vercel account
and a decision on repo layout (monorepo `web/` subdirectory vs. separate repo) before it can start.
