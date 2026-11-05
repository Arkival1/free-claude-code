"""FCC Linux in FCC Phone: the files the phone ships are the ones recorded in
vendor/ (v86, xterm.js, FCC Linux), with the checksums js/linux.js checks."""

import gzip
import hashlib
import importlib.util
import io
import json
import random
import re
import stat
import tarfile
from compression import zstd
from pathlib import Path

from free_claude_code.api.studio_routes import PHONE_DIR

ROOT = Path(__file__).resolve().parents[2]


def recorded(name: str) -> dict[str, str]:
    rows = (
        (ROOT / "vendor" / name / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    )
    return {line[66:].split(" ")[0]: line[:64] for line in rows if line.strip()}


def test_the_phone_ships_the_recorded_linux_files_and_checks_them():
    runner = (PHONE_DIR / "js" / "linux.js").read_text(encoding="utf-8")
    shipped = dict(re.findall(r'\["linux/([\w.-]+)", "([0-9a-f]{64})"\]', runner))
    sums = {**recorded("v86"), **recorded("xterm"), **recorded("fcc-linux")}
    assert set(shipped) == {
        "libv86.js",
        "v86.wasm",
        "seabios.bin",
        "vgabios.bin",
        "xterm.js",
        "xterm.css",
        "fcc-linux.kernel",
        "fcc-linux.initrd",
    }
    for name, digest in shipped.items():
        data = (PHONE_DIR / "linux" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest == sums[name], name
    # The box: no network, and only its own scripts.
    assert "connect-src 'none'" in runner and '"allow-scripts"' in runner
    worker = (PHONE_DIR / "sw.js").read_text(encoding="utf-8")
    assert 'const LINUX_CACHE = "fcc-phone-linux-1.1";' in worker


def test_fcc_linux_says_what_is_inside():
    contents = json.loads((PHONE_DIR / "linux" / "fcc-linux.json").read_text("utf-8"))
    assert contents == json.loads(
        (ROOT / "vendor" / "fcc-linux" / "contents.json").read_text("utf-8")
    )
    added = {item["name"] for item in contents["added"]}
    assert {
        "python3",
        "lua5.4",
        "bash",
        "nano",
        "tmux",
        "sqlite",
        "htop",
        "lynx",
    } <= added
    assert "busybox" in contents["base_packages"]
    assert contents["initrd"]["sha256"] == recorded("fcc-linux")["fcc-linux.initrd"]


def build_script():
    spec = importlib.util.spec_from_file_location(
        "build_fcc_linux", ROOT / "scripts" / "linux" / "build_fcc_linux.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prime(bits: int, rng: random.Random) -> int:
    while True:
        n = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if all(n % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31)) and all(
            pow(a, n - 1, n) == 1 for a in (2, 3, 5, 7, 11, 13, 17)
        ):
            return n


def test_the_build_checks_alpines_rsa_signature():
    """A real PKCS#1 v1.5 signature checks out; a changed byte or another
    key doesn't (so a tampered package index stops the build)."""
    build = build_script()
    rng = random.Random(7)
    p, q = _prime(512, rng), _prime(512, rng)
    n, e = p * q, 65537
    d = pow(e, -1, (p - 1) * (q - 1))
    size = (n.bit_length() + 7) // 8
    data = b"APKINDEX contents"
    for how in ("sha1", "sha256"):
        tail = build.DIGEST_INFO[how] + hashlib.new(how, data).digest()
        padded = b"\x00\x01" + b"\xff" * (size - 3 - len(tail)) + b"\x00" + tail
        signature = pow(int.from_bytes(padded, "big"), d, n).to_bytes(size, "big")
        assert build.rsa_verify((n, e), signature, data, how)
        assert not build.rsa_verify((n, e), signature, data + b"!", how)
        assert not build.rsa_verify((n + 2, e), signature, data, how)
        assert not build.rsa_verify((n, e), signature[:-1], data, how)


def test_the_build_keeps_names_and_reads_a_packages_own_checksum():
    build = build_script()
    assert build.clean_name("./.profile") == ".profile"
    assert build.clean_name("././etc/motd") == "etc/motd"
    assert build.clean_name("/usr/bin") == "usr/bin"
    info = tarfile.TarInfo(".PKGINFO")
    text = b"pkgname = demo\ndatahash = " + b"ab" * 32 + b"\n"
    info.size = len(text)
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w") as bundle:
        bundle.addfile(info, io.BytesIO(text))
    assert build.package_data_hash(gzip.compress(packed.getvalue())) == "ab" * 32


def test_the_shipped_system_keeps_modes_links_and_the_phones_bridge():
    data = zstd.decompress((PHONE_DIR / "linux" / "fcc-linux.initrd").read_bytes())
    entries: dict[str, tuple[int, bytes]] = {}
    at = 0
    while True:
        assert data[at : at + 6] == b"070701"
        fields = [int(data[at + 6 + i * 8 : at + 14 + i * 8], 16) for i in range(13)]
        mode, size, name_size = fields[1], fields[6], fields[11]
        name = data[at + 110 : at + 110 + name_size - 1].decode()
        at += 110 + name_size
        at += (4 - at % 4) % 4
        body = data[at : at + size]
        at += size + (4 - size % 4) % 4
        if name == "TRAILER!!!":
            break
        entries[name] = (mode, body)
    assert oct(entries["root"][0]) == "0o40700"
    assert oct(entries["tmp"][0]) == "0o41777"
    assert oct(entries["var/empty"][0]) == "0o40555"
    # Hard-linked programs come out whole, not empty.
    empty = [
        name
        for name, (mode, body) in entries.items()
        if stat.S_ISREG(mode) and not body and not name.endswith("__init__.py")
    ]
    assert empty == ["lib/apk/db/lock"], empty
    profile = entries["etc/profile.d/fcc.sh"][1].decode()
    assert "PROMPT_COMMAND" in profile and "fcc;idle" in profile
    assert "PS0=" in profile and "fcc;busy" in profile
    assert 'bash "$file" < /dev/null' in profile
    assert "HISTCONTROL=ignoreboth" in profile
    # Python's library comes compiled for 3.12 (unchecked-hash .pyc), so the
    # first python3 doesn't spend its first seconds compiling.
    pyc = entries["usr/lib/python3.12/__pycache__/os.cpython-312.pyc"][1]
    assert pyc[:4] == (3531).to_bytes(2, "little") + b"\r\n"
    assert int.from_bytes(pyc[4:8], "little") == 0b01  # hash-based, unchecked
    assert "usr/lib/python3.12/json/__pycache__/__init__.cpython-312.pyc" in entries
    release = entries["etc/os-release"][1].decode()
    assert 'PRETTY_NAME="FCC Linux 1.1' in release
