from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import aliased
from pydantic import BaseModel
from app.core.database import get_db
from app.models.document import Document, DocumentVersion, DocumentDiff
from app.services.rag.qa_service import answer_question, search_relevant_articles
from app.services.rag.multi_agent import run_multi_agent
from app.core.database import async_session_maker
import hmac
import json
import os

router = APIRouter()

def verify_api_key(x_api_key: str = Header(...)):
    expected = os.getenv("LARAVEL_API_KEY", "")
    if not hmac.compare_digest(x_api_key, expected):
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
    v_old = aliased(DocumentVersion)
    v_new = aliased(DocumentVersion)
    result = await db.execute(
        select(DocumentDiff, v_old, v_new)
        .join(v_old, DocumentDiff.version_old_id == v_old.id)
        .join(v_new, DocumentDiff.version_new_id == v_new.id)
        .where(DocumentDiff.document_id == doc_id)
        .where(DocumentDiff.ai_summary_ru.is_not(None))
        .order_by(DocumentDiff.id.desc())
        .limit(10)
    )
    rows = result.all()
    changes = []
    for diff, ver_old, ver_new in rows:
        diff_data = json.loads(diff.diff_json)
        changes.append({
            "id": diff.id,
            "date_from": ver_old.version_date,
            "date_to": ver_new.version_date,
            "summary_ru": diff.ai_summary_ru,
            "affects_sentence": diff.affects_sentence,
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
async def ask_question_ui(request: QuestionRequest, _=Depends(verify_api_key)):
    """Endpoint for the local web UI."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    answer = await answer_question(request.question)
    return {
        "question": request.question,
        "answer": answer,
        "user_id": request.user_id,
    }

@router.post("/ask/multi")
async def ask_question_multi(request: QuestionRequest, _=Depends(verify_api_key)):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    context = ""
    try:
        async with async_session_maker() as session:
            articles = await search_relevant_articles(session, request.question)
            context = "\n\n".join([a["text"] for a in articles])
    except Exception:
        pass

    result = await run_multi_agent(request.question, context)

    return {
        "question": request.question,
        "answer": result["final_answer"],
        "total_time": result["total_time"],
    }
