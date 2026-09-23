"""Internal LangGraph workflow.

Runnable standalone:  python -m services.langgraph
(runs the full pipeline: context -> vector stores -> retrieval -> LLM -> save)
"""

import os
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from services import vector_store as vss
from core.config import TOP_K
from services.llm_analisis import (
    analyze_all_pairs,
    get_chat_model,
    save_results,
    shape_results,
)
from services.retrieval import deduplicate_pairs, retrieve_candidates
from schemas.analysis import AnalysisState, AnalysisResult


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _load_context_node(state: AnalysisState) -> Dict:
    print("[analysis] node: load_context")
    records_a = vss.load_context("A")
    records_b = vss.load_context("B")
    print(f"  A: {len(records_a)} record(s), B: {len(records_b)} record(s)")
    return {"records_a": records_a, "records_b": records_b}


def _load_vector_stores_node(state: AnalysisState) -> Dict:
    print("[analysis] node: load_vector_stores")
    embeddings = state.get("embeddings") or vss.get_embeddings()
    vector_stores = vss.build_or_load_all(embeddings, rebuild=state.get("rebuild", False))
    for key, vs in vector_stores.items():
        print(f"  FAISS {key}: {len(vs.index_to_docstore_id)} vectors")
    return {"embeddings": embeddings, "vector_stores": vector_stores}


def _retrieve_candidates_node(state: AnalysisState) -> Dict:
    print("[analysis] node: retrieve_candidates")
    pairs = retrieve_candidates(
        state["vector_stores"],
        state["records_a"],
        state["records_b"],
        top_k=state.get("top_k", TOP_K),
    )
    unique = deduplicate_pairs(pairs)
    method_counts: Dict[str, int] = {}
    for p in unique:
        for m in p.get("retrieval_methods", []):
            method_counts[m] = method_counts.get(m, 0) + 1
    print(f"  {len(unique)} unique candidate pair(s); methods: {method_counts}")
    return {"candidate_pairs": unique}


def _analyze_with_llm_node(state: AnalysisState) -> Dict:
    print("[analysis] node: analyze_with_llm")
    chat_model = state.get("chat_model") or get_chat_model()
    raw = analyze_all_pairs(state["candidate_pairs"], chat_model)
    print(f"  {len(raw)} structured result(s)")
    return {"raw_results": raw}


def _save_results_node(state: AnalysisState) -> Dict:
    print("[analysis] node: save_results")
    results = state["raw_results"]
    path = save_results(state["raw_results"])
    print(f"  saved {len(results)} result(s) to {path}")
    return {"results": results, "results_path": path}


# ---------------------------------------------------------------------------
# Graph wiring
# ---------------------------------------------------------------------------


def build_analysis_graph() -> StateGraph:
    graph = StateGraph(AnalysisState)
    graph.add_node("load_context", _load_context_node)
    graph.add_node("load_vector_stores", _load_vector_stores_node)
    graph.add_node("retrieve_candidates", _retrieve_candidates_node)
    graph.add_node("analyze_with_llm", _analyze_with_llm_node)
    graph.add_node("save_results", _save_results_node)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "load_vector_stores")
    graph.add_edge("load_vector_stores", "retrieve_candidates")
    graph.add_edge("retrieve_candidates", "analyze_with_llm")
    graph.add_edge("analyze_with_llm", "save_results")
    graph.add_edge("save_results", END)
    return graph


def run_analysis(
    rebuild: bool = False,
    embeddings=None,
    chat_model=None,
    top_k: int = TOP_K,
) -> Dict:
    rebuild = rebuild or os.environ.get("LEGAL_SIM_REBUILD", "") == "1"
    graph = build_analysis_graph().compile()
    return graph.invoke({
        "rebuild": rebuild,
        "embeddings": embeddings,
        "chat_model": chat_model,
        "top_k": top_k,
    })


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
    rebuild: bool = False,
) -> List[Dict]:
    if records_a:
        _validate_records(records_a, "document_a")
        vss.save_context("A", records_a)
    if records_b:
        _validate_records(records_b, "document_b")
        vss.save_context("B", records_b)

    state = run_analysis(rebuild=rebuild)
    return state.get("results", [])


