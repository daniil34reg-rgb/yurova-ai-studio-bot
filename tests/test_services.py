from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO

from PIL import Image
from sqlalchemy import select

from portrait_bot.catalog import seed_catalog
from portrait_bot.keyboards import packages_menu, styles_menu
from portrait_bot.models import BotSetting, FeatureFlag, Package, PaymentStatus, Template
from portrait_bot.providers.images import ImageProvider, ImageProviderError, MockImageProvider
from portrait_bot.providers.payments import MockPaymentProvider
from portrait_bot.providers.videos import MockVideoProvider
from portrait_bot.services import (
    GenerationWorker,
    add_ledger_entry,
    add_wallet_entry,
    balance,
    create_generation,
    create_payment,
    create_topup_payment,
    generation_quantity,
    generation_reactions,
    generation_uses_captions,
    generation_video_duration,
    get_or_create_user,
    mark_payment_paid,
    package_price,
    result_paths,
    wallet_balance,
)
from portrait_bot.style_grid import build_style_grid


def jpeg() -> bytes:
    image = Image.new("RGB", (512, 700), "#bda68c")
    output = BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


async def test_ledger_is_idempotent(database) -> None:
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=100)
        user_id = user.id
        first = await add_ledger_entry(
            session,
            user_id=user_id,
            amount=5,
            entry_type="test",
            idempotency_key="same-key",
        )
        second = await add_ledger_entry(
            session,
            user_id=user_id,
            amount=5,
            entry_type="test",
            idempotency_key="same-key",
        )
        assert first is True
        assert second is False
        assert await balance(session, user_id) == 5


async def test_payment_adds_rubles_only_once(database, settings) -> None:
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=200)
        package = await session.scalar(select(Package).where(Package.code == "starter"))
        assert package is not None
        payment, _ = await create_payment(
            session,
            MockPaymentProvider(settings),
            user=user,
            package=package,
            provider_name="mock",
        )
        _, credited_first = await mark_payment_paid(
            session,
            payment_id=payment.id,
            transaction_id="tx-1",
            amount=Decimal("249.00"),
            account_id="200",
        )
        _, credited_second = await mark_payment_paid(
            session,
            payment_id=payment.id,
            transaction_id="tx-1",
            amount=Decimal("249.00"),
            account_id="200",
        )
        assert credited_first is True
        assert credited_second is False
        assert await wallet_balance(session, user.id) == Decimal("249.00")
        assert await balance(session, user.id) == 0


async def test_manual_topup_can_exist_without_package(database) -> None:
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=201)
        payment, checkout = await create_topup_payment(
            session,
            None,
            user=user,
            amount_rub=Decimal("500"),
            provider_name="manual",
        )

        assert checkout is None
        assert payment.package_id is None
        assert payment.amount == Decimal("500.00")
        assert payment.status == PaymentStatus.PENDING.value


async def test_package_price_modes(database) -> None:
    async with database.sessions() as session:
        package = await session.scalar(select(Package).where(Package.code == "starter"))
        assert package is not None
        package.pricing_mode = "automatic"
        assert await package_price(session, package) == Decimal("297.00")
        package.pricing_mode = "discount"
        package.discount_percent = Decimal("10")
        assert await package_price(session, package) == Decimal("267.30")


class FailingImageProvider(ImageProvider):
    async def edit(self, source: bytes, prompt: str) -> bytes:
        del source, prompt
        raise ImageProviderError("test_failure", "Test provider failed")


async def test_failed_ruble_generation_refunds_wallet(database, settings) -> None:
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=202)
        await add_wallet_entry(
            session,
            user_id=user.id,
            amount_rub=Decimal("150"),
            entry_type="test",
            idempotency_key="wallet-generation-credit",
        )
        template = await session.scalar(
            select(Template).where(Template.slug == "sticker_handdrawn")
        )
        assert template is not None
        await create_generation(
            session,
            settings,
            user=user,
            source=jpeg(),
            prompt=template.prompt,
            mode="sticker:1:plain:greeting",
            template=template,
            quantity=1,
            price_rub=Decimal("99"),
        )
        assert await wallet_balance(session, user.id) == Decimal("51.00")

    result = await GenerationWorker(
        database.sessions,
        FailingImageProvider(),
        settings,
    ).process_one()
    assert result is not None
    assert result.status == "failed"
    async with database.sessions() as session:
        assert await wallet_balance(session, user.id) == Decimal("150.00")


async def test_mock_generation_completes(database, settings) -> None:
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=300)
        await add_ledger_entry(
            session,
            user_id=user.id,
            amount=1,
            entry_type="test",
            idempotency_key="generation-credit",
        )
        template = await session.scalar(
            select(Template).where(Template.slug == "business_portrait")
        )
        assert template is not None
        generation = await create_generation(
            session,
            settings,
            user=user,
            source=jpeg(),
            prompt=template.prompt,
            mode="template",
            template=template,
        )
    worker = GenerationWorker(database.sessions, MockImageProvider(), settings)
    result = await worker.process_one()
    assert result is not None
    assert result.id == generation.id
    assert result.status == "completed"
    assert result.result_path is not None


async def test_sticker_batch_creates_requested_webp_files(database, settings) -> None:
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=301)
        await add_ledger_entry(
            session,
            user_id=user.id,
            amount=3,
            entry_type="test",
            idempotency_key="sticker-batch-credit",
        )
        template = await session.scalar(
            select(Template).where(Template.slug == "sticker_handdrawn")
        )
        assert template is not None
        generation = await create_generation(
            session,
            settings,
            user=user,
            source=jpeg(),
            prompt=template.prompt,
            mode="sticker:3",
            template=template,
            quantity=3,
        )

    worker = GenerationWorker(database.sessions, MockImageProvider(), settings)
    result = await worker.process_one()

    assert result is not None
    assert result.id == generation.id
    paths = result_paths(result)
    assert len(paths) == 3
    assert all(path.suffix == ".webp" for path in paths)
    assert all(path.exists() for path in paths)
    assert all(path.stat().st_size <= 512 * 1024 for path in paths)


async def test_new_sticker_mode_uses_reactions_and_local_captions(
    database,
    settings,
) -> None:
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=304)
        await add_ledger_entry(
            session,
            user_id=user.id,
            amount=3,
            entry_type="test",
            idempotency_key="caption-batch-credit",
        )
        template = await session.scalar(select(Template).where(Template.slug == "royal"))
        assert template is not None
        generation = await create_generation(
            session,
            settings,
            user=user,
            source=jpeg(),
            prompt=template.prompt,
            mode="sticker:3:text:standard",
            template=template,
            quantity=3,
        )

    assert generation_quantity(generation) == 3
    assert generation_reactions(generation) == ("greeting", "laugh", "approval")
    assert generation_uses_captions(generation) is True

    result = await GenerationWorker(
        database.sessions,
        MockImageProvider(),
        settings,
    ).process_one()
    assert result is not None
    paths = result_paths(result)
    assert len(paths) == 3
    with Image.open(paths[0]) as sticker:
        assert sticker.size == (512, 512)
        assert sticker.mode == "RGBA"
        assert sticker.getbbox() is not None


async def test_admin_generation_is_free(database, settings) -> None:
    admin_settings = settings.model_copy(
        update={"admin_ids": frozenset({303}), "admin_free_generations": True}
    )
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=303)
        template = await session.scalar(
            select(Template).where(Template.slug == "sticker_handdrawn")
        )
        assert template is not None
        generation = await create_generation(
            session,
            admin_settings,
            user=user,
            source=jpeg(),
            prompt=template.prompt,
            mode="sticker:1",
            template=template,
            quantity=1,
        )

        assert generation.credits == 0
        assert await balance(session, user.id) == 0


async def test_admin_video_generation_creates_mp4(database, settings) -> None:
    admin_settings = settings.model_copy(
        update={"admin_ids": frozenset({305}), "admin_free_generations": True}
    )
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=305)
        generation = await create_generation(
            session,
            admin_settings,
            user=user,
            source=jpeg(),
            prompt="Animate the photo naturally.",
            mode="video:5",
            quantity=1,
        )

    assert generation_video_duration(generation) == 5
    result = await GenerationWorker(
        database.sessions,
        MockImageProvider(),
        admin_settings,
        MockVideoProvider(),
    ).process_one()

    assert result is not None
    assert result.status == "completed"
    paths = result_paths(result)
    assert len(paths) == 1
    assert paths[0].suffix == ".mp4"
    assert paths[0].read_bytes() == b"mock-mp4"


async def test_feature_flags_are_seeded(database) -> None:
    async with database.sessions() as session:
        sticker_creator = await session.get(FeatureFlag, "sticker_creator")
        data_deletion = await session.get(FeatureFlag, "data_deletion")

    assert sticker_creator is not None and sticker_creator.enabled is True
    assert data_deletion is not None and data_deletion.enabled is False


async def test_editable_catalog_values_survive_reseeding(
    database,
    settings,
) -> None:
    async with database.sessions() as session:
        template = await session.scalar(select(Template).where(Template.slug == "sticker_3d"))
        package = await session.scalar(select(Package).where(Package.code == "starter"))
        assert template is not None
        assert package is not None
        template.title = "Мой 3D"
        package.amount_rub = Decimal("777.00")
        await session.commit()
        await seed_catalog(
            session,
            settings.templates_file,
            settings.packages_file,
            settings.features_file,
        )
        await session.refresh(template)
        await session.refresh(package)
        assert template.title == "Мой 3D"
        assert package.amount_rub == Decimal("777.00")


async def test_admin_text_settings_are_seeded(database) -> None:
    async with database.sessions() as session:
        welcome = await session.get(BotSetting, "welcome_message")
        reference_price = await session.get(BotSetting, "credit_display_price_rub")

    assert welcome is not None and "Yurova AI Studio" in welcome.value
    assert reference_price is not None and reference_price.value == "0"


async def test_style_grid_and_compact_keyboard(database) -> None:
    async with database.sessions() as session:
        templates = list(
            (
                await session.scalars(
                    select(Template).where(Template.active.is_(True)).order_by(Template.sort_order)
                )
            ).all()
        )

    image_bytes = build_style_grid(templates)
    with Image.open(BytesIO(image_bytes)) as image:
        assert image.size == (900, 900)
        assert image.format == "JPEG"

    keyboard = styles_menu(templates)
    assert len(keyboard.inline_keyboard) == 3
    assert len(keyboard.inline_keyboard[0]) == 2
    assert keyboard.inline_keyboard[0][0].callback_data == "style:royal"


async def test_packages_have_main_menu_button(database) -> None:
    async with database.sessions() as session:
        packages = list(
            (await session.scalars(select(Package).where(Package.active.is_(True)))).all()
        )

    keyboard = packages_menu(packages)
    assert keyboard.inline_keyboard[-1][0].callback_data == "menu:main"


async def test_expired_credits_are_excluded_from_balance(database) -> None:
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=302)
        await add_ledger_entry(
            session,
            user_id=user.id,
            amount=5,
            entry_type="purchase",
            idempotency_key="expired-purchase",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await add_ledger_entry(
            session,
            user_id=user.id,
            amount=2,
            entry_type="purchase",
            idempotency_key="active-purchase",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )

        assert await balance(session, user.id) == 2
