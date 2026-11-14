"""Choose a picture or clip for every scene.

In order: your own library (clips and pictures, matched by name, tags, and
show), the show's fandom wiki (real stills), stock (Pexels clips with a key,
Openverse photos), then pictures made on this PC (your Stable Diffusion) and
art cards, only when AI-made media is allowed. With AI media off and nothing
found, a scene reuses the last real picture instead of a made-up one.

A choice is saved on the scene, so the editor can show it, the user can
swap it, and a re-render keeps it.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import anyio
import httpx

from free_claude_code.core.json_types import JsonObject

from ..images import ImageError, download_image
from ..models import FarmAsset
from .fandom import Fandom, WikiImage
from .library import MediaLibrary, scene_words, word_score
from .visuals import Visuals

PEXELS_VIDEOS = "https://api.pexels.com/videos/search"
MAX_STOCK_CLIP = 80 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Candidate:
    """Something a scene could show, for the editor's picker."""

    kind: str
    """image or video."""
    title: str
    source: str
    preview: str
    """An address the page can show as a thumbnail."""
    asset_id: str = ""
    url: str = ""
    credit: str = ""

    def to_json(self) -> JsonObject:
        return {
            "kind": self.kind,
            "title": self.title,
            "source": self.source,
            "preview": self.preview,
            "asset_id": self.asset_id,
            "url": self.url,
            "credit": self.credit,
        }


def _words(text: str) -> set[str]:
    return {word for word in re.split(r"[^a-z0-9]+", text.lower()) if len(word) >= 3}


def _image_score(image: WikiImage, words: tuple[str, ...]) -> float:
    title = _words(image.title)
    page = _words(image.page)
    return sum(2.0 for word in words if word in title) + sum(
        0.5 for word in words if word in page
    )


class MediaPicker:
    def __init__(
        self,
        *,
        library: MediaLibrary,
        fandom: Fandom,
        visuals: Visuals,
        folder: Path,
        show: str = "",
        niche: str = "",
        wiki: str = "",
        mode: str = "auto",
        allow_ai: bool = True,
        prefer_clips: bool = False,
        pexels_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._library = library
        self._fandom = fandom
        self._visuals = visuals
        self._folder = folder
        self._show = show
        self._niche = niche
        self._wiki = wiki
        self._mode = mode
        self._allow_ai = allow_ai
        self._prefer_clips = prefer_clips
        self._pexels_key = pexels_key
        self._transport = transport
        self._pools: dict[str, list[WikiImage]] = {}
        self.used: set[str] = set()
        self._last_real: JsonObject | None = None
        self._clip_offsets: dict[str, float] = {}

    # ------------------------------------------------------------ picking

    async def pick(
        self, scene: JsonObject, *, topic: str = "", length: float = 5.0
    ) -> JsonObject:
        """A media choice for one scene (see the module notes for the order)."""
        words = scene_words(f"{scene.get('show', '')} {scene.get('say', '')}", topic)
        mode = self._mode
        if mode == "none":
            return {"type": "none"}
        if mode == "text":
            return self._card() if self._allow_ai else self._fallback()
        found: JsonObject | None = None
        if mode == "ai" and self._allow_ai:
            found = await self._ai(scene)
        again: JsonObject | None = None
        if found is None and mode in {"auto", "library", "ai"}:
            found = await self._from_library(words, length)
            # A clip or picture shown already gives way to a fresh wiki still,
            # so a long video doesn't show the same thing for an hour.
            if found is not None and found.get("repeat") and mode != "library":
                again, found = found, None
        if found is None and mode in {"auto", "ai"} and self._show:
            found = await self._from_wiki(words, topic or str(scene.get("show") or ""))
        found = found or again
        if found is None and mode in {"auto", "photos", "ai"}:
            found = await self._stock(scene, words)
        if found is None and self._allow_ai and mode != "library":
            found = await self._ai(scene)
        if found is None:
            return self._card() if self._allow_ai else self._fallback()
        found.pop("repeat", None)
        if found.get("asset"):
            self.used.add(str(found["asset"]))
        if found.get("source") not in {"ai", "card"}:
            self._last_real = found
        return found

    def _card(self) -> JsonObject:
        return {"type": "card", "source": "card"}

    def _fallback(self) -> JsonObject:
        """With AI media off: the last real picture again, or a plain card."""
        if self._last_real is not None:
            return {**self._last_real, "reused": True}
        return {"type": "card", "source": "card", "note": "nothing real was found"}

    async def _from_library(
        self, words: tuple[str, ...], length: float
    ) -> JsonObject | None:
        kinds = ("video", "image") if self._prefer_clips else ("image", "video")
        best = await self._library.best(
            words, show=self._show, kinds=kinds, used=self.used
        )
        if not best:
            return None
        if self._prefer_clips:
            best.sort(key=lambda asset: (asset.id in self.used, asset.kind != "video"))
        # Shown already, or only of the right show (no word in common): a
        # better-fitting wiki still goes first.
        repeat = best[0].id in self.used or word_score(best[0], words) == 0
        choice = self.from_asset(best[0], length=length, mark=False)
        return {**choice, "repeat": True} if repeat else choice

    def from_asset(
        self, asset: FarmAsset, *, length: float = 5.0, mark: bool = True
    ) -> JsonObject:
        if mark:
            self.used.add(asset.id)
        choice: JsonObject = {
            "type": "clip" if asset.kind == "video" else "image",
            "asset": asset.id,
            "source": "library",
            "title": asset.name,
            "credit": asset.credit,
        }
        if asset.kind == "video":
            choice["start"] = self._clip_start(asset, length)
        return choice

    def _clip_start(self, asset: FarmAsset, length: float) -> float:
        """A different part of a clip each time it is used."""
        room = max(0.0, asset.duration - length - 0.5)
        if room <= 0:
            return 0.0
        start = self._clip_offsets.get(asset.id, -length)
        start = (start + length + 3.0) % room
        self._clip_offsets[asset.id] = start
        return round(start, 2)

    async def wiki_images(self, topic: str) -> list[WikiImage]:
        key = topic.lower().strip()
        if key not in self._pools:
            self._pools[key] = await self._fandom.pictures(
                self._show, topic or self._show, link=self._wiki, limit=40
            )
        return self._pools[key]

    async def _from_wiki(self, words: tuple[str, ...], topic: str) -> JsonObject | None:
        pool = await self.wiki_images(topic)
        if len(pool) < 4:
            pool = pool + [
                image
                for image in await self.wiki_images(self._show)
                if image not in pool
            ]
        if not pool:
            return None
        ranked = sorted(
            pool,
            key=lambda image: (image.url in self.used, -_image_score(image, words)),
        )
        for image in ranked[:6]:
            saved = await self.save_url(image.url)
            if saved is not None:
                self.used.add(image.url)
                return {
                    "type": "image",
                    "file": saved,
                    "url": image.url,
                    "source": "wiki",
                    "title": image.title,
                    "credit": image.credit,
                }
        return None

    async def _stock(
        self, scene: JsonObject, words: tuple[str, ...]
    ) -> JsonObject | None:
        query = str(scene.get("show") or " ".join(words[:4]))
        if self._prefer_clips and self._pexels_key:
            clip = await self._pexels_clip(query)
            if clip is not None:
                return clip
        picture = await self._visuals.photo(query, used=self.used)
        if picture is None:
            return None
        name = self._name(picture.source or query, picture.ext)
        await anyio.Path(self._folder / name).write_bytes(picture.data)
        return {
            "type": "image",
            "file": name,
            "source": "openverse",
            "title": query,
            "credit": picture.credit,
        }

    async def _ai(self, scene: JsonObject) -> JsonObject | None:
        if not self._allow_ai or not self._visuals.can_make:
            return None
        made = await self._visuals.make(
            str(scene.get("show") or scene.get("say") or ""),
            style=self._show or self._niche,
        )
        if made is None:
            return None
        name = self._name(f"ai:{scene.get('say')}", made.ext)
        await anyio.Path(self._folder / name).write_bytes(made.data)
        return {"type": "image", "file": name, "source": "ai", "title": "AI picture"}

    # ------------------------------------------------------------ files

    def _name(self, key: str, ext: str) -> str:
        (self._folder / "media").mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:16]
        return f"media/{digest}{ext}"

    async def save_url(self, url: str) -> str | None:
        """Download a picture into the video's folder (once); its relative name."""
        digest = hashlib.sha1(url.encode()).hexdigest()[:16]
        folder = self._folder / "media"
        for ext in (".jpg", ".png", ".webp", ".gif"):
            if (folder / f"{digest}{ext}").is_file():
                return f"media/{digest}{ext}"
        try:
            data, ext = await download_image(url, transport=self._transport)
        except ImageError:
            return None
        folder.mkdir(parents=True, exist_ok=True)
        await anyio.Path(folder / f"{digest}{ext}").write_bytes(data)
        return f"media/{digest}{ext}"

    async def _pexels_clip(self, query: str) -> JsonObject | None:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0), transport=self._transport
        ) as client:
            try:
                response = await client.get(
                    PEXELS_VIDEOS,
                    params={"query": query[:80], "per_page": 6, "size": "medium"},
                    headers={"Authorization": self._pexels_key},
                )
                videos = (
                    response.json().get("videos", [])
                    if response.status_code < 400
                    else []
                )
            except httpx.HTTPError, ValueError:
                return None
            for video in videos:
                page = str(video.get("url") or "")
                if page in self.used:
                    continue
                files = sorted(
                    (
                        f
                        for f in video.get("video_files", [])
                        if str(f.get("link", "")).startswith("https://")
                    ),
                    key=lambda f: abs(int(f.get("height") or 0) - 1080),
                )
                if not files:
                    continue
                link = str(files[0]["link"])
                name = self._name(link, ".mp4")
                target = self._folder / name
                try:
                    async with client.stream("GET", link) as stream:
                        if stream.status_code >= 400:
                            continue
                        size = 0
                        with target.open("wb") as out:
                            async for chunk in stream.aiter_bytes():
                                size += len(chunk)
                                if size > MAX_STOCK_CLIP:
                                    break
                                out.write(chunk)
                    if size > MAX_STOCK_CLIP:
                        target.unlink(missing_ok=True)
                        continue
                except httpx.HTTPError, OSError:
                    target.unlink(missing_ok=True)
                    continue
                self.used.add(page)
                user = (video.get("user") or {}).get("name") or "Pexels"
                return {
                    "type": "clip",
                    "file": name,
                    "start": 0.0,
                    "source": "pexels",
                    "title": query,
                    "credit": f"Video by {user} on Pexels",
                }
        return None

    # ------------------------------------------------------------ for the editor

    async def candidates(self, query: str, *, limit: int = 18) -> list[Candidate]:
        """What could go in a scene: library first, then the wiki, then stock."""
        words = scene_words(query, self._show)
        mine = await self._library.best(
            words or (query.lower(),), show=self._show, limit=8
        )
        found = [
            Candidate(
                kind=asset.kind,
                title=asset.name,
                source="library",
                preview=f"/studio/api/farm/media/{asset.id}/thumb",
                asset_id=asset.id,
            )
            for asset in mine
        ]
        if self._show:
            pool = await self._fandom.pictures(
                self._show, query or self._show, link=self._wiki, limit=12
            )
            found += [
                Candidate(
                    "image",
                    image.title,
                    "wiki",
                    image.url,
                    url=image.url,
                    credit=image.credit,
                )
                for image in pool
            ]
        return found[:limit]
