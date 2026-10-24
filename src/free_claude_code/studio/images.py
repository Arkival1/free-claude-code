"""Free photos for websites the Builder makes, from Openverse (no key needed).

Openverse indexes Creative Commons images; searching for ones cleared for
commercial use means a site can use them with a credit line.
"""

import ipaddress
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import anyio
import httpx

SEARCH_URL = "https://api.openverse.org/v1/images/"
MAX_IMAGE_BYTES = 5_000_000
"""The largest photo saved into a project."""
_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_ORIENTATIONS = {"wide": "wide", "tall": "tall", "square": "square"}
MAX_REDIRECTS = 4
_HEADERS = {
    "user-agent": "FCC-Studio website builder (+https://github.com/Arkival1/free-claude-code)"
}


class ImageError(Exception):
    """An image could not be found or fetched."""


@dataclass(frozen=True, slots=True)
class FoundImage:
    url: str
    width: int
    height: int
    title: str
    credit: str
    """A ready-made credit line, as the licence asks."""
    page: str


async def find_images(
    query: str,
    *,
    count: int = 6,
    orientation: str = "",
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[FoundImage]:
    """Photos for a query that a website may use, with credit lines."""
    cleaned = " ".join(query.split())[:120]
    if not cleaned:
        raise ImageError("Say what the pictures should show.")
    params: dict[str, str | int] = {
        "q": cleaned,
        "page_size": max(1, min(12, count)),
        "license_type": "commercial",
        "mature": "false",
    }
    if orientation in _ORIENTATIONS:
        params["aspect_ratio"] = _ORIENTATIONS[orientation]
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        transport=transport,
        headers=_HEADERS,
    ) as client:
        try:
            response = await client.get(SEARCH_URL, params=params)
        except httpx.HTTPError as error:
            raise ImageError(f"The image search didn't answer: {error}") from error
    if response.status_code == 429:
        raise ImageError("The free image search is busy; try again in a minute.")
    if response.status_code >= 400:
        raise ImageError(f"The image search answered {response.status_code}.")
    try:
        results = response.json().get("results") or []
    except ValueError as error:
        raise ImageError("The image search sent something unreadable.") from error
    found: list[FoundImage] = []
    for item in results:
        if not isinstance(item, dict) or not str(item.get("url", "")).startswith(
            "https://"
        ):
            continue
        creator = str(item.get("creator") or "unknown")
        licence = str(item.get("license") or "").upper()
        version = str(item.get("license_version") or "")
        credit = (
            f"Photo by {creator}, CC {licence} {version}".strip()
            if licence not in {"CC0", "PDM"}
            else f"Photo by {creator} (public domain)"
        )
        found.append(
            FoundImage(
                url=str(item["url"]),
                width=int(item.get("width") or 0),
                height=int(item.get("height") or 0),
                title=str(item.get("title") or "")[:120],
                credit=credit,
                page=str(item.get("foreign_landing_url") or ""),
            )
        )
    return found


async def download_image(
    url: str,
    *,
    allow_private: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[bytes, str]:
    """The image's bytes and the file extension its type calls for.

    Every address on the way, redirects included, must be a public https one,
    so an agent can't be steered into fetching from the user's own network.
    """
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        transport=transport,
        headers=_HEADERS,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await _check_address(url, allow_private=allow_private)
            try:
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    return await _read_image(response)
            except httpx.HTTPError as error:
                raise ImageError(f"The image couldn't be fetched: {error}") from error
    raise ImageError("The image address redirected too many times.")


async def _read_image(response: httpx.Response) -> tuple[bytes, str]:
    if response.status_code >= 400:
        raise ImageError(f"The image answered {response.status_code}.")
    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind not in _TYPES:
        raise ImageError("That address isn't a JPEG, PNG, WebP, or GIF.")
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > MAX_IMAGE_BYTES:
            raise ImageError("That image is over 5 MB; pick a smaller one.")
    return bytes(data), _TYPES[kind]


async def _check_address(url: str, *, allow_private: bool) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ImageError("Give the image's full https:// address.")
    if allow_private:
        return
    host = parts.hostname
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            found = await anyio.getaddrinfo(host, parts.port or 443)
        except OSError as error:
            raise ImageError(f"{host} couldn't be found.") from error
        addresses = [ipaddress.ip_address(str(info[4][0])) for info in found]
    if not addresses or any(not address.is_global for address in addresses):
        raise ImageError("That address is on a private network, so it's refused.")
