import asyncio
from app.services.rag.qa_service import search_relevant_articles, extract_keywords
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os
load_dotenv()

# Тест ключевых слов
print("Тест извлечения ключевых слов:")
print("УДО ->", extract_keywords("Когда я могу подать на УДО?"))
print("права ->", extract_keywords("Какие у меня права?"))
print("амнистия ->", extract_keywords("Могу ли я получить амнистию?"))