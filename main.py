from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import aliased
from app.api.routes import router, verify_api_key
from app.api.stt_routes import router as stt_router
from app.services.rag.multi_agent import run_multi_agent
from app.core.database import async_session_maker
from app.core.config import settings
from app.core.query_log import save_query, all_queries, get_query
from app.models.document import Document, DocumentVersion, DocumentDiff
import json
import os
import asyncio
from dotenv import load_dotenv
load_dotenv()

if not os.getenv("LARAVEL_API_KEY"):
    raise RuntimeError("LARAVEL_API_KEY не задан в .env")

app = FastAPI(title="Legal AI Module", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(stt_router, prefix="/api/v1")

static_dir = os.path.join(os.path.dirname(__file__), "static")
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

@app.get("/", include_in_schema=False)
async def ui():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/dashboard")
async def dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "active_page": "dashboard"},
    )

@app.get("/admin")
async def admin(request: Request):
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "active_page": "admin"},
    )

@app.get("/history")
async def history_page(request: Request):
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "active_page": "history"},
    )

@app.get("/library")
async def library(request: Request):
    v_old = aliased(DocumentVersion)
    v_new = aliased(DocumentVersion)

    async with async_session_maker() as session:
        docs_result = await session.execute(select(Document).order_by(Document.id))
        docs = docs_result.scalars().all()

        documents = []
        total_diffs = 0
        for doc in docs:
            diffs_result = await session.execute(
                select(DocumentDiff, v_old.version_date, v_new.version_date)
                .join(v_old, DocumentDiff.version_old_id == v_old.id)
                .join(v_new, DocumentDiff.version_new_id == v_new.id)
                .where(DocumentDiff.document_id == doc.id)
                .order_by(v_new.version_date.desc(), DocumentDiff.id.desc())
            )
            diffs = []
            for diff, date_old, date_new in diffs_result.all():
                try:
                    parsed = json.loads(diff.diff_json) if diff.diff_json else {}
                except (ValueError, TypeError):
                    parsed = {}
                diffs.append({
                    "id": diff.id,
                    "date_old": date_old,
                    "date_new": date_new,
                    "ai_summary_ru": (diff.ai_summary_ru or "").strip(),
                    "affects_sentence": bool(diff.affects_sentence),
                    "added": parsed.get("added", []) or [],
                    "removed": parsed.get("removed", []) or [],
                    "added_chars": parsed.get("added_chars", 0),
                    "removed_chars": parsed.get("removed_chars", 0),
                    "total_changes": parsed.get("total_changes", 0),
                    "raw_json": json.dumps(parsed, ensure_ascii=False, indent=2),
                })
            total_diffs += len(diffs)
            documents.append({
                "id": doc.id,
                "title_ru": doc.title_ru,
                "category": doc.category,
                "url": doc.url,
                "diffs": diffs,
            })

    return templates.TemplateResponse(
        "library.html",
        {
            "request": request,
            "active_page": "library",
            "documents": documents,
            "total_diffs": total_diffs,
        },
    )

@app.get("/health")
async def health():
    from sqlalchemy import text
    import redis.asyncio as aioredis

    checks: dict[str, str] = {}

    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks, "version": "0.2.0"}

@app.get("/api/admin/laws")
async def get_laws():
    try:
        from sqlalchemy import select, func
        from app.models.document import Document, DocumentVersion
        async with async_session_maker() as session:
            docs_result = await session.execute(select(Document).order_by(Document.id))
            docs = docs_result.scalars().all()
            result = []
            for doc in docs:
                ver_result = await session.execute(
                    select(DocumentVersion)
                    .where(DocumentVersion.document_id == doc.id)
                    .order_by(DocumentVersion.id.desc())
                    .limit(1)
                )
                ver = ver_result.scalar_one_or_none()
                count_result = await session.execute(
                    select(func.count()).where(DocumentVersion.document_id == doc.id)
                )
                ver_count = count_result.scalar()
                result.append({
                    "id": doc.id,
                    "title": doc.title_ru,
                    "category": doc.category,
                    "url": doc.url,
                    "created_at": doc.created_at.strftime("%Y-%m-%d"),
                    "versions_count": ver_count,
                    "last_version_date": ver.version_date if ver else "—",
                    "last_fetched": ver.fetched_at.strftime("%Y-%m-%d %H:%M") if ver else "—",
                    "char_count": ver.char_count if ver else 0,
                })
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)

@app.get("/api/admin/queries")
async def get_queries():
    return JSONResponse([
        {
            "id": q["id"],
            "question": q["question"],
            "final_answer": q["result"].get("final_answer", ""),
            "total_tokens": q["result"].get("total_tokens", 0),
            "total_time": q["result"].get("total_time", 0),
            "created_at": q.get("created_at", ""),
            "db_available": q.get("db_available", True),
            "source": q.get("source", ""),
            "user_id": q.get("user_id"),
            "error": q.get("error"),
            "agents_count": len(q["result"].get("agents", [])),
        }
        for q in reversed(all_queries())
    ])

@app.get("/api/admin/queries/{query_id}")
async def get_query_detail(query_id: str):
    q = get_query(query_id)
    if not q:
        return JSONResponse({"error": "не найдено"}, status_code=404)
    return JSONResponse(q)

@app.websocket("/ws/ask")
async def websocket_ask(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            question = payload.get("question", "")

            if not question:
                await websocket.send_json({"error": "Вопрос пустой"})
                continue

            db_available = True

            context = ""
            try:
                from app.services.rag.qa_service import search_relevant_articles
                async with async_session_maker() as session:
                    articles = await search_relevant_articles(session, question)
                    context = "\n\n".join([a["text"] for a in articles])
            except Exception:
                db_available = False
                await websocket.send_json({"agent": "system", "status": "warning", "data": {"message": "БД недоступна. Агенты работают без контекста."}})

            event_queue: asyncio.Queue = asyncio.Queue()

            def emit(event):
                event_queue.put_nowait(event)

            agent_task = asyncio.create_task(
                run_multi_agent(
                    question,
                    context,
                    emit,
                    source="ws",
                    ip_address=(websocket.client.host if websocket.client else None),
                )
            )

            while not agent_task.done():
                try:
                    event = event_queue.get_nowait()
                    await websocket.send_json(event)
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.05)

            while not event_queue.empty():
                event = event_queue.get_nowait()
                await websocket.send_json(event)

            try:
                result = await agent_task
            except Exception as exc:
                save_query(
                    question=question,
                    result={"agents": [], "final_answer": "", "total_tokens": 0, "total_time": 0},
                    db_available=db_available,
                    source="ws",
                    error=str(exc),
                )
                await websocket.send_json({"error": str(exc)})
                continue

            query_id = save_query(
                question=question,
                result=result,
                db_available=db_available,
                source="ws",
            )

            await websocket.send_json({"type": "complete", "result": result, "query_id": query_id})

    except WebSocketDisconnect:
        pass
