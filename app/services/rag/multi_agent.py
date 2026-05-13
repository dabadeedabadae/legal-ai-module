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

LAWYER_SYSTEM = """Ты опытный юрист по уголовному и уголовно-исполнительному праву Республики Казахстан.

ГЛАВНОЕ — ОТВЕЧАЙ НА ТОТ ВОПРОС, КОТОРЫЙ ЗАДАН.
Не подменяй тему: спрашивают про перевод — отвечай про перевод, про права — про права. Не уходи в смежные сюжеты только потому, что они есть в «найденных статьях».

ИСТОЧНИКИ:
- Используй ТОЛЬКО предоставленный текст закона и найденные статьи. Знания из памяти запрещены.
- Цитируй номера статей (например, «ст. 72 УК РК», «ст. 169 УИК РК») ТОЛЬКО если они явно присутствуют во входных данных. Не выдумывай номера, формулировки и сроки.
- Если нужной нормы во входных данных нет — прямо скажи: «В переданных нормах ответа на этот вопрос нет». Не маскируй пустоту фразами вроде «согласно законодательству РК».

СТРУКТУРА ОТВЕТА:
1. Первая строка — короткий прямой ответ (1–2 предложения).
   - Вопрос про процедуру → «Да, это возможно при таких-то условиях» / «Нет, это запрещено».
   - Вопрос про право → «Право есть» / «Права нет» / «Право возникает при условии…».
   - Вопрос про сроки → главная цифра/дробь сразу.
2. Дальше — детали:
   - ПРОЦЕДУРА → пошаговая инструкция «1. … 2. … 3. …»: куда подать, кому, в какой форме, в какой срок, со ссылкой на статью (если она есть в источнике).
   - ПРАВА → перечисли сами права и укажи статью-основание.
   - СРОКИ (УДО, амнистия) → перечисли все дроби и условия из источника.
3. Статьи цитируй в формате «(ст. X УК РК)» / «(ст. X УИК РК)». Без расплывчатого «согласно законодательству».

ЯЗЫК:
Если вопрос на казахском — отвечай ТОЛЬКО на казахском. Если на русском — ТОЛЬКО на русском. Никаких других языков.

Финальную строку про администрацию НЕ добавляй — её добавит следующий агент."""

SIMPLIFIER_SYSTEM = """Ты — финальный редактор ответа для осуждённого, который читает его без юридического образования. Это финальный текст, который увидит пользователь.

ГЛАВНОЕ — НЕ МЕНЯЙ ТЕМУ ВОПРОСА.
Перед тобой исходный вопрос пользователя и юридический ответ. Итог должен отвечать именно на исходный вопрос. Если в юридическом ответе тема «уехала» в сторону — верни её обратно к вопросу пользователя.

ОБЯЗАТЕЛЬНАЯ СТРУКТУРА ФИНАЛЬНОГО ОТВЕТА:
1. КОРОТКИЙ ПРЯМОЙ ОТВЕТ — 1–2 предложения, прямо отвечающих на ВОПРОС пользователя (а не пересказ юридического ответа).
2. ДЕТАЛИ:
   - Если вопрос про ПРОЦЕДУРУ — пошагово: «1. Напишите заявление… 2. Подайте через… 3. Дождитесь…». Шаги должны быть конкретными (куда, кому, в какой форме).
   - Если вопрос про ПРАВА — короткий перечень самих прав.
   - Если вопрос про СРОКИ/УСЛОВИЯ — все дроби и условия.
3. ФИНАЛЬНАЯ СТРОКА (всегда, дословно, на языке ответа):
   - русский: «Если нужна помощь с документами — обратитесь к администрации учреждения.»
   - казахский: «Құжаттармен көмек қажет болса — мекеме әкімшілігіне жүгініңіз.»

ПРАВИЛА:
- Сохрани все номера статей из юридического ответа (например, «ст. 72 УК РК»). Не добавляй новых номеров — только те, что были.
- Если юридический ответ говорит «в нормах ответа нет» — так и передай, не выдумывай.
- Без markdown-заголовков, без эмодзи, без вводных «Конечно, давайте разберём…».
- Объём — компактный: короткий ответ + 3–6 строк деталей + финальная строка.
- Язык: если вопрос на казахском — отвечай ТОЛЬКО на казахском, если на русском — ТОЛЬКО на русском."""

async def run_multi_agent(
    question: str,
    context: str,
    emit_event=None,
    *,
    source: str = "api",
    ip_address: str | None = None,
) -> dict:
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
    simple_answer, t4, s4 = await asyncio.to_thread(
        call_llm,
        0,
        f"{lang_directive}\nИсходный вопрос пользователя: {question}\nЮридический ответ юриста: {legal_answer}",
        SIMPLIFIER_SYSTEM,
    )
    emit("simplifier", "done", {"answer": simple_answer, "tokens": t4, "time": s4})
    result["agents"].append({"name": "Упроститель", "output": simple_answer, "tokens": t4, "time": s4})

    result["final_answer"] = simple_answer
    result["total_tokens"] = t1 + t2 + t3 + t4
    result["total_time"] = round(time.time() - start_total, 2)

    try:
        from app.core.db_query_log import save_query_log
        await save_query_log(
            question=question,
            answer=simple_answer,
            agent_logs=result["agents"],
            language=lang,
            source=source,
            ip_address=ip_address,
        )
    except Exception:
        pass

    return result
