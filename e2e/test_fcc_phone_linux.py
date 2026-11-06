"""FCC Linux on the phone: FCC's own small Linux (Alpine-based) boots in the
v86 emulator in a sealed box, runs commands and Python, keeps files, has no
network, opens from a snapshot after the first boot, keeps a session, and
Jarvis uses it with the linux tool."""

import json
import re

import pytest
from playwright.sync_api import Page, expect

from free_claude_code.api.studio_routes import PHONE_DIR

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
    assert "FCC Linux 2.0" in done["info"] and "Python 3.12" in done["info"]
    assert done["wrote"].startswith("Wrote /root/hello.py")
    assert done["ran"].startswith("exit code 0") and '{"sum": 5050}' in done["ran"]
    assert "1024" in done["ran"]
    assert done["read"].startswith("import json")
    assert done["failed"].startswith("exit code 1") and "No such file" in done["failed"]
    # The network card has nothing behind it until the internet switch is on.
    assert re.search(r"exit code \d+\n(eth0  )?lo\n", done["network"]), done["network"]
    assert "Network is unreachable" in done["network"] or "Error" in done["network"]

    # Commands run in bash with no keyboard input; a half-typed line at the
    # prompt is cleared, not run; a program left open (cat reading the
    # keyboard) is never typed into: Jarvis is told, Keep waits, and
    # interrupt (Ctrl-C) brings the prompt back.
    guarded = page.evaluate(
        """async () => {
            const { runTool } = await import('./js/tools.js');
            const { runningLinux } = await import('./js/linux.js');
            const jarvis = window.fccPhone.state.agents.find((a) => a.role === 'main');
            const ctx = { depth: 0, chain: [], built: new Set() };
            const call = (args) => runTool(jarvis, { name: 'linux', arguments: args }, ctx);
            const machine = runningLinux();
            const out = {};
            out.bash = await call({ action: 'run', command: 'nums=(4 5 6); echo "count ${#nums[@]}"; python3; echo "python $?"' });
            machine.send('echo HALF-TYPED');
            out.cleared = await call({ action: 'run', command: 'echo clean' });
            machine.send('cat\\n');
            await new Promise((done) => setTimeout(done, 1500));
            out.idleWhileOpen = machine.idle;
            out.busy = await call({ action: 'run', command: 'echo should-not-run' }).catch((error) => 'error: ' + error.message);
            out.keep = await machine.keep().then(() => 'kept', (error) => 'error: ' + error.message);
            out.interrupt = await call({ action: 'interrupt' });
            out.after = await call({ action: 'run', command: 'echo back' });
            return out;
        }"""
    )
    assert "count 3" in guarded["bash"] and "python 0" in guarded["bash"], guarded
    assert guarded["cleared"].rstrip() == "exit code 0\nclean", guarded
    assert guarded["idleWhileOpen"] is False
    assert "busy" in guarded["busy"] and "should-not-run" not in guarded["busy"]
    assert guarded["keep"].startswith("error: Something is running")
    assert "back at its prompt" in guarded["interrupt"], guarded
    assert guarded["after"].rstrip() == "exit code 0\nback", guarded

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


def test_a_bad_pack_stops_fcc_linux_and_says_why(
    page: Page, admin_base_url: str
) -> None:
    """A pack that fails its checksum is never used, and the program that
    needed it doesn't hang: FCC Linux stops and the screen says why."""
    page.set_default_timeout(WAIT)
    contents = json.loads(
        (PHONE_DIR / "linux" / "fcc-linux.json").read_text(encoding="utf-8")
    )
    go_pack = next(row for row in contents["packs"] if "go" in row["packages"])
    page.route(
        f"**/linux/{go_pack['file']}",
        lambda route: route.fulfill(status=200, body=b"not the real pack"),
    )
    open_phone(page, admin_base_url, "lab/linux")
    page.get_by_role("button", name="▶ Start FCC Linux").click()
    status = page.locator(".linux-status")
    expect(status).to_contain_text("Tap the terminal to type", timeout=WAIT)
    ran = page.evaluate(
        """async () => {
            const { runningLinux } = await import('./js/linux.js');
            return runningLinux().run('go version', { timeoutMs: 120000 });
        }"""
    )
    assert ran["code"] == -1 and "closed" in ran["text"], ran
    expect(status).to_contain_text("FCC Linux stopped:")
    expect(status).to_contain_text("checksum is wrong")
    expect(page.locator(".linux-dock iframe.linux-box")).to_have_count(0)
