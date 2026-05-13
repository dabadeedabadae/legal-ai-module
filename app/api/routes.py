from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import aliased
from pydantic import BaseModel
from app.core.database import get_db
from app.models.document import Document, DocumentVersion, DocumentDiff
from app.services.rag.qa_service import search_relevant_articles
from app.services.rag.multi_agent import run_multi_agent
from app.core.database import async_session_maker
from app.core.query_log import save_query
from app.core.db_query_log import list_query_logs
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


async def _build_context(question: str) -> tuple[str, bool]:
    try:
        async with async_session_maker() as session:
            articles = await search_relevant_articles(session, question)
            return "\n\n".join([a["text"] for a in articles]), True
    except Exception:
        return "", False


_KNOWN_SOURCES = {"flutter", "web", "api"}


def detect_source(http_request: Request, default: str) -> str:
    """Determine the request source.

    Precedence:
      1. Explicit X-Source header if it's one of the known values.
      2. User-Agent heuristic (Dart/Flutter → flutter; Mozilla → web).
      3. Caller-supplied default (e.g. "api" for /ask, "ws" for the socket).
    """
    explicit = (http_request.headers.get("x-source") or "").strip().lower()
    if explicit in _KNOWN_SOURCES:
        return explicit

    ua = (http_request.headers.get("user-agent") or "").lower()
    if "dart" in ua or "flutter" in ua:
        return "flutter"
    if "mozilla" in ua or "chrome" in ua or "safari" in ua or "edge" in ua:
        return "web"
    return default


def client_ip(http_request: Request) -> str | None:
    fwd = http_request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if http_request.client and http_request.client.host:
        return http_request.client.host
    return None


async def _ask_with_agents(
    request: QuestionRequest,
    source: str,
    http_request: Request | None = None,
) -> dict:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    detected_source = detect_source(http_request, source) if http_request else source
    ip_address = client_ip(http_request) if http_request else None

    context, db_available = await _build_context(request.question)

    try:
        result = await run_multi_agent(
            request.question,
            context,
            source=detected_source,
            ip_address=ip_address,
        )
    except Exception as exc:
        save_query(
            question=request.question,
            result={"agents": [], "final_answer": "", "total_tokens": 0, "total_time": 0},
            db_available=db_available,
            source=detected_source,
            user_id=request.user_id,
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=f"Agent pipeline failed: {exc}")

    query_id = save_query(
        question=request.question,
        result=result,
        db_available=db_available,
        source=detected_source,
        user_id=request.user_id,
    )

    return {
        "question": request.question,
        "answer": result["final_answer"],
        "user_id": request.user_id,
        "total_tokens": result["total_tokens"],
        "total_time": result["total_time"],
        "agents": result["agents"],
        "query_id": query_id,
        "db_available": db_available,
        "source": detected_source,
    }


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
async def ask_question(request: QuestionRequest, http_request: Request, _=Depends(verify_api_key)):
    return await _ask_with_agents(request, source="api", http_request=http_request)

@router.post("/ui/ask", include_in_schema=False)
async def ask_question_ui(request: QuestionRequest, http_request: Request, _=Depends(verify_api_key)):
    return await _ask_with_agents(request, source="web", http_request=http_request)

@router.post("/ask/multi")
async def ask_question_multi(request: QuestionRequest, http_request: Request, _=Depends(verify_api_key)):
    return await _ask_with_agents(request, source="api", http_request=http_request)


@router.get("/history")
async def history_json(
    page: int = Query(1, ge=1),
    source: str | None = Query(None),
    language: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    try:
        return await list_query_logs(
            page=page,
            page_size=20,
            source=source or None,
            language=language or None,
            date_from=date_from or None,
            date_to=date_to or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"History unavailable: {exc}")
