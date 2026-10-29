"""Build studio/bug_library/bugs.json.gz from SWE-bench Verified.

    uv run --no-project --with pyarrow python -I vendor/swe-bench/pack.py <test.parquet>

The parquet is `data/test-00000-of-00001.parquet` of the Hugging Face dataset
princeton-nlp/SWE-bench_Verified (untrusted data: this only reads it).
Pylint's rows are left out: pylint is GPL-2.0, which FCC can't ship.
"""

import gzip
import hashlib
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "src/free_claude_code/studio/bug_library/bugs.json.gz"
LEFT_OUT = {"pylint-dev/pylint"}
LICENCES = {
    "astropy/astropy": "BSD-3-Clause",
    "django/django": "BSD-3-Clause",
    "matplotlib/matplotlib": "Matplotlib (PSF-based)",
    "mwaskom/seaborn": "BSD-3-Clause",
    "pallets/flask": "BSD-3-Clause",
    "psf/requests": "Apache-2.0",
    "pydata/xarray": "Apache-2.0",
    "pytest-dev/pytest": "MIT",
    "scikit-learn/scikit-learn": "BSD-3-Clause",
    "sphinx-doc/sphinx": "BSD-2-Clause",
    "sympy/sympy": "BSD-3-Clause",
}


def main(parquet: Path) -> None:
    rows = pq.read_table(parquet).to_pylist()
    kept = []
    for row in rows:
        if row["repo"] in LEFT_OUT:
            continue
        if row["repo"] not in LICENCES:
            raise SystemExit(f"No licence recorded for {row['repo']}")
        kept.append(
            {
                "id": row["instance_id"],
                "repo": row["repo"],
                "commit": row["base_commit"],
                "size": row["difficulty"],
                "issue": row["problem_statement"],
                "hints": row["hints_text"][:2000],
                "fix": row["patch"],
                "test": row["test_patch"],
                "fails": json.loads(row["FAIL_TO_PASS"]),
            }
        )
    kept.sort(key=lambda item: item["id"])
    payload = {"licences": LICENCES, "bugs": kept}
    data = gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), mtime=0)
    OUT.write_bytes(data)
    sums = [
        f"{hashlib.sha256(parquet.read_bytes()).hexdigest()}  test-00000-of-00001.parquet",
        f"{hashlib.sha256(data).hexdigest()}  bugs.json.gz",
    ]
    (HERE / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(len(kept), OUT.stat().st_size)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
