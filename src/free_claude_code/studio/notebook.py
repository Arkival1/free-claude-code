"""Notebooks that run the classroom's teacher, or a training job, on a free
cloud GPU (Kaggle or Google Colab).

The teacher notebook downloads a GGUF model from Hugging Face, serves it with
llama.cpp's OpenAI-compatible server behind a key the notebook makes itself,
and opens a Cloudflare quick tunnel; the owner pastes the printed address and
key into Settings (provider "Cloud notebook") and picks it for the teacher.
The training notebook runs a LoRA job's worker commands, the same ones the
Training page shows, so the student is trained on the notebook's GPU.
"""

import json
from typing import Literal

from free_claude_code.core.json_types import JsonObject

Target = Literal["kaggle", "colab"]
TARGETS: tuple[Target, ...] = ("kaggle", "colab")
TEACHER_REPO = "Qwen/Qwen3-14B-GGUF"
TEACHER_FILE = "Qwen3-14B-Q4_K_M.gguf"
"""Fits one 16 GB T4 (Kaggle and Colab's free GPU) with room for context."""
PORT = 8090
WHEELS = "https://abetlen.github.io/llama-cpp-python/whl/cu124"
CLOUDFLARED = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-linux-amd64"
)


class NotebookError(ValueError):
    """A notebook FCC can't write; the message says why."""


def _markdown(text: str) -> JsonObject:
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip()}


def _code(text: str) -> JsonObject:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": text.strip(),
    }


def _notebook(cells: list[JsonObject], target: Target) -> JsonObject:
    metadata: JsonObject = {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python"},
    }
    if target == "colab":
        metadata["accelerator"] = "GPU"
        metadata["colab"] = {"gpuType": "T4", "provenance": []}
    else:
        metadata["kaggle"] = {"accelerator": "gpu", "isInternetEnabled": True}
    return {"nbformat": 4, "nbformat_minor": 5, "metadata": metadata, "cells": cells}


def _target(value: str) -> Target:
    for item in TARGETS:
        if value == item:
            return item
    raise NotebookError("Pick kaggle or colab.")


def _setup_steps(target: Target) -> str:
    if target == "kaggle":
        return (
            "On Kaggle: **Create > New Notebook > File > Import Notebook**, pick "
            "this file, then in the right panel set **Accelerator: GPU T4** and "
            "turn **Internet on** (Kaggle asks for a verified phone once)."
        )
    return (
        "On Colab: **File > Upload notebook**, pick this file, then **Runtime > "
        "Change runtime type > T4 GPU**."
    )


def _safe_name(value: str, what: str) -> str:
    text = value.strip()
    if not text or any(char in text for char in "\"'\\\n\r`$"):
        raise NotebookError(f"The {what} can't be empty or hold quotes.")
    return text


def teacher_notebook(
    target: str = "kaggle",
    *,
    repo: str = TEACHER_REPO,
    file: str = TEACHER_FILE,
    context: int = 16384,
) -> JsonObject:
    """A notebook that serves a teacher model to FCC from a free cloud GPU."""
    where = _target(target)
    repo = _safe_name(repo, "model repo")
    file = _safe_name(file, "model file")
    if not file.endswith(".gguf"):
        raise NotebookError("The model file must be a .gguf file.")
    context = max(2048, min(131072, int(context)))
    cells = [
        _markdown(
            f"""
# FCC classroom teacher on a free GPU

This notebook runs the classroom's teacher model (`{repo}` / `{file}`) on
{"Kaggle" if where == "kaggle" else "Google Colab"}'s free GPU, so the teacher
can be bigger than the model your PC runs.

{_setup_steps(where)}

Then **Run all**. The last cell prints an address and a key: in FCC open
**Settings > Providers > Cloud notebook (Kaggle, Colab)**, paste them, and
pick the teacher's model in the Classroom (**Pals > Teacher > Cloud
notebook**). Keep this tab open while the class runs; free sessions stop
after a few idle hours (Kaggle gives about 30 GPU hours a week).

The key is made fresh in this notebook and never saved in the file.
"""
        ),
        _code(
            f"""
import secrets, subprocess, sys
API_KEY = secrets.token_urlsafe(24)
MODEL_REPO = "{repo}"
MODEL_FILE = "{file}"
PORT = {PORT}
try:
    subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv"], check=False)
except OSError:
    print("No GPU found: turn on a GPU (T4) for this notebook, then run it again.")
"""
        ),
        _code(
            f"""
# llama.cpp's server with CUDA, as a ready-built wheel (about a minute).
!pip install -q "llama-cpp-python[server]" --extra-index-url {WHEELS}
!pip install -q huggingface_hub
"""
        ),
        _code(
            """
from huggingface_hub import hf_hub_download
MODEL_PATH = hf_hub_download(MODEL_REPO, MODEL_FILE)
print("Model ready:", MODEL_PATH)
"""
        ),
        _code(
            f"""
import time, urllib.request
server = subprocess.Popen(
    [sys.executable, "-m", "llama_cpp.server", "--model", MODEL_PATH,
     "--model_alias", "teacher", "--n_gpu_layers", "-1", "--n_ctx", "{context}",
     "--host", "127.0.0.1", "--port", str(PORT), "--api_key", API_KEY],
    stdout=open("server.log", "w"), stderr=subprocess.STDOUT,
)
for _ in range(180):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{{PORT}}/v1/models",
                               timeout=2).read()
        break
    except Exception:
        time.sleep(2)
else:
    print(open("server.log").read()[-3000:])
    raise SystemExit("The model server didn't start; the log is above.")
print("Teacher model is running.")
"""
        ),
        _code(
            f"""
# A free Cloudflare quick tunnel gives the server a public https address.
import re
!wget -q -O cloudflared {CLOUDFLARED} && chmod +x cloudflared
tunnel = subprocess.Popen(
    ["./cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{{PORT}}"],
    stdout=open("tunnel.log", "w"), stderr=subprocess.STDOUT,
)
ADDRESS = ""
for _ in range(60):
    found = re.search(r"https://[a-z0-9-]+\\.trycloudflare\\.com", open("tunnel.log").read())
    if found:
        ADDRESS = found.group(0)
        break
    time.sleep(1)
if not ADDRESS:
    raise SystemExit("The tunnel didn't open; run this cell again.")
print("Paste these into FCC (Settings > Providers > Cloud notebook):")
print("  Address:", ADDRESS + "/v1")
print("  Key:    ", API_KEY)
print("  Model:   notebook/teacher")
"""
        ),
        _code(
            """
# Keeps the session busy so it isn't stopped while the class runs.
while True:
    time.sleep(300)
    print(time.strftime("%H:%M"), "teacher still serving;",
          "server up" if server.poll() is None else "SERVER STOPPED")
"""
        ),
    ]
    return _notebook(cells, where)


def training_notebook(commands: JsonObject, target: str = "kaggle") -> JsonObject:
    """A notebook that runs one LoRA job's worker on a free cloud GPU."""
    where = _target(target)
    bash = str(commands.get("bash") or "")
    tailscale = str(commands.get("tailscale") or "")
    if not bash:
        raise NotebookError("This training job has no worker commands.")
    secret_line = (
        "from kaggle_secrets import UserSecretsClient\n"
        'os.environ["TS_AUTHKEY"] = UserSecretsClient().get_secret("TS_AUTHKEY")'
        if where == "kaggle"
        else "from google.colab import userdata\n"
        'os.environ["TS_AUTHKEY"] = userdata.get("TS_AUTHKEY")'
    )
    cells = [
        _markdown(
            f"""
# Train the FCC student on a free GPU

This notebook trains the student with the lessons and grades from its
classroom (FCC's LoRA job) and sends the result back to FCC.

{_setup_steps(where)}

The GPU has to reach FCC on your PC. The simplest way is Tailscale: make an
auth key at login.tailscale.com, save it as a notebook secret called
`TS_AUTHKEY` ({"Add-ons > Secrets" if where == "kaggle" else "the key icon on the left"}),
and set **Address For Remote Trainers** in FCC to your PC's Tailscale address.
Then **Run all**.
"""
        ),
        _code(f"import os\n{secret_line}"),
        # One bash cell, so Tailscale's proxy setting reaches the worker.
        _code("\n".join(["%%bash", tailscale, bash])),
    ]
    return _notebook(cells, where)


def dumps(notebook: JsonObject) -> str:
    return json.dumps(notebook, indent=1)
