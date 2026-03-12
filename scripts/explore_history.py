import httpx
import asyncio
from bs4 import BeautifulSoup

BASE_URL = "https://adilet.zan.kz"

HISTORY_URLS = [
    "/rus/docs/K1400000226/history",  # УК РК
    "/rus/docs/K1400000234/history",  # УИК РК
]

async def explore_history():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True, verify=False) as client:
        for path in HISTORY_URLS:
            url = BASE_URL + path
            print(f"\n{'='*60}")
            print(f"URL: {url}")

            resp = await client.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")

            # Ищем все ссылки которые выглядят как версии документа
            print("\nВсе ссылки на версии:")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.text.strip()
                # Версии обычно содержат дату или параметр версии в URL
                if text and len(text) > 3 and any(c.isdigit() for c in text):
                    print(f"  текст: {text[:70]}")
                    print(f"  href:  {href[:80]}")
                    print()

            # Смотрим таблицы — история обычно в таблице
            tables = soup.find_all("table")
            print(f"Таблиц на странице: {len(tables)}")
            for i, table in enumerate(tables[:2]):
                rows = table.find_all("tr")
                print(f"\nТаблица {i+1} — строк: {len(rows)}")
                for row in rows[:5]:
                    cols = [td.text.strip()[:50] for td in row.find_all(["td", "th"])]
                    if any(cols):
                        print(f"  {cols}")

            await asyncio.sleep(2)

asyncio.run(explore_history())
