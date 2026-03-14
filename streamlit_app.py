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
    from app.chat_service import get_answer, get_session
    get_session()  # создаёт БД и заполняет базу при первом запуске
except Exception as e:
    st.error(f"Ошибка инициализации: {e}")
    st.stop()

st.title("🤖 Buddy — онбординг-агент")
st.caption("Задавай вопросы о компании, отпуске, доступах, процессах. Отвечаю из базы знаний.")

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
                response = get_answer(prompt)
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
            except Exception as e:
                err_msg = f"Ошибка: {e}"
                st.error(err_msg)
                st.session_state.messages.append({"role": "assistant", "content": err_msg})
