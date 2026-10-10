"""Check a project for the mistakes a builder makes most, without running it."""

import ast
import json
import re
from collections.abc import Iterable, Mapping
from html.parser import HTMLParser
from posixpath import dirname, normpath
from urllib.parse import unquote, urlsplit

from .templates import STARTER_TEXT

MAX_PROBLEMS = 40
CHECKED_FILES = (".html", ".htm", ".css", ".js", ".mjs", ".py", ".json")
_CSS_URL = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""")
_JS_IMPORT = re.compile(r"""(?:^|\n)\s*import\s[^'"]*?['"](\.{1,2}/[^'"]+)['"]""")
_PAIRS = {"(": ")", "[": "]", "{": "}"}
_REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^") | {""}


class _Links(HTMLParser):
    """Collect local references, ids, and the page's basic structure."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str]] = []
        self.ids: set[str] = set()
        self.tags: set[str] = set()
        self.images_without_alt = 0
        self.cut_svg_urls = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)
        values = {name: value or "" for name, value in attrs}
        if values.get("id"):
            self.ids.add(values["id"])
        for name in ("href", "src"):
            if values.get(name):
                self.refs.append((tag, values[name]))
            # A double quote inside href="data:image/svg+xml,<svg ...>" ends
            # the attribute early and the rest shows as text on the page.
            url = values.get(name, "").lower()
            if (
                url.startswith("data:image/svg+xml,")
                and "</svg>" not in url
                and "%3c/svg%3e" not in url
            ):
                self.cut_svg_urls += 1
        if tag == "img" and "alt" not in values:
            self.images_without_alt += 1


def _is_json_object(text: str) -> bool:
    """A script file that is only a JSON object (a message written into it)."""
    if not text.lstrip().startswith("{"):
        return False
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False


def _local(ref: str) -> str | None:
    """The project path a reference points to, or None for outside links."""
    parts = urlsplit(ref.strip())
    if parts.scheme or parts.netloc or ref.startswith(("#", "//", "data:")):
        return None
    path = unquote(parts.path)
    return path or None


def _resolve(base: str, ref: str) -> str:
    folder = dirname(base)
    joined = ref.lstrip("/") if ref.startswith("/") or not folder else f"{folder}/{ref}"
    path = normpath(joined) if joined else ""
    return "" if path in {"", "."} else path


def _exists(path: str, files: Mapping[str, str]) -> bool:
    return path in files or f"{path.rstrip('/')}/index.html" in files


def _balanced(code: str) -> str | None:
    """Find an unclosed or stray bracket, ignoring strings and comments."""
    stack: list[tuple[str, int]] = []
    line = 1
    index = 0
    quote = ""
    last = ""
    while index < len(code):
        char = code[index]
        if char == "\n":
            line += 1
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif code.startswith("//", index):
            end = code.find("\n", index)
            index = len(code) if end < 0 else end
            continue
        elif code.startswith("/*", index):
            end = code.find("*/", index + 2)
            line += code[index : end if end >= 0 else len(code)].count("\n")
            index = len(code) if end < 0 else end + 2
            continue
        elif char in "\"'`":
            quote = char
        elif char == "/" and last in _REGEX_BEFORE:
            index = _skip_regex(code, index)
            last = "/"
            continue
        elif char in _PAIRS:
            stack.append((char, line))
        elif char in _PAIRS.values():
            if not stack or _PAIRS[stack[-1][0]] != char:
                return f"unexpected '{char}' on line {line}"
            stack.pop()
        if not quote and not char.isspace():
            last = char
        index += 1
    if stack:
        opener, at = stack[-1]
        return f"'{opener}' opened on line {at} is never closed"
    return None


def _skip_regex(code: str, start: int) -> int:
    """Step past a JavaScript regex literal such as /[(]+/g."""
    index = start + 1
    in_class = False
    while index < len(code) and code[index] != "\n":
        char = code[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            return index + 1
        index += 1
    return start + 1


def check_project(files: Mapping[str, str], *, others: Iterable[str] = ()) -> list[str]:
    """Return the problems found in a project's text files, most useful first.

    others names the project's remaining files, such as pictures, so links
    to them count as found.
    """
    problems: list[str] = []
    present = {**dict.fromkeys(others, ""), **files}
    pages = [path for path in files if path.endswith((".html", ".htm"))]
    if pages and not any(path.split("/")[-1] == "index.html" for path in pages):
        problems.append("There is no index.html, so the preview has no start page.")
    for path in sorted(files):
        text = files[path]
        if path.endswith((".html", ".htm")):
            problems.extend(_check_html(path, text, present))
        elif path.endswith(".css"):
            problems.extend(
                f"{path}: {target} is missing (url() in the stylesheet)."
                for target in _missing(path, _CSS_URL.findall(text), present)
            )
            if (issue := _balanced(re.sub(r"url\([^)]*\)", "url()", text))) is not None:
                problems.append(f"{path}: {issue}.")
        elif path.endswith((".js", ".mjs")):
            problems.extend(
                f"{path}: imports {target}, which is missing."
                for target in _missing(path, _JS_IMPORT.findall(text), present)
            )
            if _is_json_object(text):
                problems.append(
                    f"{path}: holds a JSON object, not JavaScript, so the page's "
                    "script is gone. Bring the earlier version back with "
                    "restore_file, or write the script again."
                )
            elif (issue := _balanced(text)) is not None:
                problems.append(f"{path}: {issue}.")
        elif path.endswith(".py"):
            try:
                ast.parse(text, filename=path)
            except SyntaxError as error:
                problems.append(
                    f"{path}: syntax error on line {error.lineno}: {error.msg}."
                )
        elif path.endswith(".json"):
            try:
                json.loads(text)
            except ValueError as error:
                problems.append(f"{path}: invalid JSON ({error}).")
    return problems[:MAX_PROBLEMS]


def _missing(base: str, refs: list[str], files: Mapping[str, str]) -> list[str]:
    missing: list[str] = []
    for ref in refs:
        local = _local(ref)
        if local is None:
            continue
        target = _resolve(base, local)
        if target and not _exists(target, files) and target not in missing:
            missing.append(target)
    return missing


def _check_html(path: str, text: str, files: Mapping[str, str]) -> list[str]:
    parser = _Links()
    try:
        parser.feed(text)
        parser.close()
    except AssertionError:
        return [f"{path}: the HTML could not be read."]
    problems = [
        f"{path}: links to {target}, which is missing."
        for target in _missing(path, [ref for _, ref in parser.refs], files)
    ]
    anchors = {
        ref[1:]
        for _, ref in parser.refs
        if ref.startswith("#") and len(ref) > 1 and not ref.startswith("#/")
    }
    problems.extend(
        f"{path}: links to #{anchor}, but no element has that id."
        for anchor in sorted(anchors - parser.ids)
    )
    if "viewport" not in text and "html" in parser.tags:
        problems.append(
            f'{path}: no <meta name="viewport">, so it will look tiny on phones.'
        )
    if "title" not in parser.tags and "html" in parser.tags:
        problems.append(f"{path}: no <title>.")
    if "html" in parser.tags and not text.lstrip().lower().startswith("<!doctype"):
        problems.append(
            f"{path}: no <!doctype html> first, so browsers use quirks mode."
        )
    if parser.images_without_alt:
        problems.append(
            f"{path}: {parser.images_without_alt} image(s) without alt text."
        )
    if parser.cut_svg_urls:
        problems.append(
            f"{path}: an SVG data URL (like the favicon) is cut short by a double "
            "quote inside it, so stray text shows on the page. Use single quotes "
            "inside the SVG: href=\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'>...</svg>\"."
        )
    drawn = len(re.findall(r"<img\b[^>]*\bdata-placeholder\b", text, re.I))
    if drawn:
        problems.append(
            f"{path}: {drawn} picture(s) are still the template's drawn "
            "placeholders (data-placeholder). Swap in real photos (find_images, "
            "then save_image) and remove data-placeholder, or remove it to keep "
            "the drawn art."
        )
    problems.extend(_unsent_forms(path, text))
    left = [phrase for phrase in STARTER_TEXT if phrase in text]
    if left:
        problems.insert(
            0,
            f"{path}: still has the template's placeholder text "
            f"({'; '.join(repr(p) for p in left[:3])}). Rewrite the page with "
            "real content for the task.",
        )
    return problems


_FORM = re.compile(r"<form\b[^>]*>", re.I)
_MAILTO = re.compile(r"""href\s*=\s*["']mailto:([^"'?]+)""", re.I)


def _attribute(tag: str, name: str) -> str:
    found = re.search(rf"""\b{name}\s*=\s*["']([^"']*)["']""", tag, re.I)
    return found.group(1).strip() if found else ""


def _unsent_forms(path: str, text: str) -> list[str]:
    """A form with nowhere to send messages loses every customer who uses it."""
    emails = [
        address
        for address in _MAILTO.findall(text)
        if not address.lower().endswith(("example.com", "example.org"))
    ]
    if emails:
        return []
    lost = [
        tag
        for tag in _FORM.findall(text)
        if not any(
            _attribute(tag, name) for name in ("action", "data-endpoint", "data-email")
        )
    ]
    if not lost:
        return []
    return [
        f"{path}: {len(lost)} form(s) have nowhere to send messages, so "
        "customers' messages would be lost. Put the business's email in the "
        'form\'s data-email="..." (or a form service address such as Formspree '
        'in data-endpoint="...").'
    ]
