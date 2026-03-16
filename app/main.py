from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .llm_client import answer_from_knowledge
from .mattermost_client import post_message
from .models import (
    Answer,
    Base,
    KnowledgeItem,
    Question,
    QuestionStatusEnum,
    User,
)
from .onboarding import extract_role_from_message, get_display_role, get_scenario_for_role

settings = get_settings()

# SQLite: check_same_thread=False для работы с TestClient (разные потоки)
_connect_args = {}
if "sqlite" in settings.database_url:
    _connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base.metadata.create_all(bind=engine)

# Миграция: добавить новые поля в questions (для существующих БД)
def _migrate_questions_table(eng):
    from sqlalchemy import inspect, text
    try:
        insp = inspect(eng)
        cols = [c["name"] for c in insp.get_columns("questions")]
        alter_statements = []
        if "mattermost_channel_id" not in cols:
            alter_statements.append(
                "ALTER TABLE questions ADD COLUMN mattermost_channel_id VARCHAR(64)"
            )
        if "pending_answer_text" not in cols:
            alter_statements.append(
                "ALTER TABLE questions ADD COLUMN pending_answer_text TEXT"
            )
        if "pending_answer_author_id" not in cols:
            alter_statements.append(
                "ALTER TABLE questions ADD COLUMN pending_answer_author_id VARCHAR(64)"
            )
        if alter_statements:
            with eng.connect() as conn:
                for stmt in alter_statements:
                    conn.execute(text(stmt))
                conn.commit()
    except Exception:
        pass

_migrate_questions_table(engine)

app = FastAPI(title=settings.app_name)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
async def index_page() -> str:
    """Главная страница со ссылками на чат и проверку."""
    return """
<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"/><title>Buddy</title></head>
<body style="font-family:system-ui;max-width:600px;margin:40px auto;padding:20px">
  <h1>Buddy — онбординг-агент</h1>
  <p>Сервер работает.</p>
  <ul>
    <li><a href="/chat" style="font-size:18px">Открыть чат</a></li>
    <li><a href="/debug">Проверка LLM</a></li>
  </ul>
  <p style="color:#666;font-size:14px">Если чат не открывается — убедись, что сервер запущен: <code>uvicorn app.main:app --port 8000</code></p>
</body>
</html>
"""


@app.get("/health", response_class=PlainTextResponse)
async def healthcheck() -> str:
    """Для проверки живости (curl, мониторинг)."""
    return "Buddy Mattermost agent is running"


@app.get("/debug", response_class=PlainTextResponse)
async def debug_status() -> str:
    """Проверка: настроен ли LLM (нужен для умных ответов)."""
    key = settings.openrouter_api_key
    has_key = bool(key and key.startswith("sk-"))
    return (
        f"LLM (OpenRouter): {'настроен' if has_key else 'НЕ настроен'}\n"
        f"Для умных ответов добавь OPENROUTER_API_KEY в .env и перезапусти сервер."
    )


@app.get("/chat", response_class=HTMLResponse)
async def chat_page() -> str:
    """Веб-чат для демо без Mattermost."""
    llm_ok = bool(settings.openrouter_api_key and settings.openrouter_api_key.startswith("sk-"))
    llm_status = "LLM настроен" if llm_ok else "LLM не настроен (добавь OPENROUTER_API_KEY в .env)"
    return (
        """
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <title>Buddy – онбординг-агент</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; background: #f4f5f7; }
    .app { max-width: 800px; margin: 0 auto; height: 100vh; display: flex; flex-direction: column; }
    header { padding: 16px 20px; background: #0058cc; color: white; font-weight: 600; }
    main { flex: 1; padding: 16px 20px; overflow-y: auto; }
    .bubble { max-width: 75%; padding: 10px 14px; border-radius: 16px; margin-bottom: 8px; white-space: pre-wrap; }
    .me { margin-left: auto; background: #e1f3ff; border-bottom-right-radius: 4px; }
    .bot { margin-right: auto; background: white; border-bottom-left-radius: 4px; }
    .meta { font-size: 11px; color: #667; margin-bottom: 12px; }
    footer { padding: 12px 16px; background: #fff; border-top: 1px solid #dde1e6; display: flex; gap: 8px; }
    input[type="text"] { flex: 1; padding: 8px 10px; border-radius: 8px; border: 1px solid #ccd0d5; font-size: 14px; }
    button { padding: 8px 14px; border-radius: 8px; border: none; background: #0058cc; color: white; font-weight: 500; cursor: pointer; }
    button:disabled { opacity: 0.6; cursor: default; }
  </style>
</head>
<body>
  <div class="app">
    <header>Buddy – демо онбординга <span style="font-size:12px;opacity:0.9">("""
        + llm_status
        + """)</span></header>
    <main id="messages">
      <div class="bubble bot">
        Привет! Я Buddy — ИИ-помощник по онбордингу. Задавай любой вопрос: о компании, отпуске, доступах, процессах. Отвечаю из базы знаний.
      </div>
      <div class="meta">Пиши вопрос и нажми Enter. Например: «расскажи о компании», «как оформить отпуск».</div>
    </main>
    <footer>
      <input id="input" type="text" placeholder="Напиши сообщение и нажми Enter…" />
      <button id="send">Отправить</button>
    </footer>
  </div>
  <script>
    const messagesEl = document.getElementById('messages');
    const inputEl = document.getElementById('input');
    const sendBtn = document.getElementById('send');

    const userId = 'demo-' + (localStorage.getItem('buddy-demo-user-id') || Math.random().toString(36).slice(2));
    localStorage.setItem('buddy-demo-user-id', userId);

    function appendBubble(text, who) {
      const div = document.createElement('div');
      div.className = 'bubble ' + (who === 'me' ? 'me' : 'bot');
      div.textContent = text;
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    async function sendMessage() {
      const text = inputEl.value.trim();
      if (!text) return;
      inputEl.value = '';
      appendBubble(text, 'me');
      sendBtn.disabled = true;

      const payload = {
        user_name: 'web-demo-user',
        bot_user_id: 'buddy-bot-id',
        post: JSON.stringify({
          id: 'web-' + Date.now(),
          user_id: userId,
          channel_id: 'web-demo-channel',
          message: text,
          root_id: ''
        })
      };

      try {
        const url = (window.location.origin || '') + '/mattermost/webhook';
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const reply = await resp.text();
        if (!resp.ok) {
          appendBubble('Ошибка ' + resp.status + ': ' + reply, 'bot');
        } else {
          appendBubble(reply, 'bot');
        }
      } catch (e) {
        appendBubble('Ошибка при обращении к серверу: ' + e, 'bot');
      } finally {
        sendBtn.disabled = false;
        inputEl.focus();
      }
    }

    sendBtn.addEventListener('click', sendMessage);
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  </script>
</body>
</html>
    """
    )


@app.post("/api/knowledge", response_class=PlainTextResponse)
async def add_knowledge_item(payload: Dict[str, Any], db: Session = Depends(get_db)) -> str:
    """
    Простой API для добавления записи в базу знаний.
    Ожидает JSON: { "question": "...", "answer": "...", "tags": "optional,comma,separated" }
    """
    question = (payload.get("question") or "").strip()
    answer = (payload.get("answer") or "").strip()
    tags = (payload.get("tags") or "").strip() or None

    if not question or not answer:
        raise HTTPException(status_code=400, detail="Поле 'question' и 'answer' обязательны")

    item = KnowledgeItem(question=question, answer=answer, tags=tags)
    db.add(item)
    db.commit()
    db.refresh(item)
    return f"OK: knowledge_item_id={item.id}"


@app.get("/admin/knowledge", response_class=HTMLResponse)
async def admin_knowledge_page() -> str:
    """
    Простейшая страница для ручного добавления записей в базу знаний.
    """
    return """
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <title>Buddy – база знаний</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; background: #f4f5f7; margin: 0; }
    .app { max-width: 800px; margin: 0 auto; padding: 24px 20px 40px; }
    h1 { margin-top: 0; color: #172b4d; }
    label { display: block; font-size: 13px; font-weight: 600; margin-top: 16px; margin-bottom: 4px; color: #253858; }
    textarea, input[type="text"] { width: 100%; box-sizing: border-box; border-radius: 8px; border: 1px solid #ccd0d5; padding: 8px 10px; font-size: 14px; }
    textarea { min-height: 80px; resize: vertical; }
    button { margin-top: 20px; padding: 8px 16px; border-radius: 8px; border: none; background: #0058cc; color: white; font-weight: 500; cursor: pointer; }
    button:disabled { opacity: 0.6; cursor: default; }
    .status { margin-top: 12px; font-size: 13px; color: #344563; white-space: pre-wrap; }
    .hint { font-size: 12px; color: #6b778c; margin-top: 4px; }
  </style>
</head>
<body>
  <div class="app">
    <h1>Buddy – база знаний</h1>
    <p>Здесь можно вручную добавить пару «вопрос/ответ», которые Buddy будет использовать при ответах новичкам.</p>
    <label for="q">Вопрос</label>
    <textarea id="q" placeholder="Например: Где посмотреть дорожную карту продукта?"></textarea>

    <label for="a">Ответ</label>
    <textarea id="a" placeholder="Например: В Confluence, страница Product Roadmap, ссылка ..."></textarea>

    <label for="tags">Теги (опционально)</label>
    <input id="tags" type="text" placeholder="onboarding,product,roadmap" />
    <div class="hint">Теги можно использовать позже для маршрутизации к конкретным командам.</div>

    <button id="save">Сохранить</button>
    <div class="status" id="status"></div>
  </div>
  <script>
    const qEl = document.getElementById('q');
    const aEl = document.getElementById('a');
    const tagsEl = document.getElementById('tags');
    const statusEl = document.getElementById('status');
    const saveBtn = document.getElementById('save');

    async function save() {
      const question = qEl.value.trim();
      const answer = aEl.value.trim();
      const tags = tagsEl.value.trim();

      if (!question || !answer) {
        statusEl.textContent = "Нужно заполнить и вопрос, и ответ.";
        return;
      }

      saveBtn.disabled = true;
      statusEl.textContent = "Сохраняю...";

      try {
        const resp = await fetch('/api/knowledge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question, answer, tags })
        });
        const text = await resp.text();
        if (!resp.ok) {
          statusEl.textContent = "Ошибка: " + text;
        } else {
          statusEl.textContent = text;
          qEl.value = "";
          aEl.value = "";
          tagsEl.value = "";
        }
      } catch (e) {
        statusEl.textContent = "Ошибка сети: " + e;
      } finally {
        saveBtn.disabled = false;
      }
    }

    saveBtn.addEventListener('click', save);
  </script>
</body>
</html>
    """


def get_or_create_user(db: Session, mattermost_user_id: str, username: Optional[str]) -> User:
    user = db.scalar(select(User).where(User.mattermost_user_id == mattermost_user_id))
    if user:
        return user
    user = User(mattermost_user_id=mattermost_user_id, username=username, state="new", onboarding_step_index=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _is_yes_confirmation(text: str) -> bool:
    normalized = " ".join((text or "").strip().lower().split())
    yes_variants = {"да", "yes", "ok", "ок", "ага", "подтверждаю"}
    if normalized in yes_variants:
        return True
    return normalized.startswith("да ") or "отправляй" in normalized


def _is_no_confirmation(text: str) -> bool:
    normalized = " ".join((text or "").strip().lower().split())
    no_variants = {"нет", "no", "не", "неа", "отмена", "стоп"}
    if normalized in no_variants:
        return True
    return normalized.startswith("нет ") or "не отправляй" in normalized


async def handle_new_message(payload: Dict[str, Any], db: Session) -> str:
    """
    Handle incoming Mattermost webhook event.
    This handler assumes payload similar to outgoing webhook / plugin event:
    {
      "post": "{\"id\": ..., \"user_id\": ..., \"channel_id\": ..., \"message\": \"...\", \"root_id\": ...}",
      "user_name": "...",
      ...
    }
    """
    post_raw = payload.get("post")
    if not post_raw:
        raise HTTPException(status_code=400, detail="Missing 'post' in payload")

    import json

    post = json.loads(post_raw)
    text: str = (post.get("message") or "").strip()
    user_id: str = post["user_id"]
    channel_id: str = post["channel_id"]
    username: Optional[str] = payload.get("user_name")
    root_id: Optional[str] = post.get("root_id") or None

    # Ignore messages from the bot itself (to avoid loops)
    if user_id == payload.get("bot_user_id"):
        return "ok"

    # If this is a reply in a thread started by Buddy in moderator channel,
    # process moderator answer/approval workflow.
    if root_id and channel_id == settings.mattermost_moderator_channel_id:
        await handle_human_answer(db=db, root_post_id=root_id, text=text, author_user_id=user_id)
        return "ok"

    user = get_or_create_user(db, mattermost_user_id=user_id, username=username)

    # Демо-чат (web-demo-channel): ВСЕГДА только ИИ — никаких скриптов, никаких шагов
    if channel_id == "web-demo-channel":
        if not text or len(text.strip()) < 2:
            return "Напиши вопрос подлиннее, например: «расскажи о компании» или «как оформить отпуск»."
        user.state = "qa"
        if not user.role:
            user.role = "новичок"
        db.commit()
        return await handle_question(db=db, user=user, text=text, channel_id=channel_id)

    # Mattermost: приветствие и роль
    lowered = text.lower()
    if user.state == "new" or any(trigger in lowered for trigger in ["start", "привет", "hello", "hi", "онбординг"]):
        user.state = "awaiting_role"
        db.commit()
        return (
            "Привет! Я Buddy, помогу с первыми шагами в компании.\n\n"
            "Расскажи, какая у тебя роль? Например: backend, frontend, маркетинг, менеджер, дизайнер."
        )

    if user.state == "awaiting_role":
        user.role = extract_role_from_message(text)
        user.state = "qa"
        db.commit()
        display_role = get_display_role(user.role)
        return (
            f"Супер, {display_role}!\n\n"
            "Задавай любые вопросы — поищу в базе знаний и отвечу."
        )

    if user.state in ("qa", "onboarding"):
        if user.state == "onboarding":
            user.state = "qa"
            db.commit()
        return await handle_question(db=db, user=user, text=text, channel_id=channel_id)

    return "Напиши «start» или «привет» — начнём заново."


def _extract_search_terms(query: str) -> list[str]:
    """Извлекает значимые слова для поиска. «Расскажи о компании» → [компания, компании]."""
    stopwords = {
        "расскажи", "расскажите", "о", "про", "что", "как", "где", "когда", "почему",
        "какой", "какая", "какие", "кто", "чем", "зачем", "это", "и", "в", "на", "с",
        "для", "к", "из", "у", "при", "по", "до", "от", "после", "мне", "мне", "можно",
    }
    words = []
    for w in query.lower().split():
        w = w.strip(".,?!:;\"'")
        if len(w) >= 2 and w not in stopwords and not w.isdigit():
            words.append(w)
    return words


async def handle_question(db: Session, user: User, text: str, channel_id: str) -> str:
    from sqlalchemy import or_

    query_text = text.lower()
    terms = _extract_search_terms(text)

    # Поиск: полная фраза + по ключевым словам (чтобы «расскажи о компании» находило про компанию)
    conditions = [
        KnowledgeItem.question.ilike(f"%{query_text}%"),
        KnowledgeItem.answer.ilike(f"%{query_text}%"),
        KnowledgeItem.tags.ilike(f"%{query_text}%"),
    ]
    for term in terms[:5]:  # до 5 ключевых слов
        conditions.extend([
            KnowledgeItem.question.ilike(f"%{term}%"),
            KnowledgeItem.answer.ilike(f"%{term}%"),
            KnowledgeItem.tags.ilike(f"%{term}%"),
        ])

    stmt = (
        select(KnowledgeItem)
        .where(or_(*conditions))
        .order_by(KnowledgeItem.created_at.desc())
        .limit(20)
    )
    rows = list(db.scalars(stmt))
    # Сортируем по релевантности: больше совпадений с запросом — выше
    if terms and rows:
        def score(item):
            t = f"{item.question} {item.answer} {(item.tags or '')}".lower()
            return sum(1 for term in terms if term in t)
        rows = sorted(rows, key=score, reverse=True)
    items = rows

    known, answer = await answer_from_knowledge(
        question=text, knowledge_items=items, user_role=user.role
    )

    question = Question(user_id=user.id, text=text, mattermost_channel_id=channel_id)
    db.add(question)
    db.commit()
    db.refresh(question)

    if known:
        question.status = QuestionStatusEnum.ANSWERED
        db.add(
            Answer(
                question_id=question.id,
                author_type="bot",
                author_mattermost_user_id=None,
                text=answer,
            )
        )
        db.commit()
        return answer

    # Ask moderators in a separate channel.
    if not settings.mattermost_moderator_channel_id:
        fallback = (
            "Такого в базе знаний пока нет, а чат модератора не настроен. "
            "Лучше уточни у тимлида или наставника — они подскажут."
        )
        return fallback

    expert_text = (
        f"Коллеги, вопрос от новичка @{user.username or user.mattermost_user_id}:\n"
        f"> {text}\n\n"
        "Ответьте в этом треде. После вашего ответа я отдельно спрошу подтверждение перед отправкой пользователю."
    )
    root_post_id = await post_message(
        channel_id=settings.mattermost_moderator_channel_id,
        text=expert_text,
        root_id=None,
    )

    question.status = QuestionStatusEnum.AWAITING_HUMAN
    question.mattermost_root_post_id = root_post_id
    db.commit()

    return (
        "Хороший вопрос! В базе знаний такого пока нет — я уже спросил коллег. "
        "Как только ответят, напишу тебе сюда."
    )


async def handle_human_answer(db: Session, root_post_id: str, text: str, author_user_id: str) -> None:
    question = db.scalar(select(Question).where(Question.mattermost_root_post_id == root_post_id))
    if not question:
        return

    # 1) Если черновика ответа ещё нет — сохраняем его и просим подтверждение.
    if not question.pending_answer_text:
        question.pending_answer_text = text
        question.pending_answer_author_id = author_user_id
        db.commit()
        await post_message(
            channel_id=settings.mattermost_moderator_channel_id,
            root_id=root_post_id,
            text=(
                "Принял ответ:\n"
                f"> {text}\n\n"
                "Могу отправить этот ответ пользователю и сохранить в базу знаний?\n"
                "Ответьте в этом треде: `да` или `нет`."
            ),
        )
        return

    # 2) Есть черновик — ждём подтверждение отправки.
    if _is_yes_confirmation(text):
        final_answer = question.pending_answer_text
        final_author_id = question.pending_answer_author_id

        question.status = QuestionStatusEnum.ANSWERED
        question.pending_answer_text = None
        question.pending_answer_author_id = None
        db.add(
            Answer(
                question_id=question.id,
                author_type="human",
                author_mattermost_user_id=final_author_id,
                text=final_answer,
            )
        )
        db.add(
            KnowledgeItem(
                question=question.text,
                answer=final_answer,
                tags="moderator_validated",
                source_question_id=question.id,
            )
        )
        db.commit()

        if question.mattermost_channel_id:
            reply = f"Коллеги ответили на твой вопрос:\n\n> {question.text}\n\n{final_answer}"
            await post_message(channel_id=question.mattermost_channel_id, text=reply)

        await post_message(
            channel_id=settings.mattermost_moderator_channel_id,
            root_id=root_post_id,
            text="Готово: отправил ответ пользователю и сохранил вопрос/ответ в базу знаний.",
        )
        return

    if _is_no_confirmation(text):
        question.pending_answer_text = None
        question.pending_answer_author_id = None
        db.commit()
        await post_message(
            channel_id=settings.mattermost_moderator_channel_id,
            root_id=root_post_id,
            text="Ок, не отправляю. Напишите новый вариант ответа в этом треде.",
        )
        return

    # 3) Если пришёл новый текст вместо "да/нет", считаем это обновлённым черновиком.
    question.pending_answer_text = text
    question.pending_answer_author_id = author_user_id
    db.commit()
    await post_message(
        channel_id=settings.mattermost_moderator_channel_id,
        root_id=root_post_id,
        text=(
            "Обновил черновик ответа.\n"
            "Можно отправить пользователю и сохранить в базу знаний?\n"
            "Ответьте: `да` или `нет`."
        ),
    )


@app.post("/mattermost/webhook", response_class=PlainTextResponse)
async def mattermost_webhook(payload: Dict[str, Any], db: Session = Depends(get_db)) -> str:
    """
    Entry point for Mattermost outgoing webhook or plugin.

    For demo without Mattermost you can `curl` this endpoint with payloads
    described in README.
    """
    reply = await handle_new_message(payload=payload, db=db)
    return reply

