import httpx
import asyncio
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup

BASE_URL = "https://adilet.zan.kz"

# Приоритетные документы для осуждённых
PRIORITY_DOCS = {
    "K1400000226": "Уголовный кодекс РК",
    "K1400000234": "Уголовно-исполнительный кодекс РК",
    "K950001015_":  "Уголовно-процессуальный кодекс РК",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

def normalize_text(text: str) -> str:
    """Убираем лишние пробелы, переносы — оставляем чистый текст"""
    lines = [line.strip() for line in text.splitlines()]
    lines = [l for l in lines if l]
    return " ".join(lines)

def get_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

async def fetch_history(client: httpx.AsyncClient, doc_id: str) -> list[dict]:
    """Получаем список всех версий документа с датами"""
    url = f"{BASE_URL}/rus/docs/{doc_id}/history"
    resp = await client.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    versions = []
    table = soup.find("table")
    if not table:
        return versions

    rows = table.find_all("tr")[1:]  # пропускаем заголовок
    for row in rows:
        cols = row.find_all("td")
        if len(cols) >= 5:
            date_str = cols[4].text.strip()  # колонка "Дата изменения"
            status = cols[5].text.strip() if len(cols) > 5 else ""
            versions.append({
                "date": date_str,
                "status": status,
            })

    return versions

async def fetch_version_text(client: httpx.AsyncClient, doc_id: str, date: str) -> str | None:
    """Получаем текст документа на конкретную дату"""
    url = f"{BASE_URL}/rus/docs/{doc_id}/{date}"
    resp = await client.get(url)

    soup = BeautifulSoup(resp.text, "html.parser")
    content = soup.find("div", class_="container_gamma text text_upd text_arc") or soup.find("div", class_="document")
    if not content:
        return None

    raw_text = content.get_text(separator="\n")
    return normalize_text(raw_text)

async def parse_document(doc_id: str):
    """Основная функция — парсим документ и все его версии"""
    async with httpx.AsyncClient(
        headers=HEADERS, timeout=30,
        follow_redirects=True, verify=False
    ) as client:

        print(f"\n📄 Документ: {PRIORITY_DOCS.get(doc_id, doc_id)}")
        print(f"   ID: {doc_id}")

        # 1. Получаем историю версий
        versions = await fetch_history(client, doc_id)
        print(f"   Версий найдено: {len(versions)}")

        results = []

        # 2. Берём последние 3 версии для теста
        for v in versions[-3:]:
            date = v["date"]
            print(f"\n   ⏳ Загружаем версию от {date}...")

            text = await fetch_version_text(client, doc_id, date)
            if not text:
                print(f"   ⚠️  Текст не найден")
                continue

            text_hash = get_hash(text)
            print(f"   ✅ Текст получен: {len(text)} символов")
            print(f"   🔑 Hash: {text_hash[:16]}...")
            print(f"   📝 Начало: {text[:100]}...")

            results.append({
                "doc_id": doc_id,
                "date": date,
                "status": v["status"],
                "text_length": len(text),
                "hash": text_hash,
            })

            await asyncio.sleep(2)  # вежливая пауза

        return results

async def main():
    all_results = []
    for doc_id in PRIORITY_DOCS:
        results = await parse_document(doc_id)
        all_results.extend(results)
        await asyncio.sleep(3)

    print(f"\n{'='*60}")
    print(f"✅ Итого обработано версий: {len(all_results)}")
    for r in all_results:
        print(f"  {r['doc_id']} | {r['date']} | {r['text_length']} символов | hash: {r['hash'][:12]}")

asyncio.run(main())
