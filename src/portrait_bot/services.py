from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from portrait_bot.config import Settings
from portrait_bot.generation_metadata import split_local_caption
from portrait_bot.models import (
    BotSetting,
    Generation,
    GenerationStatus,
    LedgerEntry,
    Package,
    Payment,
    PaymentStatus,
    SupportTicket,
    Template,
    User,
    WalletEntry,
)
from portrait_bot.money import money
from portrait_bot.providers.images import ImageProvider, ImageProviderError
from portrait_bot.providers.payments import Checkout, PaymentProvider
from portrait_bot.providers.videos import VideoProvider, VideoProviderError
from portrait_bot.sticker_options import (
    SUPPORTED_STICKER_QUANTITIES,
    reaction_by_key,
    reaction_keys_for_quantity,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CreditLot:
    remaining: int
    expires_at: datetime | None


@dataclass(slots=True)
class MoneyLot:
    remaining: Decimal
    expires_at: datetime | None


async def get_or_create_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    language_code: str | None = None,
    welcome_credits: int = 0,
    welcome_balance_rub: Decimal = Decimal("0"),
) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user:
        user.username = username
        user.first_name = first_name
        user.language_code = language_code
        await session.commit()
        return user
    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        language_code=language_code,
    )
    session.add(user)
    await session.flush()
    if welcome_credits:
        session.add(
            LedgerEntry(
                user_id=user.id,
                amount=welcome_credits,
                entry_type="welcome_bonus",
                idempotency_key=f"welcome:{user.id}",
            )
        )
    if money(welcome_balance_rub) > 0:
        session.add(
            WalletEntry(
                user_id=user.id,
                amount_rub=money(welcome_balance_rub),
                entry_type="welcome_bonus",
                idempotency_key=f"wallet:welcome:{user.id}",
            )
        )
    await session.commit()
    return user


async def balance(session: AsyncSession, user_id: str) -> int:
    entries = list(
        (
            await session.scalars(
                select(LedgerEntry)
                .where(LedgerEntry.user_id == user_id)
                .order_by(LedgerEntry.created_at, LedgerEntry.id)
            )
        ).all()
    )
    now = datetime.now(UTC)
    lots: list[CreditLot] = []
    debt = 0

    def expire(at: datetime) -> None:
        lots[:] = [
            lot for lot in lots if lot.expires_at is None or _aware_datetime(lot.expires_at) > at
        ]

    for entry in entries:
        created_at = _aware_datetime(entry.created_at)
        expire(created_at)
        if entry.amount > 0:
            amount = entry.amount
            if debt:
                applied = min(amount, -debt)
                amount -= applied
                debt += applied
            if amount:
                lots.append(CreditLot(amount, entry.expires_at))
            continue
        required = -entry.amount
        lots.sort(
            key=lambda lot: (
                lot.expires_at is None,
                _aware_datetime(lot.expires_at)
                if lot.expires_at is not None
                else datetime.max.replace(tzinfo=UTC),
            )
        )
        for lot in lots:
            available = lot.remaining
            used = min(available, required)
            lot.remaining = available - used
            required -= used
            if required == 0:
                break
        lots[:] = [lot for lot in lots if lot.remaining > 0]
        if required:
            debt -= required
    expire(now)
    return sum(lot.remaining for lot in lots) + debt


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Expected datetime")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def add_ledger_entry(
    session: AsyncSession,
    *,
    user_id: str,
    amount: int,
    entry_type: str,
    idempotency_key: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
    comment: str | None = None,
    expires_at: datetime | None = None,
) -> bool:
    session.add(
        LedgerEntry(
            user_id=user_id,
            amount=amount,
            entry_type=entry_type,
            idempotency_key=idempotency_key,
            reference_type=reference_type,
            reference_id=reference_id,
            comment=comment,
            expires_at=expires_at,
        )
    )
    try:
        await session.commit()
        return True
    except IntegrityError:
        await session.rollback()
        return False


async def wallet_balance(session: AsyncSession, user_id: str) -> Decimal:
    entries = list(
        (
            await session.scalars(
                select(WalletEntry)
                .where(WalletEntry.user_id == user_id)
                .order_by(WalletEntry.created_at, WalletEntry.id)
            )
        ).all()
    )
    now = datetime.now(UTC)
    lots: list[MoneyLot] = []
    debt = Decimal("0")

    def expire(at: datetime) -> None:
        lots[:] = [
            lot for lot in lots if lot.expires_at is None or _aware_datetime(lot.expires_at) > at
        ]

    for entry in entries:
        created_at = _aware_datetime(entry.created_at)
        expire(created_at)
        amount = money(Decimal(entry.amount_rub))
        if amount > 0:
            if debt < 0:
                applied = min(amount, -debt)
                amount -= applied
                debt += applied
            if amount:
                lots.append(MoneyLot(amount, entry.expires_at))
            continue
        required = -amount
        lots.sort(
            key=lambda lot: (
                lot.expires_at is None,
                _aware_datetime(lot.expires_at)
                if lot.expires_at is not None
                else datetime.max.replace(tzinfo=UTC),
            )
        )
        for lot in lots:
            used = min(lot.remaining, required)
            lot.remaining -= used
            required -= used
            if required == 0:
                break
        lots[:] = [lot for lot in lots if lot.remaining > 0]
        if required:
            debt -= required
    expire(now)
    return money(sum((lot.remaining for lot in lots), Decimal("0")) + debt)


async def add_wallet_entry(
    session: AsyncSession,
    *,
    user_id: str,
    amount_rub: Decimal,
    entry_type: str,
    idempotency_key: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
    comment: str | None = None,
    expires_at: datetime | None = None,
) -> bool:
    amount = money(amount_rub)
    if amount == 0:
        raise ValueError("zero_wallet_entry")
    existing = await session.scalar(
        select(WalletEntry.id).where(WalletEntry.idempotency_key == idempotency_key)
    )
    if existing:
        return False
    session.add(
        WalletEntry(
            user_id=user_id,
            amount_rub=amount,
            entry_type=entry_type,
            idempotency_key=idempotency_key,
            reference_type=reference_type,
            reference_id=reference_id,
            comment=comment,
            expires_at=expires_at,
        )
    )
    try:
        await session.commit()
        return True
    except IntegrityError:
        await session.rollback()
        return False


async def get_setting(
    session: AsyncSession,
    key: str,
    default: str = "",
) -> str:
    setting = await session.get(BotSetting, key)
    return setting.value if setting else default


async def package_price(session: AsyncSession, package: Package) -> Decimal:
    base = money(await get_setting(session, "sticker_base_price_rub", "99"))
    if package.pricing_mode == "automatic":
        return money(base * package.credits)
    if package.pricing_mode == "discount":
        discount = min(Decimal("100"), max(Decimal("0"), Decimal(package.discount_percent)))
        return money(base * package.credits * (Decimal("1") - discount / Decimal("100")))
    return money(Decimal(package.amount_rub))


async def recalculate_package_prices(session: AsyncSession) -> None:
    packages = list((await session.scalars(select(Package))).all())
    for package in packages:
        if package.pricing_mode in {"automatic", "discount"}:
            package.amount_rub = await package_price(session, package)
    await session.commit()


async def create_payment(
    session: AsyncSession,
    provider: PaymentProvider,
    *,
    user: User,
    package: Package,
    provider_name: str,
) -> tuple[Payment, Checkout]:
    payment = Payment(
        user_id=user.id,
        package_id=package.id,
        provider=provider_name,
        status=PaymentStatus.CREATED.value,
        amount=package.amount_rub,
        credits=package.credits,
    )
    session.add(payment)
    await session.commit()
    checkout = await provider.create_checkout(
        payment_id=payment.id,
        telegram_id=user.telegram_id,
        title=package.title,
        amount=Decimal(payment.amount),
        credits=package.credits,
    )
    payment.provider_order_id = checkout.provider_order_id
    payment.payment_url = checkout.url
    payment.status = PaymentStatus.PENDING.value
    await session.commit()
    return payment, checkout


async def create_topup_payment(
    session: AsyncSession,
    provider: PaymentProvider | None,
    *,
    user: User,
    amount_rub: Decimal,
    provider_name: str,
    title: str = "Пополнение баланса",
) -> tuple[Payment, Checkout | None]:
    amount = money(amount_rub)
    if amount <= 0:
        raise ValueError("invalid_payment_amount")
    payment = Payment(
        user_id=user.id,
        package_id=None,
        provider=provider_name,
        purpose="wallet_topup",
        status=(
            PaymentStatus.PENDING.value
            if provider_name == "manual"
            else PaymentStatus.CREATED.value
        ),
        amount=amount,
        credits=0,
    )
    session.add(payment)
    await session.commit()
    if provider_name == "manual":
        return payment, None
    if provider is None:
        raise ValueError("payment_provider_missing")
    checkout = await provider.create_checkout(
        payment_id=payment.id,
        telegram_id=user.telegram_id,
        title=title,
        amount=amount,
        credits=0,
    )
    payment.provider_order_id = checkout.provider_order_id
    payment.payment_url = checkout.url
    payment.status = PaymentStatus.PENDING.value
    await session.commit()
    return payment, checkout


async def mark_payment_paid(
    session: AsyncSession,
    *,
    payment_id: str,
    transaction_id: str,
    amount: Decimal | None = None,
    account_id: str | None = None,
    credit_validity_days: int = 183,
) -> tuple[Payment, bool]:
    payment = await session.get(Payment, payment_id)
    if not payment:
        raise LookupError("payment_not_found")
    user = await session.get(User, payment.user_id)
    if not user:
        raise LookupError("user_not_found")
    if amount is not None and Decimal(payment.amount) != amount:
        raise ValueError("amount_mismatch")
    if account_id is not None and account_id != str(user.telegram_id):
        raise ValueError("account_mismatch")
    if payment.status != PaymentStatus.PAID.value:
        payment.status = PaymentStatus.PAID.value
        payment.provider_transaction_id = transaction_id
        payment.paid_at = datetime.now(UTC)
        await session.commit()
    credited = await add_wallet_entry(
        session,
        user_id=payment.user_id,
        amount_rub=Decimal(payment.amount),
        entry_type="wallet_topup",
        idempotency_key=f"payment:{payment.id}:wallet",
        reference_type="payment",
        reference_id=payment.id,
        expires_at=datetime.now(UTC) + timedelta(days=credit_validity_days),
    )
    return payment, credited


async def create_generation(
    session: AsyncSession,
    settings: Settings,
    *,
    user: User,
    source: bytes,
    prompt: str,
    mode: str,
    template: Template | None = None,
    quantity: int = 1,
    price_rub: Decimal | None = None,
) -> Generation:
    if quantity not in SUPPORTED_STICKER_QUANTITIES:
        raise ValueError("invalid_quantity")
    is_free_admin = settings.admin_free_generations and user.telegram_id in settings.admin_ids
    unit_credits = template.credits if template else settings.generation_credits
    credits = unit_credits * quantity
    charged_credits = 0
    charged_rub = Decimal("0")
    if price_rub is None:
        charged_credits = 0 if is_free_admin else credits
        if not is_free_admin and await balance(session, user.id) < credits:
            raise ValueError("insufficient_balance")
    else:
        configured_price = money(price_rub)
        if configured_price < 0:
            raise ValueError("invalid_generation_price")
        if not is_free_admin:
            available_accesses = await balance(session, user.id)
            if not mode.startswith("video:") and available_accesses >= credits:
                charged_credits = credits
            else:
                charged_rub = configured_price
                if charged_rub and await wallet_balance(session, user.id) < charged_rub:
                    raise ValueError("insufficient_balance")

    generation_id = str(uuid.uuid4())
    user_dir = settings.storage_dir / user.id
    user_dir.mkdir(parents=True, exist_ok=True)
    source_path = user_dir / f"{generation_id}-source.jpg"
    source_path.write_bytes(source)

    generation = Generation(
        id=generation_id,
        user_id=user.id,
        template_id=template.id if template else None,
        mode=mode,
        prompt=prompt,
        source_path=str(source_path),
        status=GenerationStatus.QUEUED.value,
        credits=charged_credits,
        price_rub=charged_rub,
    )
    session.add(generation)
    await session.commit()
    if charged_credits:
        debited = await add_ledger_entry(
            session,
            user_id=user.id,
            amount=-charged_credits,
            entry_type="generation_reserve",
            idempotency_key=f"generation:{generation.id}:reserve",
            reference_type="generation",
            reference_id=generation.id,
        )
        if not debited:
            raise RuntimeError("generation_reserve_failed")
    if charged_rub:
        debited = await add_wallet_entry(
            session,
            user_id=user.id,
            amount_rub=-charged_rub,
            entry_type="generation_reserve",
            idempotency_key=f"generation:{generation.id}:wallet:reserve",
            reference_type="generation",
            reference_id=generation.id,
        )
        if not debited:
            raise RuntimeError("generation_wallet_reserve_failed")
    return generation


def generation_quantity(generation: Generation) -> int:
    if not generation.mode.startswith("sticker:"):
        return 1
    try:
        quantity = int(generation.mode.split(":", 3)[1])
    except (IndexError, ValueError):
        return 1
    return quantity if quantity in SUPPORTED_STICKER_QUANTITIES else 1


def generation_video_duration(generation: Generation) -> int:
    if not generation.mode.startswith("video:"):
        return 0
    try:
        duration = int(generation.mode.split(":", 2)[1])
    except (IndexError, ValueError):
        return 5
    return duration if 1 <= duration <= 15 else 5


def generation_reactions(generation: Generation) -> tuple[str, ...]:
    quantity = generation_quantity(generation)
    parts = generation.mode.split(":")
    selected = parts[3] if len(parts) >= 4 and parts[3] != "standard" else "greeting"
    if quantity == 1 and selected == "meme":
        return ("meme",)
    return reaction_keys_for_quantity(quantity, selected)


def generation_uses_captions(generation: Generation) -> bool:
    parts = generation.mode.split(":")
    return len(parts) >= 3 and parts[2] == "text"


def result_paths(generation: Generation) -> list[Path]:
    if not generation.result_path:
        return []
    if generation.result_path.startswith("["):
        try:
            values = json.loads(generation.result_path)
        except json.JSONDecodeError:
            return []
        if isinstance(values, list):
            return [Path(str(value)) for value in values]
    return [Path(generation.result_path)]


def _variant_prompt(
    prompt: str,
    index: int,
    quantity: int,
    reaction_key: str,
) -> str:
    if reaction_key == "meme":
        return (
            f"{prompt}\nVariant {index + 1} of {quantity}: Create an exaggerated, "
            "immediately understandable reaction that matches the user's phrase. "
            "Do not render any words or letters."
        )
    reaction = reaction_by_key(reaction_key)
    return (
        f"{prompt}\nVariant {index + 1} of {quantity}: "
        f"{reaction.prompt}. "
        "Keep the same person and selected visual style while making this expression "
        "visibly distinct from the other variants. Do not render any words or letters."
    )


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("assets/fonts/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/seguisb.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    )
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _remove_chroma_key(image: Image.Image) -> None:
    corners = [
        cast(tuple[int, int, int, int], image.getpixel((0, 0))),
        cast(tuple[int, int, int, int], image.getpixel((image.width - 1, 0))),
        cast(tuple[int, int, int, int], image.getpixel((0, image.height - 1))),
        cast(
            tuple[int, int, int, int],
            image.getpixel((image.width - 1, image.height - 1)),
        ),
    ]
    reference = cast(
        tuple[int, int, int],
        tuple(sum(pixel[channel] for pixel in corners) // 4 for channel in range(3)),
    )
    corners_are_flat = all(
        max(abs(pixel[channel] - reference[channel]) for channel in range(3)) <= 45
        for pixel in corners
    )
    is_magenta_key = (
        reference[0] >= 160
        and reference[2] >= 160
        and reference[1] <= 135
        and min(reference[0], reference[2]) - reference[1] >= 70
    )
    if not corners_are_flat or not is_magenta_key:
        return

    pixels = cast(list[tuple[int, int, int, int]], list(image.getdata()))
    converted: list[tuple[int, int, int, int]] = []
    for red, green, blue, alpha in pixels:
        distance = (
            (red - reference[0]) ** 2 + (green - reference[1]) ** 2 + (blue - reference[2]) ** 2
        ) ** 0.5
        dominance = min(red, blue) - green
        if distance <= 65 or dominance >= 105:
            converted.append((red, green, blue, 0))
            continue
        if distance <= 145 and dominance >= 45:
            edge_alpha = int(alpha * min(1.0, max(0.0, (distance - 65) / 80)))
            neutral = max(green, min(red, blue))
            converted.append(
                (
                    min(red, neutral),
                    green,
                    min(blue, neutral),
                    edge_alpha,
                )
            )
            continue
        converted.append((red, green, blue, alpha))
    image.putdata(converted)


def _draw_caption(canvas: Image.Image, caption: str) -> None:
    draw = ImageDraw.Draw(canvas)
    font_size = 64 if len(caption) <= 8 else 54
    font = _font(font_size)
    box = draw.textbbox((0, 0), caption, font=font, stroke_width=5)
    text_width = box[2] - box[0]
    while text_width > 460 and font_size > 34:
        font_size -= 4
        font = _font(font_size)
        box = draw.textbbox((0, 0), caption, font=font, stroke_width=5)
        text_width = box[2] - box[0]
    x = (512 - text_width) // 2
    y = 512 - (box[3] - box[1]) - 26
    draw.text(
        (x, y),
        caption,
        font=font,
        fill="white",
        stroke_width=7,
        stroke_fill="#202020",
    )


def _prepare_sticker(result_path: Path, caption: str | None = None) -> Path:
    sticker_path = result_path.with_suffix(".webp")
    sticker_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(result_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
        _remove_chroma_key(image)
        content_size = (488, 402) if caption else (496, 496)
        contained = ImageOps.contain(image, content_size, method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (512, 512), (255, 255, 255, 0))
        offset = ((512 - contained.width) // 2, max(0, (content_size[1] - contained.height) // 2))
        canvas.alpha_composite(contained, offset)
        if caption:
            _draw_caption(canvas, caption)
        for quality in (92, 84, 76):
            canvas.save(sticker_path, "WEBP", quality=quality, method=6)
            if sticker_path.stat().st_size <= 512 * 1024:
                break
    return sticker_path


def _prepare_photo_caption(result_path: Path, caption: str) -> Path:
    with Image.open(result_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        draw = ImageDraw.Draw(image, "RGBA")
        max_width = int(image.width * 0.86)
        font_size = max(28, min(72, image.width // 15))
        font = _font(font_size)
        words = caption.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            width = draw.textbbox((0, 0), candidate, font=font, stroke_width=2)[2]
            if current and width > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        lines = lines[:4]
        spacing = max(8, font_size // 5)
        boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=2) for line in lines]
        text_height = sum(box[3] - box[1] for box in boxes) + spacing * max(0, len(lines) - 1)
        padding = max(20, font_size // 2)
        top = image.height - text_height - padding * 2 - max(24, image.height // 25)
        left = (image.width - max_width) // 2 - padding
        right = image.width - left
        bottom = image.height - max(16, image.height // 40)
        draw.rounded_rectangle(
            (left, top, right, bottom),
            radius=max(18, font_size // 2),
            fill=(10, 10, 14, 165),
        )
        y = top + padding
        for line, box in zip(lines, boxes, strict=True):
            width = box[2] - box[0]
            draw.text(
                ((image.width - width) // 2, y),
                line,
                font=font,
                fill="white",
                stroke_width=2,
                stroke_fill=(20, 20, 20),
            )
            y += box[3] - box[1] + spacing
        image.save(result_path, "PNG", optimize=True)
    return result_path


def _write_generated_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class GenerationWorker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        provider: ImageProvider,
        settings: Settings,
        video_provider: VideoProvider | None = None,
    ) -> None:
        self.sessions = sessions
        self.provider = provider
        self.settings = settings
        self.video_provider = video_provider

    async def process_one(self) -> Generation | None:
        async with self.sessions() as session:
            generation = await session.scalar(
                select(Generation)
                .where(Generation.status == GenerationStatus.QUEUED.value)
                .order_by(Generation.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if not generation:
                return None
            generation.status = GenerationStatus.PROCESSING.value
            generation.attempts += 1
            await session.commit()
            generation_id = generation.id
            source_path = generation.source_path
            prompt, local_caption = split_local_caption(generation.prompt)
            quantity = generation_quantity(generation)
            is_sticker = generation.mode.startswith("sticker:")
            is_video = generation.mode.startswith("video:")
            video_duration = generation_video_duration(generation)
            reaction_keys = generation_reactions(generation)
            use_captions = generation_uses_captions(generation)

        try:
            source_bytes = await asyncio.to_thread(Path(source_path).read_bytes)
            generated_paths: list[Path] = []
            compact_generation_id = generation_id.replace("-", "")
            if is_video:
                if self.video_provider is None:
                    raise VideoProviderError(
                        "video_provider_missing",
                        "Генератор видео не настроен",
                    )
                result = await self.video_provider.generate(
                    source_bytes,
                    prompt,
                    video_duration,
                )
                video_path = Path(source_path).with_name(
                    f"{compact_generation_id}-result.mp4"
                )
                await asyncio.to_thread(_write_generated_file, video_path, result)
                generated_paths.append(video_path)
            else:
                for index in range(quantity):
                    result = await self.provider.edit(
                        source_bytes,
                        _variant_prompt(prompt, index, quantity, reaction_keys[index])
                        if is_sticker
                        else prompt,
                    )
                    image_path = Path(source_path).with_name(
                        f"{compact_generation_id}-result-{index + 1}.png"
                    )
                    await asyncio.to_thread(_write_generated_file, image_path, result)
                    generated_paths.append(
                        await asyncio.to_thread(
                            _prepare_sticker,
                            image_path,
                            (
                                local_caption
                                or reaction_by_key(reaction_keys[index]).caption
                            )
                            if use_captions
                            else None,
                        )
                        if is_sticker
                        else (
                            await asyncio.to_thread(
                                _prepare_photo_caption,
                                image_path,
                                local_caption,
                            )
                            if local_caption
                            else image_path
                        )
                    )
                    if is_sticker:
                        await asyncio.to_thread(image_path.unlink, missing_ok=True)
            async with self.sessions() as session:
                generation = await session.get(Generation, generation_id)
                if not generation:
                    return None
                generation.result_path = json.dumps(
                    [str(path) for path in generated_paths],
                    ensure_ascii=False,
                )
                generation.status = GenerationStatus.COMPLETED.value
                generation.completed_at = datetime.now(UTC)
                await session.commit()
                return generation
        except (ImageProviderError, VideoProviderError) as exc:
            code, message = exc.code, str(exc)
            logger.warning(
                "Generation %s failed with provider error %s: %s",
                generation_id,
                code,
                message,
            )
        except Exception as exc:
            code, message = "internal_error", str(exc)
            logger.exception("Generation %s failed unexpectedly", generation_id)

        async with self.sessions() as session:
            generation = await session.get(Generation, generation_id)
            if not generation:
                return None
            generation.status = GenerationStatus.FAILED.value
            generation.error_code = code
            generation.error_message = message[:1000]
            await session.commit()
            if generation.credits:
                await add_ledger_entry(
                    session,
                    user_id=generation.user_id,
                    amount=generation.credits,
                    entry_type="generation_release",
                    idempotency_key=f"generation:{generation.id}:release",
                    reference_type="generation",
                    reference_id=generation.id,
                )
            if Decimal(generation.price_rub) > 0:
                await add_wallet_entry(
                    session,
                    user_id=generation.user_id,
                    amount_rub=Decimal(generation.price_rub),
                    entry_type="generation_release",
                    idempotency_key=f"generation:{generation.id}:wallet:release",
                    reference_type="generation",
                    reference_id=generation.id,
                )
            return generation


async def create_ticket(
    session: AsyncSession,
    *,
    user: User,
    category: str,
    message: str,
) -> SupportTicket:
    ticket = SupportTicket(user_id=user.id, category=category, message=message)
    session.add(ticket)
    await session.commit()
    return ticket


def generation_summary(generation: Generation) -> str:
    return json.dumps(
        {
            "id": generation.id,
            "status": generation.status,
            "mode": generation.mode,
            "credits": generation.credits,
            "price_rub": str(generation.price_rub),
        },
        ensure_ascii=False,
    )
