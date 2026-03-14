# Деплой Buddy в Streamlit Cloud

Чтобы дать ссылку на чат для тестирования, разверни приложение на [Streamlit Community Cloud](https://streamlit.io/cloud) — бесплатный хостинг для Streamlit.

## Шаг 1: Репозиторий на GitHub

1. Создай репозиторий на GitHub (если ещё нет).
2. Залей код:

```bash
cd buddy
git init
git add .
git commit -m "Buddy онбординг-агент"
git branch -M main
git remote add origin https://github.com/ТВОЙ_ЮЗЕРНЕЙМ/НАЗВАНИЕ_РЕПО.git
git push -u origin main
```

## Шаг 2: Деплой на Streamlit Cloud

1. Зайди на [share.streamlit.io](https://share.streamlit.io)
2. Войди через GitHub
3. Нажми **New app**
4. Выбери репозиторий, ветку `main`
5. **Main file path:** `streamlit_app.py`
6. Нажми **Deploy**

Через 1–2 минуты появится ссылка вида:  
`https://ТВОЙ-АПП.streamlit.app`

## Шаг 3: Секреты (опционально)

Для работы LLM (OpenRouter) добавь секреты в Streamlit Cloud:

1. В приложении на share.streamlit.io → **Settings** → **Secrets**
2. Добавь в формате TOML:

```toml
OPENROUTER_API_KEY = "sk-or-v1-..."
OPENROUTER_MODEL = "openai/gpt-4.1-mini"
```

Без ключа Buddy отвечает из базы знаний (без LLM).

## Локальный запуск Streamlit

```bash
cd buddy
source .venv/bin/activate
streamlit run streamlit_app.py
```

Откроется http://localhost:8501

## Примечания

- **База данных:** на Streamlit Cloud используется SQLite в памяти — данные сбрасываются при перезапуске. База знаний заполняется при первом запуске.
- **FastAPI** (для Mattermost webhook) нужно деплоить отдельно (Render, Railway и т.п.), если нужна интеграция с Mattermost.
