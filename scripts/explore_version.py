import httpx
import asyncio
from bs4 import BeautifulSoup

BASE_URL = "https://adilet.zan.kz"

async def explore_version():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True, verify=False) as client:

        # Пробуем разные форматы URL для версий по дате
        test_urls = [
            "/rus/docs/K1400000226",                          # текущая версия
            "/rus/docs/K1400000226?vers=07.11.2014",          # версия по дате вариант 1
            "/rus/docs/K1400000226/07.11.2014",               # вариант 2
        ]

        for path in test_urls:
            url = BASE_URL + path
            print(f"\n{'='*60}")
            print(f"URL: {url}")
            resp = await client.get(url)
            print(f"Статус: {resp.status_code}")
            print(f"Финальный URL: {resp.url}")

            soup = BeautifulSoup(resp.text, "html.parser")

            # Смотрим есть ли в странице текст статей
            # Ищем параграфы с текстом закона
            content_div = (
                soup.find("div", class_="document") or
                soup.find("div", id="doc") or
                soup.find("div", class_="content") or
                soup.find("article")
            )

            if content_div:
                text = content_div.text.strip()[:300]
                print(f"Контент найден: {text}")
            else:
                # Покажем все div классы чтобы найти нужный
                divs = set(d.get("class", [""])[0] for d in soup.find_all("div") if d.get("class"))
                print(f"Div классы на странице: {list(divs)[:15]}")

            await asyncio.sleep(2)

asyncio.run(explore_version())
