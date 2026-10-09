# stable-diffusion.cpp (vendored)

- **Upstream:** https://github.com/leejet/stable-diffusion.cpp
- **Commit:** `228c707fde018221de74674f1c2f480a9d2b228e` (release `master-948-228c707`)
- **Licence:** MIT ([LICENSE](LICENSE)); its ggml is MIT too ([LICENSE.ggml](LICENSE.ggml))

## How FCC uses it

Studio's **Image engine** (Settings → Image engine) paints cartoon places and
characters with stable-diffusion.cpp's `sd-cli` on the user's graphics card
(`src/free_claude_code/studio/image_engine.py`). On set up, Studio downloads
the official release build for the PC (Windows/Linux: the Vulkan build, so
AMD, NVIDIA and Intel cards all work; macOS: the arm64 build), then keeps the
downloaded file in the **Repo vault** with its SHA-256, so a later install
works from the kept copy if the release or the repo is deleted.

## What is kept here

- `stable-diffusion-cpp-src-228c707.zip`: a source snapshot of everything
  `sd-cli` builds from at this commit: `CMakeLists.txt`, `cmake/`,
  `include/`, `src/`, `examples/cli`, `examples/common`, the `ggml`
  submodule (without its docs, examples and tests) and `thirdparty/`. With
  it the engine can be rebuilt (`cmake -B build -DSD_VULKAN=ON && cmake
  --build build --target sd-cli`) if every release is gone.
  Checksum in [SHA256SUMS](SHA256SUMS).
- The third-party code inside is permissively licensed: nlohmann/json (MIT),
  cpp-httplib (MIT), miniz and kuba--/zip (MIT/Unlicense), stb (public domain
  or MIT), utf8proc (MIT), darts-clone (BSD-2), libwebp and libwebm (BSD),
  oniguruma (BSD-2). Their licence files are in the zip.

## Left out, and why

- **The release builds themselves** (`sd-…-bin-win-vulkan-x64.zip` and the
  others): the session that vendored this copy could not reach GitHub's
  release downloads. The app keeps each one in the Repo vault the first time
  it downloads it, and the source above rebuilds it.
- `assets/`, `docs/` and the web server's frontend: not used by `sd-cli`.
- **The style's model files** (Pony Diffusion V6 XL GGUF, the DCAU style
  LoRA, the SDXL-Lightning LoRA; 3–5 GB): too big for the repo. Each is
  pinned to an exact Hugging Face commit and SHA-256 in `image_engine.py`
  (licences: CreativeML OpenRAIL-M and OpenRAIL++, both allow sharing with
  their use restrictions), and kept in the Repo vault after the first
  download.
