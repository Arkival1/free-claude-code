#!/usr/bin/env bash
# Build the zips the owner downloads to install or update FCC on their PC.
#
#   scripts/release_zips.sh OUT_DIR
#
# FCC-Studio-<version>.zip holds the app; the -partN zips hold the starter
# repo zips and the image engine source, each part kept under 25 MB so a
# phone can download it. Every zip unpacks into the same fcc/ folder, so the
# owner unzips them all into one place. Tests, browser tests, the GitHub
# Pages site (docs/) and vendor/cua (not used yet) are left out.
set -euo pipefail
cd "$(dirname "$0")/.."

out="${1:?usage: scripts/release_zips.sh OUT_DIR}"
mkdir -p "$out"
version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n 1)
name="FCC-Studio-$version"
limit=$((25 * 1024 * 1024))
image_src=$(git ls-files 'vendor/stable-diffusion-cpp/*-src-*.zip')
mapfile -t repos < <(git ls-files 'vendor/repos/*.zip')

git archive --format=zip --prefix=fcc/ -o "$out/$name.zip" HEAD -- . \
    ':!tests' ':!e2e' ':!smoke' ':!docs' ':!vendor/cua' \
    ':!vendor/repos/*.zip' ":!$image_src"

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
for file in "${repos[@]}"; do
    bytes=$(stat -c %s "$file")
    if [ $((size + bytes)) -gt "$limit" ]; then flush; fi
    batch+=("$file")
    size=$((size + bytes))
done
flush
batch=("$image_src")
flush

ls -l "$out/$name"*.zip
