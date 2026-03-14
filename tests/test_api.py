"""
Тесты API Buddy (healthcheck, knowledge).
"""
import os

# Файловая БД для тестов (in-memory даёт разную БД на каждый connection в пуле)
os.environ["DATABASE_URL"] = "sqlite:///./test_buddy.db"

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestHealthcheck:
    """Проверка healthcheck."""

    def test_root_returns_ok(self):
        """GET / возвращает статус работы."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Buddy" in resp.text or "buddy" in resp.text.lower()
        assert "/chat" in resp.text or "running" in resp.text.lower() or "работает" in resp.text


class TestKnowledgeAPI:
    """Проверка API базы знаний."""

    def test_add_knowledge_requires_question_and_answer(self):
        """POST /api/knowledge требует question и answer."""
        resp = client.post("/api/knowledge", json={})
        assert resp.status_code in (400, 422)  # validation/required fields

        resp = client.post("/api/knowledge", json={"question": "Тест?", "answer": "Да"})
        assert resp.status_code == 200
        assert "OK" in resp.text

    def test_webhook_accepts_valid_payload(self):
        """Webhook принимает валидный payload и возвращает ответ."""
        payload = {
            "user_name": "test_user",
            "bot_user_id": "buddy-bot-id",
            "post": '{"id":"p1","user_id":"u1","channel_id":"c1","message":"привет","root_id":""}',
        }
        resp = client.post("/mattermost/webhook", json=payload)
        assert resp.status_code == 200
        assert "Buddy" in resp.text or "онбординг" in resp.text or "роль" in resp.text
