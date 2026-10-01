import json
import os
import sqlite3
import uuid
from functools import lru_cache
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from app.core.config import TOP_K ,CHECKPOINT_DB ,CANDIDATES_PATH ,MAX_MISSING_RATIO
from app.services import vector_store as vss
from app.services.llm_analisis import analyze_all_pairs, get_chat_model, save_results
from app.services.retrieval import deduplicate_pairs, retrieve_candidates


# ---------------------------------------------------------------------------
# State 
# ---------------------------------------------------------------------------


class AnalysisState(TypedDict, total=False):
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
# Nodes
# ---------------------------------------------------------------------------


def _load_context_node(state: AnalysisState) -> Dict:
    print("[analysis] node: load_context")
    records_a = vss.load_context("A")
    records_b = vss.load_context("B")
    if not records_a or not records_b:
        raise ValueError(
            f"empty context: A={len(records_a)} record(s), B={len(records_b)} record(s)"
        )
    print(f"  A: {len(records_a)} record(s), B: {len(records_b)} record(s)")
    return {"count_a": len(records_a), "count_b": len(records_b)}


def _load_vector_stores_node(state: AnalysisState) -> Dict:
    print("[analysis] node: load_vector_stores")
    stores = vss.build_or_load_all(_get_embeddings(), rebuild=True)
    counts = {key: len(vs.index_to_docstore_id) for key, vs in stores.items()}
    for key, n in counts.items():
        print(f"  FAISS {key}: {n} vectors")
    return {"vector_counts": counts}


def _retrieve_candidates_node(state: AnalysisState) -> Dict:
    print("[analysis] node: retrieve_candidates")
    records_a = vss.load_context("A")
    records_b = vss.load_context("B")
    stores = vss.build_or_load_all(_get_embeddings(), rebuild=False)

    pairs = retrieve_candidates(
        stores, records_a, records_b, top_k=state.get("top_k", TOP_K)
    )
    unique = deduplicate_pairs(pairs)

    method_counts: Dict[str, int] = {}
    for p in unique:
        for m in p.get("retrieval_methods", []):
            method_counts[m] = method_counts.get(m, 0) + 1
    print(f"  {len(unique)} unique candidate pair(s); methods: {method_counts}")

    _write_jsonl(CANDIDATES_PATH, unique)
    return {"candidates_path": CANDIDATES_PATH, "candidate_count": len(unique)}


def _analyze_and_save_node(state: AnalysisState) -> Dict:
    print("[analysis] node: analyze_with_llm")
    pairs = _read_jsonl(state["candidates_path"])
    results = analyze_all_pairs(pairs, get_chat_model())
    print(f"  {len(results)} structured result(s)")

    expected = {(p["source"].get("id"), p["candidate"].get("id")) for p in pairs}
    got = {(r.source_id, r.target_id) for r in results}
    missing = expected - got
    if expected and len(missing) / len(expected) > MAX_MISSING_RATIO:
        raise RuntimeError(
            f"LLM analysis incomplete: {len(missing)}/{len(expected)} pair(s) "
            f"have no verdict; resume the run to retry"
        )

    shaped = [r.model_dump() for r in results]  # pydantic -> dict for json
    path = save_results(shaped)
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


def run_analysis(run_id: Optional[str] = None,top_k: int = TOP_K,) -> Dict:
    run_id = run_id or str(uuid.uuid4())
    print(f"[analysis] run_id={run_id}")
    state = _get_graph().invoke(
        {"top_k": top_k}, _config(run_id)
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
    records_a: Optional[List[Dict]] = None,
    records_b: Optional[List[Dict]] = None,
    run_id: Optional[str] = None,) -> List[Dict]:
    if records_a:
        _validate_records(records_a, "document_a")
        vss.save_context("A", records_a)
    if records_b:
        _validate_records(records_b, "document_b")
        vss.save_context("B", records_b)

    state = run_analysis(run_id=run_id)
    return load_results(state["results_path"])


"""if __name__ == "__main__":
    rid = str(uuid.uuid4())
    try:
        run_analysis(run_id=rid)
    except Exception as exc:
        print(f"[analysis] run {rid} failed: {exc}")
    print(get_status(rid))"""