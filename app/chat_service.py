"""
Сервис для получения ответа Buddy — используется и в FastAPI, и в Streamlit.
"""
import asyncio
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import get_settings
from .models import Base, KnowledgeItem


def _ensure_db_and_seed():
    """Создаёт БД, таблицы и заполняет базу знаний при первом запуске."""
    settings = get_settings()
    connect_args = {}
    if "sqlite" in settings.database_url:
        connect_args["check_same_thread"] = False
    engine = create_engine(settings.database_url, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        count = session.query(KnowledgeItem).count()
        if count == 0:
            # Заполняем базу из seed
            try:
                import importlib.util
                seed_path = Path(__file__).resolve().parent.parent / "scripts" / "seed_knowledge.py"
                spec = importlib.util.spec_from_file_location("seed_knowledge", seed_path)
                seed_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(seed_mod)
                items = seed_mod.SEED_ITEMS
            except Exception:
                items = [{"question": "Расскажи о компании", "answer": "PravoTech — ИТ-компания для юридической отрасли. Миссия: помогаем получать удовольствие от работы.", "tags": "company"}]
            for item in items:
                session.add(KnowledgeItem(
                    question=item["question"],
                    answer=item["answer"],
                    tags=item.get("tags"),
                ))
            session.commit()
    finally:
        session.close()
    return engine, SessionLocal


_engine = None
_SessionLocal = None


def get_session():
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine, _SessionLocal = _ensure_db_and_seed()
    return _SessionLocal()


def get_answer(text: str, user_id: str = "streamlit-demo") -> str:
    """
    Синхронная обёртка для получения ответа Buddy.
    Используется в Streamlit и других синхронных контекстах.
    """
    from .main import get_or_create_user, handle_question

    if not text or len(text.strip()) < 2:
        return "Напиши вопрос подлиннее, например: «расскажи о компании» или «как оформить отпуск»."

    db = get_session()
    try:
        user = get_or_create_user(db, mattermost_user_id=user_id, username="Гость")
        user.state = "qa"
        user.role = user.role or "новичок"
        db.commit()
        return asyncio.run(handle_question(db=db, user=user, text=text.strip(), channel_id="streamlit-demo"))
    finally:
        db.close()
