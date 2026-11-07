"""Trading keys: encrypted at rest, never shown or logged, never able to
move money, and practice and real keys kept apart."""

import json
import re
from pathlib import Path

import httpx
import pytest

from free_claude_code.studio.resilience import ServiceError
from free_claude_code.studio.trading.brokers.common import (
    forbid_money_moves,
    make_web,
)
from free_claude_code.studio.trading.brokers.registry import environment_of
from free_claude_code.studio.trading.keyvault import KeyVault, VaultError, redact

from .test_trading_desk import FakeLock

SECRET = "sk-live-0123456789abcdef"


class OtherLock(FakeLock):
    """Another PC's protection: it can't unwrap this PC's key."""

    name = "other"

    def unwrap(self, blob: bytes) -> bytes:
        return bytes(b ^ 0x11 for b in blob)


def test_keys_are_encrypted_and_only_this_pc_can_read_them(tmp_path: Path):
    vault = KeyVault(tmp_path / "keys.vault", protector=FakeLock())
    vault.save(
        "kraken", {"api_key": "public", "api_secret": SECRET}, environment="live"
    )
    assert vault.values("kraken")["api_secret"] == SECRET
    raw = (tmp_path / "keys.vault").read_text()
    assert SECRET not in raw and "public" not in raw
    info = vault.info("kraken")
    assert info["environment"] == "live" and info["saved_at"] == info["rotated_at"]
    elsewhere = KeyVault(tmp_path / "keys.vault", protector=OtherLock())
    assert elsewhere.values("kraken") == {}


def test_without_secure_storage_nothing_is_saved(tmp_path: Path):
    vault = KeyVault(tmp_path / "keys.vault", protector=None)
    assert not vault.available and "practice mode" in vault.why_unavailable
    with pytest.raises(VaultError):
        vault.save("kraken", {"api_secret": SECRET}, environment="live")
    assert not (tmp_path / "keys.vault").exists()


def test_plain_text_keys_move_in_and_the_plain_file_goes(tmp_path: Path):
    plain = tmp_path / "trading-keys.json"
    plain.write_text(
        json.dumps({"connectors": {"alpaca": {"key_id": "A", "secret": SECRET}}})
    )
    vault = KeyVault(tmp_path / "keys.vault", protector=FakeLock())
    assert vault.migrate(plain, environment_of) == ["alpaca"]
    assert not plain.exists()
    assert vault.values("alpaca")["secret"] == SECRET
    # Alpaca without "account: live" is its paper (practice) account.
    assert vault.info("alpaca")["environment"] == "practice"


def test_secrets_are_blanked_out_of_text():
    assert redact(f"Kraken said: bad key {SECRET}!", {SECRET}) == (
        "Kraken said: bad key ••••!"
    )


@pytest.mark.parametrize(
    "path",
    [
        "/0/private/Withdraw",
        "/v2/accounts/abc/transactions",
        "/api/v3/brokerage/transfers",
        "/user/withdraw/",
        "/api/v3/brokerage/api_keys",
    ],
)
def test_calls_that_move_money_are_refused_before_they_leave(path: str):
    with pytest.raises(ServiceError) as caught:
        forbid_money_moves("POST", f"https://api.example{path}")
    assert caught.value.sent is False


def test_reading_a_keys_own_rights_and_trading_are_allowed():
    forbid_money_moves(
        "GET", "https://api.coinbase.com/api/v3/brokerage/key_permissions"
    )
    forbid_money_moves("POST", "https://api.kraken.com/0/private/AddOrder")


@pytest.mark.asyncio
async def test_the_guard_stops_the_request_on_every_platform_client():
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={})

    web = make_web(httpx.MockTransport(handler), "api.example", per_second=10)
    with pytest.raises(ServiceError):
        await web.request("POST", "https://api.example/withdraw")
    assert sent == []
    await web.aclose()


def test_no_adapter_names_an_endpoint_that_moves_money():
    folder = Path(__file__).parents[2] / "src/free_claude_code/studio/trading/brokers"
    paths = re.compile(r"[\"'](/[A-Za-z0-9_/{}.:-]+)[\"']")
    for source in folder.glob("*.py"):
        for found in paths.findall(source.read_text(encoding="utf-8")):
            if found.rstrip("/").endswith("key_permissions"):
                continue
            with pytest.raises(ServiceError):
                forbid_money_moves("POST", "https://x" + found + "/withdraw")
            forbid_money_moves("POST", "https://x" + found)
