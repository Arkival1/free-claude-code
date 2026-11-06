"""Build FCC Linux 2: FCC Phone's own Linux with every language in it.

Like FCC Linux 1 (`build_fcc_linux.py`, whose checked download, signature and
unpacking code this reuses), it is Alpine Linux 3.21 for 32-bit x86, built
without running anything that was downloaded. What changes is how it reaches
the phone: the system (about 1.2 GB with C/C++, Rust, Go, Java, Node, Python,
Ruby, PHP, Perl and git) is far too big to live in memory, so

- a tiny start-up system (busybox, musl, the kernel modules for 9p and the
  network card) is the initrd; it mounts the real system over 9p (v86's
  virtio file system, tag `host9p`) and switches to it;
- the real system is a file list (`fs-*.json.gz`, v86's format, version 3) and
  packs of zstd-compressed files (`*.pack`, at most 24 MB each, named by their
  SHA-256). Each file's name in the list says where it lives
  (`<pack>-<offset>-<length>.zst`, hex; a file bigger than a pack runs on
  through the next packs), so the phone fetches a pack only when
  something in it is first used, checks its SHA-256 against the manifest, and
  keeps it;
- `fcc-linux.json` is the manifest (the phone pins its SHA-256), listing the
  kernel, the initrd, the file list and every pack with its checksum.

    uv run python scripts/linux/build_fcc_linux2.py [--out DIR]

See vendor/fcc-linux/README.md.
"""

import argparse
import base64
import gzip
import hashlib
import io
import json
import stat
import sys
import tarfile
import zlib
from compression import zstd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_fcc_linux as base

VERSION = "2.0"
NAME = f"FCC Linux {VERSION}"
OUT = base.OUT
BLOBS = base.CACHE / "blobs"
TOOLS = Path(__file__).resolve().parent / "files"
"""FCC's own commands in FCC Linux (fcc-github, fcc-net, fcc-plugin)."""
PACK_LIMIT = 24 * 1024 * 1024
ZSTD_LEVEL = 15
LANGUAGES = [
    # C and C++
    "gcc",
    "g++",
    "musl-dev",
    "binutils",
    "linux-headers",
    "pkgconf",
    "cmake",
    "gdb",
    "nasm",
    # JavaScript, Rust, Go, Java
    "nodejs",
    "npm",
    "rust",
    "cargo",
    "go",
    "openjdk8",
    # Scripting
    "ruby",
    "php83",
    "perl",
    "py3-pip",
    # Code
    "git",
]
PACKAGES = [*base.PACKAGES, *LANGUAGES]
"""Everything in FCC Linux 2: FCC Linux 1's tools plus every language."""
MODULES = ["9p", "9pnet_virtio", "virtio_pci", "ne2k-pci"]
"""Kernel modules the start-up system loads (with what they need), in order."""
LEAVE_OUT = (
    *base.LEAVE_OUT,
    "usr/lib/go/test/",
    "usr/lib/go/misc/",
    "usr/share/gtk-doc/",
)

INIT = """#!/bin/busybox sh
# FCC Linux 2 starts here: load the 9p file system and the network card,
# open the real system the phone serves over 9p, and switch to it.
B=/bin/busybox
$B mkdir -p /proc /sys /dev /newroot
$B mount -t proc proc /proc
$B mount -t sysfs sys /sys
$B mount -t devtmpfs dev /dev
for m in $($B cat /modules/order); do $B insmod /modules/$m.ko 2>/dev/null; done
if ! $B mount -t 9p host9p /newroot -o trans=virtio,version=9p2000.L,cache=loose,msize=262144; then
  echo "FCC Linux couldn't open its files."
  exec $B sh
fi
$B mount --move /dev /newroot/dev
$B mount --move /proc /newroot/proc
$B mount --move /sys /newroot/sys
exec $B switch_root /newroot /sbin/init
"""

FCC_FILES = {
    **{path: value for path, value in base.FCC_FILES.items() if path != "init"},
    "etc/fcc/boot.sh": (
        0o755,
        """#!/bin/sh
# Mounts and settings Alpine's package scripts and init would have made.
mkdir -p /dev/pts /dev/shm /tmp /run /home/fcc /root
mount -t devpts devpts /dev/pts 2>/dev/null
mount -t tmpfs tmpfs /dev/shm 2>/dev/null
mount -t tmpfs -o mode=1777 tmpfs /tmp 2>/dev/null
mount -t tmpfs tmpfs /run 2>/dev/null
hostname fcc-linux
ip link set lo up 2>/dev/null
echo 1 > /proc/sys/kernel/printk 2>/dev/null
# The network card leads only to FCC, which decides what may go out (the
# internet switch in FCC). FCC's emulator is the gateway and answers DNS
# itself, at fixed addresses.
if ip link set eth0 up 2>/dev/null; then
  ip addr add 192.168.86.100/24 dev eth0 2>/dev/null
  ip route add default via 192.168.86.1 2>/dev/null
  echo "nameserver 192.168.86.1" > /etc/resolv.conf
fi
""",
    ),
    # Package installers go through FCC: their indexes as http (FCC fetches
    # them as https, outside Linux), and their https links turned into http.
    "etc/pip.conf": (
        0o644,
        """[global]
index-url = http://pypi.org/simple/
trusted-host = pypi.org files.pythonhosted.org
break-system-packages = true
disable-pip-version-check = true
no-cache-dir = false
""",
    ),
    "root/.npmrc": (
        0o644,
        """registry=http://registry.npmjs.org/
fund=false
audit=false
update-notifier=false
""",
    ),
    "root/.cargo/config.toml": (
        0o644,
        """[source.crates-io]
replace-with = "fcc"

[source.fcc]
registry = "sparse+http://index.crates.io/"

[net]
retry = 3
""",
    ),
    "etc/profile.d/fcc-languages.sh": (
        0o644,
        """# FCC Linux 2: where each language keeps its tools and caches. Caches
# live in /root, so a kept session keeps them (Go's first build is slow).
export JAVA_HOME=/usr/lib/jvm/java-1.8-openjdk
export GOPATH=/root/go GOCACHE=/root/.cache/go-build GOTOOLCHAIN=local GOTELEMETRY=off
# Go modules (and their checksums) come through FCC, as http.
export GOPROXY=http://proxy.golang.org
export CARGO_HOME=/root/.cargo
export PATH="$PATH:$JAVA_HOME/bin:$GOPATH/bin:$CARGO_HOME/bin:/root/.local/bin"
""",
    ),
    "etc/motd": (
        0o644,
        f"""
  {NAME} (Alpine 3.21, x86) on FCC Phone
  C/C++ (gcc, g++, cmake, gdb), Rust (cargo), Go, Java 8, Node.js (npm),
  Python 3.12 (pip), Ruby, PHP, Perl, Lua, git, bash, nano, tmux, sqlite3
  Type fcc-info for what's here. Programs load the first time you use them.
  Internet: off until you switch it on in FCC (fcc-net). GitHub: fcc-github.

""",
    ),
    "etc/os-release": (
        0o644,
        f"""NAME="FCC Linux"
ID=fcc-linux
ID_LIKE=alpine
VERSION_ID={VERSION}
PRETTY_NAME="{NAME} (Alpine 3.21 base)"
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
echo "Languages:"
echo "  C/C++   $(gcc -dumpversion 2>/dev/null)   Rust  $(rustc --version 2>/dev/null | cut -d' ' -f2)"
echo "  Go      $(go version 2>/dev/null | cut -d' ' -f3)   Java  $(java -version 2>&1 | head -1 | cut -d'"' -f2)"
echo "  Node    $(node --version 2>/dev/null)   Python $(python3 --version 2>&1 | cut -d' ' -f2)"
echo "  Ruby    $(ruby -e 'print RUBY_VERSION' 2>/dev/null)   PHP  $(php -r 'echo PHP_VERSION;' 2>/dev/null)"
echo "  Perl    $(perl -e 'print substr($^V, 1)' 2>/dev/null)   Lua  $(lua5.4 -v 2>&1 | cut -d' ' -f2)"
echo "  git     $(git --version 2>/dev/null | cut -d' ' -f3)"
echo "Packages: $(cat /etc/fcc/packages 2>/dev/null | wc -w) added to Alpine's base"
""",
    ),
}


def kernel_and_modules(
    index: dict[str, dict[str, str]],
) -> tuple[bytes, str, dict[str, bytes], list[str]]:
    """The kernel, its version, and the start-up modules (unpacked) in load order,
    from Alpine's linux-lts package (checked like every package)."""
    fields = index["linux-lts"]
    data = base.fetch(f"{base.MIRROR}/{fields['repo']}/x86/linux-lts-{fields['V']}.apk")
    members = base.gzip_members(data)
    digest = base64.b64encode(hashlib.sha1(members[-2]).digest()).decode()
    if not fields.get("C", "").startswith("Q1") or digest != fields["C"][2:]:
        raise SystemExit("linux-lts: its checksum doesn't match Alpine's index.")
    data_hash = base.package_data_hash(members[-2])
    if not data_hash or hashlib.sha256(members[-1]).hexdigest() != data_hash:
        raise SystemExit("linux-lts: its files don't match its own checksum.")
    files: dict[str, bytes] = {}
    with tarfile.open(
        fileobj=io.BytesIO(zlib.decompress(members[-1], 16 + zlib.MAX_WBITS))
    ) as bundle:
        for info in bundle:
            if info.isreg() and (
                info.name == "boot/vmlinuz-lts"
                or info.name.endswith(("modules.dep", ".ko.gz"))
            ):
                handle = bundle.extractfile(info)
                files[info.name] = handle.read() if handle else b""
    dep_name = next(name for name in files if name.endswith("modules.dep"))
    folder = dep_name.rsplit("/", 1)[0]
    version = folder.rsplit("/", 1)[1]
    needs: dict[str, list[str]] = {}
    for line in files[dep_name].decode().splitlines():
        module, _, rest = line.partition(":")
        needs[module] = rest.split()
    by_name = {Path(path).name.removesuffix(".ko.gz"): path for path in needs}
    order: list[str] = []

    def visit(path: str) -> None:
        if path in order:
            return
        for dep in reversed(needs.get(path, [])):
            visit(dep)
        order.append(path)

    for name in MODULES:
        if name not in by_name:
            raise SystemExit(f"linux-lts has no {name} module.")
        visit(by_name[name])
    modules = {
        Path(path).name.removesuffix(".ko.gz"): gzip.decompress(
            files[f"{folder}/{path}"]
        )
        for path in order
    }
    return files["boot/vmlinuz-lts"], version, modules, list(modules)


def initrd(root, modules: dict[str, bytes], order: list[str]) -> bytes:
    """The start-up system: busybox, musl, the modules and /init."""
    small: dict[str, tuple[tarfile.TarInfo, bytes | None]] = {}
    for name in ("bin/busybox", "lib/ld-musl-i386.so.1"):
        info, body = root[name]
        base.add_bytes(small, name, body or b"", info.mode & 0o7777)
    for name, (info, _) in root.items():
        if name.startswith("lib/libc.musl") and info.issym():
            base.add_link(small, name, info.linkname)
    for name, body in modules.items():
        base.add_bytes(small, f"modules/{name}.ko", body)
    base.add_text(small, "modules/order", "\n".join(order) + "\n")
    base.add_text(small, "init", INIT, 0o755)
    return zstd.compress(base.cpio(small), level=19)


def blob(body: bytes) -> bytes:
    """A file's zstd form (cached by content, so rebuilds are quick)."""
    BLOBS.mkdir(parents=True, exist_ok=True)
    cached = BLOBS / f"{hashlib.sha256(body).hexdigest()}-{ZSTD_LEVEL}.zst"
    if cached.exists():
        return cached.read_bytes()
    packed = zstd.compress(body, level=ZSTD_LEVEL)
    cached.write_bytes(packed)
    return packed


def file_body(root, info: tarfile.TarInfo, body: bytes | None) -> bytes:
    """A regular file's bytes, following hard links (and links to links)."""
    for _ in range(32):
        if not info.islnk():
            return body or b""
        target = root.get(base.clean_name(info.linkname))
        if not target:
            raise SystemExit(
                f"{info.name}: a hard link to {info.linkname}, which isn't there."
            )
        info, body = target
    raise SystemExit(
        f"{info.name}: a chain of hard links too long to follow (a loop?)."
    )


def packs_and_names(
    root, owner: dict[str, str], order: list[str]
) -> tuple[list[bytes], list[list[str]], dict[str, str], int]:
    """Pack every regular file's zstd form, packages in order (the start-up
    and everyday tools first), deduplicated; returns the packs, the packages in
    each, each content's name (`<pack>-<offset>-<length>.zst`) and the bytes."""
    content: dict[str, list[str]] = {}
    for name, (info, _) in root.items():
        if info.isreg() or info.islnk():
            content.setdefault(owner.get(name, "base"), []).append(name)
    placed: dict[str, str] = {}
    packs: list[bytearray] = [bytearray()]
    who: list[list[str]] = [[]]
    names: dict[str, str] = {}
    total = 0
    for package in order:
        for name in sorted(content.get(package, [])):
            info, body = root[name]
            data = file_body(root, info, body)
            key = hashlib.sha256(data).hexdigest()
            if key not in placed:
                packed = blob(data)
                if packs[-1] and len(packs[-1]) + len(packed) > PACK_LIMIT:
                    packs.append(bytearray())
                    who.append([])
                if len(packed) > PACK_LIMIT:
                    # Too big for one pack: it runs on through packs of its
                    # own (the phone reads across them).
                    first = len(packs) - 1
                    for at in range(0, len(packed), PACK_LIMIT):
                        if at:
                            packs.append(bytearray())
                            who.append([])
                        packs[-1] += packed[at : at + PACK_LIMIT]
                        who[-1].append(package)
                    placed[key] = f"{first:x}-0-{len(packed):x}.zst"
                    packs.append(bytearray())
                    who.append([])
                else:
                    at = len(packs[-1])
                    packs[-1] += packed
                    placed[key] = f"{len(packs) - 1:x}-{at:x}-{len(packed):x}.zst"
                    if package not in who[-1]:
                        who[-1].append(package)
                total += len(data)
            names[name] = placed[key]
    if not packs[-1]:
        packs.pop()
        who.pop()
    return [bytes(pack) for pack in packs], who, names, total


def file_list(root, names: dict[str, str]) -> list:
    """The system as v86's file list (version 3): [name, size, mtime, mode,
    uid, gid, children | content name | link target]."""
    top: dict = {"kids": {}, "info": None}
    for name in sorted(root):
        info, _ = root[name]
        if not (info.isdir() or info.isreg() or info.islnk() or info.issym()):
            continue  # devices come from devtmpfs at boot
        parts = name.split("/")
        node = top
        for part in parts[:-1]:
            node = node["kids"].setdefault(part, {"kids": {}, "info": None})
        if info.isdir():
            node["kids"].setdefault(parts[-1], {"kids": {}, "info": None})["info"] = (
                info
            )
        else:
            node["kids"][parts[-1]] = {"leaf": name}

    def emit(label: str, node: dict) -> list:
        if "leaf" in node:
            path = node["leaf"]
            info, body = root[path]
            if info.issym():
                return [
                    label,
                    len(info.linkname),
                    0,
                    stat.S_IFLNK | 0o777,
                    0,
                    0,
                    info.linkname,
                ]
            size = len(file_body(root, info, body))
            return [
                label,
                size,
                0,
                stat.S_IFREG | (info.mode & 0o7777),
                info.uid,
                info.gid,
                names[path],
            ]
        info = node["info"]
        mode = stat.S_IFDIR | ((info.mode & 0o7777) if info else 0o755)
        kids = [emit(kid, node["kids"][kid]) for kid in sorted(node["kids"])]
        return [
            label,
            0,
            0,
            mode,
            info.uid if info else 0,
            info.gid if info else 0,
            kids,
        ]

    return [emit(kid, top["kids"][kid]) for kid in sorted(top["kids"])]


def build(out: Path) -> dict:
    root: dict[str, tuple[tarfile.TarInfo, bytes | None]] = {}
    owner: dict[str, str] = {}
    base_size = base.unpack(base.fetch(*base.MINIROOTFS), root, LEAVE_OUT)
    owner.update(dict.fromkeys(root, "base"))
    index = base.read_index(base.alpine_keys(root))
    installed = (root.get("lib/apk/db/installed") or (None, b""))[1] or b""
    have = {
        line[2:] for line in installed.decode().splitlines() if line.startswith("P:")
    }
    order = base.resolve(PACKAGES, index, have)
    added: list[dict[str, str | int]] = []
    for name in order:
        fields = index[name]
        data = base.fetch(
            f"{base.MIRROR}/{fields['repo']}/x86/{name}-{fields['V']}.apk"
        )
        members = base.gzip_members(data)
        control = members[-2]
        expected = fields.get("C", "")
        digest = base64.b64encode(hashlib.sha1(control).digest()).decode()
        if not expected.startswith("Q1") or digest != expected[2:]:
            raise SystemExit(f"{name}: its checksum doesn't match Alpine's index.")
        data_hash = base.package_data_hash(control)
        if not data_hash or hashlib.sha256(members[-1]).hexdigest() != data_hash:
            raise SystemExit(f"{name}: its files don't match its own checksum.")
        before = set(root)
        size = base.unpack(
            zlib.decompress(members[-1], 16 + zlib.MAX_WBITS), root, LEAVE_OUT
        )
        owner.update(dict.fromkeys(set(root) - before, name))
        added.append(
            {
                "name": name,
                "version": fields["V"],
                "repo": fields["repo"],
                "bytes": size,
            }
        )
    for path, (mode, text) in FCC_FILES.items():
        base.add_text(root, path, text, mode)
        owner[path] = "base"
    for tool in sorted(
        item
        for item in TOOLS.iterdir()
        if item.is_file() and not item.name.startswith(".")
    ):
        path = f"usr/local/bin/{tool.name}"
        base.add_text(root, path, tool.read_text(encoding="utf-8"), 0o755)
        owner[path] = "base"
    base.add_text(
        root, "etc/fcc/packages", " ".join(str(item["name"]) for item in added) + "\n"
    )
    base.add_text(root, "etc/hostname", "fcc-linux\n")
    base.add_text(root, "etc/shells", "/bin/sh\n/bin/ash\n/bin/bash\n")
    if "usr/bin/python3" not in root and "usr/bin/python3.12" in root:
        base.add_link(root, "usr/bin/python3", "python3.12")
    compiled = base.precompile_python(root)
    for path in root:
        owner.setdefault(
            path, "python3" if path.startswith("usr/lib/python3.12/") else "base"
        )

    kernel, kernel_version, modules, module_order = kernel_and_modules(index)
    start = initrd(root, modules, module_order)
    packs, who, names, used = packs_and_names(root, owner, ["base", *order])
    listing = gzip.compress(
        json.dumps(
            {"version": 3, "size": used, "fsroot": file_list(root, names)},
            separators=(",", ":"),
        ).encode(),
        mtime=0,
    )

    fs_dir = out / "fs"
    fs_dir.mkdir(parents=True, exist_ok=True)
    wanted = set()
    pack_rows = []
    pack_bytes = 0
    for number, (pack, packages) in enumerate(zip(packs, who, strict=True)):
        digest = hashlib.sha256(pack).hexdigest()
        file = f"{digest}.pack"
        wanted.add(file)
        if not (fs_dir / file).exists():
            (fs_dir / file).write_bytes(pack)
        pack_bytes += len(pack)
        pack_rows.append(
            {
                "n": number,
                "file": f"fs/{file}",
                "sha256": digest,
                "bytes": len(pack),
                "packages": packages,
            }
        )
    listing_digest = hashlib.sha256(listing).hexdigest()
    listing_file = f"fs-{listing_digest[:16]}.json.gz"
    wanted.add(listing_file)
    (fs_dir / listing_file).write_bytes(listing)
    for stale in fs_dir.iterdir():
        if stale.name not in wanted:
            stale.unlink()
    (out / "fcc-linux.kernel").write_bytes(kernel)
    (out / "fcc-linux.initrd").write_bytes(start)
    for old in ("fcc-linux.json",):
        (out / old).unlink(missing_ok=True)
    report = {
        "name": NAME,
        "version": VERSION,
        "base": f"Alpine Linux {base.RELEASE} (x86)",
        "base_packages": sorted(have),
        "base_bytes": base_size,
        "added": added,
        "left_out": list(LEAVE_OUT),
        "python_precompiled": compiled,
        "kernel": {
            "from": f"linux-lts {index['linux-lts']['V']}",
            "release": kernel_version,
            "bytes": len(kernel),
            "sha256": hashlib.sha256(kernel).hexdigest(),
            "modules": module_order,
        },
        "initrd": {"bytes": len(start), "sha256": hashlib.sha256(start).hexdigest()},
        "files": {
            "file": f"fs/{listing_file}",
            "sha256": listing_digest,
            "bytes": len(listing),
            "count": len(names),
            "used_bytes": used,
        },
        "packs": pack_rows,
        "download_bytes": pack_bytes + len(listing),
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
    print(
        f"{report['files']['count']:,} files ({report['files']['used_bytes'] / 1e6:.0f} MB) in {len(report['packs'])} packs, {report['download_bytes'] / 1e6:.0f} MB to download"
    )


if __name__ == "__main__":
    sys.exit(main())
