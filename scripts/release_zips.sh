#!/usr/bin/env bash
# Build the zip the owner downloads to install or update FCC on their PC.
#
#   scripts/release_zips.sh OUT_DIR            one zip: FCC-Studio-<version>.zip
#   scripts/release_zips.sh --parts OUT_DIR    the app zip plus -partN zips
#
# The owner's choice (24 October 2026): one big zip, every time. It unpacks
# into the fcc/ folder. --parts splits the starter repo zips, FCC's big
# libraries and the image engine source into parts under 25 MB each (for a
# phone); every part unpacks into the same fcc/ folder. Tests, browser
# tests, the GitHub Pages site (docs/) and vendor/cua (not used yet) are
# left out either way.
set -euo pipefail
cd "$(dirname "$0")/.."

parts=0
if [ "${1:-}" = "--parts" ]; then
    parts=1
    shift
fi
out="${1:?usage: scripts/release_zips.sh [--parts] OUT_DIR}"
mkdir -p "$out"
version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n 1)
name="FCC-Studio-$version"
limit=$((25 * 1024 * 1024))
image_src=$(git ls-files 'vendor/stable-diffusion-cpp/*-src-*.zip')
mapfile -t repos < <(git ls-files 'vendor/repos/*.zip')
# FCC's own big libraries (website layouts, Kenney game art, the Godot demos'
# art) get parts too.
mapfile -t libs < <(git ls-files 'src/free_claude_code/studio/site_layouts/*.zip' \
    'src/free_claude_code/studio/game_library/kenney-core-*.zip' \
    'src/free_claude_code/studio/godot/art/demo-art-*.zip')

if [ "$parts" -eq 0 ]; then
    git archive --format=zip --prefix=fcc/ -o "$out/$name.zip" HEAD -- . \
        ':!tests' ':!e2e' ':!smoke' ':!docs' ':!vendor/cua'
    ls -l "$out/$name.zip"
    exit 0
fi

git archive --format=zip --prefix=fcc/ -o "$out/$name.zip" HEAD -- . \
    ':!tests' ':!e2e' ':!smoke' ':!docs' ':!vendor/cua' \
    ':!vendor/repos/*.zip' ":!$image_src" \
    ':!src/free_claude_code/studio/site_layouts/*.zip' \
    ':!src/free_claude_code/studio/game_library/kenney-core-*.zip' \
    ':!src/free_claude_code/studio/godot/art/demo-art-*.zip'

part=2
batch=()
size=0
flush() {
    if [ "${#batch[@]}" -eq 0 ]; then return; fi
    git archive --format=zip --prefix=fcc/ -o "$out/$name-part$part.zip" HEAD -- "${batch[@]}"
    part=$((part + 1))
    batch=()
    size=0
}
for file in "${repos[@]}" "${libs[@]}"; do
    bytes=$(stat -c %s "$file")
    if [ $((size + bytes)) -gt "$limit" ]; then flush; fi
    batch+=("$file")
    size=$((size + bytes))
done
flush
batch=("$image_src")
flush

ls -l "$out/$name"*.zip
