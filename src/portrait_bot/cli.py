from __future__ import annotations

import argparse
import asyncio
import uuid
from io import BytesIO

import uvicorn
from openai import AsyncOpenAI
from PIL import Image, ImageDraw
from sqlalchemy import select

from portrait_bot.app_factory import create_context
from portrait_bot.catalog import seed_catalog
from portrait_bot.config import get_settings
from portrait_bot.models import Template
from portrait_bot.services import (
    add_ledger_entry,
    create_generation,
    generation_summary,
    get_or_create_user,
)


async def init_db() -> None:
    settings = get_settings()
    context = create_context(settings)
    await context.db.create_all()
    async with context.db.sessions() as session:
        await seed_catalog(
            session,
            settings.templates_file,
            settings.packages_file,
            settings.features_file,
        )
    await context.db.dispose()
    print("Database initialized")


def _sample_image() -> bytes:
    image = Image.new("RGB", (800, 1000), "#D7C9B8")
    draw = ImageDraw.Draw(image)
    draw.ellipse((240, 180, 560, 500), fill="#A97C61")
    draw.rectangle((180, 500, 620, 950), fill="#334155")
    output = BytesIO()
    image.save(output, "JPEG", quality=90)
    return output.getvalue()


async def smoke() -> None:
    settings = get_settings()
    if settings.image_provider != "mock":
        raise RuntimeError("Smoke test is intentionally limited to IMAGE_PROVIDER=mock")
    context = create_context(settings)
    await context.db.create_all()
    run_id = uuid.uuid4().hex
    async with context.db.sessions() as session:
        await seed_catalog(
            session,
            settings.templates_file,
            settings.packages_file,
            settings.features_file,
        )
        telegram_id = 900_000_000 + (int(run_id[:7], 16) % 99_000_000)
        user = await get_or_create_user(session, telegram_id=telegram_id, first_name="Smoke")
        await add_ledger_entry(
            session,
            user_id=user.id,
            amount=3,
            entry_type="smoke_credit",
            idempotency_key=f"smoke:{run_id}:credit",
        )
        template = await session.scalar(select(Template).where(Template.slug == "royal"))
        if not template:
            raise RuntimeError("Seed template not found")
        generation = await create_generation(
            session,
            settings,
            user=user,
            source=_sample_image(),
            prompt=template.prompt,
            mode="sticker:3:text:standard",
            template=template,
            quantity=3,
        )
    result = await context.worker.process_one()
    if not result or result.id != generation.id or result.status != "completed":
        raise RuntimeError("Smoke generation failed")
    print(generation_summary(result))
    await context.db.dispose()


async def check_openai() -> bool:
    settings = get_settings()
    if not settings.openai_api_key:
        print("OPENAI_API_KEY is not configured in .env")
        return False
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    try:
        models = await client.models.list()
    except Exception as exc:
        print(f"Image API connection failed: {type(exc).__name__}: {exc}")
        return False
    finally:
        await client.close()
    available_models = {model.id for model in models.data}
    if settings.openai_model not in available_models:
        print(
            "Image API connection is ready, but the configured model is unavailable: "
            f"{settings.openai_model}"
        )
        return False
    print(f"Image API connection is ready. Model: {settings.openai_model}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Portrait commerce bot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("smoke")
    subparsers.add_parser("check-openai")
    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "init-db":
        asyncio.run(init_db())
    elif args.command == "smoke":
        asyncio.run(smoke())
    elif args.command == "check-openai":
        if not asyncio.run(check_openai()):
            raise SystemExit(1)
    elif args.command == "serve":
        uvicorn.run("portrait_bot.api:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
