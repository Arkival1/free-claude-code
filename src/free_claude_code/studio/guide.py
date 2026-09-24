"""The small preloaded model that explains this app to the user."""

from collections.abc import Sequence
from dataclasses import dataclass

from .llm import ChatMessage, StudioLLMError, StudioModelRouter
from .memory import keywords


@dataclass(frozen=True, slots=True)
class GuideTopic:
    """One thing the guide knows how to explain, and where it lives."""

    title: str
    route: str
    terms: tuple[str, ...]
    body: str


GUIDE_TOPICS: tuple[GuideTopic, ...] = (
    GuideTopic(
        title="Chats and agents",
        route="/studio#chats",
        terms=("chat", "agent", "assistant", "talk", "ask", "start", "new"),
        body=(
            "Every conversation belongs to an agent. An agent has its own model, "
            "its own memory, its own tools, and optionally its own light tune. "
            "Create one on the Agents tab, then start a chat with it. Agents with "
            "tools can search the web, read pages, and write files into a website "
            "workspace."
        ),
    ),
    GuideTopic(
        title="Talking to the main AI",
        route="/studio#more",
        terms=(
            "voice",
            "talk",
            "speak",
            "listen",
            "microphone",
            "mic",
            "jarvis",
            "hear",
            "hud",
            "dashboard",
        ),
        body=(
            "The main AI speaks with a built-in neural voice and understands you "
            "with Whisper, both on this PC and offline after a one-time download. "
            "The HUD is his command center: the gold core in the middle reacts "
            "as he works, listens, and speaks, the agent chat room is top right, "
            "and quick commands give the team jobs. "
            "In the HUD, tap the orb or TALK: you speak, he answers aloud, then "
            "listens again. More, Main AI voice has Hear him. The microphone works "
            "on this PC at localhost; on a phone, open Studio over HTTPS with "
            "tailscale serve."
        ),
    ),
    GuideTopic(
        title="Internet access",
        route="/studio#more",
        terms=(
            "internet",
            "web",
            "search",
            "online",
            "research",
            "key",
            "token",
            "brave",
            "tavily",
        ),
        body=(
            "Every agent can search the web and read pages, local models too: "
            "Studio does the browsing and hands them the results. Searches use "
            "DuckDuckGo with no key, which often gets blocked, so add a Brave "
            "Search, Tavily, or Serper key in admin settings under Studio, Web "
            "Search API Key, or point it at your own SearXNG. The Researcher "
            "agent is built for deep research; ask the main AI to send it, or "
            "mention @Researcher in a room. More, Internet access tests it. "
            "When this PC goes offline, web tools pause and agents work from "
            "memory; they come back on their own when the internet does."
        ),
    ),
    GuideTopic(
        title="Research and teaching agents",
        route="/studio#agents",
        terms=(
            "research",
            "sources",
            "reddit",
            "youtube",
            "teach",
            "skill",
            "learn",
            "builder",
            "stuck",
            "error",
            "helper",
            "ideas",
            "brainstorm",
        ),
        body=(
            "The research tool reads ten or more sources per question: the web, "
            "Reddit threads, YouTube transcripts, Stack Overflow, GitHub, MDN, and "
            "dev.to. The Researcher tests code it finds with test_code in its "
            "Research lab before recommending it. The Builder calls ask_researcher "
            "when it is stuck on an error; the Helper then filters what was found "
            "into a plan that fits the Builder's work. Any agent can ask_helper to "
            "brainstorm. Teach any agent a skill from its page: "
            "paste a link or notes and it keeps a short how-to it follows. Add "
            "agents with the + button and pick a role and tools."
        ),
    ),
    GuideTopic(
        title="Agent tasks",
        route="/studio#agents",
        terms=("task", "autonomous", "run", "goal", "build", "website", "site"),
        body=(
            "Give an agent a goal and it runs a bounded tool loop: search, fetch, "
            "write files, check its work, then finish with a report. Attach a site "
            "to the task and everything it writes lands in that site, which you can "
            "preview and download as a zip."
        ),
    ),
    GuideTopic(
        title="Local models",
        route="/studio#models",
        terms=("local", "model", "download", "gguf", "offline", "phone", "install"),
        body=(
            "The Models tab downloads model files straight to this device, with "
            "resume, checksums, and archive extraction. Curated small models are "
            "listed first; any direct http(s) URL also works. A downloaded model is "
            "used by referring to it as local/<model id>, served by the local "
            "runtime set in Studio settings."
        ),
    ),
    GuideTopic(
        title="Light tuning",
        route="/studio#tuning",
        terms=("tune", "tuning", "finetune", "fine-tune", "train", "adapter", "light"),
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
        terms=(
            "lora",
            "weights",
            "train",
            "training",
            "gpu",
            "rented",
            "vps",
            "finetune",
            "fine-tune",
            "adapter",
            "ollama",
        ),
        body=(
            "LoRA training changes a student model's actual weights. Server "
            "teachers write lessons on the topics you pick, plus tool-use lessons, "
            "then a trainer learns from them. Train on this computer if it has a "
            "GPU, or on a rented GPU or VPS by running the worker command the job "
            "page shows. The finished adapter installs into Ollama and the student "
            "switches to it; you can switch back any time."
        ),
    ),
    GuideTopic(
        title="Building apps",
        route="/studio#agents",
        terms=(
            "app",
            "apps",
            "build",
            "project",
            "command",
            "npm",
            "python",
            "run",
            "approve",
            "code",
        ),
        body=(
            "Agents work in a project folder and can write any source file: web "
            "pages, Python, TypeScript, configs. If you allow it in settings, they "
            "can also run commands like npm install, builds, and tests. In Ask "
            "mode each command shows up in the chat with Run it and Deny buttons."
        ),
    ),
    GuideTopic(
        title="Teacher and student",
        route="/studio#school",
        terms=(
            "teacher",
            "student",
            "class",
            "lesson",
            "teach",
            "learn",
            "test",
            "exam",
            "school",
        ),
        body=(
            "Open a class on any topic. The teacher agent plans lessons, teaches "
            "them one at a time, and the student agent answers in the same "
            "classroom chat, so you can watch the learning happen. At the end the "
            "teacher writes a test, the student sits it without the lesson notes, "
            "and every answer is graded against the teacher's rubric. A pass can "
            "queue a light tune built from the class."
        ),
    ),
    GuideTopic(
        title="Memory",
        route="/studio#memory",
        terms=("memory", "remember", "forget", "recall", "notes"),
        body=(
            "Each agent keeps working notes for the current thread and long-term "
            "memories it can recall later. Agents write memories with the remember "
            "tool; you can read, promote, or delete any of them on the Memory tab."
        ),
    ),
    GuideTopic(
        title="Obsidian",
        route="/studio#obsidian",
        terms=("obsidian", "vault", "markdown", "notes", "icloud", "sync"),
        body=(
            "Point Studio at your Obsidian vault and chats, classes, and agent "
            "memories are written as markdown notes with frontmatter. On iOS the "
            "vault usually lives in iCloud Drive under iCloud~md~obsidian; on a "
            "computer it is wherever you keep it. Notes you drop in the vault's "
            "Inbox folder can be imported into an agent's memory."
        ),
    ),
    GuideTopic(
        title="Installing on iPhone",
        route="/studio#settings",
        terms=("ios", "iphone", "ipad", "install", "home", "screen", "pwa", "app"),
        body=(
            "Open this page in Safari on the same network as the server, tap Share, "
            "then Add to Home Screen. Studio then runs full screen with its own "
            "icon, safe-area padding, and touch-sized controls."
        ),
    ),
)

GUIDE_PERSONA = (
    "You are the built-in guide for FCC Studio. You run on a small local model, "
    "so answer in at most six short sentences, in plain language. Only describe "
    "features listed in your knowledge below. If something is not there, say you "
    "are not sure and suggest the closest tab. Never invent settings."
)


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

    def summary(self) -> str:
        """Render the snapshot as a line of context for the guide."""
        return (
            f"This install has {self.agent_count} agents, {self.site_count} sites, "
            f"{self.ready_models} downloaded models. "
            f"Guide model: {self.guide_model or 'none'}"
            f"{' (ready)' if self.guide_model_ready else ' (not downloaded)'}. "
            f"Light tuning is {'on' if self.tuning_enabled else 'off'}. "
            f"Teacher mode is {'on' if self.teacher_enabled else 'off'}. "
            f"Obsidian vault is "
            f"{'configured' if self.vault_configured else 'not configured'}."
        )


@dataclass(frozen=True, slots=True)
class GuideAnswer:
    """What the guide replies, plus where the user should tap next."""

    text: str
    topics: tuple[str, ...] = ()
    route: str = ""
    offline: bool = False


def knowledge_text() -> str:
    """Render everything the guide is allowed to claim about the app."""
    return "\n\n".join(
        f"## {topic.title} ({topic.route})\n{topic.body}" for topic in GUIDE_TOPICS
    )


def match_topics(question: str, *, limit: int = 2) -> tuple[GuideTopic, ...]:
    """Return the topics that best match a question, by keyword overlap."""
    terms = set(keywords(question, limit=16)) | {
        word for word in question.lower().split() if len(word) > 2
    }
    scored = [
        (topic, sum(1 for term in topic.terms if term in terms))
        for topic in GUIDE_TOPICS
    ]
    ranked = sorted(scored, key=lambda pair: pair[1], reverse=True)
    return tuple(topic for topic, score in ranked[:limit] if score > 0)


def offline_answer(question: str, state: GuideState) -> GuideAnswer:
    """Answer from the built-in knowledge when no guide model is available."""
    matched = match_topics(question)
    if not matched:
        titles = ", ".join(topic.title for topic in GUIDE_TOPICS[:4])
        return GuideAnswer(
            text=(
                "I can explain any part of Studio: "
                f"{titles}, and more. Ask about one of those, or download the "
                "guide model on the Models tab so I can answer in my own words."
            ),
            offline=True,
        )
    body = "\n\n".join(f"**{topic.title}** — {topic.body}" for topic in matched)
    return GuideAnswer(
        text=body,
        topics=tuple(topic.title for topic in matched),
        route=matched[0].route,
        offline=True,
    )


class GuideAssistant:
    """Answer 'how does this app work' with the small preloaded model."""

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

    def system_prompt(self, state: GuideState) -> str:
        """Compose the persona, the app knowledge, and this install's state."""
        return (
            f"{GUIDE_PERSONA}\n\n"
            f"# What FCC Studio can do\n{knowledge_text()}\n\n"
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
                [*history, ChatMessage.user(question)],
                model=self._model,
                system=self.system_prompt(state),
                temperature=0.2,
                max_tokens=self._max_tokens,
            )
        except StudioLLMError:
            return offline_answer(question, state)
        text = reply.text.strip()
        if not text:
            return offline_answer(question, state)
        return GuideAnswer(
            text=text,
            topics=tuple(topic.title for topic in matched),
            route=matched[0].route if matched else "",
        )
