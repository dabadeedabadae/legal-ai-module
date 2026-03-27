# КОНТЕКСТ ПРОЕКТА — Legal AI Module

## Что это
FastAPI модуль (Python) — ИИ-правовой консультант для осуждённых УИС РК.
Подключается к основному Laravel проекту через REST API + API Key.
Работает офлайн в закрытом контуре (Android → Laravel → FastAPI).

## Разработчик
Аяган Елнур. Старт: 23.02.2026. Дедлайн: 23.04.2026.

## Стек
- FastAPI + Python 3.14
- PostgreSQL 16 (Docker, порт 5435)
- Redis (Docker, порт 6379)
- Groq API (llama-3.3-70b-versatile) — основной LLM
- Ollama + Qwen2.5:7b (резервный, офлайн)
- diff-match-patch (сравнение версий законов)
- Alembic (миграции)

## Где лежит проект
Windows ПК: C:\Users\posit\PycharmProjects\legal-ai-module
GitHub: https://github.com/dabadeedabadae/legal-ai-module

## Что уже сделано (~70% по ТЗ)
- Парсер adilet.zan.kz (URL: /rus/docs/{ID}/{дата}, класс: container_gamma text text_upd text_arc)
- Сохранение всех версий законов в БД (109 версий УК РК, 52 УИК РК)
- Diff алгоритм (сравнение соседних версий)
- LLM анализ изменений (промпт на русском, JSON ответ)
- RAG — вопрос-ответ по тексту закона
- FastAPI эндпоинты с API Key авторизацией
- Groq API интеграция (платный план)
- Универсальный LLM клиент (Groq / Ollama)
- README.md

## Мониторируемые документы
- УК РК: K1400000226 (109 версий в БД)
- УИК РК: K1400000234 (52 версии в БД)

## API эндпоинты
GET  /health
GET  /api/v1/documents
GET  /api/v1/documents/{id}/changes
GET  /api/v1/changes/important
POST /api/v1/ask  {"question": "..."}
Заголовок: x-api-key: secret_key_change_me

## Структура БД
- documents: id, external_id, title_ru, category, url
- document_versions: id, document_id, version_date, raw_text, normalized_text, text_hash, char_count
- document_diffs: id, document_id, version_old_id, version_new_id, diff_json, ai_summary_ru, affects_sentence

## Что осталось сделать
1. Планировщик Celery — автозапуск парсера раз в неделю
2. Фаза 3: проверка юристом
3. Фаза 4: казахский язык и жаргон
4. Фаза 5: интеграция с Laravel, e2e тест

## Команды запуска (Windows PowerShell)
docker compose up -d
python -m alembic upgrade head
python app/services/parser/save_versions.py
python app/services/diff/comparator.py
python -m app.services.llm.analyzer
python -m uvicorn main:app --reload --port 8000

## Известные проблемы
- Последняя версия документа (текущая) не парсится — она на другом URL
- PowerShell не отображает кириллицу (данные в БД корректные)
- .env нужно создавать без BOM (использовать [System.IO.File]::WriteAllText)
- Файлы .py сохранять через [System.IO.File]::WriteAllText для правильной кодировки

## LLM провайдеры
- Groq API: основной (llama-3.3-70b-versatile, платный план Developer)
- Ollama: резервный офлайн вариант (qwen2.5:7b)
- Переключение через LLM_PROVIDER в .env (groq/ollama)