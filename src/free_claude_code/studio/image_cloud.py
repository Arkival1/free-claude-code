"""Pictures from an online image service, for PCs without a graphics card.

Any service with the OpenAI images API works: OpenAI itself, and the many
services that copy its shape (base URL + key + model). A new picture is a
"generations" call; changing a picture (a character talking, or angry) is an
"edits" call with the first picture attached. The style's words are added
to every prompt, as the PC's image engine does.
"""

import base64
from dataclasses import dataclass
from pathlib import Path

import httpx

SIZES = ((1024, 1024), (1536, 1024), (1024, 1536))
"""What gpt-image style services accept: square, wide, and tall."""


class ImageCloudError(RuntimeError):
    """The online image service could not make the picture."""


@dataclass(frozen=True, slots=True)
class CloudSettings:
    base_url: str
    api_key: str
    model: str = "gpt-image-1"

    @property
    def ready(self) -> bool:
        return bool(self.base_url.strip() and self.api_key.strip())


def nearest_size(width: int, height: int) -> tuple[int, int]:
    """The service size closest in shape to the one asked for."""
    want = width / max(1, height)
    return min(SIZES, key=lambda size: abs(size[0] / size[1] - want))


async def make_picture(
    settings: CloudSettings,
    prompt: str,
    out: Path,
    *,
    size: tuple[int, int],
    start_from: Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Path:
    if not settings.ready:
        raise ImageCloudError("Add the image service's address and key in Settings.")
    width, height = nearest_size(*size)
    base = settings.base_url.rstrip("/")
    headers = {"authorization": f"Bearer {settings.api_key.strip()}"}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, read=300.0), transport=transport
    ) as client:
        try:
            if start_from is None:
                answer = await client.post(
                    f"{base}/images/generations",
                    headers=headers,
                    json={
                        "model": settings.model,
                        "prompt": prompt,
                        "size": f"{width}x{height}",
                        "n": 1,
                    },
                )
            else:
                answer = await client.post(
                    f"{base}/images/edits",
                    headers=headers,
                    data={
                        "model": settings.model,
                        "prompt": prompt,
                        "size": f"{width}x{height}",
                        "n": "1",
                    },
                    files={
                        "image": (start_from.name, start_from.read_bytes(), "image/png")
                    },
                )
        except httpx.HTTPError as error:
            raise ImageCloudError(
                f"The image service couldn't be reached: {error}"
            ) from error
        if answer.status_code >= 400:
            raise ImageCloudError(
                f"The image service answered {answer.status_code}: {answer.text[:300]}"
            )
        try:
            item = answer.json()["data"][0]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ImageCloudError("The image service sent no picture back.") from error
        if item.get("b64_json"):
            data = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            try:
                fetched = await client.get(str(item["url"]))
                fetched.raise_for_status()
            except httpx.HTTPError as error:
                raise ImageCloudError(
                    f"The picture couldn't be fetched: {error}"
                ) from error
            data = fetched.content
        else:
            raise ImageCloudError("The image service sent no picture back.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out
