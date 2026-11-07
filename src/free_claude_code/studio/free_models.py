"""Free AI services, ready to pick as an agent's brain.

The brain pickers list what each free service offers: FreeLLMAPI's router
choices (always, so they're there the moment it runs), OpenRouter's free
models, and the models of the free-tier providers FCC already supports. A
service without a key yet says where to get one and where to paste it.
"""

from collections.abc import Sequence

from free_claude_code.config.provider_catalog import PROVIDER_CATALOG
from free_claude_code.config.settings import Settings
from free_claude_code.core.json_types import JsonObject

FREELLMAPI_CHOICES = (
    ("auto", "the router picks any free model with quota left"),
    ("auto:coding", "the best free model for code"),
    ("auto:smartest", "the strongest free model"),
    ("auto:fast", "the quickest free model"),
)
ROUTER_CHOICES: dict[str, tuple[tuple[str, str], ...]] = {
    "freellmapi": FREELLMAPI_CHOICES,
    "omniroute": (("auto", "its router picks from the providers you connected"),),
}
"""Routers on the owner's PC: their choices show before they're set up."""
FREE_SERVICES: tuple[tuple[str, str], ...] = (
    (
        "freellmapi",
        "Runs on your PC and spreads requests over many free tiers. Install it, "
        "then paste its unified key.",
    ),
    ("nvidia_nim", "Free key; about 40 requests a minute."),
    ("open_router", "Free models (their names end in :free)."),
    ("groq", "Free and very fast; daily limits."),
    ("gemini", "Free tier; a small number of requests a day per model."),
    ("mistral", "Free experiment plan."),
    ("cerebras", "Free tier and fast."),
    (
        "omniroute",
        "Runs on your PC and falls back across the free tiers you connect to it. "
        "Install it, then paste its key.",
    ),
    ("kilo", "Free models (their names end in :free); about 200 requests an hour."),
    ("cohere", "Free trial key for testing."),
    ("zai_api", "Free GLM Flash models."),
    ("cloudflare", "Free daily allowance (needs your account id too)."),
    ("huggingface", "Small free monthly allowance."),
    ("llm7", "Free with limits; a key raises them."),
    ("ollama_cloud", "Free cloud models with hourly limits."),
)
"""From the free-API lists the owner picked (awesome-free-llm-apis and
others), the services FCC can talk to."""
MAX_SHOWN = 12
ALSO_NEEDS: dict[str, tuple[str, ...]] = {"cloudflare": ("cloudflare_account_id",)}
"""Settings a service needs besides its key before it can answer."""


def free_services(settings: Settings, server_models: Sequence[str]) -> list[JsonObject]:
    """Each free service: ready or not, its models, and how to set it up."""
    found: list[JsonObject] = []
    for provider_id, about in FREE_SERVICES:
        descriptor = PROVIDER_CATALOG.get(provider_id)
        if descriptor is None:
            continue
        attr = descriptor.credential_attr
        needed = (attr, *ALSO_NEEDS.get(provider_id, ())) if attr else ()
        ready = bool(needed) and all(getattr(settings, a, None) for a in needed)
        prefix = f"{provider_id}/"
        listed = [model for model in server_models if model.startswith(prefix)]
        if provider_id in {"open_router", "kilo"}:
            listed = [model for model in listed if model.endswith(":free")]
        models: list[JsonObject] = []
        choices = ROUTER_CHOICES.get(provider_id, ())
        if choices:
            models += [
                {"id": f"{prefix}{name}", "note": note} for name, note in choices
            ]
            listed = [m for m in listed if m not in {str(x["id"]) for x in models}]
        models += [{"id": model, "note": ""} for model in listed[:MAX_SHOWN]]
        found.append(
            {
                "id": provider_id,
                "name": descriptor.display_name,
                "about": about,
                "ready": ready,
                "models": models,
                "key_url": descriptor.credential_url or descriptor.website_url,
                "setup": f"Admin, Providers, {descriptor.display_name}: paste the key.",
            }
        )
    return found
