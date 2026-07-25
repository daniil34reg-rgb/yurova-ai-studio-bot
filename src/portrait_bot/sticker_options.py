from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StickerVariant:
    key: str
    title: str
    prompt: str


@dataclass(frozen=True)
class StickerReaction:
    key: str
    title: str
    emoji: str
    caption: str
    prompt: str


COLLECTION_VARIANTS: dict[str, tuple[StickerVariant, ...]] = {
    "royal": (
        StickerVariant(
            key="king",
            title="👑 Король",
            prompt=(
                "Present the person as a charismatic modern king wearing an elegant "
                "royal jacket and a refined crown. Masculine styling, tasteful gold "
                "details, no historical insignia."
            ),
        ),
        StickerVariant(
            key="queen",
            title="👑 Королева",
            prompt=(
                "Present the person as a charismatic modern queen wearing an elegant "
                "royal outfit and a refined tiara. Feminine styling, tasteful gold "
                "details, no historical insignia."
            ),
        ),
    ),
    "luxury": (
        StickerVariant(
            key="suit",
            title="🤵 Элегантный костюм",
            prompt=(
                "Dress the person in an elegant tailored formal suit with understated "
                "premium details."
            ),
        ),
        StickerVariant(
            key="evening",
            title="✨ Вечерний образ",
            prompt=(
                "Dress the person in a sophisticated evening look with tasteful premium "
                "styling and subtle jewelry or accessories."
            ),
        ),
        StickerVariant(
            key="modern",
            title="🧥 Современный стиль",
            prompt=(
                "Dress the person in polished modern smart-casual clothing with a clean "
                "fashion editorial feel."
            ),
        ),
    ),
    "cinema_hero": (
        StickerVariant(
            key="hero",
            title="🎬 Герой",
            prompt=(
                "Present the person as an original confident cinematic hero in a stylish "
                "modern outfit with dramatic but friendly energy."
            ),
        ),
        StickerVariant(
            key="heroine",
            title="🎬 Героиня",
            prompt=(
                "Present the person as an original confident cinematic heroine in a "
                "stylish modern outfit with dramatic but friendly energy."
            ),
        ),
    ),
    "floral": (
        StickerVariant(
            key="soft",
            title="🌸 Нежный",
            prompt=(
                "Surround the person with a tasteful small bouquet and delicate floral "
                "accents in a soft elegant palette."
            ),
        ),
        StickerVariant(
            key="bright",
            title="💐 Яркий",
            prompt=(
                "Surround the person with a vibrant celebratory bouquet and lively floral "
                "accents while keeping the face unobstructed."
            ),
        ),
        StickerVariant(
            key="classic",
            title="🌹 Элегантный",
            prompt=(
                "Add refined rose accents and an elegant timeless outfit while keeping the "
                "composition clean and suitable for a Telegram sticker."
            ),
        ),
    ),
}


REACTIONS: tuple[StickerReaction, ...] = (
    StickerReaction(
        key="greeting",
        title="Приветствие",
        emoji="👋",
        caption="Привет!",
        prompt="friendly smile, looking at the viewer and clearly waving hello with one hand",
    ),
    StickerReaction(
        key="laugh",
        title="Смех",
        emoji="😂",
        caption="Ха-ха!",
        prompt="joyful genuine laugh with a lively cheerful pose",
    ),
    StickerReaction(
        key="approval",
        title="Одобрение",
        emoji="👍",
        caption="Супер!",
        prompt="confident warm smile and a clearly visible thumbs-up gesture",
    ),
    StickerReaction(
        key="hug",
        title="Любовь и объятие",
        emoji="❤️",
        caption="Обнимаю",
        prompt="warm affectionate expression with a clear heart or hugging gesture",
    ),
    StickerReaction(
        key="thanks",
        title="Благодарность",
        emoji="🙏",
        caption="Спасибо!",
        prompt="grateful warm smile with hands held in a clear thankful gesture",
    ),
    StickerReaction(
        key="refusal",
        title="Отказ",
        emoji="🙅",
        caption="Нет",
        prompt="friendly but clear refusal gesture, expressive and not aggressive",
    ),
    StickerReaction(
        key="thinking",
        title="Размышление",
        emoji="🤔",
        caption="Думаю…",
        prompt="thoughtful curious expression with one hand near the chin",
    ),
    StickerReaction(
        key="yes",
        title="Согласие",
        emoji="✅",
        caption="Да!",
        prompt="confident happy agreement gesture with an approving nod",
    ),
    StickerReaction(
        key="celebration",
        title="Праздник",
        emoji="🎉",
        caption="Ура!",
        prompt="celebratory excitement with small tasteful confetti accents",
    ),
    StickerReaction(
        key="farewell",
        title="Прощание",
        emoji="👋",
        caption="Пока!",
        prompt="warm farewell smile with a clearly visible waving hand",
    ),
)

REACTIONS_BY_KEY = {reaction.key: reaction for reaction in REACTIONS}
DEFAULT_REACTION_KEYS = tuple(reaction.key for reaction in REACTIONS)
SUPPORTED_STICKER_QUANTITIES = (1, 3, 5, 10)


def collection_variants(slug: str) -> tuple[StickerVariant, ...]:
    return COLLECTION_VARIANTS.get(slug, ())


def variant_by_key(slug: str, key: str) -> StickerVariant | None:
    return next(
        (variant for variant in collection_variants(slug) if variant.key == key),
        None,
    )


def reaction_by_key(key: str) -> StickerReaction:
    return REACTIONS_BY_KEY.get(key, REACTIONS[0])


def reaction_keys_for_quantity(quantity: int, selected: str = "greeting") -> tuple[str, ...]:
    if quantity == 1:
        return (reaction_by_key(selected).key,)
    return DEFAULT_REACTION_KEYS[:quantity]
