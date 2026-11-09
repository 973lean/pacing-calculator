"""
Self-updater backed by GitHub Releases.

How it works
------------
1. `check_latest()` asks the GitHub API for the newest release of REPO and
   compares its tag (e.g. "v1.2.0") with the running version.
2. `download()` fetches the release's PacingCalculator.exe asset to a temp file.
3. `apply_and_restart()` writes a tiny batch script that waits for this app to
   exit, swaps the old .exe for the new one, relaunches it, and deletes itself.

Standard library only. Network calls are blocking: run them off the UI thread.
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.request

REPO = "973lean/pacing-calculator"
ASSET_NAME = "PacingCalculator.exe"
# PACING_UPDATE_API lets you point the updater at a test server
API_LATEST = os.environ.get(
    "PACING_UPDATE_API", f"https://api.github.com/repos/{REPO}/releases/latest")
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
USER_AGENT = "PacingCalculator-Updater"
TIMEOUT = 8  # seconds


def parse_version(text: str) -> tuple:
    """'v1.2.10' -> (1, 2, 10). Non-numeric parts are ignored."""
    parts = []
    for piece in text.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def is_frozen() -> bool:
    """True when running as the PyInstaller .exe (self-replacement possible)."""
    return getattr(sys, "frozen", False) and sys.platform == "win32"


def check_latest(current_version: str):
    """
    Return (version, download_url) if a newer release exists, else None.
    Raises on network / API errors so the caller can report them.
    """
    req = urllib.request.Request(API_LATEST, headers={
        "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.load(resp)

    tag = data.get("tag_name", "")
    if not tag or not is_newer(tag, current_version):
        return None
    url = next((a["browser_download_url"] for a in data.get("assets", [])
                if a.get("name") == ASSET_NAME), None)
    return tag.lstrip("vV"), url


def download(url: str, progress=None) -> str:
    """Download the new .exe to a temp file and return its path."""
    fd, path = tempfile.mkstemp(prefix="PacingCalculator-", suffix=".exe")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp, os.fdopen(fd, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    if os.path.getsize(path) < 1_000_000:  # sanity check: real build is ~12 MB
        os.remove(path)
        raise IOError("Downloaded file looks incomplete")
    return path


def apply_and_restart(new_exe: str) -> None:
    """
    Replace the running .exe with `new_exe` once this process exits, then
    relaunch it. The caller should close the app right after calling this.
    """
    current = sys.executable
    script = os.path.join(tempfile.gettempdir(), "pacing_calculator_update.cmd")
    # Retry the move for up to ~60 s: the exe stays locked until the app exits.
    with open(script, "w", encoding="utf-8") as f:
        f.write(
            "@echo off\r\n"
            "set n=0\r\n"
            ":retry\r\n"
            f'move /y "{new_exe}" "{current}" >nul 2>&1\r\n'
            "if not errorlevel 1 goto done\r\n"
            "set /a n+=1\r\n"
            "if %n% geq 60 goto end\r\n"
            "ping -n 2 127.0.0.1 >nul\r\n"
            "goto retry\r\n"
            ":done\r\n"
            f'start "" "{current}"\r\n'
            ":end\r\n"
            'del "%~f0"\r\n'
        )

    # Don't let the relaunched exe inherit this one's PyInstaller temp folder
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("_PYI") and k != "_MEIPASS2"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"

    CREATE_NO_WINDOW, DETACHED_PROCESS = 0x08000000, 0x00000008
    subprocess.Popen(["cmd", "/c", script], env=env, close_fds=True,
                     creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS)
