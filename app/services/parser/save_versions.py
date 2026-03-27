import httpx
import asyncio
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from app.models.document import Document, DocumentVersion
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
BASE_URL = "https://adilet.zan.kz"

PRIORITY_DOCS = {
    "K1400000226": "Уголовный кодекс РК",
    "K1400000234": "Уголовно-исполнительный кодекс РК",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

def normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    lines = [l for l in lines if l]
    return " ".join(lines)

def get_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

async def get_or_create_document(session: AsyncSession, external_id: str, title: str) -> Document:
    result = await session.execute(
        select(Document).where(Document.external_id == external_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        doc = Document(
            external_id=external_id,
            title_ru=title,
            category="criminal",
            url=f"{BASE_URL}/rus/docs/{external_id}",
        )
        session.add(doc)
        await session.flush()
        print(f"  📝 Создан документ: {title}")
    else:
        print(f"  📄 Документ уже есть: {title}")
    return doc

async def version_exists(session: AsyncSession, document_id: int, version_date: str) -> bool:
    result = await session.execute(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.version_date == version_date,
        )
    )
    return result.scalar_one_or_none() is not None

async def fetch_history(client, doc_id: str) -> list[dict]:
    url = f"{BASE_URL}/rus/docs/{doc_id}/history"
    resp = await client.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    versions = []
    table = soup.find("table")
    if not table:
        return versions
    for row in table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) >= 5:
            versions.append({
                "date": cols[4].text.strip(),
                "status": cols[5].text.strip() if len(cols) > 5 else "",
            })
    return versions

async def fetch_version_text(client, doc_id: str, date: str) -> str | None:
    url = f"{BASE_URL}/rus/docs/{doc_id}/{date}"
    resp = await client.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    content = (
        soup.find("div", class_="container_gamma text text_upd text_arc") or
        soup.find("div", class_="document")
    )
    if not content:
        return None
    return normalize_text(content.get_text(separator="\n"))

async def main():
    async with AsyncSessionLocal() as session:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=30,
            follow_redirects=True, verify=False
        ) as client:

            for doc_id, title in PRIORITY_DOCS.items():
                print(f"\n{'='*60}")
                print(f"📄 {title} ({doc_id})")

                # Создаём документ в БД
                doc = await get_or_create_document(session, doc_id, title)

                # Получаем историю версий
                versions = await fetch_history(client, doc_id)
                print(f"   Версий на сайте: {len(versions)}")

                saved = 0
                skipped = 0

                # Сохраняем все версии (для теста берём последние 5)
                for v in versions:
                    date = v["date"]

                    # Пропускаем если уже есть в БД
                    if await version_exists(session, doc.id, date):
                        skipped += 1
                        continue

                    text = await fetch_version_text(client, doc_id, date)
                    if not text:
                        print(f"   ⚠️  Версия {date} — текст не найден")
                        continue

                    version = DocumentVersion(
                        document_id=doc.id,
                        version_date=date,
                        raw_text=text,
                        normalized_text=text,
                        text_hash=get_hash(text),
                        char_count=len(text),
                        fetched_at=datetime.utcnow(),
                    )
                    session.add(version)
                    await session.flush()
                    saved += 1
                    print(f"   ✅ Сохранена версия {date} — {len(text)} символов")
                    await asyncio.sleep(2)

                await session.commit()
                print(f"\n   Итого: сохранено {saved}, пропущено {skipped}")
                await asyncio.sleep(3)

    print("\n✅ Готово! Данные в БД.")

asyncio.run(main())
