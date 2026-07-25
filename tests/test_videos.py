from __future__ import annotations

import base64
from typing import Any

import httpx

from portrait_bot.config import Settings
from portrait_bot.providers.videos import AITunnelVideoProvider


async def test_aitunnel_video_provider_submits_polls_and_downloads() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST" and request.url.path == "/v1/videos":
            return httpx.Response(
                202,
                json={"id": "video-123", "status": "pending"},
            )
        if request.method == "GET" and request.url.path == "/v1/videos/video-123":
            return httpx.Response(
                200,
                json={
                    "id": "video-123",
                    "status": "completed",
                    "unsigned_urls": [
                        "https://api.aitunnel.ru/v1/videos/video-123/content?index=0"
                    ],
                },
            )
        if request.method == "GET" and request.url.path.endswith("/content"):
            return httpx.Response(200, content=b"real-mp4")
        return httpx.Response(404)

    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        openai_base_url="https://api.aitunnel.ru/v1/",
        video_provider="aitunnel",
        video_model="wan2.5",
        video_size="720x1280",
        video_poll_interval_seconds=0.001,
        video_timeout_seconds=1,
    )
    provider = AITunnelVideoProvider(
        settings,
        transport=httpx.MockTransport(handler),
    )
    source = b"jpeg-data"

    result = await provider.generate(source, "Animate naturally", 5)
    await provider.client.aclose()

    assert result == b"real-mp4"
    submitted = requests[0]
    payload: dict[str, Any] = __import__("json").loads(submitted.content)
    assert payload["model"] == "wan-2.7"
    assert payload["size"] == "720x1280"
    assert payload["duration"] == 5
    assert payload["generate_audio"] is False
    assert payload["frame_images"][0]["frame_type"] == "first_frame"
    assert payload["frame_images"][0]["image_url"]["url"] == (
        "data:image/jpeg;base64," + base64.b64encode(source).decode("ascii")
    )
    assert all(request.headers["authorization"] == "Bearer test-key" for request in requests)
