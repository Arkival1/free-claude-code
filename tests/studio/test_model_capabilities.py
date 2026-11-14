"""Model Control shows which models can use tools, see images, and reason."""

import json

import httpx
import pytest

from free_claude_code.studio.engine import Engine
from free_claude_code.studio.gguf_info import read_gguf_info, supports_tools, thinks
from tests.api.support import create_test_app

from .test_model_control import fake_gguf, free_port

QWEN25 = (
    "{%- if tools %}{{- '<|im_start|>system\\n# Tools' }}{%- for tool in tools %}"
    "{{- tool | tojson }}{%- endfor %}<tool_call>{%- endif %}"
)
QWEN3 = (
    QWEN25
    + "{%- if enable_thinking is defined and enable_thinking is false %}<think>\\n\\n</think>{%- endif %}"
)
MISTRAL = "{%- if tools is not none %}[AVAILABLE_TOOLS]{{ tools }}[/AVAILABLE_TOOLS]{%- endif %}[TOOL_CALLS]"
PHI = "{% for message in messages %}<|{{ message['role'] }}|>{{ message['content'] }}<|end|>{% endfor %}"
R1 = "{% if not add_generation_prompt is defined %}{% endif %}<\uff5cAssistant\uff5c><think>\\n"


def test_tools_and_reasoning_come_from_the_chat_template():
    assert supports_tools(QWEN25) and not thinks(QWEN25)
    assert supports_tools(QWEN3) and thinks(QWEN3)
    assert supports_tools(MISTRAL) and not thinks(MISTRAL)
    assert not supports_tools(PHI) and not thinks(PHI)
    assert not supports_tools(R1) and thinks(R1)
    assert thinks("", name="DeepSeek-R1-Distill-Qwen-7B")
    assert thinks("", name="QwQ-32B-Q4_K_M")
    assert not thinks("", name="Qwen2.5-Coder-7B-Instruct")
    assert not supports_tools("You can use tools like a hammer.")


def test_the_header_reader_keeps_the_template(tmp_path):
    info = read_gguf_info(fake_gguf(tmp_path / "q.gguf", template=QWEN3))
    assert info.tools and info.reasoning
    plain = read_gguf_info(fake_gguf(tmp_path / "p.gguf", template=PHI))
    assert not plain.tools and not plain.reasoning


@pytest.mark.asyncio
async def test_each_model_shows_what_it_can_do(tmp_path, store):
    lm = tmp_path / "lmstudio"
    fake_gguf(lm / "pub" / "qwen3-gguf" / "Qwen3-8B-Q4_K_M.gguf", template=QWEN3)
    fake_gguf(lm / "pub" / "gemma" / "gemma-3-4b-it-Q4_K_M.gguf", template=PHI)
    fake_gguf(lm / "pub" / "gemma" / "mmproj-model-f16.gguf")
    shared = tmp_path / "mine"
    fake_gguf(shared / "llava-phi-q4_k_m.gguf", template=PHI)
    fake_gguf(shared / "mmproj-llava-phi-f16.gguf")
    fake_gguf(shared / "mistral-7b-q4_k_m.gguf", template=MISTRAL)
    engine = Engine(
        root=tmp_path / "engine",
        store=store,
        folders=lambda: [("LM Studio", lm), ("Yours", shared)],
        port=free_port,
    )

    status = json.loads(json.dumps(await engine.status()))

    caps = {row["name"]: row["capabilities"] for row in status["models"]}
    assert caps["qwen3-8b"] == {"tools": True, "vision": False, "reasoning": True}
    assert caps["gemma-3-4b-it"] == {"tools": False, "vision": True, "reasoning": False}
    assert caps["llava-phi"]["vision"] is True
    assert caps["mistral-7b"] == {"tools": True, "vision": False, "reasoning": False}
    assert "mmproj-model-f16" not in caps, "the image part is not a model of its own"


@pytest.mark.asyncio
async def test_capabilities_through_the_routes(make_studio, tmp_path):
    studio, _ = make_studio([], STUDIO_ENGINE_FOLDERS=str(tmp_path / "gguf"))
    fake_gguf(tmp_path / "gguf" / "qwen3-4b-q4_k_m.gguf", template=QWEN3)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            (model,) = (await client.get("/studio/api/engine")).json()["models"]
            assert model["capabilities"] == {
                "tools": True,
                "vision": False,
                "reasoning": True,
            }
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
