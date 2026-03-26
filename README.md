# Legal AI Module — ИИ-правовой консультант для осуждённых

FastAPI модуль для автоматического мониторинга изменений законодательства РК и ответов на юридические вопросы осуждённых в учреждениях УИС.

## Стек

- **FastAPI** — REST API
- **PostgreSQL** — хранение версий документов и diff
- **Redis** — очереди задач
- **Celery** — фоновые задачи (планировщик парсера)
- **Ollama + Qwen2.5:7b** — локальная LLM (работает офлайн)
- **diff-match-patch** — сравнение версий законов

## Архитектура
```
Android App → Laravel (основной бэкенд) → FastAPI (этот модуль)
                                               ↓
                                     PostgreSQL + Ollama
```

## Быстрый старт

### Требования
- Python 3.13+
- Docker Desktop
- Ollama

### Установка
```bash
git clone https://github.com/dabadeedabadae/legal-ai-module.git
cd legal-ai-module

python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### Настройка
```bash
# Скопируй и заполни .env
cp .env.example .env
```

`.env.example`:
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5435/legal_ai
REDIS_URL=redis://localhost:6379/0
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
LARAVEL_API_KEY=your_secret_key
ADILET_BASE_URL=https://adilet.zan.kz
PARSER_DELAY_SECONDS=2
```

### Запуск
```bash
# 1. Запустить базы данных
docker compose up -d

# 2. Применить миграции
python -m alembic upgrade head

# 3. Скачать LLM модель (один раз, 4.7GB)
ollama pull qwen2.5:7b

# 4. Заполнить базу версиями законов
python app/services/parser/save_versions.py

# 5. Посчитать diff между версиями
python app/services/diff/comparator.py

# 6. Запустить LLM анализ изменений
python app/services/llm/analyzer.py

# 7. Запустить API сервер
python -m uvicorn main:app --reload --port 8000
```

## API эндпоинты

Все запросы требуют заголовок `x-api-key`.

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/health` | Проверка работоспособности |
| GET | `/api/v1/documents` | Список документов |
| GET | `/api/v1/documents/{id}/changes` | Изменения документа с AI анализом |
| GET | `/api/v1/changes/important` | Только важные изменения |
| POST | `/api/v1/ask` | Вопрос-ответ (RAG) |

### Пример запроса
```bash
curl -H "x-api-key: your_key" http://localhost:8000/api/v1/documents
```
```json
[
  {"id": 1, "external_id": "K1400000226", "title_ru": "Уголовный кодекс РК"},
  {"id": 2, "external_id": "K1400000234", "title_ru": "Уголовно-исполнительный кодекс РК"}
]
```

## Мониторируемые документы

| Документ | ID | Версий |
|----------|----|--------|
| Уголовный кодекс РК | K1400000226 | 112 |
| Уголовно-исполнительный кодекс РК | K1400000234 | 54 |

## Структура проекта
```
legal-ai-module/
├── app/
│   ├── api/
│   │   └── routes.py          # FastAPI роуты
│   ├── core/
│   │   ├── config.py          # Настройки
│   │   └── database.py        # Подключение к БД
│   ├── models/
│   │   └── document.py        # SQLAlchemy модели
│   └── services/
│       ├── parser/            # Парсер adilet.zan.kz
│       ├── diff/              # Алгоритм сравнения версий
│       ├── llm/               # LLM анализ изменений
│       └── rag/               # Вопрос-ответ по тексту закона
├── migrations/                # Alembic миграции
├── docker-compose.yml
├── main.py
└── requirements.txt
```

## Разработка

- **Аяган Елнур**
- Период: 23.02.2026 — 23.04.2026
- Заказчик: УИС РК
