from typing import Any, Dict
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import logging
import uuid

from app.services import workflow, retrieval
from app.api.dependencies import get_current_user
from app.models.identity.user import User
from app.db.database import get_db
from app.crud.document.analysis_crud import (
    get_analysis,
    get_analyses_by_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/analyze",
    tags=["analyze"],
    dependencies=[Depends(get_current_user)],
)


class AnalyzeRequest(BaseModel):
    doc_a_id: int
    doc_b_id: int


class RunStarted(BaseModel):
    run_id: str


_active_runs: set[str] = set()
_early_errors: Dict[str, str] = {}


def _run_in_background(
    doc_a_id: int,
    doc_b_id: int,
    user_id: int,
    run_id: str,
) -> None:
    try:
        workflow.analyze_documents(
            doc_a_id,
            doc_b_id,
            user_id,
            run_id=run_id,
        )
    except Exception as exc:
        logger.exception("Analysis %s failed", run_id)
        _early_errors[run_id] = str(exc)
    finally:
        _active_runs.discard(run_id)


def _resume_in_background(run_id: str) -> None:
    try:
        workflow.resume_analysis(run_id)
    except Exception as exc:
        logger.exception("Resume of analysis %s failed", run_id)
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
        raise HTTPException(
            status_code=400,
            detail="Choose two different documents",
        )

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
def get_workflow_status(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        status = workflow.get_status(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # اگر اجرای workflow پیدا نشد، خطای ثبت‌شده را بررسی کن.
    if status["status"] == "not_found":
        if run_id in _early_errors:
            return {
                "run_id": run_id,
                "status": "failed",
                "error": _early_errors[run_id],
            }

        if run_id in _active_runs:
            return {"run_id": run_id, "status": "queued"}

        return status

    # برای اجراهای موجود، مالکیت run باید بررسی شود.
    # workflow.get_status باید user_id ذخیره‌شده در state را برگرداند.
    run_user_id = status.get("user_id")

    if run_user_id is not None and run_user_id != current_user.user_id:
        raise HTTPException(status_code=404, detail="Run not found")

    if run_id in _active_runs and status["status"] in ("failed", "running"):
        return {
            "run_id": run_id,
            "status": "running",
            "step": status.get("step"),
        }

    if status["status"] == "completed":
        analysis_id = status.get("analysis_id")

        if analysis_id is None:
            raise HTTPException(
                status_code=500,
                detail="Completed run has no associated analysis record",
            )

        analysis = get_analysis(
            db,
            analysis_id=analysis_id,
            user_id=current_user.user_id,
        )

        if analysis is None:
            raise HTTPException(status_code=404, detail="Analysis not found")

        relations = analysis.analysis_result

        return {
            "run_id": run_id,
            "analysis_id": analysis.analysis_id,
            "status": "completed",
            "count": len(relations),
            "relations": relations,
        }

    return status


@router.post("/workflow/resume", response_model=RunStarted, status_code=202)
def resume_workflow(
    run_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    try:
        status = workflow.get_status(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if status["status"] == "not_found" and run_id not in _early_errors:
        raise HTTPException(status_code=404, detail="Run not found")

    # اجرای workflow باید متعلق به همین کاربر باشد.
    run_user_id = status.get("user_id")
    if run_user_id is not None and run_user_id != current_user.user_id:
        raise HTTPException(status_code=404, detail="Run not found")

    if run_id in _active_runs:
        raise HTTPException(status_code=409, detail="Run is already running")

    _early_errors.pop(run_id, None)
    _active_runs.add(run_id)
    background_tasks.add_task(_resume_in_background, run_id)

    return RunStarted(run_id=run_id)


@router.get("/history")
def get_analysis_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    analyses = get_analyses_by_user(
        db,
        user_id=current_user.user_id,
    )

    return [
        {
            "analysis_id": item.analysis_id,
            "document_a_id": item.document_a_id,
            "document_b_id": item.document_b_id,
            "created_at": item.created_at,
        }
        for item in analyses
    ]


@router.get("/history/{analysis_id}")
def get_analysis_history_detail(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    analysis = get_analysis(
        db,
        analysis_id=analysis_id,
        user_id=current_user.user_id,
    )

    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return {
        "analysis_id": analysis.analysis_id,
        "document_a_id": analysis.document_a_id,
        "document_b_id": analysis.document_b_id,
        "created_at": analysis.created_at,
        "count": len(analysis.analysis_result),
        "relations": analysis.analysis_result,
    }


@router.post("/retrieval")
def run_retrieval():
    try:
        return retrieval.quick_lanch()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))