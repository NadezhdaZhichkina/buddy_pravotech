import ast
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from sqlalchemy import Column, DateTime, Integer, Text, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

Base = declarative_base()


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    tags = Column(Text, nullable=True)


class ModerationTicket(Base):
    __tablename__ = "moderation_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    requester_username = Column(Text, nullable=False)
    question = Column(Text, nullable=False)
    user_role = Column(Text, nullable=True)
    user_circle = Column(Text, nullable=True)
    draft_answer = Column(Text, nullable=True)
    final_answer = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="in_progress")  # in_progress | sent | rejected
    moderator_username = Column(Text, nullable=True)
    delivered_to_user = Column(Integer, nullable=False, default=0)  # 0/1 for sqlite portability
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class _PatchItem:
    """Обёртка для записей из knowledge_moderator.json — совместима с _score()."""

    def __init__(self, question: str, answer: str, tags: str | None = None):
        self.question = question
        self.answer = answer
        self.tags = tags


def _extract_seed_items() -> list[dict]:
    """Parse SEED_ITEMS from scripts/seed_knowledge.py without imports."""
    seed_path = Path(__file__).resolve().parent.parent / "scripts" / "seed_knowledge.py"
    src = seed_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SEED_ITEMS":
                    return ast.literal_eval(node.value)
    return []


# Алиасы для поиска: короткие формы → термины в базе знаний
_SEARCH_ALIASES = {
    "мм": ["mchat", "mattermost"],
    "мчат": ["mchat"],
    "mchat": ["mchat", "mattermost"],
    "mattermost": ["mchat", "mattermost"],
    "кб": ["корпоративная", "база", "знаний"],
}

# Окончания для простого стемминга (убираем для поиска словоформ)
_RU_ENDINGS = ("ов", "ам", "ами", "ах", "ей", "ий", "ия", "ие", "ью", "ом", "ем")


def _extract_search_terms(query: str) -> list[str]:
    stopwords = {
        "расскажи",
        "расскажите",
        "о",
        "про",
        "что",
        "как",
        "где",
        "когда",
        "почему",
        "какой",
        "какая",
        "какие",
        "кто",
        "чем",
        "зачем",
        "это",
        "и",
        "в",
        "на",
        "с",
        "для",
        "к",
        "из",
        "у",
        "при",
        "по",
        "до",
        "от",
        "после",
        "мне",
        "можно",
    }
    words = []
    for w in query.lower().split():
        w = w.strip(".,?!:;\"'")
        if len(w) >= 2 and w not in stopwords and not w.isdigit():
            words.append(w)
    return words


def _expand_search_terms(terms: list[str], original_query: str) -> list[str]:
    """
    Расширяет термины поиска: стемминг (каналов→канал), алиасы (мм→mchat).
    Улучшает поиск по уточняющим вопросам вроде «пришли названия каналов».
    """
    expanded = set(terms)
    # Добавляем алиасы
    for t in terms:
        if t in _SEARCH_ALIASES:
            expanded.update(_SEARCH_ALIASES[t])
    # Простой стемминг для русских слов
    for t in terms:
        if not re.search(r"[a-zа-яё]", t):
            continue
        if len(t) < 4:
            continue
        for ending in _RU_ENDINGS:
            if t.endswith(ending) and len(t) > len(ending) + 2:
                stem = t[: -len(ending)]
                if len(stem) >= 3:
                    expanded.add(stem)
                break
        # каналы → канал (ы)
        if t.endswith("ы") and len(t) > 2:
            expanded.add(t[:-1])
    # Аббревиатуры из запроса (ММ, MChat) — original_query сохраняет регистр
    for acr in _extract_upper_acronyms(original_query):
        if acr in _SEARCH_ALIASES:
            expanded.update(_SEARCH_ALIASES[acr])
    return list(expanded)


def _extract_upper_acronyms(text: str) -> list[str]:
    if not text:
        return []
    # Например: CRM, OKR, КБ, ИПР
    tokens = re.findall(r"(?<!\w)[A-ZА-ЯЁ]{2,6}(?!\w)", text)
    seen = set()
    result = []
    for t in tokens:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            result.append(tl)
    return result


def _normalize_question_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\sа-яёa-z0-9]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _n(t: str) -> str:
    """Нормализация для дедупликации."""
    return _normalize_question_text(t)


def _looks_like_abbreviation_query(question: str) -> bool:
    original = (question or "").strip()
    q = original.lower()
    markers = (
        "аббревиатур",
        "сокращени",
        "расшифровк",
        "что за ",
        "что значит ",
        "как расшифровывается",
    )
    if any(m in q for m in markers):
        return True
    # Формы вроде "что такое КБ?"
    if bool(re.search(r"(что такое|что значит)\s+[A-ZА-ЯЁ]{2,6}\b", original, flags=re.IGNORECASE)):
        return True

    # Короткий запрос-термин вроде "КБ" / "кдп" / "CRM".
    cleaned = re.sub(r"[\s?!.,:;\"'()\\[\\]{}]+", "", q)
    if cleaned and bool(re.fullmatch(r"[a-zа-яё0-9]{2,4}", cleaned)):
        common_short_words = {"как", "где", "кто", "что", "это", "мне", "тут", "там", "или", "надо", "можно"}
        if cleaned not in common_short_words:
            vowels = set("aeiouyауоыиэяюёе")
            if (not any(ch in vowels for ch in cleaned)) or cleaned.isupper():
                return True
    return False


def _contains_whole_token(text: str, token: str) -> bool:
    if not text or not token:
        return False
    return bool(re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text.lower()))


def _auto_tags_from_qa(question: str, answer: str, limit: int = 6) -> str:
    base_terms = _extract_search_terms(f"{question} {answer}")
    acronyms = _extract_upper_acronyms(f"{question} {answer}")
    tags = []
    seen = set()

    for t in acronyms + base_terms:
        tag = (t or "").strip().lower()
        if not tag:
            continue
        tag = re.sub(r"[^a-zа-яё0-9_+-]+", "_", tag).strip("_")
        if len(tag) < 2:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= limit:
            break

    return ",".join(tags)


def _find_existing_item_by_normalized_question(db, question: str) -> KnowledgeItem | None:
    normalized = _normalize_question_text(question)
    if not normalized:
        return None
    for row in db.query(KnowledgeItem).all():
        if _normalize_question_text(row.question) == normalized:
            return row
    return None


def _score(item: KnowledgeItem, query_text: str, terms: list[str]) -> int:
    q = (item.question or "").lower()
    a = (item.answer or "").lower()
    t = (item.tags or "").lower()
    full = f"{q} {a} {t}"

    score = 0
    if query_text:
        # Полное вхождение запроса — только как отдельное слово/фраза, иначе «привет» матчит «приветственный»
        qt = query_text.strip()
        if len(qt) >= 5:
            if qt in full:
                score += 8
        else:
            # Короткий запрос — только целое слово, не часть другого
            if re.search(rf"(^|[\s\W]){re.escape(qt)}([\s\W]|$)", full):
                score += 8

    for term in terms:
        if len(term) < 2:
            continue
        if term in q:
            score += 3
        elif term in a:
            score += 2
        elif term in t:
            score += 1
    return score


def _get_streamlit_db_url() -> str:
    """БД для Streamlit: STREAMLIT_DATABASE_URL для постоянного хранения на Cloud, иначе локальный SQLite."""
    # Принудительный fallback — не читаем secrets, сразу SQLite в файл (не :memory: — иначе данные теряются при rerun)
    if os.getenv("BUDDY_FORCE_SQLITE") == "1":
        db_path = Path(__file__).resolve().parent.parent / "buddy_streamlit.db"
        return f"sqlite:///{db_path}"
    url = (
        os.getenv("STREAMLIT_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or ""
    ).strip()
    if not url:
        try:
            import streamlit as _st
            sec = getattr(_st, "secrets", None)
            if sec is not None:
                # Прямые ключи
                v = sec.get("STREAMLIT_DATABASE_URL") or sec.get("DATABASE_URL")
                if isinstance(v, str) and v.strip():
                    url = v.strip()
                elif isinstance(v, dict) and isinstance(v.get("url"), str):
                    url = (v.get("url") or "").strip()
                # Streamlit connections: connections.postgres
                if not url:
                    conns = sec.get("connections") if isinstance(sec.get("connections"), dict) else None
                    if conns:
                        pg = conns.get("postgres") or conns.get("postgresql")
                        if isinstance(pg, str) and pg.strip():
                            url = pg.strip()
                        elif isinstance(pg, dict) and isinstance(pg.get("url"), str):
                            url = (pg.get("url") or "").strip()
        except Exception:
            pass
        url = (url or "").strip()
    if url and isinstance(url, str) and ("postgresql" in url or "postgres" in url):
        if url.startswith("postgres://"):
            url = "postgresql://" + url[10:]
        # Supabase: порт 5432 даёт "Cannot assign requested address" на Streamlit Cloud — используем pooler 6543
        if "db." in url and ".supabase.co" in url:
            m = re.search(r"db\.([a-z0-9]+)\.supabase\.co", url)
            if m:
                proj = m.group(1)
                url = re.sub(r"@db\.[a-z0-9]+\.supabase\.co:\d+", "@aws-0-eu-central-1.pooler.supabase.com:6543", url)
                url = re.sub(r"://postgres:", f"://postgres.{proj}:", url, count=1)
        if "sslmode" not in url:
            url = url + ("&" if "?" in url else "?") + "sslmode=require"
        try:
            make_url(url)  # валидация — избегаем 'NoneType' object is not iterable
        except Exception:
            url = ""
    if url and isinstance(url, str) and ("postgresql" in url or "postgres" in url):
        return url
    db_path = Path(__file__).resolve().parent.parent / "buddy_streamlit.db"
    return f"sqlite:///{db_path}"


def _get_moderator_patch_path() -> Path:
    """Путь к JSON с ответами модератора (резервное хранилище)."""
    return Path(__file__).resolve().parent.parent / "knowledge_moderator.json"


def _save_to_moderator_patch(question: str, answer: str, tags: str | None = None) -> None:
    """Дублирует запись модератора в JSON — резерв на случай проблем с БД."""
    try:
        path = _get_moderator_patch_path()
        data = _load_moderator_patch()
        q, a = (question or "").strip(), (answer or "").strip()
        if not q or not a:
            return
        # Обновить существующий или добавить
        for i, it in enumerate(data):
            if isinstance(it, dict) and (it.get("question") or "").strip() == q:
                data[i] = {"question": q, "answer": a, "tags": (tags or "").strip() or ""}
                path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                return
        data.append({"question": q, "answer": a, "tags": (tags or "").strip() or ""})
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def _load_moderator_patch() -> list[dict]:
    """Загружает дополнения модератора из JSON."""
    try:
        path = _get_moderator_patch_path()
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return [x for x in raw if isinstance(x, dict)]
            if isinstance(raw, dict) and raw.get("question") and raw.get("answer"):
                return [raw]
    except Exception:
        pass
    return []


def _notify_mattermost_new_ticket(ticket_id: int, question: str, requester: str) -> None:
    """Опционально: отправить уведомление о новом тикете в Mattermost. Если не настроено — ничего не делать."""
    base_url = (os.getenv("MATTERMOST_BASE_URL") or "").strip()
    token = (os.getenv("MATTERMOST_BOT_TOKEN") or "").strip()
    channel_id = (os.getenv("MATTERMOST_MODERATOR_CHANNEL_ID") or "").strip()
    if not all([base_url, token, channel_id]):
        return
    short_q = (question or "")[:200] + ("..." if len(question or "") > 200 else "")
    text = f"Новый тикет #{ticket_id} от @{requester}:\n\n{short_q}"
    payload = json.dumps({"channel_id": channel_id, "message": text}).encode("utf-8")
    req = urlrequest.Request(
        f"{base_url.rstrip('/')}/api/v4/posts",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            resp.read()
    except (urlerror.URLError, urlerror.HTTPError, TimeoutError):
        pass


class StreamlitChatService:
    def __init__(self, openrouter_api_key: str = "", openrouter_model: str = "openai/gpt-4.1-mini", db_url_override: str | None = None) -> None:
        db_url = (db_url_override or _get_streamlit_db_url()).strip()
        if not db_url:
            db_url = f"sqlite:///{Path(__file__).resolve().parent.parent / 'buddy_streamlit.db'}"
        engine_kw: dict = {"future": True}
        if db_url.startswith("sqlite"):
            engine_kw["connect_args"] = {"check_same_thread": False}
            if ":memory:" in db_url:
                engine_kw["poolclass"] = StaticPool
        else:
            engine_kw["pool_pre_ping"] = True
            engine_kw["connect_args"] = {"connect_timeout": 10}
        self.engine = create_engine(db_url, **engine_kw)
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)

        self.openrouter_api_key = (openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")).strip()
        self.openrouter_model = (openrouter_model or os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")).strip()
        # Не ограничиваемся префиксом sk-, чтобы не ловить ложный "LLM выключен"
        self.llm_enabled = bool(self.openrouter_api_key)

        self._sync_seed_items()
        self._cleanup_legacy_test_tickets()

    def _sync_seed_items(self) -> None:
        seed_items = _extract_seed_items()
        if seed_items is None or not isinstance(seed_items, list):
            seed_items = []
        patch_items = _load_moderator_patch()
        with self.SessionLocal() as db:
            existing = {row.question: row for row in db.query(KnowledgeItem).all()}
            changed = False
            for item in seed_items:
                q = item.get("question", "")
                a = item.get("answer", "")
                t = item.get("tags")
                row = existing.get(q)
                if row is None:
                    db.add(KnowledgeItem(question=q, answer=a, tags=t))
                    changed = True
            for it in patch_items:
                if not isinstance(it, dict):
                    continue
                q = (it.get("question") or "").strip()
                a = (it.get("answer") or "").strip()
                t = it.get("tags")
                if not q or not a:
                    continue
                row = existing.get(q) or _find_existing_item_by_normalized_question(db, q)
                if row:
                    row.answer = a
                    row.tags = t or row.tags
                else:
                    db.add(KnowledgeItem(question=q, answer=a, tags=t))
                    existing[q] = None
                changed = True
            if changed:
                db.commit()
            else:
                db.rollback()

    def _cleanup_legacy_test_tickets(self) -> None:
        """Удаляем старые тестовые тикеты из ранних версий интерфейса."""
        with self.SessionLocal() as db:
            rows = (
                db.query(ModerationTicket)
                .filter(
                    (ModerationTicket.requester_username == "system_test")
                    | (ModerationTicket.question.like("Тестовый тикет %"))
                    | (ModerationTicket.question.like("test ticket %"))
                )
                .all()
            )
            if not rows:
                db.rollback()
                return
            for row in rows:
                db.delete(row)
            db.commit()

    def create_moderation_ticket(
        self,
        question: str,
        requester_username: str,
        user_role: str | None = None,
        user_circle: str | None = None,
    ) -> int:
        q = (question or "").strip()
        requester = (requester_username or "streamlit_user").strip().lower()
        if not q:
            raise ValueError("Question is required for moderation ticket")

        with self.SessionLocal() as db:
            existing = (
                db.query(ModerationTicket)
                .filter(
                    ModerationTicket.requester_username == requester,
                    ModerationTicket.question == q,
                    ModerationTicket.status.in_(("in_progress", "pending", "awaiting_approval")),
                )
                .order_by(ModerationTicket.id.desc())
                .first()
            )
            if existing:
                return int(existing.id)

            ticket = ModerationTicket(
                requester_username=requester,
                question=q,
                user_role=user_role,
                user_circle=user_circle,
                status="in_progress",
            )
            db.add(ticket)
            db.commit()
            db.refresh(ticket)
            ticket_id = int(ticket.id)
            _notify_mattermost_new_ticket(ticket_id=ticket_id, question=q, requester=requester)
            return ticket_id

    def save_manual_knowledge(
        self,
        question: str,
        answer: str,
        tags: str | None = None,
    ) -> dict:
        q = (question or "").strip()
        a = (answer or "").strip()
        if not q or not a:
            raise ValueError("Question and answer are required")

        final_tags = (tags or "").strip()
        if not final_tags:
            final_tags = _auto_tags_from_qa(q, a)

        # Сразу в patch — не потеряем при сбоях БД
        _save_to_moderator_patch(q, a, final_tags)

        with self.SessionLocal() as db:
            existing = (
                db.query(KnowledgeItem).filter(KnowledgeItem.question == q).first()
                or _find_existing_item_by_normalized_question(db, q)
            )
            if existing:
                existing.question = q
                existing.answer = a
                existing.tags = final_tags or existing.tags
                db.commit()
                db.refresh(existing)
                return {"action": "updated", "id": int(existing.id), "tags": existing.tags or ""}

            row = KnowledgeItem(question=q, answer=a, tags=final_tags or None)
            db.add(row)
            db.commit()
            db.refresh(row)
        return {"action": "created", "id": int(row.id), "tags": row.tags or ""}

    def save_from_dialogue(self, question: str, answer: str, tags: str | None = "dialogue_learned") -> dict | None:
        """Самообучение: сохранить успешный Q&A из диалога в базу знаний."""
        q = (question or "").strip()
        a = (answer or "").strip()
        if not q or not a or len(a) < 10:
            return None
        try:
            return self.save_manual_knowledge(question=q, answer=a, tags=tags or "dialogue_learned")
        except Exception:
            return None

    def list_moderation_tickets(self, include_closed: bool = False) -> list[dict]:
        with self.SessionLocal() as db:
            query = db.query(ModerationTicket).filter(ModerationTicket.requester_username != "system_test")
            if not include_closed:
                query = query.filter(ModerationTicket.status.in_(("in_progress", "pending", "awaiting_approval")))
            rows = query.order_by(ModerationTicket.id.desc()).limit(50).all()
            return [
                {
                    "id": row.id,
                    "requester_username": row.requester_username,
                    "question": row.question,
                    "user_role": row.user_role,
                    "user_circle": row.user_circle,
                    "draft_answer": row.draft_answer,
                    "final_answer": row.final_answer,
                    "status": row.status,
                    "moderator_username": row.moderator_username,
                }
                for row in rows
            ]

    def resolve_ticket(
        self,
        ticket_id: int,
        answer: str,
        moderator_username: str,
        tags: str | None = None,
    ) -> dict | None:
        final_answer = (answer or "").strip()
        moderator = (moderator_username or "moderator").strip().lower()
        if not final_answer:
            return None

        with self.SessionLocal() as db:
            row = db.get(ModerationTicket, int(ticket_id))
            if not row:
                return None
            ticket_id_val = int(row.id)
            question_text = (row.question or "").strip()
            if not question_text:
                return None

            # Сначала сохраняем в JSON — гарантия, что не потеряем ответ модератора
            final_tags = (tags or "").strip() or _auto_tags_from_qa(question_text, final_answer, limit=10)
            _save_to_moderator_patch(question_text, final_answer, final_tags)

            row.draft_answer = None
            row.final_answer = final_answer
            row.status = "sent"
            row.moderator_username = moderator
            row.delivered_to_user = 0

            existing = (
                db.query(KnowledgeItem).filter(KnowledgeItem.question == question_text).first()
                or _find_existing_item_by_normalized_question(db, question_text)
            )
            if existing:
                existing.question = question_text
                existing.answer = final_answer
                existing.tags = final_tags or existing.tags
                action, knowledge_id = "updated", int(existing.id)
            else:
                kb_row = KnowledgeItem(
                    question=question_text,
                    answer=final_answer,
                    tags=final_tags or "moderator_validated",
                )
                db.add(kb_row)
                db.flush()
                action, knowledge_id = "created", int(kb_row.id)

            db.commit()

        return {
            "ticket_id": ticket_id_val,
            "knowledge_action": action,
            "knowledge_id": knowledge_id,
            "tags": final_tags,
            "status": "sent",
            "knowledge_verified": True,
        }

    def save_moderator_draft(self, ticket_id: int, draft_answer: str, moderator_username: str) -> bool:
        draft = (draft_answer or "").strip()
        moderator = (moderator_username or "moderator").strip().lower()

        with self.SessionLocal() as db:
            row = db.get(ModerationTicket, int(ticket_id))
            if not row:
                return False
            if draft:
                row.draft_answer = draft
            row.moderator_username = moderator
            row.status = "in_progress"
            db.commit()
            return True

    def reject_moderator_answer(self, ticket_id: int, moderator_username: str) -> bool:
        moderator = (moderator_username or "moderator").strip().lower()
        with self.SessionLocal() as db:
            row = db.get(ModerationTicket, int(ticket_id))
            if not row:
                return False
            row.draft_answer = None
            row.final_answer = (
                "На этот вопрос может ответить только твой лидер. "
                "Пожалуйста, обратись к лидеру своего круга."
            )
            row.status = "rejected"
            row.moderator_username = moderator
            row.delivered_to_user = 0
            db.commit()
            return True

    def pop_user_updates(self, requester_username: str) -> list[dict]:
        requester = (requester_username or "streamlit_user").strip().lower()
        with self.SessionLocal() as db:
            rows = (
                db.query(ModerationTicket)
                .filter(
                    ModerationTicket.requester_username == requester,
                    ModerationTicket.status.in_(("sent", "rejected", "approved")),
                    ModerationTicket.delivered_to_user == 0,
                )
                .order_by(ModerationTicket.id.asc())
                .all()
            )
            updates = [
                {
                    "ticket_id": row.id,
                    "question": row.question,
                    "answer": row.final_answer or "",
                    "status": row.status,
                }
                for row in rows
            ]
            for row in rows:
                row.delivered_to_user = 1
            if rows:
                db.commit()
            else:
                db.rollback()
            return updates

    def _retrieve_candidates_with_scores(
        self, question: str, limit: int = 8, history: list[dict] | None = None
    ) -> list[tuple[int, KnowledgeItem]]:
        # Контекст только из сообщений пользователя — иначе ответы ассистента (Buddy, наставник)
        # засоряют поиск и возвращаются одни и те же записи на разные вопросы.
        search_text = (question or "").strip()
        if history:
            for m in history[-4:]:  # последние 4 сообщения
                if m.get("role") != "user":
                    continue
                content = (m.get("content") or "").strip()
                if content:
                    search_text += " " + content
        query_text = search_text.lower().strip()
        terms = _extract_search_terms(search_text)
        terms = _expand_search_terms(terms, question)  # стемминг, алиасы (мм→mchat)
        # Берём все записи, приоритет — новейшие (ответы модератора имеют больший id)
        with self.SessionLocal() as db:
            items = list(
                db.scalars(select(KnowledgeItem).order_by(KnowledgeItem.id.desc()).limit(600))
            )
        # Дополнительно: ответы из knowledge_moderator.json (на случай рассинхрона с БД)
        patch_items = _load_moderator_patch()
        seen_questions = {(_n((i.question or "").strip())) for i in items}
        for it in patch_items:
            if not isinstance(it, dict):
                continue
            q, a = (it.get("question") or "").strip(), (it.get("answer") or "").strip()
            if not q or not a or _n(q) in seen_questions:
                continue
            seen_questions.add(_n(q))
            items.append(_PatchItem(question=q, answer=a, tags=it.get("tags")))

        scored = []
        for item in items:
            s = _score(item, query_text, terms)
            if s > 0:
                scored.append((s, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return []
        # Только если лучший кандидат достаточно релевантен (≥6)
        if scored[0][0] < 6:
            return []
        min_score = max(5, scored[0][0] - 1)
        return [(s, item) for s, item in scored if s >= min_score][:limit]

    def _retrieve_candidates(
        self, question: str, limit: int = 8, history: list[dict] | None = None
    ) -> list[KnowledgeItem]:
        return [item for _, item in self._retrieve_candidates_with_scores(question, limit=limit, history=history)]

    def has_strong_kb_match(self, question: str, history: list[dict] | None = None, min_score: int = 6) -> bool:
        """Есть ли в базе релевантный ответ (не заменять на тикет, если GPT добавил «уточнить»)."""
        scored = self._retrieve_candidates_with_scores(question, limit=1, history=history)
        return bool(scored) and scored[0][0] >= min_score

    def has_abbreviation_in_kb(self, question: str, history: list[dict] | None = None) -> bool:
        """Для запросов об аббревиатурах (КБ, ИПР и т.п.): есть ли в базе запись, где эта аббревиатура явно указана."""
        if not _looks_like_abbreviation_query(question):
            return True  # не запрос об аббревиатуре — пропускаем проверку
        acronyms = _extract_upper_acronyms(question)
        if not acronyms:
            return True
        scored = self._retrieve_candidates_with_scores(question, limit=5, history=history)
        if not scored:
            return False
        for _, item in scored:
            full = f"{(item.question or '').lower()} {(item.answer or '').lower()}"
            if all(_contains_whole_token(full, acr) for acr in acronyms):
                return True
        return False

    def _answer_with_llm(
        self,
        question: str,
        candidates: list[KnowledgeItem],
        user_role: str | None = None,
        user_circle: str | None = None,
    ) -> str | None:
        if not self.llm_enabled:
            return None

        facts = []
        for idx, item in enumerate(candidates[:6], start=1):
            facts.append(f"[Факт {idx}] Вопрос: {item.question}\nОтвет: {item.answer}")
        context = "\n\n".join(facts) if facts else "Нет релевантных фактов в базе знаний."

        profile_hint = ""
        if user_role or user_circle:
            profile_hint = f" Профиль пользователя: роль={user_role or 'не указана'}, круг={user_circle or 'не указан'}."

        system_prompt = (
            "Ты Buddy — просто друг в PravoTech. Общаешься тепло и по-человечески. "
            "Подсказываешь по чатам, культуре, знакомствам. Факты — только из базы, не придумывай. "
            "Если не знаешь — честно скажи, предложи уточнить у коллег."
            + profile_hint
        )
        user_prompt = (
            f"Вопрос пользователя: {question}\n\n"
            f"Факты из базы знаний:\n{context}\n\n"
            "Ответь по существу и дружелюбно, опираясь на факты. "
            "По вопросам что делать дальше — направляй к менеджеру по адаптации. "
            "Если данных не хватает, так и скажи и предложи уточнить у коллег."
        )

        payload = {
            "model": self.openrouter_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.6,
        }

        req = urlrequest.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.openrouter_api_key}",
                "Content-Type": "application/json",
                "X-Title": "Buddy Streamlit",
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return data["choices"][0]["message"]["content"].strip()
        except (urlerror.URLError, ValueError, KeyError, TimeoutError):
            return None

    def generate_reply(
        self,
        user_message: str,
        history: list[dict],
        profile: dict,
        next_task: dict | None = None,
        skip_retrieval: bool = False,
    ) -> str:
        """
        Генеративный режим: отвечает из базы знаний на вопросы, дружелюбно — на остальное.
        """
        if not self.llm_enabled:
            if skip_retrieval:
                return "Чем могу помочь? Спроси что угодно — про процессы, аббревиатуры, каналы."
            candidates = self._retrieve_candidates(user_message, limit=5, history=history)
            if candidates:
                return self._fallback_answer(candidates)
            return (
                "Хочу помочь, но LLM выключен. Напиши вопрос — поищу в базе. "
                "Или включи OPENROUTER_API_KEY для полноценного диалога."
            )

        if skip_retrieval:
            candidates = []
        else:
            candidates = self._retrieve_candidates(user_message, limit=6, history=history)
        kb_block = ""
        if candidates:
            facts = [f"• {item.question} → {item.answer}" for item in candidates[:5]]
            kb_block = (
                "Факты из базы знаний:\n" + "\n".join(facts)
                + "\n\nДля вопросов про компанию, процессы, аббревиатуры: отвечай ТОЛЬКО если факт напрямую отвечает на вопрос. "
                "Если факт не про то, о чём спрашивают — скажи «этого нет в базе» и предложи передать модератору."
            )
        else:
            kb_block = (
                "В базе знаний нет релевантных фактов по этому запросу. "
                "НЕ придумывай ответ. Скажи честно, что этого нет в базе, и предложи передать вопрос модератору."
            )

        role = profile.get("role") or "не указана"
        circle = profile.get("circle") or "не указан"
        progress = profile.get("progress") or {}
        done = [k for k, v in progress.items() if v]
        nt = f"По плану дальше: {next_task['title']} — {next_task['hint']}. По вопросам что делать — менеджер по адаптации." if next_task else "Все шаги welcome-курса пройдены."

        system = (
            "Ты Buddy — друг в PravoTech. Общаешься просто и тепло. "
            "По вопросам что делать дальше — направляй к менеджеру по адаптации (это не твоя роль). "
            "На вопросы про компанию, процессы, термины — отвечай только из базы знаний, не придумывай. "
            "Нет ответа — честно скажи, предложи передать модератору. "
            "Приветствия, «как дела» — свободно, по-дружески.\n\n"
            f"Профиль: роль={role}, круг={circle}. Сделано: {', '.join(done) or 'ничего'}. {nt}\n\n"
            f"{kb_block}"
        )

        messages = [{"role": "system", "content": system}]
        for m in history[-8:]:
            r = "user" if m.get("role") == "user" else "assistant"
            messages.append({"role": r, "content": (m.get("content") or "")[:2000]})
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": self.openrouter_model,
            "messages": messages,
            "temperature": 0.7,
        }
        req = urlrequest.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.openrouter_api_key}",
                "Content-Type": "application/json",
                "X-Title": "Buddy Streamlit",
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                reply = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                return reply if reply else "Не удалось сформировать ответ. Попробуй переформулировать."
        except (urlerror.URLError, ValueError, KeyError, TimeoutError):
            if candidates:
                return self._fallback_answer(candidates)
            return "Сейчас не могу ответить. Попробуй позже или передай вопрос модератору."

    def chat_reply(
        self,
        user_message: str,
        context: str,
        fallback: str,
    ) -> str:
        """Генерирует ответ через GPT по контексту. Fallback при отключённом LLM."""
        if not self.llm_enabled:
            return fallback
        system = "Ты Buddy — друг. Отвечай по контексту, коротко и по-дружески."
        user_prompt = f"Сообщение: «{user_message}»\nКонтекст: {context}\nОтвет:"
        try:
            req = urlrequest.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=json.dumps({
                    "model": self.openrouter_model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
                    "temperature": 0.7,
                }).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.openrouter_api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urlrequest.urlopen(req, timeout=15) as resp:
                reply = (json.loads(resp.read().decode("utf-8")).get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                return reply or fallback
        except (urlerror.URLError, ValueError, KeyError, TimeoutError):
            return fallback

    def _fallback_answer(self, candidates: list[KnowledgeItem]) -> str:
        if not candidates:
            return (
                "Хочу дать точный ответ, но сейчас в базе мало данных по этому запросу. "
                "Давай уточним вопрос или передадим его модератору."
            )
        if len(candidates) == 1:
            return f"Поняла, вот что могу подсказать:\n\n{candidates[0].answer}"
        return (
            "Смотри, нашла несколько полезных моментов:\n\n"
            f"1) {candidates[0].answer}\n\n"
            f"2) {candidates[1].answer}"
        )

    def answer_with_meta(
        self,
        question: str,
        user_role: str | None = None,
        user_circle: str | None = None,
    ) -> dict:
        q = (question or "").strip()
        if len(q) < 2:
            return {
                "answer": "Напиши вопрос подлиннее, например: «расскажи о компании» или «как оформить отпуск».",
                "needs_moderation": False,
                "source": "validation",
                "confidence": 0,
                "candidate_count": 0,
                "direct_question_match": False,
            }

        # Приоритет обучения: если модератор уже сохранял этот вопрос в БЗ,
        # отдаем ответ сразу из БЗ и не эскалируем повторно.
        normalized_q = _normalize_question_text(q)
        with self.SessionLocal() as db:
            exact_row = None
            for item in db.query(KnowledgeItem).all():
                if _normalize_question_text(item.question) == normalized_q:
                    exact_row = item
                    break
        if exact_row:
            return {
                "answer": f"Поняла, вот что могу подсказать:\n\n{exact_row.answer}",
                "needs_moderation": False,
                "source": "kb_exact",
                "confidence": 100,
                "candidate_count": 1,
                "direct_question_match": True,
                "exact_question_match": True,
            }

        terms = list(dict.fromkeys(_extract_search_terms(q)))
        scored_candidates = self._retrieve_candidates_with_scores(q, limit=8)
        candidates = [item for _, item in scored_candidates]
        top_score = scored_candidates[0][0] if scored_candidates else 0
        top_text = (
            f"{candidates[0].question} {candidates[0].answer} {(candidates[0].tags or '')}".lower()
            if candidates
            else ""
        )
        exact_question_match = any(
            _normalize_question_text(item.question) == normalized_q for item in candidates
        )

        direct_question_match = False
        if candidates:
            top_question = (candidates[0].question or "").lower().strip()
            normalized_q = q.lower().strip()
            if top_question and (normalized_q in top_question or top_question in normalized_q):
                direct_question_match = True
            elif terms:
                matched_in_top_question = sum(1 for term in terms if term in top_question)
                question_overlap_ratio = matched_in_top_question / max(1, len(terms))
                direct_question_match = (
                    matched_in_top_question >= 1 and question_overlap_ratio >= 0.5
                )

        abbreviation_guard = False
        if _looks_like_abbreviation_query(q):
            acronyms = _extract_upper_acronyms(question)
            # Если вопрос про аббревиатуру, а в найденном факте нет самой аббревиатуры — отправляем модератору.
            if acronyms:
                abbreviation_guard = not all(_contains_whole_token(top_text, acr) for acr in acronyms)
            else:
                abbreviation_guard = not direct_question_match

        if abbreviation_guard:
            return {
                "answer": (
                    "Не вижу в базе точной расшифровки для этого сокращения. "
                    "Передаю вопрос модератору, чтобы дать корректный ответ."
                ),
                "needs_moderation": True,
                "source": "abbreviation_guard",
                "confidence": top_score,
                "candidate_count": len(candidates),
                "direct_question_match": direct_question_match,
                "exact_question_match": exact_question_match,
            }

        matched_terms = 0
        if candidates and terms:
            matched_terms = sum(1 for term in terms if term in top_text)
        coverage_ratio = matched_terms / max(1, len(terms))
        weak_term_coverage = (
            (len(terms) >= 4 and coverage_ratio < 0.4)
            or (len(terms) >= 6 and matched_terms <= 2)
        )
        llm_answer = self._answer_with_llm(
            q,
            candidates,
            user_role=user_role,
            user_circle=user_circle,
        )

        if llm_answer:
            low_confidence_markers = (
                "не хватает информации",
                "нужно спросить у коллег",
                "уточнить у коллег",
                "нужно уточнить",
                "не могу точно",
                "нет прямой информации",
                "нет точной информации",
                "нет точного определения",
                "нет точного ответа",
                "нет объяснения",
                "в базе знаний нет",
                "по этому вопросу нет",
                "рекомендую уточнить",
                "можете уточнить",
                "можешь уточнить",
                "уточните, в каком контексте",
                "в каком контексте",
                "возможно, вы имели в виду",
                "лучше уточнить",
                "стоит уточнить",
                "уточни этот вопрос",
                "не могу дать точный ответ",
            )
            lowered = llm_answer.lower()
            # Строгий режим: если нет уверенного точного попадания — отправляем модератору.
            confident_exact_match = direct_question_match and top_score >= 6 and not weak_term_coverage
            needs_moderation = (not confident_exact_match) or any(
                m in lowered for m in low_confidence_markers
            )
            return {
                "answer": llm_answer,
                "needs_moderation": needs_moderation,
                "source": "llm",
                "confidence": top_score,
                "candidate_count": len(candidates),
                "direct_question_match": direct_question_match,
                "exact_question_match": exact_question_match,
            }

        fallback = self._fallback_answer(candidates)
        # Для не-LLM ответа:
        # - аббревиатуры: только точное одиночное попадание
        # - обычные вопросы: допускаем несколько кандидатов, если есть точное совпадение запроса
        if _looks_like_abbreviation_query(q):
            confident_kb_fallback = (
                len(candidates) == 1 and direct_question_match and not weak_term_coverage and top_score >= 6
            )
        else:
            confident_kb_fallback = direct_question_match and not weak_term_coverage and top_score >= 6
        needs_moderation = not confident_kb_fallback

        return {
            "answer": fallback,
            "needs_moderation": needs_moderation,
            "source": "kb" if candidates else "fallback",
            "confidence": top_score,
            "candidate_count": len(candidates),
            "direct_question_match": direct_question_match,
            "exact_question_match": exact_question_match,
        }

    def answer(self, question: str, user_role: str | None = None, user_circle: str | None = None) -> str:
        result = self.answer_with_meta(question, user_role=user_role, user_circle=user_circle)
        return result["answer"]

