"""Connectors: outside services the team can use, each set up with a token.

Most are MCP servers the service itself runs on the web (GitHub, Zapier for
Gmail, Google Sheets and Calendar, Slack, Notion and thousands more, Hugging
Face, Stripe, Supabase, Context7, DeepWiki): nothing is downloaded, the token
goes in a header, and agents use them with the mcp tool like any MCP server.
Two are built in: email (read the inbox over IMAP; sending writes a draft the
user approves first, unless they let agents send) and a webhook (post to a
Discord or Slack channel, or anywhere else).

Tokens are kept in one file only this user can read, and never sent back to
the app: the page shows that a field is set, not what it is.
"""

import asyncio
import email
import email.policy
import imaplib
import json
import os
import smtplib
import ssl
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

import httpx

from .extensions import McpServer

SECRET_SHOWN = "••••••"
MAX_MAILS = 20
MAIL_PREVIEW = 600
WEBHOOK_TIMEOUT = 15.0
MAIL_TIMEOUT = 30.0


class ConnectorError(ValueError):
    """A connector couldn't be set up or used; the message says why."""


@dataclass(frozen=True, slots=True)
class Field:
    key: str
    label: str
    secret: bool = True
    placeholder: str = ""
    optional: bool = False
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Connector:
    id: str
    name: str
    what: str
    kind: str
    """mcp (a web MCP server), email, or webhook (built in)."""
    url: str = ""
    header: str = "Authorization"
    scheme: str = "Bearer "
    fields: tuple[Field, ...] = ()
    get_it: str = ""
    """Where to get the token, in a sentence."""
    query: Mapping[str, str] = field(default_factory=dict)
    """Settings added to the address, e.g. Supabase's read_only."""


_TOKEN = Field("token", "Token")
CONNECTORS: tuple[Connector, ...] = (
    Connector(
        "zapier",
        "Zapier (Gmail, Sheets, Calendar, Slack, Notion, 8,000+ apps)",
        "One connector for most apps: send and read Gmail, add rows to Google "
        "Sheets, make Calendar events, post in Slack, update Notion, and the "
        "actions you pick in Zapier.",
        "mcp",
        url="https://mcp.zapier.com/api/v1/connect",
        fields=(_TOKEN,),
        get_it="mcp.zapier.com → Add MCP server → choose Other → Connect tab → "
        "Generate token (it is shown once). Pick the apps and actions there.",
    ),
    Connector(
        "github",
        "GitHub",
        "Repositories, issues, pull requests, code search, and files on GitHub.",
        "mcp",
        url="https://api.githubcopilot.com/mcp/",
        fields=(_TOKEN,),
        get_it="github.com → Settings → Developer settings → Personal access "
        "tokens: make one with only the repositories and rights it needs.",
    ),
    Connector(
        "huggingface",
        "Hugging Face",
        "Find models, datasets, papers, and Spaces, and run some Spaces.",
        "mcp",
        url="https://huggingface.co/mcp",
        fields=(_TOKEN,),
        get_it="huggingface.co → Settings → Access Tokens (a read token is enough).",
    ),
    Connector(
        "stripe",
        "Stripe",
        "Customers, payments, invoices, payment links, and products on Stripe.",
        "mcp",
        url="https://mcp.stripe.com",
        fields=(Field("token", "Restricted API key", placeholder="rk_live_..."),),
        get_it="Stripe Dashboard → Developers → API keys → Create restricted "
        "key with only what agents may do (use a test-mode key to try it).",
    ),
    Connector(
        "supabase",
        "Supabase (read only)",
        "Look at a Supabase project's tables, logs, and docs; read only.",
        "mcp",
        url="https://mcp.supabase.com/mcp",
        fields=(
            Field("token", "Personal access token"),
            Field(
                "project_ref",
                "Project ref",
                secret=False,
                optional=True,
                placeholder="abcdefghijklmnop",
            ),
        ),
        get_it="supabase.com → Dashboard → Account → Access Tokens.",
        query={"read_only": "true"},
    ),
    Connector(
        "context7",
        "Context7 (code library docs)",
        "Up-to-date docs and examples for programming libraries, for the "
        "Coder and Builder. Works without a key; a free key gives more.",
        "mcp",
        url="https://mcp.context7.com/mcp",
        header="CONTEXT7_API_KEY",
        scheme="",
        fields=(Field("token", "API key", optional=True),),
        get_it="context7.com → sign in → Dashboard → API key (optional).",
    ),
    Connector(
        "deepwiki",
        "DeepWiki (any public GitHub repo explained)",
        "Ask how a public GitHub repository works and read its generated wiki. "
        "No account needed.",
        "mcp",
        url="https://mcp.deepwiki.com/mcp",
        fields=(),
        get_it="Nothing to set up: switch it on.",
    ),
    Connector(
        "email",
        "Email (built in)",
        "Agents read your inbox and write emails. Sending makes a draft you "
        "approve on this page, unless you let agents send on their own.",
        "email",
        fields=(
            Field(
                "provider",
                "Provider",
                secret=False,
                choices=("gmail", "yahoo", "icloud", "other"),
            ),
            Field("address", "Email address", secret=False),
            Field("password", "App password"),
            Field("smtp_host", "SMTP server (other)", secret=False, optional=True),
            Field("imap_host", "IMAP server (other)", secret=False, optional=True),
            Field(
                "send_without_asking",
                "Agents may send without asking",
                secret=False,
                optional=True,
                choices=("no", "yes"),
            ),
        ),
        get_it="Use an app password, not your normal one: Gmail → Google Account "
        "→ Security → App passwords (needs 2-Step Verification); iCloud and Yahoo "
        "have the same in their security settings. Outlook.com no longer allows "
        "app passwords for mail apps: connect Outlook through Zapier instead.",
    ),
    Connector(
        "webhook",
        "Webhook (Discord, Slack, any app)",
        "Agents post messages to a channel: when a plan finishes, a site is "
        "built, or something needs you.",
        "webhook",
        fields=(
            Field(
                "url",
                "Webhook address",
                placeholder="https://discord.com/api/webhooks/...",
            ),
        ),
        get_it="Discord: channel → Edit → Integrations → Webhooks → New → Copy "
        "URL. Slack: api.slack.com/apps → Incoming Webhooks.",
    ),
)
BY_ID = {connector.id: connector for connector in CONNECTORS}

MAIL_SERVERS = {
    "gmail": ("smtp.gmail.com", "imap.gmail.com"),
    "yahoo": ("smtp.mail.yahoo.com", "imap.mail.yahoo.com"),
    "icloud": ("smtp.mail.me.com", "imap.mail.me.com"),
}


def connector(connector_id: str) -> Connector:
    found = BY_ID.get(connector_id)
    if found is None:
        raise ConnectorError(f"No connector called {connector_id!r}.")
    return found


def check_values(spec: Connector, values: Mapping[str, str]) -> dict[str, str]:
    """The values for a connector: known fields only, the required ones set."""
    clean: dict[str, str] = {}
    for item in spec.fields:
        value = str(values.get(item.key) or "").strip()
        if item.choices and value and value not in item.choices:
            raise ConnectorError(
                f"{item.label} must be one of {', '.join(item.choices)}."
            )
        if not value and not item.optional:
            if item.choices:
                value = item.choices[0]
            else:
                raise ConnectorError(f"{spec.name} needs {item.label}.")
        if value:
            clean[item.key] = value
    if spec.kind == "webhook" and not clean.get("url", "").startswith("https://"):
        raise ConnectorError("The webhook address must start with https://.")
    if spec.kind == "email":
        if "@" not in clean.get("address", ""):
            raise ConnectorError("That email address doesn't look right.")
        if clean.get("provider") == "other" and not (
            clean.get("smtp_host") and clean.get("imap_host")
        ):
            raise ConnectorError(
                "For another provider, give its SMTP and IMAP servers."
            )
    return clean


def mcp_server(spec: Connector, values: Mapping[str, str]) -> McpServer:
    """A web connector as an MCP server the team's mcp tool can use."""
    query = dict(spec.query)
    if values.get("project_ref"):
        query["project_ref"] = values["project_ref"]
    url = spec.url + (f"?{httpx.QueryParams(query)}" if query else "")
    headers = {}
    if values.get("token"):
        headers[spec.header] = f"{spec.scheme}{values['token']}"
    return McpServer(name=spec.id, url=url, headers=headers, enabled=True)


def view(spec: Connector, values: Mapping[str, str] | None) -> dict[str, Any]:
    """A connector as the app shows it: secrets only as set or not."""
    values = values or {}
    return {
        "id": spec.id,
        "name": spec.name,
        "what": spec.what,
        "kind": spec.kind,
        "get_it": spec.get_it,
        "connected": values.get("_on") == "yes",
        "fields": [
            {
                "key": item.key,
                "label": item.label,
                "secret": item.secret,
                "optional": item.optional,
                "placeholder": item.placeholder,
                "choices": list(item.choices),
                "value": (SECRET_SHOWN if values.get(item.key) else "")
                if item.secret
                else values.get(item.key, ""),
            }
            for item in spec.fields
        ],
    }


class ConnectorStore:
    """Connected services and email drafts, in one file only the user reads."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError, ValueError:
            return {"connectors": {}, "drafts": []}
        return data if isinstance(data, dict) else {"connectors": {}, "drafts": []}

    def _write(self, data: Mapping[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
        os.replace(temporary, self._path)

    def all(self) -> dict[str, dict[str, str]]:
        found = self._read().get("connectors") or {}
        return {
            key: dict(value) for key, value in found.items() if isinstance(value, dict)
        }

    def values(self, connector_id: str) -> dict[str, str]:
        return self.all().get(connector_id, {})

    def save(self, connector_id: str, values: Mapping[str, str]) -> None:
        data = self._read()
        data.setdefault("connectors", {})[connector_id] = dict(values)
        self._write(data)

    def remove(self, connector_id: str) -> None:
        data = self._read()
        data.setdefault("connectors", {}).pop(connector_id, None)
        self._write(data)

    def drafts(self) -> list[dict[str, Any]]:
        return [d for d in self._read().get("drafts") or [] if isinstance(d, dict)]

    def add_draft(self, draft: Mapping[str, Any]) -> dict[str, Any]:
        data = self._read()
        saved = {"id": f"drf_{uuid.uuid4().hex[:12]}", "at": int(time.time()), **draft}
        data.setdefault("drafts", []).append(saved)
        self._write(data)
        return saved

    def take_draft(self, draft_id: str) -> dict[str, Any]:
        data = self._read()
        drafts = data.setdefault("drafts", [])
        found = next((d for d in drafts if d.get("id") == draft_id), None)
        if found is None:
            raise ConnectorError("That draft is gone.")
        drafts.remove(found)
        self._write(data)
        return found


# ------------------------------------------------------------ built in


class Builtin(Protocol):
    name: str

    def tools(self) -> list[tuple[str, str, dict[str, Any]]]: ...

    async def call(
        self, tool: str, arguments: Mapping[str, Any]
    ) -> tuple[str, bool]: ...

    async def test(self) -> str: ...


def _hosts(values: Mapping[str, str]) -> tuple[str, str]:
    provider = values.get("provider", "gmail")
    if provider in MAIL_SERVERS:
        return MAIL_SERVERS[provider]
    return values.get("smtp_host", ""), values.get("imap_host", "")


def make_message(
    values: Mapping[str, str], to: str, subject: str, body: str
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = values["address"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message


def send_now(values: Mapping[str, str], message: EmailMessage) -> None:
    """Send over SMTP (SSL on 465, else STARTTLS on 587)."""
    smtp_host, _ = _hosts(values)
    context = ssl.create_default_context()
    if smtp_host in {"smtp.gmail.com", "smtp.mail.yahoo.com"}:
        with smtplib.SMTP_SSL(
            smtp_host, 465, timeout=MAIL_TIMEOUT, context=context
        ) as smtp:
            smtp.login(values["address"], values["password"])
            smtp.send_message(message)
        return
    with smtplib.SMTP(smtp_host, 587, timeout=MAIL_TIMEOUT) as smtp:
        smtp.starttls(context=context)
        smtp.login(values["address"], values["password"])
        smtp.send_message(message)


def read_mail(
    values: Mapping[str, str], *, count: int, unread_only: bool, search: str
) -> str:
    """The newest mails in the inbox, without marking them read."""
    _, imap_host = _hosts(values)
    with imaplib.IMAP4_SSL(imap_host, timeout=MAIL_TIMEOUT) as imap:
        imap.login(values["address"], values["password"])
        imap.select("INBOX", readonly=True)
        criteria: list[str] = ["UNSEEN"] if unread_only else ["ALL"]
        if search:
            # IMAP search words go as plain ASCII text in quotes.
            words = "".join(c for c in search if c.isascii() and c not in '"\\')
            criteria += ["TEXT", f'"{words}"']
        _, found = imap.search(None, *criteria)
        ids = (found[0] or b"").split()[-count:]
        lines = []
        for mail_id in reversed(ids):
            _, data = imap.fetch(mail_id, "(BODY.PEEK[])")
            raw = next((part[1] for part in data if isinstance(part, tuple)), b"")
            mail = email.message_from_bytes(raw, policy=email.policy.default)
            body = mail.get_body(preferencelist=("plain", "html"))
            text = body.get_content() if body is not None else ""
            lines.append(
                f"From: {mail['from']}\nDate: {mail['date']}\nSubject: {mail['subject']}\n"
                + " ".join(str(text).split())[:MAIL_PREVIEW]
            )
    if not lines:
        return "No mail matches." if search or not unread_only else "No unread mail."
    return "\n\n".join(lines)


class EmailService:
    name = "email"

    def __init__(self, values: Mapping[str, str], store: ConnectorStore) -> None:
        self._values = dict(values)
        self._store = store

    def tools(self) -> list[tuple[str, str, dict[str, Any]]]:
        return [
            (
                "read_inbox",
                "The newest mails in the inbox (sender, date, subject, start of the text).",
                {
                    "count": "how many (default 5, at most 20)",
                    "unread_only": "true or false (default true)",
                    "search": "words to look for (optional)",
                },
            ),
            (
                "send_email",
                "Write an email from the user's address. Unless the user lets "
                "agents send, it becomes a draft the user approves.",
                {"to": "address", "subject": "subject line", "body": "the text"},
            ),
        ]

    async def call(self, tool: str, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        if tool == "read_inbox":
            count = max(1, min(MAX_MAILS, int(arguments.get("count") or 5)))
            unread = str(arguments.get("unread_only", True)).lower() not in {
                "false",
                "0",
                "no",
            }
            text = await asyncio.to_thread(
                read_mail,
                self._values,
                count=count,
                unread_only=unread,
                search=str(arguments.get("search") or "").strip(),
            )
            return text, False
        if tool == "send_email":
            to = str(arguments.get("to") or "").strip()
            subject = str(arguments.get("subject") or "").strip()
            body = str(arguments.get("body") or "").strip()
            if "@" not in to or not body:
                return "Say who to send it to and what it says.", True
            if self._values.get("send_without_asking") == "yes":
                await asyncio.to_thread(
                    send_now,
                    self._values,
                    make_message(self._values, to, subject, body),
                )
                return f"Sent to {to}.", False
            draft = self._store.add_draft({"to": to, "subject": subject, "body": body})
            return (
                f"Draft to {to} saved for the user to approve (Connectors page, or "
                f"the HQ approvals desk). Tell the user it is waiting. Draft {draft['id']}.",
                False,
            )
        return f"The email connector has no tool {tool!r}.", True

    async def test(self) -> str:
        await asyncio.to_thread(
            read_mail, self._values, count=1, unread_only=True, search=""
        )
        return f"Signed in to {self._values['address']}."


def webhook_body(url: str, text: str) -> dict[str, str]:
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        return {"content": text[:2000]}
    if "hooks.slack.com" in url:
        return {"text": text}
    return {"text": text, "content": text}


class WebhookService:
    name = "webhook"

    def __init__(
        self,
        values: Mapping[str, str],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = values["url"]
        self._transport = transport

    def tools(self) -> list[tuple[str, str, dict[str, Any]]]:
        return [
            (
                "post_message",
                "Post a message to the user's channel (Discord, Slack, ...).",
                {"text": "the message"},
            )
        ]

    async def _post(self, text: str) -> None:
        async with httpx.AsyncClient(
            timeout=WEBHOOK_TIMEOUT, transport=self._transport
        ) as client:
            response = await client.post(self._url, json=webhook_body(self._url, text))
        if response.status_code >= 400:
            raise ConnectorError(f"The webhook answered {response.status_code}.")

    async def call(self, tool: str, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        if tool != "post_message":
            return f"The webhook has no tool {tool!r}.", True
        text = str(arguments.get("text") or "").strip()
        if not text:
            return "Say what to post.", True
        await self._post(text)
        return "Posted.", False

    async def test(self) -> str:
        await self._post("LCC Studio is connected to this channel.")
        return "Posted a test message."


def describe_tools(service: Builtin) -> str:
    return "\n".join(
        f"- {name}: {about} Arguments: "
        + ", ".join(f"{key} ({hint})" for key, hint in args.items())
        for name, about, args in service.tools()
    )
