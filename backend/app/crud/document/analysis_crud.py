from typing import List, Dict, Optional, Any

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.models.analysis.analysis import Analysis


def save_analysis(
    db: Session,
    document_a_id: int,
    document_b_id: int,
    user_id: int,
    results: Dict[str, Any],
) -> Analysis:
    row = Analysis(
        document_a_id=document_a_id,
        document_b_id=document_b_id,
        user_id=user_id,
        analysis_result=results,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_analysis(
    db: Session,
    analysis_id: int,
    user_id: Optional[int] = None,
) -> Optional[Analysis]:
    stmt = select(Analysis).where(Analysis.analysis_id == analysis_id)
    if user_id is not None:
        stmt = stmt.where(Analysis.user_id == user_id)
    return db.scalar(stmt)


def get_analyses_by_document(
    db: Session,
    document_id: int,
    user_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[Analysis]:
    stmt = select(Analysis).where(
        or_(
            Analysis.document_a_id == document_id,
            Analysis.document_b_id == document_id,
        )
    )
    if user_id is not None:
        stmt = stmt.where(Analysis.user_id == user_id)
    stmt = (
        stmt.order_by(Analysis.created_at.desc(), Analysis.analysis_id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def get_analyses_by_user(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 100,
) -> List[Analysis]:
    stmt = (
        select(Analysis)
        .where(Analysis.user_id == user_id)
        .order_by(Analysis.created_at.desc(), Analysis.analysis_id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def delete_analysis(
    db: Session,
    analysis_id: int,
    user_id: Optional[int] = None,
) -> bool:
    row = get_analysis(db, analysis_id, user_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True