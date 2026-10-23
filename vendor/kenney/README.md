# Kenney game assets

- Upstream: https://kenney.nl/assets (Kenney Vleugels; 217 packs on 23
  October 2026)
- Licence: CC0 1.0, public domain. Each pack has its own `License.txt` (one
  is copied here as `LICENSE.txt`). Free for any use, commercial too; credit
  is not required.
- Owner approved on 23 October 2026 after a preview with three playable games.

## What FCC uses

In `src/free_claude_code/studio/game_library/`:

- `kenney-catalogue.json.gz`: every pack's name, category, download address,
  SHA-256 of its zip, and the files a game uses (PNG sprites at their normal
  size, tile sheets, sounds, fonts, glTF models; vector copies, double-size
  copies and other engines' project files are left out). `PACKS.md` lists
  the packs and checksums.
- `kenney-core.zip`: the 49 core packs (platformers, top-down, dungeon,
  space, racing, puzzle, cards, UI, icons, particles, input prompts, fonts
  and all the sound packs), shipped inside FCC. Their sounds are converted to
  mp3 so they play on iPhones; the particle sprites are scaled to 128 px.
- `starter/`: the art and sounds of the `phaser-game` starter.

The other 168 packs (404 MB of 2D, 3D and texture zips altogether, too big
to put in FCC's release zips) download once when an agent asks
(`game_assets` action `download`). FCC only accepts the address recorded in
the catalogue, checks the SHA-256, and keeps the zip in the PC's game vault
(`<data>/game-vault/`) for good, so a pack downloaded once keeps working if
kenney.nl changes or goes away. Downloaded packs keep their .ogg sounds.

`pack.py` built both files from the downloaded zips:
`python3 -I pack.py <zips> <sizes.tsv> <out folder>` (sizes.tsv: id,
category, size, address). `SHA256SUMS` holds the files' checksums (a test
checks them).

The Builder, Coder, Designer and Developer use it through the `game_assets`
tool and the `game-dev` skill.
