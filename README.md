<div align="center">

<h1>
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="assets/free-claude-code-wordmark-light.svg">
    <img src="assets/free-claude-code-wordmark-dark.svg" alt="Free Claude Code" width="610">
  </picture>
</h1>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Python 3.14](https://img.shields.io/badge/python-3.14-3776ab.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json&style=for-the-badge)](https://github.com/astral-sh/uv)
[![Testing: Pytest](https://img.shields.io/badge/Testing-Pytest-00c0ff.svg?style=for-the-badge)](https://github.com/Alishahryar1/free-claude-code/actions/workflows/tests.yml)
[![Type checking: Ty](https://img.shields.io/badge/type%20checking-ty-ffcc00.svg?style=for-the-badge)](https://pypi.org/project/ty/)
[![Code style: Ruff](https://img.shields.io/badge/code%20formatting-ruff-f5a623.svg?style=for-the-badge)](https://github.com/astral-sh/ruff)
[![Logging: Loguru](https://img.shields.io/badge/logging-loguru-4ecdc4.svg?style=for-the-badge)](https://github.com/Delgan/loguru)

[Quick Start](#quick-start) · [Providers](#choose-a-provider) · [Studio](#studio) · [Clients](#connect-your-client) · [Integrations](#optional-integrations) · [Manage](#manage-your-installation)

</div>

<p align="center">
  <em>Independent open-source project. Not affiliated with or endorsed by Anthropic. Claude and Claude Code are trademarks of Anthropic.</em>
</p>

## What You Get

- **53 ToS-friendly providers. 1.3B+ free tokens every month.** Use free, paid, subscription, and local models from one searchable UI without putting your account at risk. FCC follows provider terms and removes integrations if they stop being allowed.
- **10 coding agents. One model catalog.** Run [Claude Code](https://code.claude.com/docs/en/overview), [Codex](https://github.com/openai/codex), [Pi](https://github.com/earendil-works/pi), [OpenCode](https://github.com/anomalyco/opencode), [Cline](https://github.com/cline/cline), [Hermes](https://github.com/NousResearch/hermes-agent), [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness), [Grok Build](https://github.com/xai-org/grok-build), [Muse Code](https://research.meta.ai/blog/introducing-muse-code-and-muse-spark-1-2/), or [Aider](https://aider.chat/) with your FCC models.
- **Keep coding through provider outages.** After retries are exhausted, FCC automatically tries your next configured model without making you restart the turn—across every client.
- **Up to 90% fewer terminal-output tokens.** Optional [RTK](https://github.com/rtk-ai/rtk) filters common command output, while five FCC optimizations handle quota probes, command-prefix detection, titles, suggestions, and filepaths without calling a provider.
- **Studio: your own agents, on your own models.** A phone-first app at `/studio` that runs agents which search the web and build real websites, downloads local models to this device, runs very light on-device tuning, gives every agent its own memory, mirrors work into Obsidian, and lets a teacher AI teach and then test a student AI in a classroom you can watch.
- **Native Code sessions in your browser.** Choose a folder and run Codex in the browser with real-time and background support. Freely switch providers/models in the same session. Support for switching harnesses in the same session coming soon!
- **Terminal, desktop, IDE, or phone.** Work through native launchers, [VS Code](https://code.visualstudio.com/), [Codex App](https://learn.chatgpt.com/docs/app), [JetBrains](https://www.jetbrains.com/), [Discord](https://discord.com/), or [Telegram](https://telegram.org/).
- **Voice notes in. Code out.** Talk to your agent using local [Whisper](https://github.com/openai/whisper) or [NVIDIA NIM](https://docs.nvidia.com/nim/speech/latest/asr/deploy-asr-models/whisper.html) transcription.
- **Agent capabilities stay intact.** Stream responses, use tools, preserve native interleaved thinking for maximum performance, send images, and route [Fable](https://www.anthropic.com/claude/fable), [Opus](https://www.anthropic.com/claude/opus), [Sonnet](https://www.anthropic.com/claude/sonnet), and [Haiku](https://www.anthropic.com/claude/haiku) independently with compatible models.

Free-tier availability and limits are controlled by each provider and may change.

<div align="center">
  <img src="assets/pic.png" alt="Claude Code running with Free Claude Code" width="700">
  <p><em>Claude Code running with FCC.</em></p>
</div>

<div align="center">
  <img src="assets/browser-code-session.png" alt="Native Codex browser session in FCC, showing model controls and a repository exploration" width="700">
  <p><em>A native Codex session in FCC's browser UI.</em></p>
</div>

## Quick Start

<a id="install"></a>

### 1. Install

macOS/Linux:

```bash
curl -fsSL "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/install.sh" | sh
```

Windows PowerShell:

```powershell
& ([scriptblock]::Create((irm "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/install.ps1")))
```

When prompted, choose at least one coding agent and optionally RTK. You can review the installers before running them: [install.sh](scripts/install.sh) and [install.ps1](scripts/install.ps1).

### 2. Start FCC

#### Windows

Open **Free Claude Code** from your desktop or Start menu.

#### macOS

Open **Free Claude Code** from your desktop or Applications folder.

#### Linux

Run:

```bash
fcc-server
```

FCC opens the Admin UI after starting. On Windows and macOS, use the tray or
menu-bar icon to open Admin, restart, or quit. When using `fcc-server`, keep its
terminal open.

<a id="nvidia-nim-provider"></a>

### 3. Configure NVIDIA NIM

1. Create an API key at [build.nvidia.com/settings/api-keys](https://build.nvidia.com/settings/api-keys).
2. Open the Admin UI URL from the server log.
3. Paste the key into `NVIDIA_NIM_API_KEY`.
4. Leave `MODEL` on the default `nvidia_nim/nvidia/nemotron-3-super-120b-a12b`, or search the model dropdown and select another model.
5. Click **Apply**.

To protect the local proxy with a bearer token, enable **Proxy Authentication**
in Admin.

<div align="center">
  <img src="assets/admin-page.png" alt="Free Claude Code Admin UI" width="700">
</div>

### 4. Run Your Coding Agent

Claude Code:

```bash
fcc-claude
```

Codex:

```bash
fcc-codex
```

Pi:

```bash
fcc-pi
```

OpenCode 2:

```bash
fcc-opencode
```

To upgrade from OpenCode 1, rerun the FCC installer with OpenCode selected. It
upgrades the native installation in `~/.opencode/bin`; for npm or other package
managers, follow [OpenCode's migration instructions](https://opencode.ai/v2/docs/migrate-v1/)
first. For npm v1, run `npm uninstall -g opencode-ai`, then rerun the FCC installer.
Close OpenCode before upgrading. OpenCode manages its own data upgrades.

RTK integration is temporarily unavailable for OpenCode 2. The installer saves
the recognized old RTK plugin outside the plugin directory; customized plugins
need manual migration. RTK continues to work with the other supported agents.

Use `fcc-opencode` for coding and sessions. Use plain `opencode` for commands
such as upgrades, service management, ACP, and MCP setup.

Cline:

```bash
fcc-cline
```

Hermes:

```bash
fcc-hermes
```

DeepSeek Harness Web:

```bash
fcc-dsh
```

Grok Build:

```bash
fcc-grok
```

Muse Code:

```bash
fcc-muse
```

Aider:

```bash
fcc-aider
```

<a id="model-picker"></a>

<div align="center">
  <img src="assets/cc-model-picker.png" alt="Claude Code model picker showing FCC models" width="700">
  <p><em>Select an FCC model from Claude Code's native <code>/model</code> picker.</em></p>
</div>

## Choose A Provider

1. Open a provider link below for its key, models, or setup instructions.
2. In the Admin UI, configure the listed setting. For OpenAI, use
   **Providers → Connected accounts** instead.
3. Search the `MODEL` dropdown and select a model. If the provider cannot list
   models, enter `<provider-id>/<exact-provider-model-id>` manually.
4. Click **Apply**.

Optional: add an ordered **Fallback Models** list under **Model Config**. It
applies to every connected client. A failed request may reach and consume usage
from more than one provider before succeeding.

<details>
<summary><strong>Provider catalog</strong></summary>

| Provider | Admin UI setting | Example `MODEL` |
| --- | --- | --- |
| [NVIDIA NIM](https://build.nvidia.com/settings/api-keys) | `NVIDIA_NIM_API_KEY` | `nvidia_nim/nvidia/nemotron-3-super-120b-a12b` |
| [OpenRouter](https://openrouter.ai/keys) | `OPENROUTER_API_KEY` | `open_router/openrouter/free` |
| [Groq](https://console.groq.com/keys) | `GROQ_API_KEY` | `groq/llama-3.3-70b-versatile` |
| [ClinePass](https://docs.cline.bot/getting-started/clinepass) | `CLINE_API_KEY` | `cline_pass/cline-pass/kimi-k3` |
| [OpenAI / ChatGPT](https://learn.chatgpt.com/docs/auth) | Connect ChatGPT in the Admin UI | `openai/<model-id>` |
| [GitHub Copilot](https://docs.github.com/en/copilot/how-tos/copilot-sdk/auth/authenticate) | Connect GitHub Copilot in the Admin UI | `github_copilot/<model-id>` |
| [xAI (Grok)](https://console.x.ai/team/default/api-keys) | `XAI_API_KEY` | `xai/grok-4.5` |
| [QwenCloud Token Plan](https://home.qwencloud.com/api-keys) | `QWENCLOUD_API_KEY` | `qwencloud/qwen3.7-plus` |
| [QwenCloud Coding Plan](https://home.qwencloud.com/api-keys) | `QWENCLOUD_CODING_API_KEY` | `qwencloud_coding/qwen3.7-plus` |
| [Together AI](https://api.together.ai/settings/api-keys) | `TOGETHER_API_KEY` | `together/zai-org/GLM-5.2` |
| [DeepInfra](https://deepinfra.com/dash/api_keys) | `DEEPINFRA_API_KEY` | `deepinfra/deepseek-ai/DeepSeek-V4-Flash` |
| [SiliconFlow](https://cloud.siliconflow.com/account/ak) | `SILICONFLOW_API_KEY` | `siliconflow/Qwen/Qwen3-32B` |
| [Nebius Token Factory](https://tokenfactory.nebius.com/project/api-keys) | `NEBIUS_API_KEY` | `nebius/Qwen/Qwen3-30B-A3B` |
| [Chutes](https://chutes.ai/docs/getting-started/authentication) | `CHUTES_API_KEY` | `chutes/Qwen/Qwen3-32B-TEE` |
| [Featherless AI](https://featherless.ai/account/api-keys) | `FEATHERLESS_API_KEY` | `featherless/Qwen/Qwen3-32B` |
| [Agnes AI](https://agnes-ai.com/) | `AGNES_API_KEY` | `agnes/agnes-2.0-flash` |
| [ZenMux](https://zenmux.ai/platform/pay-as-you-go) | `ZENMUX_API_KEY` | `zenmux/deepseek/deepseek-v4-flash-free` |
| [W&B Inference](https://wandb.ai/settings) | `WANDB_API_KEY` | `wandb/openai/gpt-oss-20b` |
| [Azure OpenAI](https://learn.microsoft.com/azure/foundry/openai/how-to/chatgpt) | `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_BASE_URL` | `azure_openai/<deployment-name>` |
| [Google AI Studio (Gemini)](https://aistudio.google.com/apikey) | `GEMINI_API_KEY` | `gemini/models/gemini-3.1-flash-lite` |
| [Google Vertex AI](https://cloud.google.com/vertex-ai/generative-ai/docs/start/openai) | `VERTEX_PROJECT_ID` + ADC | `vertex/google/gemini-3.5-flash` |
| [DeepSeek](https://platform.deepseek.com/api_keys) | `DEEPSEEK_API_KEY` | `deepseek/deepseek-chat` |
| [Mistral La Plateforme](https://console.mistral.ai/) | `MISTRAL_API_KEY` | `mistral/devstral-small-latest` |
| [Mistral Codestral](https://console.mistral.ai/) | `CODESTRAL_API_KEY` | `mistral_codestral/codestral-latest` |
| [OpenCode Zen](https://opencode.ai/auth) | `OPENCODE_API_KEY` | `opencode_zen/gpt-5.3-codex` |
| [OpenCode Go](https://opencode.ai/auth) | `OPENCODE_API_KEY` | `opencode_go/minimax-m2.7` |
| [Vercel AI Gateway](https://vercel.com/docs/ai-gateway/models-and-providers) | `AI_GATEWAY_API_KEY` | `vercel/openai/gpt-5.5` |
| [Amazon Bedrock](https://console.aws.amazon.com/bedrock/) | `AWS_BEARER_TOKEN_BEDROCK` | `bedrock/openai.gpt-oss-120b` |
| [Hugging Face Inference Providers](https://huggingface.co/settings/tokens) | `HUGGINGFACE_API_KEY` | `huggingface/Qwen/Qwen3-Coder-480B-A35B-Instruct:fastest` |
| [Cohere](https://dashboard.cohere.com/api-keys) | `COHERE_API_KEY` | `cohere/command-a-plus-05-2026` |
| [Wafer](https://wafer.ai/) | `WAFER_API_KEY` | `wafer/DeepSeek-V4-Pro` |
| [Kimi API](https://platform.moonshot.ai/console/api-keys) | `KIMI_API_KEY` | `kimi/kimi-k2.5` |
| [Kimi Code](https://www.kimi.com/code/console) | `KIMI_CODE_API_KEY` | `kimi_code/k3` |
| [MiniMax](https://platform.minimax.io/user-center/basic-information/interface-key) | `MINIMAX_API_KEY` | `minimax/MiniMax-M3` |
| [Cerebras Inference](https://cloud.cerebras.ai/) | `CEREBRAS_API_KEY` | `cerebras/gpt-oss-120b` |
| [SambaNova](https://cloud.sambanova.ai/apis) | `SAMBANOVA_API_KEY` | `sambanova/Meta-Llama-3.3-70B-Instruct` |
| [Kilo.ai](https://kilo.ai) | `KILO_API_KEY` | `kilo/kilo-auto/free` |
| [Fireworks AI](https://fireworks.ai/account/api-keys) | `FIREWORKS_API_KEY` | `fireworks/accounts/fireworks/models/llama-v3p3-70b-instruct` |
| [Novita AI](https://novita.ai/settings/key-management) | `NOVITA_API_KEY` | `novita/deepseek/deepseek-v4-flash-0731` |
| [Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/) | `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` | `cloudflare/@cf/moonshotai/kimi-k2.6` |
| [Z.ai Coding Plan](https://z.ai/manage-apikey/apikey-list) | `ZAI_API_KEY` | `zai/glm-5.2` |
| [Z.ai API (pay as you go)](https://z.ai/manage-apikey/apikey-list) | `ZAI_API_KEY` | `zai_api/glm-4.7-flash` |
| [TokenRouter](https://www.tokenrouter.com/) | `TOKENROUTER_API_KEY` | `tokenrouter/moonshotai/kimi-k3-free` |
| [NaraRoute](https://router.bynara.id/) | `NARAROUTE_API_KEY` | `nararoute/kimi-k3-free` |
| [Poolside AI](https://platform.poolside.ai/) | `POOLSIDE_API_KEY` | `poolside/poolside/laguna-s-2.1` |
| [LLM7.io](https://dash.llm7.io/) | `LLM7_API_KEY` | `llm7/default` |
| [Scaleway](https://console.scaleway.com/iam/api-keys) | `SCW_SECRET_KEY` | `scaleway/deepseek/deepseek-v4-flash` |
| [Lightning AI](https://lightning.ai/) | `LIGHTNING_API_KEY` | `lightning/lightning-ai/Qwen3.8-27B` |
| [Experiential Labs](https://platform.experientiallabs.ai/) | `EXPLABS_API_KEY` | `experiential/union-alpha` |
| [Ollama Cloud](https://ollama.com/settings/keys) | `OLLAMA_API_KEY` | `ollama_cloud/qwen3-coder:480b` |
| [LM Studio](https://lmstudio.ai/) | `LM_STUDIO_BASE_URL` | `lmstudio/<model-id>` |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | `LLAMACPP_BASE_URL` | `llamacpp/<model-id>` |
| [Ollama](https://ollama.com/) | `OLLAMA_BASE_URL` | `ollama/<model-tag>` |

</details>

<details>
<summary><strong>Provider-specific setup</strong></summary>

- OpenAI uses your ChatGPT subscription rather than an API key. Connect from
  **Providers → OAuth providers → OpenAI / ChatGPT → Connect** in the Admin UI
  and finish signing in through your browser. Restart an already-running agent after connecting.
- GitHub Copilot uses your signed-in GitHub account and subscription. Install
  [Copilot CLI 1.0.83](https://github.com/github/copilot-cli/releases/tag/v1.0.83)
  on PATH, then choose **Providers → OAuth providers → GitHub Copilot → Connect**.
  FCC reuses the native profile or shows a GitHub device code when sign-in is needed.
  You can also sign in first with `copilot login --device-code`. Select a concrete
  `github_copilot/<model-id>` from the discovered list; available models and quotas
  depend on your subscription and organization policies. Restart an already-running
  agent after connecting. Disconnect stops FCC use and leaves the native login intact.
  FCC pins its SDK and CLI compatibility because direct endpoint access is experimental.
- Azure OpenAI uses the deployment names from your resource. Set
  `AZURE_OPENAI_BASE_URL` to its complete v1 endpoint, such as
  `https://YOUR-RESOURCE-NAME.openai.azure.com/openai/v1/`, and select a
  deployment that supports Chat Completions. Enter the deployment name as a
  custom model slug if it does not appear in the model dropdown.
- Mistral Codestral uses a separate key from Mistral La Plateforme.
- Kimi Code subscription keys use `kimi_code/`; Kimi API credit keys use
  `kimi/`. Kimi Code plans are for personal interactive coding-agent use under
  [Kimi's community guidelines](https://www.kimi.com/code/docs/en/kimi-code/community-guidelines.html).
- QwenCloud Coding Plan keys use `qwencloud_coding/`; QwenCloud Token Plan keys
  use `qwencloud/`. The keys and endpoints are not interchangeable. Coding Plan
  is for local, personal, interactive coding-agent use under the
  [Coding Plan terms](https://www.alibabacloud.com/help/en/model-studio/coding-plan).
- OpenCode Zen and OpenCode Go share `OPENCODE_API_KEY` but use the explicit
  `opencode_zen/` and `opencode_go/` model prefixes.
- For Amazon Bedrock, set `BEDROCK_BASE_URL` to the URL for the same region as
  the API key and select one of the listed models.
- Vertex AI uses Google Application Default Credentials instead of an API key.
  Locally, run `gcloud auth application-default login` once; service-account
  files and attached service accounts also work. Set `VERTEX_PROJECT_ID`, and
  optionally change `VERTEX_LOCATION` from its `global` default.
- Cloudflare requires both its API token and account ID.
- For Ollama Cloud, use the exact model IDs shown in the model picker. Local
  Ollama uses the separate `ollama/` prefix.
- Prefer tool-capable models for coding agents. Local models also need enough context for the agent's system prompt and tool definitions.

</details>

<details>
<summary><strong>Local provider setup</strong></summary>

### LM Studio

Start LM Studio's local server, load a tool-capable model, and use the model identifier shown by LM Studio with the `lmstudio/` prefix. The default URL is `http://localhost:1234/v1`.

### llama.cpp

Start `llama-server` with its OpenAI-compatible Chat Completions API and enough context for the model. Use the local model ID with the `llamacpp/` prefix. `LLAMACPP_BASE_URL` defaults to `http://localhost:8080/v1`; FCC accepts either the server root or an explicit `/v1` suffix.

### Ollama

```bash
ollama pull llama3.1
ollama serve
```

Use the tag shown by `ollama list` with the `ollama/` prefix. `OLLAMA_BASE_URL` defaults to `http://localhost:11434`; FCC accepts either the root URL or an explicit `/v1` suffix.

</details>

<details>
<summary><strong>Optional model-tier routing</strong></summary>

`MODEL` is the fallback for every request. Select a model for `MODEL_FABLE`, `MODEL_OPUS`, `MODEL_SONNET`, or `MODEL_HAIKU` to override an individual Claude Code tier; select **None** to use `MODEL`.

For example, route Opus to `nvidia_nim/nvidia/nemotron-3-super-120b-a12b`, Sonnet to `open_router/openrouter/free`, Haiku to `lmstudio/qwen3.5-coder`, and keep `MODEL` on `zai/glm-5.2`.

</details>

<details>
<summary><strong>Reasoning control</strong></summary>

Open **Admin UI → Model Config → Reasoning** and select the behavior you want.

| Selection | Behavior |
| --- | --- |
| **From client** (default) | Use the effort sent by Claude Code, Codex, Pi, OpenCode, Cline, Hermes, DeepSeek Harness, Grok Build, Muse Code, or Aider. If none is sent, keep the provider default. |
| **Off** | Request reasoning to be disabled. |
| **Low**, **Medium**, **High**, **X-High**, or **Max** | Override the client with the selected reasoning level. |
| **Inherit** (Fable, Opus, Sonnet, and Haiku only) | Use the root Reasoning selection. |

Providers that do not support a selected control retain their own behavior.

</details>

<a id="studio"></a>

## Studio

Studio is an app served by the same local server: open
`http://<server-host>:8082/studio` in a browser. It is built phone-first — on
iOS, open it in Safari, tap **Share → Add to Home Screen**, and it runs full
screen with its own icon, safe-area padding, and touch-sized controls. Turn the
whole app off with `STUDIO_ENABLED=false`.

Everything Studio stores lives under `~/.fcc/studio/`: `studio.db` for agents,
chats, memory, tuning, and classes; `models/` for downloaded model files; and
`sites/` for websites agents build.

<details>
<summary><strong>Studio as a desktop app on Windows</strong></summary>

1. Download this branch as a zip and extract it, for example to `C:\fcc`.
2. Open `scripts\windows` and double-click **install-studio-app.cmd** once.
   It installs uv, Python 3.14, the app's packages, and the main AI's voice
   (a few minutes the first time), then adds an **FCC Studio** icon to your
   Desktop and Start menu and opens the app. Add `-StartWithWindows` from
   PowerShell to open it when you sign in; `-Uninstall` removes the icons.
3. From then on, double-click **FCC Studio**. A small "Waking Jarvis up"
   window shows while the server starts in the background (no black console
   window), then Studio opens in its own app window with its own taskbar
   icon, using Microsoft Edge (or Chrome) without tabs or an address bar.
   Closing the window stops the server. Run `studio-app.ps1 -KeepServer` to
   leave it running for your phone.
4. Every Free Claude Code setting is inside the app: **Settings** in the left
   menu (or **More → Open settings**) shows the full settings page, with its
   search box. Settings only open on the PC running Studio.

Server logs are in `%LOCALAPPDATA%\FCC Studio\logs` if the app will not start.

**Replies as they are written.** With a local model, the HUD shows the main
AI's reply word by word while LM Studio writes it, and **Agents at work**
shows the watched agent's reply the same way. The HUD checks for news twice a
second while anyone is working and every few seconds otherwise; the CPU and
memory gauges and the mission list are only rebuilt when something changed.
On phones and PCs with four or fewer processor cores, the gold core draws
fewer particles at 30 frames a second so the processor stays free for the AI.

</details>

<details>
<summary><strong>Running Studio on Windows, step by step</strong></summary>

1. Get the code: download this branch as a zip and extract it, or run
   `git clone` in PowerShell. Put it somewhere without spaces if you can,
   such as `C:\fcc`.
2. Open the folder, then `scripts\windows`, and double-click
   **start-studio.cmd**. The first run installs [uv](https://docs.astral.sh/uv/)
   if it is missing, lets uv install Python 3.14 for you, and installs the
   app's packages into the folder. That takes a few minutes once; later starts
   take seconds. You do not need to install Python yourself.
3. Your browser opens `http://localhost:8082/studio`. Leave the black window
   open — it is the server. Press Ctrl+C in it to stop.
4. Open `http://localhost:8082/admin` on the same PC to add a provider key or
   point **Local Model Server** at LM Studio, `llama-server`, or Ollama.
5. When Windows Firewall asks, allow Python on **Private networks** only. Your
   phone can then open the address listed under **More → Install on your
   iPhone**.

From PowerShell you can pass options instead:
`.\scripts\windows\start-studio.ps1 -Port 9000 -NoBrowser`. Add
`-WithTraining` to also install PyTorch, transformers, and PEFT so this PC can
train LoRA adapters (a few GB; an NVIDIA GPU is strongly advised). Add
`-DryRun` to see every step without running it. If PowerShell refuses to run scripts,
the `.cmd` file above already bypasses that for this one script.

</details>

<details>
<summary><strong>The HUD and your main AI</strong></summary>

Home is a command center for your main AI (named **Jarvis** by default,
`STUDIO_MAIN_AGENT_NAME`), and every other page (Agents, Chats, Classroom,
Models, Tuning, More) uses the same dark console look. **More** has a search
box for its settings, and the admin page has one search box that looks
through every settings page at once.

In the middle of the HUD is his core: a gold sphere of glowing particles and
filaments that floats, turns, and reacts. It swirls while he works, swells
with your voice while he listens, pulses as he speaks, and dims if the link to
the server drops. Tap it to start a spoken conversation. Around it:

- **Agent chat room** (top right): the latest team room. Start one with
  **START TEAM ROOM**, then talk to all the agents at once.
- **AI core overview** and **brain status**: which model he runs on, whether
  your local models are reachable, web search, voice, and ears.
- **Agents at work** (bottom left): every agent with a READY or ACTIVE light.
  Tap one to watch it work live: its task, each tool it uses (searches, files,
  commands), what it is thinking, and its report. The first agent that starts
  working is shown until you pick one; **OPEN ›** opens its full chat. Tap
  **+** to add an agent.
- **Mission timeline** (tasks, rooms, classes, and training) and the **live
  intelligence feed** (running jobs and commands waiting for **Run it**).
- **Quick commands**: voice chat, an executive briefing, and shortcuts to give
  Builder, Researcher, or Helper a job.
- **System monitor** (CPU, RAM, and disk of the PC running Studio) and
  **memory insights**.
- The sidebar goes to the rest of Studio; **ASK THE GUIDE** explains anything.

On an iPhone the same panels stack into one column, with the talk bar pinned
to the bottom of the screen.

**Choosing his brain.** Press **CHOOSE BRAIN** (or the **Choose brain** quick
command, or **Choose a model from this PC** on the Models page). It lists the
models LM Studio has on this PC; press **Use** on one. **Find a model file on
this PC…** opens a normal file window on the PC running Studio: pick any
`.gguf` model and Studio adds it to LM Studio's models folder (a hard link, so
no second copy on the same drive) and switches to it. Leave **Use it for every
agent too** ticked to move the whole team, or untick it for the main AI only.
The choice is saved as the Main AI Model and Studio Default Model settings.

If the Studio default is a server model whose provider has no key, or a local
model this PC doesn't have, Studio uses the model loaded in LM Studio instead
of failing, and the HUD shows which one.

**Speed on a small GPU.** Studio keeps the start of every prompt the same
between turns (tool list and instructions first, this turn's memories last),
so LM Studio reuses what it already read instead of re-reading thousands of
words before each reply. **Fast Local Replies** (`STUDIO_LOCAL_FAST_REPLIES`,
on by default) also switches off the hidden "thinking" pass that reasoning
models such as Qwen3 write before every answer; turn it off for hard problems.
In LM Studio, load the model with GPU Offload at maximum and a Context Length
of 8192; a larger context can spill out of an 8 GB card and slow every reply.

More speed-ups that keep answers and memory exactly the same:

- **Memory on the message.** What memory recalls for a message is attached to
  that message instead of the instructions, so the instructions and the whole
  earlier conversation stay word-for-word the same and LM Studio reuses them
  instead of re-reading them. Every memory still reaches the agent.
- **Look-ups together.** Agents may ask for several tools in one reply; web
  searches, page reads, file reads, recall, research, and questions to the
  Researcher or Helper then run at the same time. Anything that changes files
  or runs commands still runs one at a time, in order.
- **He talks while he writes.** The main AI starts speaking his first finished
  sentence while the rest of the reply is still being written, instead of
  waiting for the whole answer.
- **No waiting on the notes.** When memory is mirrored into Obsidian, that
  happens in the background after an agent's reply, not before it counts as
  done. Memory itself is saved first, as before.
- **Agent Temperature** (`STUDIO_AGENT_TEMPERATURE`, default 0.2) sets how much
  agents vary their wording; low values keep tool use steady.

You talk to the main AI in the HUD by typing or with the mic button (when the
browser supports speech recognition), and it can read its replies aloud
(**VOICE ON/OFF**). It answers simple questions itself and runs the rest of
the team:

- `ask_agent` gives one agent a task and waits for its report, for example
  "Have Builder make a landing page for my bakery". Build work lands in a
  project; the main AI names one, and Studio creates it when it doesn't exist.
- `team_task` puts several agents in a room to work on one goal together.

The HUD shows which agents are working, recent jobs, commands waiting for
**Run it**, and the team's shared memory. Tap a hand-off to open that agent's
own chat. Only the main AI can hand work off, so agents can't start loops of
delegation. Give it a local model to keep everything on your machine:
`STUDIO_MAIN_AGENT_MODEL=local/qwen2.5-coder:7b`. Without that setting it uses
the Studio default model.

**His voice.** The main AI talks and listens on your PC with no server and no
internet: speech is Kokoro, a small neural voice (the default `jarvis` voice
blends two of its British men, with a subtle "AI in the room" effect), and
your voice is understood by Whisper. Both run on the CPU. The Windows launcher
installs them (`-NoVoice` skips it; elsewhere use `--extra studio_voice`), and
the HUD downloads the model files once (about 500 MB), after which they work
offline. Tap the orb or **TALK** for a spoken conversation: you speak, he
answers out loud, then he listens again until you press **END TALK**. The ● button sends one spoken message.
**More → Main AI voice** has a **Hear him** button and the download status.
Voice settings are under admin → Studio: engine, voice (`jarvis`,
`bm_george`, `bm_lewis`, `bm_daniel`, `bm_fable`, and others), effect, speed,
and the speech-recognition size. A voice server (Kokoro-FastAPI, Speaches,
whisper.cpp's server, or OpenAI) can be used instead of the built-in engine.

Browsers only share the microphone with secure pages. On the PC,
`http://localhost:8082/studio` counts as secure. On an iPhone, use HTTPS:
install Tailscale on both devices and run `tailscale serve --bg 8082` on the
PC, then open the `https://…ts.net/studio` address it prints.

**Shared memory.** With `STUDIO_SHARED_MEMORY` on (the default), every agent's
`remember` goes into one team memory that all agents recall from, tagged with
who wrote it, unless the agent marks it `private`. Finished tasks and room
outcomes go there too, so the main AI and the team build on each other's work.
Each agent still keeps its own working notes. You can add to it from the HUD,
and it mirrors into Obsidian as a **Team memory** hub.

</details>

<details>
<summary><strong>Agents that search the web and build sites</strong></summary>

An agent is a name, a model, a set of tools, its own memory, and optionally its
own tune pack. Agents call `web_search`, `web_fetch`, `write_file`,
`read_file`, `list_files`, `remember`, `recall`, and `finish`; web tools reuse
FCC's existing local `web_search`/`web_fetch` implementation and its SSRF
guard.

Give an agent a goal on the **Agents** tab and it runs a bounded tool loop —
`STUDIO_AGENT_MAX_STEPS` caps it — inside a **project**: a folder that can hold
a whole website or app (HTML, CSS, JavaScript/TypeScript, Python, configs, and
more), previewed live and downloadable as a zip. Writes are sandboxed: no path
traversal, text source files only, a 512 KB per-file cap, and a file-count cap;
`node_modules`, `.git`, virtualenvs, and caches are never listed or zipped.

**Commands.** With `STUDIO_AGENT_COMMANDS` set to `ask` or `auto`, agents also
get `run_command` to install packages, build, and run tests or scripts inside
the project folder. In `ask` mode every command appears in the chat (and on
Home) with **Run it** and **Deny**, and the agent waits for your answer. Commands
run on this computer with your permissions, but with any environment variable
that looks like a credential removed, a time limit (`STUDIO_COMMAND_TIMEOUT`),
and the whole process tree stopped when it expires. It is off by default.
Rooms can be given a project too, so a team of agents builds in one folder.

**Giving Jarvis orders.** When you tell Jarvis to have an agent do something,
Studio hands the job out the moment you say it, before Jarvis even answers, so
an order never depends on the model choosing to call a tool. It understands
"have Builder make a timer app", "tell the Researcher to look into cheap GPUs",
"ask Helper to plan my week", "I need Builder to fix the menu", "@Researcher
compare phones", "Builder, fix the menu", "let the Researcher know I like short
answers", and "get an agent to …" (Jarvis picks who: the Builder for making
things, the Researcher for finding out, the Helper for plans). Several orders
in one message all start, each agent works in the background and reports back
in Jarvis's conversation, and Jarvis just confirms who is doing what. "Stop
Builder" (or "tell the Builder to stop") stops its background work. Jarvis
won't hand the same job out twice.

Jarvis also has `team_status` (what every agent is doing and last finished,
with results) and `stop_agent`, and plans bigger goals by splitting them into
parts for the right agents, running independent parts at the same time. Ask
"what is everyone doing?" any time.

**Jarvis's own tools.** Besides running the team, Jarvis has:

- `todo`: your to-do list and reminders. "Add milk to my list", "remind me to
  call Sam in 20 minutes", "what's on my list?", "tick off milk". Reminder
  times can be "in 20 minutes", "tomorrow 9am", "at 17:30", "tonight", or
  "2026-10-01 14:00". A due reminder is announced on the HUD (spoken when his
  voice is on). **Knowledge & Memory → To-dos and reminders** shows the list,
  adds items with an optional reminder, and ticks them off.
- `calculate`: exact arithmetic (+ - * / // % **, brackets, "15% of 80",
  sqrt, round, min, max, log), so sums are never guessed. Only plain maths is
  evaluated.
- `list_projects`: finds your projects with their file counts, when they
  changed, and preview links.
- `system_status`: CPU, memory, and disk use, whether LM Studio is running and
  what it serves, the internet connection, and the voice.
- The date and time ride on every message, so "remind me at 5" and "what day
  is it?" work.

**The Helper** plans in a fixed shape: *Best approach*, numbered *Steps*,
*Check* (what to test and how to tell it worked), and *Backup*. Ask it to
review work and it reads the files, runs `check_project`, and lists what to
fix, most important first. It plans your own things too (a week, a trip, a
budget) with `calculate` for every sum, and adds items to your to-do list when
you ask. Starter Helpers whose instructions were never edited are upgraded in
place.

The first run creates the main AI (**Jarvis**) and six starter agents:
**Guide**, **Builder**, **Researcher**, **Helper**, **Teacher**, and
**Student**.

</details>

<details>
<summary><strong>The Guide: ask anything about the app</strong></summary>

Open the Guide with **ASK THE GUIDE** on the HUD, the **?** button at the top,
the **?** key, or by tapping **SYSTEM STATUS** when it is not OPTIMAL. It
knows every page and button: what each feature does and exactly where to tap,
from setting up LM Studio to teaching an agent a skill.

- **What is wrong right now.** The sheet opens with a live check of this
  install: LM Studio unreachable or with no model loaded, a model with no API
  key, a failed reply, commands waiting for approval, the PC offline, a search
  key problem, or the voice not downloaded. Each has its fix and an **Open**
  button for the right page.
- **Answers that take you there.** Every answer ends with **Open** buttons for
  the pages it mentions and a few follow-up questions to tap. **Where
  everything is** lists every feature with its location.
- **Uses the model already running.** The Guide answers in its own words with
  its small guide model, or, when that is not downloaded, with the model LM
  Studio has loaded. With no model at all it answers from built-in help. It
  gets only the notes that match the question plus a one-line index of the
  whole app, so a small local model reads it quickly.
- **Jarvis knows too.** Jarvis has an `app_help` tool that returns the same
  notes and live problems, so "how do I…" and "why isn't … working" questions
  asked on the HUD get the real button and page names.

</details>

<details>
<summary><strong>Internet access for every agent</strong></summary>

Every agent can search the web and read pages, including agents running on
local models: Studio does the browsing and gives the model the results.
`STUDIO_WEB_ACCESS` sets who may: `all` (the default), `listed` (only agents
with `web_search`/`web_fetch` in their tools), or `off`.

Web tools follow the connection of the PC running Studio (your phone is only
the screen). Studio checks for internet about once a minute. While the PC is
offline, agents don't get `web_search`, `web_fetch`, or `research`, and they
are told to work from memory and the project files instead. If a web tool
fails to connect partway through, the tools are paused straight away. They come
back on their own within about 15 seconds of the connection returning. The HUD
shows **WEB OFFLINE** while this is happening.

Without a key, searches go to DuckDuckGo. It often blocks automated searches,
so Studio retries once and then falls back to Wikipedia's search. For reliable
full-web search, add a key in **admin → Studio → Web Search API Key**:

| Service | Key looks like | Notes |
| --- | --- | --- |
| [Brave Search API](https://brave.com/search/api/) | `BSA…` | Free tier, independent index |
| [Tavily](https://tavily.com/) | `tvly-…` | Free tier, returns page extracts built for AI research |
| [Serper](https://serper.dev/) | 40 hex characters | Google results, free trial credits |
| [SearXNG](https://docs.searxng.org/) | no key | Self-hosted and free: set `STUDIO_SEARCH_BASE_URL` and enable its `json` format |

`STUDIO_SEARCH_PROVIDER=auto` (the default) picks the service from the key. If
the service rejects the key or runs out of quota, the search falls back to
DuckDuckGo and the agent is told why. **More → Internet access** shows the setup
and has a **Test search** button. The HUD shows the service as a `WEB` pill.

A **Researcher** agent is created for deep research: it searches, reads the
best sources, answers with links, and saves what it finds to shared memory.
Ask the main AI to send it, or write `@Researcher` in a room.

**More platforms.** `web_fetch` reads Reddit threads (post plus top comments)
and YouTube videos (title, description, and transcript when the video has
captions). Two optional credentials make these reliable:

- **YouTube API Key** (`STUDIO_YOUTUBE_API_KEY`, from Google Cloud, YouTube
  Data API v3) is optional: research searches YouTube through the API with it,
  and through YouTube's own search page without it. Transcripts come from the
  video page, or from YouTube's player API when the page is behind a consent
  or bot check.
- **Reddit App ID and Secret** (`STUDIO_REDDIT_CLIENT_ID`,
  `STUDIO_REDDIT_CLIENT_SECRET`): create a free *script* app at
  reddit.com/prefs/apps. Research then reads Reddit through its official API,
  since Reddit often blocks unauthenticated requests.

For Google results, use a Serper key as the Web Search API Key.

</details>

<details>
<summary><strong>Deep research, testing what it finds, and the Builder asking for help</strong></summary>

The `research` tool answers a question from at least ten sources
(`STUDIO_RESEARCH_SOURCES`, 3 to 25), and every run brings back a fixed mix
with links:

| Kind | Default | Setting | What counts |
| --- | --- | --- | --- |
| Web pages | 3 | `STUDIO_RESEARCH_WEB` | The most on-topic results, read in full |
| Reddit threads | 2 | `STUDIO_RESEARCH_REDDIT` | On topic (at least half the question's key words), with real replies or votes; NSFW, removed, and silent threads are skipped, and the most upvoted and discussed come first |
| YouTube videos | 2 | `STUDIO_RESEARCH_YOUTUBE` | On topic, not Shorts, and only if the transcript could be read |

Ask for a different mix any time ("research this with no YouTube", "get me 4
Reddit threads") and the agent passes that to the tool for that question. If
fewer good threads or videos exist, the report says so instead of filling in
off-topic ones. Coding questions also search Stack Overflow, GitHub, MDN, and
dev.to; everyday questions don't. The rest of the sources come from each
platform in turn so no single site dominates, with more angles tried if it is
still short. The report groups sources under Web, Reddit, and YouTube, with
each thread's score and comment count and whether a transcript was read, and
numbers them `[1]`, `[2]`, and so on so the agent can cite them. The
Researcher answers with a short answer, the findings, what Reddit and the
videos add, and a list of every link it used.

**Video notes.** Every YouTube video research reads, and every video you give
Studio, is turned into notes the agents can work from: a summary, key points,
the steps in order, the tools and names it mentions, and its warnings, written
by the Researcher's model from the transcript (long videos are read in parts).
The full transcript is kept with its times. Each video also goes into the
team's memory as a short entry with its link and notes id, so any agent's
recall finds it. Agents use two tools:

- `study_video` (Researcher and Jarvis): give it a link and, optionally, what
  the team should learn from it. Give Jarvis or the Researcher a YouTube link
  in chat and they study it.
- `video_notes` (every starter agent): search the studied videos; it returns
  the best match's notes and the exact transcript parts about the question,
  each with a link that starts the video at that moment.

In the app, **Knowledge & Memory → Video notes** has a box to paste a link
(plus an optional focus) and lists every studied video; open one to read its
notes, search the transcript, jump to any moment, or forget it. Research
studies its videos in the background, one at a time, so it never waits on
them; with no model running, notes are built from the transcript's most
telling sentences instead.

The **Researcher** tests code before recommending it: `test_code` saves a
snippet in its **Research lab** project and runs it (Python or JavaScript), then
reports PASSED or FAILED. Findings go into team memory tagged `verified` or
`unverified`. Running code follows `STUDIO_AGENT_COMMANDS`: with `ask`, each
run waits for your **Run it**.

The **Builder** builds websites, apps, and games on its own, with coding tools
like a coding assistant's: `read_file` with line numbers and ranges,
`edit_file` to change exact text without rewriting the file, `search_files` to
find text across the project (regular expressions, file patterns), `list_files`
with patterns such as `src/**/*.js`, `run_command` and `test_code` to run and
test, `update_plan` to keep a checklist of its steps, and `check_project` to
check the whole project without running it: links, images, scripts, and
stylesheets that point at missing files, `#anchors` with no matching id,
unbalanced brackets in JavaScript and CSS, Python syntax errors, invalid JSON,
and pages missing a title, a mobile viewport, or image alt text. When the
Builder says it is finished after changing files, Studio runs the check first
and sends it back once to fix anything found. The tools are the
same whether the Builder runs on a local model or a server one; only the
internet tools need a connection. When it hits an error it can't fix quickly,
it calls `ask_researcher` with the exact error. The Researcher looks it up,
tests the fix, and answers, and the Builder applies the fix and tests again.
Both conversations are visible as linked chats.

**Builder upgrades.**

- **Starter templates.** `start_project` begins a new project from a tested,
  mobile-first starter instead of a blank page: `website` (sections, phone
  menu, contact form), `landing` (hero, features, testimonial, pricing,
  signup), `webapp` (single-page app with saved state), `game` (canvas game
  loop, score, best score, touch controls), `python-tool` (command line with a
  test), `python-web` (FastAPI API with a page), and `node-api` (Node server
  with no dependencies). Every template passes `check_project`. It only
  replaces a new project's placeholder files, never real work, unless told to.
- **Undo.** Every write, edit, and delete keeps the file's last ten versions
  (in a hidden `.studio-history` folder that is never listed or zipped).
  `restore_file` lists them or puts one back, and the replaced version is kept
  too. Say "Builder, undo your last change to index.html".
- **Better edits.** `edit_file` takes several changes to one file at once
  (`edits`), saves nothing if any of them fails, and still applies a change
  whose `old_text` only differs in indentation, re-indented to match the file.
- **Knows the project.** At the start of every job the Builder sees the
  project's files and the start of its README, so it builds on what is there.
- **Real JavaScript checks.** When Node is installed, `check_project` has Node
  parse each script (without running it) and reports the exact line of a
  syntax error.
- **More room.** Builders get `STUDIO_BUILDER_MAX_STEPS` steps per job (40 by
  default) instead of the general 12, so whole apps fit in one job.
- **No going in circles.** When the same tool call fails twice, the agent is
  told to stop repeating it and try another way or ask the Researcher.
- New instructions: start from a template, finished code only, graphics with
  inline SVG, CSS, or emoji, several edits at once, undo when a change makes
  things worse. Starter Builders whose instructions were never edited are
  upgraded in place.

The **Helper** supports the other agents. When the Researcher finishes, the
Helper reads what it found alongside what the asking agent is working on, drops
what doesn't matter, and turns the rest into a short plan: the best idea to try
first, a backup, and what to test. The asking agent gets both the findings and
the plan (`STUDIO_HELPER_PIPELINE` turns this off). Any agent can also call
`ask_helper` directly to brainstorm or get unstuck, and the main AI can send
the Helper work like any other agent.

The main AI can hand work off with `background: true`, so the Builder keeps
working while you talk. When it finishes, the main AI's conversation gets a
note saying how it went.

</details>

<details>
<summary><strong>Adding agents and teaching them skills</strong></summary>

Tap **+** on the Agents tab, or in the HUD's Active agents panel, to add an
agent. Start from a preset (Builder, Researcher, Helper, Designer, Tester,
Assistant, or Custom), then set its name, role, and model, and choose its
tools: Internet, Code and files, Run and test code, Ask teammates, and Memory.

Each agent's page has **Teach a skill**. Paste a link (a docs page, a Reddit
thread, or a YouTube video) or write notes about a tool, command, or code
pattern. The agent reads it, keeps a short how-to, and sees your skills in
every prompt, so the Builder follows the tools and patterns you taught it.

</details>

<details>
<summary><strong>Agent rooms: agents talking to each other</strong></summary>

A room is a group chat between you and several agents — mix server and local
models freely. Write to the room and everyone answers in turn; write `@Name`
to address one agent. Agents hand work to each other the same way: an agent
that mentions `@Scout` passes the turn to Scout.

**Start task** gives the room a goal. The first member leads: it plans, hands
parts off, and the room keeps going until an agent replies `TASK COMPLETE:`
with a summary. A room pauses after eight turns so agents cannot loop forever
(press **Continue** to let them carry on) and **Stop** halts it after the turn
in progress. Every agent keeps working notes of what it said, and a finished
task goes into the team's shared memory (or into each member's long-term memory
when shared memory is off).

</details>

<details>
<summary><strong>Local models you download and own</strong></summary>

The **Models** tab lists curated small models (0.36B to 7B GGUF builds) and
accepts any direct `http(s)` URL. Downloads resume from a partial file, report
live progress, verify an optional SHA-256, and unpack `.zip`/`.tar*` archives —
refusing archive members that escape the destination. **Scan folder** adopts
model files you copied in by hand.

Point `STUDIO_LOCAL_BASE_URL` at whatever serves those files (LM Studio,
`llama-server`, Ollama's OpenAI endpoint), then write an agent's model as
`local/<model id>`. Every other model reference goes through the FCC proxy, so
Studio agents can use all of FCC's providers and its fallback chain. Small
local models that cannot call tools natively are driven through a text tool
protocol instead.

</details>

<details>
<summary><strong>The built-in guide</strong></summary>

The **?** button opens the guide: a small preloaded model instructed on how
this app works. It answers from a knowledge base of what Studio actually does
and points at the right tab. Before you have downloaded anything it still
answers, from that same knowledge base, so the app explains itself on a fresh
install. `STUDIO_GUIDE_MODEL` selects the model and
`STUDIO_GUIDE_CATALOG_ID` the file fetched when it is missing.

</details>

<details>
<summary><strong>Tuning: local or on the server</strong></summary>

Every tune pack has two buttons, and you pick per run.

**Tune locally** is deliberately small: it searches for the shortest
instruction pack — a preamble, up to five rules, and the clearest few
exemplars — and scores each candidate with token-F1 against held-out pairs your
examples are split into. That is a handful of short calls per run
(`STUDIO_TUNING_ROUNDS`, default 3), and it reports its baseline score, its
tuned score, and live progress. It changes no weights, so it works for any
model, including local ones. Give the pack a **coach model** and a server model
writes the candidate packs while your local model is the one scored — the
server teaching the local model.

**Tune on server** sends the same examples to an OpenAI-compatible fine-tuning
API (`STUDIO_CLOUD_TUNING_BASE_URL`, `STUDIO_CLOUD_TUNING_API_KEY`) for real
weight training, polls until it finishes, and — when
`STUDIO_CLOUD_TUNING_PROVIDER` names the FCC provider that serves the result —
switches the agent to the tuned model. Server tuning trains server models; an
agent on a local model gets a clear refusal pointing it at local tuning.

Local tuning is off until `STUDIO_LIGHT_TUNING_ENABLED` is on, or until you
turn it on for one agent: a chat's settings sheet has a **Very light tuning**
toggle, and switching it on opens a fresh chat bound to that agent's tune pack
and allows that pack to run.

</details>

<details>
<summary><strong>LoRA: training the weights</strong></summary>

**LoRA training** on the Tuning tab changes a student model's real weights.
Pick the student, a Hugging Face model to train (curated choices, from Qwen2.5
Coder 7B down to a 0.5B model that trains on a plain CPU, each paired with the
Ollama build of the same weights), and what to learn from:

- **Topics** — a server teacher writes realistic requests on each topic and
  the ideal answer to each, so the student learns from the teacher's output.
- **Tool-use lessons** — the teacher writes requests and the exact tool call
  for each, in the format Studio's local models use.
- **Classes** and **tune-pack examples** the student already has.

Then choose where to train:

- **This computer** runs the trainer as a child process: with a GPU it's fast,
  with 4-bit loading when `bitsandbytes` is installed. Install the libraries
  with the `lora` extra (`uv sync --extra lora`, or `-WithTraining` on Windows),
  or point `STUDIO_LORA_PYTHON` at any Python that has them.
- **Rented GPU or VPS**: the job page shows a few commands to paste on that
  machine. They download a single standalone script from Studio, which pulls the
  training set with a per-job token, reports every step, and uploads the result.
  The GPU machine must reach Studio — Tailscale on both is easiest, or set
  `STUDIO_LORA_PUBLIC_URL`. You can train on a rented GPU while Studio and the
  model you chat with stay on your own PC.

The job page shows live progress, the loss per step as a chart, and held-out
loss before and after.

**What you get back.** Choose under **What to make**:

- **A full model with the new weights** (the default). After training, the
  worker merges the LoRA into the base model's weights, converts the result to
  GGUF with llama.cpp, and quantizes it: `Q4_K_M` (about 4.7 GB for a 7B model,
  fits an 8 GB GPU such as an RX 580), `Q5_K_M`, or `Q8_0`. That one
  `model.gguf` is uploaded to Studio. Studio puts it in LM Studio's models
  folder (`~/.lmstudio/models/fcc-studio/…`, or `STUDIO_LMSTUDIO_MODELS_DIR`),
  creates it in Ollama if Ollama is installed, and switches the student to it
  as soon as the local model server offers it. In LM Studio, turn on
  Just-in-Time model loading, or load the model once from My Models, then press
  **Switch** on the job page. It is an ordinary GGUF file: download it from the
  job page and use it anywhere.
- **A small adapter** on top of the base model. It needs Ollama and
  `STUDIO_LORA_LLAMA_CPP`; Studio runs `ollama create` with `FROM base` and
  `ADAPTER`.

Either way Studio remembers the student's old model, so **Switch back** undoes
it.

**Training on a rented GPU, step by step:**

1. Install Tailscale on the PC running Studio and note its address (100.x.y.z).
   In admin settings, set **Address For Remote Trainers**
   (`STUDIO_LORA_PUBLIC_URL`) to `http://100.x.y.z:8082`.
2. Rent a 24 GB GPU (an RTX 4090 or A5000 on RunPod or Vast.ai) with a
   PyTorch template. Merging a 7B model also needs about 16 GB of RAM and
   40 GB of disk on that machine.
3. Start the job in Studio with **Where to train: Rented GPU**. The job page
   shows three command blocks. On a container host like RunPod, first run the
   **Tailscale for containers** block, after setting `TS_AUTHKEY` to an
   ephemeral auth key from the Tailscale admin console. Then run the Linux
   block: it downloads the worker, installs the libraries, builds
   `llama-quantize`, and trains.
4. Watch the loss here. When it ends, the new model arrives on your PC and is
   installed, and the student switches to it. Stop the rented machine.

</details>

<details>
<summary><strong>AI teacher and AI student</strong></summary>

Open a class on any topic and the teacher agent plans the lessons, teaches them
one at a time, and hears the student agent back — all in one classroom chat you
can read as it happens. After the last lesson the teacher writes a test, the
student answers each question without the lesson transcript, and the teacher
grades every answer against its own rubric. Pass or fail is decided by
`STUDIO_CLASS_PASS_MARK`.

Pick any two agents as teacher and student when you open the class. The point
is a server model teaching a local one: the teacher's calls go through FCC to
your provider, the student's go straight to your local runtime, and the Models
tab shows which local models that runtime is serving right now.

What the teacher marks as worth remembering goes into the student's long-term
memory, and a pass with light tuning enabled queues a tune built from the
class — coached by the teacher's model and scored on the student's.
`STUDIO_TEACHER_MODEL` and `STUDIO_STUDENT_MODEL` set the default Teacher and
Student agents' models.

</details>

<details>
<summary><strong>Memory and Obsidian</strong></summary>

Every agent keeps working notes for the thread it is in and long-term memories
it recalls by keyword, ranked by overlap, recall count, and recency. Agents
write memories themselves with the `remember` tool; you can read, add, promote,
or delete any of them.

Set `STUDIO_OBSIDIAN_VAULT` to your vault folder and Studio writes chats,
classes, and agent memories as markdown notes with YAML frontmatter under
`STUDIO_OBSIDIAN_FOLDER`. On iOS that vault usually lives in iCloud Drive
under `iCloud~md~obsidian`; Studio lists the vaults it can see on the device.
Notes you drop in the vault's `Inbox` folder import into an agent's memory, and
`STUDIO_OBSIDIAN_AUTO_SYNC` writes a note after every chat turn.

**Sync memory** mirrors the memory structure itself: a `Memory index` note,
a hub note per agent, and one note per memory under that agent's
`Working memory` or `Long-term memory` folder, all wikilinked. It works both
ways — edit a memory note in Obsidian, or drag it between the two folders to
change its scope, and the next sync brings the change into Studio. Studio only
ever deletes notes it wrote itself, and never overwrites a memory note you
edited since its last pull. `STUDIO_OBSIDIAN_MEMORY_SYNC` keeps the mirror
current after every chat turn, room conversation, and class.

</details>

<details>
<summary><strong>Installing it on an iPhone</strong></summary>

Studio is served wherever the proxy is bound, so a phone on the same network
can reach it. Open **More → Install on your iPhone** on the computer running
the server: it lists every address the server answers on — loopback, the
Bonjour `<hostname>.local` name, and each LAN address — with the live port and,
when proxy auth is on, the token already attached. Copy one, open it in Safari
on the phone, then **Share → Add to Home Screen**.

Installed, Studio runs standalone with a 180×180 touch icon, safe-area padding,
and 44pt targets. If the server is asleep or off the network, the app says so
plainly instead of failing blank, and nothing is lost — all state lives on the
computer. A service worker precaches the shell for instant launches, but
browsers only register one on a secure origin, so over plain HTTP on a LAN it
is skipped; put the server behind HTTPS or a tunnel to get it.

With `PROXY_AUTH_ENABLED` on, Studio requires the same token as the proxy.
Without it, anyone on the network who reaches the port can use Studio and your
models. Note that `/admin` stays local-only either way, so settings are changed
from the computer, not the phone.

</details>

<a id="connect-your-client"></a>

## Connect Your Client

For terminal use, start `fcc-server`, then run `fcc-claude`, `fcc-codex`,
`fcc-pi`, `fcc-opencode`, `fcc-cline`, `fcc-hermes`, `fcc-dsh`, `fcc-grok`,
`fcc-muse`, or `fcc-aider`.

For editor and app integrations, install the client, start FCC, then open
**Admin UI → Integrations** and click **Connect** on its card.

- **Claude Code in VS Code** — install the [Claude Code extension](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code).
- **Claude Desktop** — install [Claude Desktop](https://claude.ai/download). Fully quit it before connecting or disconnecting, then reopen it. Disconnect returns to normal Claude sign-in.
- **Codex in VS Code and App** — install the [Codex extension](https://marketplace.visualstudio.com/items?itemName=openai.chatgpt) or Codex App.
- **Claude Code in JetBrains ACP** — install Claude Agent in JetBrains AI Assistant and start it once, then click **Connect** in FCC. Reopen the IDE, select **Claude Code (FCC)**, and start a new chat. After JetBrains updates the agent, restart FCC before starting a new chat. Requires a local IDE in its standard installation locations.

Reload VS Code or restart the app/IDE after connecting. In Codex and Claude Desktop, select an FCC
model from the model picker. FCC keeps connected integrations up to date when it
starts; reload or restart the client when FCC reports updated settings. Use
**Disconnect** on the same card to remove the integration.

Run FCC on the same computer and in the same user environment as the client you
are configuring.

<a id="optional-integrations"></a>

## Optional Integrations

Configure integrations from **Admin UI → Messaging**, then click **Apply**.

<details>
<summary><strong>Discord bot</strong></summary>

1. Create a bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Enable **Message Content Intent** and invite it with read, send,
   message-history, and **Manage Messages** permissions so `/clear` can remove
   user prompts.
3. Set **Messaging Platform** to **discord**.
4. Enter **Discord Bot Token**, **Allowed Discord Channels**, and an absolute **Allowed Directory**.
5. Apply the settings and restart the server if requested.

</details>

<details>
<summary><strong>Telegram bot</strong></summary>

1. Create a bot with [@BotFather](https://t.me/BotFather).
2. Get your numeric user ID from [@userinfobot](https://t.me/userinfobot).
   In groups, grant the bot permission to delete messages.
3. Set **Messaging Platform** to **telegram**.
4. Enter **Telegram Bot Token**, **Allowed Telegram User ID**, and an absolute **Allowed Directory**.
5. Apply the settings and restart the server if requested.

</details>

### Messaging commands

| Usage | Behavior |
| --- | --- |
| `/stats` | Show session state. |
| Standalone `/stop` | Cancel all work. |
| Reply with `/stop` | Cancel only the selected request while other queued requests continue. |
| Standalone `/clear` | Reset all FCC state and remove every tracked message in that chat, including user prompts, voice notes, FCC replies, Telegram's online notice, and the clear command itself. |
| Reply with `/clear` | Delete the selected message and its literal platform reply subtree while preserving its ancestors and siblings. |

<details>
<summary><strong>Voice notes</strong></summary>

Re-run the installer with the command for your voice backend.

macOS/Linux:

NVIDIA NIM transcription:

```bash
curl -fsSL "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/install.sh" | sh -s -- --voice-nim
```

Local Whisper on CPU or CUDA:

```bash
curl -fsSL "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/install.sh" | sh -s -- --voice-local
```

Both backends:

```bash
curl -fsSL "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/install.sh" | sh -s -- --voice-all
```

Local Whisper with CUDA 13.0:

```bash
curl -fsSL "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/install.sh" | sh -s -- --voice-local --torch-backend cu130
```

Windows PowerShell:

NVIDIA NIM transcription:

```powershell
& ([scriptblock]::Create((irm "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/install.ps1"))) -VoiceNim
```

Local Whisper on CPU or CUDA:

```powershell
& ([scriptblock]::Create((irm "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/install.ps1"))) -VoiceLocal
```

Both backends:

```powershell
& ([scriptblock]::Create((irm "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/install.ps1"))) -VoiceAll
```

Local Whisper with CUDA 13.0:

```powershell
& ([scriptblock]::Create((irm "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/install.ps1"))) -VoiceLocal -TorchBackend cu130
```

Restart `fcc-server`. In **Admin UI → Messaging → Voice**, enable voice notes, select `cpu`, `cuda`, or `nvidia_nim`, and choose the Whisper model. Local gated models need `HUGGINGFACE_API_KEY`; NVIDIA NIM transcription needs `NVIDIA_NIM_API_KEY`.

</details>

## Manage Your Installation

Run `fcc-server --version` to check the installed version without starting FCC.

### Update

Stop all running FCC commands, then run:

```sh
fcc-update
```

This runs the same installer as above, including its coding-agent prompts and checks. If you use voice support, pass the same voice options used during installation.

If your installation does not have `fcc-update` yet, run the [installer](#install) once to add it.

### Muse Code on native Windows

Rerunning FCC's Windows installer with Muse Code selected installs or updates FCC's managed Muse executable. To install or update only Muse Code:

```powershell
& ([scriptblock]::Create((irm "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/install-muse.ps1")))
```

To remove only that managed Muse executable while preserving Muse data and other installations:

```powershell
& ([scriptblock]::Create((irm "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/uninstall-muse.ps1")))
```

FCC's ordinary uninstaller below continues to leave Muse Code installed.

### Uninstall

Stop every running FCC command before uninstalling.

**Removes**

- Free Claude Code, including its desktop launcher and commands
- `~/.fcc/`

**Keeps**

- uv and Python
- Claude Code, Codex, Pi, OpenCode, Cline, Hermes, DeepSeek Harness, Grok Build, Muse Code, Aider, and RTK
- Shared PATH entries

macOS/Linux:

```bash
curl -fsSL "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/uninstall.sh" | sh
```

Windows PowerShell:

```powershell
& ([scriptblock]::Create((irm "https://raw.githubusercontent.com/Alishahryar1/free-claude-code/main/scripts/uninstall.ps1")))
```

## Project Links

- [Report bugs or request features](https://github.com/Alishahryar1/free-claude-code/issues)
- [Contributing guide](CONTRIBUTING.md)

## License

MIT License. See [LICENSE](LICENSE) for details.
