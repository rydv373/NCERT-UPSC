# Deployment — Supabase + Streamlit Community Cloud

**Status: Supabase complete; Streamlit hosting is the next step.** Data is live in Supabase
(248 chapters migrated), and the app has passed the local test suite. The remaining work is to
connect this GitHub repository to Streamlit Community Cloud and add the two public read-only
Supabase secrets in the Cloud settings.

## Hosting choice

The current app (`app/app.py`) is a **Streamlit** app. Streamlit Community Cloud is the matching
hosting platform, and Supabase supplies the hosted database, full-text search, and PDF storage.
The deployed app uses Supabase when its credentials are configured; SQLite and local files remain
available as a development fallback.

Streamlit Community Cloud is free for this deployment and connects directly to the GitHub `main`
branch. No local PDFs, extracted text, or SQLite database need to be committed.

---

## Deployment checklist

✅ **Done.** Repo is at [github.com/rydv373/NCERT-UPSC](https://github.com/rydv373/NCERT-UPSC),
with the deployment code on `main`.

### 1. Supabase setup

✅ **Done.**
1. Project created at [supabase.com](https://supabase.com)
2. Schema applied (`chapters` table + full-text search + RLS policy)
3. Storage bucket `pdfs` created and set Public
4. Credentials noted:
   - Project URL: `https://poghmlsnbzqeaufzebwp.supabase.co`
   - Anon key: In `.streamlit/secrets.toml`
   - Service role key: Used for migration script only (never committed)

### 2. Data migration

✅ **Done.** Ran `scripts/05_migrate_to_supabase.py`:
- All 248 chapters uploaded to `pdfs` Storage bucket
- All 248 chapters upserted into `chapters` table (metadata + extracted text)
### 3. Local smoke test

Before deploying, verify the app with the same public credentials that will be entered in Cloud:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit .streamlit/secrets.toml with SUPABASE_URL and SUPABASE_ANON_KEY
source venv/bin/activate
streamlit run app/app.py
```

Open `http://localhost:8501`, run a search, open a chapter, and confirm the PDF link works.

### 4. Deploy to Streamlit Community Cloud

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with the GitHub account that can
   access `rydv373/NCERT-UPSC`.
2. Select **Create app** / **New app**.
3. Choose repository `rydv373/NCERT-UPSC`, branch `main`, and main file path `app/app.py`.
4. Open **Advanced settings**, then paste the contents of `.streamlit/secrets.toml` into the
   **Secrets** field. Use only `SUPABASE_URL` and `SUPABASE_ANON_KEY`; never add the
   `SUPABASE_SERVICE_KEY`.
5. Select **Deploy** and wait for the app health check to finish.
6. Open the generated `streamlit.app` URL and test Search, Browse, chapter text, and the PDF link.

Future pushes to `main` automatically redeploy the app. The Streamlit Cloud logs are available
under **Manage app** if startup or Supabase connection errors occur.
6. Deploy. Every push to `main` auto-redeploys; PRs get their own preview URL for free.

The Python pipeline (`scripts/01`–`04` + the new `05_migrate_to_supabase.py`) stays exactly as it
is either way — it's the offline data-preparation step that feeds Supabase, not part of the
deployed app itself.

---

## Status

**Remaining action:** deploy `app/app.py` using section 4, then record the generated public URL
below.

Hosted URL: _pending Streamlit Community Cloud deployment_
