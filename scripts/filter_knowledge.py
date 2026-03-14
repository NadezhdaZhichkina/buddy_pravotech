#!/usr/bin/env python3
"""
Фильтрация базы знаний: удаление рисков, дубликатов, узкоспециализированных записей.
Результат перезаписывает SEED_ITEMS в seed_knowledge.py.
"""
import importlib.util
import json
import re
from pathlib import Path

script_dir = Path(__file__).parent
seed_path = script_dir / "seed_knowledge.py"

spec = importlib.util.spec_from_file_location("seed_knowledge", seed_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

items = mod.SEED_ITEMS.copy()

# Вопросы для исключения (подстрока в вопросе)
EXCLUDE_PATTERNS = [
    # Риски
    "риск", "рисками",
    # Sales-специфика
    "Miro для Sales", "описание продуктов PravoTech", "KYC по сделкам",
    "конверсию в проведённые презентации", "KAM Sales и ДРМ",
    "роли в New Logo Sales", "роли в KAM Sales", "онбординг Sales",
    "онбординг Business Development", "судебную систему России",
    "банкротство и этапы", "роли в юридическом департаменте клиента",
    "структура круга Sales", "материалы Researchers", "письмо почтой РФ",
    # New Business / Discovery продукты
    "ПравоПатент", "сегмент", "ЦА у продукта Управляй", "Европлан",
    "Право (риски) Web", "Право (консультант)", "Право (суды)",
    "Право (Взыскания)", "Право (Навыки)", "Право (Диалог)",
    "Право (Корпорация)", "роли в продукте Право (Риски)",
    "инструменты валидации гипотез", "участие в Discovery-команде",
    "роли в NB/Discovery", "роли есть в NB", "NB/Discovery", "PRD (product requirements",
    # Docs circle
    "задачу W.Docs", "задачу K.Docs", "задачу сервисному кругу Docs",
    "доверенность МД", "KAM Sales оформить Upsale", "Docs, Legal и Partners",
    "САД и Docs", "автооферту без Docs", "W.Docs", "K.Docs",
    # Projects Team III
    "Projects Team III", "песочницы Case.one", "очистить инстанс",
    "обновить шаблоны системных отчетов", "перенести сценарии",
    # Legal процедуры
    "чек-листы Legal", "расходный договор", "чек-лист договора ГПХ",
    "соглашение о сотрудничестве", "задачу Legal", "агентами и партнёрами",
    "журнал регистрации исходящей", "нормативные требования к коммуникациям",
    "академическую лицензию вузу",
    # Лидерство / HR-специфика
    "создать новую роль в компании", "роль Интегратора",
    "индекс лидера и как он считается", "увеличить бюджет ФОТ",
    "начать найм нового сотрудника", "собрать онбординг для роли",
    "добавить навыки в библиотеку", "бюджет на тимбилдинг у круга",
    "заявку на мотивацию круга", "заполнить график отпусков",
    "лидерские коины", "создать операционный круг",
    "информацию для лидера",
    # Финансы-специфика
    "инвестиционные затраты на тестирование", "финансовую модель нового продукта",
    # Слишком технические
    "Auth Service", "Anonymizer Service", "AI Proxy",
    "BPMN", "элементы и символы есть в BPMN",
    # Дубликаты / избыточные
    "Как AI добавляет описания к роликам",
    "В чём миссия PravoTech",  # есть в "Расскажи о компании"
    "Что такое 101 или 1-to-1",  # дублирует "встреча 1-to-1"
    "Что такое E1 и для чего",  # дублирует "Что такое E1?"
]

def should_exclude(q: str) -> bool:
    q_lower = q.lower()
    for pat in EXCLUDE_PATTERNS:
        if pat.lower() in q_lower:
            return True
    return False

def normalize_for_dedup(q: str) -> str:
    """Нормализация для поиска дубликатов."""
    return re.sub(r'\s+', ' ', q.lower().strip())

# Фильтрация
filtered = []
seen_normalized = set()

for item in items:
    q = item["question"]
    if should_exclude(q):
        continue
    norm = normalize_for_dedup(q)
    if norm in seen_normalized:
        continue
    seen_normalized.add(norm)
    filtered.append(item)

# Собираем новый файл
with open(seed_path, "r", encoding="utf-8") as f:
    content = f.read()

start_marker = "SEED_ITEMS = ["
end_marker = "]\n\n\ndef main"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)
if start_idx == -1 or end_idx == -1:
    raise SystemExit(f"Не найден SEED_ITEMS (start={start_idx}, end={end_idx})")

# Формируем новый SEED_ITEMS (Python-синтаксис)
lines = ["SEED_ITEMS = ["]
for item in filtered:
    d = {"question": item["question"], "answer": item["answer"], "tags": item.get("tags", "")}
    s = json.dumps(d, ensure_ascii=False, indent=4)
    lines.append("    " + s.replace("\n", "\n    ") + ",")
lines.append("]")

new_items_str = "\n".join(lines)
# end_idx указывает на "]", content[end_idx+1:] = "\n\n\ndef main..."
new_content = content[:start_idx] + new_items_str + content[end_idx + 1:]

with open(seed_path, "w", encoding="utf-8") as f:
    f.write(new_content)

print(f"Было: {len(items)}, стало: {len(filtered)}")
print(f"Удалено: {len(items) - len(filtered)}")
