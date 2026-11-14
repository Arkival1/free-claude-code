# Godot 4 (engine, demo projects, starters)

- Engine: https://github.com/godotengine/godot, release `4.7.2-stable`
  (commit ed1daf0bf), MIT (`LICENSE`).
- Demos: https://github.com/godotengine/godot-demo-projects, commit
  `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`, MIT (`LICENSE-demos.md`).
- Owner approved on 24 October 2026 after a preview.

## What FCC uses

**The engine** is not shipped inside FCC (each build is 60-80 MB). On first
use `studio/godot/engine.py` downloads the editor for the PC from the
release above, checks it against Godot's own SHA-512 list
(`SHA512-SUMS.txt`, copied from the release; the checksums are also written
into `engine.py`), and keeps it in the Repo vault. If GitHub no longer has
the release, the vault's copy is used. Export templates (about 1 GB) are
downloaded the same way, only when a game is exported.

| File | SHA-512 |
| --- | --- |
| Godot_v4.7.2-stable_win64.exe.zip | 83decd58fdf67b9d657958a1ae6bf1929c20785315a81effe245874cdc57acb709bf868e00778a96984338c1b29dafdb453c6847747694621c6ecf5da2259993 |
| Godot_v4.7.2-stable_linux.x86_64.zip | 9aa00f7a605200940bce3027a567b782f49bd8e940dd06ae9e987bd65aee1b1467edd56ed84fcdcbdd44354bf613bdbb4e5d2913e925850368e150c59ed54c65 |
| Godot_v4.7.2-stable_macos.universal.zip | 38aa16e5bba2083941fc5b3e54be0089bd4cc35e32415f5b9fd9a8a6a7b9818255d44532ea8ef94b5aef56c4b407c2d634fa4f657e4ebe681ebbf59b7bac69ca |
| Godot_v4.7.2-stable_export_templates.tpz | ca4d71c4d7b81dfc15d1a98baa07534aa95b03fdda78a0075b06672e1648d2e5f40980c9adc28d23e1b92e732ee7bf3461997aa804af74ec2fcd7a93ccb84079 |

**The demos**: `studio/godot/demos.json.gz`, built by `pack_demos.py`: the
133 GDScript demo projects' scripts, scenes, resources, shaders, project
files and READMEs (each file at most 120 KB). Left out: the 6 C# copies in
`mono/` (and C# project files elsewhere), screenshots and dotfiles.

**The demos' art** (owner asked for it, 24 October 2026):
`studio/godot/art/demo-art-01.zip` ... `-12.zip`, built by `pack_art.py`:
every other file of the 133 demos (2,159 files, 267 MB unpacked, 214 MB
packed): pictures, sound, music, fonts, models (glTF, Blender, OBJ),
skies (HDR, EXR) and Godot's `.import`/`.uid` notes, so a copied demo opens
and runs. Each part is under 23 MB (the release splits parts at 25 MB); a
file bigger than 16 MB (four skies) is stored in chunks across parts.
`art/art.json.gz` lists every file's SHA-256, size and chunks;
`SHA256SUMS` holds every part's checksum, and FCC checks each file against
its SHA-256 before copying it. The demo repo is MIT; some art inside carries
its own open licence (CC0 skies and models, CC-BY / CC BY-SA music and
sounds, SIL OFL fonts), with its licence file or README credit next to it,
copied along with the demo. `art/LICENSE-demos.txt` (the repo's MIT text) is
put into every copied demo as `LICENSE-godot-demos.txt`.

**The starters** in `studio/godot/starters/` are FCC's own (platformer-2d,
rpg-topdown, third-person-3d); the 2D ones take Kenney's Pixel Platformer,
Tiny Town and Tiny Dungeon (CC0) from FCC's game library. All three were
checked with Godot 4.7.2 headless and on screen before shipping.

Agents use all of it through the `godot` tool (`use` copies a whole demo,
code and art, into a project) and the `godot-dev` skill.
