# Как протестировать Buddy

Три уровня тестирования: от быстрой проверки без настройки до полной интеграции с Mattermost.

---

## 1. Быстрый старт (без Mattermost и LLM)

### Запуск сервера

```bash
cd buddy
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

Переменные окружения можно не задавать — Buddy работает в демо-режиме.

### Проверка

```bash
curl http://localhost:8000/
# → Buddy Mattermost agent is running
```

### Веб-демо (чат в браузере)

Открой в браузере: **http://localhost:8000/chat**

Там можно:
1. Написать «привет» → Buddy попросит указать роль
2. Написать «backend» → начнётся сценарий онбординга
3. Пройти шаги сценария (просто отправляй любые сообщения)
4. Задать вопрос из базы знаний, например: «Где посмотреть структуру компании?»

**Без OPENROUTER_API_KEY:** Buddy ответит по базе знаний, но с fallback-текстом («LLM не настроен»). Для полноценных ответов нужен ключ.

---

## 2. Тесты через curl (имитация Mattermost)

### Шаг 1: Приветствие

```bash
curl -X POST http://localhost:8000/mattermost/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "user_name": "test_user",
    "bot_user_id": "buddy-bot-id",
    "post": "{\"id\": \"p1\", \"user_id\": \"u1\", \"channel_id\": \"dm-1\", \"message\": \"привет\", \"root_id\": \"\"}"
  }'
```

Ожидаемый ответ: приветствие и просьба указать роль.

### Шаг 2: Указать роль

```bash
curl -X POST http://localhost:8000/mattermost/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "user_name": "test_user",
    "bot_user_id": "buddy-bot-id",
    "post": "{\"id\": \"p2\", \"user_id\": \"u1\", \"channel_id\": \"dm-1\", \"message\": \"backend\", \"root_id\": \"\"}"
  }'
```

Ожидаемый ответ: первый шаг сценария онбординга.

### Шаг 3: Пройти сценарий

Повтори запрос несколько раз с разными `id` в `post` (например `p3`, `p4`, …) и любым `message`. Каждое сообщение — следующий шаг.

### Шаг 4: Задать вопрос

```bash
curl -X POST http://localhost:8000/mattermost/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "user_name": "test_user",
    "bot_user_id": "buddy-bot-id",
    "post": "{\"id\": \"p5\", \"user_id\": \"u1\", \"channel_id\": \"dm-1\", \"message\": \"Где посмотреть структуру компании?\", \"root_id\": \"\"}"
  }'
```

Ожидаемый ответ: ответ из базы знаний (если есть OPENROUTER_API_KEY) или fallback.

---

## 3. Unit-тесты (pytest)

```bash
cd buddy
source .venv/bin/activate
python -m pytest tests/ -v
```

Проверяется:
- структура базы знаний (seed)
- healthcheck
- добавление записей в базу знаний
- webhook с валидным payload

---

## 4. С LLM (OpenRouter)

Для реальных ответов из базы знаний нужен ключ OpenRouter:

```bash
export OPENROUTER_API_KEY=sk-or-...
export OPENROUTER_MODEL=openai/gpt-4.1-mini
uvicorn app.main:app --reload --port 8000
```

Или создай `.env`:

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-4.1-mini
```

После этого вопросы в `/chat` или через curl будут обрабатываться LLM.

---

## 5. Заполнение базы знаний

Перед тестами с вопросами заполни базу:

```bash
python scripts/seed_knowledge.py
```

---

## 6. Полная интеграция с Mattermost

### Что нужно

1. **Mattermost** с доступом на создание webhook и ботов
2. **Публичный URL** для Buddy (ngrok, туннель или хостинг)

### Настройка

1. Создай бот-аккаунт Buddy в Mattermost
2. Получи токен бота
3. Создай канал для экспертов (например `buddy_experts`)
4. Создай исходящий webhook:
   - URL: `https://твой-хост/mattermost/webhook`
   - Триггеры: `buddy`, `@buddy`, `онбординг`
   - Каналы: личные сообщения (или нужные каналы)

5. Заполни `.env`:

```
OPENROUTER_API_KEY=sk-or-...
MATTERMOST_BASE_URL=https://mchat.pravo.tech
MATTERMOST_BOT_TOKEN=mm-...
MATTERMOST_EXPERT_CHANNEL_ID=<id канала buddy_experts>
```

6. Запусти Buddy и напиши боту в личку в Mattermost

---

## 7. Чек-лист проверки

| Что проверить | Как |
|---------------|-----|
| Сервер запускается | `curl http://localhost:8000/` |
| Приветствие | curl с `"message": "привет"` |
| Сценарий онбординга | curl: роль → несколько шагов |
| Ответ из базы знаний | curl с вопросом типа «Где структура компании?» |
| Эскалация экспертам | Вопрос, которого нет в БЗ; без MATTERMOST_EXPERT_CHANNEL_ID — fallback |
| Веб-демо | http://localhost:8000/chat |
| Unit-тесты | `pytest tests/ -v` |
