import ast
import json
import os
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

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


def _score(item: KnowledgeItem, query_text: str, terms: list[str]) -> int:
    q = (item.question or "").lower()
    a = (item.answer or "").lower()
    t = (item.tags or "").lower()
    full = f"{q} {a} {t}"

    score = 0
    if query_text and query_text in full:
        score += 8

    for term in terms:
        if term in q:
            score += 3
        elif term in a:
            score += 2
        elif term in t:
            score += 1
    return score


class StreamlitChatService:
    def __init__(self, openrouter_api_key: str = "", openrouter_model: str = "openai/gpt-4.1-mini") -> None:
        db_path = Path(__file__).resolve().parent.parent / "buddy_streamlit.db"
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)

        self.openrouter_api_key = (openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")).strip()
        self.openrouter_model = (openrouter_model or os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")).strip()
        self.llm_enabled = bool(self.openrouter_api_key.startswith("sk-"))

        self._sync_seed_items()

    def _sync_seed_items(self) -> None:
        with self.SessionLocal() as db:
            existing = {row.question: row for row in db.query(KnowledgeItem).all()}
            changed = False
            for item in _extract_seed_items():
                q = item.get("question", "")
                a = item.get("answer", "")
                t = item.get("tags")
                row = existing.get(q)
                if row is None:
                    db.add(KnowledgeItem(question=q, answer=a, tags=t))
                    changed = True
                elif row.answer != a or row.tags != t:
                    row.answer = a
                    row.tags = t
                    changed = True
            if changed:
                db.commit()
            else:
                db.rollback()

    def _retrieve_candidates(self, question: str, limit: int = 8) -> list[KnowledgeItem]:
        query_text = question.lower().strip()
        terms = _extract_search_terms(question)
        with self.SessionLocal() as db:
            items = list(db.scalars(select(KnowledgeItem).limit(400)))

        scored = []
        for item in items:
            s = _score(item, query_text, terms)
            if s > 0:
                scored.append((s, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return []
        if scored[0][0] < 3:
            return []
        min_score = max(3, scored[0][0] - 2)
        return [item for s, item in scored if s >= min_score][:limit]

    def _answer_with_llm(self, question: str, candidates: list[KnowledgeItem]) -> str | None:
        if not self.llm_enabled:
            return None

        facts = []
        for idx, item in enumerate(candidates[:6], start=1):
            facts.append(f"[Факт {idx}] Вопрос: {item.question}\nОтвет: {item.answer}")
        context = "\n\n".join(facts) if facts else "Нет релевантных фактов в базе знаний."

        system_prompt = (
            "Ты Buddy — дружелюбный помощник по онбордингу в компании PravoTech. "
            "Твоя задача: понять запрос пользователя, выбрать релевантные факты из базы знаний "
            "и дать полезный, живой ответ. Не копируй текст дословно."
        )
        user_prompt = (
            f"Вопрос пользователя: {question}\n\n"
            f"Факты из базы знаний:\n{context}\n\n"
            "Ответь по существу, опираясь на факты. "
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

    def _fallback_answer(self, candidates: list[KnowledgeItem]) -> str:
        if not candidates:
            return "Мне не хватает информации в базе знаний, нужно спросить у коллег."
        if len(candidates) == 1:
            return f"Вот что нашлось по твоему вопросу:\n\n{candidates[0].answer}"
        return (
            "По запросу нашла несколько релевантных моментов:\n\n"
            f"1) {candidates[0].answer}\n\n"
            f"2) {candidates[1].answer}"
        )

    def answer(self, question: str) -> str:
        q = (question or "").strip()
        if len(q) < 2:
            return "Напиши вопрос подлиннее, например: «расскажи о компании» или «как оформить отпуск»."

        candidates = self._retrieve_candidates(q, limit=8)
        llm_answer = self._answer_with_llm(q, candidates)
        if llm_answer:
            return llm_answer
        return self._fallback_answer(candidates)

