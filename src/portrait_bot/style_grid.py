from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from portrait_bot.models import Template

GRID_SIZE = 900
GAP = 18
TILE_SIZE = (GRID_SIZE - GAP * 3) // 2


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("assets/fonts/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    )
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def _preview_path(template: Template) -> Path | None:
    candidates = [
        Path(template.preview_path) if template.preview_path else None,
        Path("assets/previews") / f"{template.slug.replace('_', '-')}.png",
    ]
    return next((path for path in candidates if path and path.exists()), None)


def _placeholder() -> Image.Image:
    image = Image.new("RGB", (TILE_SIZE, TILE_SIZE), "#e8f2e6")
    draw = ImageDraw.Draw(image)
    draw.ellipse((150, 110, 275, 235), fill="#80bd7b")
    draw.rounded_rectangle((115, 235, 310, 350), radius=45, fill="#80bd7b")
    return image


def build_style_grid(templates: list[Template]) -> bytes:
    canvas = Image.new("RGB", (GRID_SIZE, GRID_SIZE), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    badge_font = _font(52)
    title_font = _font(30)
    for index in range(4):
        row, column = divmod(index, 2)
        x = GAP + column * (TILE_SIZE + GAP)
        y = GAP + row * (TILE_SIZE + GAP)
        if index < len(templates):
            path = _preview_path(templates[index])
            if path:
                with Image.open(path) as source:
                    tile = ImageOps.fit(
                        source.convert("RGB"),
                        (TILE_SIZE, TILE_SIZE),
                        method=Image.Resampling.LANCZOS,
                    )
            else:
                tile = _placeholder()
            mask = Image.new("L", (TILE_SIZE, TILE_SIZE), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, TILE_SIZE, TILE_SIZE),
                radius=32,
                fill=255,
            )
            canvas.paste(tile, (x, y), mask)
            draw.rounded_rectangle(
                (
                    x,
                    y + TILE_SIZE - 62,
                    x + TILE_SIZE,
                    y + TILE_SIZE,
                ),
                radius=24,
                fill="#ffffff",
            )
            title = templates[index].title
            while len(title) > 3 and draw.textlength(title, font=title_font) > TILE_SIZE - 28:
                title = title[:-2].rstrip() + "…"
            draw.text(
                (x + 14, y + TILE_SIZE - 48),
                title,
                fill="#1f2937",
                font=title_font,
            )
            draw.ellipse((x + 18, y + 18, x + 90, y + 90), fill="#35a853")
            label = str(index + 1)
            box = draw.textbbox((0, 0), label, font=badge_font)
            draw.text(
                (
                    x + 54 - (box[2] - box[0]) / 2,
                    y + 54 - (box[3] - box[1]) / 2 - box[1],
                ),
                label,
                fill="white",
                font=badge_font,
            )
        else:
            draw.rounded_rectangle(
                (x, y, x + TILE_SIZE, y + TILE_SIZE),
                radius=32,
                fill="#f1f4f0",
            )
            draw.ellipse(
                (
                    x + TILE_SIZE // 2 - 38,
                    y + TILE_SIZE // 2 - 38,
                    x + TILE_SIZE // 2 + 38,
                    y + TILE_SIZE // 2 + 38,
                ),
                fill="#c8d4c6",
            )
            draw.text(
                (x + TILE_SIZE // 2, y + TILE_SIZE // 2),
                "+",
                fill="white",
                font=badge_font,
                anchor="mm",
            )
    output = BytesIO()
    canvas.save(output, "JPEG", quality=90, optimize=True)
    return output.getvalue()
