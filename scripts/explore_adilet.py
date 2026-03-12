import httpx
import asyncio
from bs4 import BeautifulSoup

BASE_URL = "https://adilet.zan.kz"

# Известные документы для теста — УК РК и УИК РК
TEST_DOCS = [
    "/rus/docs/K1400000226",  # УК РК
    "/rus/docs/K1400000234",  # УИК РК
]

async def explore():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True, verify=False) as client:
        for path in TEST_DOCS:
            url = BASE_URL + path
            print(f"\n{'='*60}")
            print(f"URL: {url}")

            resp = await client.get(url)
            print(f"Статус: {resp.status_code}")
            print(f"Заголовки защиты: {dict(resp.headers).get('x-ratelimit-limit', 'нет')}")

            soup = BeautifulSoup(resp.text, "html.parser")

            # Ищем название документа
            title = soup.find("h1") or soup.find("h2")
            if title:
                print(f"Название: {title.text.strip()[:80]}")

            # Ищем ссылки на редакции/версии
            version_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.text.strip()
                if any(word in text.lower() for word in ["редакц", "версия", "изменен", "от ", "2024", "2025", "2026"]):
                    version_links.append((text[:60], href[:80]))

            print(f"\nНайдено ссылок на версии: {len(version_links)}")
            for text, href in version_links[:5]:
                print(f"  → {text} | {href}")

            # Проверяем есть ли captcha
            page_text = resp.text.lower()
            has_captcha = any(w in page_text for w in ["captcha", "recaptcha", "cloudflare", "robot"])
            print(f"\nCaptcha/защита: {'⚠️  ЕСТЬ' if has_captcha else '✅ нет'}")

            await asyncio.sleep(2)  # вежливая пауза

asyncio.run(explore())
