"""Build FCC Linux: a small custom Linux for FCC Phone's Lab, booted by the v86
emulator in a sealed box on the phone.

It is Alpine Linux 3.21 (32-bit x86, the machine v86 emulates) with FCC's own
additions, built without running anything that was downloaded: the minimal
root filesystem and each package are fetched, checked (SHA-256 for the
release files, the package index's SHA-1 for every package), and unpacked by
this script; FCC's start-up files are written in; and the whole system is
packed into one compressed in-memory root (an initramfs) next to Alpine's
kernel. Package scripts are not run: what they would do (shells, links) is
done here.

    uv run python scripts/linux/build_fcc_linux.py [--out DIR]

writes `fcc-linux.kernel`, `fcc-linux.initrd` (zstd) and `fcc-linux.json`
(what is inside, with sizes) to `src/free_claude_code/api/phone_static/linux/`
by default. See vendor/fcc-linux/README.md.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import stat
import sys
import tarfile
import urllib.request
import zlib
from compression import zstd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "src" / "free_claude_code" / "api" / "phone_static" / "linux"
CACHE = ROOT / ".cache" / "fcc-linux"
MIRROR = "https://dl-cdn.alpinelinux.org/alpine/v3.21"
RELEASE = "3.21.9"
MINIROOTFS = (
    f"{MIRROR}/releases/x86/alpine-minirootfs-{RELEASE}-x86.tar.gz",
    "d1f765c811308a8b971f43286b512ae622c3fd46e67b0a20bbac9d61d070466d",
)
NETBOOT = (
    f"{MIRROR}/releases/x86/alpine-netboot-{RELEASE}-x86.tar.gz",
    "b8d368b02f358e0e1c797af1bda34b0857d1443e22a1cef7519db1ba4e699b04",
)
KERNEL_IN_NETBOOT = "boot/vmlinuz-lts"
PACKAGES = [
    # Shell and editing
    "bash",
    "nano",
    "less",
    "tmux",
    "ncurses",
    # Programming
    "python3",
    "lua5.4",
    "make",
    # Data and tools
    "sqlite",
    "jq",
    "bc",
    "file",
    "tree",
    "htop",
    "figlet",
    # A text web browser for local pages (there is no network in the box)
    "lynx",
]
"""What FCC Linux adds to Alpine's minimal system (with their dependencies)."""
LEAVE_OUT = (
    "usr/share/man/",
    "usr/share/doc/",
    "usr/share/info/",
    "usr/lib/python3.12/test/",
    "usr/lib/python3.12/idlelib/",
    "usr/lib/python3.12/tkinter/",
    "usr/lib/python3.12/turtledemo/",
    "usr/lib/python3.12/ensurepip/",
    "usr/lib/python3.12/lib2to3/",
)
"""Parts left out to keep the phone's download small (manuals, Python's own
tests and GUI kits that can't run without a screen server)."""


def fetch(url: str, sha256: str = "") -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / hashlib.sha256(url.encode()).hexdigest()
    if cached.exists():
        data = cached.read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=300) as response:
            data = response.read()
        cached.write_bytes(data)
    if sha256 and hashlib.sha256(data).hexdigest() != sha256:
        cached.unlink(missing_ok=True)
        raise SystemExit(f"{url}: the checksum is wrong, so it wasn't used.")
    return data


def gzip_members(data: bytes) -> list[bytes]:
    """An .apk is several gzip streams back to back: split them (compressed)."""
    members = []
    rest = data
    while rest:
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        inflater.decompress(rest)
        used = len(rest) - len(inflater.unused_data)
        members.append(rest[:used])
        rest = inflater.unused_data
    return members


def read_index() -> dict[str, dict[str, str]]:
    """Every package in main and community: name -> its index fields."""
    packages: dict[str, dict[str, str]] = {}
    for repo in ("main", "community"):
        raw = fetch(f"{MIRROR}/{repo}/x86/APKINDEX.tar.gz")
        with tarfile.open(fileobj=io.BytesIO(raw)) as bundle:
            member = bundle.extractfile("APKINDEX")
            assert member is not None
            text = member.read().decode()
        for block in text.split("\n\n"):
            fields: dict[str, str] = {}
            for line in block.splitlines():
                if len(line) > 2 and line[1] == ":":
                    fields[line[0]] = line[2:]
            if "P" in fields:
                fields["repo"] = repo
                packages.setdefault(fields["P"], fields)
    return packages


def providers(index: dict[str, dict[str, str]]) -> dict[str, str]:
    """What each package provides (so:libz.so.1, cmd:python3...) -> the package."""
    found: dict[str, str] = {}
    for name, fields in index.items():
        found.setdefault(name, name)
        for item in fields.get("p", "").split():
            found.setdefault(item.split("=")[0], name)
    return found


def resolve(
    wanted: list[str], index: dict[str, dict[str, str]], have: set[str]
) -> list[str]:
    """The packages to add, with all their dependencies, in install order."""
    provided = providers(index)
    order: list[str] = []
    seen = set(have)

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        for dep in index[name].get("D", "").split():
            if dep.startswith("!"):
                continue
            key = dep.split("=")[0].split(">")[0].split("<")[0].split("~")[0]
            target = provided.get(key)
            if target is None:
                raise SystemExit(f"{name} needs {dep}, which no package provides.")
            visit(target)
        order.append(name)

    for name in wanted:
        visit(provided.get(name, name))
    return order


def unpack(
    tar_bytes: bytes,
    root: dict[str, tuple[tarfile.TarInfo, bytes | None]],
    skip=LEAVE_OUT,
) -> int:
    """Unpack a tar stream into the in-memory tree; returns the bytes added."""
    added = 0
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*") as bundle:
        for info in bundle:
            name = info.name.lstrip("./")
            if not name or (name.startswith(".") and "/" not in name):
                continue  # .PKGINFO, .SIGN..., the package's own bookkeeping
            if any(name.startswith(prefix) for prefix in skip):
                continue
            body = None
            if info.isreg():
                handle = bundle.extractfile(info)
                body = handle.read() if handle else b""
                added += len(body)
            info.name = name
            root[name] = (info, body)
    return added


def add_text(root, path: str, text: str, mode: int = 0o644) -> None:
    info = tarfile.TarInfo(path)
    data = text.encode()
    info.size = len(data)
    info.mode = mode
    info.mtime = 0
    root[path] = (info, data)


def add_link(root, path: str, target: str) -> None:
    info = tarfile.TarInfo(path)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    info.mode = 0o777
    root[path] = (info, None)


def cpio(root) -> bytes:
    """The tree as a newc cpio archive (what the kernel unpacks into RAM)."""
    out = io.BytesIO()
    inode = 1
    dirs = set()
    for name in root:
        parts = name.rstrip("/").split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))

    def entry(name: str, mode: int, body: bytes = b"", links: int = 1) -> None:
        nonlocal inode
        encoded = name.encode() + b"\0"
        head = "070701" + "".join(
            f"{value:08x}"
            for value in (
                inode,
                mode,
                0,
                0,
                links,
                0,
                len(body),
                0,
                0,
                0,
                0,
                len(encoded),
                0,
            )
        )
        out.write(head.encode() + encoded)
        out.write(b"\0" * ((4 - (110 + len(encoded)) % 4) % 4))
        out.write(body)
        out.write(b"\0" * ((4 - len(body) % 4) % 4))
        inode += 1

    for name in sorted(
        dirs
        - {name.rstrip("/") for name, (info, _) in root.items() if not info.isdir()}
    ):
        if name and (name not in root or root[name][0].isdir()):
            info = root.get(name, (None, None))[0]
            entry(
                name, stat.S_IFDIR | ((info.mode & 0o7777) if info else 0o755), links=2
            )
    for name in sorted(root):
        info, body = root[name]
        if info.isdir():
            if name.rstrip("/") not in dirs:
                entry(name.rstrip("/"), stat.S_IFDIR | (info.mode & 0o7777), links=2)
        elif info.issym():
            entry(name, stat.S_IFLNK | 0o777, info.linkname.encode())
        elif info.islnk():
            target = root.get(info.linkname.lstrip("./"))
            entry(
                name,
                stat.S_IFREG | (info.mode & 0o7777),
                (target[1] or b"") if target else b"",
            )
        elif info.isreg():
            entry(name, stat.S_IFREG | (info.mode & 0o7777), body or b"")
        elif info.ischr() or info.isblk():
            continue  # /dev comes from devtmpfs at boot
    entry("TRAILER!!!", 0, links=1)
    return out.getvalue()


FCC_FILES = {
    "init": (
        0o755,
        """#!/bin/sh
# FCC Linux starts here (the kernel runs /init from the in-memory root).
mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t devtmpfs dev /dev 2>/dev/null
mkdir -p /dev/pts /dev/shm /tmp /run
mount -t devpts devpts /dev/pts
mount -t tmpfs tmpfs /tmp
mount -t tmpfs tmpfs /run
hostname fcc-linux
exec /sbin/init
""",
    ),
    "etc/inittab": (
        0o644,
        """# FCC Linux: one console on the serial line (FCC Phone's terminal).
::sysinit:/bin/sh /etc/fcc/boot.sh
ttyS0::respawn:/sbin/getty -n -l /etc/fcc/login.sh -L 115200 ttyS0 xterm-256color
::ctrlaltdel:/sbin/reboot
::shutdown:/bin/sync
""",
    ),
    "etc/fcc/boot.sh": (
        0o755,
        """#!/bin/sh
# Things Alpine's package scripts would have set up.
ip link set lo up 2>/dev/null
mkdir -p /home/fcc /root
[ -f /etc/shells ] || printf '/bin/sh\\n/bin/bash\\n' > /etc/shells
echo 1 > /proc/sys/kernel/printk 2>/dev/null
""",
    ),
    "etc/fcc/login.sh": (
        0o755,
        """#!/bin/sh
cd /root
export HOME=/root TERM=xterm-256color
exec /bin/bash -l
""",
    ),
    "etc/profile.d/fcc.sh": (
        0o644,
        r"""# FCC Linux: the prompt, and the bridge FCC Phone (and Jarvis) talk through.
export PS1='\[\e[38;5;208m\]fcc\[\e[0m\]:\[\e[36m\]\w\[\e[0m\]\$ '
export EDITOR=nano PAGER=less
alias ll='ls -la'
# Run a command sent by FCC Phone (base64, so any text survives the serial
# line); its output sits between two markers the phone looks for.
__fcc_run() {
  printf '\033]fcc;begin;%s\a\n' "$1"
  printf '%s' "$2" | base64 -d > /tmp/.fcc-cmd 2>/dev/null
  sh /tmp/.fcc-cmd 2>&1
  printf '\033]fcc;end;%s;%s\a\n' "$1" "$?"
}
# Write a file sent by FCC Phone (base64).
__fcc_put() {
  mkdir -p "$(dirname "$2")"
  printf '%s' "$3" | base64 -d > "$2" && printf '\033]fcc;end;%s;0\a\n' "$1" || printf '\033]fcc;end;%s;1\a\n' "$1"
}
""",
    ),
    "etc/motd": (
        0o644,
        """
  FCC Linux (Alpine 3.21, x86) on FCC Phone
  python3, lua, bash, nano, tmux, sqlite3, jq, bc, htop, lynx, make
  Type fcc-info for what's here. Files in /root stay while the box is open.

""",
    ),
    "etc/os-release": (
        0o644,
        """NAME="FCC Linux"
ID=fcc-linux
ID_LIKE=alpine
VERSION_ID=1.0
PRETTY_NAME="FCC Linux 1.0 (Alpine 3.21 base)"
HOME_URL="https://github.com/arkival1/free-claude-code"
""",
    ),
    "usr/local/bin/fcc-info": (
        0o755,
        """#!/bin/sh
figlet -f small "FCC Linux" 2>/dev/null || echo "FCC Linux"
. /etc/os-release
echo "$PRETTY_NAME"
echo "Kernel:  $(uname -r) ($(uname -m))"
echo "Memory:  $(free -m | awk '/Mem/ {print $3 " MB used of " $2 " MB"}')"
echo "Python:  $(python3 --version 2>&1)"
echo "Lua:     $(lua5.4 -v 2>&1 | cut -d' ' -f1-2)"
echo "Packages: $(cat /etc/fcc/packages 2>/dev/null | wc -w) added to Alpine's base"
echo "No network in the box: files you make stay inside it while it's open."
""",
    ),
}


def build(out: Path) -> dict:
    index = read_index()
    root: dict[str, tuple[tarfile.TarInfo, bytes | None]] = {}
    base_size = unpack(fetch(*MINIROOTFS), root)
    installed = (root.get("lib/apk/db/installed") or (None, b""))[1] or b""
    have = {
        line[2:] for line in installed.decode().splitlines() if line.startswith("P:")
    }
    order = resolve(PACKAGES, index, have)
    added: list[dict[str, str | int]] = []
    for name in order:
        fields = index[name]
        url = f"{MIRROR}/{fields['repo']}/x86/{name}-{fields['V']}.apk"
        data = fetch(url)
        members = gzip_members(data)
        control = members[-2]
        expected = fields.get("C", "")
        if expected.startswith("Q1"):
            digest = base64.b64encode(hashlib.sha1(control).digest()).decode()
            if digest != expected[2:]:
                raise SystemExit(f"{name}: its checksum doesn't match Alpine's index.")
        size = unpack(zlib.decompress(members[-1], 16 + zlib.MAX_WBITS), root)
        added.append(
            {
                "name": name,
                "version": fields["V"],
                "repo": fields["repo"],
                "bytes": size,
            }
        )
    for path, (mode, text) in FCC_FILES.items():
        add_text(root, path, text, mode)
    add_text(
        root, "etc/fcc/packages", " ".join(str(item["name"]) for item in added) + "\n"
    )
    add_text(root, "etc/hostname", "fcc-linux\n")
    add_text(root, "etc/shells", "/bin/sh\n/bin/ash\n/bin/bash\n")
    if "usr/bin/python3" not in root and "usr/bin/python3.12" in root:
        add_link(root, "usr/bin/python3", "python3.12")
    out.mkdir(parents=True, exist_ok=True)
    # zstd: the kernel unpacks it several times faster than xz inside the
    # emulator, for a slightly bigger download.
    initrd = zstd.compress(cpio(root), level=19)
    with tarfile.open(fileobj=io.BytesIO(fetch(*NETBOOT))) as bundle:
        member = bundle.extractfile(KERNEL_IN_NETBOOT)
        assert member is not None
        kernel = member.read()
    (out / "fcc-linux.kernel").write_bytes(kernel)
    (out / "fcc-linux.initrd").write_bytes(initrd)
    report = {
        "name": "FCC Linux 1.0",
        "base": f"Alpine Linux {RELEASE} (x86)",
        "base_packages": sorted(have),
        "base_bytes": base_size,
        "added": added,
        "left_out": list(LEAVE_OUT),
        "kernel": {
            "from": KERNEL_IN_NETBOOT,
            "bytes": len(kernel),
            "sha256": hashlib.sha256(kernel).hexdigest(),
        },
        "initrd": {"bytes": len(initrd), "sha256": hashlib.sha256(initrd).hexdigest()},
    }
    (out / "fcc-linux.json").write_text(
        json.dumps(report, indent=1) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    report = build(parser.parse_args().out)
    print(
        f"{report['name']}: {len(report['base_packages'])} base packages + {len(report['added'])} added"
    )
    print(
        f"kernel {report['kernel']['bytes']:,} bytes, initrd {report['initrd']['bytes']:,} bytes"
    )


if __name__ == "__main__":
    sys.exit(main())
