import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from fastapi import HTTPException, status
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from app.core.config import (
    CANDIDATES_PATH,
    CHECKPOINT_DB,
    MAX_MISSING_RATIO,
    RESULTS_PATH,
    TOP_K,
)
from app.db.database import SessionLocal
from app.models.identity.user import User
from app.services import document_service
from app.services import vector_store as vss
from app.services.llm_analisis import analyze_all_pairs, get_chat_model, save_results
from app.services.retrieval import deduplicate_pairs, retrieve_candidates


# ---------------------------------------------------------------------------
# State 
# ---------------------------------------------------------------------------


class AnalysisState(TypedDict, total=False):
    doc_a_id: int
    doc_b_id: int
    user_id: int
    top_k: int
    count_a: int
    count_b: int
    vector_counts: Dict[str, int]
    candidates_path: str
    candidate_count: int
    results_path: str
    result_count: int


# ---------------------------------------------------------------------------
# Process-level caches 
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_embeddings():
    return vss.get_embeddings()


@lru_cache(maxsize=1)
def _get_checkpointer() -> SqliteSaver:
    conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    return SqliteSaver(conn)


# ---------------------------------------------------------------------------
# jsonl helpers 
# ---------------------------------------------------------------------------


def _write_jsonl(path: str, items: List[Dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _read_jsonl(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_results(path: str) -> List[Dict]:
    return _read_jsonl(path)


# ---------------------------------------------------------------------------
# Document helpers (DB session + per-document records / FAISS stores)
# ---------------------------------------------------------------------------


@contextmanager
def _db_and_user(state: AnalysisState):
    """Open a short-lived session and load the user stored in the state.
    (Session / User objects are not checkpointable, so only ids live in state.)"""
    db = SessionLocal()
    try:
        user = db.get(User, state["user_id"])
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
        yield db, user
    finally:
        db.close()


def _articles(records: Optional[List[Dict]]) -> List[Dict]:
    """The per-document FAISS index only holds article records, so the
    analysis works on articles only (title/preamble are skipped)."""
    return [
        r for r in (records or [])
        if r.get("kind") == "article" and str(r.get("text", "")).strip()
    ]


def _load_article_records(state: AnalysisState):
    with _db_and_user(state) as (db, user):
        records_a = document_service.read_structure(db, state["doc_a_id"], user)
        records_b = document_service.read_structure(db, state["doc_b_id"], user)
    return _articles(records_a), _articles(records_b)


def _load_stores(state: AnalysisState) -> Dict[int, Any]:
    """Load the prebuilt FAISS stores, keyed by doc_id."""
    with _db_and_user(state) as (db, user):
        return document_service.load_pair_stores(
            db, state["doc_a_id"], state["doc_b_id"], user
        )


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _load_context_node(state: AnalysisState) -> Dict:
    print("[analysis] node: load_context")
    records_a, records_b = _load_article_records(state)
    if not records_a or not records_b:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"No article records: doc A={len(records_a)}, doc B={len(records_b)}",
        )
    print(f"  A: {len(records_a)} article(s), B: {len(records_b)} article(s)")
    return {"count_a": len(records_a), "count_b": len(records_b)}


def _load_vector_stores_node(state: AnalysisState) -> Dict:
    # Validation + counting only. Nothing is built here: the indexes are
    # created at upload time (document_service.run_structure_extraction).
    print("[analysis] node: load_vector_stores")
    stores = _load_stores(state)
    counts = {
        "A": len(stores[state["doc_a_id"]].index_to_docstore_id),
        "B": len(stores[state["doc_b_id"]].index_to_docstore_id),
    }
    for key, n in counts.items():
        print(f"  FAISS {key}: {n} vectors")
    return {"vector_counts": counts}


def _retrieve_candidates_node(state: AnalysisState) -> Dict:
    print("[analysis] node: retrieve_candidates")
    records_a, records_b = _load_article_records(state)
    stores = _load_stores(state)

    pairs = retrieve_candidates(
        {"B": stores[state["doc_b_id"]]},   # retrieval reads only the "B" store
        records_a,
        records_b,
        top_k=state.get("top_k", TOP_K),
    )
    unique = deduplicate_pairs(pairs)

    method_counts: Dict[str, int] = {}
    for p in unique:
        for m in p.get("retrieval_methods", []):
            method_counts[m] = method_counts.get(m, 0) + 1
    print(f"  {len(unique)} unique candidate pair(s); methods: {method_counts}")

    _write_jsonl(state["candidates_path"], unique)
    return {"candidate_count": len(unique)}


def _analyze_and_save_node(state: AnalysisState) -> Dict:
    print("[analysis] node: analyze_with_llm")
    pairs = _read_jsonl(state["candidates_path"])

    # Results of earlier attempts of this run (survive a failed node / resume)
    partial_path = state["results_path"] + ".partial"
    done = _read_jsonl(partial_path) if os.path.exists(partial_path) else []
    done_keys = {(r["source_id"], r["target_id"]) for r in done}

    todo = [
        p for p in pairs
        if (p["source"].get("id"), p["candidate"].get("id")) not in done_keys
    ]
    print(f"  {len(done)} already done, {len(todo)} to go")

    results = analyze_all_pairs(todo, get_chat_model())
    print(f"  {len(results)} new result(s)")

    # persist successful results BEFORE the completeness check
    new = [r.model_dump() for r in results]  # pydantic -> dict for json
    with open(partial_path, "a", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    shaped = done + new

    expected = {(p["source"].get("id"), p["candidate"].get("id")) for p in pairs}
    got = {(r["source_id"], r["target_id"]) for r in shaped}
    missing = expected - got
    if expected and len(missing) / len(expected) > MAX_MISSING_RATIO:
        raise RuntimeError(
            f"LLM analysis incomplete: {len(missing)}/{len(expected)} pair(s) "
            f"have no verdict; resume the run to retry"
        )

    path = save_results(shaped, state["results_path"])
    print(f"  saved {len(shaped)} result(s) to {path}")
    return {"results_path": path, "result_count": len(shaped)}


# ---------------------------------------------------------------------------
# Graph wiring
# ---------------------------------------------------------------------------


def build_analysis_graph() -> StateGraph:
    graph = StateGraph(AnalysisState)
    graph.add_node("load_context", _load_context_node)
    graph.add_node("load_vector_stores", _load_vector_stores_node)
    graph.add_node("retrieve_candidates", _retrieve_candidates_node)
    graph.add_node("analyze_with_llm", _analyze_and_save_node)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "load_vector_stores")
    graph.add_edge("load_vector_stores", "retrieve_candidates")
    graph.add_edge("retrieve_candidates", "analyze_with_llm")
    graph.add_edge("analyze_with_llm", END)
    return graph


@lru_cache(maxsize=1)
def _get_graph():
    return build_analysis_graph().compile(checkpointer=_get_checkpointer())


# ---------------------------------------------------------------------------
# Run / resume / status
# ---------------------------------------------------------------------------


def _config(run_id: str) -> Dict:
    return {"configurable": {"thread_id": run_id}}


def _run_paths(run_id: str) -> tuple[str, str]:
    """Per-run candidate/result files, so concurrent runs never overwrite each other."""
    def _per_run(base: str) -> str:
        p = Path(base)
        return str(p.with_name(f"{p.stem}_{run_id}{p.suffix}"))

    return _per_run(CANDIDATES_PATH), _per_run(RESULTS_PATH)


def run_analysis(
    doc_a_id: int,
    doc_b_id: int,
    user_id: int,
    run_id: Optional[str] = None,
    top_k: int = TOP_K,
) -> Dict:
    run_id = run_id or str(uuid.uuid4())
    candidates_path, results_path = _run_paths(run_id)
    print(f"[analysis] run_id={run_id} docs=({doc_a_id}, {doc_b_id})")
    state = _get_graph().invoke(
        {
            "doc_a_id": doc_a_id,
            "doc_b_id": doc_b_id,
            "user_id": user_id,
            "top_k": top_k,
            "candidates_path": candidates_path,
            "results_path": results_path,
        },
        _config(run_id),
    )
    return {"run_id": run_id, **state}


def resume_analysis(run_id: str) -> Dict:
    print(f"[analysis] resuming run_id={run_id}")
    state = _get_graph().invoke(None, _config(run_id))
    return {"run_id": run_id, **state}


def get_status(run_id: str) -> Dict[str, Any]:
    snap = _get_graph().get_state(_config(run_id))
    if not snap.values and not snap.next:
        return {"run_id": run_id, "status": "not_found"}
    if not snap.next:
        return {
            "run_id": run_id,
            "status": "completed",
            "results_path": snap.values.get("results_path"),
        }
    errors = [t.error for t in snap.tasks if getattr(t, "error", None)]
    if errors:
        return {
            "run_id": run_id,
            "status": "failed",
            "step": snap.next[0],
            "error": str(errors[0]),
        }
    return {"run_id": run_id, "status": "running", "step": snap.next[0]}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _validate_records(records: List[Dict], label: str) -> None:
    for i, r in enumerate(records):
        if r.get("id") is None:
            raise ValueError(f"{label}[{i}] is missing the 'id' field")
        if not str(r.get("text", "")).strip():
            raise ValueError(f"{label}[{i}] is missing the 'text' field")


def analyze_documents(
    doc_a_id: int,
    doc_b_id: int,
    user_id: int,
    run_id: Optional[str] = None,
) -> Dict:
    state = run_analysis(doc_a_id, doc_b_id, user_id, run_id=run_id)
    return {
        "run_id": state["run_id"],
        "relations": load_results(state["results_path"]),
    }


"""if __name__ == "__main__":
    rid = str(uuid.uuid4())
    try:
        run_analysis(run_id=rid)
    except Exception as exc:
        print(f"[analysis] run {rid} failed: {exc}")
    print(get_status(rid))"""
