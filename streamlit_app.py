"""
Buddy — онбординг-агент. Streamlit-интерфейс для тестирования.
Запуск: streamlit run streamlit_app.py
"""

import os
import random

import streamlit as st

st.set_page_config(
    page_title="Buddy — онбординг-агент",
    page_icon="🤖",
    layout="centered",
)

# Инициализация при первом запуске
try:
    from app.onboarding import ROLE_DISPLAY, extract_role_from_message, get_display_role
    from app.streamlit_chat import StreamlitChatService

    def _get_secret(name: str, default: str = "") -> str:
        try:
            return str(st.secrets.get(name, default))
        except Exception:
            return default

    def _get_openrouter_api_key() -> str:
        variants = [
            "OPENROUTER_API_KEY",
            "openrouter_api_key",
            "OPEN_ROUTER_API_KEY",
        ]
        for k in variants:
            v = _get_secret(k, "").strip()
            if v:
                return v
        return os.getenv("OPENROUTER_API_KEY", "").strip()

    def _get_openrouter_model() -> str:
        variants = [
            "OPENROUTER_MODEL",
            "openrouter_model",
        ]
        for k in variants:
            v = _get_secret(k, "").strip()
            if v:
                return v
        return os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini").strip()

    resolved_key = _get_openrouter_api_key()
    resolved_model = _get_openrouter_model()

    service = StreamlitChatService(
        openrouter_api_key=resolved_key,
        openrouter_model=resolved_model,
    )
except Exception as e:
    st.error(f"Ошибка инициализации: {e}")
    st.stop()

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
}

STARTER_TASKS = [
    {
        "id": "mchat_setup",
        "title": "Установить и настроить MChat (Mattermost)",
        "hint": "Если нужно, подскажу адрес сервера и как авторизоваться.",
    },
    {
        "id": "join_channels",
        "title": "Подписаться на каналы `news`, `talk`, `benefits`, `okr`, `правократия`, `pravo_job`",
        "hint": "После этого будет проще не пропустить важное.",
    },
    {
        "id": "intro_post",
        "title": "Отправить приветственный пост в `talk`",
        "hint": "Если хочешь, дам короткий шаблон поста под твою роль.",
    },
    {
        "id": "check_access",
        "title": "Проверить доступы к E1, HR, FOKUS и почте",
        "hint": "Если где-то нет доступа — подскажу, куда завести заявку.",
    },
]


def _extract_circle(text: str) -> str | None:
    t = (text or "").lower()
    for alias, normalized in CIRCLE_ALIASES.items():
        if alias in t:
            return normalized
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


def _looks_like_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if "?" in t:
        return True
    return any(t.startswith(w + " ") or t == w for w in QUESTION_WORDS)


def _update_progress(text: str, progress: dict[str, bool]) -> list[str]:
    t = (text or "").lower()
    changed = []

    if _has_done_signal(t):
        if any(w in t for w in ("mchat", "mattermost", "маттермост", "мчат")) and not progress["mchat_setup"]:
            progress["mchat_setup"] = True
            changed.append("MChat настроен")
        if any(w in t for w in ("канал", "каналы", "подпис")) and not progress["join_channels"]:
            progress["join_channels"] = True
            changed.append("каналы подключены")
        if any(w in t for w in ("пост", "talk", "приветствен")) and not progress["intro_post"]:
            progress["intro_post"] = True
            changed.append("приветственный пост отправлен")
        if any(w in t for w in ("доступ", "доступы", "e1", "hr", "fokus", "почта")) and not progress["check_access"]:
            progress["check_access"] = True
            changed.append("доступы проверены")

    return changed


def _next_task(progress: dict[str, bool]) -> dict | None:
    for task in STARTER_TASKS:
        if not progress.get(task["id"], False):
            return task
    return None


def _starter_plan(role: str, circle: str) -> str:
    role_text = get_display_role(role)
    return (
        f"Супер! Вижу тебя как **{role_text}** в круге **{circle}** 🙌\n\n"
        "Я помогу тебе с адаптацией. Давай начнем с простого плана на старт:\n\n"
        "1. Установи и настрой **MChat (Mattermost)**.\n"
        "2. Подпишись на каналы: `news`, `talk`, `benefits`, `okr`, `правократия`, `pravo_job`.\n"
        "3. Напиши приветственный пост в `talk`.\n"
        "4. Проверь доступы: **E1**, **HR**, **FOKUS**, **почта**.\n\n"
        "Когда сделаешь шаг — просто напиши, например: «пост уже отправила»."
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


st.title("🤖 Buddy — онбординг-агент")
st.caption(
    "Задавай вопросы о компании, отпуске, доступах, процессах. "
    "Я ищу релевантное в базе и формирую ответ через GPT (если настроен ключ OpenRouter)."
)
if service.llm_enabled:
    st.success(f"LLM: включен (OpenRouter, model: {resolved_model})")
else:
    st.info("LLM: выключен — ответы только по базе знаний. Добавь OPENROUTER_API_KEY в Secrets Streamlit Cloud.")

with st.expander("Диагностика LLM", expanded=False):
    st.write(
        {
            "llm_enabled": service.llm_enabled,
            "model": resolved_model,
            "key_detected": bool(resolved_key),
            "key_prefix": (resolved_key[:8] + "...") if resolved_key else "",
        }
    )

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "Привет! Я Buddy — помогу тебе с адаптацией в компании 👋\n\n"
                "Для начала напиши, пожалуйста, **твою роль** и **круг**.\n"
                "Например: «Я backend, круг Product»."
            ),
        }
    ]

if "profile" not in st.session_state:
    st.session_state.profile = {
        "role": None,
        "circle": None,
        "started": False,
        "progress": {task["id"]: False for task in STARTER_TASKS},
    }

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Напиши сообщение…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Думаю…"):
            try:
                profile = st.session_state.profile
                role = profile.get("role")
                circle = profile.get("circle")

                if not profile["started"]:
                    role = role or _extract_known_role(prompt)
                    circle = circle or _extract_circle(prompt)
                    profile["role"] = role
                    profile["circle"] = circle

                    if not role and not circle:
                        response = (
                            "Хочу лучше тебе помочь с адаптацией. Напиши, пожалуйста, "
                            "**роль** и **круг**. Например: «Я маркетолог, круг Marketing»."
                        )
                    elif role and not circle:
                        response = (
                            f"Супер, роль поняла: **{get_display_role(role)}**. "
                            "Теперь подскажи, в каком ты круге? Например: Product, Marketing, Sales, Legal."
                        )
                    elif circle and not role:
                        response = (
                            f"Отлично, круг: **{circle}**. "
                            "Теперь напиши, пожалуйста, твою роль (например: backend, маркетолог, менеджер)."
                        )
                    else:
                        profile["started"] = True
                        response = _starter_plan(role, circle)
                else:
                    changes = _update_progress(prompt, profile["progress"])
                    next_task = _next_task(profile["progress"])
                    is_question = _looks_like_question(prompt)
                    has_problem = _has_problem_signal(prompt)

                    if changes:
                        if next_task:
                            response = (
                                f"Класс, отметила прогресс: **{', '.join(changes)}** ✅\n\n"
                                f"Что дальше: **{next_task['title']}**\n"
                                f"{next_task['hint']}"
                            )
                        else:
                            response = (
                                f"Класс, отметила прогресс: **{', '.join(changes)}** ✅\n\n"
                                "Все стартовые шаги закрыты. Если хочешь, могу рассказать план на первую неделю по твоей роли."
                            )
                    elif has_problem:
                        answer = service.answer(prompt, user_role=role, user_circle=circle)
                        response = f"Поняла, давай решим это.\n\n{answer}"
                    elif _asks_next_step(prompt) and next_task:
                        response = (
                            f"Дальше предлагаю такой шаг: **{next_task['title']}**\n"
                            f"{next_task['hint']}"
                        )
                    elif _has_no_problem_signal(prompt) and not is_question:
                        response = _small_talk_reply(next_task)
                    elif not is_question and len(prompt.strip().split()) <= 5:
                        if next_task:
                            response = (
                                f"Приняла 👍 Тогда идем дальше: **{next_task['title']}**\n"
                                f"{next_task['hint']}\n\n"
                                "Если уже сделала — напиши коротко, и я отмечу шаг."
                            )
                        else:
                            response = _small_talk_reply(next_task)
                    else:
                        response = service.answer(prompt, user_role=role, user_circle=circle)

                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
            except Exception as e:
                err_msg = f"Ошибка: {e}"
                st.error(err_msg)
                st.session_state.messages.append({"role": "assistant", "content": err_msg})
