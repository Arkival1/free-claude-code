# hyperliquid-python-sdk (signing reference)

- Upstream: https://github.com/hyperliquid-dex/hyperliquid-python-sdk
- Commit: `2fdb18f9517675ea03695a0962bd19eece9c83f0` (4 June 2026)
- Licence: MIT (see `LICENSE.md`), copyright Hyperliquid Labs Pte. Ltd.

## How FCC uses it

FCC does **not** install or run this SDK. The Trading Bank's Hyperliquid
account (the exchange the Invo app trades on) signs its orders with FCC's
own code, `src/free_claude_code/studio/trading/hlsign.py` (Keccak-256,
MessagePack, EIP-712 and secp256k1 written in plain Python, no new
packages). This folder keeps the SDK's reference signing code and its test
values so that code can always be checked, even if the upstream repo goes:
`tests/studio/test_trading_hyperliquid.py` signs the same actions with the
same test key and must produce exactly the signatures in
`source/signing_test.py.txt`.

## What is kept

| File | What it is |
| --- | --- |
| `LICENSE.md` | The upstream licence |
| `source/signing.py.txt` | `hyperliquid/utils/signing.py` at the commit above (reference only) |
| `source/signing_test.py.txt` | `tests/signing_test.py` at the commit above (the test values) |
| `SHA256SUMS` | Checksums of the files above |

The two source files are kept as `.txt` so no tool here runs or checks
them as code (their own imports aren't installed). Left out: the rest of the SDK (the exchange and info clients, websocket
manager, examples and recorded test cassettes); FCC has its own client
(`trading/brokers/hyperliquid.py`) and needs only the signing reference.
No release files are installed, so there are none to keep.
