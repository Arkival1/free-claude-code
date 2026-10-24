"""Find the fastest way to run one model on this PC by measuring it.

Tokens per second is set by the graphics card's memory speed and the model
file's size, but the engine's settings decide how close a model gets to that
limit, and the best ones differ from card to card (flash attention helps on
some cards and slows others). So instead of guessing, Studio tries each
setting on the user's own card, times a real reply, and keeps the winner.
"""

from dataclasses import dataclass, field

from free_claude_code.core.json_types import JsonObject

from .models import EngineModelSettings

BATCH_CHOICES = (256, 512, 1024, 2048)
DEFAULT_BATCH = 512
PROMPT_TOKENS = 1500
"""New text an agent's turn typically reads (the rest is cached)."""
REPLY_TOKENS = 150
"""What it typically writes back."""
BETTER_BY = 1.03
"""A change has to be at least 3% faster to be kept (timings wobble)."""

# Bits per weight, so a file's quantization says how much it slows writing.
_BITS = {
    "F32": 32.0,
    "F16": 16.0,
    "FP16": 16.0,
    "BF16": 16.0,
    "Q8_0": 8.5,
    "Q6_K": 6.6,
    "Q5_K_M": 5.7,
    "Q5_K_S": 5.5,
    "Q5_0": 5.5,
    "Q5_1": 6.0,
    "Q4_K_M": 4.85,
}
FAST_QUANT = "Q4_K_M"


def turn_seconds(result: dict[str, float]) -> float:
    """How long a typical agent turn takes at these speeds (lower is better)."""
    reading = max(result.get("prompt_per_second", 0.0), 0.1)
    writing = max(result.get("predicted_per_second", 0.0), 0.1)
    return PROMPT_TOKENS / reading + REPLY_TOKENS / writing


def filler_prompt() -> str:
    """About a thousand tokens of plain text, so reading speed is measured
    on something as long as an agent's turn."""
    paragraph = (
        "The workshop keeps a log of every job: what the customer asked for, "
        "which parts were ordered, how long each step took, and what was "
        "learned for next time. Reading it back helps plan the next job and "
        "spot the steps that always run late. "
    )
    return (
        paragraph
        * 18
        + "\nIn two sentences, say what the log is for, then list three ways "
        "to keep it useful."
    )


def alternatives(
    stage: str, best: EngineModelSettings, *, layers: int
) -> list[tuple[str, dict[str, object]]]:
    """Settings to try at one stage, as changes to the best so far."""
    if stage == "flash":
        return [
            (f"Flash attention {choice}", {"flash_attention": choice})
            for choice in ("on", "off")
            if choice != best.flash_attention
        ]
    if stage == "batch":
        return [
            (f"Reading batch {size}", {"batch": size})
            for size in (1024, 2048)
            if size != best.batch
        ]
    if stage == "kv":
        other = "q8_0" if best.kv_cache == "f16" else "f16"
        return [(f"Context memory {other}", {"kv_cache": other})]
    if stage == "layers" and 0 <= best.gpu_layers < layers:
        # More layers on the card is faster, until the card runs out of room.
        return [
            (f"{count} layers on the graphics card", {"gpu_layers": count})
            for count in (best.gpu_layers + 2, best.gpu_layers + 4)
            if count <= layers
        ]
    return []


STAGES = ("flash", "batch", "kv", "layers")


def quant_advice(quant: str) -> str:
    """How much faster a smaller quantization of the same model would write."""
    bits = _BITS.get(quant.upper())
    if bits is None or bits <= _BITS[FAST_QUANT] + 0.2:
        return ""
    speedup = bits / _BITS[FAST_QUANT]
    return (
        f"This file is {quant.upper()}. The same model as a {FAST_QUANT} file is "
        f"about {speedup:.1f}x smaller, so it writes about {speedup:.1f}x faster "
        "with little loss in quality: search Hugging Face for the model's name "
        f"plus 'GGUF' and download the {FAST_QUANT} file."
    )


def split_advice(best: EngineModelSettings, layers: int) -> str:
    if 0 <= best.gpu_layers < layers:
        return (
            f"Only {best.gpu_layers} of {layers} layers fit on the graphics card; "
            "the rest run on the processor, which is what slows it most. A "
            "smaller quantization or a smaller model that fits whole is several "
            "times faster."
        )
    return ""


@dataclass
class SpeedHunt:
    """One model's search for its fastest settings, shown as it goes."""

    model: str
    state: str = "running"
    """running, done, or failed."""
    step: str = "Starting"
    done: int = 0
    total: int = 0
    trials: list[JsonObject] = field(default_factory=list)
    best: JsonObject | None = None
    before: JsonObject | None = None
    advice: list[str] = field(default_factory=list)
    error: str = ""

    def view(self) -> JsonObject:
        return {
            "model": self.model,
            "state": self.state,
            "step": self.step,
            "done": self.done,
            "total": self.total,
            "trials": list(self.trials),
            "best": self.best,
            "before": self.before,
            "advice": list(self.advice),
            "error": self.error,
        }


def record(
    label: str,
    settings: EngineModelSettings,
    result: dict[str, float] | None,
    error: str = "",
) -> JsonObject:
    row: JsonObject = {
        "label": label,
        "settings": settings.model_dump(exclude={"id", "created_at", "updated_at"}),
    }
    if result is None:
        row["failed"] = error or "Did not load."
        return row
    row.update(
        {
            "prompt_per_second": result.get("prompt_per_second", 0.0),
            "predicted_per_second": result.get("predicted_per_second", 0.0),
            "turn_seconds": round(turn_seconds(result), 2),
        }
    )
    return row


def plan_size(best: EngineModelSettings, layers: int) -> int:
    """About how many timings the search takes, for the progress bar."""
    return 1 + sum(len(alternatives(stage, best, layers=layers)) for stage in STAGES)
