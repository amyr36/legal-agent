"""FastAPI server for the legal document comparison MVP.

app.py is ONLY the API layer:

    FastAPI -> endpoint -> analyses_service.analyze_documents() -> response

All analysis logic lives in services/analyses_service.py; vector stores live
in services/vector_store_service.py. Analysis runs only when the endpoint is
called — starting this file just starts the server.

Run:

    python app.py        # serves on http://127.0.0.1:8000 (docs at /docs)

Endpoints:
    GET  /health                       -> liveness probe
    POST /analyze                      -> run A -> B comparison, return relations
"""

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from services import workflow as ans

app = FastAPI(
    title="Legal Document Comparison MVP",
    description="Compares two legal documents (A vs B) record-by-record and returns "
    "similar / contradiction / neither relations with explanations and exact sources.",
    version="0.1.0",
)


class AnalyzeRequest(BaseModel):
    """Body of POST /analyze.

    Both lists are optional: pass records inline, or omit them to analyze
    whatever is currently in sources/context_A.jsonl / context_B.jsonl.
    """

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
    """Run the comparison workflow (A -> B) and return the relations found.

    Delegates everything to analyses_service.analyze_documents().
    """
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
