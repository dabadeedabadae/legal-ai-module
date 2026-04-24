import asyncio
import os
import time
from dotenv import load_dotenv
from app.services.llm.client import is_kazakh
load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "groq")

OPENAI_KEYS = [
    os.getenv("OPENAI_API_KEY"),
    os.getenv("OPENAI_API_KEY_2") or os.getenv("OPENAI_API_KEY"),
    os.getenv("OPENAI_API_KEY_3") or os.getenv("OPENAI_API_KEY"),
]

GROQ_KEYS = [
    os.getenv("GROQ_API_KEY"),
    os.getenv("GROQ_API_KEY_2") or os.getenv("GROQ_API_KEY"),
    os.getenv("GROQ_API_KEY_3") or os.getenv("GROQ_API_KEY"),
]

OPENAI_MODEL = "gpt-4o-mini"
GROQ_MODEL = "llama-3.3-70b-versatile"

def call_llm(key_index: int, prompt: str, system: str) -> tuple[str, int, float]:
    start = time.time()
    if PROVIDER == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_KEYS[key_index])
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=500,
        )
        text = response.choices[0].message.content
        tokens = response.usage.total_tokens
    else:
        from groq import Groq
        client = Groq(api_key=GROQ_KEYS[key_index])
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=500,
        )
        text = response.choices[0].message.content
        tokens = response.usage.total_tokens

    elapsed = round(time.time() - start, 2)
    return text, tokens, elapsed

CLASSIFIER_SYSTEM = """Ты классификатор юридических вопросов для системы УИС РК.
Определи категорию вопроса. Отвечай ТОЛЬКО одним словом из списка:
удо, права, жалоба, амнистия, адвокат, медицина, свидание, перевод, общее
Отвечай ТОЛЬКО на русском языке. Никакого китайского, английского или других языков."""

SEARCHER_SYSTEM = """Ты помощник по поиску в законодательстве РК.
На основе категории вопроса назови ключевые статьи.
Формат: "Статья X УК/УИК РК — название". Перечисли 2-3 статьи.
Отвечай ТОЛЬКО на русском языке. Никакого китайского, английского или других языков."""

LAWYER_SYSTEM = """Ты опытный юрист специализирующийся на уголовном праве РК.
Дай точный юридический ответ со ссылкой на конкретную статью.
Не придумывай нормы. Всегда указывай номер статьи.
Если вопрос задан на казахском языке — отвечай на казахском. Если на русском — отвечай на русском. Никогда не используй другие языки."""

SIMPLIFIER_SYSTEM = """Ты помощник который объясняет юридические тексты простым языком.
Перепиши ответ так чтобы его понял человек без образования.
Сохрани все важные детали и номера статей.
Максимум 4-5 предложений.
Если вопрос задан на казахском языке — отвечай на казахском. Если на русском — отвечай на русском. Никогда не используй другие языки."""

async def run_multi_agent(question: str, context: str, emit_event=None) -> dict:
    result = {
        "question": question,
        "agents": [],
        "final_answer": "",
        "total_tokens": 0,
        "total_time": 0,
    }
    start_total = time.time()

    lang = "kk" if is_kazakh(question) else "ru"
    lang_directive = (
        "Язык пользователя: казахский (kk). Отвечай ТОЛЬКО на казахском."
        if lang == "kk"
        else "Язык пользователя: русский (ru). Отвечай ТОЛЬКО на русском."
    )

    def emit(agent_name, status, data=None):
        if emit_event:
            emit_event({"agent": agent_name, "status": status, "data": data or {}})

    # Агент 1: Классификатор
    emit("classifier", "started")
    category, t1, s1 = await asyncio.to_thread(call_llm, 0, f"Вопрос: {question}", CLASSIFIER_SYSTEM)
    category = category.strip().lower()
    emit("classifier", "done", {"category": category, "tokens": t1, "time": s1})
    result["agents"].append({"name": "Классификатор", "output": category, "tokens": t1, "time": s1})

    # Агент 2: Поисковик
    emit("searcher", "started")
    articles, t2, s2 = await asyncio.to_thread(call_llm, 1, f"Категория: {category}\nВопрос: {question}\nКонтекст: {context[:500]}", SEARCHER_SYSTEM)
    emit("searcher", "done", {"articles": articles, "tokens": t2, "time": s2})
    result["agents"].append({"name": "Поисковик", "output": articles, "tokens": t2, "time": s2})

    # Агент 3: Юрист
    emit("lawyer", "started")
    legal_answer, t3, s3 = await asyncio.to_thread(call_llm, 1, f"{lang_directive}\nВопрос: {question}\nНайденные статьи: {articles}\nТекст закона: {context[:1000]}", LAWYER_SYSTEM)
    emit("lawyer", "done", {"answer": legal_answer, "tokens": t3, "time": s3})
    result["agents"].append({"name": "Юрист", "output": legal_answer, "tokens": t3, "time": s3})

    # Агент 4: Упроститель
    emit("simplifier", "started")
    simple_answer, t4, s4 = await asyncio.to_thread(call_llm, 0, f"{lang_directive}\nЮридический ответ: {legal_answer}", SIMPLIFIER_SYSTEM)
    emit("simplifier", "done", {"answer": simple_answer, "tokens": t4, "time": s4})
    result["agents"].append({"name": "Упроститель", "output": simple_answer, "tokens": t4, "time": s4})

    result["final_answer"] = simple_answer
    result["total_tokens"] = t1 + t2 + t3 + t4
    result["total_time"] = round(time.time() - start_total, 2)
    return result
