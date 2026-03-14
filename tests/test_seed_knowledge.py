"""
Тесты для seed_knowledge.py и структуры базы знаний.
"""
import sys
from pathlib import Path

import pytest

# Добавляем корень проекта в path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.seed_knowledge import SEED_ITEMS


class TestSeedStructure:
    """Проверка структуры SEED_ITEMS."""

    def test_seed_items_not_empty(self):
        """База знаний не пустая."""
        assert len(SEED_ITEMS) > 100

    def test_each_item_has_required_fields(self):
        """Каждая запись содержит question, answer, tags."""
        for item in SEED_ITEMS:
            assert "question" in item, f"Missing question in: {item}"
            assert "answer" in item, f"Missing answer in: {item}"
            assert "tags" in item, f"Missing tags in: {item}"

    def test_questions_non_empty(self):
        """Вопросы не пустые."""
        for item in SEED_ITEMS:
            assert item["question"].strip(), f"Empty question: {item}"

    def test_answers_non_empty(self):
        """Ответы не пустые."""
        for item in SEED_ITEMS:
            assert item["answer"].strip(), f"Empty answer: {item}"

    def test_no_duplicate_questions(self):
        """Нет дубликатов вопросов."""
        questions = [item["question"] for item in SEED_ITEMS]
        assert len(questions) == len(set(questions)), "Duplicate questions found"

    def test_marketing_entries_exist(self):
        """Есть записи по Маркетингу."""
        marketing_items = [
            i for i in SEED_ITEMS
            if "marketing" in (i.get("tags") or "").lower()
            or "маркетинг" in (i.get("question") or "").lower()
        ]
        assert len(marketing_items) >= 4, "Expected at least 4 Marketing entries"
