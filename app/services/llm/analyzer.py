import asyncio
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from app.services.llm.client import chat as llm_chat
from sqlalchemy import select
from app.core.database import async_session_maker
from app.models.document import Document, DocumentVersion, DocumentDiff

PROMPT_TEMPLATE = """Ты юридический помощник. Отвечай ТОЛЬКО на русском языке. Запрещено использовать китайский, английский или любой другой язык кроме русского.

Документ: {doc_title}
Период: {date_old} -> {date_new}

Добавлено в закон:
{added_text}

Удалено из закона:
{removed_text}

Ответь только JSON на русском языке:
{{"summary_ru": "что изменилось (2-3 предложения по-русски)", "affects_sentence": false, "affects_rights": false, "category": "нейтральное", "importance": "низкая", "explanation_ru": "что это значит для осуждённого (по-русски)"}}"""

def build_prompt(doc_title, date_old, date_new, diff_data):
    added = "\n".join(f"+ {t}" for t in diff_data.get("added", [])[:5]) or "нет"
    removed = "\n".join(f"- {t}" for t in diff_data.get("removed", [])[:5]) or "нет"
    return PROMPT_TEMPLATE.format(
        doc_title=doc_title,
        date_old=date_old,
        date_new=date_new,
        added_text=added,
        removed_text=removed,
    )

async def analyze_diff(diff_record, doc_title, date_old, date_new):
    diff_data = json.loads(diff_record.diff_json)
    if diff_data.get("total_changes", 0) < 2:
        return None
    prompt = build_prompt(doc_title, date_old, date_new, diff_data)
    try:
        raw = (await asyncio.to_thread(llm_chat, prompt)).strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"   Ошибка LLM: {e}")
        return None

async def main():
    async with async_session_maker() as session:
        diffs_result = await session.execute(select(DocumentDiff).where(DocumentDiff.ai_summary_ru == None))
        diffs = diffs_result.scalars().all()
        print(f"Записей для анализа: {len(diffs)}")

        for diff in diffs:
            v_old = await session.get(DocumentVersion, diff.version_old_id)
            v_new = await session.get(DocumentVersion, diff.version_new_id)
            doc = await session.get(Document, diff.document_id)

            print(f"\nАнализируем: {doc.title_ru} | {v_old.version_date} -> {v_new.version_date}")

            result = await analyze_diff(diff, doc.title_ru, v_old.version_date, v_new.version_date)

            if result:
                diff.ai_summary_ru = result.get("summary_ru", "")
                diff.affects_sentence = result.get("affects_sentence", False)
                print(f"   Резюме: {result.get('summary_ru', '')[:100]}")
                await session.commit()
            else:
                print(f"   Пропущено")

    print("\nАнализ завершён!")

asyncio.run(main())