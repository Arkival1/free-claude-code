# Tabler UI kit and Tabler Icons

- Upstream: https://github.com/tabler/tabler (npm `@tabler/core` 1.7.1) and
  https://github.com/tabler/tabler-icons (npm `@tabler/icons` 3.49.0)
- Licence: MIT for both (`LICENSE`, `LICENSE-icons`)
- Owner approved on 24 October 2026 after a preview.

## What FCC uses

`src/free_claude_code/studio/ui_kit/tabler.zip`, built by `pack.py`:

| In the zip | From | Notes |
| --- | --- | --- |
| `vendor/tabler/tabler.min.css`, `tabler.min.js` | `@tabler/core` 1.7.1 `dist/` | unchanged |
| `vendor/tabler/LICENSE` | tabler/tabler `LICENSE` | the npm package has none, so it comes from the repo |
| `vendor/tabler-icons/LICENSE` | `@tabler/icons` 3.49.0 | |
| `icons.json` | `tabler-nodes-outline.json` and `icons.json` of `@tabler/icons` 3.49.0 | all 5,184 outline icons: name, category, tags, shapes |
| `app-kit/` | `vendor/tabler/app-kit/` (FCC's own) | home, leaderboard and settings screens on Tabler |

SHA-256 of the release files read by `pack.py`:

| File | SHA-256 |
| --- | --- |
| tabler.min.css | dcf84d7b4319c29ab33450bfe2a7bbf607458d994ef71023f7509e912cafdbd5 |
| tabler.min.js | 2a3b9ecae44d821b21ba4521da33fca1bdc692454745536418c4e078e8ba6abf |
| tabler-nodes-outline.json | 5a2c7e18f3ce5d49115bddd046b4a81cc9752b30acbb29aa7118c4dfc83df1ba |
| icons.json | 82ee817c9c8256d1b81fad2ffd17c4561de8615ea80aa2f3f63b2c54833abae5 |

`SHA256SUMS` holds the zip's checksum (a test checks it).

Left out: Tabler's optional plugin libraries in `dist/libs/` (charts, maps,
editors; each has its own licence) and the filled icon style. Agents use
the kit through the `ui_kit` tool (`studio/tools.py`).
