# Yurova AI Studio

Коммерческий Telegram-бот для создания мультяшных стикеров из фотографии.

## Реализовано

- Постоянное кнопочное меню вместо длинного списка slash-команд.
- Подтверждение политики, оферты и согласия на обработку фото.
- Четыре коммерческие коллекции в компактной сетке 2×2:
  - король и королева;
  - Luxury;
  - герой кино;
  - цветочное настроение.
- Выбор варианта образа внутри коллекции.
- Выбор количества: 1, 3, 5 или 10 стикеров.
- Для одного стикера пользователь выбирает эмоцию; для набора бот автоматически
  собирает разные реакции: «Привет!», «Ха-ха!», «Супер!», «Обнимаю»,
  «Спасибо!» и дополнительные варианты.
- Надписи включаются или отключаются перед загрузкой фотографии и наносятся
  локально, поэтому нейросеть не искажает русские слова.
- Подготовка статических WEBP-файлов 512×512 и автоматическое создание
  Telegram-стикерпака.
- Общий рублёвый баланс для стикеров и оживления фотографий.
- Публичное создание короткого видео из фотографии с отдельной настраиваемой ценой.
- Ручное пополнение по инструкции, ссылке или QR-коду: пользователь отправляет чек,
  администратор подтверждает или отклоняет заявку кнопкой.
- Быстрые суммы пополнения автоматически включают актуальные цены наборов и видео;
  доступна настраиваемая произвольная сумма.
- Подготовленная интеграция CloudPayments/CloudKassir, включаемая отдельно от
  ручного пополнения.
- Срок действия средств на балансе 183 дня.
- Автоматический возврат списанной суммы при технической ошибке.
- Одно поле обращения в поддержку; адрес внутреннего чата пользователю не
  раскрывается. Ответ и закрытие обращения выполняются кнопками.
- Админ-панель `/admin` для функций, способов оплаты, заявок, рублёвых цен,
  тарифов, видео, текстов, стилей, картинок, скрытых промптов и обращений.
- После готового заказа автоматически показываются кнопки следующего действия.
- Администратор может выполнять тестовые генерации без внутреннего баланса.
- Автоматическое удаление исходной фотографии через 24 часа и локальных
  результатов через настраиваемый срок.
- SQLite для локальной проверки, PostgreSQL и Redis для production.
- Polling для разработки и webhook для сервера.

## Быстрый запуск на Windows

Требуется Python 3.11 или новее.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
notepad .env
```

Минимальные настройки:

```dotenv
TELEGRAM_BOT_TOKEN=токен_из_BotFather
ADMIN_IDS=ваш_цифровой_Telegram_ID
TELEGRAM_MODE=polling
IMAGE_PROVIDER=mock
PAYMENT_PROVIDER=mock
```

Инициализация и запуск:

```powershell
.\.venv\Scripts\python.exe main.py
```

`main.py` сам применяет миграции базы и запускает polling или webhook согласно
`TELEGRAM_MODE`. После изменения кода остановите процесс через `Ctrl+C` и
запустите команду снова.

## Тестовый и реальный режим

В mock-режиме внешние API и реальные деньги не используются:

```dotenv
IMAGE_PROVIDER=mock
PAYMENT_PROVIDER=mock
```

Для OpenAI:

```dotenv
IMAGE_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_BASE_URL=
OPENAI_MODEL=gpt-image-2
OPENAI_IMAGE_SIZE=1024x1024
OPENAI_IMAGE_QUALITY=medium
```

Для OpenAI-совместимого AI Tunnel укажите:

```dotenv
IMAGE_PROVIDER=openai
OPENAI_API_KEY=ваш_ключ_aitunnel
OPENAI_BASE_URL=https://api.aitunnel.ru/v1/
OPENAI_MODEL=gpt-image-2
```

Для прямого OpenAI оставьте `OPENAI_BASE_URL` пустым.

Ключ хранится только в `.env`; не отправляйте его в переписке. Подключение
проверяется без генерации изображения:

```powershell
.\.venv\Scripts\portrait-bot.exe check-openai
```

Подписка ChatGPT не включает API: ключ и биллинг API настраиваются отдельно в
[OpenAI Platform](https://platform.openai.com/). Используйте API только из
[поддерживаемой страны или территории](https://developers.openai.com/api/docs/supported-countries).
Бесплатный режим администратора отменяет только списание рублей с внутреннего
баланса; запросы к AI API всё равно оплачиваются владельцем API-аккаунта.

## CloudPayments и CloudKassir

Начальные цены и пакеты находятся в `config/packages.yaml`. Текущая стартовая
сетка: 1 — 99 ₽, 3 — 249 ₽, 5 — 399 ₽, 10 — 699 ₽; видео — 200 ₽. После
первого запуска цены, скидки и режим расчёта редактируются через `/admin` и
сохраняются в базе. Это тестовые значения: до production-запуска их нужно
утвердить отдельно.

Пока эквайринг не подключён, оставьте `PAYMENT_PROVIDER=mock`, а в
`/admin` → «Способы оплаты» включите ручное пополнение, добавьте инструкцию,
ссылку или QR-код. Заявка зачисляется на рублёвый баланс только после нажатия
администратором кнопки «Подтвердить». Повторное нажатие не начисляет деньги
дважды.

```dotenv
PAYMENT_PROVIDER=cloudpayments
CLOUDPAYMENTS_PUBLIC_ID=pk_...
CLOUDPAYMENTS_API_SECRET=...
BASE_URL=https://ваш-домен

CLOUDKASSIR_ENABLED=true
CLOUDKASSIR_INN=343609055622
CLOUDKASSIR_TAXATION_SYSTEM=0
CLOUDKASSIR_VAT=0
CLOUDKASSIR_RECEIPT_OBJECT=4
CLOUDKASSIR_RECEIPT_METHOD=4
```

HTTPS-уведомления CloudPayments:

```text
Check  https://ваш-домен/webhooks/cloudpayments/check
Pay    https://ваш-домен/webhooks/cloudpayments/pay
Fail   https://ваш-домен/webhooks/cloudpayments/fail
Refund https://ваш-домен/webhooks/cloudpayments/refund
```

Систему налогообложения, НДС, предмет и способ расчёта должен подтвердить
бухгалтер.

## Настройка продукта

- Стили и промпты: `config/templates.yaml`
- Функции по умолчанию: `config/features.yaml`
- Пакеты и цены: `config/packages.yaml`
- Примеры: `assets/previews/`
- Реквизиты оператора и сроки: `.env`

После первого запуска изменения из `/admin` сохраняются в базе и не
перезаписываются начальными YAML-файлами при следующем запуске.

## Production

```dotenv
TELEGRAM_MODE=webhook
BASE_URL=https://ваш-домен
TELEGRAM_WEBHOOK_SECRET=<случайная_строка>
DATABASE_URL=postgresql+asyncpg://portrait:password@postgres:5432/portrait
REDIS_URL=redis://redis:6379/0
```

```bash
docker compose up --build -d
```

Для TLS нужен reverse proxy. PostgreSQL и Redis нельзя публиковать напрямую в
интернет.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\portrait-bot.exe smoke
```

Юридические тексты встроены как рабочие проекты и должны быть проверены
профильным юристом перед приёмом реальных платежей.
