## Buddy — AI‑агент онбординга в Mattermost

Buddy — это backend‑сервис (FastAPI), который работает как бот в Mattermost и:

- **Встречает нового сотрудника** и узнаёт его роль.
- **Ведёт по сценарию онбординга**, зависящему от роли.
- **Отвечает на вопросы новичка** из базы знаний с помощью LLM.
- **Если ответа нет** — спрашивает коллег в выделенном канале.
- **Сохраняет ответы коллег в базу знаний**, чтобы следующий новичок сразу получил готовый ответ.

### Архитектура

- **Язык / стек**: Python 3.11+, FastAPI, SQLAlchemy, SQLite, httpx.
- **Интеграция с Mattermost**:
  - Вход: исходящий webhook или plugin‑endpoint `POST /mattermost/webhook` с полем `post` (JSON‑строка с постом).
  - Выход: REST API Mattermost `POST /api/v4/posts` (бот‑токен).
- **LLM**: OpenRouter `chat/completions` API.
- **Хранение**:
  - `users` — состояние онбординга и роль.
  - `questions` / `answers` — история вопросов/ответов.
  - `knowledge_items` — база знаний (вопрос/ответ/теги/ссылка на исходный вопрос).
  - **Сценарий онбординга** — в коде (`app/onboarding.py`), можно вынести в БД/YAML.

### Локальный запуск

```bash
cd buddy
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export OPENROUTER_API_KEY=...              # ключ для LLM (для локального теста можно не задавать)
export OPENROUTER_MODEL=openai/gpt-4.1-mini
export MATTERMOST_BASE_URL=https://mattermost.example.com
export MATTERMOST_BOT_TOKEN=mm-...         # токен бот‑аккаунта
export MATTERMOST_EXPERT_CHANNEL_ID=...    # id канала, куда Buddy задаёт вопросы коллегам

uvicorn app.main:app --reload --port 8000
```

Проверка:

```bash
curl http://localhost:8000/
```

Ожидаемый ответ: `Buddy Mattermost agent is running`.

### Streamlit-чат (для тестирования)

```bash
streamlit run streamlit_app.py
```

Откроется http://localhost:8501

**Деплой на Streamlit Cloud** — см. [DEPLOY.md](DEPLOY.md). После деплоя получишь публичную ссылку для тестирования.

### База знаний

```bash
python scripts/seed_knowledge.py --clear   # очистить и заново (~216 записей)
python scripts/seed_knowledge.py           # только добавить/обновить
```

Отборная база (~50 записей): `python scripts/seed_knowledge_curated.py --clear`

Экспорт в Excel: `python scripts/export_knowledge_to_excel.py` → `knowledge_base.xlsx`

### Связка с Mattermost

Есть два варианта:

- **Исходящий webhook**:
  - В админке Mattermost создать исходящий webhook.
  - Указать URL: `http://<host>:8000/mattermost/webhook`.
  - Задать триггеры, например: `buddy`, `онбординг`.
  - Включить поля в payload (по умолчанию Mattermost кладёт пост в `post` как JSON‑строку).
- **Plugin / custom integration**:
  - Использовать тот же эндпоинт `POST /mattermost/webhook` и отправлять туда payload с полем `post`.

Buddy игнорирует сообщения от самого бота (по `bot_user_id`) и:

- Обрабатывает личные сообщения/упоминания от новичков.
- Вопросы к коллегам отправляет в канал `MATTERMOST_EXPERT_CHANNEL_ID`.
- Ответы коллег в тредах этого канала воспринимает как новые факты базы знаний.

### Формат ожидаемого payload (пример)

```json
{
  "user_name": "newbie",
  "bot_user_id": "buddy-bot-id",
  "post": "{\"id\": \"post-1\", \"user_id\": \"user-123\", \"channel_id\": \"dm-channel-1\", \"message\": \"start\", \"root_id\": \"\"}"
}
```

Mattermost по умолчанию как раз отправляет `post` строкой — сервис её парсит внутри.

---

## Демо‑сценарии

### 1. Сценарий от лица новичка

Предположим, настроен исходящий webhook на ключевое слово `buddy` в личных сообщениях.

**Шаг 1. Новичок пишет Buddy в личку:**

```bash
curl -X POST http://localhost:8000/mattermost/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "user_name": "newbie",
    "bot_user_id": "buddy-bot-id",
    "post": "{\"id\": \"p1\", \"user_id\": \"user-newbie\", \"channel_id\": \"dm-1\", \"message\": \"привет buddy\", \"root_id\": \"\"}"
  }'
```

**Ответ Buddy:**

- Приветствие + просьба указать роль:
  - «Привет! Я Buddy, помогу с онбордингом. Для начала расскажи, какая у тебя роль (например: backend, frontend, менеджер).»

**Шаг 2. Новичок отвечает ролью:**

```bash
curl -X POST http://localhost:8000/mattermost/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "user_name": "newbie",
    "bot_user_id": "buddy-bot-id",
    "post": "{\"id\": \"p2\", \"user_id\": \"user-newbie\", \"channel_id\": \"dm-1\", \"message\": \"backend\", \"root_id\": \"\"}"
  }'
```

**Ответ Buddy:**

- «Отлично, ты backend. …» + первый шаг сценария онбординга (общий + backend‑часть).

**Дальше**:

- Каждый следующий месседж новичка в этом диалоге продвигает сценарий (`ONBOARDING_SCENARIOS`) вперёд.
- После окончания шагов Buddy пишет:
  - «Мы прошли базовый сценарий онбординга. Теперь можешь задавать любые вопросы…»
- Любое сообщение становится вопросом к базе знаний / коллегам.

**Пример вопроса новичка:**

```bash
curl -X POST http://localhost:8000/mattermost/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "user_name": "newbie",
    "bot_user_id": "buddy-bot-id",
    "post": "{\"id\": \"p3\", \"user_id\": \"user-newbie\", \"channel_id\": \"dm-1\", \"message\": \"Где лежит репозиторий user-service?\", \"root_id\": \"\"}"
  }'
```

- Если в базе знаний уже есть похожий вопрос, Buddy отвечает сразу (через LLM).
- Если нет — сообщает, что спросит у коллег.

### 2. Сценарий от лица коллеги‑эксперта

Предполагаем, что `MATTERMOST_EXPERT_CHANNEL_ID` указывает на канал `experts`, и там настроен отдельный исходящий webhook на тот же эндпоинт.

**Шаг 1. Buddy спрашивает коллег:**

- После неизвестного вопроса от новичка Buddy делает `POST /api/v4/posts` в канал `experts` со следующим текстом:
  - «Коллеги, вопрос от нового сотрудника @newbie: … Пожалуйста, ответьте в этом треде. Я сохраню ответ в базу знаний и передам новичку.»
- Возвращённый `id` корневого поста сохраняется в `questions.mattermost_root_post_id`.

**Шаг 2. Коллега отвечает в треде**

Смоделируем это вручную:

```bash
curl -X POST http://localhost:8000/mattermost/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "user_name": "expert",
    "bot_user_id": "buddy-bot-id",
    "post": "{\"id\": \"p4\", \"user_id\": \"user-expert\", \"channel_id\": \"'"$MATTERMOST_EXPERT_CHANNEL_ID"'\", \"message\": \"Репозиторий user-service лежит в GitHub org X, репо user-service.\", \"root_id\": \"<root_post_id>\"}"
  }'
```

Где `<root_post_id>` — идентификатор поста, который вернул Mattermost при вопросе Buddy в канал `experts`.

**Что делает Buddy:**

- Находит `Question` по `mattermost_root_post_id`.
- Создаёт `Answer` с `author_type=human`.
- Создаёт `KnowledgeItem` (вопрос/ответ).
- Помечает вопрос как `answered`.
- В реальной интеграции можно дополнительно:
  - Отправить ответ новичку в личку.
  - Синхронизировать статус в задачах/портале.

---

## Что сделано и почему

- **Простой, но расширяемый стек**: FastAPI + SQLite подходят для прототипа/демо, легко развернуть локально, можно заменить БД на Postgres без изменения логики.
- **Сценарий онбординга в коде**:
  - Быстрый старт, минимум инфраструктуры.
  - Структура `ONBOARDING_SCENARIOS` позволяет позже вынести сценарии в БД или YAML/JSON.
- **База знаний как Q/A–таблица**:
  - Проста в реализации.
  - Можно легко добавить полнотекстовый поиск или векторный поиск.
  - LLM работает поверх уже отфильтрованных/суженных фактов.
- **Маршрутизация вопросов к людям**:
  - Через выделенный канал экспертов, без сложной логики поиска конкретных людей.
  - В реальном проекте можно привязать теги/темы к конкретным ролям/тимлидам.

### Что бы улучшил при большем времени

- **Улучшить поиск по базе знаний**:
  - Добавить полнотекстовый индекс или векторный поиск (например, с помощью внешней БД/сервиса).
  - Сохранять теги/темы и использовать их в ранжировании.
- **Гибкое управление сценарием онбординга**:
  - Вынести сценарий в конфигурацию (YAML/JSON или админ‑UI).
  - Добавить условия, ветвления, повторные проверки и напоминания.
- **Более умная маршрутизация к людям**:
  - Маппинг тегов вопросов на конкретные команды/людей.
  - SLA и напоминания, если вопрос долго остаётся без ответа.
- **Больше контекста для LLM**:
  - Подмешивать информацию из handbook/Confluence/Notion.
  - Ограничивать ответы политиками компании.
- **Логирование и метрики**:
  - Статистика по вопросам, «дыркам» в базе знаний, времени ответа.
  - Экспорт в Prometheus/Grafana.

