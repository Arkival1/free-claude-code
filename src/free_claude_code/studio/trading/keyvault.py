"""Trading platform keys, encrypted on this PC.

- Each platform's keys are encrypted (AES-256-GCM, the platform's id bound
  in) with a data key that is itself locked by Windows (DPAPI): only this
  Windows user on this PC can unlock it, so a copied file is useless
  elsewhere. Nothing is ever kept in plain text.
- Where no such protection exists (not Windows), keys can't be saved and
  FCC stays in practice mode: there is no weaker fallback.
- Keys saved by older versions in plain text are moved in, and the plain
  file is removed once the encrypted copy is safely written.
- Each key set records whether it is for a practice (demo or paper)
  account or a real one, when it was saved and when it was last replaced.
  Switching a set between practice and real needs its secrets typed again,
  so practice and real credentials are never the same stored secret.
- Every secret value can be listed for redaction, so none reaches the feed,
  the audit trail or the logs.
"""

import base64
import ctypes
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from free_claude_code.core.json_types import JsonObject

VERSION = 1


class VaultError(RuntimeError):
    """The vault can't be used (no protection here, or it can't be unlocked)."""


class Protector(Protocol):
    name: str

    def wrap(self, key: bytes) -> bytes: ...

    def unwrap(self, blob: bytes) -> bytes: ...


class Dpapi:
    """Windows' data protection for the current user."""

    name = "Windows DPAPI"

    def wrap(self, key: bytes) -> bytes:
        return _dpapi(key, protect=True)

    def unwrap(self, blob: bytes) -> bytes:
        return _dpapi(blob, protect=False)


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = (
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        )

    # Both exist only on Windows (where this runs).
    windll = getattr(ctypes, "WinDLL", None)
    last_error = getattr(ctypes, "get_last_error", None)
    if windll is None or last_error is None:
        raise VaultError("Windows' key protection isn't available here.")
    crypt32 = windll("crypt32", use_last_error=True)
    kernel32 = windll("kernel32", use_last_error=True)
    buffer = ctypes.create_string_buffer(data, len(data))
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = Blob()
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ui_forbidden = 0x1
    if not call(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        ui_forbidden,
        ctypes.byref(result),
    ):
        raise VaultError(
            "Windows couldn't "
            + ("protect" if protect else "unlock")
            + f" the trading keys (error {last_error()})."
        )
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def default_protector() -> Protector | None:
    """Windows' protection on Windows; nothing (no saving keys) elsewhere."""
    return Dpapi() if sys.platform == "win32" else None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: object) -> bytes:
    if not isinstance(text, str):
        raise VaultError("The key file is damaged.")
    try:
        return base64.b64decode(text, validate=True)
    except ValueError as error:
        raise VaultError("The key file is damaged.") from error


class KeyVault:
    def __init__(
        self,
        path: Path,
        *,
        protector: Protector | None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path
        self._protector = protector
        self._clock = clock
        self._key: bytes | None = None

    # ------------------------------------------------------------ state

    @property
    def available(self) -> bool:
        return self._protector is not None

    @property
    def why_unavailable(self) -> str:
        if self._protector is not None:
            return ""
        return (
            "Secure key storage isn't available on this computer (FCC uses "
            "Windows' own protection), so keys can't be saved and FCC stays in "
            "practice mode."
        )

    @property
    def protection(self) -> str:
        return self._protector.name if self._protector is not None else ""

    def _read(self) -> dict[str, object]:
        try:
            found = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except ValueError as error:
            raise VaultError("The key file is damaged.") from error
        return found if isinstance(found, dict) else {}

    def _write(self, data: Mapping[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
        os.replace(temporary, self._path)

    def _data_key(self, data: dict[str, object]) -> bytes:
        if self._protector is None:
            raise VaultError(self.why_unavailable)
        if self._key is not None:
            return self._key
        wrapped = data.get("key")
        if wrapped is None:
            key = AESGCM.generate_key(bit_length=256)
            data["key"] = _b64(self._protector.wrap(key))
            data["protector"] = self._protector.name
        else:
            key = self._protector.unwrap(_unb64(wrapped))
        self._key = key
        return key

    def _entries(self, data: Mapping[str, object]) -> dict[str, dict[str, object]]:
        found = data.get("entries")
        if not isinstance(found, dict):
            return {}
        return {
            str(name): dict(entry)
            for name, entry in found.items()
            if isinstance(entry, dict)
        }

    def _open(
        self, name: str, entry: Mapping[str, object], key: bytes
    ) -> dict[str, str]:
        try:
            plain = AESGCM(key).decrypt(
                _unb64(entry.get("nonce")), _unb64(entry.get("data")), name.encode()
            )
        except InvalidTag as error:
            raise VaultError(f"The {name} keys can't be unlocked here.") from error
        values = json.loads(plain.decode("utf-8"))
        return (
            {str(k): str(v) for k, v in values.items()}
            if isinstance(values, dict)
            else {}
        )

    # ------------------------------------------------------------ keys

    def names(self) -> list[str]:
        try:
            return sorted(self._entries(self._read()))
        except VaultError:
            return []

    def all(self) -> dict[str, dict[str, str]]:
        return {name: self.values(name) for name in self.names()}

    def values(self, name: str) -> dict[str, str]:
        """The platform's keys, or nothing when there are none (or they
        can't be unlocked on this PC: then the platform can't be used)."""
        if self._protector is None:
            return {}
        try:
            data = self._read()
            entry = self._entries(data).get(name)
            if entry is None:
                return {}
            return self._open(name, entry, self._data_key(data))
        except VaultError, ValueError:
            return {}

    def info(self, name: str) -> JsonObject:
        """What can be said about a key set without its secrets."""
        try:
            entry = self._entries(self._read()).get(name)
        except VaultError:
            return {}
        if entry is None:
            return {}
        found: JsonObject = {}
        environment = entry.get("environment")
        if isinstance(environment, str):
            found["environment"] = environment
        for key in ("saved_at", "rotated_at"):
            value = entry.get(key)
            if isinstance(value, int | float):
                found[key] = float(value)
        return found

    def save(self, name: str, values: Mapping[str, str], *, environment: str) -> None:
        if self._protector is None:
            raise VaultError(self.why_unavailable)
        data = self._read()
        key = self._data_key(data)
        entries = self._entries(data)
        before = entries.get(name, {})
        nonce = os.urandom(12)
        sealed = AESGCM(key).encrypt(
            nonce, json.dumps(dict(values)).encode("utf-8"), name.encode()
        )
        now = self._clock()
        entries[name] = {
            "nonce": _b64(nonce),
            "data": _b64(sealed),
            "environment": environment,
            "saved_at": before.get("saved_at", now),
            "rotated_at": now,
        }
        data["version"] = VERSION
        data["entries"] = entries
        self._write(data)

    def remove(self, name: str) -> None:
        try:
            data = self._read()
        except VaultError:
            return
        entries = self._entries(data)
        if entries.pop(name, None) is not None:
            data["entries"] = entries
            self._write(data)

    def secret_values(self, secret_keys: Mapping[str, set[str]]) -> set[str]:
        """Every saved secret (by each platform's secret field names), for
        blanking out of anything shown or written."""
        found: set[str] = set()
        for name in self.names():
            secret = secret_keys.get(name, set())
            for field_name, value in self.values(name).items():
                if field_name in secret and len(value) >= 6:
                    found.add(value)
        return found

    def migrate(
        self, plain: Path, environment_of: Callable[[str, Mapping[str, str]], str]
    ) -> list[str]:
        """Move keys an older FCC kept in plain text into the vault, then
        remove the plain file. Nothing moves when the vault can't be used."""
        if self._protector is None or not plain.exists():
            return []
        try:
            found = json.loads(plain.read_text(encoding="utf-8"))
        except ValueError, OSError:
            return []
        connectors = found.get("connectors") if isinstance(found, dict) else None
        if not isinstance(connectors, dict):
            return []
        moved: list[str] = []
        for name, values in connectors.items():
            if not isinstance(values, dict) or self.values(str(name)):
                continue
            clean = {str(k): str(v) for k, v in values.items()}
            self.save(str(name), clean, environment=environment_of(str(name), clean))
            moved.append(str(name))
        # Only once every key is safely in the vault: overwrite, then delete.
        if all(self.values(str(name)) for name in connectors):
            plain.write_text("{}", encoding="utf-8")
            plain.unlink(missing_ok=True)
        return moved


def redact(text: str, secrets: set[str]) -> str:
    """The text with every secret blanked out."""
    for secret in sorted(secrets, key=len, reverse=True):
        if secret and secret in text:
            text = text.replace(secret, "••••")
    return text
