"""DocForge Launcher - Starts the DocForge server and opens the browser dashboard."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent


def find_venv_python() -> str:
    venv_py = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        return str(venv_py)
    unix_py = ROOT_DIR / ".venv" / "bin" / "python"
    if unix_py.is_file():
        return str(unix_py)
    return sys.executable


def launch() -> None:
    py_exec = find_venv_python()
    print("=" * 65)
    print("             DOCFORGE APPLICATION LAUNCHER")
    print("=" * 65)
    print()
    print("[*] Starting DocForge Server...")

    if sys.platform.startswith("win"):
        cmd = (
            f'title DocForge - Server (:8000) && color 0a && '
            f'echo =================================================== && '
            f'echo   DOCFORGE RUNNING ON http://127.0.0.1:8000 && '
            f'echo   - Web Dashboard:  http://127.0.0.1:8000/ && '
            f'echo   - REST API:       http://127.0.0.1:8000/api && '
            f'echo   - Swagger Docs:   http://127.0.0.1:8000/docs && '
            f'echo   - Demo Login:     demo / demo123 && '
            f'echo =================================================== && '
            f'"{py_exec}" -m uvicorn docforge.api.app:app --host 127.0.0.1 --port 8000 --reload'
        )
        subprocess.Popen(["cmd.exe", "/k", cmd], cwd=str(ROOT_DIR), creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen(
            [py_exec, "-m", "uvicorn", "docforge.api.app:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
            cwd=str(ROOT_DIR),
        )

    print()
    print("=" * 65)
    print("  * Web Dashboard:  http://127.0.0.1:8000")
    print("  * REST API:       http://127.0.0.1:8000/api")
    print("  * Swagger Docs:   http://127.0.0.1:8000/docs")
    print("  * Demo Login:     demo / demo123")
    print("=" * 65)
    print()
    print("Opening browser to http://127.0.0.1:8000 in 2 seconds...")
    time.sleep(2)
    webbrowser.open("http://127.0.0.1:8000")


if __name__ == "__main__":
    launch()
