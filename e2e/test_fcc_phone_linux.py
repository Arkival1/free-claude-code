"""FCC Linux on the phone: FCC's own small Linux (Alpine-based) boots in the
v86 emulator in a sealed box, runs commands and Python, keeps files, has no
network, opens from a snapshot after the first boot, keeps a session, and
Jarvis uses it with the linux tool."""

import json
import re
from pathlib import Path

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
                network: await call({ action: 'run', command: 'python3 -c "import urllib.request; urllib.request.urlopen(\'http://example.com\', timeout=20)" 2>&1 | tail -1' }),
            };
        }"""
    )
    assert done["tools"]
    assert "FCC Linux 2.0" in done["info"] and re.search(
        r"Python\s+3\.12", done["info"]
    )
    assert done["wrote"].startswith("Wrote /root/hello.py")
    assert done["ran"].startswith("exit code 0") and '{"sum": 5050}' in done["ran"]
    assert "1024" in done["ran"]
    assert done["read"].startswith("import json")
    assert done["failed"].startswith("exit code 1") and "No such file" in done["failed"]
    # The network card leads only to FCC, which says no while the internet
    # switch is off.
    assert "HTTP Error 403" in done["network"], done["network"]

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


def test_the_internet_switch_github_and_the_token_stay_outside_linux(
    page: Page, admin_base_url: str
) -> None:
    """Off by default: nothing leaves. Switched on: http requests go out as
    https through FCC, fcc-github clones through GitHub's API with the token
    FCC adds (never seen inside Linux), and a push waits for the user's OK."""
    page.set_default_timeout(WAIT)
    seen: list[dict] = []

    def github(route) -> None:
        request = route.request
        seen.append(
            {
                "url": request.url,
                "auth": request.headers.get("authorization", ""),
                "method": request.method,
            }
        )
        path = request.url.split("api.github.com", 1)[1]
        answers = {
            "/zen": "Keep it logically awesome.",
            "/repos/o/r": json.dumps({"default_branch": "main", "private": True}),
            "/repos/o/r/commits/main": json.dumps(
                {"sha": "c" * 40, "commit": {"tree": {"sha": "t" * 40}}}
            ),
            f"/repos/o/r/git/trees/{'t' * 40}?recursive=1": json.dumps(
                {
                    "truncated": False,
                    "tree": [
                        {
                            "path": "hello.py",
                            "mode": "100644",
                            "type": "blob",
                            "sha": "b" * 40,
                        }
                    ],
                }
            ),
            f"/repos/o/r/git/blobs/{'b' * 40}": "print('hello from GitHub')\n",
        }
        if path in answers:
            route.fulfill(status=200, body=answers[path])
        else:
            route.fulfill(status=404, body=json.dumps({"message": "Not Found"}))

    page.route("https://api.github.com/**", github)
    open_phone(page, admin_base_url, "lab/linux")
    expect(page.get_by_role("switch", name="FCC Linux internet")).not_to_be_checked()
    page.get_by_role("button", name="▶ Start FCC Linux").click()
    expect(page.locator(".linux-status")).to_contain_text(
        "Tap the terminal to type", timeout=WAIT
    )
    run = """async ([command, seconds]) => {
        const { runningLinux } = await import('./js/linux.js');
        return runningLinux().run(command, { timeoutMs: seconds * 1000 });
    }"""
    off = page.evaluate(
        run, ["fcc-net; wget -qO- http://api.github.com/zen; echo exit=$?", 60]
    )
    assert "Internet: off" in off["text"] and "exit=1" in off["text"], off
    assert seen == []

    page.get_by_role("switch", name="FCC Linux internet").check()
    page.get_by_label("GitHub token").fill("ghp_test_token_never_inside")
    page.get_by_role("button", name="Save").click()
    on = page.evaluate(
        run,
        [
            "wget -qO- http://api.github.com/zen; echo; cd /root && fcc-github clone o/r && cat r/hello.py && grep -r ghp_test /root /etc 2>/dev/null | head -1; echo done",
            240,
        ],
    )
    assert "Keep it logically awesome." in on["text"], on
    assert "hello from GitHub" in on["text"] and "ghp_test" not in on["text"], on
    assert all(item["url"].startswith("https://api.github.com/") for item in seen)
    assert seen[-1]["auth"] == "Bearer ghp_test_token_never_inside"

    # A push asks first; saying no stops it.
    page.once("dialog", lambda dialog: dialog.dismiss())
    pushed = page.evaluate(
        run,
        [
            "cd /root/r && echo more >> hello.py && git -c user.name=t -c user.email=t@t commit -qam more && fcc-github push; echo exit=$?",
            240,
        ],
    )
    assert "said no" in pushed["text"] and "exit=1" in pushed["text"], pushed
    assert not any(item["method"] == "PATCH" for item in seen)
    expect(page.locator(".linux-net-log")).to_contain_text("denied")


PIXEL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="


def test_projects_are_folders_in_fcc_linux_both_ways(
    page: Page, admin_base_url: str
) -> None:
    """Each FCC project is /projects/<project> in FCC Linux: its files are
    there when it opens, and files changed there (by Jarvis or typed in the
    terminal) come back into the project."""
    page.set_default_timeout(WAIT)
    open_phone(page, admin_base_url, "lab/linux")
    page.evaluate(
        """async (pixel) => {
            const projects = await import('./js/projects.js');
            const project = await projects.createProject('Shop site', 'you');
            await projects.writeFile(project, 'index.html', '<h1>Shop</h1>\\n', 'you');
            await projects.putPicture(project, 'img/dot.png', pixel, 'you');
        }""",
        PIXEL,
    )
    page.get_by_role("button", name="▶ Start FCC Linux").click()
    expect(page.locator(".linux-status")).to_contain_text(
        "Tap the terminal to type", timeout=WAIT
    )
    done = page.evaluate(
        r"""async () => {
            const { runTool } = await import('./js/tools.js');
            const { runningLinux } = await import('./js/linux.js');
            const jarvis = window.fccPhone.state.agents.find((a) => a.role === 'main');
            const ctx = { depth: 0, chain: [], built: new Set() };
            const call = (args) => runTool(jarvis, { name: 'linux', arguments: args }, ctx);
            const wait = (ms) => new Promise((done) => setTimeout(done, ms));
            for (let i = 0; i < 40 && !(await runningLinux().run('ls /projects/shop-site 2>/dev/null')).text.includes('index.html'); i += 1) await wait(500);
            const out = {};
            out.inside = await call({ action: 'run', command: 'cat /projects/shop-site/index.html; file /projects/shop-site/img/dot.png' });
            out.edited = await call({ action: 'run', command: 'sed -i "s/Shop/Shop (built in Linux)/" /projects/shop-site/index.html && echo "body{color:red}" > /projects/shop-site/style.css' });
            runningLinux().send('echo typed > /projects/shop-site/notes.txt\n');
            for (let i = 0; i < 40; i += 1) {
                const project = window.fccPhone.state.projects.find((p) => p.slug === 'shop-site');
                if (project.files['notes.txt']) break;
                await wait(500);
            }
            const project = window.fccPhone.state.projects.find((p) => p.slug === 'shop-site');
            out.files = { index: project.files['index.html'], style: project.files['style.css'], notes: project.files['notes.txt'] };
            return out;
        }"""
    )
    assert "<h1>Shop</h1>" in done["inside"] and "PNG image" in done["inside"], done
    assert "Saved back to FCC Projects" in done["edited"], done
    assert done["files"]["index"] == "<h1>Shop (built in Linux)</h1>\n"
    assert done["files"]["style"] == "body{color:red}\n"
    assert done["files"]["notes"] == "typed\n"


def test_a_backup_never_carries_fcc_linuxs_github_token(
    page: Page, admin_base_url: str
) -> None:
    page.set_default_timeout(WAIT)
    open_phone(page, admin_base_url, "settings")
    page.evaluate(
        """async () => {
            const net = await import('./js/linuxnet.js');
            await net.setInternet(true);
            await net.setGithubToken('ghp_secret_never_in_backups');
        }"""
    )
    with page.expect_download() as caught:
        page.get_by_role("button", name="Save a backup").click()
    backup = json.loads(Path(caught.value.path()).read_text(encoding="utf-8"))
    assert "ghp_secret" not in json.dumps(backup)
    assert backup["settings"]["linux"] == {"internet": False}


def test_the_internet_gateway_guards_fcc_itself_pushes_and_size(
    page: Page, admin_base_url: str
) -> None:
    """Found by CodeRabbit: a program in FCC Linux can't reach FCC's own
    address through the gateway; an OK to push covers only the push calls (a
    repo deletion still asks); an answer over the cap stops as it arrives."""
    page.set_default_timeout(WAIT)
    asked: list[str] = []
    page.route(
        "https://api.github.com/**",
        lambda route: route.fulfill(
            status=200, headers={"Access-Control-Allow-Origin": "*"}, body="{}"
        ),
    )
    page.route(
        "https://bounce.example.org/**",
        lambda route: route.fulfill(
            status=307,
            headers={
                "Location": "http://127.0.0.1:9/stop",
                "Access-Control-Allow-Origin": "*",
            },
        ),
    )
    open_phone(page, admin_base_url, "settings")
    page.expose_function("fccAsk", lambda question: asked.append(question) or True)
    result = page.evaluate(
        """async () => {
            const net = await import('./js/linuxnet.js');
            await net.setInternet(true);
            await net.setGithubToken('ghp_test_token');
            const ask = async (question) => window.fccAsk(question);
            const own = await net.handle({ url: `http://${location.host}/phone/js/state.js`, method: 'GET' }, { ask });
            const push = (path, method) => net.handle({ url: `https://api.github.com/repos/me/app${path}`, method, body: '{}' }, { ask });
            await push('/git/blobs', 'POST');
            await push('/git/trees', 'POST');
            await push('/git/refs/heads/main', 'PATCH');
            await push('', 'DELETE');
            const local = [];
            for (const address of ['http://127.0.0.1:8082/x', 'http://192.168.1.5/', 'http://10.0.0.2/', 'http://100.101.2.3/', 'http://pc.tail1234.ts.net/', 'http://printer.local/', 'http://[::1]/', 'http://intranet/']) {
                local.push((await net.handle({ url: address, method: 'GET' }, { ask })).status);
            }
            const bounced = await net.handle({ url: 'http://bounce.example.org/go', method: 'POST', body: 'x' }, { ask });
            return { own: own.status, local, bounced: bounced.status };
        }"""
    )
    assert result["own"] == 403
    assert result["local"] == [403] * 8, result["local"]
    # A change answered with a redirect isn't followed (it could be bounced
    # into FCC or the home network).
    assert result["bounced"] == 502
    assert len(asked) == 2, asked  # once for the push, once for the deletion
    assert "push to me/app" in asked[0] and "Allow this one change?" in asked[1]


def test_a_phone_file_without_a_sync_record_is_never_overwritten(
    page: Page, admin_base_url: str
) -> None:
    """Found by CodeRabbit: when the record of what FCC wrote into Linux is
    missing (a kept session whose record was lost), a Linux file that differs
    from the phone's comes in beside it instead of replacing it."""
    page.set_default_timeout(WAIT)
    open_phone(page, admin_base_url, "settings")
    result = page.evaluate(
        """async () => {
            const projects = await import('./js/projects.js');
            const sync = await import('./js/linuxprojects.js');
            const project = await projects.createProject('Kept', 'you');
            await projects.putFile(project, 'index.html', 'phone copy', 'you');
            sync.forgetSynced();
            const linuxCopy = btoa('linux copy');
            const machine = {
                run: async (command) => {
                    if (command.includes('find .')) return { code: 0, text: '1' };
                    if (command.startsWith('sed -n')) return { code: 0, text: `./${project.slug}/index.html` };
                    if (command.startsWith('base64')) return { code: 0, text: linuxCopy };
                    return { code: 0, text: '' };
                },
            };
            const back = await sync.syncOut(machine, 'you');
            return { back, files: project.files };
        }"""
    )
    assert result["files"]["index.html"] == "phone copy"
    assert result["files"]["index.html.from-linux.txt"] == "linux copy"
    assert "both changed" in result["back"][0]
