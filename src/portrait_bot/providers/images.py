from __future__ import annotations

import asyncio
import base64
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Literal, cast

from openai import AsyncOpenAI
from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from portrait_bot.config import Settings


class ImageProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ImageProvider(ABC):
    @abstractmethod
    async def edit(self, source: bytes, prompt: str) -> bytes:
        raise NotImplementedError


class MockImageProvider(ImageProvider):
    async def edit(self, source: bytes, prompt: str) -> bytes:
        return await asyncio.to_thread(self._render, source, prompt)

    @staticmethod
    def _render(source: bytes, prompt: str) -> bytes:
        try:
            with Image.open(BytesIO(source)) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                fitted = ImageOps.fit(image, (760, 760), method=Image.Resampling.LANCZOS)
                fitted = ImageEnhance.Color(fitted).enhance(1.15)
        except Exception as exc:
            raise ImageProviderError("invalid_image", "Не удалось прочитать изображение") from exc

        canvas = Image.new("RGBA", (1024, 1024), "#8B5CF6")
        draw = ImageDraw.Draw(canvas)
        for offset in range(1024):
            ratio = offset / 1023
            color = (
                int(139 + (236 - 139) * ratio),
                int(92 + (72 - 92) * ratio),
                int(246 + (153 - 246) * ratio),
                255,
            )
            draw.line((0, offset, 1024, offset), fill=color)
        draw.rounded_rectangle(
            (100, 100, 924, 924),
            radius=210,
            fill="white",
        )
        mask = Image.new("L", (760, 760), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, 759, 759),
            radius=175,
            fill=255,
        )
        canvas.paste(fitted, (132, 132), mask)
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(
            (112, 112, 912, 912),
            radius=195,
            outline="white",
            width=28,
        )
        draw.ellipse((80, 70, 160, 150), fill="#FDE047", outline="white", width=8)
        draw.ellipse((860, 820, 950, 910), fill="#2DD4BF", outline="white", width=8)
        output = BytesIO()
        canvas.save(output, "PNG", optimize=True)
        return output.getvalue()


class OpenAIImageProvider(ImageProvider):
    def __init__(self, settings: Settings) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.openai_model
        self.size = settings.openai_image_size
        self.quality = settings.openai_image_quality

    async def edit(self, source: bytes, prompt: str) -> bytes:
        try:
            result = await self.client.images.edit(
                model=self.model,
                image=("portrait.jpg", source, "image/jpeg"),
                prompt=prompt,
                size=self.size,
                quality=cast(
                    Literal["standard", "low", "medium", "high", "auto"],
                    self.quality,
                ),
            )
            encoded = result.data[0].b64_json if result.data else None
            if not encoded:
                raise ImageProviderError("empty_response", "OpenAI не вернул изображение")
            return base64.b64decode(encoded)
        except ImageProviderError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None) or "openai_error"
            raise ImageProviderError(str(code), "Не удалось обработать фото через OpenAI") from exc


def build_image_provider(settings: Settings) -> ImageProvider:
    if settings.image_provider == "openai":
        return OpenAIImageProvider(settings)
    return MockImageProvider()
