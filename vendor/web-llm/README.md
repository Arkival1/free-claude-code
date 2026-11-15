# WebLLM (mlc-ai/web-llm), vendored

- Upstream: https://github.com/mlc-ai/web-llm
- Release: npm package `@mlc-ai/web-llm@0.2.87` (integrity
  `sha512-34N19988MdaEtzh8Mq/IOrfKCk2HRDOrXgEkLT28r3aiyAU6ZJSUB+v35t7zyU+0QEaFl91Y4U5SuPN/cwoHNw==`)
- Model programs: https://github.com/mlc-ai/binary-mlc-llm-libs,
  `web-llm-models/v0_2_87/base/` (the files WebLLM 0.2.87 pairs with)
- Licence: Apache 2.0 (see [LICENSE](LICENSE)); the model programs come from
  the same project under the same licence.

FCC Phone's second engine. WebLLM runs a model on the phone's graphics chip
through WebGPU, so the weights live in the chip's memory and not the web
page's (about 1 GB on an iPhone), which is how a 4B model fits on a phone
(Models, "Qwen3 4B (graphics chip)"; also Qwen3.5 2B and Qwen3 1.7B). `js/webgpu.js` loads it only when a
graphics-chip model is used, gives Jarvis's tools to Qwen3 in its own
`<tool_call>` format, and passes the model's temperature setting.

The files FCC Phone serves, byte for byte, in
`src/free_claude_code/api/phone_static/vendor/web-llm/`:

| Served as | From | Job |
| --- | --- | --- |
| `web-llm.js` | the npm package's `lib/index.js` (self-contained ES module) | The engine |
| `LICENSE` | the npm package's `LICENSE` | Apache 2.0 |
| `libs/Qwen3-4B-q4f16_1_cs1k-webgpu.wasm` | binary-mlc-llm-libs | Qwen3 4B's program for the graphics chip |
| `libs/Qwen2.5-3B-Instruct-q4f16_1_cs1k-webgpu.wasm` | binary-mlc-llm-libs | Qwen2.5 3B (chips with half-size numbers) |
| `libs/Qwen2.5-3B-Instruct-q4f32_1_cs1k-webgpu.wasm` | binary-mlc-llm-libs | Qwen2.5 3B (every WebGPU chip) |
| `libs/Qwen3.5-2B-q4f16_1_cs1k-webgpu.wasm` | binary-mlc-llm-libs | Qwen3.5 2B (chips with half-size numbers) |
| `libs/Qwen3.5-2B-q4f32_1_cs1k-webgpu.wasm` | binary-mlc-llm-libs | Qwen3.5 2B (every WebGPU chip) |
| `libs/Qwen3-1.7B-q4f16_1_cs1k-webgpu.wasm` | binary-mlc-llm-libs | Qwen3 1.7B (chips with half-size numbers) |
| `libs/Qwen3-1.7B-q4f32_1_cs1k-webgpu.wasm` | binary-mlc-llm-libs | Qwen3 1.7B (every WebGPU chip) |

`SHA256SUMS` lists their checksums and the npm tarball's; a test checks the
served copies still match. The programs ship with FCC, so the phone never
needs GitHub for them.

The weights (about 2.3 GB for the 4B, 1.1 GB for Qwen3.5 2B, 1 GB for the 1.7B) are not kept here:
they are Qwen3 (Apache 2.0) converted by the MLC team, and the phone fetches
them from Hugging Face once, pinned to these commits in `js/webgpu.js`:
`mlc-ai/Qwen3-4B-q4f16_1-MLC@a5c9fab855e3ccbdfed2e7e69683d75f30332161`,
`mlc-ai/Qwen2.5-3B-Instruct-q4f16_1-MLC@7690aaaa46df36b1be0fe93b9c9abac0497eff6c`,
`mlc-ai/Qwen2.5-3B-Instruct-q4f32_1-MLC@dfa91e859b714acfa489a1464297080656c3460d`,
`mlc-ai/Qwen3.5-2B-q4f16_1-MLC@dd74e9c8a20c4546df85c844103bff87b6dcacad`,
`mlc-ai/Qwen3.5-2B-q4f32_1-MLC@d835e5c41aa56174d915e8a3940cde599d3f5a30`,
`mlc-ai/Qwen3-1.7B-q4f16_1-MLC@80b3abcec6c3b3f5355dc0cc99cc4fb578f192bc`,
`mlc-ai/Qwen3-1.7B-q4f32_1-MLC@bddd4d584cabe19113f7e4ff46fd9e73b4d3dc89`.

Needs WebGPU: on by default from iOS 26; on iOS 18, Safari's Settings,
Apps, Safari, Advanced, Feature Flags, WebGPU (Safari only, not Chrome).
