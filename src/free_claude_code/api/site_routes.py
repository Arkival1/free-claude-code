"""Site Studio: build small business websites from the offline UI library (local only)."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from free_claude_code.application.orb.sites import SiteError, SiteStore
from free_claude_code.config.paths import config_dir_path
from free_claude_code.core.version import package_version

from .admin_security import require_loopback_admin
from .orb_routes import ORB_STATIC_DIR, orb_studio

router = APIRouter()
_PREVIEW_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src https: http: data:; "
    "form-action mailto:; base-uri 'none'; frame-ancestors 'self'"
)


class NewSite(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(default="restaurant", max_length=20)
    description: str = Field(default="", max_length=300)
    preset: str = Field(default="", max_length=40)


class SpecBody(BaseModel):
    spec: dict[str, Any]


class SectionBody(BaseModel):
    action: str = Field(pattern="^(edit|add|remove)$")
    which: str | int | None = None
    kind: str = Field(default="", max_length=20)
    variant: str = Field(default="", max_length=20)
    fields: dict[str, Any] | None = None
    position: int = -1


class ThemeBody(BaseModel):
    palette: str | dict[str, str] | None = None
    font: str | None = None
    button: str | None = None
    radius: float | None = None
    spacing: float | None = None
    scale: float | None = None
    shadow: float | None = None
    width: float | None = None


class PaletteBody(BaseModel):
    base: str = Field(max_length=7)
    harmony: str = Field(default="complementary", max_length=20)
    mode: str = Field(default="light", max_length=10)
    apply_to: str = Field(default="", max_length=60)


class DesignBody(BaseModel):
    kind: str = Field(max_length=20)
    name: str = Field(max_length=40)
    data: dict[str, Any]
    source_url: str = Field(max_length=500)
    licence: str = Field(max_length=40)


def store(request: Request) -> SiteStore:
    sites = getattr(request.app.state, "site_store", None)
    if sites is None:
        sites = SiteStore(config_dir_path() / "sites")
        request.app.state.site_store = sites
    return sites


def _note(request: Request, text: str) -> None:
    orb_studio(request).activity.note(text, "sites")


def _run(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except SiteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orb/sites", include_in_schema=False)
def studio_page(request: Request) -> HTMLResponse:
    require_loopback_admin(request)
    page = (ORB_STATIC_DIR / "sites.html").read_text(encoding="utf-8")
    return HTMLResponse(page.replace("__FCC_VERSION__", package_version()))


@router.get("/orb/site/{slug}", include_in_schema=False)
def preview(slug: str, request: Request) -> HTMLResponse:
    require_loopback_admin(request)
    sites = store(request)
    html_text = _run(lambda: sites.render(sites.get(slug)))
    return HTMLResponse(html_text, headers={"Content-Security-Policy": _PREVIEW_CSP})


@router.get("/orb/api/sites/library")
def library(request: Request) -> dict[str, Any]:
    require_loopback_admin(request)
    return store(request).library()


@router.get("/orb/api/sites")
def list_sites(request: Request) -> dict[str, Any]:
    require_loopback_admin(request)
    return {"sites": store(request).sites()}


@router.post("/orb/api/sites")
def create_site(body: NewSite, request: Request) -> dict[str, Any]:
    require_loopback_admin(request)
    spec = _run(
        store(request).create, body.name, body.kind, body.description, body.preset
    )
    _note(request, f"New site: {spec['name']}")
    return spec


@router.get("/orb/api/sites/{slug}")
def get_site(slug: str, request: Request) -> dict[str, Any]:
    require_loopback_admin(request)
    return _run(store(request).get, slug)


@router.put("/orb/api/sites/{slug}")
def save_site(slug: str, body: SpecBody, request: Request) -> dict[str, Any]:
    require_loopback_admin(request)
    return _run(store(request).save, slug, body.spec)


@router.post("/orb/api/sites/render")
def render(body: SpecBody, request: Request) -> dict[str, Any]:
    require_loopback_admin(request)
    return {"html": _run(store(request).render, body.spec)}


@router.post("/orb/api/sites/{slug}/section")
def section(slug: str, body: SectionBody, request: Request) -> dict[str, Any]:
    require_loopback_admin(request)
    sites = store(request)
    if body.action == "add":
        out = _run(sites.add_section, slug, body.kind, body.variant, body.position)
    elif body.action == "remove":
        out = _run(
            sites.remove_section,
            slug,
            body.which if body.which is not None else body.kind,
        )
    else:
        out = _run(
            sites.edit_section,
            slug,
            body.which if body.which is not None else body.kind,
            body.fields,
            body.variant,
        )
    _note(request, f"Site {slug}: {body.action} {body.kind or body.which}")
    return out


@router.post("/orb/api/sites/{slug}/theme")
def theme(slug: str, body: ThemeBody, request: Request) -> dict[str, Any]:
    require_loopback_admin(request)
    out = _run(store(request).set_theme, slug, **body.model_dump(exclude_none=True))
    _note(request, f"Site {slug}: new look")
    return out


@router.post("/orb/api/sites/palette")
def palette(body: PaletteBody, request: Request) -> dict[str, Any]:
    require_loopback_admin(request)
    sites = store(request)
    if body.apply_to:
        made = _run(
            sites.apply_palette, body.apply_to, body.base, body.harmony, body.mode
        )
        _note(request, f"Site {body.apply_to}: original palette {made['name']}")
        return made
    return _run(sites.make_palette, body.base, body.harmony, body.mode)


@router.post("/orb/api/sites/library")
def add_design(body: DesignBody, request: Request) -> dict[str, Any]:
    require_loopback_admin(request)
    out = _run(
        store(request).add_design,
        body.kind,
        body.name,
        body.data,
        body.source_url,
        body.licence,
    )
    _note(request, f"Library: added {body.kind} {out['added']} ({out['licence']})")
    return out


@router.post("/orb/api/sites/{slug}/export")
async def export(slug: str, request: Request) -> dict[str, Any]:
    require_loopback_admin(request)
    out = await asyncio.to_thread(_run, store(request).export, slug)
    _note(request, f"Site {slug}: exported")
    return out
