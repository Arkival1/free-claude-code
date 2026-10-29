"""Claw Code launcher with a native FCC connection.

Studio builds ``claw`` from FCC's own copy of the source (Knowledge &
Memory, Claw Code); a ``claw`` on PATH works too.
"""

import shutil
from collections.abc import Sequence

from free_claude_code.config.paths import studio_dir_path
from free_claude_code.harnesses.environment import client_environment
from free_claude_code.harnesses.launch import PreparedLaunch
from free_claude_code.harnesses.resources import LaunchResources

from .runner import HarnessSpec, LaunchContext, launch_harness

_INSTALL_HINT = (
    "Build Claw Code in FCC Studio: Knowledge & Memory, Claw Code, Build. "
    "It needs Rust from https://rustup.rs."
)
_ROUTING_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OLLAMA_HOST",
    "XAI_API_KEY",
    "DASHSCOPE_API_KEY",
)


def built_binary() -> str | None:
    """The claw Studio built, or one on PATH."""
    for name in ("claw.exe", "claw"):
        path = studio_dir_path() / "claw-code" / "bin" / name
        if path.is_file():
            return str(path)
    return shutil.which("claw")


def _configure(
    ctx: LaunchContext, args: list[str], _files: LaunchResources
) -> PreparedLaunch:
    env = client_environment(
        ctx.base_env,
        proxy_root_url=ctx.proxy_root_url,
        remove_keys=_ROUTING_ENV_KEYS,
        remove_prefixes=("ANTHROPIC_",),
        updates={
            "ANTHROPIC_BASE_URL": ctx.proxy_root_url,
            "ANTHROPIC_AUTH_TOKEN": ctx.auth_token,
        },
    )
    return PreparedLaunch([ctx.binary_path, *args], env)


SPEC = HarnessSpec(
    binary_name="claw",
    display_name="Claw Code",
    install_hint=_INSTALL_HINT,
    configure=_configure,
    binary_finder=built_binary,
)


def launch(argv: Sequence[str] | None = None) -> None:
    launch_harness(SPEC, argv)


if __name__ == "__main__":
    launch()
