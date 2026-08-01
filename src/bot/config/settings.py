from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

_env_path = Path(__file__).resolve().parent.parent.parent / ".env"


def _default_database_url() -> str:
    shared_storage = Path("/app/shared")
    if shared_storage.is_dir():
        return "sqlite+aiosqlite:////app/shared/bot.db"
    return "sqlite+aiosqlite:///./data/bot.db"


class Settings(BaseSettings):
    # Bot
    BOT_TOKEN: str = ""

    # Database
    STORE_DATABASE_URL: str = "sqlite+aiosqlite:///./data/store.db"

    # Redis
    REDIS_URL: str = "memory"

    # Admins
    ADMIN_IDS: List[int] = Field(default_factory=list)

    # Usernames
    PAYMENT_MANAGER_USERNAME: str = ""
    SUPPORT_USERNAME: str = "yurov_support"

    # Alfa bank
    ALFA_RECIPIENT: str = ""
    ALFA_ACCOUNT: str = ""
    ALFA_BIC: str = ""
    ALFA_BANK_TITLE: str = "Альфа-Банк"
    ALFA_COLOR: str = "#EF3124"

    # Uralsib bank
    URALSIB_RECIPIENT: str = ""
    URALSIB_ACCOUNT: str = ""
    URALSIB_BIC: str = ""
    URALSIB_BANK_TITLE: str = "УралСиб"
    URALSIB_COLOR: str = "#0033A0"

    # Payment (generic)
    PAYMENT_CARD: str = "0000 0000 0000 0000"
    PAYMENT_RECIPIENT: str = "John Doe"
    PAYMENT_BANK: str = "Bank"
    PAYMENT_AMOUNT: int = 1000
    PAYMENT_REQUESTS_ENABLED: bool = False
    MANUAL_ISSUE_BUTTON_LABEL: str = "Выдать номера стикеров"

    # Access
    ACCESS_CHANNEL_ID: int = 0
    ACCESS_INVITE_LINK: str = ""

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",")]
        if isinstance(v, int):
            return [v]
        return v

    model_config = {
        "env_file": str(_env_path),
        "env_file_encoding": "utf-8",
        "extra": "allow",
    }

    # ── lowercase aliases used throughout the codebase ──────────────────────

    @property
    def bot_token(self) -> str:
        return self.BOT_TOKEN

    @property
    def database_url(self) -> str:
        return self.STORE_DATABASE_URL

    @property
    def redis_url(self) -> str:
        return self.REDIS_URL

    @property
    def admin_ids(self) -> List[int]:
        return self.ADMIN_IDS

    @property
    def payment_manager_username(self) -> str:
        return self.PAYMENT_MANAGER_USERNAME

    @property
    def support_username(self) -> str:
        return self.SUPPORT_USERNAME

    @property
    def alfa_recipient(self) -> str:
        return self.ALFA_RECIPIENT

    @property
    def alfa_bank_title(self) -> str:
        return self.ALFA_BANK_TITLE

    @property
    def alfa_color(self) -> str:
        return self.ALFA_COLOR

    @property
    def uralsib_recipient(self) -> str:
        return self.URALSIB_RECIPIENT

    @property
    def uralsib_bank_title(self) -> str:
        return self.URALSIB_BANK_TITLE

    @property
    def uralsib_color(self) -> str:
        return self.URALSIB_COLOR

    @property
    def payment_card(self) -> str:
        return self.PAYMENT_CARD

    @property
    def payment_recipient(self) -> str:
        return self.PAYMENT_RECIPIENT

    @property
    def payment_bank(self) -> str:
        return self.PAYMENT_BANK

    @property
    def payment_amount(self) -> int:
        return self.PAYMENT_AMOUNT

    @property
    def payment_requests_enabled(self) -> bool:
        return self.PAYMENT_REQUESTS_ENABLED

    @property
    def access_channel_id(self) -> int:
        return self.ACCESS_CHANNEL_ID

    @property
    def access_invite_link(self) -> str:
        return self.ACCESS_INVITE_LINK

    @property
    def alfa_account(self) -> str:
        return self.ALFA_ACCOUNT

    @property
    def alfa_bic(self) -> str:
        return self.ALFA_BIC

    @property
    def uralsib_account(self) -> str:
        return self.URALSIB_ACCOUNT

    @property
    def uralsib_bic(self) -> str:
        return self.URALSIB_BIC


settings = Settings()
