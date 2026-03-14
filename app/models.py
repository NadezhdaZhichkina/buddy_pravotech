from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    mattermost_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str] = mapped_column(String(64), default="new")  # new, awaiting_role, onboarding, qa
    onboarding_step_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    questions: Mapped[list["Question"]] = relationship("Question", back_populates="user")


class QuestionStatusEnum(str):
    UNANSWERED = "unanswered"
    AWAITING_HUMAN = "awaiting_human"
    ANSWERED = "answered"


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Enum(
            QuestionStatusEnum.UNANSWERED,
            QuestionStatusEnum.AWAITING_HUMAN,
            QuestionStatusEnum.ANSWERED,
            name="question_status",
        ),
        default=QuestionStatusEnum.UNANSWERED,
    )
    mattermost_root_post_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mattermost_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # DM канал новичка
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="questions")
    answers: Mapped[list["Answer"]] = relationship("Answer", back_populates="question")


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    author_type: Mapped[str] = mapped_column(String(16))  # bot | human
    author_mattermost_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    question: Mapped["Question"] = relationship("Question", back_populates="answers")


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

