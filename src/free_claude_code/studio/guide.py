"""The guide that explains this app, knows where everything is, and spots problems."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .llm import ChatMessage, StudioLLMError, StudioModelRouter


@dataclass(frozen=True, slots=True)
class GuideTopic:
    """One thing the guide knows how to explain, and where it lives."""

    title: str
    route: str
    terms: tuple[str, ...]
    body: str
    where: str = ""
    asks: tuple[str, ...] = ()


GUIDE_TOPICS: tuple[GuideTopic, ...] = (
    GuideTopic(
        title="What Studio can do",
        route="/studio#home",
        where="Everything starts on the HUD. MENU opens the rest.",
        terms=(
            "overview",
            "features",
            "everything",
            "what can",
            "capabilities",
            "tour",
            "begin",
            "new here",
            "first time",
            "get started",
        ),
        body=(
            "Studio is a team of AI agents run by Jarvis, the main AI. You talk to "
            "Jarvis on the HUD by typing or by voice; he answers, and hands work to "
            "the team: the Builder writes apps and websites, the Researcher reads "
            "ten or more sources, and the Helper turns ideas into a plan. Agents "
            "remember things, work together in rooms, run tasks on their own, and "
            "can use the internet. Models can run on this PC through LM Studio or on "
            "a server. You can also teach agents skills, hold classes where one AI "
            "teaches another, tune them, sync memory to Obsidian, and install "
            "Studio as a desktop app or on an iPhone."
        ),
        asks=(
            "How do I set up LM Studio?",
            "How do I talk to Jarvis with my voice?",
            "How do I get the Builder to make an app?",
        ),
    ),
    GuideTopic(
        title="The HUD command center",
        route="/studio#home",
        where=(
            "Studio opens on the HUD (Command Center). On a PC the left sidebar "
            "lists every page: Command Center, Agents, Chats, Classroom, Models, "
            "Tuning & LoRA, Knowledge & Memory, and Settings. On a phone, MENU "
            "opens Knowledge & Memory and the tabs at the bottom do the rest."
        ),
        terms=(
            "hud",
            "home",
            "orb",
            "core",
            "screen",
            "dashboard",
            "command center",
            "layout",
            "panel",
            "system status",
            "feed",
            "timeline",
        ),
        body=(
            "The gold orb in the middle is Jarvis's AI CORE: it swirls while he "
            "thinks, and pulses while he listens and speaks. Type below it and "
            "press SEND, or press TALK for voice. NEW TALK starts a clean "
            "conversation, CHOOSE BRAIN picks his model, and MENU opens every "
            "other page. SYSTEM STATUS at the top reads OPTIMAL when all is well; "
            "tap it when it says ATTENTION or LOCAL MODELS OFFLINE and I explain "
            "what is wrong. Top right is the AGENT CHAT ROOM, bottom left is "
            "AGENTS AT WORK, and the side panels show the LIVE INTELLIGENCE FEED, "
            "MISSION TIMELINE, QUICK COMMANDS, SYSTEM MONITOR, BRAIN STATUS, and "
            "SHARED MEMORY."
        ),
        asks=(
            "What does ATTENTION mean?",
            "How do I watch an agent work?",
            "What are quick commands?",
        ),
    ),
    GuideTopic(
        title="Talking to Jarvis",
        route="/studio#home",
        where="HUD: type in the box under the orb and press SEND.",
        terms=(
            "jarvis",
            "main ai",
            "message",
            "type",
            "send",
            "new talk",
            "reset",
            "conversation",
            "delegate",
            "boss",
            "order",
            "orders",
            "have builder",
            "tell agent",
            "stop agent",
        ),
        body=(
            "Jarvis is the main AI. Type on the HUD and press SEND; his words "
            "appear as he writes them. Ask for anything: he answers himself, or "
            "sends the job to the Builder, Researcher, or Helper and reports back. "
            "Orders are carried out the moment you say them: 'have Builder make a "
            "timer app', 'tell the Researcher to look into cheap GPUs', '@Helper "
            "plan my week', 'get an agent to ...' (he picks who), several in one "
            "message, or 'stop Builder'. Ask 'what is everyone doing?' for a team "
            "update. NEW TALK clears the conversation but keeps his memory. "
            "You can rename him with Main Agent Name in Settings, under Studio."
        ),
        asks=(
            "How do I talk to Jarvis with my voice?",
            "How do I change Jarvis's model?",
        ),
    ),
    GuideTopic(
        title="Voice and talk mode",
        route="/studio#more",
        where=(
            "HUD: press TALK or tap the orb. Voice setup: Knowledge & Memory (MENU), then the Main AI "
            "voice card (Hear him, Download the voice)."
        ),
        terms=(
            "voice",
            "speak",
            "talk mode",
            "microphone",
            "mic",
            "hear",
            "listen",
            "whisper",
            "kokoro",
            "audio",
            "sound",
            "aloud",
            "spoken",
        ),
        body=(
            "Press TALK or tap the orb: you speak, Jarvis answers out loud, then "
            "listens again. He starts speaking before his reply is finished. The "
            "built-in voice and Whisper speech recognition run offline on this PC "
            "after a one-time download; Knowledge & Memory (MENU), Main AI voice shows the status, "
            "Hear him plays a sample, and Download the voice fetches it. The "
            "microphone works at http://localhost:8082/studio on this PC or in "
            "the desktop app; on a phone Studio must be opened over HTTPS with "
            "tailscale serve. Voice name, speed, and quality are in Settings, "
            "under Studio."
        ),
        asks=(
            "Why is the microphone not working?",
            "How do I change his voice?",
        ),
    ),
    GuideTopic(
        title="Choosing Jarvis's brain",
        route="/studio#home",
        where=(
            "HUD: CHOOSE BRAIN under the orb, or QUICK COMMANDS, Choose brain. "
            "Other agents: Agents, tap the agent, Model."
        ),
        terms=(
            "brain",
            "choose",
            "switch",
            "change model",
            "which model",
            "pick",
            "use model",
            "different model",
            "change",
            "jarvis model",
            "his model",
        ),
        body=(
            "CHOOSE BRAIN lists every model LM Studio is serving on this PC, plus "
            "server models; tap one and Jarvis uses it from his next reply. "
            "Choose a model from this PC opens a file picker for a .gguf file "
            "anywhere on your drives, copies it where LM Studio finds it, and "
            "names it local/<name>. If the chosen model is unreachable, for "
            "example a server model with no key, Studio uses the model LM Studio "
            "has loaded instead so Jarvis keeps working. Each agent has its own "
            "model on its page under Agents."
        ),
        asks=(
            "How do I set up LM Studio?",
            "Which model should I use?",
        ),
    ),
    GuideTopic(
        title="Local models",
        route="/studio#models",
        where=(
            "Models in the left sidebar (on a phone: MENU, Local models, Open models). The Models page lists what your "
            "local runtime serves and has Choose a model from this PC."
        ),
        terms=(
            "local",
            "model",
            "gguf",
            "download",
            "offline",
            "install",
            "file",
            "qwen",
            "llama",
            "curated",
        ),
        body=(
            "Local models run on this PC, free and private. LM Studio serves "
            "them; Studio calls each one local/<model id>. The Models page shows "
            "Served by your local runtime, a list of Curated small models, "
            "Download any model file from a link, and Choose a model from this "
            "PC for a .gguf file you already have. Any model works: Qwen, Llama, "
            "Gemma, Mistral, Phi, and others. On an 8 GB graphics card, 3 to 8 "
            "billion parameter models at Q4 are the sweet spot."
        ),
        asks=(
            "How do I set up LM Studio?",
            "How do I add a model file from my PC?",
        ),
    ),
    GuideTopic(
        title="Setting up LM Studio",
        route="/studio#models",
        where=(
            "In LM Studio: the Developer tab, then Start Server. In Studio: the "
            "Models page shows whether it is reached."
        ),
        terms=(
            "lm studio",
            "lmstudio",
            "vulkan",
            "server",
            "runtime",
            "port",
            "1234",
            "gpu",
            "amd",
            "radeon",
            "nvidia",
            "load",
            "offload",
            "context",
        ),
        body=(
            "1. Install LM Studio and download a model in its Discover tab. "
            "2. On an AMD card like the RX 580, pick the Vulkan runtime in LM "
            "Studio's settings under Runtime. 3. Load the model with GPU Offload "
            "as high as fits in video memory and a Context Length of 4096 to "
            "8192. 4. Open the Developer tab and switch Start Server on; it "
            "serves at http://localhost:1234/v1, the address Studio expects "
            "(Local Runtime URL in Settings, under Studio). 5. Back in Studio, "
            "the HUD reads OPTIMAL and CHOOSE BRAIN lists the model. Everything "
            "stays on this PC; the 'server' only talks to programs on it."
        ),
        asks=(
            "Why does it say LOCAL MODELS OFFLINE?",
            "How do I make replies faster?",
        ),
    ),
    GuideTopic(
        title="Making replies faster",
        route="/studio#settings",
        where=(
            "Settings, Studio: Fast Local Replies and Agent Temperature. In LM "
            "Studio: GPU Offload and Context Length when loading a model."
        ),
        terms=(
            "slow",
            "fast",
            "faster",
            "speed",
            "lag",
            "quicker",
            "performance",
            "temperature",
            "wait",
            "waiting",
            "takes long",
        ),
        body=(
            "Keep Fast Local Replies on: it skips a thinking model's hidden "
            "reasoning so the answer starts at once. Studio already streams "
            "words as they are written, reuses the unchanged start of every "
            "prompt, and runs web searches and file reads side by side. The "
            "biggest wins are in LM Studio: offload every layer to the graphics "
            "card, keep Context Length around 4096 to 8192, and keep only one "
            "model loaded. A smaller model (3 to 4 billion parameters) answers "
            "fastest. Agent Temperature only changes wording, not speed."
        ),
        asks=(
            "How do I set up LM Studio?",
            "What does Agent Temperature do?",
        ),
    ),
    GuideTopic(
        title="Agents at work",
        route="/studio#home",
        where="HUD, bottom left: AGENTS AT WORK. Tap an agent to watch it.",
        terms=(
            "working",
            "watch",
            "process",
            "steps",
            "progress",
            "busy",
            "doing",
            "activity",
            "at work",
            "see agents",
        ),
        body=(
            "AGENTS AT WORK lists the whole team with a live dot on anyone who is "
            "busy. Tap an agent to watch its process step by step: what it was "
            "asked, each tool it used such as writing a file or searching the "
            "web, and its words as it writes them. Tap All to go back to the "
            "team, or OPEN to jump to that agent's chat."
        ),
        asks=("How do I give the Builder a job?",),
    ),
    GuideTopic(
        title="Team rooms",
        route="/studio#chats",
        where=(
            "HUD, top right: AGENT CHAT ROOM, with START TEAM ROOM and POST. "
            "Every room is also on the Chats tab."
        ),
        terms=(
            "room",
            "rooms",
            "team room",
            "together",
            "group",
            "mention",
            "collaborate",
            "post",
            "chat room",
        ),
        body=(
            "A room puts several agents in one conversation. Start one with "
            "START TEAM ROOM on the HUD or QUICK COMMANDS, Team room. Post a "
            "message and the right agents answer; write @Builder or @Researcher "
            "to ask one directly. Give the room a task and the agents hand work "
            "to each other until it is done. Past rooms are on the Chats tab."
        ),
        asks=("What does each agent do?",),
    ),
    GuideTopic(
        title="Quick commands",
        route="/studio#home",
        where="HUD: the QUICK COMMANDS panel.",
        terms=("quick", "shortcut", "shortcuts", "briefing", "executive"),
        body=(
            "QUICK COMMANDS are one-tap jobs: Voice chat starts talk mode, "
            "Executive briefing has Jarvis sum up what the team is doing, Build "
            "starts a job for the Builder, Research one for the Researcher, "
            "Brainstorm asks the Helper for a plan, Team room opens a room with "
            "every agent, and Choose brain switches Jarvis's model."
        ),
    ),
    GuideTopic(
        title="The team",
        route="/studio#agents",
        where="The Agents tab lists every agent. The HUD shows them in AGENTS AT WORK.",
        terms=(
            "builder",
            "researcher",
            "helper",
            "guide",
            "team",
            "who",
            "roles",
            "agents",
            "each agent",
        ),
        body=(
            "Jarvis runs the team. The Builder writes code, websites, and whole "
            "apps into a project folder, and can read, edit, and search its "
            "files. The Researcher digs through the web, Reddit, YouTube, and "
            "code sites and tests code before recommending it. The Helper "
            "brainstorms and turns messy findings into a clear plan. I am the "
            "Guide: I explain the app. Add more with + New agent on the Agents "
            "tab."
        ),
        asks=(
            "How do I add an agent?",
            "How do I get the Builder to make an app?",
        ),
    ),
    GuideTopic(
        title="Adding and changing agents",
        route="/studio#agents",
        where=(
            "Agents tab: + New agent in the Add an agent card. Tap any agent to "
            "change its model, tools, and memory."
        ),
        terms=(
            "add",
            "create",
            "new agent",
            "make agent",
            "edit",
            "delete",
            "rename",
            "role",
            "tools",
            "customize",
        ),
        body=(
            "On the Agents tab, + New agent asks for a name, a role, a model, "
            "and the tools it may use: building files, running code, the "
            "internet, deep research, or asking the Researcher and Helper. Tap "
            "an agent to open its page: change its model, read and add to its "
            "memory, Teach a skill, start a chat, or tune it."
        ),
        asks=("How do I teach an agent a skill?",),
    ),
    GuideTopic(
        title="Agent tasks",
        route="/studio#agents",
        where="Agents tab: the Run an agent task card. Progress shows on the HUD's MISSION TIMELINE.",
        terms=(
            "task",
            "autonomous",
            "goal",
            "mission",
            "job",
            "background",
            "on its own",
        ),
        body=(
            "Give an agent a goal and it works on its own in a bounded loop: "
            "search, fetch pages, write files, check its work, then finish with a "
            "report. Attach a site and everything it writes lands there, ready "
            "to preview and download as a zip. Tasks keep running while you do "
            "other things; the MISSION TIMELINE and AGENTS AT WORK follow them."
        ),
    ),
    GuideTopic(
        title="Building apps and websites",
        route="/studio#agents",
        where=(
            "Ask on the HUD ('have Builder make ...') or use Agents, Run an agent "
            "task. The result opens on its Site page with Open full screen and "
            "Download .zip."
        ),
        terms=(
            "apps",
            "an app",
            "my app",
            "builder made",
            "result",
            "build",
            "website",
            "site",
            "code",
            "coding",
            "project",
            "preview",
            "zip",
            "html",
            "python",
            "game",
            "template",
            "undo",
            "restore",
        ),
        body=(
            "The Builder writes any kind of project: web pages, Python, "
            "TypeScript, games, configs. New projects start from a solid template "
            "(website, landing page, web app, canvas game, Python tool, Python "
            "web API, Node API) that it then shapes to the job. It reads, edits, "
            "and searches its own files, checks the whole project before it says "
            "it is done, and asks the Researcher when stuck on an error. Every "
            "file change keeps the last ten versions, so you can say 'Builder, "
            "undo your last change to index.html'. Builders get 40 steps per job "
            "(Builder Max Steps in Settings, under Studio). The finished site has "
            "a live preview, Open full screen, Edit for any file, and Download "
            ".zip. With Agent Commands allowed in Settings it can also run npm "
            "install, builds, and tests."
        ),
        asks=(
            "How do I let agents run commands?",
            "Where do I see what the Builder made?",
        ),
    ),
    GuideTopic(
        title="Commands and approvals",
        route="/studio#settings",
        where=(
            "Settings, Studio: Agent Commands (off, ask, or on). Requests to run "
            "one show in the chat and the HUD with Run it and Deny."
        ),
        terms=(
            "command",
            "commands",
            "npm",
            "terminal",
            "shell",
            "approve",
            "approval",
            "approvals",
            "deny",
            "permission",
            "allow",
        ),
        body=(
            "Agents can run commands like npm install, builds, and tests only if "
            "you allow it. Agent Commands off means never, ask means each command "
            "waits for you to press Run it or Deny, and on runs them in the "
            "project folder without asking. Waiting requests show on the HUD."
        ),
    ),
    GuideTopic(
        title="Internet access",
        route="/studio#more",
        where=(
            "Knowledge & Memory (MENU), Internet access card (Test search). Keys: Settings, Studio, "
            "Web Search API Key."
        ),
        terms=(
            "internet",
            "web",
            "search",
            "online",
            "key",
            "token",
            "brave",
            "tavily",
            "serper",
            "searxng",
            "duckduckgo",
            "browse",
        ),
        body=(
            "Every agent can search the web and read pages, local models too: "
            "Studio does the browsing and hands them the results. Searches use "
            "DuckDuckGo with no key, which often gets blocked, so add a Brave "
            "Search, Tavily, or Serper key in Settings under Studio, Web Search "
            "API Key, or point it at your own SearXNG. Knowledge & Memory (MENU), Internet access "
            "tests it. When this PC goes offline, web tools pause and agents "
            "work from memory; they come back on their own when the internet "
            "does. Web Access in Settings can limit or turn off browsing."
        ),
        asks=("How does deep research work?",),
    ),
    GuideTopic(
        title="Deep research",
        route="/studio#agents",
        where=(
            "Ask on the HUD ('have Researcher look into ...') or QUICK COMMANDS, "
            "Research."
        ),
        terms=(
            "research",
            "sources",
            "reddit",
            "youtube",
            "stack overflow",
            "github",
            "investigate",
            "look into",
            "find out",
            "test_code",
        ),
        body=(
            "The research tool reads ten or more sources per question: the web, "
            "Reddit threads, YouTube transcripts, Stack Overflow, GitHub, MDN, and "
            "dev.to. The Researcher tests code it finds with test_code in its "
            "Research lab before recommending it. The Builder calls ask_researcher "
            "when it is stuck on an error. Reddit and YouTube keys in Settings, "
            "under Studio, make research more reliable."
        ),
    ),
    GuideTopic(
        title="Helper and brainstorming",
        route="/studio#agents",
        where="QUICK COMMANDS, Brainstorm, or say 'ask Helper for ideas on ...'.",
        terms=("helper", "ideas", "brainstorm", "plan", "stuck", "organize"),
        body=(
            "The Helper brainstorms and filters. When the Researcher brings back "
            "a pile of findings, the Helper turns them into a short plan that "
            "fits the job. Any agent can call ask_helper, and you can ask it "
            "directly from QUICK COMMANDS, Brainstorm."
        ),
    ),
    GuideTopic(
        title="To-dos and reminders",
        route="/studio#more",
        where=(
            "Knowledge & Memory (MENU), To-dos and reminders card. Or just tell "
            "Jarvis: 'remind me to call Sam at 5pm'."
        ),
        terms=(
            "todo",
            "to-do",
            "todos",
            "reminder",
            "reminders",
            "remind",
            "list",
            "tasks list",
            "alarm",
            "schedule",
        ),
        body=(
            "Jarvis and the Helper keep your to-do list with the todo tool: 'add "
            "milk to my list', 'remind me to call Sam in 20 minutes', 'what's on "
            "my list?', 'tick off milk'. Reminders understand 'in 20 minutes', "
            "'tomorrow 9am', 'at 17:30', and dates like '2026-10-01 14:00'. When "
            "one is due, Jarvis announces it on the HUD (spoken when his voice is "
            "on). The To-dos and reminders card on Knowledge & Memory shows the "
            "list, adds items with an optional reminder, and ticks them off. "
            "Jarvis also has calculate for exact sums, list_projects to find your "
            "projects with their links, and system_status for how your PC and LM "
            "Studio are doing, and he always knows the date and time."
        ),
        asks=("What can Jarvis do?", "How do I talk to Jarvis with my voice?"),
    ),
    GuideTopic(
        title="Video notes",
        route="/studio#more",
        where=(
            "Knowledge & Memory (MENU), Video notes card: paste a YouTube link "
            "and press Study it, or Open a studied video."
        ),
        terms=(
            "video",
            "videos",
            "youtube",
            "transcript",
            "transcribe",
            "watch",
            "video notes",
            "study video",
        ),
        body=(
            "Every YouTube video research reads, and any video you give Studio, "
            "is turned into video notes: a summary, key points, steps, names, and "
            "warnings, plus the full transcript with times. The notes go into the "
            "team's memory with the link, so every agent can use them, and agents "
            "look back at the exact parts with the video_notes tool, each with a "
            "link to that moment. Give Jarvis or the Researcher a link, or paste "
            "it on the Video notes card; add what the team should learn from it "
            "to focus the notes. Open a note to read it, search the transcript, "
            "jump to a moment, or forget the video."
        ),
        asks=("How does deep research work?", "Where is memory?"),
    ),
    GuideTopic(
        title="Memory",
        route="/studio#agents",
        where=(
            "HUD: SHARED MEMORY panel (type a note, SAVE). One agent's memory: "
            "Agents, tap the agent, Memory."
        ),
        terms=(
            "memory",
            "remember",
            "forget",
            "recall",
            "notes",
            "shared",
            "facts",
            "memories",
        ),
        body=(
            "Each agent keeps working notes for the current conversation and "
            "long-term memories it recalls when they matter. With shared memory "
            "on, the whole team reads one common memory, shown in the HUD's "
            "SHARED MEMORY panel where you can SAVE a note. Agents write memories "
            "with the remember tool. On an agent's page you can read them, add a "
            "fact, or delete one. Memory can mirror into Obsidian."
        ),
        asks=("How do I sync memory to Obsidian?",),
    ),
    GuideTopic(
        title="Obsidian",
        route="/studio#more",
        where=(
            "Knowledge & Memory (MENU), Obsidian card: Sync memory, Pull edits only, Import notes to "
            "memory. Vault folder: Settings, Studio, Obsidian Vault."
        ),
        terms=("obsidian", "vault", "markdown", "icloud", "sync", "inbox"),
        body=(
            "Point Studio at your Obsidian vault and chats, classes, and agent "
            "memories are written as markdown notes with frontmatter. Edits you "
            "make in Obsidian flow back with Pull edits only. On iOS the vault "
            "usually lives in iCloud Drive under iCloud~md~obsidian; on a "
            "computer it is wherever you keep it. Notes you drop in the vault's "
            "Inbox folder can be imported into an agent's memory."
        ),
    ),
    GuideTopic(
        title="Teach an agent a skill",
        route="/studio#agents",
        where="Agents, tap the agent, the Teach a skill card.",
        terms=(
            "skill",
            "skills",
            "how-to",
            "instructions",
            "teach it",
            "teach an agent",
            "link",
        ),
        body=(
            "Open an agent on the Agents tab and use Teach a skill: paste a link "
            "or your own notes. The agent reads it and keeps a short how-to it "
            "follows from then on. It is the quickest way to give an agent a new "
            "habit without any training."
        ),
    ),
    GuideTopic(
        title="Teacher and student",
        route="/studio#learn",
        where="The Classroom tab (Learn): Open a class, then pick a teacher and a student.",
        terms=(
            "teacher",
            "student",
            "class",
            "classroom",
            "lesson",
            "exam",
            "school",
            "teach another",
            "another ai",
            "teach",
            "learn",
        ),
        body=(
            "Open a class on any topic. The teacher agent plans lessons, teaches "
            "them one at a time, and the student agent answers in the same "
            "classroom chat, so you can watch the learning happen. At the end the "
            "teacher writes a test, the student sits it without the lesson notes, "
            "and every answer is graded against the teacher's rubric. A pass can "
            "queue a light tune built from the class. A strong server model makes "
            "a good teacher for a small local student."
        ),
    ),
    GuideTopic(
        title="Light tuning",
        route="/studio#tune",
        where="Tuning & LoRA in the left sidebar (on a phone: MENU, Tuning, Open tuning): Make a tune pack.",
        terms=(
            "tune",
            "tuning",
            "finetune",
            "fine-tune",
            "light",
            "phone",
            "iphone",
            "profile",
            "tune pack",
        ),
        body=(
            "Light tuning learns an instruction pack, not weights: it searches for "
            "the shortest preamble, rules, and examples that best reproduce your "
            "sample answers, scored on held-out pairs. It is small enough to finish "
            "on a phone. Turn it on from chat settings and a fresh chat opens using "
            "the tuned profile. Real weight training is delegated to the cloud "
            "trainer when you pick the cloud backend."
        ),
    ),
    GuideTopic(
        title="LoRA weight training",
        route="/studio#tune",
        where="Tuning & LoRA in the left sidebar: the LoRA section. Rented GPU steps are on the job page.",
        terms=(
            "lora",
            "weights",
            "train",
            "training",
            "rented",
            "vps",
            "finetune",
            "adapter",
            "ollama",
        ),
        body=(
            "LoRA training changes a student model's actual weights. Server "
            "teachers write lessons on the topics you pick, plus tool-use lessons, "
            "then a trainer learns from them. Train on this computer if it has a "
            "suitable GPU, or on a rented GPU or VPS by running the worker "
            "command the job page shows under Run it on a rented GPU or VPS. The "
            "finished model downloads to this PC, installs into LM Studio and "
            "Ollama, and the student switches to it; you can switch back any time."
        ),
    ),
    GuideTopic(
        title="Settings",
        route="/studio#settings",
        where=(
            "Settings in the left sidebar (on a phone: MENU, Settings, Open settings). It has a search bar: type a word "
            "like voice or key. It opens only on the PC running Studio."
        ),
        terms=(
            "settings",
            "setting",
            "config",
            "configure",
            "configuration",
            "option",
            "options",
            "preferences",
            "api key",
            "admin",
            "provider",
        ),
        body=(
            "Every Free Claude Code option lives in Settings inside the app: "
            "providers and API keys, models, messaging, the Studio section, and "
            "voice. Type in the search bar to find one. Studio options include "
            "Main Model, Local Runtime URL, Fast Local Replies, Agent Temperature, "
            "Agent Commands, Web Access, Web Search API Key, voice, and Obsidian "
            "Vault. Knowledge & Memory also has its own search bar for its cards."
        ),
    ),
    GuideTopic(
        title="Desktop app on Windows",
        route="",
        where=(
            "Double-click scripts\\windows\\install-studio-app.cmd once. Then "
            "open FCC Studio from the Desktop or Start menu."
        ),
        terms=(
            "desktop",
            "windows",
            "shortcut",
            "icon",
            "startup",
            "launch",
            "exe",
            "physical app",
            "application",
            "start menu",
        ),
        body=(
            "The installer sets Studio up once and adds an FCC Studio icon to "
            "the Desktop and Start menu. Opening it starts the server hidden, "
            "shows a splash, and opens Studio in its own window without browser "
            "tabs; closing the window stops the server. Run the installer with "
            "-StartWithWindows to open it at sign-in, or -Uninstall to remove the "
            "icons (your agents and memory stay)."
        ),
    ),
    GuideTopic(
        title="Installing on iPhone",
        route="/studio#more",
        where="In Safari on the iPhone: Share, then Add to Home Screen. Setup help: Knowledge & Memory (MENU), Install on your iPhone.",
        terms=(
            "ios",
            "iphone",
            "ipad",
            "home screen",
            "pwa",
            "phone",
            "mobile",
            "tailscale",
            "install",
        ),
        body=(
            "Open this page in Safari on the same network as the server, tap Share, "
            "then Add to Home Screen. Studio then runs full screen with its own "
            "icon, safe-area padding, and touch-sized controls. Away from home, "
            "Tailscale gives the phone a private link to this PC, and tailscale "
            "serve adds the HTTPS the microphone needs."
        ),
    ),
    GuideTopic(
        title="Chats",
        route="/studio#chats",
        where="The Chats tab: every conversation and room, and New chat.",
        terms=(
            "chats",
            "chat",
            "history",
            "past",
            "conversations",
            "previous",
            "old",
            "new chat",
        ),
        body=(
            "The Chats tab keeps every conversation with every agent and every "
            "room, newest first. New chat starts one with any agent. Inside a "
            "chat, its settings can turn on light tuning or teacher mode for "
            "that conversation."
        ),
    ),
    GuideTopic(
        title="Troubleshooting",
        route="/studio#home",
        where=(
            "HUD: tap SYSTEM STATUS when it is not OPTIMAL. I list what is wrong "
            "right now at the top of this sheet."
        ),
        terms=(
            "wrong",
            "broken",
            "error",
            "errors",
            "fix",
            "problem",
            "problems",
            "issue",
            "not working",
            "doesn't work",
            "dont work",
            "attention",
            "failed",
            "crash",
            "trouble",
            "stuck",
            "offline",
        ),
        body=(
            "LOCAL MODELS OFFLINE means Studio cannot reach LM Studio: open LM "
            "Studio, load a model, and switch the server on in the Developer tab. "
            "ATTENTION means the last reply failed; the reason shows here. A "
            "model that 'has no key' is a server model without an API key: "
            "pick a local model with CHOOSE BRAIN or add the key in Settings. No "
            "microphone: use localhost on this PC or HTTPS on a phone. No voice: "
            "Knowledge & Memory (MENU), Main AI voice, Download the voice. Searches failing: add a "
            "search key. If the desktop app will not open, run "
            "install-studio-app.cmd again."
        ),
        asks=(
            "Why does it say LOCAL MODELS OFFLINE?",
            "How do I set up LM Studio?",
        ),
    ),
)

STARTER_QUESTIONS: tuple[str, ...] = (
    "What can this app do?",
    "How do I set up LM Studio?",
    "How do I talk to Jarvis with my voice?",
    "How do I get the Builder to make an app?",
    "How do I make replies faster?",
    "How do I add an agent?",
)

GUIDE_PERSONA = (
    "You are the Guide inside FCC Studio. Answer questions about this app in "
    "plain, friendly language, in at most six short sentences. Always say where "
    "to tap, using the button and page names exactly as written in your notes "
    "(they are shown in capitals on the HUD). Only describe features in your "
    "notes. If something is not there, say you are not sure and name the "
    "closest page. Never invent settings or buttons. If a problem listed under "
    "'This install right now' explains the question, start with its fix."
)

_WORD = re.compile(r"[a-z0-9][a-z0-9_+#-]*")
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "how",
        "can",
        "you",
        "what",
        "does",
        "this",
        "that",
        "with",
        "are",
        "your",
        "my",
        "is",
        "do",
        "to",
        "in",
        "on",
        "of",
        "it",
        "an",
        "be",
        "me",
        "get",
        "use",
        "where",
        "why",
        "when",
        "which",
        "one",
        "from",
        "into",
        "app",
        "there",
        "have",
        "about",
        "make",
        "work",
        "works",
        "want",
        "need",
        "show",
        "not",
        "working",
        "made",
    }
)


def _stem(word: str) -> str:
    """Fold simple English endings so 'models' finds 'model', 'tuning' finds 'tune'."""
    while True:
        for ending in ("ing", "ies", "es", "ed", "s", "e"):
            if word.endswith(ending) and len(word) - len(ending) >= 3:
                base = word[: -len(ending)]
                word = f"{base}y" if ending == "ies" else base
                break
        else:
            return word


def _stems(text: str) -> set[str]:
    words = (word for word in _WORD.findall(text.lower()) if word not in _STOP)
    return {stem for stem in map(_stem, words) if len(stem) > 1 and stem not in _STOP}


def _normal(text: str) -> str:
    return " ".join(_WORD.findall(text.lower().replace("'", "")))


@dataclass(frozen=True, slots=True)
class GuideProblem:
    """Something wrong with this install right now, and how to fix it."""

    title: str
    fix: str
    route: str = ""


@dataclass(frozen=True, slots=True)
class GuideState:
    """A snapshot of the install, so the guide can answer about this device."""

    agent_count: int = 0
    site_count: int = 0
    ready_models: int = 0
    guide_model: str = ""
    guide_model_ready: bool = False
    tuning_enabled: bool = False
    teacher_enabled: bool = False
    vault_configured: bool = False
    main_name: str = "Jarvis"
    main_model: str = ""
    main_model_ready: bool = True
    local_url: str = ""
    local_reachable: bool | None = None
    local_models: tuple[str, ...] = ()
    web_online: bool | None = None
    web_access: str = ""
    search_provider: str = ""
    search_problem: str = ""
    voice_speak: str = ""
    voice_ready: bool = True
    commands: str = ""
    approvals: int = 0
    busy_agents: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    last_error: str = ""
    problems: tuple[GuideProblem, ...] = ()

    def summary(self) -> str:
        """Render the snapshot as a few lines of context for the guide."""
        lines = [
            f"This install has {self.agent_count} agents"
            + (f" ({', '.join(self.agents)})" if self.agents else "")
            + f", {self.site_count} sites, {self.ready_models} downloaded models.",
            f"Guide model: {self.guide_model or 'none'}"
            f"{' (ready)' if self.guide_model_ready else ' (not downloaded)'}.",
        ]
        if self.main_model:
            lines.append(
                f"{self.main_name} uses {self.main_model}"
                f"{'' if self.main_model_ready else ' (cannot be reached)'}."
            )
        if self.local_reachable is not None:
            served = ", ".join(self.local_models[:6]) or "no models loaded"
            lines.append(
                f"Local runtime at {self.local_url or 'the local URL'} is "
                + (f"running: {served}." if self.local_reachable else "not reachable.")
            )
        if self.web_online is not None:
            lines.append(
                f"Internet: {'online' if self.web_online else 'offline'}, "
                f"web access {self.web_access or 'on'}, search by "
                f"{self.search_provider or 'DuckDuckGo'}."
            )
        if self.voice_speak:
            lines.append(
                f"Voice: {self.voice_speak}"
                f"{'' if self.voice_ready else ' (not downloaded yet)'}."
            )
        if self.commands:
            lines.append(f"Agent commands: {self.commands}.")
        if self.busy_agents:
            lines.append(f"Working right now: {', '.join(self.busy_agents)}.")
        lines.append(
            f"Light tuning is {'on' if self.tuning_enabled else 'off'}. "
            f"Teacher mode is {'on' if self.teacher_enabled else 'off'}. "
            f"Obsidian vault is "
            f"{'configured' if self.vault_configured else 'not configured'}."
        )
        if self.problems:
            lines.append(
                "Problems: " + " ".join(f"{p.title}: {p.fix}" for p in self.problems)
            )
        return "\n".join(lines)


def diagnose(state: GuideState) -> tuple[GuideProblem, ...]:
    """List what is wrong with this install right now, most urgent first."""
    problems: list[GuideProblem] = []
    local_main = state.main_model.startswith("local/")
    if state.local_reachable is False and (local_main or not state.main_model_ready):
        problems.append(
            GuideProblem(
                "Local models are offline",
                f"Studio cannot reach LM Studio at {state.local_url or 'http://localhost:1234/v1'}. "
                "Open LM Studio, load a model, and switch Start Server on in the "
                "Developer tab.",
                "/studio#models",
            )
        )
    elif state.local_reachable and not state.local_models and local_main:
        problems.append(
            GuideProblem(
                "No model is loaded",
                "LM Studio is running but serves no model. Load one in LM Studio, "
                "or use Choose a model from this PC on the Models page.",
                "/studio#models",
            )
        )
    if not state.main_model_ready and state.main_model and not local_main:
        problems.append(
            GuideProblem(
                f"{state.main_name}'s model has no key",
                f"{state.main_model} needs an API key. Pick a local model with "
                "CHOOSE BRAIN on the HUD, or add the key in Settings.",
                "/studio#home",
            )
        )
    if state.last_error:
        problems.append(
            GuideProblem(
                "The last reply failed",
                f"{state.last_error[:240]} Try again, or check the model with "
                "CHOOSE BRAIN.",
                "/studio#home",
            )
        )
    if state.approvals:
        problems.append(
            GuideProblem(
                f"{state.approvals} command{'s' if state.approvals != 1 else ''} "
                "waiting for you",
                "An agent asked to run a command. Press Run it or Deny on the HUD.",
                "/studio#home",
            )
        )
    if state.web_online is False:
        problems.append(
            GuideProblem(
                "This PC is offline",
                "Web tools are paused and agents work from memory. They come back "
                "on their own when the internet does.",
                "/studio#more",
            )
        )
    if state.search_problem:
        problems.append(
            GuideProblem(
                "Web search key problem",
                f"{state.search_problem} Fix it in Settings, under Studio, Web "
                "Search API Key.",
                "/studio#more",
            )
        )
    if state.voice_speak == "builtin" and not state.voice_ready:
        problems.append(
            GuideProblem(
                "The voice is not downloaded yet",
                "Knowledge & Memory (MENU), Main AI voice, Download the voice. Until then the browser "
                "voice speaks.",
                "/studio#more",
            )
        )
    return tuple(problems)


@dataclass(frozen=True, slots=True)
class GuideLink:
    """A place in the app the answer points to."""

    label: str
    route: str


@dataclass(frozen=True, slots=True)
class GuideAnswer:
    """What the guide replies, plus where the user should tap next."""

    text: str
    topics: tuple[str, ...] = ()
    route: str = ""
    offline: bool = False
    links: tuple[GuideLink, ...] = ()
    suggestions: tuple[str, ...] = ()


def knowledge_text() -> str:
    """Render everything the guide is allowed to claim about the app."""
    return "\n\n".join(_topic_text(topic) for topic in GUIDE_TOPICS)


def _topic_text(topic: GuideTopic) -> str:
    where = f"\nWhere: {topic.where}" if topic.where else ""
    return f"## {topic.title}{where}\n{topic.body}"


def topic_index() -> str:
    """One line per topic, so the model knows the whole app in a few hundred words."""
    return "\n".join(
        f"- {topic.title}: {topic.where or topic.body[:90]}" for topic in GUIDE_TOPICS
    )


def _score(topic: GuideTopic, stems: set[str], phrase: str) -> int:
    score = 0
    for term in topic.terms:
        if " " in term or "-" in term or "_" in term:
            score += 3 if f" {term} " in f" {phrase} " else 0
        elif _stem(term) in stems:
            score += 3
    score += 2 * len(_stems(topic.title) & stems)
    score += min(3, len(_stems(topic.body) & {s for s in stems if len(s) > 3}))
    return score


def match_topics(question: str, *, limit: int = 2) -> tuple[GuideTopic, ...]:
    """Return the topics that best match a question, best first."""
    stems = _stems(question)
    phrase = _normal(question)
    scored = [(topic, _score(topic, stems, phrase)) for topic in GUIDE_TOPICS]
    ranked = sorted(
        (pair for pair in scored if pair[1] >= 2),
        key=lambda pair: pair[1],
        reverse=True,
    )
    if not ranked:
        return ()
    best = ranked[0][1]
    return tuple(topic for topic, score in ranked[:limit] if score * 3 >= best)


def _links(topics: Sequence[GuideTopic]) -> tuple[GuideLink, ...]:
    seen: dict[str, GuideLink] = {}
    for topic in topics:
        if topic.route and topic.route not in seen:
            seen[topic.route] = GuideLink(page_name(topic.route), topic.route)
    return tuple(seen.values())


def page_name(route: str) -> str:
    """The name of the page a route opens, as the user sees it."""
    return {
        "home": "Command Center",
        "chats": "Chats",
        "agents": "Agents",
        "learn": "Classroom",
        "models": "Models",
        "tune": "Tuning & LoRA",
        "more": "Knowledge & Memory",
        "settings": "Settings",
    }.get(route.rsplit("#", 1)[-1], route)


def _suggestions(topics: Sequence[GuideTopic], question: str) -> tuple[str, ...]:
    asked = question.strip().lower().rstrip("?")
    picks: list[str] = []
    for ask in [a for topic in topics for a in topic.asks] + list(STARTER_QUESTIONS):
        if ask.lower().rstrip("?") != asked and ask not in picks:
            picks.append(ask)
    return tuple(picks[:3])


_TROUBLE = re.compile(
    r"\b(wrong|broken|errors?|fix|problems?|issues?|nothing|not working|"
    r"doesn'?t|dont|won'?t|can'?t|cant|failed|attention|offline|stuck|slow)\b"
)


def offline_answer(question: str, state: GuideState) -> GuideAnswer:
    """Answer from the built-in knowledge when no guide model is available."""
    matched = match_topics(question)
    trouble = bool(state.problems) and bool(_TROUBLE.search(question.lower()))
    parts: list[str] = []
    if trouble:
        parts.append(
            "Right now: "
            + " ".join(f"**{p.title}.** {p.fix}" for p in state.problems[:3])
        )
    if not matched and not trouble:
        titles = ", ".join(topic.title for topic in GUIDE_TOPICS[1:6])
        return GuideAnswer(
            text=(
                "I can explain any part of Studio: "
                f"{titles}, and more. Ask about one of those, or load a model in "
                "LM Studio so I can answer in my own words."
            ),
            offline=True,
            suggestions=STARTER_QUESTIONS[:3],
        )
    for topic in matched:
        where = f"\n*Where:* {topic.where}" if topic.where else ""
        parts.append(f"**{topic.title}** — {topic.body}{where}")
    links = _links(matched)
    first = state.problems[0].route if trouble else ""
    if first and all(link.route != first for link in links):
        links = (GuideLink(page_name(first), first), *links)
    return GuideAnswer(
        text="\n\n".join(parts),
        topics=tuple(topic.title for topic in matched),
        route=links[0].route if links else "",
        offline=True,
        links=links,
        suggestions=_suggestions(matched, question),
    )


class GuideAssistant:
    """Answer 'how does this app work' with a model, or from built-in help."""

    def __init__(
        self,
        *,
        router: StudioModelRouter,
        model: str,
        max_tokens: int = 400,
    ) -> None:
        self._router = router
        self._model = model
        self._max_tokens = max_tokens

    @property
    def model(self) -> str:
        return self._model

    def system_prompt(self, state: GuideState, question: str = "") -> str:
        """Compose the persona, the most relevant notes, the index, and this install.

        A small local model reads a short prompt much faster, so it gets the
        full text of the topics that match the question plus a one-line index
        of everything else, not the whole manual.
        """
        matched = match_topics(question, limit=3) if question else GUIDE_TOPICS
        notes = "\n\n".join(_topic_text(topic) for topic in matched) or "(none match)"
        return (
            f"{GUIDE_PERSONA}\n\n"
            f"# Notes for this question\n{notes}\n\n"
            f"# Everything in FCC Studio\n{topic_index()}\n\n"
            f"# This install right now\n{state.summary()}"
        )

    async def answer(
        self,
        question: str,
        state: GuideState,
        *,
        history: Sequence[ChatMessage] = (),
    ) -> GuideAnswer:
        """Answer one question, falling back to built-in help on any failure."""
        if not state.guide_model_ready and self._model.startswith("local/"):
            return offline_answer(question, state)
        matched = match_topics(question)
        try:
            reply = await self._router.complete(
                [*history[-6:], ChatMessage.user(question)],
                model=self._model,
                system=self.system_prompt(state, question),
                temperature=0.2,
                max_tokens=self._max_tokens,
            )
        except StudioLLMError:
            return offline_answer(question, state)
        text = reply.text.strip()
        if not text:
            return offline_answer(question, state)
        links = _links(matched)
        return GuideAnswer(
            text=text,
            topics=tuple(topic.title for topic in matched),
            route=links[0].route if links else "",
            links=links,
            suggestions=_suggestions(matched, question),
        )
