# SWE-bench Verified (the bug-fix library)

- Upstream: https://github.com/SWE-bench/SWE-bench (MIT, `LICENSE`); data
  from the Hugging Face dataset `princeton-nlp/SWE-bench_Verified`
  (`data/test-00000-of-00001.parquet`, last changed 18 February 2025)
- Owner approved on 24 October 2026 after a preview.

## What FCC uses

`src/free_claude_code/studio/bug_library/bugs.json.gz`, built by `pack.py`:
490 of the 500 bugs, each with its issue text, hints, the fix the project
merged, the test patch, and the tests that fail before and pass after.
The Changer, its Planner and reviewers read it through the `bug_library`
tool, as examples for fixing FCC's own bugs; the debugging skill points at it.

Each fix and test is the project's own code, under that project's licence,
recorded in the data and shown with each bug:

| Project | Licence | Bugs |
| --- | --- | --- |
| django/django | BSD-3-Clause | 231 |
| sympy/sympy | BSD-3-Clause | 75 |
| sphinx-doc/sphinx | BSD-2-Clause | 44 |
| matplotlib/matplotlib | Matplotlib (PSF-based) | 34 |
| scikit-learn/scikit-learn | BSD-3-Clause | 32 |
| astropy/astropy | BSD-3-Clause | 22 |
| pydata/xarray | Apache-2.0 | 22 |
| pytest-dev/pytest | MIT | 19 |
| psf/requests | Apache-2.0 | 8 |
| mwaskom/seaborn | BSD-3-Clause | 2 |
| pallets/flask | BSD-3-Clause | 1 |

Left out: pylint-dev/pylint's 10 bugs (GPL-2.0, which FCC can't ship), and
the dataset's environment and pass-to-pass fields (FCC doesn't run the
benchmark). `SHA256SUMS` holds the parquet's and the built file's checksums.
