"""Pack Phaser's example code (MIT; not its art) into phaser-examples.json.gz.

    python3 -I pack_examples.py <examples checkout> <out.json.gz>

Only public/src/**/*.js is read, as data. The bugs folder (bug reports, not
lessons) and files over 40 KB (bundled engines and base64 art) are left out.
"""

import gzip
import json
import sys
from pathlib import Path

MAX_BYTES = 40_000


def main() -> None:
    root, out = Path(sys.argv[1]) / "public" / "src", Path(sys.argv[2])
    rows = []
    for path in sorted(root.rglob("*.js")):
        relative = path.relative_to(root)
        if relative.parts[0] == "bugs" or path.stat().st_size > MAX_BYTES:
            continue
        code = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        rows.append(
            {
                "id": relative.with_suffix("").as_posix(),
                "topic": relative.parts[0],
                "title": " / ".join(relative.with_suffix("").parts[1:])
                or relative.stem,
                "code": code,
            }
        )
    blob = gzip.compress(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode(),
        mtime=0,
        compresslevel=9,
    )
    out.write_bytes(blob)
    print(len(rows), "examples", len(blob), "bytes")


if __name__ == "__main__":
    main()
