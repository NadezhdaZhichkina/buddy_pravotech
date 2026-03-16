"""
Buddy — помощник по адаптации. Streamlit-интерфейс для тестирования.
Запуск: streamlit run streamlit_app.py
"""

import os
import sys

# Корень проекта в sys.path (для Streamlit Cloud и др.)
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import random
import re

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Buddy — адаптация",
    page_icon="🤖",
    layout="centered",
)

# Инициализация при первом запуске
from app.onboarding import ROLE_DISPLAY, extract_role_from_message, get_display_role
from app.streamlit_chat import StreamlitChatService


def _get_secret(name: str, default: str = "") -> str:
    try:
        secrets = getattr(st, "secrets", None)
        if secrets is None:
            return default
        val = secrets.get(name, default)
        return str(val) if val is not None else default
    except Exception:
        return default


def _get_openrouter_api_key() -> str:
    variants = ["OPENROUTER_API_KEY", "openrouter_api_key", "OPEN_ROUTER_API_KEY"]
    for k in variants:
        v = _get_secret(k, "").strip()
        if v:
            return v
    return os.getenv("OPENROUTER_API_KEY", "").strip()


def _get_openrouter_model() -> str:
    variants = ["OPENROUTER_MODEL", "openrouter_model"]
    for k in variants:
        v = _get_secret(k, "").strip()
        if v:
            return v
    return os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini").strip()


_resolved_key = _get_openrouter_api_key()
_resolved_model = _get_openrouter_model()

# Подключение к БД: если PostgreSQL не работает — fallback на SQLite
_service = None
_init_error = None

try:
    _service = StreamlitChatService(
        openrouter_api_key=_resolved_key,
        openrouter_model=_resolved_model,
    )
except Exception as e:
    _init_error = e
    # Fallback: принудительно SQLite — st.secrets не очищается при pop env, потому флаг
    _old_db = os.environ.pop("STREAMLIT_DATABASE_URL", None)
    _old_db2 = os.environ.pop("DATABASE_URL", None)
    os.environ["BUDDY_FORCE_SQLITE"] = "1"
    try:
        _service = StreamlitChatService(
            openrouter_api_key=_resolved_key,
            openrouter_model=_resolved_model,
        )
        st.warning(
            "⚠️ Не удалось подключиться к PostgreSQL — используется локальный SQLite (buddy_streamlit.db). "
            "Ошибка: " + str(_init_error)
        )
    except Exception as e2:
        import traceback
        st.error(f"Ошибка инициализации: {_init_error}")
        st.caption("Повторная попытка с SQLite также не удалась:")
        st.code(traceback.format_exc(), language=None)
        st.stop()
    finally:
        os.environ.pop("BUDDY_FORCE_SQLITE", None)
        if _old_db is not None:
            os.environ["STREAMLIT_DATABASE_URL"] = _old_db
        if _old_db2 is not None:
            os.environ["DATABASE_URL"] = _old_db2

service = _service

QUESTION_WORDS = (
    "как",
    "что",
    "где",
    "когда",
    "зачем",
    "почему",
    "кто",
    "какой",
    "какая",
    "какие",
    "можно",
    "нужно",
    "подскажи",
)

DONE_WORDS = (
    "сделал",
    "сделала",
    "готов",
    "готово",
    "уже",
    "отправил",
    "отправила",
    "настроил",
    "настроила",
    "подписался",
    "подписалась",
    "проверил",
    "проверила",
)

PROBLEM_WORDS = (
    "проблем",
    "ошибка",
    "не работает",
    "не получается",
    "не могу",
    "нет доступа",
    "не заходит",
    "сломал",
    "сломалось",
)

NO_PROBLEM_WORDS = (
    "нет проблем",
    "все ок",
    "всё ок",
    "все хорошо",
    "всё хорошо",
    "нормально",
    "в порядке",
)

NEXT_STEP_WORDS = (
    "что дальше",
    "что делать дальше",
    "что мне делать",
    "что делать",
    "дальше",
)

DEMO_USERS = ("user1", "user2")

CIRCLE_ALIASES = {
    "маркет": "маркетинг",
    "marketing": "маркетинг",
    "sales": "sales",
    "продаж": "sales",
    "product": "product",
    "продукт": "product",
    "docs": "docs",
    "legal": "legal",
    "new business": "new business",
    "nb": "new business",
    "projects": "projects",
    "инфра": "инфраструктура и ит",
    "it": "инфраструктура и ит",
    "hr": "hr",
    "client care": "client care",
    "work": "work",
}

CIRCLE_INTERACTIONS = {
    "маркетинг": ["sales", "product", "new business", "legal", "docs"],
    "sales": ["маркетинг", "product", "docs", "legal", "client care"],
    "product": ["sales", "маркетинг", "new business", "docs", "legal"],
    "new business": ["product", "маркетинг", "sales", "legal"],
    "legal": ["sales", "маркетинг", "docs", "product"],
    "docs": ["sales", "legal", "product"],
    "client care": ["sales", "product", "docs"],
    "hr": ["инфраструктура и ит", "legal", "все круги"],
    "projects": ["product", "sales", "docs", "legal"],
    "инфраструктура и ит": ["hr", "product", "projects", "все круги"],
    "work": ["product", "sales", "docs", "legal"],
}

# План онбординга по welcome-курсу (День 1 → День 2)
# Buddy помогает с культурной навигацией, чатами, ритуалами; не обучает продукту и не контролирует KPI
ONBOARDING_TASKS = [
    # День 1 — welcome-курс
    {"id": "auth_email", "day": 1, "title": "Авторизоваться в корпоративной почте", "hint": "Доступы пришлёт менеджер по адаптации."},
    {"id": "setup_services", "day": 1, "title": "Настроить сервисы: VPN, Focus, Яндекс-360, HR, MChat, CRM, MangoTalker", "hint": "По вопросам — менеджер по адаптации в течение дня."},
    {"id": "company_video", "day": 1, "title": "Посмотреть вступительное видео: история компании, миссия и ценности", "hint": "Часть welcome-курса."},
    {"id": "product_video", "day": 1, "title": "Изучить видео по продуктам", "hint": "В рамках welcome-курса."},
    {"id": "intro_post", "day": 1, "title": "Написать приветственный пост в чат `talk` и рассказать о себе", "hint": "Если хочешь, подскажу шаблон поста."},
    {"id": "benefits_culture", "day": 1, "title": "Изучить бенефиты, КЭДО и культуру коммуникации", "hint": "Всё в welcome-курсе."},
    {"id": "social_media", "day": 1, "title": "Подписаться на соцсети компании", "hint": "Часть welcome-курса."},
    {"id": "meet_leader_mentor", "day": 1, "title": "Познакомиться с лидером и наставником", "hint": "На вводной встрече обсудите структуру круга, цели, чаты, ритуалы."},
    {"id": "get_materials", "day": 1, "title": "Получить материалы для изучения от лидера", "hint": "Лидер сориентирует, что изучить в первую очередь."},
    {"id": "join_chats", "day": 1, "title": "Быть добавленным в командные чаты (лидер/наставник)", "hint": "Обычно добавляют в первый день."},
    # День 2
    {"id": "welcome_meeting", "day": 2, "title": "Пройти welcome-встречу с менеджером по адаптации", "hint": "Расскажут про сервисы, MChat, культуру, OKR, мероприятия. Здесь же подключается Buddy."},
]


def _extract_circle(text: str) -> str | None:
    t = (text or "").lower()
    for alias, normalized in CIRCLE_ALIASES.items():
        if alias in t:
            return normalized
    # Фолбек: "круг work" / "в круге work" / "мой круг product" / "circle docs"
    m = re.search(
        r"(?:круг|круге|круга|circle)\s*[:\-]?\s*([a-zа-яё0-9_+\-]{2,30})",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        raw = (m.group(1) or "").strip().lower()
        return CIRCLE_ALIASES.get(raw, raw)
    return None


def _extract_leader(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    # Приоритет: упоминание @username
    for token in t.replace(",", " ").split():
        if token.startswith("@") and len(token) > 1:
            return token
    low = t.lower()
    markers = ("лидер", "мой лидер", "тимлид", "руководитель")
    if any(m in low for m in markers):
        return t
    return None


def _extract_known_role(text: str) -> str | None:
    role = extract_role_from_message(text or "")
    if role in ROLE_DISPLAY:
        return role
    return None


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    t = (text or "").lower()
    return any(w in t for w in words)


def _has_done_signal(text: str) -> bool:
    return _has_any(text, DONE_WORDS)


def _has_problem_signal(text: str) -> bool:
    return _has_any(text, PROBLEM_WORDS)


def _has_no_problem_signal(text: str) -> bool:
    return _has_any(text, NO_PROBLEM_WORDS)


def _asks_next_step(text: str) -> bool:
    return _has_any(text, NEXT_STEP_WORDS)


def _asks_circle_interactions(text: str) -> bool:
    return _has_any(
        text,
        (
            "с кем взаимодействует",
            "с какими кругами",
            "взаимодействует круг",
            "какие круги",
            "с кем мы работаем",
        ),
    )


def _looks_like_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if "?" in t:
        return True
    return any(t.startswith(w + " ") or t == w for w in QUESTION_WORDS)


def _looks_like_profile_declaration(text: str) -> bool:
    """Сообщение похоже на объявление роли/круга — приоритетно обрабатываем как информативное."""
    t = (text or "").strip().lower()
    if not t or len(t) < 4:
        return False
    role_markers = (
        "менеджер", "маркетолог", "дизайнер", "backend", "frontend", "sales",
        "работаю", "я ", "круг", "круге", "circle", "в круге", "в кругу",
    )
    return any(m in t for m in role_markers)


def _looks_like_small_talk(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    markers = (
        "привет",
        "доброе утро",
        "добрый день",
        "добрый вечер",
        "как дела",
        "спасибо",
        "благодарю",
        "понятно",
        "ок",
        "хорошо",
        "норм",
        "ясно",
        "круто",
        "супер",
        "отлично",
        "давай",
        "ага",
        "угу",
    )
    return any(m in t for m in markers)


def _needs_moderator_escalation(text: str) -> bool:
    t = (text or "").lower()
    return (
        "не хватает информации" in t
        or "нужно спросить у коллег" in t
        or "уточнить у коллег" in t
    )


def _looks_like_term_or_abbreviation_query(text: str) -> bool:
    t = (text or "").strip()
    low = t.lower()
    if any(k in low for k in ("аббревиатур", "сокращени", "расшифровк", "что за ", "что значит ")):
        return True
    token = low.replace("?", "").replace("!", "").strip()
    # Не считать термином короткие разговорные слова
    conversational = {"давай", "да", "нет", "ок", "привет", "пока", "ага", "угу", "ну", "вот", "так", "ну да"}
    if token in conversational:
        return False
    if 2 <= len(token) <= 6 and bool(re.fullmatch(r"[a-zа-яё0-9]+", token)):
        return True
    return bool(re.search(r"\b[A-ZА-ЯЁ]{2,6}\b", t))


def _contains_uncertainty_language(text: str) -> bool:
    t = (text or "").lower()
    markers = (
        "не хватает информации",
        "нужно спросить у коллег",
        "уточнить у коллег",
        "нет прямой информации",
        "нет точной информации",
        "нет точного определения",
        "нет объяснения",
        "нет точного ответа",
        "рекомендую уточнить",
        "можете уточнить",
        "можешь уточнить",
        "в каком контексте",
        "возможно, вы имеете в виду",
        "лучше уточнить",
        "стоит уточнить",
        "спросить у коллег",
        "передать модератору",
        "передам вопрос модератору",
        "передадим вопрос модератору",
        "передам модератору",
        "направлю тикет",
        "направить тикет",
        "передам вопрос",
        "подскажу, к кому",
        "нет в базе",
        "этого нет в базе",
    )
    if any(m in t for m in markers):
        return True
    # Дополнительный мягкий матч по корням.
    return bool(re.search(r"уточн|нет .*определен|нет .*объяснен|нет .*информац|не могу|переда(м|ть).*модератор", t))


def _is_yes_reply(text: str) -> bool:
    t = (text or "").strip().lower()
    yes_variants = {"да", "yes", "ок", "ok", "ага", "давай", "отправляй", "подтверждаю"}
    return t in yes_variants or t.startswith("да ")


def _is_no_reply(text: str) -> bool:
    t = (text or "").strip().lower()
    no_variants = {"нет", "no", "неа", "стоп", "отмена", "не надо"}
    return t in no_variants or t.startswith("нет ")


def _is_direct_moderator_request(text: str) -> bool:
    """Пользователь явно просит отправить вопрос модератору."""
    t = (text or "").strip().lower()
    if len(t) > 80:
        return False  # Длинное сообщение — не команда
    phrases = (
        "передай модератору", "отправь модератору", "передай вопрос модератору",
        "отправь вопрос модератору", "передай вопрос", "отправь вопрос",
        "передай человеку", "отправь человеку", "передай запрос модератору",
        "передай модератор", "отправь модератор", "да, передай", "ок, передай",
    )
    if any(p in t for p in phrases):
        return True
    if t in ("передай", "отправь"):
        return True
    # «передай» или «отправь» в начале или как основная мысль
    if re.search(r"^(да|ок|ага|хорошо)[,\s]+(передай|отправь)", t):
        return True
    return "передай" in t and len(t) < 25  # Короткая команда с «передай»


def _extract_question_from_history_for_ticket(messages: list, current_prompt: str) -> str | None:
    """Извлекает последний вопрос пользователя из истории (для тикета при «передай модератору»)."""
    fallback = None
    last_assistant_content = None
    for m in reversed(messages):
        if m.get("role") == "assistant":
            if last_assistant_content is None:
                last_assistant_content = (m.get("content") or "").strip()
            continue
        if m.get("role") != "user":
            continue
        content = (m.get("content") or "").strip()
        if not content or content == current_prompt:
            continue
        if len(content) > 3 and (_looks_like_question(content) or _looks_like_term_or_abbreviation_query(content)):
            return content
        # Fallback только для содержательных сообщений, не приветствий
        if len(content) > 5 and fallback is None and not _looks_like_small_talk(content):
            fallback = content
    # Если не нашли в пользовательских сообщениях — пробуем из ответа ассистента («вопрос про X»)
    if last_assistant_content:
        m = re.search(r"(?:вопрос|запрос)\s+про\s+[«\"']?([^»\"'?\n]+)", last_assistant_content, re.I)
        if m:
            return m.group(0).strip()  # весь фрагмент «вопрос про КБ и лицензии»
        m = re.search(r"про\s+[«\"']([^»\"']+)[«\"']", last_assistant_content)
        if m:
            return m.group(1).strip()
    return fallback


def _prepare_ticket_offer(
    question: str,
    role: str | None,
    circle: str | None,
    requester_username: str,
) -> str:
    username = (requester_username or "user1").strip().lower()
    st.session_state.pending_ticket_offer_by_user[username] = {
        "question": (question or "").strip(),
        "user_role": role,
        "user_circle": circle,
    }
    return (
        "Хочешь, я направлю тикет с этим вопросом модератору?\n\n"
        "Когда модератор ответит, я пришлю ответ сюда.\n"
        "Напиши: **да** или **нет**, либо нажми кнопку **Отправить вопрос человеку** ниже."
    )


def _should_send_to_moderator(prompt: str, result: dict) -> bool:
    if result.get("needs_moderation"):
        return True

    if _contains_uncertainty_language(result.get("answer", "")):
        return True

    exact_match = bool(result.get("exact_question_match"))
    direct_match = bool(result.get("direct_question_match"))
    confidence = int(result.get("confidence") or 0)
    candidate_count = int(result.get("candidate_count") or 0)
    is_question_like = _looks_like_question(prompt) or _looks_like_term_or_abbreviation_query(prompt)

    # Если есть точное и уверенное попадание в базе, повторно в модерацию не отправляем.
    if exact_match and confidence >= 8:
        return False

    if _looks_like_term_or_abbreviation_query(prompt) and not exact_match:
        # Для аббревиатур/терминов всегда требуем точный факт.
        return True

    if _looks_like_term_or_abbreviation_query(prompt):
        normalized = (
            (prompt or "")
            .strip()
            .lower()
            .replace("?", "")
            .replace("!", "")
            .replace(".", "")
            .replace(",", "")
        )
        # Короткие токены (например "кб") считаем неоднозначными: лучше валидировать через модератора.
        if re.fullmatch(r"[a-zа-яё0-9]{2,3}", normalized or ""):
            return True

        candidate_count = int(result.get("candidate_count") or 0)
        confidence = int(result.get("confidence") or 0)
        direct_match = bool(result.get("direct_question_match"))
        if candidate_count != 1:
            return True
        if not direct_match:
            return True
        if confidence < 8:
            return True

    # Строгий фолбек: если вопрос от пользователя не имеет точного совпадения в БЗ,
    # оставляем автоответ только для очень уверенных матчей.
    if is_question_like and not exact_match:
        very_confident_non_exact = direct_match and confidence >= 5 and candidate_count <= 4
        if not very_confident_non_exact:
            return True

    source = (result.get("source") or "").lower()
    return source in ("fallback", "abbreviation_guard")


def _update_progress(text: str, progress: dict[str, bool]) -> list[str]:
    t = (text or "").lower()
    changed = []

    if _has_done_signal(t):
        if any(w in t for w in ("почта", "email", "mail", "авториз")) and not progress.get("auth_email"):
            progress["auth_email"] = True
            changed.append("почта настроена")
        if any(w in t for w in ("vpn", "focus", "яндекс", "mchat", "crm", "mangotalker", "сервис", "настроил")) and not progress.get("setup_services"):
            progress["setup_services"] = True
            changed.append("сервисы настроены")
        if any(w in t for w in ("видео", "история", "миссия", "ценност")) and not progress.get("company_video"):
            progress["company_video"] = True
            changed.append("видео о компании просмотрено")
        if any(w in t for w in ("видео", "продукт")) and not progress.get("product_video"):
            progress["product_video"] = True
            changed.append("видео по продуктам изучено")
        if any(w in t for w in ("пост", "talk", "приветствен")) and not progress.get("intro_post"):
            progress["intro_post"] = True
            changed.append("приветственный пост отправлен")
        if any(w in t for w in ("бенефит", "кэдо", "культур")) and not progress.get("benefits_culture"):
            progress["benefits_culture"] = True
            changed.append("бенефиты и культура изучены")
        if any(w in t for w in ("соцсети", "подпис")) and not progress.get("social_media"):
            progress["social_media"] = True
            changed.append("соцсети подключены")
        if any(w in t for w in ("лидер", "наставник", "познакомился", "встреча")) and not progress.get("meet_leader_mentor"):
            progress["meet_leader_mentor"] = True
            changed.append("знакомство с лидером и наставником")
        if any(w in t for w in ("материал", "лидер", "изуч")) and not progress.get("get_materials"):
            progress["get_materials"] = True
            changed.append("материалы от лидера получены")
        if any(w in t for w in ("чат", "добавили", "командн")) and not progress.get("join_chats"):
            progress["join_chats"] = True
            changed.append("в командные чаты добавлен")
        if any(w in t for w in ("welcome", "встреча", "второй день")) and not progress.get("welcome_meeting"):
            progress["welcome_meeting"] = True
            changed.append("welcome-встреча пройдена")

    return changed


def _next_task(progress: dict[str, bool]) -> dict | None:
    for task in ONBOARDING_TASKS:
        if not progress.get(task["id"], False):
            return task
    return None


def _starter_plan(role: str, circle: str) -> str:
    role_text = get_display_role(role)
    return (
        f"Супер! Вижу тебя как **{role_text}** в круге **{circle}** 🙌\n\n"
        "Я Buddy — твой неформальный друг на онбординге. Помогаю с культурной навигацией, чатами, ритуалами и знакомствами.\n\n"
        "**План на первый день** (welcome-курс):\n"
        "• Авторизация в почте\n"
        "• Настройка сервисов (VPN, MChat, HR и др.)\n"
        "• Видео о компании и продуктах\n"
        "• Приветственный пост в `talk`\n"
        "• Знакомство с лидером и наставником\n\n"
        "**Второй день** — welcome-встреча с менеджером по адаптации, там же подключается живой Buddy.\n\n"
        "Когда сделаешь шаг — напиши, например: «пост отправила» или «сервисы настроила». "
        "Если знаешь лидера — напиши `мой лидер @username`."
    )


def _circle_interactions_reply(circle: str | None) -> str:
    if not circle:
        return (
            "Чтобы подсказать взаимодействия между кругами, сначала напиши, в каком ты круге. "
            "Например: «круг Marketing»."
        )
    peers = CIRCLE_INTERACTIONS.get(circle, [])
    if not peers:
        return (
            f"Для круга **{circle}** у меня пока нет детальной карты. "
            "Подскажи лидеру или наставнику — они лучше знают, с кем из смежных направлений полезно познакомиться."
        )
    return (
        f"Обычно круг **{circle}** чаще всего взаимодействует с: "
        + ", ".join(f"**{p}**" for p in peers)
        + ".\n\nПо конкретным лайфхакам и контактам внутри круга — лучше у лидера или наставника. "
        "Когда появятся материалы по ролям и кругам, смогу подсказать точнее."
    )


def _small_talk_reply(next_task: dict | None) -> str:
    options = [
        "Класс, если проблем нет — это отличный знак 😊",
        "Супер, что всё спокойно. Так и должно быть на старте 🙌",
        "Отлично! Тогда можем двигаться дальше без спешки.",
    ]
    base = random.choice(options)
    if next_task:
        return (
            f"{base}\n\n"
            f"Давай следующий шаг: **{next_task['title']}**\n"
            f"{next_task['hint']}\n\n"
            "Или могу просто рассказать о компании, каналах и полезных ритуалах в команде."
        )
    return (
        f"{base}\n\n"
        "Если хочешь, могу:\n"
        "- коротко рассказать о компании;\n"
        "- подсказать, какие каналы читать каждый день;\n"
        "- дать план на первую неделю по твоей роли."
    )


def _apply_informative_user_message(profile: dict, prompt: str) -> dict:
    """Обновляет профиль по информативным сообщениям (не Q&A)."""
    text = (prompt or "").strip()
    role = _extract_known_role(text)
    circle = _extract_circle(text)
    leader = _extract_leader(text)
    changes = _update_progress(text, profile["progress"])

    updated_fields = []
    if role and role != profile.get("role"):
        profile["role"] = role
        updated_fields.append(f"роль: **{get_display_role(role)}**")
    if circle and circle != profile.get("circle"):
        profile["circle"] = circle
        updated_fields.append(f"круг: **{circle}**")
    if leader and leader != profile.get("leader"):
        profile["leader"] = leader
        updated_fields.append(f"лидер: **{leader}**")

    # Если собрали роль и круг — считаем онбординг стартованным.
    if profile.get("role") and profile.get("circle"):
        profile["started"] = True

    informative = bool(updated_fields or changes)
    return {
        "informative": informative,
        "updated_fields": updated_fields,
        "progress_changes": changes,
    }


def _build_informative_ack(profile: dict, info: dict, keep_pending_offer: bool = False) -> str:
    parts = []
    if info.get("updated_fields"):
        parts.append("Записала в профиль: " + ", ".join(info["updated_fields"]) + ".")
    if info.get("progress_changes"):
        parts.append("Отметила прогресс: **" + ", ".join(info["progress_changes"]) + "** ✅")

    next_task = _next_task(profile["progress"])
    if next_task:
        parts.append(f"Следующий шаг: **{next_task['title']}**\n{next_task['hint']}")
    else:
        parts.append(_small_talk_reply(next_task))

    missing = []
    if not profile.get("role"):
        missing.append("роль")
    if not profile.get("circle"):
        missing.append("круг")
    if missing:
        parts.append("Чтобы помогать точнее, напиши, пожалуйста: **" + " и ".join(missing) + "**.")

    if keep_pending_offer:
        parts.append(
            "По предыдущему вопросу тикет всё еще готов к отправке: "
            "нажми **Отправить вопрос человеку** ниже или ответь `да`/`нет`."
        )
    return "\n\n".join(parts) if parts else ""


def _default_user_messages() -> list[dict[str, str]]:
    return [
        {
            "role": "assistant",
            "content": (
                "Привет! Я Buddy — твой неформальный друг на онбординге 👋\n\n"
                "Помогаю с культурной навигацией, чатами, ритуалами и знакомствами. "
                "Чтобы подсказывать точнее, напиши **роль** и **круг**.\n"
                "Например: «Я менеджер, круг Work»."
            ),
        }
    ]


def _default_user_profile() -> dict:
    return {
        "role": None,
        "circle": None,
        "leader": None,
        "started": False,
        "progress": {task["id"]: False for task in ONBOARDING_TASKS},
        "last_suggested_task_id": None,
        "next_step_repeat_count": 0,
    }


def _ensure_profile_defaults(profile: dict) -> None:
    profile.setdefault("role", None)
    profile.setdefault("circle", None)
    profile.setdefault("leader", None)
    profile.setdefault("started", False)
    profile.setdefault("progress", {})
    # Миграция старых ключей прогресса
    p = profile["progress"]
    if p.get("mchat_setup") or p.get("join_channels"):
        p["setup_services"] = True
    if p.get("intro_post"):
        p["intro_post"] = True
    if p.get("check_access"):
        p["setup_services"] = True
    for task in ONBOARDING_TASKS:
        p.setdefault(task["id"], False)
    profile.setdefault("last_suggested_task_id", None)
    profile.setdefault("next_step_repeat_count", 0)


def _next_step_response(profile: dict, next_task: dict | None) -> str:
    if not next_task:
        return _small_talk_reply(next_task)
    task_id = next_task["id"]
    last_id = profile.get("last_suggested_task_id")
    repeats = int(profile.get("next_step_repeat_count") or 0)
    if last_id == task_id:
        repeats += 1
    else:
        repeats = 0
    profile["last_suggested_task_id"] = task_id
    profile["next_step_repeat_count"] = repeats

    if repeats >= 1:
        return (
            "Двигаемся спокойно, ты на правильном пути 🙌\n\n"
            f"Актуальный следующий шаг всё тот же: **{next_task['title']}**\n"
            f"{next_task['hint']}\n\n"
            "Если хочешь, могу пока подсказать короткий лайфхак по адаптации или ответить на любой вопрос."
        )
    return (
        f"Дальше предлагаю такой шаг: **{next_task['title']}**\n"
        f"{next_task['hint']}"
    )


# ========== ПАНЕЛЬ РОЛЕЙ — Пользователь 1, Пользователь 2 или Модератор ==========
ROLE_OPTIONS = ["Пользователь 1", "Пользователь 2", "Модератор"]
if "current_role" not in st.session_state:
    st.session_state.current_role = "Пользователь 1"
if "chat_username" not in st.session_state:
    st.session_state.chat_username = "user1"
if "moderator_username" not in st.session_state:
    st.session_state.moderator_username = "nadezhda_zhichkina"

# Единый селектор: роль пользователя или модератора
st.markdown("---")
st.markdown("### 🔀 Роль")
col1, col2 = st.columns([2, 1])
with col1:
    role_idx = ROLE_OPTIONS.index(st.session_state.current_role) if st.session_state.current_role in ROLE_OPTIONS else 0
    selected_role = st.radio(
        "Выбери роль",
        options=ROLE_OPTIONS,
        index=role_idx,
        horizontal=True,
        key="role_switch",
    )
    st.session_state.current_role = selected_role
    if selected_role == "Пользователь 1":
        st.session_state.chat_username = "user1"
        is_moderator = False
    elif selected_role == "Пользователь 2":
        st.session_state.chat_username = "user2"
        is_moderator = False
    else:
        is_moderator = True  # Модератор
with col2:
    moderator_username = st.text_input(
        "Username модератора",
        value=st.session_state.moderator_username,
        help="Этому модератору приходят тикеты.",
        key="mod_switch",
    ).strip().lower()
    st.session_state.moderator_username = moderator_username or "nadezhda_zhichkina"
try:
    pending_total = len(service.list_moderation_tickets(include_closed=False))
except Exception:
    pending_total = 0
st.caption(
    f"Чат: `{st.session_state.chat_username}` · Модератор: `{st.session_state.moderator_username}`"
    + (f" · Тикетов в очереди: {pending_total}" if is_moderator else "")
)
st.divider()

st.title("🤖 Buddy")
st.caption(
    "Твой buddy на онбординге: помогу с адаптацией, вопросами по процессам и первыми шагами в компании. "
    "Можем общаться свободно: и по делу, и по-человечески."
)
if service.llm_enabled:
    st.success(f"LLM: включен (OpenRouter, model: {_resolved_model})")
else:
    st.info("LLM: выключен — ответы только по базе знаний. Добавь OPENROUTER_API_KEY в Secrets Streamlit Cloud.")

with st.expander("Диагностика LLM", expanded=False):
    st.write(
        {
            "llm_enabled": service.llm_enabled,
            "model": _resolved_model,
            "key_detected": bool(_resolved_key),
            "key_prefix": (_resolved_key[:8] + "...") if _resolved_key else "",
        }
    )

# is_moderator определяется в блоке ролей выше
is_moderator = st.session_state.current_role == "Модератор"
if "messages_by_user" not in st.session_state:
    st.session_state.messages_by_user = {}
if "profiles_by_user" not in st.session_state:
    st.session_state.profiles_by_user = {}
if "user_notices_by_user" not in st.session_state:
    st.session_state.user_notices_by_user = {}
if "pending_ticket_offer_by_user" not in st.session_state:
    st.session_state.pending_ticket_offer_by_user = {}
if st.session_state.chat_username not in st.session_state.messages_by_user:
    st.session_state.messages_by_user[st.session_state.chat_username] = _default_user_messages()
if st.session_state.chat_username not in st.session_state.profiles_by_user:
    st.session_state.profiles_by_user[st.session_state.chat_username] = _default_user_profile()
if st.session_state.chat_username not in st.session_state.user_notices_by_user:
    st.session_state.user_notices_by_user[st.session_state.chat_username] = ""
if st.session_state.chat_username not in st.session_state.pending_ticket_offer_by_user:
    st.session_state.pending_ticket_offer_by_user[st.session_state.chat_username] = None

st.session_state.messages = st.session_state.messages_by_user[st.session_state.chat_username]
st.session_state.profile = st.session_state.profiles_by_user[st.session_state.chat_username]
_ensure_profile_defaults(st.session_state.profile)
if "moderator_notice" not in st.session_state:
    st.session_state.moderator_notice = ""
if "selected_ticket_id" not in st.session_state:
    st.session_state.selected_ticket_id = None

if not is_moderator:
    user_updates = service.pop_user_updates(st.session_state.chat_username)
    for upd in user_updates:
        if upd.get("status") == "rejected":
            update_text = (
                "Вопрос отклонен модератором.\n\n"
                "На этот вопрос может ответить только твой лидер. "
                "Пожалуйста, обратись к лидеру своего круга."
            )
        else:
            update_text = (
                "Модератор обработал вопрос и отправил ответ ✅\n\n"
                f"> {upd['question']}\n\n"
                f"{upd['answer']}"
            )
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": update_text,
            }
        )
    if user_updates:
        st.rerun()  # Сразу показать ответ модератора пользователю

moderator_tickets = service.list_moderation_tickets(include_closed=False) if is_moderator else []

if is_moderator:
    with st.expander("🧾 Тикеты модератора", expanded=bool(moderator_tickets)):
        if st.session_state.moderator_notice:
            st.success(st.session_state.moderator_notice)
            st.session_state.moderator_notice = ""

        st.info(
            "Приветствую в панели модератора. "
            "Здесь можно пополнить базу знаний и отработать вопросы от пользователей."
        )
        if not (os.getenv("STREAMLIT_DATABASE_URL") or os.getenv("DATABASE_URL")):
            st.warning(
                "⚠️ **База данных временная:** без `STREAMLIT_DATABASE_URL` (PostgreSQL) "
                "тикеты и добавленные вопросы не сохраняются надёжно на Streamlit Cloud. "
                "Разные инстансы используют разные SQLite, перезапуск стирает данные. "
                "Добавь секрет в Settings → Secrets, см. DEPLOY.md."
            )

        tickets = moderator_tickets
        if not tickets:
            st.caption("Новых тикетов в очереди нет.")
            st.session_state.selected_ticket_id = None
        else:
            st.caption(f"Тикеты в работе: {len(tickets)}")
            st.markdown("### Тикеты")
            for ticket in tickets:
                cols = st.columns([7, 2, 2])
                with cols[0]:
                    short_q = ticket["question"]
                    if len(short_q) > 90:
                        short_q = short_q[:90] + "..."
                    st.markdown(f"**#{ticket['id']}** — {short_q}")
                    st.caption(f"Пользователь: `{ticket['requester_username']}`")
                with cols[1]:
                    status_map = {
                        "in_progress": "в работе",
                        "pending": "в работе",
                        "awaiting_approval": "в работе",
                        "sent": "отправлен",
                        "rejected": "отклонен",
                    }
                    st.caption(f"Статус: `{status_map.get(ticket['status'], ticket['status'])}`")
                with cols[2]:
                    if st.button("Открыть", key=f"open_ticket_{ticket['id']}"):
                        st.session_state.selected_ticket_id = ticket["id"]
                        st.rerun()
                st.divider()

        selected_ticket = None
        if tickets and st.session_state.selected_ticket_id is not None:
            selected_ticket = next(
                (t for t in tickets if t["id"] == st.session_state.selected_ticket_id),
                None,
            )
            if selected_ticket is None:
                st.session_state.selected_ticket_id = None

        if selected_ticket:
            st.markdown(f"### Карточка тикета #{selected_ticket['id']}")
            with st.container(border=True):
                st.text_area(
                    "Вопрос пользователя",
                    value=selected_ticket["question"],
                    disabled=True,
                    key=f"ticket_question_view_{selected_ticket['id']}",
                )
                if selected_ticket["user_role"] or selected_ticket["user_circle"]:
                    st.caption(
                        f"Профиль: роль={selected_ticket['user_role'] or 'не указана'}, "
                        f"круг={selected_ticket['user_circle'] or 'не указан'}"
                    )

                with st.form(f"ticket_editor_{selected_ticket['id']}", clear_on_submit=False):
                    ticket_answer = st.text_area(
                        "Ответ",
                        value=selected_ticket.get("draft_answer") or "",
                        key=f"ticket_answer_edit_{selected_ticket['id']}",
                        placeholder="Напиши ответ пользователю...",
                    )
                    status_default = "в работе"
                    ticket_status = st.selectbox(
                        "Статус",
                        options=["в работе", "отправить", "отклонен"],
                        index=0 if status_default == "в работе" else 1,
                        key=f"ticket_status_edit_{selected_ticket['id']}",
                        help="«Отправить» — отправит ответ пользователю и сохранит в общую базу знаний",
                    )
                    ticket_tags = st.text_input(
                        "Теги (опционально)",
                        key=f"ticket_tags_edit_{selected_ticket['id']}",
                        placeholder="Если пусто — теги определятся автоматически",
                    )
                    save_ticket = st.form_submit_button("Сохранить")

                c_close1, c_close2 = st.columns([1, 3])
                with c_close1:
                    if st.button("Закрыть", key=f"close_ticket_{selected_ticket['id']}"):
                        st.session_state.selected_ticket_id = None
                        st.rerun()

                if save_ticket:
                    if ticket_status == "отправить":
                        resolved = service.resolve_ticket(
                            ticket_id=selected_ticket["id"],
                            answer=ticket_answer,
                            moderator_username=st.session_state.moderator_username,
                            tags=ticket_tags,
                        )
                        if resolved:
                            action_ru = "добавлено" if resolved.get("knowledge_action") == "created" else "обновлено"
                            st.session_state.moderator_notice = (
                                f"✅ Тикет #{resolved['ticket_id']} отправлен пользователю. "
                                f"Ответ сохранён в базу знаний (id={resolved['knowledge_id']}, {action_ru}). "
                                f"Пользователь увидит ответ при следующем открытии чата."
                            )
                            st.session_state.selected_ticket_id = None
                            st.rerun()
                        else:
                            st.warning("Нужен непустой ответ, чтобы отправить пользователю.")
                    elif ticket_status == "отклонен":
                        rejected = service.reject_moderator_answer(
                            ticket_id=selected_ticket["id"],
                            moderator_username=st.session_state.moderator_username,
                        )
                        if rejected:
                            st.session_state.moderator_notice = (
                                f"Тикет #{selected_ticket['id']} отклонен. "
                                "Пользователю отправлено сообщение обратиться к лидеру."
                            )
                            st.session_state.selected_ticket_id = None
                            st.rerun()
                        else:
                            st.warning("Не удалось отклонить тикет.")
                    else:  # в работе
                        saved = service.save_moderator_draft(
                            ticket_id=selected_ticket["id"],
                            draft_answer=ticket_answer,
                            moderator_username=st.session_state.moderator_username,
                        )
                        if saved:
                            st.session_state.moderator_notice = (
                                f"Тикет #{selected_ticket['id']}: черновик сохранен."
                            )
                            st.rerun()
                        else:
                            st.warning("Не удалось сохранить тикет в статусе «в работе».")

        st.markdown("### Внести ВОПРОС и ОТВЕТ в базу")
        with st.form("manual_kb_form", clear_on_submit=True):
            manual_question = st.text_area(
                "ВОПРОС",
                placeholder="Например: Что означает аббревиатура КБ?",
            )
            manual_answer = st.text_area(
                "ОТВЕТ",
                placeholder="Например: КБ — корпоративная база знаний...",
            )
            manual_tags = st.text_input(
                "Теги (опционально)",
                placeholder="Если пусто — теги определятся автоматически",
            )
            save_manual = st.form_submit_button("Сохранить ВОПРОС + ОТВЕТ в базу")

        if save_manual:
            try:
                saved = service.save_manual_knowledge(
                    question=manual_question,
                    answer=manual_answer,
                    tags=manual_tags,
                )
                st.session_state.moderator_notice = (
                    f"Сохранено ({saved['action']}) в базу, id={saved['id']}, теги: {saved['tags'] or '—'}"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Не удалось сохранить запись: {e}")

# Модератор видит только тикеты, не чат пользователей
if not is_moderator:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

show_user_panel = not is_moderator
if show_user_panel:
    current_user = st.session_state.chat_username
    pending_offer = st.session_state.pending_ticket_offer_by_user.get(current_user)
    if pending_offer:
        st.warning("Есть вопрос, готовый к отправке модератору.")
        c_offer1, c_offer2 = st.columns([2, 2])
        with c_offer1:
            if st.button("Отправить вопрос человеку", key="send_pending_offer_btn"):
                ticket_id = service.create_moderation_ticket(
                    question=pending_offer.get("question", ""),
                    requester_username=st.session_state.chat_username,
                    user_role=pending_offer.get("user_role"),
                    user_circle=pending_offer.get("user_circle"),
                )
                st.session_state.pending_ticket_offer_by_user[current_user] = None
                msg = (
                    "Отправила вопрос человеку ✅\n\n"
                    f"Тикет: **#{ticket_id}**. Когда модератор ответит, я пришлю ответ в этот чат."
                )
                st.session_state.messages.append({"role": "assistant", "content": msg})
                st.rerun()
        with c_offer2:
            if st.button("Пока не отправлять", key="skip_pending_offer_btn"):
                st.session_state.pending_ticket_offer_by_user[current_user] = None
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": "Ок, не отправляю вопрос на модерацию. Если понадобится, можно отправить его позже.",
                    }
                )
                st.rerun()

    with st.expander("Нужна помощь человека? Отправь вопрос модератору", expanded=True):
        current_notice = st.session_state.user_notices_by_user.get(current_user, "")
        if current_notice:
            st.success(current_notice)
            st.session_state.user_notices_by_user[current_user] = ""
        with st.form("user_manual_ticket_form", clear_on_submit=True):
            user_ticket_question = st.text_area(
                "Вопрос для модератора",
                placeholder="Напиши вопрос, который нужно передать человеку...",
            )
            send_user_ticket = st.form_submit_button("Отправить вопрос человеку")
        if send_user_ticket:
            q = (user_ticket_question or "").strip()
            if not q:
                st.warning("Напиши вопрос перед отправкой.")
            else:
                profile = st.session_state.profile
                ticket_id = service.create_moderation_ticket(
                    question=q,
                    requester_username=st.session_state.chat_username,
                    user_role=profile.get("role"),
                    user_circle=profile.get("circle"),
                )
                st.session_state.user_notices_by_user[current_user] = (
                    f"Вопрос отправлен модератору. Тикет: #{ticket_id}. Ответ придет в этот чат."
                )
                st.rerun()

if (not is_moderator) and (prompt := st.chat_input("Напиши сообщение…")):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Думаю…"):
            try:
                profile = st.session_state.profile
                role = profile.get("role")
                circle = profile.get("circle")
                leader = profile.get("leader")
                created_ticket_id = None
                handled_ticket_offer = False

                current_user = st.session_state.chat_username
                pending_offer = st.session_state.pending_ticket_offer_by_user.get(current_user)
                if pending_offer:
                    if _is_yes_reply(prompt):
                        created_ticket_id = service.create_moderation_ticket(
                            question=pending_offer.get("question", prompt),
                            requester_username=st.session_state.chat_username,
                            user_role=pending_offer.get("user_role"),
                            user_circle=pending_offer.get("user_circle"),
                        )
                        st.session_state.pending_ticket_offer_by_user[current_user] = None
                        response = (
                            "Отлично, отправила вопрос модератору ✅\n\n"
                            f"Тикет: **#{created_ticket_id}**. "
                            "Как только будет ответ, пришлю его сюда."
                        )
                        handled_ticket_offer = True
                    elif _is_no_reply(prompt):
                        st.session_state.pending_ticket_offer_by_user[current_user] = None
                        response = (
                            "Ок, не отправляю этот вопрос модератору.\n\n"
                            "Если передумаешь, напиши вопрос еще раз и ответь `да`."
                        )
                        handled_ticket_offer = True
                    else:
                        info = _apply_informative_user_message(profile, prompt)
                        if info["informative"]:
                            role = profile.get("role")
                            circle = profile.get("circle")
                            response = _build_informative_ack(
                                profile,
                                info,
                                keep_pending_offer=True,
                            )
                            handled_ticket_offer = True
                        elif _looks_like_small_talk(prompt):
                            response = (
                                "Супер, на связи 😊\n\n"
                                "По предыдущему вопросу тикет всё еще ждёт решения: "
                                "нажми **Отправить вопрос человеку** ниже или ответь `да`/`нет`."
                            )
                            handled_ticket_offer = True
                        else:
                            response = "Чтобы продолжить, ответь, пожалуйста: **да** или **нет**."
                            handled_ticket_offer = True

                # Прямая просьба «передай модератору» — сразу создаём тикет
                if not handled_ticket_offer and _is_direct_moderator_request(prompt):
                    history = [
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state.messages[-10:]
                    ]
                    ticket_question = _extract_question_from_history_for_ticket(history, prompt)
                    if ticket_question:
                        created_ticket_id = service.create_moderation_ticket(
                            question=ticket_question,
                            requester_username=st.session_state.chat_username,
                            user_role=profile.get("role"),
                            user_circle=profile.get("circle"),
                        )
                        response = (
                            "Отлично, отправила вопрос модератору ✅\n\n"
                            f"Тикет: **#{created_ticket_id}**. "
                            "Как только будет ответ, пришлю его сюда."
                        )
                        handled_ticket_offer = True

                if not handled_ticket_offer:
                    _apply_informative_user_message(profile, prompt)
                    if profile.get("role") and profile.get("circle"):
                        profile["started"] = True
                    if _extract_leader(prompt):
                        profile["leader"] = _extract_leader(prompt)
                    _update_progress(prompt, profile["progress"])
                    next_task = _next_task(profile["progress"])
                    history = [
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state.messages[-10:]
                    ]
                    # При выключенном LLM и приветствии/малом разговоре — короткий ответ, не поиск по базе.
                    if not service.llm_enabled and _looks_like_small_talk(prompt):
                        response = (
                            "Привет! Чем могу помочь? Можешь спросить про процессы, аббревиатуры или каналы — "
                            "поищу в базе знаний. Если напишешь роль и круг, подскажу точнее."
                        )
                    else:
                        response = service.generate_reply(
                        prompt,
                        history=history,
                        profile=profile,
                        next_task=next_task,
                    )
                    # Заменять на тикет, если GPT явно предлагает передать модератору — всегда.
                    # Иначе — только когда нет релевантного ответа в базе (GPT мог добавить «уточнить» как оговорку).
                    has_kb_answer = service.has_strong_kb_match(prompt, history=history)
                    escalation_phrases = (
                        "передам вопрос модератору", "направлю тикет", "передать модератору",
                        "передам модератору", "отправлю модератору", "предложи передать",
                        "предлагаю передать", "передай вопрос", "передать вопрос",
                        "могу передать", "могу отправить",
                    )
                    explicit_escalation = any(
                        phrase in (response or "").lower()
                        for phrase in escalation_phrases
                    )
                    ticket_question = prompt
                    if explicit_escalation and history:
                        for m in reversed(history):
                            prev = (m.get("content") or "").strip()
                            if (
                                m.get("role") == "user"
                                and len(prev) > 3
                                and prev != prompt
                                and not _looks_like_small_talk(prev)
                            ):
                                if _looks_like_question(prev) or _looks_like_term_or_abbreviation_query(prev):
                                    ticket_question = prev
                                    break
                    if (
                        created_ticket_id is None
                        and (_looks_like_question(prompt) or _looks_like_term_or_abbreviation_query(prompt) or explicit_escalation)
                        and (
                            explicit_escalation
                            or (not has_kb_answer and _contains_uncertainty_language(response))
                        )
                    ):
                        response = _prepare_ticket_offer(
                            ticket_question,
                            profile.get("role"),
                            profile.get("circle"),
                            st.session_state.chat_username,
                        )

                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
                if created_ticket_id is not None:
                    st.rerun()
            except Exception as e:
                err_msg = f"Ошибка: {e}"
                st.error(err_msg)
                st.session_state.messages.append({"role": "assistant", "content": err_msg})
