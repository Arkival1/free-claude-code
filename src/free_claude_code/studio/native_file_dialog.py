"""Short-lived OS dialog for choosing a model file; stdout carries only JSON.

Studio runs this in its own process so the dialog opens on the computer
running Studio, and a stuck or closed dialog never blocks the server.
"""

import json
import shutil
import subprocess
import sys

_TITLE = "Choose a model file (.gguf)"
_MAC_SCRIPT = """
try
    set chosen to choose file with prompt "Choose a model file (.gguf)"
    return POSIX path of chosen
on error messageText number errorNumber
    if errorNumber is -128 then return ""
    error messageText number errorNumber
end try
"""


def _windows() -> str | None:
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        return (
            filedialog.askopenfilename(
                parent=root,
                title=_TITLE,
                filetypes=[("Model files", "*.gguf"), ("All files", "*.*")],
            )
            or None
        )
    finally:
        root.destroy()


def _macos() -> str | None:
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", _MAC_SCRIPT], capture_output=True, check=True
    )
    return result.stdout.decode("utf-8").removesuffix("\n") or None


def _linux() -> str | None:
    if executable := shutil.which("zenity"):
        command = [
            executable,
            "--file-selection",
            f"--title={_TITLE}",
            "--file-filter=Model files | *.gguf",
            "--file-filter=All files | *",
        ]
    elif executable := shutil.which("kdialog"):
        command = [executable, "--title", _TITLE, "--getopenfilename", ".", "*.gguf"]
    else:
        raise RuntimeError("No desktop file picker is available")
    result = subprocess.run(command, capture_output=True, check=False)
    path = result.stdout.decode("utf-8").removesuffix("\n")
    if result.returncode == 0 and path:
        return path
    if result.returncode == 1:
        return None
    raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))


def main() -> int:
    try:
        if sys.platform == "win32":
            path = _windows()
        elif sys.platform == "darwin":
            path = _macos()
        else:
            path = _linux()
        print(json.dumps({"path": path}, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        print(json.dumps({"error": "unavailable"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
