from typing import Any, Dict, List


# Сценарии онбординга по ролям. Тон — тёплый, по-человечески.
ONBOARDING_SCENARIOS: Dict[str, List[Dict[str, Any]]] = {
    "default": [
        {
            "id": "welcome",
            "type": "message",
            "text": "Рад познакомиться! Я Buddy — твой помощник на первые дни в компании. Буду рядом: подскажу, куда смотреть, и отвечу на вопросы. Пиши в любое время.",
        },
        {
            "id": "day1_overview",
            "type": "message",
            "text": "Сейчас расскажу про команду, процессы и инструменты. Если что-то непонятно — сразу спрашивай, не стесняйся.",
        },
        {
            "id": "tools",
            "type": "message",
            "text": "Из главного: общаемся в Mattermost, задачи ведём в Jira, код — в GitHub. Ссылки и доступы подскажу по запросу.",
        },
        {
            "id": "mentor",
            "type": "message",
            "text": "У тебя есть наставник — он поможет влиться. Если не знаешь, к кому обратиться по теме — спроси меня, подскажу.",
        },
        {
            "id": "questions_hint",
            "type": "message",
            "text": "Главное: задавай любые вопросы. Знаю ответ — расскажу. Не знаю — спрошу коллег и вернусь с ответом. Так и устроено.",
        },
    ],
    "backend": [
        {
            "id": "backend_intro",
            "type": "message",
            "text": "Как backend‑разработчик ты будешь работать с нашим API и микросервисами. Если нужны детали по стеку или репозиториям — спрашивай.",
        },
        {
            "id": "backend_repos",
            "type": "message",
            "text": "Ключевые репо: api-gateway, user-service, billing-service. Ссылки и доступы — в базе знаний или у тимлида.",
        },
    ],
    "frontend": [
        {
            "id": "frontend_intro",
            "type": "message",
            "text": "Как frontend‑разработчик ты будешь работать с дизайн‑системой и нашими SPA. Если нужны ссылки или гайды — пиши.",
        },
        {
            "id": "frontend_repos",
            "type": "message",
            "text": "Основные репо: web-app, design-system. Документация и доступы — в базе знаний.",
        },
    ],
    "marketing": [
        {
            "id": "marketing_intro",
            "type": "message",
            "text": "В маркетинге много направлений: Acquisition, креатив, контент. Задачи ставятся через Fokus, проект Marketing. Подробности — в базе знаний.",
        },
        {
            "id": "marketing_tools",
            "type": "message",
            "text": "Если нужны доступы к Figma, Midjourney или другому софту — в базе знаний есть контакты держателей. Или спроси у лидера круга.",
        },
    ],
    "manager": [
        {
            "id": "manager_intro",
            "type": "message",
            "text": "Как менеджер ты будешь работать с командой и процессами. Структура, OKR, задачи — всё в базе знаний. Спрашивай, что нужно.",
        },
    ],
    "designer": [
        {
            "id": "designer_intro",
            "type": "message",
            "text": "Дизайнеры у нас в креативе и в продукте. Figma, доступы к стокам — в базе знаний. Если что-то не найдёшь — пиши, подскажу.",
        },
    ],
    "sales": [
        {
            "id": "sales_intro",
            "type": "message",
            "text": "В продажах у нас New Logo и KAM. CRM, воронка, материалы — в базе знаний и Sales Wiki. Спрашивай, что нужно.",
        },
    ],
}


# Алиасы ролей: пользователь может написать по-разному
ROLE_ALIASES: Dict[str, str] = {
    "маркетинг": "marketing",
    "маркетолог": "marketing",
    "дизайнер": "designer",
    "дизайн": "designer",
    "менеджер": "manager",
    "менеджер по документам": "manager",
    "менедже": "manager",  # опечатка
    "продажи": "sales",
    "sales": "sales",
    "бэкенд": "backend",
    "бекенд": "backend",
    "фронтенд": "frontend",
    "фронт": "frontend",
}

# Как показывать роль пользователю (красиво)
ROLE_DISPLAY: Dict[str, str] = {
    "backend": "backend‑разработчик",
    "frontend": "frontend‑разработчик",
    "marketing": "маркетолог",
    "manager": "менеджер",
    "designer": "дизайнер",
    "sales": "в продажах",
}


def extract_role_from_message(text: str) -> str:
    """
    Извлекает роль из фраз вроде «я менеджер», «менеджер», «работаю в маркетинге».
    Возвращает нормализованный ключ роли.
    """
    t = (text or "").lower().strip()
    # Убираем типичные префиксы
    for prefix in ("я ", "я - ", "я-", "работаю ", "работаю в ", "это ", "это "):
        if t.startswith(prefix):
            t = t[len(prefix) :].strip()
    # Проверяем точное совпадение или вхождение
    if t in ROLE_ALIASES:
        return ROLE_ALIASES[t]
    if t in ONBOARDING_SCENARIOS:
        return t
    # Ищем роль внутри фразы
    for alias, role_key in ROLE_ALIASES.items():
        if alias in t or t in alias:
            return role_key
    for role_key in ONBOARDING_SCENARIOS:
        if role_key != "default" and role_key in t:
            return role_key
    return t  # как есть


def get_display_role(role_key: str) -> str:
    """Красивое отображение роли для ответа пользователю."""
    return ROLE_DISPLAY.get(role_key, role_key)


def get_scenario_for_role(role: str | None) -> List[Dict[str, Any]]:
    role_key = extract_role_from_message(role or "")
    parts: List[Dict[str, Any]] = []
    parts.extend(ONBOARDING_SCENARIOS["default"])
    if role_key in ONBOARDING_SCENARIOS:
        parts.extend(ONBOARDING_SCENARIOS[role_key])
    return parts

