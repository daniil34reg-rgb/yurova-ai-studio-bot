# Запуск Yurova AI Studio на Bothost Basic

Архив подготовлен для Python 3.11 и Telegram long polling. Секретных ключей внутри нет.

## Перед загрузкой

1. В BotFather отзовите старый токен, который попадал на скриншот, и создайте новый.
2. Создайте новый ключ AI Tunnel. Старый ключ, использовавшийся на заражённом компьютере,
   безопаснее считать скомпрометированным.
3. Не создавайте и не загружайте файл `.env`: ключи вводятся только в панели Bothost.
4. Остановите локальную копию бота сочетанием `Ctrl+C`. Один Telegram-бот не должен
   одновременно работать в polling на компьютере и на сервере.

## Загрузка через интерфейс

1. Распакуйте ZIP.
2. В Bothost создайте или откройте Telegram-бота и загрузите содержимое распакованной
   папки так, чтобы `main.py`, `requirements.txt`, `pyproject.toml` и `Dockerfile`
   находились в корне проекта.
3. Выберите Python 3.11.
4. Если есть переключатель `Использовать собственный Dockerfile`, включите его:
   Dockerfile уже задаёт Python 3.11, устанавливает кириллический шрифт и запускает бота.
5. Если Bothost просит главный файл, укажите `main.py`.
6. Если Bothost просит команду запуска, укажите `python main.py`.
7. Выполните новый деплой, а не только рестарт.

Bothost автоматически выполняет `pip install -r requirements.txt`. В этом проекте
`requirements.txt` устанавливает сам пакет и все зависимости из `pyproject.toml`.

## Загрузка через Git

1. Создайте пустой репозиторий GitHub/GitLab.
2. Загрузите туда содержимое архива без `.env`.
3. В Bothost укажите URL репозитория и ветку `main`.
4. Повторите настройки Python, Dockerfile, главного файла и переменных среды из этой
   инструкции.

## Переменные среды

Добавьте в разделе `Переменные окружения`:

```dotenv
TELEGRAM_BOT_TOKEN=<НОВЫЙ_ТОКЕН_ИЗ_BOTFATHER>
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
OPENAI_API_KEY=<НОВЫЙ_КЛЮЧ_AI_TUNNEL>
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

Не добавляйте угловые скобки: вместо них вставьте реальные новые значения.

Необязательная переменная для пересылки обращений в отдельный служебный чат:

```dotenv
SUPPORT_CHAT_ID=<ЧИСЛОВОЙ_ID_ЧАТА>
```

## Постоянное хранилище

На тарифе Basic у Bothost заявлено постоянное хранилище Volume. Подключите Volume к
пути `/app/data`. Название кнопки или поля в панели может отличаться; важно, чтобы
точкой монтирования был именно `/app/data`. Без Volume SQLite-база и созданные
стикеры могут исчезнуть при пересборке.

## Первая проверка

После деплоя откройте runtime-логи. Нормальный результат: процесс продолжает работать
и не завершается с ошибкой. Затем:

1. Откройте бота в Telegram.
2. Отправьте `/start`.
3. Выполните одну тестовую генерацию из админского аккаунта.

Если в логах появляется `Conflict: terminated by other getUpdates`, локальная копия
бота всё ещё запущена. Остановите её и перезапустите бот в Bothost.

Если появляется `401`, неверен или не активирован новый токен/ключ. Не публикуйте
значение ключа в чате или скриншотах.

## Оплата

Для первого серверного теста оставлен `PAYMENT_PROVIDER=mock`. В самом боте
откройте `/admin` → «Способы оплаты»: там настраиваются ручная инструкция,
ссылка, QR-код и проверка присланных чеков. Средства начисляются в рублях.

Реальные платежи CloudPayments/CloudKassir не включайте до настройки публичного
HTTPS webhook, боевых ключей, чеков и юридических ссылок. Для webhook-режима
потребуются `TELEGRAM_MODE=webhook`, корректный `BASE_URL` и
`TELEGRAM_WEBHOOK_SECRET`; `main.py` автоматически выберет нужный серверный
режим.
