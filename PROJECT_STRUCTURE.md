# Buddy — структура проекта

Краткий обзор компонентов и точек входа.

---

## Точки входа

| Файл | Назначение |
|------|------------|
| **streamlit_app.py** | Главный UI для тестирования. Деплой на Streamlit Cloud. Запуск: `streamlit run streamlit_app.py` |
| **app/streamlit_chat.py** | Чат-сервис: KB, self-learning, тикеты модерации, поиск по базе знаний |
| **app/main.py** | FastAPI для Mattermost (опционально). Webhook-обработка сообщений из MChat |
| **scripts/seed_knowledge.py** | Начальная загрузка базы знаний (Q&A) |

---

## Ключевые файлы

| Файл | Описание |
|------|----------|
| **knowledge_moderator.json** | Резервная копия ответов модератора (создаётся при resolve тикета) |
| **.env** | Переменные окружения (см. .env.example) |
| **.streamlit/secrets.toml** | Секреты для Streamlit Cloud (не коммитить) |
| **.streamlit/config.toml** | Конфиг Streamlit (theme, server, timeout) |

---

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| **OPENROUTER_API_KEY** | Ключ API OpenRouter для LLM |
| **OPENROUTER_MODEL** | Модель (по умолчанию: openai/gpt-4.1-mini) |
| **STREAMLIT_DATABASE_URL** | PostgreSQL для Streamlit (Supabase: порт **6543** pooler, не 5432) |
| **DATABASE_URL** | Альтернатива для FastAPI / seed-скриптов |
| **BUDDY_FORCE_SQLITE** | Принудительный fallback на SQLite при ошибке PostgreSQL |

---

## Директории

```
buddy_2.0/
├── streamlit_app.py          # UI
├── app/
│   ├── streamlit_chat.py     # Chat, KB, self-learning, moderation
│   ├── main.py               # FastAPI (Mattermost)
│   ├── config.py
│   ├── models.py
│   ├── llm_client.py
│   ├── mattermost_client.py
│   └── onboarding.py
├── scripts/
│   ├── seed_knowledge.py     # Начальная KB
│   └── ...
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml         # (локально, не в git)
└── knowledge_moderator.json  # Backup ответов модератора
```
