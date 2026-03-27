import asyncio
import json
from app.services.llm.client import chat as llm_chat
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

PROMPT_TEMPLATE = """РўС‹ СЋСЂРёРґРёС‡РµСЃРєРёР№ РїРѕРјРѕС‰РЅРёРє. РћС‚РІРµС‡Р°Р№ РўРћР›Р¬РљРћ РЅР° СЂСѓСЃСЃРєРѕРј СЏР·С‹РєРµ. Р—Р°РїСЂРµС‰РµРЅРѕ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РєРёС‚Р°Р№СЃРєРёР№, Р°РЅРіР»РёР№СЃРєРёР№ РёР»Рё Р»СЋР±РѕР№ РґСЂСѓРіРѕР№ СЏР·С‹Рє РєСЂРѕРјРµ СЂСѓСЃСЃРєРѕРіРѕ.

Р”РѕРєСѓРјРµРЅС‚: {doc_title}
РџРµСЂРёРѕРґ: {date_old} в†’ {date_new}

Р”РѕР±Р°РІР»РµРЅРѕ РІ Р·Р°РєРѕРЅ:
{added_text}

РЈРґР°Р»РµРЅРѕ РёР· Р·Р°РєРѕРЅР°:
{removed_text}

РћС‚РІРµС‚СЊ С‚РѕР»СЊРєРѕ JSON РЅР° СЂСѓСЃСЃРєРѕРј СЏР·С‹РєРµ:
{{"summary_ru": "С‡С‚Рѕ РёР·РјРµРЅРёР»РѕСЃСЊ (2-3 РїСЂРµРґР»РѕР¶РµРЅРёСЏ РїРѕ-СЂСѓСЃСЃРєРё)", "affects_sentence": false, "affects_rights": false, "category": "РЅРµР№С‚СЂР°Р»СЊРЅРѕРµ", "importance": "РЅРёР·РєР°СЏ", "explanation_ru": "С‡С‚Рѕ СЌС‚Рѕ Р·РЅР°С‡РёС‚ РґР»СЏ РѕСЃСѓР¶РґС‘РЅРЅРѕРіРѕ (РїРѕ-СЂСѓСЃСЃРєРё)"}}"""

def build_prompt(doc_title: str, date_old: str, date_new: str, diff_data: dict) -> str:
    added = "\n".join(f"+ {t}" for t in diff_data.get("added", [])[:5]) or "РЅРµС‚"
    removed = "\n".join(f"- {t}" for t in diff_data.get("removed", [])[:5]) or "РЅРµС‚"
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

    # РџСЂРѕРїСѓСЃРєР°РµРј РµСЃР»Рё РёР·РјРµРЅРµРЅРёР№ РїРѕС‡С‚Рё РЅРµС‚
    if diff_data.get("total_changes", 0) < 2:
        return None

    prompt = build_prompt(doc_title, date_old, date_new, diff_data)

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}  # РЅРёР·РєР°СЏ С‚РµРјРїРµСЂР°С‚СѓСЂР° РґР»СЏ С‚РѕС‡РЅРѕСЃС‚Рё
        )
        raw = response["message"]["content"].strip()

        # Р§РёСЃС‚РёРј РѕС‚ markdown РµСЃР»Рё РјРѕРґРµР»СЊ РІСЃС‘ Р¶Рµ РґРѕР±Р°РІРёР»Р°
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)

    except Exception as e:
        print(f"   вљ пёЏ  РћС€РёР±РєР° LLM: {e}")
        return None

async def main():
    async with AsyncSessionLocal() as session:

        # Р‘РµСЂС‘Рј РІСЃРµ diff Р·Р°РїРёСЃРё Р±РµР· Р°РЅР°Р»РёР·Р°
        diffs_result = await session.execute(
            select(DocumentDiff, Document, DocumentVersion, DocumentVersion)
            .join(Document, DocumentDiff.document_id == Document.id)
            .join(DocumentVersion, DocumentDiff.version_old_id == DocumentVersion.id)
            .filter(DocumentDiff.ai_summary_ru == None)
        )

        # РџСЂРѕС‰Рµ СЃРґРµР»Р°С‚СЊ РѕС‚РґРµР»СЊРЅС‹РјРё Р·Р°РїСЂРѕСЃР°РјРё
        diffs_result = await session.execute(select(DocumentDiff).where(DocumentDiff.ai_summary_ru == None))
        diffs = diffs_result.scalars().all()
        print(f"Р—Р°РїРёСЃРµР№ РґР»СЏ Р°РЅР°Р»РёР·Р°: {len(diffs)}")

        for diff in diffs:
            # РџРѕР»СѓС‡Р°РµРј РІРµСЂСЃРёРё
            v_old = await session.get(DocumentVersion, diff.version_old_id)
            v_new = await session.get(DocumentVersion, diff.version_new_id)
            doc = await session.get(Document, diff.document_id)

            print(f"\nрџ¤– РђРЅР°Р»РёР·РёСЂСѓРµРј: {doc.title_ru}")
            print(f"   {v_old.version_date} в†’ {v_new.version_date}")

            result = await analyze_diff(diff, doc.title_ru, v_old.version_date, v_new.version_date)

            if result:
                diff.ai_summary_ru = result.get("summary_ru", "")
                diff.affects_sentence = result.get("affects_sentence", False)

                print(f"   рџ“ќ Р РµР·СЋРјРµ: {result.get('summary_ru', '')}")
                print(f"   вљ–пёЏ  Р’Р»РёСЏРµС‚ РЅР° СЃСЂРѕРє: {result.get('affects_sentence')}")
                print(f"   рџ“Љ Р’Р°Р¶РЅРѕСЃС‚СЊ: {result.get('importance')}")
                print(f"   рџ’¬ Р”Р»СЏ РѕСЃСѓР¶РґС‘РЅРЅРѕРіРѕ: {result.get('explanation_ru', '')}")

                await session.commit()
            else:
                print(f"   вЏ­пёЏ  РџСЂРѕРїСѓС‰РµРЅРѕ (РјР°Р»Рѕ РёР·РјРµРЅРµРЅРёР№)")

    print("\nвњ… РђРЅР°Р»РёР· Р·Р°РІРµСЂС€С‘РЅ!")

asyncio.run(main())
