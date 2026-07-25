from __future__ import annotations

from pathlib import Path

import pytest

from portrait_bot.catalog import seed_catalog
from portrait_bot.config import Settings
from portrait_bot.db import Database


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        base_url="http://testserver",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        storage_dir=tmp_path / "storage",
        templates_file=Path("config/templates.yaml"),
        packages_file=Path("config/packages.yaml"),
        features_file=Path("config/features.yaml"),
        image_provider="mock",
        payment_provider="mock",
    )


@pytest.fixture
async def database(settings: Settings):
    db = Database(settings)
    await db.create_all()
    async with db.sessions() as session:
        await seed_catalog(
            session,
            settings.templates_file,
            settings.packages_file,
            settings.features_file,
        )
    yield db
    await db.dispose()
