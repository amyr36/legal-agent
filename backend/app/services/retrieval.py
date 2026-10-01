import re
from typing import Any, Dict, List, Optional, Tuple

from app.services import vector_store as vss
from app.core.config import TOP_K


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def records_by_id(records: List[Dict]) -> Dict[Any, Dict]:
    return {r.get("id"): r for r in records if r.get("id") is not None}


# ---------------------------------------------------------------------------
# BM25 lexical retriever
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077FA-Za-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(str(text)) if t.strip()]


class BM25Index:
    """Minimal BM25 lexical index over the records of one document slot."""

    def __init__(self, records: List[Dict]):
        from rank_bm25 import BM25Okapi

        self._records = records
        self._by_index = {i: r for i, r in enumerate(records)}
        corpus_tokens = [_tokenize(r.get("text", "")) for r in records]
        self._bm25 = BM25Okapi(corpus_tokens) if records else None

    def search(self, query: str, k: int) -> List[Tuple[Dict, float]]:
        if not self._bm25 or not str(query).strip():
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        hits = [(self._by_index[i], float(scores[i])) for i in order if scores[i] > 0]
        if not hits:
            hits = [(self._by_index[i], 1e-9) for i in order]
        return hits


# ---------------------------------------------------------------------------
# FAISS semantic search
# ---------------------------------------------------------------------------


def _semantic_search(vector_store, query_text: str, top_k: int) -> List[Tuple[Any, float]]:
    hits = vector_store.similarity_search_with_score(query_text, k=top_k)
    return [(doc.metadata.get("id"), float(score)) for doc, score in hits]


# ---------------------------------------------------------------------------
# Reference/metadata matching
# ---------------------------------------------------------------------------

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _fa_to_int(raw: str) -> Optional[int]:
    try:
        return int(str(raw).translate(_FA_DIGITS))
    except (ValueError, TypeError):
        return None


def _reference_candidates(source_record: Dict, target_records: List[Dict]) -> List[Dict]:
    text = str(source_record.get("text", ""))
    candidates: List[Dict] = []
    for match in re.finditer(r"(ماده|اصل|تبصره|بند)\s*([۰-۹0-9]+)", text):
        kind, raw_number = match.group(1), match.group(2)
        number = _fa_to_int(raw_number)
        if number is None:
            continue
        for record in target_records:
            if record.get("number") != number:
                continue
            record_type = str(record.get("type") or "")
            if kind == "ماده" and "ماده" not in record_type:
                continue
            candidates.append(record)
    return candidates


# ---------------------------------------------------------------------------
# Hybrid retrieval (A -> B only)
# ---------------------------------------------------------------------------


def retrieve_candidates(
    vector_stores: Dict[str, Any],
    records_a: List[Dict],
    records_b: List[Dict],
    top_k: int = TOP_K,
) -> List[Dict]:
    """HYBRID candidate generation (A -> B, FAISS+BM25+ref)."""
    bm25_b = BM25Index(records_b)
    by_id_b = records_by_id(records_b)
    vector_store_b = vector_stores["B"]

    pairs_by_key: Dict[Tuple[Any, Any], Dict] = {}

    def _add_pair(rec_source: Dict, rec_target: Dict) -> None:
        key = (rec_source.get("id"), rec_target.get("id"))
        entry = pairs_by_key.get(key)
        if entry is None:
            pairs_by_key[key] = {
                "source": rec_source,
                "candidate": rec_target,
            }

    for record in records_a:
        query_text = str(record.get("text", ""))
        if not query_text.strip():
            continue

        for target_id, distance in _semantic_search(vector_store_b, query_text, top_k):
            target_record = by_id_b.get(target_id)
            if target_record is not None:
                _add_pair(record, target_record)

        for target_record, score in bm25_b.search(query_text, top_k):
            _add_pair(record, target_record)

        for target_record in _reference_candidates(record, records_b):
            _add_pair(record, target_record)

    return list(pairs_by_key.values())


def deduplicate_pairs(pairs: List[Dict]) -> List[Dict]:
    seen: set = set()
    unique: List[Dict] = []
    for pair in pairs:
        key = (pair["source"].get("id"), pair["candidate"].get("id"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(pair)
    dropped = len(pairs) - len(unique)
    if dropped:
        print(f"  [dedup] removed {dropped} duplicate pair(s); {len(unique)} remain")
    return unique


# ---------------------------------------------------------------------------
# Standalone run
# ---------------------------------------------------------------------------


def quick_lanch() -> list[dict]:
    print("=== services.retrieval (standalone) ===")
    print("[1/4] loading context ...")
    records_a = vss.load_context("A")
    records_b = vss.load_context("B")
    print(f"      A: {len(records_a)} record(s) | B: {len(records_b)} record(s)")

    print("[2/4] loading embeddings + FAISS ...")
    embeddings = vss.get_embeddings()
    vector_stores = vss.build_or_load_all(embeddings, rebuild=False)

    print("[3/4] running hybrid retrieval (A -> B) ...")
    pairs = retrieve_candidates(vector_stores, records_a, records_b, top_k=TOP_K)
    pairs = deduplicate_pairs(pairs)

    print(f"[4/4] {len(pairs)} unique candidate pair(s):")

    return pairs


if __name__ == "__main__":
    pairs = quick_lanch()
