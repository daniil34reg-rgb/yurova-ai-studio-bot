from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserRole(str, PyEnum):
    user = "user"
    admin = "admin"
    banned = "banned"


class PaymentStatus(str, PyEnum):
    pending = "pending"
    confirmed = "confirmed"
    rejected = "rejected"


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    prize_name: Mapped[str] = mapped_column(String(128), nullable=False)
    photo_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    price_per_sticker: Mapped[float] = mapped_column(Float, default=1999.9, nullable=False)
    qr_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)  # legacy, kept for compat
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_codes: Mapped[list["PromotionQR"]] = relationship(
        "PromotionQR", back_populates="promotion", cascade="all, delete-orphan"
    )
    payment_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sticker_buttons: Mapped[list["StickerButton"]] = relationship(
        "StickerButton", back_populates="promotion", cascade="all, delete-orphan",
        order_by="StickerButton.sort_order"
    )

class StickerButton(Base):
    __tablename__ = "sticker_buttons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promotion_id: Mapped[int] = mapped_column(Integer, ForeignKey("promotions.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)   # текст кнопки
    sticker_count: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    row_width: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    promotion: Mapped["Promotion"] = relationship("Promotion", back_populates="sticker_buttons")

class PromotionQR(Base):
    __tablename__ = "promotion_qr_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promotion_id: Mapped[int] = mapped_column(Integer, ForeignKey("promotions.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "Альфа-Банк"
    # Kept in the existing table for backwards compatibility. A payment
    # method can now be either an uploaded QR image or an external link.
    method_type: Mapped[str] = mapped_column(String(16), default="qr", nullable=False)
    file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payment_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    promotion: Mapped["Promotion"] = relationship("Promotion", back_populates="qr_codes")


class SavedQR(Base):
    __tablename__ = "saved_qr_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    file_id: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SentQRMessage(Base):
    """A QR message scheduled for deletion from a user's Telegram chat."""

    __tablename__ = "sent_qr_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    delete_after: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class SavedStickerButtonConfig(Base):
    __tablename__ = "saved_sticker_button_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    buttons: Mapped[list["SavedStickerButton"]] = relationship(
        "SavedStickerButton",
        back_populates="config",
        cascade="all, delete-orphan",
        order_by="SavedStickerButton.sort_order",
    )


class SavedStickerButton(Base):
    __tablename__ = "saved_sticker_buttons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_id: Mapped[int] = mapped_column(Integer, ForeignKey("saved_sticker_button_configs.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    sticker_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    row_width: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    config: Mapped["SavedStickerButtonConfig"] = relationship("SavedStickerButtonConfig", back_populates="buttons")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    customer_full_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.user, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="user")
    accesses: Mapped[list["AccessRecord"]] = relationship("AccessRecord", back_populates="user")
    profile_changes: Mapped[list["UserProfileChange"]] = relationship(
        "UserProfileChange",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="UserProfileChange.changed_at",
    )


class UserProfileChange(Base):
    __tablename__ = "user_profile_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(32), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="profile_changes")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), default=PaymentStatus.pending, nullable=False
    )
    screenshot_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payment_method: Mapped[str] = mapped_column(String(64), default="card", nullable=False)
    admin_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="payments")


class AccessRecord(Base):
    __tablename__ = "access_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    access_type: Mapped[str] = mapped_column(String(64), default="channel", nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["User"] = relationship("User", back_populates="accesses")

class BotSettings(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
