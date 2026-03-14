from typing import List, Optional

import httpx

from .config import get_settings
from .models import KnowledgeItem


async def answer_from_knowledge(
    question: str,
    knowledge_items: List[KnowledgeItem],
    user_role: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Use LLM to answer the question based only on knowledge_items.
    Returns (known, answer).
    """
    settings = get_settings()

    role_hint = f" Новичок работает в роли: {user_role}." if user_role else ""

    system_prompt = (
        "Ты Buddy — дружелюбный помощник по онбордингу в компании PravoTech. "
        "Ты общаешься тепло и по-человечески, как коллега, а не как робот. "
        "Отвечай развёрнуто, но по делу. Используй только факты из базы знаний."
        + role_hint
        + "\n\n"
        "Важно: НЕ отвечай односложно («ок», «да», «нет»). "
        "Если в базе знаний есть ответ — дай его понятно, с контекстом под роль человека. "
        "Если ответа нет — честно скажи и предложи спросить у коллег. "
        "Пиши живым языком, можно с лёгким юмором или поддержкой."
    )

    context_parts = []
    for idx, item in enumerate(knowledge_items, start=1):
        context_parts.append(f"[Факт {idx}] Вопрос: {item.question}\nОтвет: {item.answer}")

    context = "\n\n".join(context_parts) if context_parts else "Нет известных фактов."

    user_prompt = (
        f"База знаний:\n{context}\n\n"
        f"Вопрос новичка: {question}\n\n"
        "Если в базе знаний явно есть ответ — дай его простыми словами, тепло и по-человечески. "
        "Учитывай роль новичка. НЕ пиши сухо и формально. "
        "Если ответа нет — напиши: 'Мне не хватает информации в базе знаний, нужно спросить у коллег.'"
    )

    if not settings.openrouter_api_key or not settings.openrouter_api_key.startswith("sk-"):
        # Без LLM — возвращаем самый релевантный ответ из базы
        if knowledge_items:
            return True, knowledge_items[0].answer
        return False, "Мне не хватает информации в базе знаний, нужно спросить у коллег."

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "X-Title": "Buddy Mattermost Onboarding Agent",
                },
                json={
                    "model": settings.openrouter_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.8,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            answer: str = data["choices"][0]["message"]["content"]

        lower = answer.lower()
        if "нужно спросить у коллег" in lower or "не хватает информации" in lower:
            return False, answer
        return True, answer
    except Exception:
        # LLM недоступен — возвращаем ответ из базы
        if knowledge_items:
            return True, knowledge_items[0].answer
        return False, "Мне не хватает информации в базе знаний, нужно спросить у коллег."

