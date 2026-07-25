from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioOption:
    key: str
    title: str
    prompt: str


@dataclass(frozen=True)
class PhotoScenario:
    key: str
    title: str
    description: str
    prompt: str
    section: str
    options: tuple[ScenarioOption, ...] = ()
    asks_for_text: bool = False


IDENTITY_RULES = (
    "Use the uploaded photo as the identity reference. Preserve the person's clearly "
    "recognizable facial identity, age, skin tone, body proportions and the number of "
    "people. Preserve the original crop: if the source is a close portrait, keep a close "
    "portrait; if it is half-body or full-body, keep that framing. Use realistic anatomy, "
    "natural hands and high photographic detail. Do not add logos, watermarks, letters "
    "or words."
)


PHOTO_SCENARIOS: tuple[PhotoScenario, ...] = (
    PhotoScenario(
        key="enhance",
        title="✨ Улучшить качество",
        description=(
            "Улучшает свет, цвет, резкость и детализацию, не меняя человека, одежду и фон."
        ),
        section="processing",
        prompt=(
            f"{IDENTITY_RULES} Restore and professionally enhance the existing photograph "
            "without redesigning it. Keep the same background, clothing, pose and facial "
            "features. Correct exposure and white balance, reduce noise and blur, recover "
            "natural detail and produce a clean premium photograph. Avoid plastic skin or "
            "heavy beauty retouching."
        ),
    ),
    PhotoScenario(
        key="business",
        title="💼 Деловой портрет",
        description=(
            "Профессиональный деловой образ: аккуратная одежда, хороший свет и нейтральный фон."
        ),
        section="processing",
        prompt=(
            f"{IDENTITY_RULES} Create a premium professional business portrait. Choose an "
            "elegant business outfit appropriate for the person, a refined neutral office "
            "or studio background and flattering soft professional lighting. Keep the result "
            "credible, modern and suitable for a profile or company website."
        ),
    ),
    PhotoScenario(
        key="beauty",
        title="📸 Красивый портрет",
        description=(
            "Естественный журнальный портрет с мягким светом и аккуратной ретушью."
        ),
        section="processing",
        prompt=(
            f"{IDENTITY_RULES} Create a flattering premium editorial portrait with soft "
            "studio-quality light, natural skin texture, elegant color grading and a clean "
            "tasteful background. Keep the person's real appearance and avoid excessive "
            "retouching or changing facial features."
        ),
    ),
    PhotoScenario(
        key="movie",
        title="🎬 Герой кино",
        description="Кинематографичный образ с выбранным жанром и драматичным светом.",
        section="looks",
        prompt=(
            f"{IDENTITY_RULES} Transform the person into an original cinematic protagonist. "
            "The image must look like a premium movie still, without copying a protected "
            "character or displaying a movie title."
        ),
        options=(
            ScenarioOption(
                "action",
                "🔥 Экшен",
                "Stylish modern action-film atmosphere, confident pose, city lights, dramatic "
                "teal-and-orange lighting, no weapons and no violence.",
            ),
            ScenarioOption(
                "noir",
                "🕵️ Детектив",
                "Elegant modern noir detective atmosphere, rain reflections, tailored coat, "
                "mysterious cinematic lighting.",
            ),
            ScenarioOption(
                "scifi",
                "🚀 Фантастика",
                "Original near-future science-fiction atmosphere, refined futuristic clothing, "
                "cinematic city light, no franchise references.",
            ),
            ScenarioOption(
                "romance",
                "🌆 Романтика",
                "Warm sophisticated romantic-film atmosphere at golden hour, elegant clothing "
                "and cinematic depth of field.",
            ),
        ),
    ),
    PhotoScenario(
        key="travel",
        title="✈️ Путешествие мечты",
        description="Переносит человека в красивое место, сохраняя внешность и исходный ракурс.",
        section="looks",
        prompt=(
            f"{IDENTITY_RULES} Place the person naturally into an aspirational premium travel "
            "photograph. Match lighting, perspective and shadows so the person truly belongs "
            "in the location. Use tasteful travel clothing appropriate for the destination."
        ),
        options=(
            ScenarioOption("sea", "🏝 Море", "Luxurious tropical coast at golden hour."),
            ScenarioOption("dubai", "🏙 Дубай", "Modern Dubai skyline and premium city atmosphere."),
            ScenarioOption(
                "paris",
                "🗼 Париж",
                "Elegant Paris street with subtle Eiffel Tower view.",
            ),
            ScenarioOption("mountains", "🏔 Горы", "Epic but realistic alpine mountain landscape."),
            ScenarioOption(
                "winter",
                "⛷ Зима",
                "Premium snowy mountain resort with warm winter styling.",
            ),
            ScenarioOption(
                "italy",
                "🇮🇹 Италия",
                "Beautiful Italian coastal town in warm evening light.",
            ),
        ),
    ),
    PhotoScenario(
        key="royal",
        title="👑 Король или королева",
        description="Благородный современный королевский портрет с дорогой подачей.",
        section="looks",
        prompt=(
            f"{IDENTITY_RULES} Create a tasteful premium modern royal portrait with refined "
            "palace lighting, luxurious fabrics and elegant details. Avoid historical state "
            "symbols and avoid looking like a cheap costume."
        ),
        options=(
            ScenarioOption(
                "king",
                "👑 Король",
                "Present the person as a charismatic modern king with a refined crown and "
                "masculine royal tailoring.",
            ),
            ScenarioOption(
                "queen",
                "👑 Королева",
                "Present the person as a charismatic modern queen with a refined tiara and "
                "elegant royal styling.",
            ),
        ),
    ),
    PhotoScenario(
        key="greeting",
        title="🎉 Праздничная открытка",
        description="Красивый праздничный портрет с вашей точной подписью.",
        section="looks",
        prompt=(
            f"{IDENTITY_RULES} Create a premium festive greeting-card portrait. Leave clean "
            "negative space for a caption that will be added separately. Do not generate any "
            "letters or words inside the image."
        ),
        options=(
            ScenarioOption(
                "birthday",
                "🎂 День рождения",
                "Tasteful birthday lights, balloons and confetti.",
            ),
            ScenarioOption(
                "new_year",
                "🎄 Новый год",
                "Elegant winter holiday lights and festive decor.",
            ),
            ScenarioOption(
                "love",
                "❤️ Для любимого",
                "Warm romantic decor, subtle hearts and soft light.",
            ),
            ScenarioOption("custom", "✨ Другой праздник", "Tasteful universal celebration decor."),
        ),
        asks_for_text=True,
    ),
)


MEME_PROMPT = (
    f"{IDENTITY_RULES} Turn the person into a polished expressive cartoon Telegram sticker. "
    "Create a funny, instantly readable reaction matching this exact user phrase and its "
    "meaning. Use a clean thick white sticker outline and a flat vivid magenta chroma-key "
    "background reaching every corner. Leave space at the bottom for a caption that will be "
    "added separately. Do not render the phrase or any other text inside the image."
)


def scenario_by_key(key: str) -> PhotoScenario | None:
    return next((item for item in PHOTO_SCENARIOS if item.key == key), None)


def scenarios_for_section(section: str) -> tuple[PhotoScenario, ...]:
    return tuple(item for item in PHOTO_SCENARIOS if item.section == section)


def option_by_key(scenario: PhotoScenario, key: str) -> ScenarioOption | None:
    return next((item for item in scenario.options if item.key == key), None)


def enabled_setting_key(key: str) -> str:
    return f"photo_{key}_enabled"


def price_setting_key(key: str) -> str:
    return f"photo_{key}_price_rub"


def prompt_setting_key(key: str) -> str:
    return f"photo_{key}_prompt"
