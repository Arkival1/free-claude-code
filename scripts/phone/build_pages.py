"""Copy FCC Phone into docs/ so GitHub Pages serves it for free.

GitHub Pages publishes a branch's docs/ folder at
https://<user>.github.io/<repo>/, so the phone app ends up at .../phone/.
Run this after changing anything in src/free_claude_code/api/phone_static/;
a test fails while the two copies differ.
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "free_claude_code" / "api" / "phone_static"
DOCS = ROOT / "docs"
TARGET = DOCS / "phone"
INDEX = """<!doctype html>
<meta charset="utf-8" />
<meta http-equiv="refresh" content="0; url=phone/" />
<title>FCC Phone</title>
<a href="phone/">Open FCC Phone</a>
"""


def build() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET)
    (DOCS / "index.html").write_text(INDEX, encoding="utf-8")
    # Serve the files as they are, without Jekyll.
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")


if __name__ == "__main__":
    build()
    print(f"FCC Phone copied to {TARGET.relative_to(ROOT)}")
