from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import workflow, llm_analisis, retrieval


router = APIRouter(prefix="/analyze", tags=["analyze"])


class AnalyzeRequest(BaseModel):
    document_a: Optional[List[Dict[str, Any]]]
    document_b: Optional[List[Dict[str, Any]]]
    rebuild: bool = Field(default=False, description="rebuild Chunks and VectorDatabase")


class AnalyzeResponse(BaseModel):
    count: int
    relations: List[Dict[str, Any]]



@router.post("/workflow", response_model=AnalyzeResponse)
def run_workflow(request: AnalyzeRequest) -> AnalyzeResponse:
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


# @router.get("/workflow")
# def get_workflow:


# @router.post("/llm")
# def run_llm_analyze():


@router.post("/retrieval")
def run_retrieval():
    try:
        candidates = retrieval.quick_lanch()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))   
    return candidates

# @router.post("/vector")
# def run_vector_store():