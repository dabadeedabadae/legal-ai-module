import asyncio
import json
import ollama
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from app.models.document import Document, DocumentVersion, DocumentDiff
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

PROMPT_TEMPLATE = """Ты юридический помощник. Отвечай ТОЛЬКО на русском языке. Запрещено использовать китайский, английский или любой другой язык кроме русского.

Документ: {doc_title}
Период: {date_old} → {date_new}

Добавлено в закон:
{added_text}

Удалено из закона:
{removed_text}

Ответь только JSON на русском языке:
{{"summary_ru": "что изменилось (2-3 предложения по-русски)", "affects_sentence": false, "affects_rights": false, "category": "нейтральное", "importance": "низкая", "explanation_ru": "что это значит для осуждённого (по-русски)"}}"""

def build_prompt(doc_title: str, date_old: str, date_new: str, diff_data: dict) -> str:
    added = "\n".join(f"+ {t}" for t in diff_data.get("added", [])[:5]) or "нет"
    removed = "\n".join(f"- {t}" for t in diff_data.get("removed", [])[:5]) or "нет"
    return PROMPT_TEMPLATE.format(
        doc_title=doc_title,
        date_old=date_old,
        date_new=date_new,
        added_text=added,
        removed_text=removed,
    )

async def analyze_diff(diff_record: DocumentDiff, doc_title: str,
                       date_old: str, date_new: str) -> dict | None:
    diff_data = json.loads(diff_record.diff_json)

    # Пропускаем если изменений почти нет
    if diff_data.get("total_changes", 0) < 2:
        return None

    prompt = build_prompt(doc_title, date_old, date_new, diff_data)

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}  # низкая температура для точности
        )
        raw = response["message"]["content"].strip()

        # Чистим от markdown если модель всё же добавила
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)

    except Exception as e:
        print(f"   ⚠️  Ошибка LLM: {e}")
        return None

async def main():
    async with AsyncSessionLocal() as session:

        # Берём все diff записи без анализа
        diffs_result = await session.execute(
            select(DocumentDiff, Document, DocumentVersion, DocumentVersion)
            .join(Document, DocumentDiff.document_id == Document.id)
            .join(DocumentVersion, DocumentDiff.version_old_id == DocumentVersion.id)
            .filter(DocumentDiff.ai_summary_ru == None)
        )

        # Проще сделать отдельными запросами
        diffs_result = await session.execute(select(DocumentDiff).where(DocumentDiff.ai_summary_ru == None))
        diffs = diffs_result.scalars().all()
        print(f"Записей для анализа: {len(diffs)}")

        for diff in diffs:
            # Получаем версии
            v_old = await session.get(DocumentVersion, diff.version_old_id)
            v_new = await session.get(DocumentVersion, diff.version_new_id)
            doc = await session.get(Document, diff.document_id)

            print(f"\n🤖 Анализируем: {doc.title_ru}")
            print(f"   {v_old.version_date} → {v_new.version_date}")

            result = await analyze_diff(diff, doc.title_ru, v_old.version_date, v_new.version_date)

            if result:
                diff.ai_summary_ru = result.get("summary_ru", "")
                diff.affects_sentence = result.get("affects_sentence", False)

                print(f"   📝 Резюме: {result.get('summary_ru', '')}")
                print(f"   ⚖️  Влияет на срок: {result.get('affects_sentence')}")
                print(f"   📊 Важность: {result.get('importance')}")
                print(f"   💬 Для осуждённого: {result.get('explanation_ru', '')}")

                await session.commit()
            else:
                print(f"   ⏭️  Пропущено (мало изменений)")

    print("\n✅ Анализ завершён!")

asyncio.run(main())
