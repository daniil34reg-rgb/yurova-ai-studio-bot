import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import uvicorn
from alembic import command
from alembic.config import Config

from portrait_bot.config import get_settings
from portrait_bot.polling import main as polling_main


def migrate_database() -> None:
    project_dir = Path(__file__).resolve().parent
    config_path = project_dir / "alembic.ini"
    migrations_path = project_dir / "migrations"
    if not config_path.is_file() or not migrations_path.is_dir():
        return
    alembic_config = Config(str(config_path))
    alembic_config.set_main_option("script_location", str(migrations_path))
    command.upgrade(alembic_config, "head")


def main() -> None:
    migrate_database()
    settings = get_settings()
    if settings.telegram_mode == "webhook":
        uvicorn.run(
            "portrait_bot.api:app",
            host="0.0.0.0",
            port=int(os.environ.get("PORT", "8000")),
        )
        return
    polling_main()

if __name__ == "__main__":
    main()
