from __future__ import annotations

import asyncio
import base64
from abc import ABC, abstractmethod
from time import monotonic
from typing import Any

import httpx

from portrait_bot.config import Settings


class VideoProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VideoProvider(ABC):
    @abstractmethod
    async def generate(self, source: bytes, prompt: str, duration: int) -> bytes:
        raise NotImplementedError


class MockVideoProvider(VideoProvider):
    async def generate(self, source: bytes, prompt: str, duration: int) -> bytes:
        del source, prompt, duration
        return b"mock-mp4"


class AITunnelVideoProvider(VideoProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for video generation")
        base_url = (settings.openai_base_url or "https://api.aitunnel.ru/v1/").rstrip("/") + "/"
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            timeout=httpx.Timeout(60.0, read=120.0),
            follow_redirects=True,
            transport=transport,
        )
        self.model = settings.video_model
        self.size = settings.video_size
        self.poll_interval = settings.video_poll_interval_seconds
        self.timeout = settings.video_timeout_seconds
        self.generate_audio = settings.video_generate_audio

    async def generate(self, source: bytes, prompt: str, duration: int) -> bytes:
        encoded = base64.b64encode(source).decode("ascii")
        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": self.size,
            "duration": duration,
            "generate_audio": self.generate_audio,
            "frame_images": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                    "frame_type": "first_frame",
                }
            ],
        }
        try:
            response = await self.client.post("videos", json=payload)
            response.raise_for_status()
            submitted = self._json_object(response)
            job_id = str(submitted.get("id") or "")
            if not job_id:
                raise VideoProviderError(
                    "empty_job_id",
                    "AI Tunnel не вернул идентификатор видеозадания",
                )

            started_at = monotonic()
            while monotonic() - started_at < self.timeout:
                await asyncio.sleep(self.poll_interval)
                status_response = await self.client.get(f"videos/{job_id}")
                status_response.raise_for_status()
                status_data = self._json_object(status_response)
                status = str(status_data.get("status") or "")
                if status == "completed":
                    urls = status_data.get("unsigned_urls")
                    download_url = (
                        str(urls[0])
                        if isinstance(urls, list) and urls and isinstance(urls[0], str)
                        else f"videos/{job_id}/content?index=0"
                    )
                    video_response = await self.client.get(download_url)
                    video_response.raise_for_status()
                    if not video_response.content:
                        raise VideoProviderError(
                            "empty_video",
                            "AI Tunnel вернул пустой видеофайл",
                        )
                    return video_response.content
                if status == "failed":
                    error = status_data.get("error")
                    raise VideoProviderError(
                        "generation_failed",
                        f"AI Tunnel не создал видео: {error or 'неизвестная ошибка'}",
                    )
            raise VideoProviderError(
                "generation_timeout",
                "AI Tunnel не завершил видео за отведённое время",
            )
        except VideoProviderError:
            raise
        except httpx.HTTPStatusError as exc:
            detail = self._error_detail(exc.response)
            raise VideoProviderError(
                f"http_{exc.response.status_code}",
                f"Ошибка AI Tunnel ({exc.response.status_code}): {detail}",
            ) from exc
        except httpx.HTTPError as exc:
            raise VideoProviderError(
                "network_error",
                "Не удалось связаться с AI Tunnel",
            ) from exc

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise VideoProviderError(
                "invalid_response",
                "AI Tunnel вернул некорректный ответ",
            ) from exc
        if not isinstance(data, dict):
            raise VideoProviderError(
                "invalid_response",
                "AI Tunnel вернул ответ неожиданного формата",
            )
        return data

    @classmethod
    def _error_detail(cls, response: httpx.Response) -> str:
        try:
            data = cls._json_object(response)
        except VideoProviderError:
            return response.text[:300] or "неизвестная ошибка"
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)[:300]
        return str(error or data)[:300]


def build_video_provider(settings: Settings) -> VideoProvider:
    use_aitunnel = settings.video_provider == "aitunnel" or (
        settings.video_provider == "auto"
        and bool(settings.openai_api_key)
        and "aitunnel.ru" in (settings.openai_base_url or "")
    )
    if use_aitunnel:
        return AITunnelVideoProvider(settings)
    return MockVideoProvider()
