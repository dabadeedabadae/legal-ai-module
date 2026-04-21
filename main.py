from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.api.routes import router, verify_api_key
from app.services.rag.multi_agent import run_multi_agent
from app.core.database import async_session_maker
from app.core.config import settings
import json
import os
import asyncio
import uuid
from datetime import datetime
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

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# История запросов в памяти
query_history: list[dict] = []

@app.get("/", include_in_schema=False)
async def ui():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/dashboard")
async def dashboard():
    return FileResponse(os.path.join(static_dir, "dashboard.html"))

@app.get("/admin")
async def admin():
    return FileResponse(os.path.join(static_dir, "admin.html"))

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
async def get_laws(_=Depends(verify_api_key)):
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
async def get_queries(_=Depends(verify_api_key)):
    return JSONResponse([
        {
            "id": q["id"],
            "question": q["question"],
            "final_answer": q["result"]["final_answer"],
            "total_tokens": q["result"]["total_tokens"],
            "total_time": q["result"]["total_time"],
            "created_at": q["created_at"],
            "db_available": q["db_available"],
        }
        for q in reversed(query_history)
    ])

@app.get("/api/admin/queries/{query_id}")
async def get_query_detail(query_id: str, _=Depends(verify_api_key)):
    for q in query_history:
        if q["id"] == query_id:
            return JSONResponse(q)
    return JSONResponse({"error": "не найдено"}, status_code=404)

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

            query_id = str(uuid.uuid4())
            db_available = True

            # Ищем статьи в БД (необязательно — агенты работают и без контекста)
            context = ""
            try:
                from app.services.rag.qa_service import search_relevant_articles
                async with async_session_maker() as session:
                    articles = await search_relevant_articles(session, question)
                    context = "\n\n".join([a["text"] for a in articles])
            except Exception as db_err:
                db_available = False
                await websocket.send_json({"agent": "system", "status": "warning", "data": {"message": f"БД недоступна. Агенты работают без контекста."}})

            # Буфер событий для отправки через WebSocket
            event_queue: asyncio.Queue = asyncio.Queue()

            def emit(event):
                event_queue.put_nowait(event)

            # run_multi_agent — async, все LLM-вызовы внутри идут через asyncio.to_thread
            agent_task = asyncio.create_task(run_multi_agent(question, context, emit))

            # Отправляем события пока агенты работают
            while not agent_task.done():
                try:
                    event = event_queue.get_nowait()
                    await websocket.send_json(event)
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.05)

            # Сливаем оставшиеся события
            while not event_queue.empty():
                event = event_queue.get_nowait()
                await websocket.send_json(event)

            result = await agent_task

            # Сохраняем в историю
            query_history.append({
                "id": query_id,
                "question": question,
                "result": result,
                "db_available": db_available,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            # Держим не более 500 записей
            if len(query_history) > 500:
                query_history.pop(0)

            await websocket.send_json({"type": "complete", "result": result, "query_id": query_id})

    except WebSocketDisconnect:
        pass
