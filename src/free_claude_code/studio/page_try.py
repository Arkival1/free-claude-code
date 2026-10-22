"""Use a project's web page the way a person would, in a hidden browser.

Reading the code can't tell whether typing in a box updates the total; using
the page can. ``try_page`` opens a page from the project folder in a headless
browser (the same Playwright the desktop browser uses), does the steps it is
given (type, pick, click, press a key), reads what is on screen, and reports
what went wrong: a step it couldn't do, a value that wasn't what was
expected, pop-up boxes, script errors, missing files, and a page wider than
the phone screen.
"""

import asyncio
import importlib.util
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

MAX_STEPS = 30
STEP_SECONDS = 4.0
MAX_WAIT_MS = 3000
PAGE_TEXT_CHARS = 1500
PHONE_SIZE = (390, 800)
DESKTOP_SIZE = (1280, 800)
PICTURE_QUALITY = 55
"""JPEG quality of the pictures sent to a model: small enough for free
vision models that take about 180 KB per picture."""
BROWSER_CHANNELS = ("", "msedge", "chrome")
"""Playwright's own Chromium first, then the Edge or Chrome on the PC."""
ACTIONS = ("fill", "select", "click", "press", "check", "uncheck", "wait", "read")
_CSS = re.compile(r"^[#.\[*]|^[a-z][a-z0-9-]*(?:[#.\[:]\S*)?$|\s[>~+]\s")
"""Looks like a CSS selector: #id, .class, [attr], a tag, or a > b."""
_NAME = re.compile(r"^[A-Za-z][\w-]*$")
"""A bare id or name (bill-amount), which small models often give without #."""
CONTROLS_JS = """() => {
  const seen = new Set(), out = [];
  const add = (e, label) => {
    if (seen.has(e) || out.length >= 24) return;
    seen.add(e);
    const tag = e.tagName.toLowerCase();
    const where = e.id ? '#' + e.id : e.name ? `${tag}[name=${e.name}]` : tag;
    label = (label || '').trim().replace(/\\s+/g, ' ').slice(0, 30);
    out.push(label ? `${where} "${label}"` : where);
  };
  for (const e of document.querySelectorAll(
    'input, select, textarea, button, a[href], [role=button]'
  )) {
    const label = e.labels && e.labels[0] ? e.labels[0].innerText : e.innerText || e.value;
    add(e, label);
  }
  // Elements with an id that show something: results like #total.
  for (const e of document.querySelectorAll('body [id]')) {
    if (e.children.length <= 2 && e.innerText) add(e, e.innerText);
  }
  return out;
}"""


class PageTryError(RuntimeError):
    """The page couldn't be opened at all."""


@dataclass(frozen=True, slots=True)
class Step:
    do: str
    target: str = ""
    value: str = ""
    expect: str | None = None


@dataclass(slots=True)
class PageReport:
    page: str
    size: tuple[int, int]
    lines: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    read: dict[str, str] = field(default_factory=dict)
    text: str = ""
    shot: Path | None = None
    picture: bytes = b""
    """With a shot: the same view as a small JPEG, for a model that can see."""

    @property
    def passed(self) -> bool:
        return not self.problems

    def render(self) -> str:
        verdict = "PASSED" if self.passed else f"FAILED ({len(self.problems)})"
        width, height = self.size
        out = [f"{verdict}: tried {self.page} at {width}x{height}."]
        out += self.lines
        if self.problems:
            out.append("Problems:")
            out += [f"- {problem}" for problem in self.problems]
        if self.text:
            out.append(f"Page text at the end:\n{self.text}")
        return "\n".join(out)


def page_try_ready() -> bool:
    """Whether Playwright, which drives the hidden browser, is installed."""
    return importlib.util.find_spec("playwright") is not None


def parse_steps(raw: object) -> tuple[Step, ...]:
    """The steps an agent asked for, checked before the browser opens."""
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise ValueError("steps must be a list of {do, target, value} objects.")
    if len(raw) > MAX_STEPS:
        raise ValueError(f"Give at most {MAX_STEPS} steps at a time.")
    steps: list[Step] = []
    for number, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"Step {number} must be an object like {{do, target}}.")
        do = str(item.get("do", "")).strip().lower()
        if do not in ACTIONS:
            raise ValueError(
                f"Step {number}: do must be one of {', '.join(ACTIONS)} (got {do!r})."
            )
        target = str(item.get("target", "")).strip()
        if do not in {"wait", "press"} and not target:
            raise ValueError(f"Step {number} ({do}) needs a target.")
        expect = item.get("expect")
        steps.append(
            Step(
                do=do,
                target=target,
                value=str(item.get("value", "")),
                expect=None if expect is None else str(expect),
            )
        )
    return tuple(steps)


def page_path(folder: Path, page: str) -> Path:
    """The page's file inside the project; never a file outside it."""
    name = (page or "index.html").strip().lstrip("/") or "index.html"
    path = (folder / name).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise ValueError("The page must be a file inside the project.")
    if path.is_dir():
        path = path / "index.html"
    if not path.is_file():
        raise ValueError(f"There is no {name} in the project.")
    return path


type Launch = Callable[[], Awaitable[tuple[Any, Any]]]
"""Start Playwright and a browser: (runner, browser)."""


async def _launch() -> tuple[Any, Any]:
    from playwright.async_api import async_playwright

    runner = await async_playwright().start()
    errors: list[str] = []
    for channel in BROWSER_CHANNELS:
        try:
            browser = await runner.chromium.launch(
                channel=channel or None, headless=True
            )
        except Exception as error:  # a missing browser raises Error
            errors.append(f"{channel or 'chromium'}: {str(error).splitlines()[0]}")
            continue
        return runner, browser
    await runner.stop()
    raise PageTryError(
        "Could not start a hidden browser to try the page. " + "; ".join(errors)
    )


async def try_page(
    folder: Path,
    page: str,
    steps: Sequence[Step],
    *,
    phone: bool = True,
    shot: Path | None = None,
    launch: Launch = _launch,
) -> PageReport:
    """Open the page, do the steps, and report what a user would see; with
    ``shot``, save a picture of the page at the end there too."""
    path = page_path(folder, page)
    size = PHONE_SIZE if phone else DESKTOP_SIZE
    report = PageReport(page=path.relative_to(folder.resolve()).as_posix(), size=size)
    runner, browser = await launch()
    try:
        context = await browser.new_context(
            viewport={"width": size[0], "height": size[1]}
        )
        tab = await context.new_page()
        _listen(tab, report, folder)
        await tab.goto(path.as_uri(), wait_until="load", timeout=15_000)
        await _play(tab, report, steps, phone=phone, shot=shot)
    finally:
        try:
            await browser.close()
        finally:
            await runner.stop()
    return report


async def try_url(
    url: str,
    steps: Sequence[Step],
    *,
    name: str = "",
    phone: bool = True,
    shot: Path | None = None,
    settle_ms: int = 1500,
    launch: Launch = _launch,
) -> PageReport:
    """The same as ``try_page`` for a page a server serves (FCC's own Studio
    pages, run from the Changer's copy). Files the page asks for that the
    server doesn't have count as missing files."""
    size = PHONE_SIZE if phone else DESKTOP_SIZE
    report = PageReport(page=name or url, size=size)
    runner, browser = await launch()
    try:
        context = await browser.new_context(
            viewport={"width": size[0], "height": size[1]}
        )
        tab = await context.new_page()
        _listen(tab, report, None, origin=_origin(url))
        try:
            await tab.goto(url, wait_until="load", timeout=30_000)
        except Exception as error:  # Playwright raises its own Error
            raise PageTryError(
                f"Could not open {name or url}: {str(error).splitlines()[0][:200]}"
            ) from error
        await tab.wait_for_timeout(settle_ms)
        await _play(tab, report, steps, phone=phone, shot=shot)
    finally:
        try:
            await browser.close()
        finally:
            await runner.stop()
    return report


def _origin(url: str) -> str:
    match = re.match(r"^(https?://[^/]+)", url)
    return match.group(1) if match else ""


async def _play(
    tab: Any,
    report: PageReport,
    steps: Sequence[Step],
    *,
    phone: bool,
    shot: Path | None,
) -> None:
    """Do the steps, check the width, read the page, and take its picture."""
    await tab.wait_for_timeout(200)
    for number, step in enumerate(steps, start=1):
        if not await _do(tab, number, step, report):
            break
        await tab.wait_for_timeout(120)
    await _phone_width(tab, report, phone)
    text = await tab.evaluate("() => document.body ? document.body.innerText : ''")
    report.text = " ".join(str(text).split())[:PAGE_TEXT_CHARS]
    if shot is not None:
        shot.parent.mkdir(parents=True, exist_ok=True)
        await tab.screenshot(path=str(shot))
        report.shot = shot
        report.picture = await tab.screenshot(type="jpeg", quality=PICTURE_QUALITY)


async def screenshot_pages(
    pages: Sequence[tuple[str, str]],
    folder: Path,
    *,
    size: tuple[int, int] = DESKTOP_SIZE,
    settle_ms: int = 2500,
    launch: Launch = _launch,
) -> tuple[list[Path], list[str]]:
    """Screenshot web pages by URL: ``(name, url)`` pairs → ``folder/name.png``.

    Returns the pictures taken and a line for each page that failed.
    """
    folder.mkdir(parents=True, exist_ok=True)
    taken: list[Path] = []
    problems: list[str] = []
    runner, browser = await launch()
    try:
        context = await browser.new_context(
            viewport={"width": size[0], "height": size[1]}
        )
        tab = await context.new_page()
        for name, url in pages:
            target = folder / f"{name}.png"
            try:
                await tab.goto(url, wait_until="load", timeout=30_000)
                await tab.wait_for_timeout(settle_ms)
                await tab.screenshot(path=str(target))
            except Exception as error:  # one page failing keeps the rest
                problems.append(f"{name}: {str(error).splitlines()[0][:200]}")
                continue
            taken.append(target)
    finally:
        try:
            await browser.close()
        finally:
            await runner.stop()
    return taken, problems


def _listen(
    tab: Any, report: PageReport, folder: Path | None, *, origin: str = ""
) -> None:
    def on_dialog(dialog: Any) -> None:
        report.problems.append(
            f"A pop-up {dialog.type} box opened: {dialog.message!r}. Pop-up "
            "boxes block the page; show messages and ask for input on the page."
        )
        asyncio.ensure_future(dialog.dismiss())

    def on_console(message: Any) -> None:
        # A served page's failed loads are judged by on_response below: a
        # missing script is a problem, an API's 404 is an answer.
        if origin and message.text.startswith("Failed to load resource"):
            return
        if message.type == "error":
            report.problems.append(f"Console error: {message.text[:300]}")

    def on_error(error: Any) -> None:
        report.problems.append(f"Script error: {str(error)[:300]}")

    def on_failed(request: Any) -> None:
        url = str(request.url)
        if url.startswith("file:") and folder is not None:
            name = url.removeprefix(folder.resolve().as_uri()).lstrip("/")
            report.problems.append(f"Missing file: {name or url}")

    def on_response(response: Any) -> None:
        url = str(response.url)
        # Scripts, styles, pictures and fonts only: an API's 404 is an answer.
        kind = str(getattr(response.request, "resource_type", ""))
        if (
            url.startswith(origin)
            and int(response.status) == 404
            and kind in {"script", "stylesheet", "image", "font"}
        ):
            report.problems.append(f"Missing file: {url.removeprefix(origin)}")

    tab.on("dialog", on_dialog)
    tab.on("console", on_console)
    tab.on("pageerror", on_error)
    tab.on("requestfailed", on_failed)
    if origin:
        tab.on("response", on_response)


async def _find(tab: Any, target: str) -> Any:
    """A CSS selector, or else a field's label, a button's name, or text."""
    css = bool(_CSS.search(target))
    if css:
        try:
            found = tab.locator(target)
            if await found.count():
                return found.first
        except Exception:  # not valid CSS after all; try it as words
            css = False
    if _NAME.match(target):
        found = tab.locator(f'[id="{target}"], [name="{target}"]')
        if await found.count():
            return found.first
    for found in (
        tab.get_by_label(target),
        tab.get_by_role("button", name=target),
        tab.get_by_role("link", name=target),
        tab.get_by_placeholder(target),
        tab.get_by_text(target),
    ):
        if await found.count():
            return found.first
    return tab.locator(target).first if css else tab.get_by_text(target).first


async def _do(tab: Any, number: int, step: Step, report: PageReport) -> bool:
    """One step; False stops the run (the page isn't what the steps expect)."""
    timeout = STEP_SECONDS * 1000
    label = f"{step.do} {step.target}".strip()
    try:
        match step.do:
            case "wait":
                ms = min(int(float(step.value or 500)), MAX_WAIT_MS)
                await tab.wait_for_timeout(ms)
                report.lines.append(f"{number}. waited {ms} ms")
                return True
            case "press":
                key = step.value or "Enter"
                if step.target:
                    await (await _find(tab, step.target)).press(key, timeout=timeout)
                else:
                    await tab.keyboard.press(key)
                report.lines.append(f"{number}. pressed {key} {step.target}".rstrip())
                return True
            case "read":
                found = await _find(tab, step.target)
                shown = await _shown(found, timeout)
                report.read[step.target] = shown
                line = f"{number}. {step.target} shows {shown!r}"
                if step.expect is not None:
                    if _same(shown, step.expect):
                        line += " (as expected)"
                    else:
                        line += f" (expected {step.expect!r})"
                        report.problems.append(
                            f"Step {number}: {step.target} shows {shown!r}, "
                            f"expected {step.expect!r}."
                        )
                report.lines.append(line)
                return True
        found = await _find(tab, step.target)
        match step.do:
            case "fill":
                await found.fill(step.value, timeout=timeout)
            case "select":
                try:
                    await found.select_option(value=step.value, timeout=timeout)
                except Exception:
                    await found.select_option(label=step.value, timeout=timeout)
            case "click":
                await found.click(timeout=timeout)
            case "check":
                await found.check(timeout=timeout)
            case "uncheck":
                await found.uncheck(timeout=timeout)
        value = f" = {step.value!r}" if step.do in {"fill", "select"} else ""
        report.lines.append(f"{number}. {label}{value}")
        return True
    except Exception as error:
        first = str(error).splitlines()[0] if str(error) else type(error).__name__
        logger.debug("Studio: try_page step {} failed: {}", number, first)
        controls = await _controls(tab)
        report.problems.append(
            f"Step {number} ({label}) couldn't be done: {first[:240]}. Fix the "
            "step, not the page: use a target the page has (#id, a label, or "
            "button text)."
            + (f" The page has: {', '.join(controls)}." if controls else "")
        )
        return False


async def _controls(tab: Any) -> list[str]:
    """The page's boxes and buttons, to name in a failed step's report."""
    try:
        return [str(item) for item in await tab.evaluate(CONTROLS_JS)]
    except Exception:
        return []


async def _shown(found: Any, timeout: float) -> str:
    tag = await found.evaluate("e => e.tagName.toLowerCase()", timeout=timeout)
    if tag in {"input", "textarea", "select"}:
        return str(await found.input_value(timeout=timeout))
    return " ".join(str(await found.inner_text(timeout=timeout)).split())


def _same(shown: str, expect: str) -> bool:
    """Equal, or the expected words appear in what's shown (ignoring case
    and spacing): "$15.21" matches "Tip: $15.21"."""
    a = " ".join(shown.split()).casefold()
    b = " ".join(expect.split()).casefold()
    return a == b or (bool(b) and b in a)


async def _phone_width(tab: Any, report: PageReport, phone: bool) -> None:
    if not phone:
        return
    wide = await tab.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    if int(wide) > 2:
        report.problems.append(
            f"The page is {int(wide)}px wider than a phone screen, so it "
            "scrolls sideways; something is too wide."
        )
