import asyncio
from app.services.rag.qa_service import search_relevant_articles
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os
load_dotenv()

engine = create_async_engine(os.getenv("DATABASE_URL"), echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def test():
    async with AsyncSessionLocal() as session:
        print("=== УДО ===")
        results = await search_relevant_articles(session, "Когда я могу подать на УДО?")
        for r in results[:3]:
            print(f"\nscore={r['score']} | {r['doc_title']}")
            print(r['text'][:500])
            print("---")

asyncio.run(test())