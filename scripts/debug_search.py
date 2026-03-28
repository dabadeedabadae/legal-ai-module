import asyncio
from app.services.rag.qa_service import search_relevant_articles, extract_keywords
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os
load_dotenv()

engine = create_async_engine(os.getenv("DATABASE_URL"), echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def test():
    questions = [
        "Когда я могу подать на УДО?",
        "Какие у меня права как у осуждённого?",
        "Как подать жалобу на администрацию?",
    ]
    async with AsyncSessionLocal() as session:
        for q in questions:
            print(f"\n{'='*60}")
            print(f"Вопрос: {q}")
            print(f"Ключевые слова: {extract_keywords(q)}")
            results = await search_relevant_articles(session, q)
            print(f"Найдено фрагментов: {len(results)}")
            for i, r in enumerate(results[:3]):
                print(f"\n[{i+1}] score={r['score']} | {r['doc_title']}")
                print(r['text'][:400])

asyncio.run(test())