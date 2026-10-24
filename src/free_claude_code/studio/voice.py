"""Give the main AI a voice and let it hear the user, through speech servers.

Both directions use the OpenAI audio API shape, which local servers share:
Kokoro-FastAPI or Speaches for speech, whisper.cpp's server or Speaches for
transcription, or OpenAI itself. When nothing is configured, the browser's own
speech engines are used instead.
"""

import re
from dataclasses import dataclass

import httpx

from free_claude_code.core.json_types import JsonObject

MAX_SPEECH_CHARS = 1_500
MAX_AUDIO_BYTES = 25 * 1024 * 1024
_CODE_BLOCK = re.compile(r"```.*?(?:```|$)", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_URL = re.compile(r"https?://\S+")
_MARKS = re.compile(r"[*_#>|~]+")
_CITATION = re.compile(r"\s*\[\d+\]")


class VoiceError(RuntimeError):
    """Raised when the speech or transcription server cannot help."""


@dataclass(frozen=True, slots=True)
class SpeechAudio:
    """Synthesized speech ready to send to the browser."""

    audio: bytes
    content_type: str


def speakable(text: str, *, limit: int = MAX_SPEECH_CHARS) -> str:
    """Turn a chat reply into something that sounds right read aloud."""
    spoken = _CODE_BLOCK.sub(" I've put the code on screen. ", text)
    spoken = _LINK.sub(r"\1", spoken)
    spoken = _URL.sub("the link on screen", spoken)
    spoken = _INLINE_CODE.sub(r"\1", spoken)
    spoken = _CITATION.sub("", spoken)
    spoken = _MARKS.sub(" ", spoken)
    spoken = " ".join(spoken.split())
    if len(spoken) <= limit:
        return spoken
    cut = spoken[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: end + 1] if end > limit // 2 else cut).strip()


def _auth(key: str) -> dict[str, str]:
    return {"authorization": f"Bearer {key}"} if key else {}


def _failure(what: str, error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        detail = error.response.text[:200].strip()
        if status in {401, 403}:
            return f"The {what} server rejected the key ({status})."
        return f"The {what} server answered {status}: {detail}"
    return f"The {what} server could not be reached ({type(error).__name__})."


class VoiceService:
    """Speak replies and transcribe the user's speech via configured servers."""

    def __init__(
        self,
        *,
        speak_url: str = "",
        speak_key: str = "",
        speak_model: str = "kokoro",
        voice: str = "bm_george",
        listen_url: str = "",
        listen_key: str = "",
        listen_model: str = "whisper-1",
        language: str = "en",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._speak_url = speak_url.strip().rstrip("/")
        self._speak_key = speak_key.strip()
        self._speak_model = speak_model.strip() or "kokoro"
        self._voice = voice.strip() or "bm_george"
        self._listen_url = listen_url.strip().rstrip("/")
        self._listen_key = listen_key.strip() or (
            self._speak_key if self._listen_url == self._speak_url else ""
        )
        self._listen_model = listen_model.strip() or "whisper-1"
        self._language = language.strip()
        self._transport = transport
        self._timeout = timeout

    @property
    def server_speech(self) -> bool:
        return bool(self._speak_url)

    @property
    def server_listening(self) -> bool:
        return bool(self._listen_url)

    def status(self) -> JsonObject:
        """Say which engines speak and listen, without revealing keys."""
        return {
            "speak": "server" if self.server_speech else "browser",
            "listen": "server" if self.server_listening else "browser",
            "voice": self._voice if self.server_speech else "",
            "speak_url": self._speak_url,
            "listen_url": self._listen_url,
            "language": self._language,
        }

    async def speak(self, text: str) -> SpeechAudio:
        """Synthesize a reply as audio the browser can play."""
        if not self._speak_url:
            raise VoiceError("No speech server is set; the browser voice is used.")
        spoken = speakable(text)
        if not spoken:
            raise VoiceError("There is nothing to say.")
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._speak_url}/audio/speech",
                    json={
                        "model": self._speak_model,
                        "input": spoken,
                        "voice": self._voice,
                        "response_format": "mp3",
                    },
                    headers=_auth(self._speak_key),
                )
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise VoiceError(_failure("speech", error)) from error
        audio = response.content
        if not audio:
            raise VoiceError("The speech server sent back no audio.")
        content_type = response.headers.get("content-type", "audio/mpeg")
        if not content_type.startswith("audio/"):
            raise VoiceError("The speech server did not send audio.")
        return SpeechAudio(audio=audio, content_type=content_type.split(";")[0])

    async def transcribe(self, audio: bytes, *, content_type: str) -> str:
        """Turn one recorded turn of the user's speech into text."""
        if not self._listen_url:
            raise VoiceError("No transcription server is set.")
        if not audio:
            raise VoiceError("No audio was recorded.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise VoiceError("That recording is too long.")
        suffix = "wav" if "wav" in content_type else content_type.split("/")[-1][:8]
        fields = {"model": self._listen_model, "response_format": "json"}
        if self._language:
            fields["language"] = self._language
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._listen_url}/audio/transcriptions",
                    data=fields,
                    files={"file": (f"speech.{suffix}", audio, content_type)},
                    headers=_auth(self._listen_key),
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as error:
            raise VoiceError(_failure("transcription", error)) from error
        except ValueError as error:
            raise VoiceError("The transcription server sent back no text.") from error
        text = body.get("text") if isinstance(body, dict) else None
        return " ".join(str(text or "").split())
