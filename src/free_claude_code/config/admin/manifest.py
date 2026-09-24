"""Admin configuration manifest."""

from collections.abc import Iterable

from free_claude_code.config.provider_catalog import PROVIDER_CATALOG
from free_claude_code.config.reasoning import (
    ROOT_REASONING_PREFERENCES,
    ROUTE_REASONING_PREFERENCES,
    ReasoningPreference,
)
from free_claude_code.config.settings import Settings

from .provider_manifest import provider_field_specs
from .specs import ConfigFieldSpec, ConfigOptionSpec, ConfigSectionSpec


def _reasoning_options(
    preferences: tuple[ReasoningPreference, ...],
) -> tuple[ConfigOptionSpec, ...]:
    labels = {
        ReasoningPreference.INHERIT: "Inherit",
        ReasoningPreference.OFF: "Off",
        ReasoningPreference.CLIENT: "From client",
        ReasoningPreference.LOW: "Low",
        ReasoningPreference.MEDIUM: "Medium",
        ReasoningPreference.HIGH: "High",
        ReasoningPreference.XHIGH: "X-High",
        ReasoningPreference.MAX: "Max",
    }
    return tuple(
        ConfigOptionSpec(preference.value, labels[preference])
        for preference in preferences
    )


SECTIONS: tuple[ConfigSectionSpec, ...] = (
    ConfigSectionSpec(
        "providers",
        "Providers",
        "Provider keys, local endpoints, and proxy settings.",
    ),
    ConfigSectionSpec(
        "models",
        "Model Routing",
        "Search discovered provider models or enter a provider/model slug.",
    ),
    ConfigSectionSpec(
        "reasoning",
        "Reasoning",
        "Client reasoning policy and route-specific overrides.",
    ),
    ConfigSectionSpec(
        "runtime",
        "Runtime",
        "Server API token, rate limits, timeouts, and process settings.",
    ),
    ConfigSectionSpec(
        "messaging",
        "Messaging",
        "Discord, Telegram, CLI workspace, and session settings.",
    ),
    ConfigSectionSpec(
        "voice",
        "Voice",
        "Voice note transcription settings.",
    ),
    ConfigSectionSpec(
        "web_tools",
        "Web Tools",
        "Local Anthropic web_search and web_fetch behavior.",
    ),
    ConfigSectionSpec(
        "studio",
        "Studio",
        "Agents, local models, light tuning, classes, memory, and Obsidian.",
    ),
    ConfigSectionSpec(
        "diagnostics",
        "Diagnostics",
        "Logging and debugging flags.",
        advanced=True,
    ),
    ConfigSectionSpec(
        "smoke",
        "Smoke Tests",
        "Optional live smoke-test model overrides.",
        advanced=True,
    ),
)


_NON_PROVIDER_FIELDS: tuple[ConfigFieldSpec, ...] = (
    ConfigFieldSpec(
        "MODEL",
        "Default Model",
        "models",
        "model",
        settings_attr="model",
        description="Provider/model used when no tier-specific override applies.",
    ),
    ConfigFieldSpec(
        "MODEL_FABLE",
        "Fable Override",
        "models",
        "optional_model",
        settings_attr="model_fable",
        description="Select None to use the Default Model for Fable requests.",
    ),
    ConfigFieldSpec(
        "MODEL_OPUS",
        "Opus Override",
        "models",
        "optional_model",
        settings_attr="model_opus",
        description="Select None to use the Default Model for Opus requests.",
    ),
    ConfigFieldSpec(
        "MODEL_SONNET",
        "Sonnet Override",
        "models",
        "optional_model",
        settings_attr="model_sonnet",
        description="Select None to use the Default Model for Sonnet requests.",
    ),
    ConfigFieldSpec(
        "MODEL_HAIKU",
        "Haiku Override",
        "models",
        "optional_model",
        settings_attr="model_haiku",
        description="Select None to use the Default Model for Haiku requests.",
    ),
    ConfigFieldSpec(
        "MODEL_FALLBACKS",
        "Fallback Models",
        "models",
        "model_list",
        settings_attr="model_fallbacks",
        description=(
            "Tried in order when the selected provider/model fails before output "
            "starts. Applies to every client. One request may reach multiple "
            "providers and consume usage at each."
        ),
    ),
    ConfigFieldSpec(
        "REASONING_POLICY",
        "Reasoning Policy",
        "reasoning",
        "select",
        settings_attr="reasoning_policy",
        options=_reasoning_options(ROOT_REASONING_PREFERENCES),
        description=(
            "From client preserves CLI effort. Providers translate only the controls "
            "their API supports."
        ),
    ),
    ConfigFieldSpec(
        "REASONING_FABLE",
        "Fable Reasoning",
        "reasoning",
        "select",
        settings_attr="reasoning_fable",
        options=_reasoning_options(ROUTE_REASONING_PREFERENCES),
    ),
    ConfigFieldSpec(
        "REASONING_OPUS",
        "Opus Reasoning",
        "reasoning",
        "select",
        settings_attr="reasoning_opus",
        options=_reasoning_options(ROUTE_REASONING_PREFERENCES),
    ),
    ConfigFieldSpec(
        "REASONING_SONNET",
        "Sonnet Reasoning",
        "reasoning",
        "select",
        settings_attr="reasoning_sonnet",
        options=_reasoning_options(ROUTE_REASONING_PREFERENCES),
    ),
    ConfigFieldSpec(
        "REASONING_HAIKU",
        "Haiku Reasoning",
        "reasoning",
        "select",
        settings_attr="reasoning_haiku",
        options=_reasoning_options(ROUTE_REASONING_PREFERENCES),
    ),
    ConfigFieldSpec(
        "PROXY_AUTH_ENABLED",
        "Require API Authentication",
        "runtime",
        "boolean",
        settings_attr="proxy_auth_enabled",
        restart_required=True,
        description="Require the retained API/CLI token on FCC API routes.",
    ),
    ConfigFieldSpec(
        "ANTHROPIC_AUTH_TOKEN",
        "API/CLI Auth Token",
        "runtime",
        "secret",
        settings_attr="proxy_auth_token",
        secret=True,
        restart_required=True,
        description=(
            "Retained non-empty token passed to every harness. Authentication can be "
            "disabled without clearing it."
        ),
    ),
    ConfigFieldSpec(
        "PROVIDER_RATE_LIMIT",
        "Provider Rate Limit",
        "runtime",
        "number",
        settings_attr="provider_rate_limit",
    ),
    ConfigFieldSpec(
        "PROVIDER_RATE_WINDOW",
        "Provider Rate Window",
        "runtime",
        "number",
        settings_attr="provider_rate_window",
    ),
    ConfigFieldSpec(
        "PROVIDER_MAX_CONCURRENCY",
        "Provider Max Concurrency",
        "runtime",
        "number",
        settings_attr="provider_max_concurrency",
    ),
    ConfigFieldSpec(
        "PROVIDER_PROGRESS_TIMEOUT",
        "Provider Progress Timeout",
        "runtime",
        "number",
        settings_attr="provider_progress_timeout",
        description=(
            "Maximum seconds without a non-empty protocol event, including "
            "provider admission, retries, and backoff. Independent of HTTP Read "
            "Timeout."
        ),
        advanced=True,
    ),
    ConfigFieldSpec(
        "HTTP_READ_TIMEOUT",
        "HTTP Read Timeout",
        "runtime",
        "number",
        settings_attr="http_read_timeout",
    ),
    ConfigFieldSpec(
        "HTTP_WRITE_TIMEOUT",
        "HTTP Write Timeout",
        "runtime",
        "number",
        settings_attr="http_write_timeout",
    ),
    ConfigFieldSpec(
        "HTTP_CONNECT_TIMEOUT",
        "HTTP Connect Timeout",
        "runtime",
        "number",
        settings_attr="http_connect_timeout",
    ),
    ConfigFieldSpec(
        "HOST",
        "Server Host",
        "runtime",
        settings_attr="host",
        restart_required=True,
    ),
    ConfigFieldSpec(
        "PORT",
        "Server Port",
        "runtime",
        "number",
        settings_attr="port",
        restart_required=True,
    ),
    ConfigFieldSpec(
        "FCC_OPEN_BROWSER",
        "Open Admin on Startup",
        "runtime",
        "boolean",
        settings_attr="open_admin_browser",
        description="Open the Admin UI after the next fcc-server launch becomes healthy.",
    ),
    ConfigFieldSpec(
        "MESSAGING_PLATFORM",
        "Messaging Platform",
        "messaging",
        "select",
        settings_attr="messaging_platform",
        options=("telegram", "discord", "none"),
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "MESSAGING_RATE_LIMIT",
        "Messaging Rate Limit",
        "messaging",
        "number",
        settings_attr="messaging_rate_limit",
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "MESSAGING_RATE_WINDOW",
        "Messaging Rate Window",
        "messaging",
        "number",
        settings_attr="messaging_rate_window",
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "TELEGRAM_BOT_TOKEN",
        "Telegram Bot Token",
        "messaging",
        "secret",
        settings_attr="telegram_bot_token",
        secret=True,
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "ALLOWED_TELEGRAM_USER_ID",
        "Allowed Telegram User ID",
        "messaging",
        settings_attr="allowed_telegram_user_id",
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "TELEGRAM_PROXY_URL",
        "Telegram Proxy URL",
        "messaging",
        "secret",
        settings_attr="telegram_proxy_url",
        secret=True,
        session_sensitive=True,
        description="Optional Telegram-only proxy, e.g. socks5://127.0.0.1:1080.",
    ),
    ConfigFieldSpec(
        "DISCORD_BOT_TOKEN",
        "Discord Bot Token",
        "messaging",
        "secret",
        settings_attr="discord_bot_token",
        secret=True,
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "ALLOWED_DISCORD_CHANNELS",
        "Allowed Discord Channels",
        "messaging",
        settings_attr="allowed_discord_channels",
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "ALLOWED_DIR",
        "Allowed Directory",
        "messaging",
        settings_attr="allowed_dir",
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "MAX_MESSAGE_LOG_ENTRIES_PER_CHAT",
        "Max Tracked Messages Per Chat",
        "messaging",
        "number",
        settings_attr="max_message_log_entries_per_chat",
        advanced=True,
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "VOICE_NOTE_ENABLED",
        "Voice Notes",
        "voice",
        "boolean",
        settings_attr="voice_note_enabled",
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "WHISPER_DEVICE",
        "Whisper Device",
        "voice",
        "select",
        settings_attr="whisper_device",
        options=("cpu", "cuda", "nvidia_nim"),
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "WHISPER_MODEL",
        "Whisper Model",
        "voice",
        settings_attr="whisper_model",
        session_sensitive=True,
    ),
    ConfigFieldSpec(
        "FAST_PREFIX_DETECTION",
        "Fast Prefix Detection",
        "runtime",
        "boolean",
        settings_attr="fast_prefix_detection",
        advanced=True,
    ),
    ConfigFieldSpec(
        "ENABLE_NETWORK_PROBE_MOCK",
        "Network Probe Mock",
        "runtime",
        "boolean",
        settings_attr="enable_network_probe_mock",
        advanced=True,
    ),
    ConfigFieldSpec(
        "ENABLE_TITLE_GENERATION_SKIP",
        "Title Generation Skip",
        "runtime",
        "boolean",
        settings_attr="enable_title_generation_skip",
        advanced=True,
    ),
    ConfigFieldSpec(
        "ENABLE_SUGGESTION_MODE_SKIP",
        "Suggestion Mode Skip",
        "runtime",
        "boolean",
        settings_attr="enable_suggestion_mode_skip",
        advanced=True,
    ),
    ConfigFieldSpec(
        "ENABLE_FILEPATH_EXTRACTION_MOCK",
        "Filepath Extraction Mock",
        "runtime",
        "boolean",
        settings_attr="enable_filepath_extraction_mock",
        advanced=True,
    ),
    ConfigFieldSpec(
        "ENABLE_WEB_SERVER_TOOLS",
        "Web Server Tools",
        "web_tools",
        "boolean",
        settings_attr="enable_web_server_tools",
        description=(
            "Let Claude Code use WebSearch through FCC and allow forced local web "
            "tools. Disable to prevent local web access."
        ),
    ),
    ConfigFieldSpec(
        "WEB_FETCH_ALLOWED_SCHEMES",
        "Allowed Web Fetch Schemes",
        "web_tools",
        settings_attr="web_fetch_allowed_schemes",
    ),
    ConfigFieldSpec(
        "WEB_FETCH_ALLOW_PRIVATE_NETWORKS",
        "Allow Private Networks",
        "web_tools",
        "boolean",
        settings_attr="web_fetch_allow_private_networks",
    ),
    ConfigFieldSpec(
        "LOG_LEVEL",
        "Log Level",
        "diagnostics",
        "select",
        settings_attr="log_level",
        options=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "DEBUG_PLATFORM_EDITS",
        "Debug Platform Edits",
        "diagnostics",
        "boolean",
        settings_attr="debug_platform_edits",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "DEBUG_SUBAGENT_STACK",
        "Debug Subagent Stack",
        "diagnostics",
        "boolean",
        settings_attr="debug_subagent_stack",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "LOG_RAW_API_PAYLOADS",
        "Log Raw API Payloads",
        "diagnostics",
        "boolean",
        settings_attr="log_raw_api_payloads",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "LOG_RAW_SSE_EVENTS",
        "Log Raw SSE Events",
        "diagnostics",
        "boolean",
        settings_attr="log_raw_sse_events",
        advanced=True,
    ),
    ConfigFieldSpec(
        "LOG_API_ERROR_TRACEBACKS",
        "Log API Error Tracebacks",
        "diagnostics",
        "boolean",
        settings_attr="log_api_error_tracebacks",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "LOG_RAW_MESSAGING_CONTENT",
        "Log Raw Messaging Content",
        "diagnostics",
        "boolean",
        settings_attr="log_raw_messaging_content",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "LOG_RAW_CLI_DIAGNOSTICS",
        "Log Raw CLI Diagnostics",
        "diagnostics",
        "boolean",
        settings_attr="log_raw_cli_diagnostics",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "LOG_MESSAGING_ERROR_DETAILS",
        "Log Messaging Error Details",
        "diagnostics",
        "boolean",
        settings_attr="log_messaging_error_details",
        advanced=True,
        restart_required=True,
    ),
    ConfigFieldSpec(
        "FCC_SMOKE_MODEL_MISTRAL_REASONING",
        "Smoke Mistral Reasoning Model",
        "smoke",
        advanced=True,
    ),
    ConfigFieldSpec(
        "FCC_SMOKE_NIM_MODELS",
        "Smoke NIM Models",
        "smoke",
        advanced=True,
    ),
    ConfigFieldSpec(
        "FCC_SMOKE_NIM_EXTRA_MODELS",
        "Smoke NIM Extra Models",
        "smoke",
        advanced=True,
    ),
    ConfigFieldSpec(
        "FCC_SMOKE_OPENROUTER_FREE_MODELS",
        "Smoke OpenRouter Free Models",
        "smoke",
        advanced=True,
    ),
    ConfigFieldSpec(
        "FCC_SMOKE_OPENROUTER_FREE_EXTRA_MODELS",
        "Smoke OpenRouter Free Extra Models",
        "smoke",
        advanced=True,
    ),
)


_STUDIO_FIELDS: tuple[ConfigFieldSpec, ...] = (
    ConfigFieldSpec(
        "STUDIO_ENABLED",
        "Enable Studio",
        "studio",
        "boolean",
        settings_attr="studio_enabled",
        restart_required=True,
        description="Serve the Studio app at /studio for agents, classes, and tuning.",
    ),
    ConfigFieldSpec(
        "STUDIO_DEFAULT_MODEL",
        "Studio Default Model",
        "studio",
        "optional_model",
        settings_attr="studio_default_model",
        description="Model new Studio agents use. Defaults to the Default Model.",
    ),
    ConfigFieldSpec(
        "STUDIO_LOCAL_BASE_URL",
        "Local Model Server",
        "studio",
        "text",
        settings_attr="studio_local_base_url",
        description=(
            "OpenAI-compatible endpoint that serves downloaded models. "
            "Studio models written as local/<id> are sent here."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_LOCAL_API_KEY",
        "Local Model Server Key",
        "studio",
        "secret",
        settings_attr="studio_local_api_key",
        secret=True,
        advanced=True,
        description="Only needed when your local runtime requires a key.",
    ),
    ConfigFieldSpec(
        "STUDIO_GUIDE_MODEL",
        "Guide Model",
        "studio",
        "text",
        settings_attr="studio_guide_model",
        description="Small preloaded model that explains the app to the user.",
    ),
    ConfigFieldSpec(
        "STUDIO_GUIDE_CATALOG_ID",
        "Guide Model Download",
        "studio",
        "text",
        settings_attr="studio_guide_catalog_id",
        advanced=True,
        description="Curated catalog id downloaded when the guide model is missing.",
    ),
    ConfigFieldSpec(
        "STUDIO_MODELS_DIR",
        "Model Download Folder",
        "studio",
        "text",
        settings_attr="studio_models_dir",
        advanced=True,
        description="Where downloaded model files are stored. Defaults to ~/.fcc/studio/models.",
    ),
    ConfigFieldSpec(
        "STUDIO_AGENT_MAX_STEPS",
        "Agent Step Budget",
        "studio",
        "number",
        settings_attr="studio_agent_max_steps",
        description="Maximum tool steps one agent task may take before stopping.",
    ),
    ConfigFieldSpec(
        "STUDIO_LIGHT_TUNING_ENABLED",
        "Light Tuning",
        "studio",
        "boolean",
        settings_attr="studio_light_tuning_enabled",
        description=(
            "Allow very light tuning from chat settings. Turning it on in a chat "
            "opens a new chat that uses the tuned profile."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_TUNING_BACKEND",
        "Tuning Backend",
        "studio",
        "select",
        settings_attr="studio_tuning_backend",
        options=(
            ConfigOptionSpec("local_light", "On device (very light)"),
            ConfigOptionSpec("cloud", "Cloud trainer"),
        ),
        description=(
            "On device searches a small instruction pack and runs on a phone. "
            "Cloud sends the dataset to an OpenAI-compatible fine-tuning API."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_TUNING_ROUNDS",
        "Tuning Rounds",
        "studio",
        "number",
        settings_attr="studio_tuning_rounds",
        description="How many candidate packs on-device tuning tries. Keep it small on a phone.",
    ),
    ConfigFieldSpec(
        "STUDIO_CLOUD_TUNING_BASE_URL",
        "Cloud Trainer URL",
        "studio",
        "text",
        settings_attr="studio_cloud_tuning_base_url",
        description="OpenAI-compatible /v1 root exposing files and fine_tuning endpoints.",
    ),
    ConfigFieldSpec(
        "STUDIO_CLOUD_TUNING_API_KEY",
        "Cloud Trainer Key",
        "studio",
        "secret",
        settings_attr="studio_cloud_tuning_api_key",
        secret=True,
    ),
    ConfigFieldSpec(
        "STUDIO_CLOUD_TUNING_PROVIDER",
        "Cloud Trainer Provider",
        "studio",
        "text",
        settings_attr="studio_cloud_tuning_provider",
        description=(
            "FCC provider that serves models the trainer produces, e.g. openai or "
            "together. When set, a finished server tune switches the agent to it."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_TEACHER_ENABLED",
        "AI Teacher",
        "studio",
        "boolean",
        settings_attr="studio_teacher_enabled",
        description="Show the classroom where a teacher agent teaches and tests a student agent.",
    ),
    ConfigFieldSpec(
        "STUDIO_TEACHER_MODEL",
        "Teacher Model",
        "studio",
        "optional_model",
        settings_attr="studio_teacher_model",
        description="Model the teacher agent uses. Defaults to the Studio default model.",
    ),
    ConfigFieldSpec(
        "STUDIO_STUDENT_MODEL",
        "Student Model",
        "studio",
        "optional_model",
        settings_attr="studio_student_model",
        description="Model the student agent uses. A small local model is the point.",
    ),
    ConfigFieldSpec(
        "STUDIO_CLASS_PASS_MARK",
        "Class Pass Mark",
        "studio",
        "number",
        settings_attr="studio_class_pass_mark",
        description="Fraction of the end-of-class test the student must score to pass.",
    ),
    ConfigFieldSpec(
        "STUDIO_OBSIDIAN_VAULT",
        "Obsidian Vault",
        "studio",
        "text",
        settings_attr="studio_obsidian_vault",
        description=(
            "Vault folder to mirror chats, classes, and memories into. On iOS this "
            "is usually in iCloud Drive under iCloud~md~obsidian."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_OBSIDIAN_FOLDER",
        "Obsidian Subfolder",
        "studio",
        "text",
        settings_attr="studio_obsidian_folder",
        description="Folder inside the vault that Studio writes to.",
    ),
    ConfigFieldSpec(
        "STUDIO_OBSIDIAN_AUTO_SYNC",
        "Auto-sync To Obsidian",
        "studio",
        "boolean",
        settings_attr="studio_obsidian_auto_sync",
        description="Write a note every time a chat turn or class finishes.",
    ),
    ConfigFieldSpec(
        "STUDIO_OBSIDIAN_MEMORY_SYNC",
        "Mirror Memory Into Obsidian",
        "studio",
        "boolean",
        settings_attr="studio_obsidian_memory_sync",
        description=(
            "Keep every agent's working and long-term memory in the vault as "
            "linked notes, one per memory, updated as agents learn."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_SHARED_MEMORY",
        "Shared Team Memory",
        "studio",
        "boolean",
        settings_attr="studio_shared_memory",
        description=(
            "Agents save what they learn into one memory the whole team reads, "
            "so the main AI and every agent build on each other's work. Each "
            "agent keeps its own working notes."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_MAIN_AGENT_NAME",
        "Main AI Name",
        "studio",
        "text",
        settings_attr="studio_main_agent_name",
        description="Name of the main AI that runs the other agents from the HUD.",
    ),
    ConfigFieldSpec(
        "STUDIO_MAIN_AGENT_MODEL",
        "Main AI Model",
        "studio",
        "optional_model",
        settings_attr="studio_main_agent_model",
        description=(
            "Model the main AI thinks with, e.g. local/qwen2.5-coder:7b. "
            "Defaults to the Studio Default Model."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_UI_THEME",
        "Studio Look",
        "studio",
        "select",
        settings_attr="studio_ui_theme",
        options=(
            ConfigOptionSpec("classic", "Classic app"),
            ConfigOptionSpec("hud", "HUD (main AI console)"),
        ),
        description=(
            "Which interface Studio opens with. Each device can still switch "
            "in the app under More > Appearance."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_WEB_ACCESS",
        "Agents On The Internet",
        "studio",
        "select",
        settings_attr="studio_web_access",
        options=(
            ConfigOptionSpec("all", "Every agent"),
            ConfigOptionSpec("listed", "Only agents given web tools"),
            ConfigOptionSpec("off", "No agent"),
        ),
        description=(
            "Lets agents search the web and read pages, local models included: "
            "Studio does the browsing on their behalf."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_SEARCH_PROVIDER",
        "Web Search Service",
        "studio",
        "select",
        settings_attr="studio_search_provider",
        options=(
            ConfigOptionSpec("auto", "Auto (from the key)"),
            ConfigOptionSpec("duckduckgo", "DuckDuckGo (no key)"),
            ConfigOptionSpec("brave", "Brave Search API"),
            ConfigOptionSpec("tavily", "Tavily"),
            ConfigOptionSpec("serper", "Serper (Google results)"),
            ConfigOptionSpec("searxng", "SearXNG (self-hosted)"),
        ),
        description=(
            "Where agents' web searches go. DuckDuckGo needs no key but often "
            "limits automated searches; a key makes search reliable. Auto picks "
            "the service from the key: tvly- is Tavily, BSA is Brave."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_SEARCH_API_KEY",
        "Web Search API Key",
        "studio",
        "secret",
        settings_attr="studio_search_api_key",
        secret=True,
        description=(
            "Key or token for Brave Search, Tavily, or Serper. Studio uses it "
            "for every agent's searches and falls back to DuckDuckGo if it fails."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_YOUTUBE_API_KEY",
        "YouTube API Key",
        "studio",
        "secret",
        settings_attr="studio_youtube_api_key",
        secret=True,
        description=(
            "YouTube Data API key from Google Cloud. Lets research search "
            "YouTube directly; without it, videos are found through web search. "
            "Transcripts are read either way when a video has captions."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_REDDIT_CLIENT_ID",
        "Reddit App ID",
        "studio",
        "text",
        settings_attr="studio_reddit_client_id",
        description=(
            "From reddit.com/prefs/apps (create a 'script' app). With the "
            "secret, research reads Reddit through its official API instead "
            "of the public pages Reddit often blocks."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_REDDIT_CLIENT_SECRET",
        "Reddit App Secret",
        "studio",
        "secret",
        settings_attr="studio_reddit_client_secret",
        secret=True,
    ),
    ConfigFieldSpec(
        "STUDIO_RESEARCH_SOURCES",
        "Sources Per Research",
        "studio",
        "number",
        settings_attr="studio_research_sources",
        description=(
            "How many sources the research tool gathers and reads for each "
            "question, from 3 to 25."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_SEARCH_BASE_URL",
        "SearXNG Address",
        "studio",
        "text",
        settings_attr="studio_search_base_url",
        description=(
            "Address of your own SearXNG, e.g. http://localhost:8888, with the "
            "json format enabled. Free and needs no key."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_AGENT_COMMANDS",
        "Agents Can Run Commands",
        "studio",
        "select",
        settings_attr="studio_agent_commands",
        options=(
            ConfigOptionSpec("off", "Off"),
            ConfigOptionSpec("ask", "Ask me each time"),
            ConfigOptionSpec("auto", "Run without asking"),
        ),
        description=(
            "Lets agents run shell commands (npm, python, builds, tests) inside a "
            "project folder. Commands run on this computer with your permissions, "
            "minus credentials; Ask shows each one for approval first."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_COMMAND_TIMEOUT",
        "Command Time Limit",
        "studio",
        "number",
        settings_attr="studio_command_timeout",
        description="Seconds before an agent's command and everything it started is stopped.",
    ),
    ConfigFieldSpec(
        "STUDIO_LORA_PYTHON",
        "LoRA Trainer Python",
        "studio",
        "text",
        settings_attr="studio_lora_python",
        description=(
            "Python with torch, transformers, and peft for training on this "
            "computer. Leave empty to use Studio's own (install the lora extra)."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_LORA_LLAMA_CPP",
        "llama.cpp Folder",
        "studio",
        "text",
        settings_attr="studio_lora_llama_cpp",
        description="A llama.cpp checkout; lets training also produce a GGUF adapter Ollama can load.",
    ),
    ConfigFieldSpec(
        "STUDIO_LMSTUDIO_MODELS_DIR",
        "LM Studio Models Folder",
        "studio",
        "text",
        settings_attr="studio_lmstudio_models_dir",
        description=(
            "Where LM Studio keeps models, so trained models install there. "
            "Leave empty to use LM Studio's usual folder (.lmstudio/models in "
            "your user folder)."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_LORA_OLLAMA",
        "Ollama Program",
        "studio",
        "text",
        settings_attr="studio_lora_ollama",
        advanced=True,
        description="Path to ollama when it is not on PATH.",
    ),
    ConfigFieldSpec(
        "STUDIO_LORA_PUBLIC_URL",
        "Address For Remote Trainers",
        "studio",
        "text",
        settings_attr="studio_lora_public_url",
        description=(
            "How a rented GPU or VPS reaches this Studio, e.g. a Tailscale address "
            "like http://my-pc:8082. Defaults to this computer's LAN address."
        ),
    ),
    ConfigFieldSpec(
        "STUDIO_MEMORY_WORKING_LIMIT",
        "Working Memory Size",
        "studio",
        "number",
        settings_attr="studio_memory_working_limit",
        advanced=True,
        description="How many short-term notes each agent keeps.",
    ),
    ConfigFieldSpec(
        "STUDIO_MEMORY_RECALL_LIMIT",
        "Memory Recall Size",
        "studio",
        "number",
        settings_attr="studio_memory_recall_limit",
        advanced=True,
        description="How many long-term memories are recalled into one prompt.",
    ),
)


def _catalog_smoke_fields() -> tuple[ConfigFieldSpec, ...]:
    return tuple(
        ConfigFieldSpec(
            key=f"FCC_SMOKE_MODEL_{provider_id.upper()}",
            label=f"Smoke {descriptor.display_name} Model",
            section_id="smoke",
            advanced=True,
        )
        for provider_id, descriptor in PROVIDER_CATALOG.items()
    )


FIELDS: tuple[ConfigFieldSpec, ...] = (
    *provider_field_specs(),
    *_NON_PROVIDER_FIELDS,
    *_STUDIO_FIELDS,
    *_catalog_smoke_fields(),
)
FIELD_BY_KEY = {field.key: field for field in FIELDS}


def field_input_key(field: ConfigFieldSpec) -> str | None:
    """Return the Settings input key used for a manifest field."""

    if field.settings_attr is None:
        return None
    model_field = Settings.model_fields[field.settings_attr]
    alias = model_field.validation_alias
    if alias is None:
        return field.settings_attr
    return str(alias)


def env_keys() -> frozenset[str]:
    """Return env keys owned by the admin manifest."""

    return frozenset(field.key for field in FIELDS)


def fields_with_attrs() -> Iterable[ConfigFieldSpec]:
    """Yield fields that validate through Settings."""

    return (field for field in FIELDS if field.settings_attr is not None)
