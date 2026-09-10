from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from services import analyses_service as ans

app = FastAPI(
    title="Legal Document Comparison MVP",
    description="Compares two legal documents (A vs B) record-by-record and returns "
    "similar / contradiction / neither relations with explanations and exact sources.",
    version="0.1.0",
)


class AnalyzeRequest(BaseModel):
    document_a: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Records of document A (one legal unit per item). Omit to use sources/context_A.jsonl.",
    )
    document_b: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Records of document B (one legal unit per item). Omit to use sources/context_B.jsonl.",
    )
    rebuild: bool = Field(
        default=False,
        description="Force rebuilding both vector-store indexes from the records.",
    )


class AnalyzeResponse(BaseModel):
    count: int
    relations: List[Dict[str, Any]]


@app.get("/health")
def health() -> Dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        results = ans.analyze_documents(
            records_a=request.document_a,
            records_b=request.document_b,
            rebuild=request.rebuild,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return AnalyzeResponse(count=len(results), relations=results)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
