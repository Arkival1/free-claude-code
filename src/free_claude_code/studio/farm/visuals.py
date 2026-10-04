"""Pictures for each scene: a local image maker, free photos, or art cards.

A local image maker is Stable Diffusion running on this PC (Automatic1111,
Forge, or SD.Next answer /sdapi/v1/txt2img; LocalAI, sd.cpp's server and
others answer the OpenAI images API). Free photos come from Openverse, the
same search the Builder uses for websites. With neither, the renderer draws
an art card, so a video can always be made offline.
"""

import base64
from dataclasses import dataclass

import httpx

from ..images import ImageError, download_image, find_images

IMAGE_TIMEOUT = 300.0
"""Stable Diffusion on an older graphics card takes a while per picture."""
AI_STYLE = "vertical 9:16, cinematic lighting, highly detailed, sharp focus"


@dataclass(frozen=True, slots=True)
class Picture:
    data: bytes
    ext: str
    credit: str = ""
    source: str = ""


def _sniff(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ""


class Visuals:
    def __init__(
        self,
        *,
        image_url: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        image_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._image_url = image_url.strip().rstrip("/")
        self._transport = transport
        self._image_transport = image_transport

    @property
    def can_make(self) -> bool:
        return bool(self._image_url)

    async def picture(
        self, show: str, *, mode: str, used: set[str], style: str = ""
    ) -> Picture | None:
        """A picture of `show`, or None when the renderer should draw a card."""
        if mode == "ai" and self._image_url:
            made = await self.make(show, style=style)
            if made is not None:
                return made
        if mode in {"photos", "ai"}:
            return await self.photo(show, used=used)
        return None

    async def make(self, show: str, *, style: str = "") -> Picture | None:
        prompt = ", ".join(part for part in (show, style, AI_STYLE) if part)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(IMAGE_TIMEOUT, connect=10.0),
            transport=self._image_transport,
        ) as client:
            for attempt in (self._a1111, self._openai):
                try:
                    data = await attempt(client, prompt)
                except httpx.HTTPError, ValueError, KeyError, IndexError, TypeError:
                    continue
                ext = _sniff(data) if data else ""
                if ext:
                    return Picture(data, ext, source="ai")
        return None

    async def _a1111(self, client: httpx.AsyncClient, prompt: str) -> bytes:
        response = await client.post(
            f"{self._image_url}/sdapi/v1/txt2img",
            json={
                "prompt": prompt,
                "negative_prompt": "text, watermark, blurry, deformed",
                "width": 576,
                "height": 1024,
                "steps": 22,
            },
        )
        response.raise_for_status()
        return base64.b64decode(response.json()["images"][0].split(",")[-1])

    async def _openai(self, client: httpx.AsyncClient, prompt: str) -> bytes:
        base = self._image_url
        path = (
            "/images/generations" if base.endswith("/v1") else "/v1/images/generations"
        )
        response = await client.post(
            f"{base}{path}",
            json={"prompt": prompt, "size": "576x1024", "response_format": "b64_json"},
        )
        response.raise_for_status()
        return base64.b64decode(response.json()["data"][0]["b64_json"])

    async def photo(self, show: str, *, used: set[str]) -> Picture | None:
        for orientation in ("tall", ""):
            try:
                found = await find_images(
                    show, count=6, orientation=orientation, transport=self._transport
                )
            except ImageError:
                return None
            for image in found:
                if image.url in used:
                    continue
                try:
                    data, ext = await download_image(
                        image.url, transport=self._transport
                    )
                except ImageError:
                    continue
                used.add(image.url)
                return Picture(data, ext, credit=image.credit, source=image.page)
        return None
