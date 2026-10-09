"""ORM 模型。

六张表一次定义完整（含阶段 2~4 才会用到的事件 / 纪念日 / 提醒），
这样初始迁移就是完整的，后面不用为了加表反复生成迁移。
"""

from datetime import UTC, date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# 身份标签，只用于界面展示
ROLE_FEMALE = "female"
ROLE_MALE = "male"

# 追踪的指标类型。业务逻辑一律判断 metric_type 而不是 role，
# 这样「记什么」和「性别标签」解耦，以后想让两人都记睡眠+锻炼不必改逻辑。
METRIC_SLEEP = "sleep"
METRIC_EXERCISE = "exercise"

METRIC_LABELS = {METRIC_SLEEP: "睡眠时长", METRIC_EXERCISE: "锻炼时长"}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    """只会有两条记录。没有注册流程，用 scripts/create_users.py 创建。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(16))
    metric_type: Mapped[str] = mapped_column(String(16))

    # 当前达标值（分钟）。改动它不影响已存档的历史记录，见 DailyRecord.target_minutes
    target_minutes: Mapped[int] = mapped_column(Integer, default=480)

    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")

    push_provider: Mapped[str | None] = mapped_column(String(16), nullable=True)
    push_token: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    records: Mapped[list["DailyRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def metric_label(self) -> str:
        return METRIC_LABELS.get(self.metric_type, self.metric_type)


class DailyRecord(Base):
    """每日打卡。核心表。

    ``target_minutes`` 和 ``deviation_minutes`` 是刻意冗余存储的快照：
    达标值可以在设置页随时修改，如果偏差值靠「读当前达标值实时计算」，
    改一次目标就会把全部历史存档静默改写。所以实际值、当时的目标值、
    当时算出的偏差，三者一起入库。
    """

    __tablename__ = "daily_records"
    __table_args__ = (
        # 顺带解决并发：两人各写自己的行，不可能互相覆盖
        UniqueConstraint("user_id", "record_date", name="uq_daily_user_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    record_date: Mapped[date] = mapped_column(Date, index=True)

    actual_minutes: Mapped[int] = mapped_column(Integer)
    target_minutes: Mapped[int] = mapped_column(Integer)
    deviation_minutes: Mapped[int] = mapped_column(Integer)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="records")

    @property
    def on_target(self) -> bool:
        return self.deviation_minutes >= 0


class Event(Base):
    """事件记录。start_time / end_time 为空表示全天事件。"""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    event_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    is_shared: Mapped[bool] = mapped_column(Boolean, default=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Anniversary(Base):
    """纪念日。recurrence: yearly | monthly | once"""

    __tablename__ = "anniversaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    recurrence: Mapped[str] = mapped_column(String(16), default="yearly")

    # 是否展示「已经第 N 天」
    show_countup: Mapped[bool] = mapped_column(Boolean, default=True)
    remind_days_before: Mapped[int] = mapped_column(Integer, default=3)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Reminder(Base):
    """提醒配置。user_id 为空表示两人都提醒。"""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # daily_checkin|anniversary|event|custom
    title: Mapped[str] = mapped_column(String(200))
    cron_time: Mapped[str] = mapped_column(String(5))  # 'HH:MM'，按用户时区解释
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ReminderLog(Base):
    """提醒发送日志。

    唯一约束是提醒可靠性的基石：平台 cron 可能重复触发、服务可能重启，
    有了 (reminder, user, date) 唯一约束，重复调用也只会真正推送一次。
    """

    __tablename__ = "reminder_logs"
    __table_args__ = (
        UniqueConstraint(
            "reminder_id", "user_id", "sent_date", name="uq_reminder_once_per_day"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reminder_id: Mapped[int] = mapped_column(
        ForeignKey("reminders.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    sent_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(16))  # sent | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
