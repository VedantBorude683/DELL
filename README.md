# Alderwood University Assistant

A local university assistant that answers from:

- PostgreSQL 16 + pgvector
- A read-only PostgreSQL role for generated SQL
- Four handbook PDFs, ingested into `document_chunks`
- Local `sentence-transformers` embeddings
- A real Gemini API call for routing, SQL generation, synthesis, and claim checking

It is not a dashboard. The UI is a chat panel plus an execution trace.

## Run locally without Docker

1. Install native PostgreSQL and pgvector, then start PostgreSQL.
2. Create the database and apply the schema/seed:
   ```bash
   createdb alderwood_rag
   psql -d alderwood_rag -f db/schema.sql
   psql -d alderwood_rag -f db/seed.sql
   ```
3. Copy the environment template:
   ```bash
   cp .env.example .env
   ```
4. Set `GEMINI_API_KEY` and available model names in `.env`. The key must have API quota.
5. Create the Python environment and ingest PDFs:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   set -a && source .env && set +a
   export DATABASE_URL="postgresql+psycopg://alderwood_admin:alderwood_dev_password@localhost:5432/alderwood_rag"
   .venv/bin/python scripts/build_phase2.py
   ```
6. Start the API and UI:
   ```bash
   export READONLY_DATABASE_URL="postgresql+psycopg://alderwood_readonly:alderwood_ro_password@localhost:5432/alderwood_rag"
   .venv/bin/uvicorn src.api.main:app --host 0.0.0.0 --port 8000
   .venv/bin/streamlit run app_streamlit.py --server.address 0.0.0.0 --server.port 8501
   ```
7. Open:
   - Chat UI: http://localhost:8501
   - API health: http://localhost:8000/health

Docker Compose remains optional:

```bash
docker compose up --build
```

## Deploy the whole app with Streamlit Cloud

Streamlit can host the Streamlit UI and run the FastAPI-independent Python assistant directly.
PostgreSQL and pgvector must be hosted by a managed database provider.

1. Push this repository to GitHub.
2. Create a managed PostgreSQL database that supports the `vector` extension.
3. Create one admin connection URL and one read-only user connection URL.
4. Initialize the remote database:
   ```bash
   export DATABASE_URL="postgresql+psycopg://ADMIN_USER:PASSWORD@HOST:5432/DATABASE"
   export READONLY_DATABASE_URL="postgresql+psycopg://READONLY_USER:PASSWORD@HOST:5432/DATABASE"
   psql "$DATABASE_URL" -f db/schema.sql
   psql "$DATABASE_URL" -f db/seed.sql
   python scripts/build_phase2.py
   ```
5. In Streamlit Community Cloud, create a new app from the GitHub repository.
6. Set the main file to `app_streamlit.py`.
7. Add these values to **Advanced settings -> Secrets**:
   ```toml
   GEMINI_API_KEY = "replace-with-your-key"
   FAST_MODEL = "gemini-3.5-flash-lite"
   STRONG_MODEL = "gemini-3.5-flash-lite"
   DATABASE_URL = "postgresql+psycopg://ADMIN_USER:PASSWORD@HOST:5432/DATABASE"
   READONLY_DATABASE_URL = "postgresql+psycopg://READONLY_USER:PASSWORD@HOST:5432/DATABASE"
   ```
8. Deploy. Do not add `API_BASE_URL`; without it, the app runs the assistant directly in Streamlit.

The Compose startup runs seed data, waits for Postgres, downloads/loads the local embedding model, and ingests the four configured PDFs into pgvector.

## Real-data boundaries

- There are no simulated metrics, offline answer fallbacks, or deterministic fake models.
- Missing API keys, unreadable PDFs, unavailable embeddings, and unavailable Postgres cause explicit errors.
- Generated SQL must be one read-only `SELECT`, is executed through `alderwood_readonly`, and is retried up to three times.
- Hybrid questions execute SQL first; if SQL returns no grant rows, document search is skipped.
- Document citations identify handbook document, version, and page.
- If the database deadline and handbook text differ, the answer reports the conflict rather than choosing silently.

## 10 test questions

1. What is Maya Lin's cumulative GPA?
2. Which open grants may Maya Lin qualify for based on the database?
3. What is the submission window for the Turing Undergraduate Research Fellowship?
4. What deadline does the database list for GR-CS-01, and what date appears in the 2026 handbook?
5. What courses is Maya Lin taking in Fall 2026?
6. How much does Maya Lin still owe?
7. Can internal Alderwood research stipends be stacked?
8. What lab or safety clearance is required for the Maxwell Hardware Prototyping Grant?
9. Was the Summer 2026 Heritage Innovation Grant expired by November 23, 2026?
10. What is the weather in London today?

Question 10 should be classified `out_of_scope` and declined.

## Live evaluation

With the API running, generate an actual 10-query report:

```bash
.venv/bin/python scripts/run_live_eval.py
```

The report is written to `eval/live_10_report.json`. It records, for every question:

- expected and actual route
- SQL text and row count
- PDF citations and passage count
- answer text
- HTTP status
- measured end-to-end latency

This is a live LLM + Postgres + pgvector evaluation, not a hardcoded or simulated score.
