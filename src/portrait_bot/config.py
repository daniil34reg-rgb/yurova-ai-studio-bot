from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    base_url: str = "http://localhost:8000"
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"
    redis_url: str | None = None
    storage_dir: Path = Path("./storage")
    templates_file: Path = Path("./config/templates.yaml")
    packages_file: Path = Path("./config/packages.yaml")
    features_file: Path = Path("./config/features.yaml")

    telegram_bot_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "BOT_TOKEN"),
    )
    telegram_webhook_secret: str = "change-me"
    telegram_mode: str = "polling"
    telegram_retry_seconds: float = 5.0
    admin_ids: Annotated[frozenset[int], NoDecode] = Field(
        default_factory=frozenset
    )
    support_chat_id: int | None = None

    image_provider: str = "mock"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-image-2"
    openai_image_size: str = "1024x1024"
    openai_image_quality: str = "medium"
    video_provider: str = "auto"
    video_model: str = "wan-2.7"
    video_duration_seconds: int = 5
    video_size: str = "720x1280"
    video_poll_interval_seconds: float = 15.0
    video_timeout_seconds: float = 600.0
    video_generate_audio: bool = False

    payment_provider: str = "mock"
    cloudpayments_public_id: str | None = None
    cloudpayments_api_secret: str | None = None
    cloudpayments_api_url: str = "https://api.cloudpayments.ru"
    cloudpayments_offer_url: str | None = None
    cloudpayments_success_url: str | None = None
    cloudpayments_fail_url: str | None = None

    cloudkassir_enabled: bool = False
    cloudkassir_inn: str | None = None
    cloudkassir_taxation_system: int = 0
    cloudkassir_vat: int = 0
    cloudkassir_receipt_object: int = 4
    cloudkassir_receipt_method: int = 4

    privacy_url: str = "https://example.com/privacy"
    terms_url: str = "https://example.com/terms"
    consent_url: str = "https://example.com/consent"
    support_url: str | None = None

    welcome_credits: int = 0
    welcome_balance_rub: Decimal = Decimal("0")
    generation_credits: int = 1
    admin_free_generations: bool = True
    max_upload_mb: int = 20
    photo_retention_days: int = 7
    result_retention_days: int = 30
    delete_user_files_on_request: bool = True

    operator_name: str = "ИП Юрова Людмила Георгиевна"
    operator_inn: str = "343609055622"
    operator_ogrnip: str = "326344300036615"
    operator_address: str = ""
    support_email: str = "preisroza@mail.ru"
    service_bot_username: str = "Y_AIStickerBot"
    minimum_age: int = 18
    credit_validity_days: int = 183
    source_retention_hours: int = 24

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> frozenset[int]:
        if value in (None, "", frozenset()):
            return frozenset()
        if isinstance(value, str):
            return frozenset(int(item.strip()) for item in value.split(",") if item.strip())
        if isinstance(value, int):
            return frozenset({value})
        if isinstance(value, Iterable):
            return frozenset(int(item) for item in value)
        raise ValueError("ADMIN_IDS must be a comma-separated string")

    @field_validator("support_chat_id", mode="before")
    @classmethod
    def parse_optional_chat_id(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("openai_base_url", mode="before")
    @classmethod
    def parse_optional_base_url(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("image_provider")
    @classmethod
    def validate_image_provider(cls, value: str) -> str:
        if value not in {"mock", "openai"}:
            raise ValueError("IMAGE_PROVIDER must be mock or openai")
        return value

    @field_validator("video_provider")
    @classmethod
    def validate_video_provider(cls, value: str) -> str:
        if value not in {"auto", "mock", "aitunnel"}:
            raise ValueError("VIDEO_PROVIDER must be auto, mock or aitunnel")
        return value

    @field_validator("video_model", mode="before")
    @classmethod
    def normalize_legacy_video_model(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "wan2.5":
            return "wan-2.7"
        return value

    @field_validator("video_duration_seconds")
    @classmethod
    def validate_video_duration(cls, value: int) -> int:
        if not 1 <= value <= 15:
            raise ValueError("VIDEO_DURATION_SECONDS must be between 1 and 15")
        return value

    @field_validator("video_poll_interval_seconds", "video_timeout_seconds")
    @classmethod
    def validate_positive_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Video polling and timeout values must be positive")
        return value

    @field_validator("payment_provider")
    @classmethod
    def validate_payment_provider(cls, value: str) -> str:
        if value not in {"mock", "cloudpayments"}:
            raise ValueError("PAYMENT_PROVIDER must be mock or cloudpayments")
        return value

    @model_validator(mode="after")
    def validate_provider_secrets(self) -> Settings:
        if self.image_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when IMAGE_PROVIDER=openai")
        if self.video_provider == "aitunnel" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when VIDEO_PROVIDER=aitunnel")
        if self.payment_provider == "cloudpayments" and not (
            self.cloudpayments_public_id and self.cloudpayments_api_secret
        ):
            raise ValueError("CLOUDPAYMENTS_PUBLIC_ID and CLOUDPAYMENTS_API_SECRET are required")
        return self

    def prepare_directories(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        Path("./data").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_directories()
    return settings
