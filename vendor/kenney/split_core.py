"""Split kenney-core.zip into parts under 20 MB, whole packs per part.

    python3 -I split_core.py <kenney-core.zip> <catalogue.json.gz> <out folder>

Writes kenney-core-1.zip, kenney-core-2.zip, ... and records each shipped
pack's part in the catalogue ("bundle"), so every release zip stays under the
25 MB a phone can download.
"""

import gzip
import json
import sys
import zipfile
from pathlib import Path

LIMIT = 20_000_000


def main() -> None:
    core, catalogue, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    rows = json.loads(gzip.decompress(catalogue.read_bytes()))
    with zipfile.ZipFile(core) as source:
        by_pack: dict[str, list[zipfile.ZipInfo]] = {}
        for info in source.infolist():
            by_pack.setdefault(info.filename.split("/", 1)[0], []).append(info)
        part, target, written = 0, None, 0
        bundles: dict[str, str] = {}
        for pack_id in sorted(by_pack):
            size = sum(info.compress_size for info in by_pack[pack_id])
            if target is None or written + size > LIMIT:
                if target is not None:
                    target.close()
                part += 1
                target = zipfile.ZipFile(
                    out / f"kenney-core-{part}.zip",
                    "w",
                    zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
                written = 0
            for info in by_pack[pack_id]:
                target.writestr(
                    zipfile.ZipInfo(info.filename, (2024, 1, 1, 0, 0, 0)),
                    source.read(info),
                    zipfile.ZIP_DEFLATED,
                )
            written += size
            bundles[pack_id] = f"kenney-core-{part}.zip"
        if target is not None:
            target.close()
    for row in rows:
        row["bundle"] = bundles.get(row["id"], "") if row["shipped"] else ""
    blob = gzip.compress(
        json.dumps(rows, separators=(",", ":")).encode(), mtime=0, compresslevel=9
    )
    catalogue.write_bytes(blob)
    print(
        part,
        "parts",
        {
            name: sum(1 for b in bundles.values() if b == name)
            for name in set(bundles.values())
        },
    )


if __name__ == "__main__":
    main()
