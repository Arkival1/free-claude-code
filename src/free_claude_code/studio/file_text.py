"""Read the text out of a file someone attached to a chat.

Plain text and code are read as they are; Word, Excel, and PowerPoint files
are zipped XML, so their text is pulled from it; simple PDFs give up the text
in their content streams. Every read is capped so a hostile file cannot
exhaust memory.
"""

import html
import io
import re
import zipfile
import zlib

from free_claude_code.core.json_types import JsonObject

from .model_inspect import identify

MAX_UPLOAD = 25 * 1024 * 1024
MAX_TEXT = 40_000
"""Characters handed to the agent; the rest is left out and said so."""
_MEMBER_BYTES = 20 * 1024 * 1024
_TAG = re.compile(r"<[^>]+>")
_PDF_STREAM = re.compile(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream", re.S)
_PDF_TEXT = re.compile(rb"\((?:\\.|[^\\)])*\)\s*(?:Tj|'|\")|\[(?:[^\]]*)\]\s*TJ|T\*|ET")
_PDF_STRING = re.compile(rb"\((?:\\.|[^\\)])*\)")
_PDF_ESCAPES = {b"n": "\n", b"r": "", b"t": "\t", b"(": "(", b")": ")", b"\\": "\\"}


def read_file_text(name: str, data: bytes) -> JsonObject:
    """{kind, label, text, truncated, message} for one attached file."""
    kind, label = identify(data[:64], name)
    lowered = name.lower()
    text = ""
    message = ""
    if kind == "document" or lowered.endswith((".docx", ".xlsx", ".pptx")):
        text = _office_text(data, lowered)
    elif kind == "pdf":
        text = _pdf_text(data)
        if not text.strip():
            message = (
                "This PDF's text couldn't be read (it may be scanned pictures). "
                "Copy the text into the message instead."
            )
    elif kind == "image":
        message = (
            f"{name} is a picture. Studio's agents read text, so describe it or "
            "paste any text from it."
        )
    elif kind == "gguf":
        message = f"{name} is an AI model. Add it on Model Control instead."
    elif kind == "text" or (kind == "unknown" and b"\x00" not in data[:8192]):
        text = _decode(data)
        label = "text file" if kind != "text" else label
    else:
        message = f"{name} is a {label}; it has no text to read."
    text = text.replace("\r\n", "\n").strip()
    truncated = len(text) > MAX_TEXT
    return {
        "name": name,
        "kind": kind,
        "label": label,
        "text": text[:MAX_TEXT],
        "chars": len(text),
        "truncated": truncated,
        "message": message
        or (
            f"Read {len(text):,} characters"
            + (f"; the first {MAX_TEXT:,} go to the agent." if truncated else ".")
        ),
    }


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _xml_text(xml: str, *, paragraph: str) -> str:
    xml = re.sub(paragraph, "\n", xml)
    xml = re.sub(r"<(?:w:tab|w:br|a:br)[^>]*/>", " ", xml)
    return html.unescape(_TAG.sub("", xml))


def _office_text(data: bytes, name: str) -> str:
    try:
        bundle = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ""

    def member(path: str) -> str:
        with bundle.open(path) as handle:
            return handle.read(_MEMBER_BYTES).decode("utf-8", "replace")

    names = bundle.namelist()
    if name.endswith(".docx") or "word/document.xml" in names:
        return _xml_text(member("word/document.xml"), paragraph=r"</w:p>")
    if name.endswith(".pptx") or any(n.startswith("ppt/slides/") for n in names):
        slides = sorted(
            (n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.findall(r"\d+", n)[-1]),
        )
        return "\n\n".join(
            f"Slide {index}:\n" + _xml_text(member(slide), paragraph=r"</a:p>").strip()
            for index, slide in enumerate(slides, start=1)
        )
    if name.endswith(".xlsx") or "xl/workbook.xml" in names:
        return _sheet_text(bundle, member)
    return ""


def _sheet_text(bundle: zipfile.ZipFile, member) -> str:
    shared: list[str] = []
    if "xl/sharedStrings.xml" in bundle.namelist():
        shared = [
            html.unescape(_TAG.sub("", item))
            for item in re.findall(
                r"<si>(.*?)</si>", member("xl/sharedStrings.xml"), re.S
            )
        ]
    sheets = sorted(
        n for n in bundle.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)
    )
    out: list[str] = []
    for index, sheet in enumerate(sheets, start=1):
        out.append(f"Sheet {index}:")
        for row in re.findall(r"<row[^>]*>(.*?)</row>", member(sheet), re.S)[:2000]:
            cells = []
            for attrs, body in re.findall(r"<c([^>]*)>(.*?)</c>", row, re.S):
                value = re.search(r"<v>(.*?)</v>", body, re.S)
                inline = re.search(r"<t[^>]*>(.*?)</t>", body, re.S)
                if value and 't="s"' in attrs:
                    position = int(value.group(1))
                    cells.append(shared[position] if position < len(shared) else "")
                elif value:
                    cells.append(html.unescape(value.group(1)))
                elif inline:
                    cells.append(html.unescape(inline.group(1)))
            if cells:
                out.append("\t".join(cells))
    return "\n".join(out)


def _pdf_text(data: bytes) -> str:
    """The text of a PDF's pages (not scanned pictures of text)."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        return _basic_pdf_text(data)
    try:
        reader = PdfReader(io.BytesIO(data))
        pages: list[str] = []
        size = 0
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"Page {number}:\n{text}")
                size += len(text)
            if size > MAX_TEXT * 2:
                break
        return "\n\n".join(pages)
    except PdfReadError, ValueError, KeyError, OSError:
        return _basic_pdf_text(data)


def _basic_pdf_text(data: bytes) -> str:
    """The literal text in a simple PDF's content streams, without pypdf."""
    parts: list[str] = []
    for header, body in _PDF_STREAM.findall(data):
        if b"/FlateDecode" in header:
            try:
                body = zlib.decompressobj().decompress(body, _MEMBER_BYTES)
            except zlib.error:
                continue
        elif b"/Filter" in header:
            continue
        if b"Tj" not in body and b"TJ" not in body:
            continue
        line: list[str] = []
        for token in _PDF_TEXT.finditer(body):
            chunk = token.group(0)
            if chunk in (b"T*", b"ET"):
                if line:
                    parts.append("".join(line))
                    line = []
                continue
            line.append("".join(_pdf_string(s) for s in _PDF_STRING.findall(chunk)))
        if line:
            parts.append("".join(line))
    return "\n".join(part for part in parts if part.strip())


def _pdf_string(raw: bytes) -> str:
    inner = raw[1:-1]
    out: list[str] = []
    index = 0
    while index < len(inner):
        byte = inner[index : index + 1]
        if byte == b"\\" and index + 1 < len(inner):
            nxt = inner[index + 1 : index + 2]
            octal = re.match(rb"[0-7]{1,3}", inner[index + 1 : index + 4])
            if octal:
                out.append(chr(int(octal.group(0), 8)))
                index += 1 + len(octal.group(0))
                continue
            out.append(_PDF_ESCAPES.get(nxt, nxt.decode("latin-1")))
            index += 2
            continue
        out.append(byte.decode("latin-1"))
        index += 1
    return "".join(out)
