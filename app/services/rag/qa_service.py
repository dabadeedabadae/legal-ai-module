import asyncio
import ollama
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from app.models.document import Document, DocumentVersion
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def search_relevant_articles(session: AsyncSession, question: str, limit: int = 5) -> list[dict]:
    """Ищем релевантные фрагменты текста по вопросу"""
    
    # Берём ключевые слова из вопроса (убираем стоп-слова)
    keywords = [w for w in question.lower().split() 
                if len(w) > 3 and w not in {"могу", "может", "можно", "если", "когда", "какой", "какие", "это", "что", "как"}]
    
    results = []
    
    # Для каждого ключевого слова ищем в последних версиях документов
    for doc_id in [1, 2]:  # УК РК и УИК РК
        # Берём последнюю версию документа
        version_result = await session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == doc_id)
            .order_by(DocumentVersion.id.desc())
            .limit(1)
        )
        version = version_result.scalar_one_or_none()
        if not version:
            continue
            
        doc = await session.get(Document, doc_id)
        text_content = version.normalized_text
        
        # Разбиваем текст на абзацы и ищем релевантные
        paragraphs = [p.strip() for p in text_content.split('.') if len(p.strip()) > 50]
        
        for keyword in keywords[:3]:  # берём топ 3 ключевых слова
            for para in paragraphs:
                if keyword in para.lower():
                    results.append({
                        "doc_title": doc.title_ru,
                        "text": para[:500],
                        "keyword": keyword,
                    })
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break
    
    # Убираем дубликаты
    seen = set()
    unique_results = []
    for r in results:
        if r["text"] not in seen:
            seen.add(r["text"])
            unique_results.append(r)
    
    return unique_results[:limit]

async def answer_question(question: str) -> str:
    """Основная функция RAG — отвечаем на вопрос осуждённого"""
    
    async with AsyncSessionLocal() as session:
        # 1. Ищем релевантные статьи
        articles = await search_relevant_articles(session, question)
        
        if not articles:
            context = "Релевантные статьи не найдены в базе данных."
        else:
            context = "\n\n".join([
                f"Из {a['doc_title']}:\n{a['text']}"
                for a in articles
            ])
    
    # 2. Формируем промпт
    prompt = f"""Ты юридический помощник для осуждённых в учреждениях УИС Республики Казахстан.
Отвечай ТОЛЬКО на русском языке. Простым и понятным языком.

Вопрос осуждённого: {question}

Relevant статьи из законодательства РК:
{context}

Ответь на вопрос основываясь на приведённых статьях. 
Если информации недостаточно — скажи об этом честно.
Не придумывай статьи которых нет в контексте.
Ответ должен быть понятен человеку без юридического образования."""

    # 3. Отправляем в LLM
    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1}
    )
    
    return response["message"]["content"]

async def main():
    # Тестируем с реальными вопросами осуждённых
    questions = [
        "Когда я могу подать на условно-досрочное освобождение?",
        "Какие у меня права как у осуждённого?",
        "Что такое незаконный оборот наркотиков по казахстанскому закону?",
    ]
    
    for q in questions:
        print(f"\n{'='*60}")
        print(f"❓ Вопрос: {q}")
        print(f"{'='*60}")
        answer = await answer_question(q)
        print(f"💬 Ответ:\n{answer}")
        print()



