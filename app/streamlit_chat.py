import ast
from pathlib import Path

from sqlalchemy import Column, Integer, Text, create_engine, select
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    tags = Column(Text, nullable=True)


def _extract_seed_items() -> list[dict]:
    """
    Parse SEED_ITEMS from scripts/seed_knowledge.py without importing it
    (to avoid FastAPI/Pydantic dependency chain in Streamlit Cloud).
    """
    seed_path = Path(__file__).resolve().parent.parent / "scripts" / "seed_knowledge.py"
    src = seed_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SEED_ITEMS":
                    return ast.literal_eval(node.value)
    return []


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


def _score(item: KnowledgeItem, terms: list[str]) -> int:
    text = f"{item.question} {item.answer} {item.tags or ''}".lower()
    return sum(1 for t in terms if t in text)


class StreamlitChatService:
    def __init__(self) -> None:
        db_path = Path(__file__).resolve().parent.parent / "buddy_streamlit.db"
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        self._seed_if_empty()

    def _seed_if_empty(self) -> None:
        with self.SessionLocal() as db:
            count = db.query(KnowledgeItem).count()
            if count > 0:
                return
            for item in _extract_seed_items():
                db.add(
                    KnowledgeItem(
                        question=item.get("question", ""),
                        answer=item.get("answer", ""),
                        tags=item.get("tags"),
                    )
                )
            db.commit()

    def answer(self, question: str) -> str:
        q = (question or "").strip()
        if len(q) < 2:
            return "Напиши вопрос подлиннее, например: «расскажи о компании» или «как оформить отпуск»."

        terms = _extract_search_terms(q)
        with self.SessionLocal() as db:
            stmt = select(KnowledgeItem).limit(300)
            items = list(db.scalars(stmt))
            if not items:
                return "Пока пустая база знаний. Попробуй позже."
            if terms:
                items = sorted(items, key=lambda i: _score(i, terms), reverse=True)
            best = items[0]
            if terms and _score(best, terms) == 0:
                return "Мне не хватает информации в базе знаний, нужно спросить у коллег."
            return best.answer

