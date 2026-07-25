# Отдельный бот Yurova AI Studio

Это самостоятельная копия сервиса для `@Y_AIStickerBot`. Она не должна запускаться
с токеном, базой или каталогом данных первого бота.

## Что должно быть отдельным

- новый токен Telegram от BotFather;
- новый проект/бот в Bothost;
- отдельный репозиторий;
- новый ключ AI Tunnel;
- собственный Volume, подключённый к `/app/data`.

Именно отдельный проект и Volume дают независимые балансы, заказы, обращения,
настройки из админ-панели и пользовательские файлы.

## Обязательные пользовательские переменные Bothost

```dotenv
TELEGRAM_BOT_TOKEN=<ТОКЕН_НОВОГО_БОТА>
ADMIN_IDS=<TELEGRAM_ID_АДМИНИСТРАТОРА>

APP_ENV=production
LOG_LEVEL=INFO
TELEGRAM_MODE=polling
TELEGRAM_RETRY_SECONDS=5

DATABASE_URL=sqlite+aiosqlite:////app/data/bot.db
STORAGE_DIR=/app/data/storage
TEMPLATES_FILE=./config/templates.yaml
PACKAGES_FILE=./config/packages.yaml
FEATURES_FILE=./config/features.yaml

IMAGE_PROVIDER=openai
OPENAI_API_KEY=<ОТДЕЛЬНЫЙ_КЛЮЧ_AI_TUNNEL>
OPENAI_BASE_URL=https://api.aitunnel.ru/v1/
OPENAI_MODEL=gpt-image-2
OPENAI_IMAGE_SIZE=1024x1024
OPENAI_IMAGE_QUALITY=medium

VIDEO_PROVIDER=auto
VIDEO_MODEL=wan-2.7
VIDEO_DURATION_SECONDS=5
VIDEO_SIZE=720x1280
VIDEO_POLL_INTERVAL_SECONDS=15
VIDEO_TIMEOUT_SECONDS=600
VIDEO_GENERATE_AUDIO=false

PAYMENT_PROVIDER=mock
ADMIN_FREE_GENERATIONS=true
WELCOME_BALANCE_RUB=0
MAX_UPLOAD_MB=20
SOURCE_RETENTION_HOURS=24
RESULT_RETENTION_DAYS=30
PYTHONUNBUFFERED=1

OPERATOR_NAME=ИП Юрова Людмила Георгиевна
OPERATOR_INN=343609055622
OPERATOR_OGRNIP=326344300036615
OPERATOR_ADDRESS=
SUPPORT_EMAIL=preisroza@mail.ru
SERVICE_BOT_USERNAME=Y_AIStickerBot
```

Домашний адрес намеренно оставлен пустым и не показывается пользователям.

## Запуск

В Bothost выберите Python 3.11, подключите новый репозиторий и ветку `main`.
После сохранения переменных выполните полную пересборку. Успешная сборка
заканчивается сообщением `Build completed`, после чего в рабочих логах процесс
должен оставаться запущенным.
