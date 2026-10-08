from typing import Any, Dict, List, Optional
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel, Field
import json
import logging
import uuid

from app.services import workflow, llm_analisis, retrieval
from app.core.config import SOURCES_DIR
from app.api.dependencies import get_current_user
from app.models.identity.user import User

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/analyze", tags=["analyze"], dependencies=[Depends(get_current_user)])


class AnalyzeRequest(BaseModel):
    doc_a_id: int
    doc_b_id: int


class RunStarted(BaseModel):
    run_id: str


_active_runs: set[str] = set()
_early_errors: Dict[str, str] = {}


def _run_in_background(doc_a_id: int, doc_b_id: int, user_id: int, run_id: str) -> None:
    try:
        workflow.analyze_documents(doc_a_id, doc_b_id, user_id, run_id=run_id)
    except Exception as exc:
        logger.exception("analysis %s failed", run_id)
        _early_errors[run_id] = str(exc)
    finally:
        _active_runs.discard(run_id)


def _resume_in_background(run_id: str) -> None:
    try:
        workflow.resume_analysis(run_id)
    except Exception as exc:
        logger.exception("resume of analysis %s failed", run_id)
        _early_errors[run_id] = str(exc)
    finally:
        _active_runs.discard(run_id)


@router.post("/workflow/run", response_model=RunStarted, status_code=202)
def run_workflow(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> RunStarted:
    if request.doc_a_id == request.doc_b_id:
        raise HTTPException(status_code=400, detail="Choose two different documents")

    run_id = str(uuid.uuid4())
    _active_runs.add(run_id)
    background_tasks.add_task(
        _run_in_background,
        request.doc_a_id,
        request.doc_b_id,
        current_user.user_id,
        run_id,
    )
    return RunStarted(run_id=run_id)


@router.get("/workflow/status")
def get_workflow_status(run_id: str):
    try:
        status = workflow.get_status(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if status["status"] == "not_found":
        if run_id in _early_errors:
            return {"run_id": run_id, "status": "failed", "error": _early_errors[run_id]}
        if run_id in _active_runs:
            return {"run_id": run_id, "status": "queued"}
        return status

    if run_id in _active_runs and status["status"] in ("failed", "running"):
        return {"run_id": run_id, "status": "running", "step": status.get("step")}

    if status["status"] == "completed":
        relations = workflow.load_results(status["results_path"])
        return {
            "run_id": run_id,
            "status": "completed",
            "count": len(relations),
            "relations": relations,
        }

    return status


@router.post("/workflow/resume", response_model=RunStarted, status_code=202)
def resume_workflow(run_id: str, background_tasks: BackgroundTasks):
    try:
        status = workflow.get_status(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if status["status"] == "not_found" and run_id not in _early_errors:
        raise HTTPException(status_code=404, detail="Run not found")
    if run_id in _active_runs:
        raise HTTPException(status_code=409, detail="Run is already running")

    _early_errors.pop(run_id, None)
    _active_runs.add(run_id)
    background_tasks.add_task(_resume_in_background, run_id)
    return RunStarted(run_id=run_id)


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