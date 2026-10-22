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
)
MAX_SHOWN = 12


def free_services(settings: Settings, server_models: Sequence[str]) -> list[JsonObject]:
    """Each free service: ready or not, its models, and how to set it up."""
    found: list[JsonObject] = []
    for provider_id, about in FREE_SERVICES:
        descriptor = PROVIDER_CATALOG.get(provider_id)
        if descriptor is None:
            continue
        attr = descriptor.credential_attr
        ready = bool(attr and getattr(settings, attr, None))
        prefix = f"{provider_id}/"
        listed = [model for model in server_models if model.startswith(prefix)]
        if provider_id == "open_router":
            listed = [model for model in listed if model.endswith(":free")]
        models: list[JsonObject] = []
        if provider_id == "freellmapi":
            models += [
                {"id": f"{prefix}{name}", "note": note}
                for name, note in FREELLMAPI_CHOICES
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
