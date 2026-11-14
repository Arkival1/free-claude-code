"""Signing Hyperliquid actions, written in FCC (no extra packages).

Hyperliquid (the exchange Invo trades on) accepts an action, an order or a
cancel, only with a signature from the account's key or its API wallet. The
signature is Ethereum-style: the action is packed with MessagePack, hashed
with Keccak-256 together with a nonce, wrapped as an EIP-712 "Agent"
message, and signed with secp256k1 (deterministic, RFC 6979, low-s, v of 27
or 28). This module does exactly that and nothing else, and it is checked
against the test values of Hyperliquid's own Python SDK (vendored under
``vendor/hyperliquid-python-sdk``).

Only the actions FCC needs can be signed here (placing and cancelling
orders, and setting 1x isolated leverage). Anything else, such as a
withdrawal or a transfer, is refused before it is signed.
"""

import hashlib
import hmac
import struct
from collections.abc import Mapping, Sequence
from decimal import Decimal

ALLOWED_ACTIONS = frozenset({"order", "cancel", "cancelByCloid", "updateLeverage"})

# ------------------------------------------------------------ Keccak-256

_ROUNDS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)  # fmt: skip
_ROTATIONS = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)
_MASK = (1 << 64) - 1


def _rotate(value: int, shift: int) -> int:
    return ((value << shift) | (value >> (64 - shift))) & _MASK if shift else value


def _permute(lanes: list[list[int]]) -> None:
    for constant in _ROUNDS:
        columns = [
            lanes[x][0] ^ lanes[x][1] ^ lanes[x][2] ^ lanes[x][3] ^ lanes[x][4]
            for x in range(5)
        ]
        for x in range(5):
            mix = columns[(x - 1) % 5] ^ _rotate(columns[(x + 1) % 5], 1)
            for y in range(5):
                lanes[x][y] ^= mix
        moved = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                moved[y][(2 * x + 3 * y) % 5] = _rotate(lanes[x][y], _ROTATIONS[x][y])
        for x in range(5):
            for y in range(5):
                lanes[x][y] = moved[x][y] ^ (
                    (~moved[(x + 1) % 5][y]) & moved[(x + 2) % 5][y]
                )
        lanes[0][0] ^= constant


def keccak256(data: bytes) -> bytes:
    """Ethereum's Keccak-256 (not SHA3-256: the padding differs)."""
    rate = 136
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate:
        padded.append(0)
    padded[-1] |= 0x80
    lanes = [[0] * 5 for _ in range(5)]
    for start in range(0, len(padded), rate):
        block = padded[start : start + rate]
        for index in range(rate // 8):
            (word,) = struct.unpack_from("<Q", block, index * 8)
            lanes[index % 5][index // 5] ^= word
        _permute(lanes)
    out = bytearray()
    for index in range(4):
        out += struct.pack("<Q", lanes[index % 5][index // 5])
    return bytes(out)


# ------------------------------------------------------------ MessagePack


def packb(value: object) -> bytes:
    """MessagePack, as the reference packer writes it (smallest forms,
    strings as str, bytes as bin, floats as 64-bit)."""
    out = bytearray()
    _pack(value, out)
    return bytes(out)


def _pack(value: object, out: bytearray) -> None:
    if value is None:
        out.append(0xC0)
    elif value is True:
        out.append(0xC3)
    elif value is False:
        out.append(0xC2)
    elif isinstance(value, int):
        _pack_int(value, out)
    elif isinstance(value, float):
        out += b"\xcb" + struct.pack(">d", value)
    elif isinstance(value, str):
        raw = value.encode("utf-8")
        size = len(raw)
        if size < 32:
            out.append(0xA0 | size)
        elif size < 1 << 8:
            out += b"\xd9" + struct.pack(">B", size)
        elif size < 1 << 16:
            out += b"\xda" + struct.pack(">H", size)
        else:
            out += b"\xdb" + struct.pack(">I", size)
        out += raw
    elif isinstance(value, bytes | bytearray):
        size = len(value)
        if size < 1 << 8:
            out += b"\xc4" + struct.pack(">B", size)
        elif size < 1 << 16:
            out += b"\xc5" + struct.pack(">H", size)
        else:
            out += b"\xc6" + struct.pack(">I", size)
        out += value
    elif isinstance(value, Mapping):
        size = len(value)
        if size < 16:
            out.append(0x80 | size)
        elif size < 1 << 16:
            out += b"\xde" + struct.pack(">H", size)
        else:
            out += b"\xdf" + struct.pack(">I", size)
        for key, item in value.items():
            _pack(key, out)
            _pack(item, out)
    elif isinstance(value, Sequence):
        size = len(value)
        if size < 16:
            out.append(0x90 | size)
        elif size < 1 << 16:
            out += b"\xdc" + struct.pack(">H", size)
        else:
            out += b"\xdd" + struct.pack(">I", size)
        for item in value:
            _pack(item, out)
    else:
        raise TypeError(f"Can't pack {type(value).__name__}")


def _pack_int(value: int, out: bytearray) -> None:
    if 0 <= value < 128:
        out.append(value)
    elif -32 <= value < 0:
        out += struct.pack(">b", value)
    elif value >= 0:
        for limit, code, form in (
            (1 << 8, 0xCC, ">B"),
            (1 << 16, 0xCD, ">H"),
            (1 << 32, 0xCE, ">I"),
            (1 << 64, 0xCF, ">Q"),
        ):
            if value < limit:
                out += bytes([code]) + struct.pack(form, value)
                return
        raise OverflowError("Integer too large to pack")
    else:
        for limit, code, form in (
            (1 << 7, 0xD0, ">b"),
            (1 << 15, 0xD1, ">h"),
            (1 << 31, 0xD2, ">i"),
            (1 << 63, 0xD3, ">q"),
        ):
            if -limit <= value:
                out += bytes([code]) + struct.pack(form, value)
                return
        raise OverflowError("Integer too small to pack")


# ------------------------------------------------------------ secp256k1

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)

type _Jacobian = tuple[int, int, int]


def _double(point: _Jacobian) -> _Jacobian:
    x, y, z = point
    if not y:
        return (0, 0, 0)
    ysq = (y * y) % _P
    s = (4 * x * ysq) % _P
    m = (3 * x * x) % _P
    nx = (m * m - 2 * s) % _P
    ny = (m * (s - nx) - 8 * ysq * ysq) % _P
    nz = (2 * y * z) % _P
    return (nx, ny, nz)


def _add(p: _Jacobian, q: _Jacobian) -> _Jacobian:
    if not p[1]:
        return q
    if not q[1]:
        return p
    u1 = (p[0] * q[2] ** 2) % _P
    u2 = (q[0] * p[2] ** 2) % _P
    s1 = (p[1] * q[2] ** 3) % _P
    s2 = (q[1] * p[2] ** 3) % _P
    if u1 == u2:
        return _double(p) if s1 == s2 else (0, 0, 1)
    h = u2 - u1
    r = s2 - s1
    h2 = (h * h) % _P
    h3 = (h * h2) % _P
    u1h2 = (u1 * h2) % _P
    nx = (r * r - h3 - 2 * u1h2) % _P
    ny = (r * (u1h2 - nx) - s1 * h3) % _P
    nz = (h * p[2] * q[2]) % _P
    return (nx, ny, nz)


def _multiply(scalar: int) -> tuple[int, int]:
    result: _Jacobian = (0, 0, 1)
    addend: _Jacobian = (_G[0], _G[1], 1)
    while scalar:
        if scalar & 1:
            result = _add(result, addend)
        addend = _double(addend)
        scalar >>= 1
    x, y, z = result
    inverse = pow(z, -1, _P)
    return (x * inverse**2) % _P, (y * inverse**3) % _P


def _nonce(digest: bytes, secret: bytes) -> int:
    """The deterministic nonce (RFC 6979 with HMAC-SHA256), as the reference
    Ethereum signer computes it."""
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + secret + digest, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + secret + digest, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    return int.from_bytes(hmac.new(k, v, hashlib.sha256).digest(), "big")


def private_key(text: str) -> bytes:
    raw = bytes.fromhex(text.strip().removeprefix("0x"))
    number = int.from_bytes(raw, "big")
    if len(raw) != 32 or not 0 < number < _N:
        raise ValueError("That isn't a valid private key (64 hex characters).")
    return raw


def address_of(secret: bytes) -> str:
    """The Ethereum address of a private key (0x + 40 hex, lower case)."""
    x, y = _multiply(int.from_bytes(secret, "big"))
    return "0x" + keccak256(x.to_bytes(32, "big") + y.to_bytes(32, "big"))[-20:].hex()


def sign_digest(digest: bytes, secret: bytes) -> tuple[int, int, int]:
    """(r, s, v) for a 32-byte digest: low s, v of 27 or 28."""
    z = int.from_bytes(digest, "big")
    d = int.from_bytes(secret, "big")
    k = _nonce(digest, secret)
    rx, ry = _multiply(k)
    r = rx % _N
    s = (pow(k, -1, _N) * (z + r * d)) % _N
    v = 27 + ((ry % 2) ^ (0 if s * 2 < _N else 1))
    if s * 2 >= _N:
        s = _N - s
    return r, s, v


# ------------------------------------------------------------ actions


def wire(value: float) -> str:
    """A number as Hyperliquid's wire format writes it (no float drift)."""
    rounded = f"{value:.8f}"
    if abs(float(rounded) - value) >= 1e-12:
        raise ValueError(f"{value} can't be sent without rounding.")
    if rounded == "-0":
        rounded = "0"
    return f"{Decimal(rounded).normalize():f}"


def action_hash(
    action: Mapping[str, object], nonce: int, vault: str | None = None
) -> bytes:
    data = packb(action) + nonce.to_bytes(8, "big")
    if vault is None:
        data += b"\x00"
    else:
        data += b"\x01" + bytes.fromhex(vault.removeprefix("0x"))
    return keccak256(data)


def _domain() -> bytes:
    type_hash = keccak256(
        b"EIP712Domain(string name,string version,uint256 chainId,"
        b"address verifyingContract)"
    )
    return keccak256(
        type_hash
        + keccak256(b"Exchange")
        + keccak256(b"1")
        + (1337).to_bytes(32, "big")
        + bytes(32)
    )


def agent_digest(connection: bytes, *, mainnet: bool) -> bytes:
    struct_hash = keccak256(
        keccak256(b"Agent(string source,bytes32 connectionId)")
        + keccak256(b"a" if mainnet else b"b")
        + connection
    )
    return keccak256(b"\x19\x01" + _domain() + struct_hash)


def sign_action(
    action: Mapping[str, object],
    secret: bytes,
    nonce: int,
    *,
    mainnet: bool = True,
    vault: str | None = None,
    allowed: frozenset[str] = ALLOWED_ACTIONS,
) -> dict[str, object]:
    """The signature for an action FCC is allowed to send; anything else
    (withdrawals, transfers, ...) is refused before it is signed."""
    kind = action.get("type")
    if kind not in allowed:
        raise PermissionError(f"FCC never signs a {kind!r} action.")
    digest = agent_digest(action_hash(action, nonce, vault), mainnet=mainnet)
    r, s, v = sign_digest(digest, secret)
    return {"r": hex(r), "s": hex(s), "v": v}
