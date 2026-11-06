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
        "fcc-linux.json",
    }
    for name, digest in shipped.items():
        data = (PHONE_DIR / "linux" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest == sums[name], name
    # The box: no network, and only its own scripts.
    assert "connect-src 'none'" in runner and '"allow-scripts"' in runner
    worker = (PHONE_DIR / "sw.js").read_text(encoding="utf-8")
    assert 'const LINUX_CACHE = "fcc-phone-linux-2.0";' in worker
    # The system's packs skip the worker (js/linuxfiles.js keeps them itself).
    assert '"/linux/fs/"' in worker


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
        "gcc",
        "g++",
        "rust",
        "cargo",
        "go",
        "openjdk8-jdk",
        "nodejs",
        "ruby",
        "php83",
        "perl",
        "git",
    } <= added
    assert "busybox" in contents["base_packages"]
    assert contents["version"] == "2.0"
    assert contents["initrd"]["sha256"] == recorded("fcc-linux")["fcc-linux.initrd"]
    # Every pack and the file list are shipped as recorded, each under the
    # 100 MB GitHub limit (24 MB packs).
    for row in [*contents["packs"], contents["files"]]:
        data = (PHONE_DIR / "linux" / row["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["sha256"], row["file"]
        assert len(data) == row["bytes"] <= 25 * 1024 * 1024
    shipped = {path.name for path in (PHONE_DIR / "linux" / "fs").iterdir()}
    assert shipped == {
        Path(row["file"]).name for row in [*contents["packs"], contents["files"]]
    }


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


def shipped_system() -> tuple[dict, dict[str, list]]:
    """FCC Linux 2 as shipped: the manifest, and its file list by path."""
    contents = json.loads((PHONE_DIR / "linux" / "fcc-linux.json").read_text("utf-8"))
    listing = json.loads(
        gzip.decompress((PHONE_DIR / "linux" / contents["files"]["file"]).read_bytes())
    )
    assert listing["version"] == 3
    paths: dict[str, list] = {}

    def walk(entries: list, folder: str) -> None:
        for entry in entries:
            path = f"{folder}{entry[0]}"
            paths[path] = entry
            if stat.S_ISDIR(entry[3]):
                walk(entry[6], f"{path}/")

    walk(listing["fsroot"], "")
    return contents, paths


def shipped_file(contents: dict, entry: list) -> bytes:
    """A file's bytes from its packs (a big one runs on through the next)."""
    number, at, size = (int(part, 16) for part in entry[6][:-4].split("-"))
    data = b""
    while len(data) < size:
        pack = (PHONE_DIR / "linux" / contents["packs"][number]["file"]).read_bytes()
        data += pack[at : at + size - len(data)]
        number, at = number + 1, 0
    return zstd.decompress(data)


def test_the_shipped_system_keeps_modes_links_and_the_phones_bridge():
    contents, paths = shipped_system()
    assert oct(paths["root"][3]) == "0o40700"
    assert oct(paths["tmp"][3]) == "0o41777"
    assert oct(paths["var/empty"][3]) == "0o40555"
    assert stat.S_ISLNK(paths["usr/bin/python3"][3])
    profile = shipped_file(contents, paths["etc/profile.d/fcc.sh"]).decode()
    assert "PROMPT_COMMAND" in profile and "fcc;idle" in profile
    assert "PS0=" in profile and "fcc;busy" in profile
    assert 'bash "$file" < /dev/null' in profile
    assert "HISTCONTROL=ignoreboth" in profile
    assert (
        "mount -t devpts" in shipped_file(contents, paths["etc/fcc/boot.sh"]).decode()
    )
    # Python's library comes compiled for 3.12 (unchecked-hash .pyc).
    pyc = shipped_file(
        contents, paths["usr/lib/python3.12/__pycache__/os.cpython-312.pyc"]
    )
    assert pyc[:4] == (3531).to_bytes(2, "little") + b"\r\n"
    assert int.from_bytes(pyc[4:8], "little") == 0b01
    release = shipped_file(contents, paths["etc/os-release"]).decode()
    assert 'PRETTY_NAME="FCC Linux 2.0' in release
    biggest = max(
        (entry for entry in paths.values() if stat.S_ISREG(entry[3])),
        key=lambda entry: entry[1],
    )
    assert len(shipped_file(contents, biggest)) == biggest[1]  # runs across packs
    # Every language's program is in the list, with its bytes in a pack.
    for program in (
        "usr/bin/gcc",
        "usr/bin/g++",
        "usr/bin/rustc",
        "usr/bin/cargo",
        "usr/bin/node",
        "usr/bin/ruby",
        "usr/bin/php83",
        "usr/bin/perl",
        "usr/bin/git",
        "usr/lib/go/bin/go",
    ):
        entry = paths[program]
        if stat.S_ISREG(entry[3]):
            assert len(shipped_file(contents, entry)) == entry[1], program
    # The start-up system: busybox, musl, the 9p modules and /init.
    data = zstd.decompress((PHONE_DIR / "linux" / "fcc-linux.initrd").read_bytes())
    names = set()
    at = 0
    while True:
        assert data[at : at + 6] == b"070701"
        fields = [int(data[at + 6 + i * 8 : at + 14 + i * 8], 16) for i in range(13)]
        size, name_size = fields[6], fields[11]
        name = data[at + 110 : at + 110 + name_size - 1].decode()
        at += 110 + name_size
        at += (4 - at % 4) % 4
        at += size + (4 - size % 4) % 4
        if name == "TRAILER!!!":
            break
        names.add(name)
    assert {
        "init",
        "bin/busybox",
        "lib/ld-musl-i386.so.1",
        "modules/9p.ko",
        "modules/9pnet_virtio.ko",
        "modules/order",
    } <= names


def build2_script():
    spec = importlib.util.spec_from_file_location(
        "build_fcc_linux2", ROOT / "scripts" / "linux" / "build_fcc_linux2.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entry(path: str, kind: str = "file", body: bytes = b"", link: str = ""):
    info = tarfile.TarInfo(path)
    info.mode = 0o755 if kind == "dir" else 0o644
    if kind == "dir":
        info.type = tarfile.DIRTYPE
    elif kind == "sym":
        info.type = tarfile.SYMTYPE
        info.linkname = link
    elif kind == "hard":
        info.type = tarfile.LNKTYPE
        info.linkname = link
    info.size = len(body)
    return info, (body if kind == "file" else None)


def test_the_v2_file_list_is_v86s_format_and_names_say_where_files_live(tmp_path):
    """Each file in the list is named <pack>-<offset>-<length>.zst; the same
    content is stored once; hard links read their target's bytes; links and
    folders keep their shape; files that live in packs come back whole."""
    build = build2_script()
    build.BLOBS = tmp_path / "blobs"
    root = {
        "usr": _entry("usr", "dir"),
        "usr/bin/hello": _entry("usr/bin/hello", body=b"hello"),
        "usr/bin/same": _entry("usr/bin/same", body=b"hello"),
        "usr/bin/hard": _entry("usr/bin/hard", "hard", link="./usr/bin/hello"),
        "usr/bin/link": _entry("usr/bin/link", "sym", link="hello"),
        "etc/big": _entry("etc/big", body=bytes(range(256)) * 400),
    }
    owner = {"etc/big": "big", **{name: "base" for name in root if name != "etc/big"}}
    packs, who, names, used = build.packs_and_names(root, owner, ["base", "big"])
    assert names["usr/bin/hello"] == names["usr/bin/same"] == names["usr/bin/hard"]
    assert who[0] == ["base", "big"] and used == 5 + 256 * 400
    for path, expected in (
        ("usr/bin/hello", b"hello"),
        ("etc/big", bytes(range(256)) * 400),
    ):
        number, at, size = (int(part, 16) for part in names[path][:-4].split("-"))
        assert zstd.decompress(packs[number][at : at + size]) == expected
    listing = build.file_list(root, names)
    by_name = {entry[0]: entry for entry in listing}
    usr = {entry[0]: entry for entry in by_name["usr"][6]}
    assert by_name["usr"][3] == stat.S_IFDIR | 0o755
    assert usr["bin"][3] & stat.S_IFDIR
    bins = {entry[0]: entry for entry in usr["bin"][6]}
    assert bins["hello"][1] == 5 and bins["hello"][6] == names["usr/bin/hello"]
    assert bins["hard"][1] == 5 and bins["hard"][3] == stat.S_IFREG | 0o644
    assert bins["link"][3] == stat.S_IFLNK | 0o777 and bins["link"][6] == "hello"
    assert by_name["etc"][3] == stat.S_IFDIR | 0o755  # made for etc/big


def test_the_v2_start_up_system_mounts_the_real_one_over_9p():
    build = build2_script()
    assert "mount -t 9p host9p /newroot -o trans=virtio" in build.INIT
    assert "exec $B switch_root /newroot /sbin/init" in build.INIT
    assert {"9p", "9pnet_virtio", "virtio_pci"} <= set(build.MODULES)
    for language in (
        "gcc",
        "g++",
        "rust",
        "cargo",
        "go",
        "openjdk8",
        "nodejs",
        "ruby",
        "php83",
        "perl",
        "git",
    ):
        assert language in build.PACKAGES
    assert "init" not in build.FCC_FILES  # the 9p system starts with /sbin/init
    assert "mount -t devpts" in build.FCC_FILES["etc/fcc/boot.sh"][1]
