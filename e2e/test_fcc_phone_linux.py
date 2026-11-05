"""FCC Linux on the phone: FCC's own small Linux (Alpine-based) boots in the
v86 emulator in a sealed box, runs commands and Python, keeps files, has no
network, opens from a snapshot after the first boot, keeps a session, and
Jarvis uses it with the linux tool."""

import re

import pytest
from playwright.sync_api import Page, expect

from .test_fcc_phone import open_phone

WAIT = 240_000


@pytest.fixture
def browser_context_args(browser_context_args: dict) -> dict:
    return {**browser_context_args, "has_touch": True}


def test_fcc_linux_runs_on_the_phone_and_jarvis_uses_it(
    page: Page, admin_base_url: str
) -> None:
    page.set_default_timeout(WAIT)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_phone(page, admin_base_url, "lab/linux")
    page.get_by_role("button", name="▶ Start FCC Linux").click()
    status = page.locator(".linux-status")
    expect(status).to_contain_text("Tap the terminal to type", timeout=WAIT)
    expect(page.locator(".linux-dock.shown iframe.linux-box")).to_have_attribute(
        "sandbox", "allow-scripts"
    )
    expect(page.get_by_role("button", name="Ctrl-C")).to_be_enabled()
    done = page.evaluate(
        r"""async () => {
            const { runTool } = await import('./js/tools.js');
            const jarvis = window.fccPhone.state.agents.find((a) => a.role === 'main');
            const ctx = { depth: 0, chain: [], built: new Set() };
            const call = (args) => runTool(jarvis, { name: 'linux', arguments: args }, ctx);
            return {
                tools: jarvis.tools.includes('linux'),
                info: await call({ action: 'info' }),
                wrote: await call({ action: 'write', path: '/root/hello.py', content: 'import json\nprint(json.dumps({"sum": sum(range(101))}))\n' + '#'.repeat(9000) + '\n' }),
                ran: await call({ action: 'run', command: 'python3 /root/hello.py && lua5.4 -e "print(2^10)"' }),
                read: await call({ action: 'read', path: '/root/hello.py' }),
                failed: await call({ action: 'run', command: 'ls /missing' }),
                network: await call({ action: 'run', command: 'ls /sys/class/net; python3 -c "import socket; socket.create_connection((\'1.1.1.1\', 80), timeout=3)" 2>&1 | tail -1' }),
            };
        }"""
    )
    assert done["tools"]
    assert "FCC Linux 1.0" in done["info"] and "Python 3.12" in done["info"]
    assert done["wrote"].startswith("Wrote /root/hello.py")
    assert done["ran"].startswith("exit code 0") and '{"sum": 5050}' in done["ran"]
    assert "1024" in done["ran"]
    assert done["read"].startswith("import json")
    assert done["failed"].startswith("exit code 1") and "No such file" in done["failed"]
    # Only the loopback: no network card in the emulated PC.
    assert re.search(r"exit code \d+\nlo\n", done["network"]), done["network"]
    assert "Network is unreachable" in done["network"] or "Error" in done["network"]

    # Keep the session, close, and come back to it in seconds.
    page.get_by_role("button", name="Keep my session").click()
    expect(status).to_contain_text("Kept (", timeout=WAIT)
    page.get_by_role("button", name="Stop").click()
    expect(page.locator(".linux-dock iframe.linux-box")).to_have_count(0)
    page.get_by_role("button", name="▶ Start FCC Linux").click()
    expect(status).to_contain_text("Back where you left off", timeout=WAIT)
    again = page.evaluate(
        """async () => {
            const { runningLinux } = await import('./js/linux.js');
            return (await runningLinux().run('head -c 11 /root/hello.py')).text;
        }"""
    )
    assert again == "import json"
    page.get_by_role("button", name="Stop").click()
    assert errors == [], errors
