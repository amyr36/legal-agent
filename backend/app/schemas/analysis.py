from typing import Any, Dict, List, Literal, TypedDict

from pydantic import BaseModel, Field



# ---------------------------------------------------------------------------
# LLM output schemas
# ---------------------------------------------------------------------------


class AnalysisResult(BaseModel):

    source_id: int 
    target_id: int 
    relation: Literal["مشابه", "متناقض", "بی‌ارتباط"]
    relation_type: Literal[None, "تکرار مقرراتی", "اقتباس", "تکمیل", "تخصیص", "تعارض", "نسخ صریح", "نسخ ضمنی", "ابهام تفسیری", "ناسازگاری"]
    explanation: str
    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )


class BatchAnalysisResult(BaseModel):
    """LLM verdicts for a batch of candidate pairs sent in one prompt."""

    results: List[AnalysisResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LangGraph state schema
# ---------------------------------------------------------------------------


class AnalysisState(TypedDict, total=False):

    rebuild: bool
    records_a: List[Dict]
    records_b: List[Dict]
    embeddings: Any
    chat_model: Any
    top_k: int
    vector_stores: Dict[str, Any]
    candidate_pairs: List[Dict]
    raw_results: List[AnalysisResult]
    results: List[Dict]
    results_path: str
