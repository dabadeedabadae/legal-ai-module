import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from app.services.llm.client import chat as llm_chat, is_kazakh
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import async_session_maker
from app.models.document import Document, DocumentVersion

LEGAL_SYNONYMS = {
    "удо": ["условно-досрочное", "досрочное освобождение", "условно-досрочного"],
    "права": ["право осужденного", "права осужденных", "вправе", "имеет право"],
    "жалоба": ["обжаловать", "обращение осужденного", "жалобу"],
    "адвокат": ["защитник", "юридическая помощь"],
    "амнистия": ["акт об амнистии", "амнистии", "помилование"],
    "свидание": ["свидания", "посещение родственников"],
    "медицина": ["медицинская помощь", "медицинское обслуживание"],
}

STOP_WORDS = {"могу", "может", "можно", "если", "когда", "какой", "какие",
              "это", "что", "как", "для", "при", "или", "также", "меня",
              "мне", "моя", "мой", "себя", "свой", "свою", "буду", "ли"}

LEGAL_KEYWORDS = {
    # Из категорий
    "удо", "условно-досрочн", "досрочн",
    "права", "право", "обязанност", "обязан", "вправе",
    "амнист", "помилован",
    "жалоб", "обжалова", "апелляц", "обращени",
    "адвокат", "защитник", "юрист",
    "свидани", "посещени", "родственник",
    "медицин", "врач", "лечени", "больниц",
    "перевод", "этапирова",
    # Общие правовые термины
    "закон", "кодекс", "статья", "норма", "суд", "приговор",
    "осуждён", "осужден", "осуждённ", "заключён", "заключен",
    "наказани", "срок", "лишени", "свободы", "колони", "тюрьм",
    "уголовн", "уик", "прокурор", "следовател", "дознани",
    "обвиняем", "подозреваем", "задержан", "арест", "конвой",
    "учреждени", "администраци", "инспекци", "надзор",
    "освобожден", "освобождён", "этап", "режим",
    # Казахские эквиваленты
    "бап", "заң", "құқық", "сот", "мерзім", "босату", "босат",
    "шартты", "шағым", "тұтқын", "үкім",
    "сотталған", "соттал", "түрме", "жаза",
}

def is_legal_question(question: str) -> bool:
    if is_kazakh(question):
        return True
    q = question.lower()
    return any(kw in q for kw in LEGAL_KEYWORDS)

QUESTION_CATEGORIES = {
    "удо": ["удо", "условно-досрочн", "досрочн"],
    "права": ["права", "право", "обязанност", "обязан", "вправе"],
    "амнистия": ["амнист", "помилован"],
    "жалоба": ["жалоб", "обжалова", "апелляц", "обращени"],
    "адвокат": ["адвокат", "защитник", "юрист"],
    "свидание": ["свидани", "посещени", "родственник"],
    "медицина": ["медицин", "врач", "лечени", "больниц"],
    "перевод": ["перевод", "этапирова", "другое учреждени"],
}

# Ключевые статьи для каждой категории — ищем их принудительно
KEY_ARTICLES = {
    "удо": ["фактического отбытия осужденным", "одной трети срока наказания", "одной второй срока", "двух третей срока"],
    "права": ["осужденные имеют право на", "осужденный имеет право", "основные права осужденных", "осужденные вправе обращаться"],
    "жалоба": ["обращения осужденных по поводу решений", "жалобы осужденных", "направляются через администрацию"],
    "амнистия": ["акт об амнистии", "амнистии в связи", "не распространяется на лиц"],
}

def normalize_word(word: str) -> str:
    for ending in ["ию", "ии", "ия", "ой", "ом", "ого", "ому", "ых", "ым", "ами", "ану", "ану"]:
        if word.endswith(ending) and len(word) > len(ending) + 2:
            return word[:-len(ending)]
    return word

def classify_question(question: str) -> str:
    q_lower = question.lower()
    for category, keywords in QUESTION_CATEGORIES.items():
        for kw in keywords:
            if kw in q_lower:
                return category
    return "общее"

def extract_keywords(question: str) -> list[str]:
    words = [w.lower().strip("?.,!()") for w in question.split()]
    keywords = [w for w in words if len(w) >= 2 and w not in STOP_WORDS]
    expanded = list(keywords)
    for word in keywords:
        norm_word = normalize_word(word)
        for key, synonyms in LEGAL_SYNONYMS.items():
            norm_key = normalize_word(key)
            if norm_key in norm_word or norm_word in norm_key:
                expanded.extend(synonyms)
                break
    return list(set(expanded))[:15]

async def search_relevant_articles(session: AsyncSession, question: str, limit: int = 6) -> list[dict]:
    keywords = extract_keywords(question)
    # Убираем короткие и общие слова которые дают мусор
    keywords = [k for k in keywords if len(k) > 3 and k not in {"подать", "получить", "иметь", "нужно"}]
    results = []

    # Получаем ID и названия нужных документов из БД (не хардкодим [1, 2])
    id_result = await session.execute(
        select(Document.id, Document.title_ru).where(
            Document.external_id.in_(["K1400000226", "K1400000234"])
        )
    )
    doc_rows = id_result.all()  # list of Row(id, title_ru)

    for doc_id, doc_title in doc_rows:
        version_result = await session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == doc_id)
            .order_by(DocumentVersion.id.desc())
            .limit(1)
        )
        version = version_result.scalar_one_or_none()
        if not version:
            continue

        text_content = version.normalized_text
        sentences = [p.strip() for p in text_content.split(". ") if len(p.strip()) > 80]

        scored = []
        for sentence in sentences:
            sentence_lower = sentence.lower()
            score = sum(1 for kw in keywords if kw in sentence_lower)
            # Штраф за мусорные совпадения
            if any(noise in sentence_lower for noise in ["наркотических средств", "психотропных веществ", "таможенн"]):
                if not any(kw in ["наркотики", "наркотических"] for kw in keywords):
                    score = 0
            if score > 0:
                scored.append((score, sentence[:600], doc_title))

        scored.sort(reverse=True)
        for score, text, title in scored[:3]:
            results.append({
                "doc_title": title,
                "text": text,
                "score": score,
            })

    seen = set()
    unique = []
    for r in sorted(results, key=lambda x: x["score"], reverse=True):
        if r["text"] not in seen:
            seen.add(r["text"])
            unique.append(r)

    # Принудительно ищем ключевые статьи для категории (один раз, вне цикла дедупликации)
    category = classify_question(question)
    if category in KEY_ARTICLES:
        for doc_id, doc_title in doc_rows:
            version_result = await session.execute(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == doc_id)
                .order_by(DocumentVersion.id.desc())
                .limit(1)
            )
            version = version_result.scalar_one_or_none()
            if not version:
                continue
            sentences = [p.strip() for p in version.normalized_text.split(". ") if len(p.strip()) > 80]
            for marker in KEY_ARTICLES[category]:
                for sentence in sentences:
                    if marker.lower() in sentence.lower() and sentence not in seen:
                        seen.add(sentence)
                        unique.insert(0, {
                            "doc_title": doc_title,
                            "text": sentence[:600],
                            "score": 10,
                        })
                        break

    return unique[:limit]

SYSTEM_PROMPT = """Ты — юридический помощник для осуждённых в учреждениях УИС Республики Казахстан.

ГЛАВНОЕ ПРАВИЛО — ОТВЕЧАЙ НА ТОТ ВОПРОС, КОТОРЫЙ ЗАДАН.
Не подменяй тему. Спрашивают про перевод — отвечай про перевод; про права — про права; про УДО — про УДО. Не уходи в смежные сюжеты, даже если в найденных статьях есть «более интересные» нормы.

ИСТОЧНИКИ И ССЫЛКИ НА СТАТЬИ:
1. Используй ТОЛЬКО предоставленные статьи. Знания из памяти запрещены.
2. Цитируй номера статей (например, «ст. 72 УК РК», «ст. 169 УИК РК») ТОЛЬКО если они явно присутствуют в переданном контексте. Никогда не выдумывай номера, формулировки или сроки.
3. ЗАПРЕЩЕНО писать «Основание: статьи УК и УИК РК» — указывай конкретный номер или ничего.
4. Если нужной нормы в контексте нет — честно скажи: «В переданных нормах ответа на этот вопрос нет», не маскируй пустоту общими словами.
5. Если в контексте есть дроби срока, перечень прав или порядок подачи — обязательно включи их.

СТРУКТУРА ОТВЕТА (единый текст, без markdown-заголовков и эмодзи):
1. КОРОТКИЙ ПРЯМОЙ ОТВЕТ — 1–2 предложения, по сути вопроса.
   - Вопрос про право: «Да, право есть…» / «Нет, такого права нет» / «Право возникает при условии…» + минимальное основание.
   - Вопрос про процедуру: одно предложение — возможно ли это и при каких условиях.
   - Вопрос про сроки/условия: главная цифра/условие сразу.
2. ДЕТАЛИ:
   - Если вопрос ПРО ПРОЦЕДУРУ — дай пошаговую инструкцию:
       «1. Напишите заявление на имя…
        2. Подайте его через…
        3. Дождитесь решения в течение … дней.»
     Каждый шаг конкретный: куда подаёшь, в какой форме, кому адресуешь, со ссылкой на статью (если она есть в контексте).
   - Если вопрос ПРО ПРАВА — перечисли сами права (3–5 пунктов, если они есть в источнике) и укажи статью-основание.
   - Если вопрос ПРО СРОКИ/УСЛОВИЯ (УДО, амнистия и т. п.) — выведи все дроби и условия из контекста.
3. ФИНАЛЬНАЯ СТРОКА — добавь дословно (на языке ответа):
   - русский: «Если нужна помощь с документами — обратитесь к администрации учреждения.»
   - казахский: «Құжаттармен көмек қажет болса — мекеме әкімшілігіне жүгініңіз.»

ЯЗЫК:
Если вопрос на казахском — отвечай ТОЛЬКО на казахском. Если на русском — ТОЛЬКО на русском. Другие языки запрещены.

ПРОВЕРКА ПЕРЕД ОТПРАВКОЙ:
□ Первая фраза отвечает именно на заданный вопрос (а не на смежную тему)?
□ Все номера статей взяты из контекста (а не придуманы)?
□ Для процедурного вопроса есть явные шаги «1., 2., 3.»?
□ В конце стоит обязательная финальная строка?"""

async def answer_question(
    question: str,
    *,
    source: str = "api",
    ip_address: str | None = None,
) -> str:
    if not is_legal_question(question):
        return (
            "Я отвечаю только на вопросы по правовым нормам — "
            "уголовному и уголовно-исполнительному законодательству Республики Казахстан. "
            "Спросите, например, об УДО, правах осуждённых, порядке подачи жалобы или условиях отбывания наказания."
        )

    category = classify_question(question)
    lang = "kk" if is_kazakh(question) else "ru"

    async with async_session_maker() as session:
        articles = await search_relevant_articles(session, question)

        if not articles or max(a["score"] for a in articles) < 2:
            return (
                "**Краткий ответ:** Я не нашёл достаточно точной нормы для уверенного ответа.\n\n"
                "**Что сделать:** Для получения точного ответа обратитесь к администрации учреждения "
                "или дежурному юристу. Уточните статью УК по которой осуждены, "
                "категорию преступления и срок наказания."
            )

        context = "\n\n".join([
            f"[{a['doc_title']}]:\n{a['text']}"
            for a in articles
        ])

    lang_directive = (
        "Язык пользователя: казахский (kk). Отвечай ТОЛЬКО на казахском языке."
        if lang == "kk"
        else "Язык пользователя: русский (ru). Отвечай ТОЛЬКО на русском языке."
    )

    prompt = f"""{SYSTEM_PROMPT}

{lang_directive}

Категория вопроса: {category}
Вопрос осуждённого: {question}

Статьи из законодательства РК (используй ТОЛЬКО эти источники):
{context}

Ответь строго по формату. Если источников недостаточно — честно скажи об этом."""

    answer = await asyncio.to_thread(llm_chat, prompt)

    try:
        from app.core.db_query_log import save_query_log
        await save_query_log(
            question=question,
            answer=answer,
            agent_logs=[{
                "name": "qa_service",
                "category": category,
                "articles_count": len(articles),
                "output": answer,
            }],
            language=lang,
            source=source,
            ip_address=ip_address,
        )
    except Exception:
        pass

    return answer

async def main():
    questions = [
        "Когда я могу подать на УДО?",
        "Какие у меня права как у осуждённого?",
        "Могу ли я получить амнистию?",
        "Как подать жалобу на администрацию?",
    ]
    for q in questions:
        print(f"\n{'='*60}")
        print(f"Вопрос: {q}")
        answer = await answer_question(q)
        print(f"Ответ:\n{answer}")

if __name__ == "__main__":
    asyncio.run(main())