# Legal Agent

FastAPI backend that ingests Persian legal PDFs, structures them with an LLM, and runs a RAG-based comparison pipeline to find relations (similar / conflicting) between articles of two bills.

## Services

- **postgres** — PostgreSQL 17 database (host port `1700`).
- **backend** — FastAPI app on host port `8080`.

## Run with Docker

```bash
cp .env.example .env   # then fill in real values (API keys, secrets)
docker compose up --build -d
```

The API is then available at `http://localhost:8080` (Swagger UI at `http://localhost:8080/docs`).

Volumes:
- `./storage` → `/app/storage` — uploaded documents and extracted files (`docs/<id>/`).
- `./backend/storage` → `/app/analysis_storage` — analysis pipeline data (`context_A.jsonl`, `context_B.jsonl`, FAISS indexes).
- `./backend` → `/app` — live code reload.

## End-to-end flow

1. **Auth** — `POST /api/v1/auth/register` (or `/login`, `/token`) to get a JWT.
2. **Upload** — `POST /api/v1/document/` (multipart PDF). Text is extracted, and structure extraction runs in the background.
3. **Structure** — `GET /api/v1/document/{id}/structure` returns the structured JSONL records.
4. **Analyze** — `POST /api/v1/analyze/workflow/run` with `document_a` / `document_b` record lists (or pre-loaded `context_A.jsonl` / `context_B.jsonl`) runs:
   - load contexts → build/load FAISS vector stores
   - hybrid retrieval (semantic + BM25 + reference matching)
   - LLM batch analysis of candidate pairs
   - results saved to `backend/analysis_results.jsonl`
5. **Resume / status** — `GET /api/v1/analyze/workflow/status?run_id=...` and `POST /api/v1/analyze/workflow/resume?run_id=...`.

## Configuration

All settings are read from the root `.env` (see `.env.example`):

- `DATABASE_URL` — SQLAlchemy database URL (host `postgres` inside the compose network).
- `AVALAI_API_KEY` / `AVALAI_BASE_URL` / `AVALAI_MODEL` / `STRUCTURE_MODEL` — LLM provider used by both structuring and analysis.
- `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` — JWT auth.

Optional toggles: `LLM_REASONING_EFFORT=1` and `LLM_REASONING_EFFORT_LEVEL=high` enable reasoning-effort for the analysis model.
