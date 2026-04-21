import asyncio
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from diff_match_patch import diff_match_patch
from sqlalchemy import select
from app.core.database import async_session_maker
from app.models.document import Document, DocumentVersion, DocumentDiff

dmp = diff_match_patch()

def compute_diff(text_old: str, text_new: str) -> dict:
    """Сравниваем два текста и возвращаем структурированный результат"""
    diffs = dmp.diff_main(text_old, text_new)
    dmp.diff_cleanupSemantic(diffs)  # делает diff более читаемым

    added = []
    removed = []

    for op, text in diffs:
        if op == 1 and len(text.strip()) > 10:   # добавлено
            added.append(text.strip()[:500])
        elif op == -1 and len(text.strip()) > 10: # удалено
            removed.append(text.strip()[:500])

    return {
        "added": added[:20],    # топ 20 изменений
        "removed": removed[:20],
        "added_chars": sum(len(t) for _, t in diffs if _ == 1),
        "removed_chars": sum(len(t) for _, t in diffs if _ == -1),
        "total_changes": len([d for d in diffs if d[0] != 0]),
    }

async def main():
    async with async_session_maker() as session:

        # Берём все документы
        docs_result = await session.execute(select(Document))
        documents = docs_result.scalars().all()

        for doc in documents:
            print(f"\n{'='*60}")
            print(f"📄 {doc.title_ru}")

            # Берём все версии документа отсортированные по дате
            versions_result = await session.execute(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == doc.id)
                .order_by(DocumentVersion.id)
            )
            versions = versions_result.scalars().all()
            print(f"   Версий в БД: {len(versions)}")

            # Сравниваем каждую версию с предыдущей
            for i in range(1, len(versions)):
                v_old = versions[i-1]
                v_new = versions[i]

                # Проверяем не считали ли уже
                existing = await session.execute(
                    select(DocumentDiff).where(
                        DocumentDiff.version_old_id == v_old.id,
                        DocumentDiff.version_new_id == v_new.id,
                    )
                )
                if existing.scalar_one_or_none():
                    print(f"   ⏭️  {v_old.version_date} → {v_new.version_date} уже есть")
                    continue

                print(f"\n   🔍 Сравниваем {v_old.version_date} → {v_new.version_date}")
                print(f"      Старый: {v_old.char_count} символов")
                print(f"      Новый:  {v_new.char_count} символов")

                diff_result = compute_diff(v_old.normalized_text, v_new.normalized_text)

                print(f"      Добавлено символов: {diff_result['added_chars']}")
                print(f"      Удалено символов:   {diff_result['removed_chars']}")
                print(f"      Всего изменений:    {diff_result['total_changes']}")

                if diff_result['added']:
                    print(f"\n      📗 Примеры добавленного текста:")
                    for t in diff_result['added'][:2]:
                        print(f"         + {t[:150]}")

                if diff_result['removed']:
                    print(f"\n      📕 Примеры удалённого текста:")
                    for t in diff_result['removed'][:2]:
                        print(f"         - {t[:150]}")

                # Сохраняем в БД
                diff_record = DocumentDiff(
                    document_id=doc.id,
                    version_old_id=v_old.id,
                    version_new_id=v_new.id,
                    diff_json=json.dumps(diff_result, ensure_ascii=False),
                    affects_sentence=False,  # пока False, LLM поставит True если нужно
                )
                session.add(diff_record)

            await session.commit()
            print(f"\n   ✅ Diff сохранён в БД")

asyncio.run(main())
