from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from services import workflow, llm_analisis, retrieval, vector_store, text_extractor 


app = FastAPI()


class AnalyzeRequest(BaseModel):
    document_a: Optional[List[Dict[str, Any]]]
    document_b: Optional[List[Dict[str, Any]]]
    rebuild: bool = Field(default=False, description="rebuild Chunks and VectorDatabase")


class AnalyzeResponse(BaseModel):
    count: int
    relations: List[Dict[str, Any]]


@app.get("/")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        results = workflow.analyze_documents(
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
