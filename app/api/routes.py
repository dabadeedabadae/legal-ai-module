from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.core.database import get_db
from app.models.document import Document, DocumentVersion, DocumentDiff
from app.services.rag.qa_service import answer_question
import json
import os

router = APIRouter()

def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("LARAVEL_API_KEY", "secret_key_change_me"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

class QuestionRequest(BaseModel):
    question: str
    user_id: int | None = None

@router.get("/documents")
async def list_documents(db: AsyncSession = Depends(get_db), _=Depends(verify_api_key)):
    result = await db.execute(select(Document))
    docs = result.scalars().all()
    return [{"id": d.id, "external_id": d.external_id, "title_ru": d.title_ru} for d in docs]

@router.get("/documents/{doc_id}/changes")
async def get_changes(doc_id: int, db: AsyncSession = Depends(get_db), _=Depends(verify_api_key)):
    result = await db.execute(
        select(DocumentDiff)
        .where(DocumentDiff.document_id == doc_id)
        .where(DocumentDiff.ai_summary_ru != None)
        .order_by(DocumentDiff.id.desc())
        .limit(10)
    )
    diffs = result.scalars().all()
    changes = []
    for d in diffs:
        v_old = await db.get(DocumentVersion, d.version_old_id)
        v_new = await db.get(DocumentVersion, d.version_new_id)
        diff_data = json.loads(d.diff_json)
        changes.append({
            "id": d.id,
            "date_from": v_old.version_date if v_old else None,
            "date_to": v_new.version_date if v_new else None,
            "summary_ru": d.ai_summary_ru,
            "affects_sentence": d.affects_sentence,
            "total_changes": diff_data.get("total_changes", 0),
        })
    return changes

@router.get("/changes/important")
async def get_important_changes(db: AsyncSession = Depends(get_db), _=Depends(verify_api_key)):
    result = await db.execute(
        select(DocumentDiff)
        .where(DocumentDiff.affects_sentence == True)
        .order_by(DocumentDiff.id.desc())
        .limit(20)
    )
    diffs = result.scalars().all()
    return [{"id": d.id, "summary_ru": d.ai_summary_ru} for d in diffs]

@router.post("/ask")
async def ask_question(request: QuestionRequest, _=Depends(verify_api_key)):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    answer = await answer_question(request.question)
    return {
        "question": request.question,
        "answer": answer,
        "user_id": request.user_id,
    }

@router.post("/ui/ask", include_in_schema=False)
async def ask_question_ui(request: QuestionRequest):
    """Endpoint for the local web UI (no API key required)."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    answer = await answer_question(request.question)
    return {
        "question": request.question,
        "answer": answer,
        "user_id": request.user_id,
    }
