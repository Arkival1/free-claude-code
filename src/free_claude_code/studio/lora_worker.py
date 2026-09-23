"""Train a LoRA adapter for one Studio job, anywhere Python and a GPU live.

This file is deliberately standalone: it imports nothing from FCC, so the same
script runs on the machine serving Studio, on a rented GPU, or on a VPS. It
pulls the job's settings and training data from Studio over HTTP with a
per-job token, reports every optimizer step back, and uploads the finished
adapter (and a GGUF copy for Ollama/llama.cpp when llama.cpp is available).

    pip install torch transformers peft accelerate
    python lora_worker.py --studio http://HOST:8082 --job lora_x --token T

Heavy libraries are imported inside functions so ``--probe`` can report what
is missing instead of crashing.
"""

import argparse
import contextlib
import json
import math
import os
import random
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, BinaryIO

PROGRESS_EVERY_SECONDS = 2.0
RETRIES = 4


class Cancelled(Exception):
    """Studio asked this job to stop."""


class Studio:
    """The few HTTP calls a worker makes, with retries for flaky links."""

    def __init__(self, base_url: str, job_id: str, token: str) -> None:
        self.base = base_url.rstrip("/")
        self.job = job_id
        self.token = token

    def _call(
        self,
        method: str,
        path: str,
        *,
        body: bytes | BinaryIO | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> bytes:
        url = f"{self.base}/studio/api/lora/worker/{self.job}/{path}"
        all_headers = {"x-lora-token": self.token, **(headers or {})}
        last_error: Exception | None = None
        for attempt in range(RETRIES):
            request = urllib.request.Request(
                url, data=body, method=method, headers=all_headers
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:300]
                if error.code in {401, 403, 404, 409, 410}:
                    raise RuntimeError(
                        f"Studio refused {path}: {error.code} {detail}"
                    ) from error
                last_error = error
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last_error = error
            time.sleep(2**attempt)
        raise RuntimeError(f"Could not reach Studio at {url}: {last_error}")

    def get_json(self, path: str) -> dict:
        return json.loads(self._call("GET", path))

    def get_rows(self, split: str) -> list[dict]:
        text = self._call("GET", f"dataset?split={split}").decode("utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def post_json(self, path: str, payload: dict) -> dict:
        raw = self._call(
            "POST",
            path,
            body=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        return json.loads(raw) if raw else {}

    def upload(self, name: str, path: Path) -> None:
        size = path.stat().st_size
        with path.open("rb") as handle:
            self._call(
                "PUT",
                f"files/{name}",
                body=handle,
                headers={
                    "content-type": "application/octet-stream",
                    "content-length": str(size),
                },
                timeout=1800.0,
            )


def probe() -> dict[str, object]:
    """Report which training libraries and accelerators this Python can use."""
    report: dict[str, object] = {
        "python": sys.version.split()[0],
        "executable": sys.executable,
    }
    try:
        import torch

        report["torch"] = torch.__version__
        report["cuda"] = bool(torch.cuda.is_available())
        report["gpu"] = (
            torch.cuda.get_device_name(0) if torch.cuda.is_available() else ""
        )
        report["gpu_memory_gb"] = (
            round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
            if torch.cuda.is_available()
            else 0
        )
        backends = getattr(torch, "backends", None)
        mps = getattr(backends, "mps", None)
        report["mps"] = bool(mps and mps.is_available())
    except ImportError:
        report["torch"] = None
    for name in ("transformers", "peft", "bitsandbytes"):
        try:
            module = __import__(name)
            report[name] = getattr(module, "__version__", "installed")
        except ImportError:
            report[name] = None
    return report


def _device(preference: str) -> str:
    import torch

    if preference in {"cpu", "cuda", "mps"}:
        return preference
    if torch.cuda.is_available():
        return "cuda"
    backends = getattr(torch, "backends", None)
    mps = getattr(backends, "mps", None)
    if mps and mps.is_available():
        return "mps"
    return "cpu"


def _estimated_parameters(config: object) -> float:
    hidden = getattr(config, "hidden_size", 0) or 0
    layers = getattr(config, "num_hidden_layers", 0) or 0
    vocab = getattr(config, "vocab_size", 0) or 0
    return 12.0 * layers * hidden * hidden + 2.0 * vocab * hidden


def _render(tokenizer: Any, messages: list[dict], *, generation: bool) -> str:
    template = getattr(tokenizer, "chat_template", None)
    if template:
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=generation
        )
    parts = [f"<|{m['role']}|>\n{m['content']}\n" for m in messages]
    if generation:
        parts.append("<|assistant|>\n")
    eos = getattr(tokenizer, "eos_token", "") or ""
    return "".join(parts) + ("" if generation else eos)


def encode(tokenizer: Any, row: dict, max_len: int) -> dict[str, list[int]] | None:
    """Tokenize one chat and train only on the final assistant turn."""
    messages = row.get("messages") or []
    if len(messages) < 2 or messages[-1].get("role") != "assistant":
        return None
    full = tokenizer(
        _render(tokenizer, messages, generation=False), add_special_tokens=False
    )["input_ids"]
    prompt = tokenizer(
        _render(tokenizer, messages[:-1], generation=True), add_special_tokens=False
    )["input_ids"]
    shared = 0
    for left, right in zip(full, prompt, strict=False):
        if left != right:
            break
        shared += 1
    if len(full) > max_len:
        # Keep the answer: drop the oldest prompt tokens first, and when the
        # answer alone is too long keep a little context plus its beginning.
        keep_prompt = max(0, min(shared, max_len - (len(full) - shared)))
        if keep_prompt == 0 and shared:
            keep_prompt = min(shared, max_len // 4)
        full = full[shared - keep_prompt :][:max_len]
        shared = keep_prompt
    labels = [-100] * shared + full[shared:]
    if all(label == -100 for label in labels):
        return None
    return {"input_ids": full, "labels": labels}


def _batches(rows: list[dict[str, list[int]]], size: int, pad_id: int):
    import torch

    for start in range(0, len(rows), size):
        chunk = rows[start : start + size]
        width = max(len(item["input_ids"]) for item in chunk)
        ids, labels, mask = [], [], []
        for item in chunk:
            gap = width - len(item["input_ids"])
            ids.append(item["input_ids"] + [pad_id] * gap)
            labels.append(item["labels"] + [-100] * gap)
            mask.append([1] * len(item["input_ids"]) + [0] * gap)
        yield {
            "input_ids": torch.tensor(ids),
            "labels": torch.tensor(labels),
            "attention_mask": torch.tensor(mask),
        }


def train(
    spec: dict,
    train_rows: list[dict],
    eval_rows: list[dict],
    workdir: Path,
    studio: Studio,
) -> dict:
    """Run LoRA training and return metrics; the adapter lands in workdir/adapter."""
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

    random.seed(int(spec.get("seed", 7)))
    torch.manual_seed(int(spec.get("seed", 7)))
    base = spec["base_model"]
    token = os.environ.get("HF_TOKEN") or None
    device = _device(str(spec.get("device", "auto")))
    studio.post_json(
        "progress",
        {"step": 0, "message": f"Loading {base} on {device}", "device": device},
    )

    config = AutoConfig.from_pretrained(base, token=token)
    tokenizer = AutoTokenizer.from_pretrained(base, token=token)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    quantize = str(spec.get("quantize", "auto"))
    four_bit = False
    if device == "cuda" and quantize in {"auto", "4bit"}:
        try:
            __import__("bitsandbytes")
            four_bit = quantize == "4bit" or _estimated_parameters(config) > 3e9
        except ImportError:
            if quantize == "4bit":
                raise RuntimeError(
                    "4-bit training needs: pip install bitsandbytes"
                ) from None

    kwargs: dict[str, object] = {"token": token}
    if device == "cuda":
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        kwargs["dtype"] = dtype
        if four_bit:
            from transformers import BitsAndBytesConfig

            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=dtype,
                bnb_4bit_use_double_quant=True,
            )
            kwargs["device_map"] = {"": 0}
    else:
        kwargs["dtype"] = torch.float32
    model = AutoModelForCausalLM.from_pretrained(base, **kwargs)
    model.config.use_cache = False
    if four_bit:
        from peft import prepare_model_for_kbit_training

        model = prepare_model_for_kbit_training(model)
    elif device != "cpu":
        model.to(device)
    if spec.get("gradient_checkpointing", device == "cuda"):
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    model = get_peft_model(
        model,
        LoraConfig(
            r=int(spec.get("rank", 16)),
            lora_alpha=int(spec.get("alpha", 32)),
            lora_dropout=float(spec.get("dropout", 0.05)),
            target_modules="all-linear",
            task_type="CAUSAL_LM",
        ),
    )
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)

    max_len = int(spec.get("max_seq_len", 1024))
    train_set = [
        item for row in train_rows if (item := encode(tokenizer, row, max_len))
    ]
    eval_set = [item for row in eval_rows if (item := encode(tokenizer, row, max_len))]
    if not train_set:
        raise RuntimeError("No training example had an answer to learn from.")

    batch = max(1, int(spec.get("batch_size", 1)))
    accum = max(1, int(spec.get("grad_accum", 4)))
    epochs = max(1, int(spec.get("epochs", 2)))
    per_epoch = max(1, math.ceil(len(train_set) / (batch * accum)))
    total = per_epoch * epochs
    warmup = max(1, int(total * 0.05))
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=float(spec.get("learning_rate", 2e-4)),
    )
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: (
            min(1.0, (step + 1) / warmup)
            * max(0.0, (total - step) / max(1, total - warmup))
        ),
    )
    pad = int(tokenizer.pad_token_id)
    target = "cuda:0" if four_bit else device

    def evaluate() -> float | None:
        if not eval_set:
            return None
        model.eval()
        losses = []
        with torch.no_grad():
            for item in _batches(eval_set, batch, pad):
                item = {key: value.to(target) for key, value in item.items()}
                losses.append(float(model(**item).loss.detach()))
        model.train()
        return sum(losses) / len(losses)

    before = evaluate()
    studio.post_json(
        "progress",
        {
            "step": 0,
            "total": total,
            "eval_loss_before": before,
            "trainable_parameters": trainable,
            "train_examples": len(train_set),
            "eval_examples": len(eval_set),
            "message": f"Training {trainable:,} LoRA parameters on {device}",
            "device": device,
        },
    )
    model.train()
    step, window, last_report = 0, [], 0.0
    for epoch in range(epochs):
        random.shuffle(train_set)
        micro = 0
        for item in _batches(train_set, batch, pad):
            item = {key: value.to(target) for key, value in item.items()}
            loss = model(**item).loss / accum
            loss.backward()
            window.append(float(loss.detach()) * accum)
            micro += 1
            last_micro = micro * batch >= len(train_set)
            if micro % accum and not last_micro:
                continue
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            now = time.monotonic()
            if now - last_report >= PROGRESS_EVERY_SECONDS or step == total:
                reply = studio.post_json(
                    "progress",
                    {
                        "step": step,
                        "total": total,
                        "epoch": epoch + 1,
                        "loss": sum(window) / len(window),
                        "message": f"Epoch {epoch + 1}/{epochs}, step {step}/{total}",
                    },
                )
                window, last_report = [], now
                if reply.get("cancel"):
                    raise Cancelled()
    after = evaluate()
    adapter_dir = workdir / "adapter"
    model.save_pretrained(adapter_dir)
    return {
        "eval_loss_before": before,
        "eval_loss_after": after,
        "steps": step,
        "trainable_parameters": trainable,
        "device": device,
        "four_bit": four_bit,
    }


def zip_adapter(adapter_dir: Path, out: Path) -> Path:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(adapter_dir.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(adapter_dir).as_posix())
    return out


def convert_to_gguf(adapter_dir: Path, base: str, llama_cpp: Path, out: Path) -> Path:
    """Convert the adapter with llama.cpp so Ollama and llama.cpp can load it."""
    from huggingface_hub import snapshot_download

    converter = llama_cpp / "convert_lora_to_gguf.py"
    if not converter.is_file():
        raise RuntimeError(
            f"{converter} not found; point --llama-cpp at a llama.cpp checkout."
        )
    base_dir = snapshot_download(
        base,
        allow_patterns=["*.json", "*.model", "*.txt", "*.tiktoken"],
        token=os.environ.get("HF_TOKEN") or None,
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(converter),
            str(adapter_dir),
            "--base",
            base_dir,
            "--outfile",
            str(out),
            "--outtype",
            "f16",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not out.is_file():
        raise RuntimeError(f"GGUF conversion failed: {completed.stderr[-800:]}")
    return out


def run(args: argparse.Namespace) -> int:
    studio = Studio(args.studio, args.job, args.token)
    workdir = Path(args.workdir or f"lora-{args.job}").resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        spec = studio.get_json("spec")
        studio.post_json(
            "progress", {"step": 0, "message": "Worker connected", "worker": probe()}
        )
        train_rows = studio.get_rows("train")
        eval_rows = studio.get_rows("eval")
        metrics = train(spec, train_rows, eval_rows, workdir, studio)
        studio.post_json(
            "progress", {"step": metrics["steps"], "message": "Uploading the adapter"}
        )
        studio.upload(
            "adapter.zip", zip_adapter(workdir / "adapter", workdir / "adapter.zip")
        )
        llama_cpp = args.llama_cpp or os.environ.get("LLAMA_CPP_DIR")
        if llama_cpp:
            try:
                gguf = convert_to_gguf(
                    workdir / "adapter",
                    spec["base_model"],
                    Path(llama_cpp),
                    workdir / "adapter.gguf",
                )
                studio.upload("adapter.gguf", gguf)
                metrics["gguf"] = True
            except Exception as error:  # the adapter itself is still useful
                metrics["gguf_error"] = str(error)[:400]
        studio.post_json("finish", metrics)
        print("LoRA training finished.", flush=True)
        return 0
    except Cancelled:
        print("Cancelled by Studio.", flush=True)
        return 0
    except BaseException as error:
        detail = f"{type(error).__name__}: {error}"
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        with contextlib.suppress(Exception):
            studio.post_json("fail", {"error": detail[:2000]})
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--studio", help="Studio base URL, e.g. http://100.64.0.2:8082")
    parser.add_argument("--job", help="LoRA job id")
    parser.add_argument(
        "--token",
        default=os.environ.get("STUDIO_LORA_TOKEN"),
        help="The job's worker token (or set STUDIO_LORA_TOKEN)",
    )
    parser.add_argument("--workdir", help="Scratch folder for this job")
    parser.add_argument(
        "--llama-cpp", help="llama.cpp checkout, to also produce a GGUF adapter"
    )
    parser.add_argument(
        "--probe", action="store_true", help="Print what this Python can train with"
    )
    args = parser.parse_args(argv)
    if args.probe:
        print(json.dumps(probe()))
        return 0
    if not (args.studio and args.job and args.token):
        parser.error("--studio, --job and --token are required")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
