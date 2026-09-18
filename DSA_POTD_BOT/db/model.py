from datetime import date
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    Enum,
    String,
    Date,
    ForeignKey,
    JSON
)

from sqlalchemy.orm import relationship

from db.base import Base


# ENUMS

class Year(str, PyEnum):
    first = "1st"
    second = "2nd"
    third = "3rd"
    final = "final"
    working = "working"


class Org_type(str, PyEnum):
    service = "service"
    product = "product"
    toptech = "toptech"
    hft = "hft"


class Level(str, PyEnum):
    beginner = "beginner"
    intermediate = "intermediate"
    pro = "pro"


class Status(str, PyEnum):
    active = "active"
    inactive = "inactive"
    trial = "trial"


class Source(str, PyEnum):
    leetcode = "leetcode"
    codeforces = "codeforces"


class Difficulty(str, PyEnum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class Log_Status(str, PyEnum):
    pending = "pending"
    solved = "solved"
    skipped = "skipped"


class Slot(str, PyEnum):
    morning = "morning"
    evening = "evening"


# TABLES


# USERS TABLE
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    year = Column(Enum(Year), nullable=False)
    org_type = Column(Enum(Org_type), nullable=False)
    level = Column(Enum(Level), nullable=False)
    trial_start = Column(Date, default=date.today)
    subscription_end = Column(Date)
    status = Column(Enum(Status), nullable=False)
    created_at = Column(Date, default=date.today)

    user_question_log = relationship(
        "User_Question_Log",
        back_populates="user"
    )

    payments = relationship(
        "Payment",
        back_populates="user"
    )


# QUESTIONS TABLE
class Questions(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(Enum(Source), nullable=False)
    title = Column(String(500), nullable=False)
    url = Column(String(500), nullable=False)
    difficulty = Column(Enum(Difficulty), nullable=False)
    tags = Column(JSON, nullable=True)
    rating = Column(Integer, nullable=True)
    external_id = Column(String(200), unique=True, nullable=True)

    user_question_log = relationship(
        "User_Question_Log",
        back_populates="question"
    )

    daily_question_log = relationship(
        "Daily_Question_Log",
        back_populates="question"
    )


# USER QUESTION LOG
class User_Question_Log(Base):
    __tablename__ = "user_question_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )
    question_id = Column(
        Integer,
        ForeignKey("questions.id"),
        nullable=False
    )
    send_at = Column(Date)
    status = Column(Enum(Log_Status))

    user = relationship(
        "User",
        back_populates="user_question_log"
    )

    question = relationship(
        "Questions",
        back_populates="user_question_log"
    )


# DAILY QUESTION LOG
class Daily_Question_Log(Base):
    __tablename__ = "daily_question_log"

    id = Column(Integer, primary_key=True, index=True)
    bucket_key = Column(String(100), nullable=False)
    question_id = Column(
        Integer,
        ForeignKey("questions.id"),
        nullable=False
    )
    slot = Column(Enum(Slot), nullable=False)
    date = Column(Date)

    question = relationship(
        "Questions",
        back_populates="daily_question_log"
    )


# PAYMENTS
class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )
    stars_amount = Column(Integer, default=5)
    paid_at = Column(Date)
    valid_till = Column(Date)

    user = relationship(
        "User",
        back_populates="payments"
    )