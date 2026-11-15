# FCC's Godot kit fonts

Five fonts from Google Fonts (https://github.com/google/fonts), each under
the SIL Open Font License 1.1 (all five licences, with their copyright lines,
are in `LICENSE`). They are FCC's Godot kit fonts: every FCC game on the PC
and the phone can show symbols and emoji (Godot's built-in font has letters,
digits and punctuation only) and use a pixel or fantasy style for headings.

| Kit file | Font | google/fonts path | Upstream file |
| --- | --- | --- | --- |
| `symbols2.ttf` | Noto Sans Symbols 2 | `ofl/notosanssymbols2` | `NotoSansSymbols2-Regular.ttf` |
| `symbols.ttf` | Noto Sans Symbols | `ofl/notosanssymbols` | `NotoSansSymbols[wght].ttf` |
| `emoji.ttf` | Noto Emoji (black and white) | `ofl/notoemoji` | `NotoEmoji[wght].ttf` |
| `pixel.ttf` | Press Start 2P | `ofl/pressstart2p` | `PressStart2P-Regular.ttf` |
| `fantasy.ttf` | MedievalSharp | `ofl/medievalsharp` | `MedievalSharp.ttf` |

Fetched from the `main` branch of google/fonts on 2026-11-06 through
raw.githubusercontent.com (the GitHub API wasn't reachable from the build
machine, so the commit isn't recorded; `SHA256SUMS` pins the exact bytes).
The fonts are unmodified; only the file names are shorter. Press Start 2P and
MedievalSharp have Reserved Font Names, which only matter for modified
versions (none here).

How FCC uses them:

- `src/free_claude_code/studio/godot/kit/fonts/` holds them, with
  `.ttf.import` files saying `importer="keep"`, so Godot ships them as they
  are and `FontFile.load_dynamic_font` reads them on the PC, in exports and
  on the phone alike.
- `kit.gd` (`res://fcc/kit.gd` in a game): `Kit.use_fonts()` makes the
  symbols and emoji fonts fallbacks of the default font; `Kit.font("pixel")`
  and `Kit.font("fantasy")` give the styles.
- PC: `godot.starter_files()` copies the kit into every starter as `fcc/`.
- Phone: `scripts/phone/build_pages.py` copies the fonts to
  `phone_static/godot/fcc/fonts/` and lists their checksums in
  `godot/kit.js`; `js/godot.js` adds the kit to any game that loads
  `res://fcc/`, fetching the fonts once and checking them.
