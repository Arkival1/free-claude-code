# Uiverse (galaxy)

- Upstream: https://github.com/uiverse-io/galaxy (the open-source collection
  behind https://uiverse.io)
- Commit: `adbd2adde0a299a3956ea288fb444ec01891ca41` (2 September 2024, the
  newest on `main` on 23 October 2026)
- Licence: MIT (`LICENSE`, copyright Uiverse.io). Each piece keeps its
  designer's credit comment (`From Uiverse.io by …`).

## What FCC uses

All 3,802 pieces (buttons, cards, checkboxes, forms, inputs, notifications,
patterns, radio buttons, toggle switches, tooltips and loaders), owner
approved on 23 October 2026 after a live preview of the whole library.

They ship in `src/free_claude_code/studio/ui_library/uiverse.json.gz`: one
row per upstream file with its id (`kind/author_name`), kind, designer, tags,
whether it needs Tailwind or has a script, and the file's HTML and CSS
unchanged. That file is the source snapshot; `SHA256SUMS` holds its checksum
(a test checks it). `pack.py` rebuilds it from a checkout of the upstream
repo: `python3 -I pack.py <galaxy checkout> uiverse.json.gz`.

The Builder, Coder and Designer use it through the `ui_library` tool
(`studio/ui_library/__init__.py`): `search` by words and kind (plain CSS
first; pieces that need Tailwind only when asked), `get` for one piece's
code, which they copy into a site, rename and restyle with the site's own
colours and fonts.

Nothing is downloaded at run time, so FCC keeps the library if the repo or
uiverse.io goes away. Nothing was left out.
