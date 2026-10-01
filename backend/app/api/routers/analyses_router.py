from typing import Any, Dict, List, Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
import json

from app.services import workflow, llm_analisis, retrieval
from app.core.config import SOURCES_DIR
from app.api.dependencies import get_current_user


router = APIRouter(prefix="/analyze", tags=["analyze"], dependencies=[Depends(get_current_user)])


class AnalyzeRequest(BaseModel):
    document_a: Optional[List[Dict[str, Any]]] = None
    document_b: Optional[List[Dict[str, Any]]] = None
    rebuild: bool = Field(default=True, description="rebuild Chunks and VectorDatabase")


class AnalyzeResponse(BaseModel):
    count: int
    relations: List[Dict[str, Any]]



@router.post("/workflow/run", response_model=AnalyzeResponse)
def run_workflow(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        results = workflow.analyze_documents(records_a=request.document_a, records_b=request.document_b)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return AnalyzeResponse(count=len(results), relations=results)


@router.get("/workflow/status")
def get_workflow_status(run_id: str):
    try:
        status = workflow.get_status(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return status

@router.post("/workflow/resume")
def resume_workflow(run_id: str):
    try:
        results = workflow.resume_analysis(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return results


@router.post("/llm")
def run_llm_analyze():
    path = Path(SOURCES_DIR) / "file.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    pairs = json.loads(Path(path).read_text(encoding="utf-8"))   
    try:
        raw = llm_analisis.analyze_all_pairs(pairs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return raw



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