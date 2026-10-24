"""Hold a small model's tool calls to what the user actually said.

A 4B model asked 'which model is the Builder using?' sometimes calls the
switch form of the tool, and one asked to 'add eggs to my list' sometimes
copies a reminder time from an example. The call is trimmed to the user's
words before it runs, and the trimmed call is what the playbook learns.
"""

import re
from dataclasses import replace

from .llm import ToolCall

_TIME = re.compile(
    r"\b(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\d{1,2}:\d{2}|at\s+\d{1,2}\b|"
    r"in\s+(?:a|an|one|\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?|m|min|mins|minutes?|"
    r"h|hr|hrs|hours?|d|days?|weeks?)\b|today|tonight|tomorrow|morning|afternoon|"
    r"evening|noon|midnight|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday|next\s+week|later|\d{4}-\d{2}-\d{2})",
    re.I,
)
_COMMAND = re.compile(
    r"^\s*(?:(?:hey|ok|okay|yo)\s+)?(?:jarvis\s*[,:!]?\s*)?(?:please\s+)?"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?"
    r"(?:switch|change|set|swap|use|give|put|make|assign|move|try|turn|add|remove|"
    r"take|enable|disable|allow|let|forget|remember|save|note|teach)\b",
    re.I,
)
_VERBS = (
    r"(?:switch|change|set|swap|use|give|put|make|assign|move|try|turn|add|remove|"
    r"take|enable|disable|allow|let|forget|remember|save|note|teach)\b"
)
_LATER_COMMAND = re.compile(
    rf"(?:[.?!,;]|\b(?:then|and|also|but|so)\b)\s*(?:please\s+)?"
    rf"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?{_VERBS}",
    re.I,
)
_QUESTION = re.compile(
    r"^\s*(?:(?:hey|ok|okay|yo)\s+)?(?:jarvis\s*[,:!]?\s*)?"
    r"(?:which|what|what's|whats|who|whose|is|are|does|do|did|how|why|where|when|"
    r"tell\s+me|show|list|check|can\s+you\s+(?:tell|show|check|list))\b",
    re.I,
)
SHOW_ONLY = frozenset(
    {"every_tool_on", "every_tool_off", "tool_on", "tool_off", "add_memory", "forget"}
)


def names_a_time(said: str) -> bool:
    return bool(_TIME.search(said))


def asks_only(said: str) -> bool:
    """A question or a 'show me', not a 'switch ...' or 'can you give ...'."""
    text = said.strip()
    if _COMMAND.match(text) or _LATER_COMMAND.search(text):
        return False
    return text.endswith("?") or bool(_QUESTION.match(text))


def guarded(call: ToolCall, said: str) -> ToolCall:
    """The call, trimmed to what the user's message asked for."""
    if not said.strip():
        return call
    arguments = dict(call.arguments)
    if call.name == "agent_model" and arguments.get("model") and asks_only(said):
        arguments.pop("model")
    elif (
        call.name == "manage_agent"
        and str(arguments.get("action") or "") in SHOW_ONLY
        and asks_only(said)
    ):
        arguments = {
            "action": "show",
            **({"agent": arguments["agent"]} if arguments.get("agent") else {}),
        }
    elif (
        call.name == "todo"
        and str(arguments.get("action") or "").lower() == "add"
        and arguments.get("due")
        and not names_a_time(said)
    ):
        arguments.pop("due")
    if arguments == call.arguments:
        return call
    return replace(call, arguments=arguments)
