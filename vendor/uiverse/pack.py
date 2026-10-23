"""Pack the Uiverse galaxy folder into FCC's ui_library data file (read as data only)."""
import gzip, hashlib, json, re, sys, pathlib
src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
KINDS = {"Buttons": "button", "Cards": "card", "Checkboxes": "checkbox", "Forms": "form",
         "Inputs": "input", "Notifications": "notification", "Patterns": "background",
         "Radio-buttons": "radio", "Toggle-switches": "toggle", "Tooltips": "tooltip", "loaders": "loader"}
TW = re.compile(r'class="[^"]*\b(?:bg|text|flex|px|py|p|m|mx|my|rounded|w|h|gap|items|justify|border|shadow|font)-[a-z0-9\[]')
rows = []
for folder, kind in KINDS.items():
    for f in sorted((src / folder).glob("*.html")):
        text = f.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip()
        tags = re.search(r"Tags:\s*([^*]+)\*/", text)
        author, _, name = f.stem.rpartition("_")
        tailwind = bool(TW.search(text)) and "<style>" not in text
        scripted = "<script" in text.lower()
        rows.append({"id": f"{kind}/{f.stem}", "kind": kind, "author": author or f.stem,
                     "name": name.replace("-", " "), "tags": tags.group(1).strip() if tags else "",
                     "tailwind": tailwind, "script": scripted, "html": text})
blob = gzip.compress(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0, compresslevel=9)
out.write_bytes(blob)
print(len(rows), len(blob), hashlib.sha256(blob).hexdigest())
