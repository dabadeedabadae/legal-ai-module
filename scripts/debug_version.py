import httpx
import asyncio
from bs4 import BeautifulSoup

async def debug():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, verify=False,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    ) as client:
        
        # Берём конкретную архивную версию
        url = "https://adilet.zan.kz/rus/docs/K1400000226/01.01.2026"
        resp = await client.get(url)
        
        print(f"Финальный URL: {resp.url}")
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Смотрим ВСЕ div с классами
        print("\nВсе div классы:")
        divs = {}
        for d in soup.find_all("div"):
            cls = " ".join(d.get("class", []))
            if cls:
                divs[cls] = divs.get(cls, 0) + 1
        for cls, count in sorted(divs.items()):
            print(f"  '{cls}' x{count}")
        
        # Смотрим первые 500 символов HTML
        print(f"\nHTML (фрагмент):\n{resp.text[2000:3000]}")

asyncio.run(debug())
