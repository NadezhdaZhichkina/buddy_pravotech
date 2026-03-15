"""
Buddy — онбординг-агент. Streamlit-интерфейс для тестирования.
Запуск: streamlit run streamlit_app.py
"""
import streamlit as st

st.set_page_config(
    page_title="Buddy — онбординг-агент",
    page_icon="🤖",
    layout="centered",
)

# Инициализация при первом запуске
try:
    from app.streamlit_chat import StreamlitChatService

    def _get_secret(name: str, default: str = "") -> str:
        try:
            return str(st.secrets.get(name, default))
        except Exception:
            return default

    service = StreamlitChatService(
        openrouter_api_key=_get_secret("OPENROUTER_API_KEY", ""),
        openrouter_model=_get_secret("OPENROUTER_MODEL", "openai/gpt-4.1-mini"),
    )
except Exception as e:
    st.error(f"Ошибка инициализации: {e}")
    st.stop()

st.title("🤖 Buddy — онбординг-агент")
st.caption("Задавай вопросы о компании, отпуске, доступах, процессах. Я ищу релевантное в базе и формирую ответ через GPT (если настроен ключ OpenRouter).")
if service.llm_enabled:
    st.success("LLM: включен (OpenRouter)")
else:
    st.info("LLM: выключен — ответы только по базе знаний. Добавь OPENROUTER_API_KEY в Secrets Streamlit Cloud.")

# Инициализация истории чата
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Привет! Я Buddy — ИИ-помощник по онбордингу. Задавай любой вопрос: о компании, отпуске, доступах, процессах."}
    ]

# Показываем историю
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Поле ввода
if prompt := st.chat_input("Напиши вопрос…"):
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Думаю…"):
            try:
                response = service.answer(prompt)
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
            except Exception as e:
                err_msg = f"Ошибка: {e}"
                st.error(err_msg)
                st.session_state.messages.append({"role": "assistant", "content": err_msg})
