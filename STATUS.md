# STATUS — Legal Document Comparison MVP

> Snapshot of the project as actually implemented and tested at the end of this
> task. Everything below reflects the real code, not intentions.

## Project Overview

The project compares **two legal documents** ("Document A" vs "Document B") that
arrive as **pre-segmented independent legal records** (JSONL), and detects the
relationship between every pair of records across the two documents:

- `مشابه` — the two records express substantially the same legal rule/provision.
- `متناقض` — the two records' actual rulings genuinely conflict.
- `بی‌ارتباط` — no meaningful legal relation (topic overlap alone is not similarity;
  topical relation alone is not contradiction).

For every pair the system also produces `relation_type` (kind of legal
relation), `relation_basis` (what the relation is legally grounded in),
`relation_mode` (how the relation manifests), a Persian `explanation`, a
`confidence` between 0.0 and 1.0, and — critically — the **exact
source/address of both records taken verbatim from their metadata** (the LLM
never invents addresses).

The pipeline is a two-stage design: a **HYBRID retrieval (FAISS semantic +
BM25 lexical + cheap reference matching), BIDIRECTIONAL (A→B and B→A)**
generates candidate pairs, and a **GLM-5.3-Flash LLM is the sole classifier**
that decides the final relation via structured output. Everything is exposed
through a **FastAPI server**.

## Responsibility Map (most important section)

```text
app.py                   = FastAPI server ONLY. Defines endpoints, parses the
                           request body, calls analyses_service, returns the
                           response. No analysis logic of any kind.
analyses_service.py      = ALL analysis logic: hybrid retriever (FAISS + BM25 +
                           reference matching), bidirectional candidate
                           generation, LangGraph workflow (defined AND invoked
                           here), LLM prompt + calls, structured output, result
                           shaping.
vector_store_service.py   = Vector store management ONLY: reading contexts,
                           records -> Documents, embeddings, building/saving/
                           loading FAISS A + B, chunks.jsonl, fingerprints.
```

Layering:

```text
FastAPI (app.py)
    ↓
analyses_service.py
    ↓
Hybrid Retrieval (FAISS + BM25) + LangGraph workflow + LLM analysis
    ↓
final results
```

## Current Architecture

```text
            context_A.jsonl                    context_B.jsonl
                   │                                 │
            records → Documents              records → Documents
            (1 record = 1 doc,                (1 record = 1 doc,
             NO chunking/splitting)            NO chunking/splitting)
                   │                                 │
              Embedding                        Embedding
         (parsbert-fa-2.0)                (parsbert-fa-2.0)
                   │                                 │
               FAISS A                             FAISS B
                   │                                 │
                   ▼                                 ▼
     ┌─────────────────────────────────────────────────────┐
     │  analyses_service.py — HYBRID BIDIRECTIONAL retrieval│
     │                                                     │
     │   A records ──┬── FAISS B (semantic, per record)    │
     │               ├── BM25 over B (lexical, per record) │
     │               └── reference match (ماده ۳۰۵ → record) │
     │                                                     │
     │   B records ──┬── FAISS A (semantic, per record)    │
     │               ├── BM25 over A (lexical, per record) │
     │               └── reference match                    │
     │                                                     │
     │   UNION → DEDUP by (min_id, max_id) → Candidate Pool│
     │        ↓                                            │
     │   LLM glm-5.3-flash (batched, structured out)       │
     │        ↓                                            │
     │   مشابه / متناقض / بی‌ارتباط + type + basis + mode  │
     │   + Persian explanation + confidence                │
     └─────────────────────────────────────────────────────┘
                   │
        join verbatim metadata by id
                   │
                   ▼
        analysis_results.jsonl + API response
```

## Directory Structure

```text
legal_similarity/
├── app.py                      # FastAPI server ONLY (thin API layer)
├── STATUS.md                   # this file
├── README.md                   # repo title only (added manually by user)
├── .gitignore                  # standard python gitignore + models/ (user)
├── .env.example                # documents env knobs; only LEGAL_SIM_REBUILD is actually read today
├── requirements.txt            # dependency list (incl. rank_bm25)
├── test_smoke.py               # offline checks (no network needed)
├── analysis_results.jsonl      # final output (generated at runtime)
├── models/                     # local embedding model (gitignored)
│   └── sentence-transformer-parsbert-fa-2.0/
├── services/
│   ├── __init__.py
│   ├── vector_store_service.py # context → Documents → embeddings → FAISS (+ chunks.jsonl, fingerprints)
│   └── analyses_service.py     # ALL analysis logic + Hybrid RAG + LangGraph + LLM
└── sources/
    ├── context_A.jsonl         # input document A
    ├── context_B.jsonl         # input document B
    └── temp/                   # generated at runtime (safe to delete; auto-rebuilt)
        ├── document_A/
        │   ├── faiss/          # index.faiss + index.pkl + fingerprint.txt
        │   └── chunks.jsonl    # one indexed legal unit per line (NOT split output)
        └── document_B/
            ├── faiss/
            └── chunks.jsonl
```

## Input Format

`sources/context_A.jsonl` and `sources/context_B.jsonl`: one JSON object per
line, each line an **independent legal unit** (e.g. one اصل / ماده / تبصره / بند):

```json
{
  "id": 1,
  "law_seq": 0,
  "category": null,
  "law": null,
  "book": "اصول قانون اساسي",
  "chapter": null,
  "subchapter": null,
  "type": "اصل",
  "number_raw": "اول",
  "number": 1,
  "parent_number": null,
  "text": "حكومت ايران جمهوري اسلامي است...",
  "breadcrumb": "اصول قانون اساسي"
}
```

- `text` → `Document.page_content`; every other field → `Document.metadata`
  (all 12 metadata fields preserved end-to-end).
- an extra `_record_index` (0-based position in the file) is injected into
  metadata for traceability.
- **Records can also be passed inline in the API body** (`document_a` /
  `document_b`); they are written to the context files first.
- `id` must be present and unique **within each context file** (ids may repeat
  across A and B — pairs are identified by the combination).

**No re-chunking and no sentence splitting ever happens.**

## Vector Store

- **Embedding model**: `EMBEDDING_MODEL = "models/sentence-transformer-parsbert-fa-2.0"`
  via `HuggingFaceEmbeddings` (768-dim; local copy in `models/` so the constant
  resolves offline). The same embeddings instance is used for building AND
  searching both indexes.
- **Two independent FAISS indexes**:
  - FAISS A: `sources/temp/document_A/faiss/` — ONLY A records.
  - FAISS B: `sources/temp/document_B/faiss/` — ONLY B records.
- **Persistence policy**: if `index.faiss` exists AND `fingerprint.txt`
  (record count + ids) matches the current context file → load from disk; if
  the context changed or `rebuild=True` → rebuild. Directories auto-created.
- **`chunks.jsonl`**: one original record per line (`{"text": ..., "metadata": {...}}`)
  — the exact units embedded. NOT text-splitting output.
- `vector_store_service.py` contains no LLM / analysis logic.

## Hybrid Retrieval (FAISS + BM25 + reference matching, bidirectional)

All retrieval lives in `services/analyses_service.py` (`retrieve_candidates`).

- **FAISS semantic search** — per record: `similarity_search_with_score(
  record["text"], k=TOP_K)` against the OTHER document's index. Query is
  always the record's own text, never a global prompt embedding.
- **BM25 lexical search** — a minimal `BM25Index` class over
  `rank_bm25.BM25Okapi` (same library LangChain's BM25Retriever wraps), built
  per run from the target document's records. Tokenizer = simple regex
  (Persian/Arabic + latin word tokens, lowercased; no stemmer — the goal is
  lexical recall for exact legal phrases, statute numbers, law names, shared
  references). BM25 catches candidates FAISS misses (exact terms, numbers) and
  vice versa.
  - *Known small-corpus quirk handled*: with tiny corpora BM25 idf can clip all
    scores to ~0; in that case the relative ranking is kept with a tiny
    positive score so lexical candidates are never silently lost.
- **Reference/metadata matching** (cheap, heuristic, no parser/rule engine):
  if a record's text mentions «ماده ۳۰۵» / «تبصره ۲» etc., the record with
  that `number` (and matching `type` for ماده references) in the other document
  is added directly as a candidate. Persian digits (۰-۹) are converted.
- **Bidirectional**: both directions run — A→B (each A record queries B) and
  B→A (each B record queries A) — to reduce misses from asymmetric retrieval.
- **Union + dedup**: results from both directions and all three methods merge
  into one candidate pool keyed by the **canonical pair key (min_id, max_id)**
  — so (A1,B10) found by FAISS A→B, BM25 A→B, FAISS B→A and reference matching
  collapses into ONE pair. The best (lowest) retrieval score is kept, and the
  `retrieval_methods` list records which methods found the pair
  (e.g. `["faiss", "bm25", "reference"]`).
- **`TOP_K = 20`** candidates per record per retriever (recall-oriented; NOT
  the number of real relations — most candidates end up بی‌ارتباط).
- Retrieval scores (FAISS L2 distance; lower = closer) are context only; they
  never dictate the verdict.

## LLM Analysis

- **Chat model** (`get_chat_model()`): `ChatOpenAI(base_url="https://api.avalai.ir/v1",
  api_key="aa-…" (hardcoded, per spec), model="glm-5.3-flash")`.
- **Role**: the LLM is the **final classifier**. It receives candidate pairs
  where BOTH records are rendered with text AND full metadata (id, type,
  parent_number, book/chapter/subchapter, breadcrumb, law, number, …), so it
  can reason about legal structure (ماده vs تبصره vs بند, parent/child,
  references), not isolated sentences.
- **System prompt** (`ANALYSIS_SYSTEM_PROMPT`, Persian) explicitly instructs:
  semantic/legal analysis, not lexical matching; surface similarity ≠ legal
  equivalence; obligation/permission/prohibition/recommendation distinctions;
  conditions, restrictions, exceptions («در صورتی که»، «مگر آنکه»);
  negation vs affirmation; scope of application (عام/خاص, مطلق/مقید);
  parent/child structure via `parent_number`/`type`; internal/external
  references; explicit vs implicit relations; relation ≠ relation_type ≠
  relation_mode (independent dimensions, e.g. تعارض+ضمنی is valid);
  avoid overclaiming when evidence is insufficient; ALL analytical outputs in
  Persian; never fabricate ids/metadata/addresses; exactly one result per pair
  in pair order.
- **Structured output**: Pydantic via `with_structured_output(BatchAnalysisResult)`:
  `AnalysisResult(source_id, target_id, relation: Literal["مشابه","متناقض","بی‌ارتباط"],
  relation_type, relation_basis, relation_mode, explanation, confidence∈[0,1])`.
  No free-text parsing. Results are matched back to pairs **by
  (source_id, target_id)**, not by response order; unknown ids are dropped; a
  failed batch is skipped without killing the run.
- **Batching**: `LLM_BATCH_SIZE = 10` pairs per request (context-overflow guard
  only, sequential).

### Relation taxonomy (single source of truth: `analyses_service.py`)

- **relation**: `مشابه` | `متناقض` | `بی‌ارتباط`
- **relation_type**: `تکرار مقرراتی` | `اقتباس` | `تکمیل` | `تخصیص` | `تعارض` |
  `نسخ صریح` | `نسخ ضمنی` | `ابهام تفسیری` | `ناسازگاری اصلاحی` | `هم‌ارزی حکمی` | `سایر`
- **relation_basis**: `حکم` | `الزام` | `اختیار` | `ممنوعیت` | `توصیه` | `شرط` | `قید` |
  `استثناء` | `نفی` | `اثبات` | `دامنه شمول` | `محدودیت زمانی` | `محدودیت مکانی` |
  `موضوعی` | `مفهومی` | `ارجاع داخلی` | `ارجاع بیرونی` | `اصلاح یا الحاق` | `ترکیبی`
- **relation_mode**: `صریح` | `ضمنی` | `ارجاعی` | `ترکیبی`
  (mode is independent of type — e.g. «تعارض ضمنی» and «تکمیل ارجاعی» are valid).

## LangGraph Workflow

Defined **and** invoked inside `services/analyses_service.py`
(`build_analysis_graph()` / `run_analysis()`). `app.py` never touches it.

```text
START
  → load_context          # read context_A/B.jsonl → records_a/records_b
  → load_vector_stores    # build-or-load FAISS A and B (shared embeddings)
  → retrieve_candidates   # HYBRID + BIDIRECTIONAL → union → dedup
  → analyze_with_llm      # batched LLM calls → validated AnalysisResult list
  → build_results         # join verbatim metadata by id → save analysis_results.jsonl
  → END
```

## API

`app.py` exposes FastAPI (docs at `http://127.0.0.1:8000/docs`):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | liveness probe → `{"status": "ok"}` |
| `POST` | `/analyze` | run the bidirectional comparison, return relations |

`POST /analyze` body (all fields optional):

```json
{
  "document_a": [ { ...record... }, ... ],
  "document_b": [ { ...record... }, ... ],
  "rebuild": false
}
```

- Inline records are written to the context files, then the analysis runs.
- If omitted, the current context files are used.
- `rebuild: true` forces a FAISS rebuild (same as `LEGAL_SIM_REBUILD=1`).
- Errors: `400` invalid records (missing id/text), `404` missing context files.
- The endpoint contains no analysis logic — it only calls
  `analyses_service.analyze_documents()`.

Response: `{"count": N, "relations": [ { ...one relation object per pair... } ]}`,
each relation object shaped like:

```json
{
  "source_id": 1, "target_id": 10,
  "source_metadata": { "id": 1, "book": "...", "type": "ماده", "number": 305, "breadcrumb": "...", "...": "..." },
  "target_metadata": { "...": "..." },
  "source_text": "...", "target_text": "...",
  "relation": "متناقض",
  "relation_type": "تعارض",
  "relation_basis": "محدودیت زمانی",
  "relation_mode": "ضمنی",
  "explanation": "هر دو رکورد ماده ۳۰۵ ...",
  "confidence": 0.88,
  "retrieval_methods": ["faiss", "bm25"]
}
```

Metadata is joined verbatim from the original records by id — never from LLM
text. `retrieval_methods` documents how the pair entered the candidate pool.

## Data Flow

1. `POST /analyze` (or `run_analysis()` directly): context files read; inline
   body records written to the context files first.
2. `load_context`: both JSONL files → record dicts.
3. `load_vector_stores`: records → Documents (metadata preserved) → FAISS →
   persisted (skipped when fingerprint matches) → `chunks.jsonl` written.
4. `retrieve_candidates` (hybrid, bidirectional): for each record on EACH side,
   FAISS semantic + BM25 lexical + reference matching against the OTHER
   document; union; canonical dedup by (min_id, max_id); best score + method
   list kept per pair.
5. `analyze_with_llm`: pairs → GLM-5.3-Flash in batches of 10, structured
   output, Pydantic-validated, matched by ids.
6. `build_results`: verbatim metadata join by id + retrieval methods → returned
   by the API and written to `analysis_results.jsonl` (one object per line).

## Configuration

| Name | Value | Where |
|---|---|---|
| `EMBEDDING_MODEL` | `models/sentence-transformer-parsbert-fa-2.0` | `services/vector_store_service.py` |
| `TOP_K` | `20` (candidates per record per retriever) | `services/analyses_service.py` |
| `CHAT_MODEL` | `ChatOpenAI(base_url="https://api.avalai.ir/v1", model="glm-5.3-flash")` | `services/analyses_service.py` |
| `CHAT_MODEL_API_KEY` | `aa-TXcGYa761kThZ5MWuVDzE3jX5HNJPEpsOe1tbjKITwuPrA95` (hardcoded, per spec) | `services/analyses_service.py` |
| `LLM_BATCH_SIZE` | `10` pairs per LLM request | `services/analyses_service.py` |
| context A / B paths | `sources/context_A.jsonl` / `context_B.jsonl` | `vector_store_service.DOCUMENT_SLOTS` |
| FAISS A / B paths | `sources/temp/document_A|B/faiss/` | `vector_store_service.DOCUMENT_SLOTS` |
| chunks A / B | `sources/temp/document_A|B/chunks.jsonl` | `vector_store_service` |
| results path | `analysis_results.jsonl` (project root) | `analyses_service.RESULTS_PATH` |
| `rebuild` | API field / `LEGAL_SIM_REBUILD=1` env var | `analyses_service.run_analysis` |

Environment variables (see `.env.example`): **`LEGAL_SIM_REBUILD` is the ONLY
env var the code currently reads** (`os.environ` is used once, in
`run_analysis`). The LLM base_url/model/api_key are hardcoded constants in
`analyses_service.py`, and `EMBEDDING_MODEL` is a hardcoded path constant in
`vector_store_service.py`. `.env.example` documents all these knobs with their
current values, mostly commented out as future wiring (python-dotenv is NOT a
dependency — `.env` files are not loaded automatically). `PYTHONIOENCODING=utf-8`
is an OS-level nicety for readable Persian logs on Windows consoles.

## Current Status

**Done and verified by real runs:**

- **Hybrid RAG implemented**: FAISS (semantic) + BM25 (lexical,
  `rank_bm25.BM25Okapi`) + cheap reference/metadata matching; union + canonical
  dedup. Verified end-to-end: 3×3 sample corpus → 9 unique pairs with methods
  `{'faiss': 9, 'bm25': 8, 'reference': 1}` (all three methods contributed).
- **Bidirectional retrieval implemented** (A→B AND B→A), merged and
  deduplicated via the canonical pair key.
- **Persian legal schema restored**: `relation` ∈ {مشابه, متناقض, بی‌ارتباط} as a
  Pydantic Literal; `relation_type` (11 values), `relation_basis` (19 values),
  `relation_mode` (4 values) with the required taxonomies.
- **Persian legal-analysis system prompt restored** covering: semantic vs
  lexical, obligation/permission/prohibition/recommendation, شرط/قید/استثناء,
  negation, scope, parent/child structure (`parent_number`, `type`:
  ماده/تبصره/بند/جزء), internal/external references, صریح vs ضمنی, independence
  of type/basis/mode, avoiding overclaims, all-Persian output.
- **Metadata-aware LLM input**: every pair renders BOTH records with text +
  full metadata (`text_block` / `build_pair_prompt`).
- **Metadata preservation verified** through indexing and retrieval (12
  fields, asserted by `test_smoke.py`).
- **TOP_K = 20**.
- **JSONL output** carries both records' metadata + texts + all relation
  fields + `retrieval_methods`.
- **End-to-end run with the real LLM (exit code 0)** on a 3×3 sample with
  designed relations — the LLM found: 2 متناقض (both designed deadline
  contradictions, correctly typed تعارض/ضمنی/محدودیت زمانی), 1 مشابه (a designed
  explicit cross-document reference «تبصره ۲ ماده ۷», correctly typed
  تکمیل/ارجاعی/ارجاع بیرونی and found via `reference` matching), 6 بی‌ارتباط
  with grounded Persian explanations; model correctly distinguished type vs
  mode vs basis in every result.
- **`python app.py` starts the FastAPI server only** (no analysis at startup);
  analysis runs only via `POST /analyze`.
- `python test_smoke.py` — all offline checks PASS (30+ assertions: metadata
  preservation, dedup, Persian schema validation, prompt coverage of the
  taxonomy, BM25 behavior incl. empty corpus, reference matching, hybrid
  merge with a FAISS stub, canonical dedup across directions/methods, JSONL
  round trip, TOP_K, thin-`app.py` guard, record validation).

**NOT done / open:**

- Real production data not yet loaded — context files currently hold the small
  sample corpus used for the verification run (user will replace with real
  records).
- See Known Limitations for deliberate MVP boundaries.

## Known Limitations

- **`/analyze` is synchronous and slow** — one request runs the whole pipeline;
  with TOP_K=20 the candidate pool (and thus LLM batches) grows quickly on
  large corpora. No background jobs yet.
- **No reranker** between hybrid retrieval and the LLM (a natural next step
  now that the pool is larger).
- **BM25 tokenizer is naive** (regex word tokens, no stemming/lemmatization,
  no Persian normalization like ی/ي or ک/ك unification). Works for exact
  phrases/numbers; a Persian normalizer would improve recall.
- **Reference matching is intentionally minimal**: only «(ماده|اصل|تبصره|بند) N»
  patterns against the other document's `number`/`type`. No breadcrumbs/law
  names parsing; cross-document name matching is left as future work.
- **`confidence` is the model's self-report**, not calibrated.
- **Sequential LLM batches** — no concurrency by design.
- **API key hardcoded** in `analyses_service.py` (explicitly requested for the
  MVP; move to env var before real deployment).
- One transient **LLM connection error** (`Connection error` to avalai.ir)
  occurred during testing; the batch-failure guard skipped the batch and a
  retry run succeeded — recommend a retry/backoff if this recurs in
  production. No automatic retry is implemented (kept simple).
- `models/` is gitignored (user's `.gitignore`); on a fresh clone the embedding
  model must be re-provided for `EMBEDDING_MODEL` to resolve offline.

## How to Run

Prerequisites: Python 3.10+ (developed on 3.14), dependencies:

```bash
python -m pip install -r requirements.txt
```

The embedding model must resolve at `models/sentence-transformer-parsbert-fa-2.0`
(local copy of `myrkur/sentence-transformer-parsbert-fa-2.0`; the folder is
gitignored, so ensure it exists — copy from the HF cache if missing).

Start the server:

```bash
python app.py        # FastAPI on http://127.0.0.1:8000, docs at /docs
```

Populate `sources/context_A.jsonl` / `context_B.jsonl` (or POST records
inline) and call:

```bash
curl -X POST http://127.0.0.1:8000/analyze
```

`rebuild: true` (or `LEGAL_SIM_REBUILD=1`) forces a FAISS rebuild. Internet
access to `https://api.avalai.ir/v1` is required for the LLM step. On Windows
consoles, set `PYTHONIOENCODING=utf-8` for readable Persian logs.

Offline checks: `python test_smoke.py` (no network/model download).

## Important Design Decisions

- **`app.py` = FastAPI server only** (asserted by a smoke test that scans for
  analysis-related symbols).
- **`analyses_service.py` = the whole analysis brain**: hybrid retrieval, BM25
  index, reference matching, canonical dedup, LangGraph workflow, LLM prompt
  and calls, structured output, result shaping, `analyze_documents()` entry
  point.
- **`vector_store_service.py` = vector stores only** (FAISS, chunks, fingerprints).
- **One JSON record = one legal unit = one Document.** No chunking/splitting.
- **Two independent FAISS indexes** (A never contains B and vice versa).
- **RAG = candidate generation only**; the LLM is the final classifier.
- **Hybrid + bidirectional retrieval**: recall over precision at the candidate
  stage; the canonical (min_id, max_id) pair key makes the merge symmetric and
  stable; `retrieval_methods` keeps provenance per pair.
- **relation / relation_type / relation_basis / relation_mode are independent
  dimensions**; the prompt and schema teach the model not to conflate them
  (verified: the model produced تعارض+ضمنی and تکمیل+ارجاعی in the same run).
- **TOP_K is candidate count, not relation count.**
- **Addresses/sources are never LLM-generated** — verbatim metadata join by id.
- **Simple staleness policy**: fingerprint (count + ids) mismatch ⇒ rebuild.
- **LangGraph only inside `analyses_service.py`**, linear 5-node graph.

## Future Extension Points

- **Reranker** (cross-encoder) between the hybrid pool and the LLM — now more
  valuable with TOP_K=20 pools.
- **Persian text normalization** (ی/ي, ک/ك, ZWNJ handling) before BM25 to
  improve lexical recall.
- **Richer reference matching**: breadcrumb/law-name cross-document matching,
  references by «قانون X» names.
- **Automatic LLM retry/backoff** for transient API failures.
- **Async/background `/analyze`** (job id + polling) for large corpora.
- **Reverse-verdict merging policy**: currently a pair is analyzed once
  (canonical order); if directional asymmetry matters later, keep per-direction
  verdicts separately.
- **Evaluation harness**: labeled pair set for precision/recall measurement.
- **API key via environment variable.**
- **Confidence calibration / low-confidence review queue.**
