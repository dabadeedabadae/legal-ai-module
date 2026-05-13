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


FAQ_ITEMS = [
    {
        "id": 1,
        "category": "УДО",
        "question": "Когда я могу подать на условно-досрочное освобождение?",
        "answer": (
            "Право на УДО возникает после фактического отбытия минимальной части срока, "
            "которая зависит от тяжести преступления.\n\n"
            "По общему правилу: не менее одной трети срока — за преступления небольшой и средней "
            "тяжести; не менее половины — за тяжкие; не менее двух третей — за особо тяжкие. "
            "Конкретные дроби для вашей статьи уточняйте у юриста или через бот по вашему составу.\n\n"
            "Если нужна помощь с документами — обратитесь к администрации учреждения."
        ),
    },
    {
        "id": 2,
        "category": "УДО",
        "question": "Как подать заявление на УДО?",
        "answer": (
            "Заявление подаётся в суд через администрацию учреждения.\n\n"
            "1. Напишите ходатайство об УДО на имя суда по месту отбывания наказания.\n"
            "2. Передайте его в спецотдел учреждения — администрация в течение 15 дней "
            "направляет материалы в суд и прикладывает характеристику.\n"
            "3. Дождитесь судебного заседания — рассмотрение обычно в течение месяца.\n\n"
            "Если нужна помощь с документами — обратитесь к администрации учреждения."
        ),
    },
    {
        "id": 3,
        "category": "УДО",
        "question": "Что делать, если в УДО отказали?",
        "answer": (
            "Отказ можно обжаловать в апелляционном порядке в течение 15 суток.\n\n"
            "1. Получите копию постановления суда об отказе.\n"
            "2. Подайте апелляционную жалобу через тот же суд, который вынес решение, "
            "адресовав её в апелляционную инстанцию областного суда.\n"
            "3. Повторно подать ходатайство об УДО можно не ранее чем через 6 месяцев "
            "со дня вынесения постановления об отказе.\n\n"
            "Если нужна помощь с документами — обратитесь к администрации учреждения."
        ),
    },
    {
        "id": 4,
        "category": "права",
        "question": "Какие у меня основные права как у осуждённого?",
        "answer": (
            "Осуждённый сохраняет основные права человека — с ограничениями, прямо "
            "установленными законом.\n\n"
            "Ключевые права: на личную безопасность; на охрану здоровья и медицинскую помощь; "
            "на психологическую помощь; на свидания, телефонные разговоры и переписку "
            "в установленном порядке; на обращения в государственные органы и к прокурору; "
            "на юридическую помощь.\n\n"
            "Если нужна помощь с документами — обратитесь к администрации учреждения."
        ),
    },
    {
        "id": 5,
        "category": "права",
        "question": "Имею ли я право на встречу с адвокатом?",
        "answer": (
            "Да. Право на юридическую помощь сохраняется на всех этапах отбывания наказания — "
            "встречи с адвокатом конфиденциальны и не ограничиваются по количеству и "
            "продолжительности.\n\n"
            "Чтобы пригласить адвоката:\n"
            "1. Передайте через администрацию письменное заявление о вызове защитника.\n"
            "2. После прибытия адвоката встреча проходит в отдельном помещении "
            "без прослушивания.\n\n"
            "Если нужна помощь с документами — обратитесь к администрации учреждения."
        ),
    },
    {
        "id": 6,
        "category": "права",
        "question": "Имею ли я право на медицинскую помощь?",
        "answer": (
            "Да. Медицинская помощь оказывается в учреждении бесплатно и в объёме, "
            "гарантированном законодательством РК.\n\n"
            "Что делать при необходимости:\n"
            "1. Запишитесь на приём через дежурного — обращения фиксируются в журнале.\n"
            "2. При острой ситуации помощь оказывается немедленно, без записи.\n"
            "3. Если случай требует стационара или специалистов — вас переводят "
            "в медицинскую часть или гражданскую больницу.\n\n"
            "Если нужна помощь с документами — обратитесь к администрации учреждения."
        ),
    },
    {
        "id": 7,
        "category": "жалобы",
        "question": "Как подать жалобу?",
        "answer": (
            "Жалобы и обращения подаются в письменном виде через администрацию учреждения, "
            "которая обязана направить их адресату без вскрытия и без задержки.\n\n"
            "1. Напишите жалобу с указанием адресата (прокурор, суд, омбудсмен, вышестоящий "
            "орган) и обстоятельств.\n"
            "2. Передайте её сотруднику спецотдела под роспись или через ящик для обращений.\n"
            "3. Сохраните копию или номер регистрации — это пригодится при обжаловании "
            "бездействия.\n\n"
            "Если нужна помощь с документами — обратитесь к администрации учреждения."
        ),
    },
    {
        "id": 8,
        "category": "жалобы",
        "question": "Куда жаловаться на действия администрации?",
        "answer": (
            "Жалобу на действия или бездействие администрации можно направить в несколько "
            "адресов одновременно.\n\n"
            "Основные адресаты:\n"
            "- прокурор по надзору за законностью в местах лишения свободы;\n"
            "- вышестоящий орган уголовно-исполнительной системы;\n"
            "- суд (по правилам административного судопроизводства);\n"
            "- Уполномоченный по правам человека (омбудсмен);\n"
            "- Национальный превентивный механизм.\n\n"
            "Если нужна помощь с документами — обратитесь к администрации учреждения."
        ),
    },
    {
        "id": 9,
        "category": "свидания",
        "question": "Сколько свиданий мне положено?",
        "answer": (
            "Количество и продолжительность свиданий зависит от вида учреждения "
            "и режима содержания.\n\n"
            "В общем случае различают краткосрочные свидания (до 4 часов, в присутствии "
            "сотрудника) и длительные свидания (до 3 суток, с проживанием на территории "
            "учреждения, как правило, с близкими родственниками). Конкретные нормы "
            "уточняйте по своему режиму у начальника отряда или через бот.\n\n"
            "Если нужна помощь с документами — обратитесь к администрации учреждения."
        ),
    },
    {
        "id": 10,
        "category": "свидания",
        "question": "Кто может прийти ко мне на свидание?",
        "answer": (
            "На свидания допускаются близкие родственники, иные родственники и иные лица — "
            "с разрешения администрации.\n\n"
            "Как организовать:\n"
            "1. Посетитель подаёт заявление о свидании на имя начальника учреждения "
            "с документом, удостоверяющим личность.\n"
            "2. Администрация проверяет основания и назначает дату.\n"
            "3. В назначенный день посетитель приезжает к КПП с документами; запрещённые "
            "предметы при себе иметь нельзя.\n\n"
            "Если нужна помощь с документами — обратитесь к администрации учреждения."
        ),
    },
]


@router.get("/faq")
async def get_faq(_=Depends(verify_api_key)):
    return FAQ_ITEMS


@router.get("/documents/{document_id}/text")
async def get_document_text(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key),
):
    doc = (
        await db.execute(select(Document).where(Document.external_id == document_id))
    ).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    version = (
        await db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == doc.id)
            .order_by(DocumentVersion.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail=f"No versions for document {document_id}")

    text = version.normalized_text or ""
    return {
        "title": doc.title_ru,
        "version_date": version.version_date,
        "text": text,
        "total_chars": len(text),
    }


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
