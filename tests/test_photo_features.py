from __future__ import annotations

from io import BytesIO

from PIL import Image

from portrait_bot.catalog import seed_catalog
from portrait_bot.generation_metadata import attach_local_caption, split_local_caption
from portrait_bot.keyboards import photo_options_menu, photo_scenarios_menu
from portrait_bot.models import BotSetting, FeatureFlag
from portrait_bot.photo_scenarios import (
    PHOTO_SCENARIOS,
    enabled_setting_key,
    scenario_by_key,
    scenarios_for_section,
)
from portrait_bot.providers.images import MockImageProvider
from portrait_bot.services import (
    GenerationWorker,
    create_generation,
    generation_reactions,
    get_or_create_user,
    result_paths,
)


def jpeg() -> bytes:
    image = Image.new("RGB", (800, 1000), "#d8c8b8")
    output = BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


def test_photo_scenario_catalog_is_complete_and_unique() -> None:
    keys = [scenario.key for scenario in PHOTO_SCENARIOS]
    assert len(keys) == len(set(keys))
    assert {item.key for item in scenarios_for_section("processing")} == {
        "enhance",
        "business",
        "beauty",
    }
    assert {item.key for item in scenarios_for_section("looks")} == {
        "movie",
        "travel",
        "royal",
        "greeting",
    }
    assert scenario_by_key("greeting") is not None
    assert scenario_by_key("missing") is None


def test_local_caption_roundtrip_preserves_russian_text() -> None:
    prompt = attach_local_caption("Base prompt", "Алина, с днём рождения! 🎉")
    clean_prompt, caption = split_local_caption(prompt)
    assert clean_prompt == "Base prompt"
    assert caption == "Алина, с днём рождения! 🎉"
    assert "Алина" not in clean_prompt


def test_photo_keyboards_keep_callbacks_short() -> None:
    scenarios = scenarios_for_section("looks")
    menu = photo_scenarios_menu(scenarios, {})
    movie = scenario_by_key("movie")
    assert movie is not None
    options = photo_options_menu(movie)
    callbacks = [
        button.callback_data
        for keyboard in (menu, options)
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert callbacks
    assert all(len(value.encode("utf-8")) <= 64 for value in callbacks)


async def test_new_photo_settings_are_seeded_without_overwriting(database, settings) -> None:
    async with database.sessions() as session:
        processing = await session.get(FeatureFlag, "photo_processing")
        looks = await session.get(FeatureFlag, "photo_looks")
        base_price = await session.get(BotSetting, "photo_base_price_rub")
        enhance_enabled = await session.get(BotSetting, enabled_setting_key("enhance"))
        assert processing is not None and processing.enabled is True
        assert looks is not None and looks.enabled is True
        assert base_price is not None and base_price.value == "99"
        assert enhance_enabled is not None and enhance_enabled.value == "true"
        base_price.value = "321"
        await session.commit()
        await seed_catalog(
            session,
            settings.templates_file,
            settings.packages_file,
            settings.features_file,
        )
        preserved = await session.get(BotSetting, "photo_base_price_rub")
        assert preserved is not None and preserved.value == "321"


async def test_worker_adds_exact_local_caption_to_photo(database, settings) -> None:
    admin_settings = settings.model_copy(
        update={"admin_ids": frozenset({501}), "admin_free_generations": True}
    )
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=501)
        await create_generation(
            session,
            admin_settings,
            user=user,
            source=jpeg(),
            prompt=attach_local_caption("Create a greeting card.", "С праздником!"),
            mode="photo:greeting",
            quantity=1,
            price_rub=99,
        )

    result = await GenerationWorker(
        database.sessions,
        MockImageProvider(),
        admin_settings,
    ).process_one()
    assert result is not None and result.status == "completed"
    paths = result_paths(result)
    assert len(paths) == 1 and paths[0].suffix == ".png"
    with Image.open(paths[0]) as image:
        assert image.size == (1024, 1024)


async def test_worker_creates_meme_as_telegram_sticker(database, settings) -> None:
    admin_settings = settings.model_copy(
        update={"admin_ids": frozenset({502}), "admin_free_generations": True}
    )
    async with database.sessions() as session:
        user = await get_or_create_user(session, telegram_id=502)
        generation = await create_generation(
            session,
            admin_settings,
            user=user,
            source=jpeg(),
            prompt=attach_local_caption("Create a funny reaction.", "Я всё видел"),
            mode="sticker:1:text:meme",
            quantity=1,
            price_rub=99,
        )
    assert generation_reactions(generation) == ("meme",)

    result = await GenerationWorker(
        database.sessions,
        MockImageProvider(),
        admin_settings,
    ).process_one()
    assert result is not None and result.status == "completed"
    paths = result_paths(result)
    assert len(paths) == 1 and paths[0].suffix == ".webp"
    assert paths[0].stat().st_size <= 512 * 1024
